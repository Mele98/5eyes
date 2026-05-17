"""Nelson-Siegel (1987) Yield-Curve-Modell.

Parametrische Form fuer die Zinsstrukturkurve:

    y(tau) = beta0
           + beta1 * ((1 - exp(-lambda*tau)) / (lambda*tau))
           + beta2 * (((1 - exp(-lambda*tau)) / (lambda*tau)) - exp(-lambda*tau))

Interpretation der Parameter:
    beta0   = Long-Term Rate (Level): y(inf) -> beta0
    beta1   = Slope: y(0+) -> beta0 + beta1, y(inf) -> beta0 (Slope = beta1)
    beta2   = Curvature (Bauchigkeit, mittlere Maturitaeten)
    lambda  = Decay-Parameter (typisch 0.5-0.7 fuer Jahre)
              Steuert wo der Knick liegt: peak curvature ~ ln(2)/lambda

Spec: docs/planning/2026-05-17-sprint-6-nelson-siegel.md
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class NelsonSiegelCurve:
    """Nelson-Siegel Yield-Curve.

    Alle Yields werden in **bps** (1 bps = 0.01%) zurueckgegeben damit es
    zu den CMA-Konventionen passt. Internally rechnet alles in float (1.0 = 100%).

    Beispiel:
        >>> curve = NelsonSiegelCurve(beta0_bps=400, beta1_bps=-100, beta2_bps=50, lambda_=0.6)
        >>> curve.yield_at(1.0)  # 1-Jahr-Yield in bps
        ...
        >>> curve.yield_at(np.array([1, 5, 10, 30]))  # Vektor-Eingabe
        ...
    """

    beta0_bps: float
    """Long-Term Rate (Level) in bps. y(inf) -> beta0."""

    beta1_bps: float
    """Slope in bps. y(0+) -> beta0 + beta1. Negativ = ansteigend."""

    beta2_bps: float
    """Curvature in bps. Bauchigkeit bei mittleren Maturitaeten."""

    lambda_: float
    """Decay-Parameter. Typisch 0.5-0.7 fuer Jahre. Muss > 0 sein."""

    def __post_init__(self) -> None:
        if self.lambda_ <= 0:
            raise ValueError(f"lambda_ must be > 0, got {self.lambda_}")

    def yield_at(self, maturity_years):
        """Returns Yield in bps fuer Maturity(s) in Jahren.

        maturity_years: float oder ndarray. Muss > 0 sein.
        Returns: gleicher Typ wie input (float oder ndarray).
        """
        tau = np.asarray(maturity_years, dtype=np.float64)
        if np.any(tau <= 0):
            raise ValueError("maturity_years must be > 0")

        lam_tau = self.lambda_ * tau
        # Factor1: (1 - exp(-lam*tau)) / (lam*tau)
        # Numerisch stabil auch fuer kleine lam_tau
        with np.errstate(divide="ignore", invalid="ignore"):
            f1 = np.where(
                lam_tau > 1e-10,
                (1.0 - np.exp(-lam_tau)) / lam_tau,
                1.0 - 0.5 * lam_tau,  # Taylor-Approximation fuer tau -> 0
            )
        # Factor2: Factor1 - exp(-lam*tau)
        f2 = f1 - np.exp(-lam_tau)

        result = self.beta0_bps + self.beta1_bps * f1 + self.beta2_bps * f2
        # Return same shape as input
        if np.isscalar(maturity_years):
            return float(result)
        return result

    def forward_rate(self, t1: float, t2: float) -> float:
        """Returns Forward-Rate von t1 bis t2 in bps (annualisiert).

        Formel: f(t1,t2) = (y(t2)*t2 - y(t1)*t1) / (t2 - t1)
        Implizite Annahme: continuous compounding.
        """
        if t1 < 0 or t2 <= t1:
            raise ValueError(f"Require 0 <= t1 < t2, got t1={t1}, t2={t2}")
        if t1 == 0:
            return float(self.yield_at(t2))
        y1 = float(self.yield_at(t1))
        y2 = float(self.yield_at(t2))
        return (y2 * t2 - y1 * t1) / (t2 - t1)

    def short_rate_bps(self) -> float:
        """Short-Rate (instantaner Spot): y(0+) = beta0 + beta1."""
        return float(self.beta0_bps + self.beta1_bps)

    def long_rate_bps(self) -> float:
        """Long-Rate (asymptotisch): y(inf) = beta0."""
        return float(self.beta0_bps)

    def to_dict(self) -> dict:
        return {
            "beta0_bps": float(self.beta0_bps),
            "beta1_bps": float(self.beta1_bps),
            "beta2_bps": float(self.beta2_bps),
            "lambda_": float(self.lambda_),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "NelsonSiegelCurve":
        return cls(
            beta0_bps=float(d["beta0_bps"]),
            beta1_bps=float(d["beta1_bps"]),
            beta2_bps=float(d["beta2_bps"]),
            lambda_=float(d["lambda_"]),
        )


def fit_nelson_siegel(
    maturities_years: np.ndarray,
    yields_bps: np.ndarray,
    *,
    lambda_init: float = 0.6,
    lambda_fixed: bool = False,
) -> NelsonSiegelCurve:
    """Kalibriert NelsonSiegelCurve auf Markt-Yields (Least-Squares).

    Args:
        maturities_years: shape (N,) Maturities in Jahren (> 0)
        yields_bps: shape (N,) beobachtete Yields in bps
        lambda_init: Start-Wert fuer Decay-Parameter
        lambda_fixed: wenn True, lambda wird nicht optimiert
            (typisch True fuer Vergleichbarkeit ueber Zeit)

    Returns:
        NelsonSiegelCurve mit besten Parametern.

    Implementation: linear LS fuer (beta0, beta1, beta2) bei festem lambda,
    dann Outer-Loop ueber lambda wenn lambda_fixed=False (1D-Search).
    """
    from scipy.optimize import minimize_scalar

    maturities = np.asarray(maturities_years, dtype=np.float64)
    targets = np.asarray(yields_bps, dtype=np.float64)
    if maturities.shape != targets.shape:
        raise ValueError(
            f"shape mismatch: maturities {maturities.shape} vs yields {targets.shape}"
        )
    if maturities.size < 3:
        raise ValueError(f"Need >= 3 data points, got {maturities.size}")
    if (maturities <= 0).any():
        raise ValueError("maturities must be > 0")

    def _fit_betas_for_lambda(lam: float) -> tuple[float, np.ndarray]:
        """Linear-LS fuer (beta0, beta1, beta2) bei gegebenem lambda.
        Returns (rss, betas)."""
        lam_tau = lam * maturities
        with np.errstate(divide="ignore", invalid="ignore"):
            f1 = np.where(
                lam_tau > 1e-10,
                (1.0 - np.exp(-lam_tau)) / lam_tau,
                1.0 - 0.5 * lam_tau,
            )
        f2 = f1 - np.exp(-lam_tau)
        # Design matrix: [1, f1, f2]
        X = np.column_stack([np.ones_like(maturities), f1, f2])
        betas, residuals, rank, _ = np.linalg.lstsq(X, targets, rcond=None)
        predicted = X @ betas
        rss = float(np.sum((targets - predicted) ** 2))
        return rss, betas

    if lambda_fixed:
        rss, betas = _fit_betas_for_lambda(lambda_init)
        return NelsonSiegelCurve(
            beta0_bps=float(betas[0]),
            beta1_bps=float(betas[1]),
            beta2_bps=float(betas[2]),
            lambda_=float(lambda_init),
        )

    # Outer-Optimization: 1D search ueber lambda
    def _obj(lam: float) -> float:
        if lam <= 0.05 or lam > 5.0:
            return 1e20
        rss, _ = _fit_betas_for_lambda(lam)
        return rss

    result = minimize_scalar(
        _obj, bracket=(0.1, lambda_init, 2.0), method="brent", options={"xtol": 1e-6}
    )
    best_lambda = float(result.x)
    _, betas = _fit_betas_for_lambda(best_lambda)

    return NelsonSiegelCurve(
        beta0_bps=float(betas[0]),
        beta1_bps=float(betas[1]),
        beta2_bps=float(betas[2]),
        lambda_=best_lambda,
    )
