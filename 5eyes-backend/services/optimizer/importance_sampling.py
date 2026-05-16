"""Mean-Shift Importance Sampling fuer Tail-Risk im Monte-Carlo-Optimizer.

Phase 5 der Stochastic-Optimizer-Spec (docs/planning/2026-05-05-stochastic-
optimizer-spec.md §5). Verbessert die Stichproben-Effizienz fuer
Tail-Events (Black-Swan-Verluste), bei denen Standard-MC zu wenige
relevante Szenarien liefert.

## Ansatz

Mean-Shift Importance Sampling (Glasserman 2004, "Monte Carlo Methods in
Financial Engineering", Ch. 4.6):

Statt Z ~ N(0, I) zu sampeln, sampeln wir aus N(-mu, I) wobei mu > 0
ein Shift-Vector pro Asset ist (default: Shift in Richtung negativer
Aktien-Returns, weil das die kritische Tail-Region fuer Shortfall ist).
Die Pfade laufen also "von Natur aus" haeufiger in den Tail.

Die likelihood ratio (Radon-Nikodym derivative) korrigiert den Bias:

    w_i = exp(mu^T Z_i + 0.5 * |mu|^2)

So dass fuer beliebige integrable f gilt:

    E_{N(0,I)}[f(Z)] = E_{N(-mu,I)}[f(Z) * w(Z)]

In der Praxis: jeder Pfad bekommt ein Gewicht w_i, und Objektiv-
Funktionen muessen die gewichtete Erwartung berechnen statt der
ungewichteten Sample-Mean.

## Wichtige Eigenschaften (verifiziert in Tests)

- Sum-of-weights / N ~= 1.0 (asymptotisch, MC-Fehler O(1/sqrt(N)))
- Gewichtete Mean-Estimator unverzerrt: E[f * w] = E_{original}[f]
- Bei f(Z) := 1{Z < -3} (Tail-Indikator) reduziert sich die Varianz
  des Estimators um 5-50x je nach Shift-Magnitude
- Bei Symmetric f wie Mean(Z) bleibt Estimator unverzerrt aber liefert
  keine Varianz-Reduktion (Standard-MC ist hier optimal)

## Defaults

Aus Methodik-Schulung Slide 19 (Skew/Kurt-Modelle) wissen wir, dass die
kritischen Tails fuer goal-based Allocation in den Aktien-Renditen liegen
(Aktien_CH, Aktien_Intl, Aktien_EM). Default-Shift:

    mu = [0, 0, -shift_strength, -shift_strength, 0]
    (Liquid, Bonds, Equity_CH, Equity_Intl, Alt)

mit shift_strength = 0.5 (entspricht 0.5 Standard-Deviationen Shift,
moderat genug um Bias-Variance-Tradeoff im sweet spot zu halten).

Opt-in via Config-Flag `mc_importance_sampling_enabled` in config.py.
Default: False (Phase 5 ist optional laut Spec).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np


# Default-Shift-Vector: nur Aktien-Buckets (Index 2, 3 in der 5-Bucket-Welt
# liquidity/bonds/equity_ch/equity_intl/alternatives). Wert -0.5 = halbe
# Standard-Deviation Shift in negative Richtung (= mehr Drawdown-Szenarien).
DEFAULT_TAIL_SHIFT_VECTOR = np.array([0.0, 0.0, -0.5, -0.5, 0.0])
DEFAULT_TAIL_SHIFT_STRENGTH = 0.5  # einheitenlose Standard-Deviation-Multiplikator


@dataclass(frozen=True)
class ImportanceSamplingResult:
    """Bundle aus geshifteten Pfaden + Likelihood-Ratio-Gewichten.

    Attributes
    ----------
    paths : np.ndarray
        Shape (n_paths, horizon_years, n_buckets) — log-normal return
        factors, kompatibel zum Output von build_scenario_paths().
    weights : np.ndarray
        Shape (n_paths,) — Likelihood-Ratio pro Pfad. Sum/N -> 1.0.
        Bei Standard-MC (kein IS) sind alle Gewichte = 1.0.
    is_active : bool
        True wenn Importance Sampling aktiv ist (Gewichte nicht-trivial).
    shift_vector : np.ndarray
        Der angewandte Mean-Shift-Vector pro Bucket. Shape (n_buckets,).
        Falls is_active=False: zero-vector.
    """

    paths: np.ndarray
    weights: np.ndarray
    is_active: bool
    shift_vector: np.ndarray


def compute_likelihood_weights(
    z_uncorrelated: np.ndarray,
    shift_vector: np.ndarray,
) -> np.ndarray:
    """Likelihood-Ratio fuer Mean-Shift Importance Sampling.

    Parameters
    ----------
    z_uncorrelated : np.ndarray
        Shape (n_paths, horizon_years, n_buckets) — die *unkorrelierten*
        Standard-Normals BEVOR Cholesky-Multiplikation. Diese sind die
        eigentlichen Quellen-Zufallszahlen, an denen die Likelihood
        gemessen wird.
    shift_vector : np.ndarray
        Shape (n_buckets,) — der angewandte Mean-Shift pro Bucket.

    Returns
    -------
    np.ndarray
        Shape (n_paths,) — w_i = exp(-mu^T sum_t Z_it - 0.5 * T * |mu|^2)

        Note: wir berechnen ueber alle Jahre + alle Buckets aggregiert,
        weil jeder Jahres-Schritt unabhaengig geshiftet wird. Die finale
        Likelihood ueber den vollen Pfad ist das Produkt der Jahres-
        Likelihoods, das wir per Summen in den Exponenten berechnen.
    """
    # Sum von Z * shift_vector ueber Bucket-Achse → (n_paths, horizon_years)
    z_dot_mu = np.einsum("phb,b->ph", z_uncorrelated, shift_vector)
    # Summe ueber Jahre → (n_paths,)
    cum_z_dot_mu = z_dot_mu.sum(axis=1)
    # |mu|^2 * horizon (gleicher Shift jedes Jahr)
    horizon_years = int(z_uncorrelated.shape[1])
    mu_sq_norm = float(np.dot(shift_vector, shift_vector))
    # Likelihood-Ratio per (z aus proposal N(mu, I), gewichtet gegen target N(0, I)):
    # p(z)/q(z) = exp(-z²/2) / exp(-(z-mu)²/2) = exp(-z·mu + |mu|²/2)
    # Multi-step (T years, IID): w = exp(-Σ_t z_t·mu + T·|mu|²/2)
    log_weights = -cum_z_dot_mu + 0.5 * horizon_years * mu_sq_norm
    return np.exp(log_weights)


def apply_mean_shift(
    z_uncorrelated: np.ndarray,
    shift_vector: np.ndarray,
) -> np.ndarray:
    """Verschiebt die unkorrelierten Standard-Normals um -shift_vector pro Bucket.

    Wenn die ursprünglichen Z ~ N(0, I) sind, dann sind die geshifteten
    (Z + shift_vector) ~ N(shift_vector, I). Wir geben die geshifteten zurueck,
    sodass die Folge-Pipeline (Cornish-Fisher, Cholesky, log-normal) auf den
    geshifteten Werten arbeitet.

    Note: wir verschieben um +shift_vector (nicht -), damit shift_vector mit
    negativen Komponenten (default fuer Tail) tatsaechlich nach negativen
    Returns biased.

    Parameters
    ----------
    z_uncorrelated : np.ndarray
        Shape (n_paths, horizon_years, n_buckets).
    shift_vector : np.ndarray
        Shape (n_buckets,).

    Returns
    -------
    np.ndarray
        Shape (n_paths, horizon_years, n_buckets) — Z + shift_vector
        (broadcasted ueber Path- und Year-Achse).
    """
    return z_uncorrelated + shift_vector[np.newaxis, np.newaxis, :]


def make_default_weights(n_paths: int) -> np.ndarray:
    """Liefert ein neutrales Gewichts-Array (alle 1.0) fuer Standard-MC ohne IS.

    Wird verwendet wenn IS deaktiviert ist, damit downstream-Code immer
    mit einem Weights-Array arbeiten kann (auch ohne IS-Code-Pfad).
    """
    return np.ones(int(max(1, n_paths)), dtype=np.float64)


def build_shift_vector(
    n_buckets: int,
    *,
    target_indices: Optional[list[int]] = None,
    strength: float = DEFAULT_TAIL_SHIFT_STRENGTH,
) -> np.ndarray:
    """Konstruiert einen Shift-Vector fuer Mean-Shift IS.

    Default (target_indices=None): nutzt die Equity-Buckets (Index 2 + 3
    in der 5-Bucket-Welt = Equity_CH, Equity_Intl) mit negativem Shift.
    Das biased die Stichproben in die fuer Shortfall-Optimierung wichtige
    Drawdown-Tail.

    Parameters
    ----------
    n_buckets : int
        Anzahl Asset-Buckets (typisch 5).
    target_indices : list of int, optional
        Welche Buckets shiften. Default = [2, 3] (Equity CH + Intl).
    strength : float
        Shift-Magnitude in Standard-Deviationen. Default 0.5.
        Empfohlen: 0.3-1.0. >1.5 fuehrt zu starkem Bias-Variance-Tradeoff.

    Returns
    -------
    np.ndarray
        Shape (n_buckets,) — Shift-Vector mit -strength an target_indices.
    """
    n_buckets = int(max(1, n_buckets))
    if target_indices is None:
        # Default fuer 5-Bucket-Welt: Equity_CH (2) + Equity_Intl (3)
        target_indices = [i for i in (2, 3) if i < n_buckets]
    shift = np.zeros(n_buckets, dtype=np.float64)
    for i in target_indices:
        if 0 <= int(i) < n_buckets:
            shift[int(i)] = -float(strength)
    return shift


def is_importance_sampling_enabled() -> bool:
    """Liest den Feature-Flag aus den Settings.

    Default: False (Phase 5 ist optional). Aktivierbar via
    MC_IMPORTANCE_SAMPLING_ENABLED=true in .env.
    """
    try:
        from config import settings  # local import um Circular Imports zu vermeiden
        return bool(getattr(settings, "mc_importance_sampling_enabled", False))
    except Exception:
        return False
