"""Sprint U-100 (2026-06-05): Nelson-Siegel-Kalibrierung mit CHF-Swap-Kurve.

Liefert eine ready-to-use Default-Kalibrierung der NS-Yield-Kurve auf
Basis annaehernder CHF-Marktdaten per Ende-2024. Diese Werte sind als
**Approximation** zu verstehen — fuer FINMA-Compliance-relevante
Renditeerwartungen sollte der Berater die SNB/ECB-Roh-Daten quartalsweise
neu kalibrieren (siehe `calibrate_from_market_yields`).

Pre-U-100 hatte die NS-Curve zwar Code (services/rates/nelson_siegel.py)
und CMA-Felder (bonds_ns_beta0_bps/...), aber **keine** Default-
Kalibrierung — die CMA-Werte mussten per Hand gesetzt werden, was die
Engine de-facto auf die fixed bonds_*_return_bps-Fallback-Werte
zurueckwarf (siehe _compute_bonds_return_from_nelson_siegel).

Quellen-Hinweis:
  Die hier hinterlegten CHF-Swap-Yields per 2024-12-31 sind eine
  Approximation aus oeffentlich zugaenglichen SNB-Bulletins. Sie sind
  **bewusst konservativ** (untere Bandbreite, [[feedback_conservative_values]])
  und sollten quartalsweise via `calibrate_from_market_yields()` aktualisiert
  werden, sobald aktuelle SNB-Aggregate verfuegbar sind.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from services.rates.nelson_siegel import NelsonSiegelCurve, fit_nelson_siegel


CALIBRATION_DATE_ISO = "2024-12-31"
"""Stichtag der hier hinterlegten CHF-Swap-Yields."""


# Approximation CHF-Swap-Yields per 2024-12-31 (in bps).
# Quelle-Hinweis siehe Doc-String. Berater sollte quartalsweise updaten.
# Konservative Variante: bei Bandbreiten der oeffentlichen Daten den
# **tieferen** Wert genommen (Ruhestandsgelder-Prinzip).
CHF_SWAP_CURVE_DEC_2024_BPS: dict[float, int] = {
    0.25: 50,   # 3M
    0.5: 45,    # 6M
    1.0: 35,    # 1Y
    2.0: 35,    # 2Y
    3.0: 40,    # 3Y
    5.0: 50,    # 5Y
    7.0: 55,    # 7Y
    10.0: 65,   # 10Y
    15.0: 75,   # 15Y
    20.0: 80,   # 20Y
    30.0: 85,   # 30Y
}


@dataclass(frozen=True)
class CalibrationResult:
    """Ergebnis einer NS-Kalibrierung mit Diagnostik."""

    curve: NelsonSiegelCurve
    calibration_date_iso: str
    """Stichtag der zugrundeliegenden Markt-Daten."""
    rss_bps2: float
    """Residual Sum of Squares (in bps^2)."""
    max_residual_bps: float
    """Groesster Abstand Curve vs Markt-Yield (in bps)."""
    n_points: int
    """Anzahl Maturitaeten in der Kalibrierung."""

    def to_dict(self) -> dict:
        return {
            "curve": self.curve.to_dict(),
            "calibration_date_iso": self.calibration_date_iso,
            "rss_bps2": self.rss_bps2,
            "max_residual_bps": self.max_residual_bps,
            "n_points": self.n_points,
        }


def calibrate_from_market_yields(
    yields_by_maturity_bps: dict[float, int],
    *,
    calibration_date_iso: str,
    lambda_init: float = 0.6,
    lambda_fixed: bool = False,
) -> CalibrationResult:
    """Kalibriert die NS-Curve auf gegebenen Markt-Daten.

    Args:
        yields_by_maturity_bps: {maturity_years: yield_bps}, mindestens 3 Punkte
        calibration_date_iso: ISO-Datum der Markt-Daten (z.B. '2025-03-31')
        lambda_init: Start-Wert fuer Decay-Parameter
        lambda_fixed: True = lambda nicht optimieren (Vergleichbarkeit ueber Zeit)

    Returns:
        CalibrationResult mit Curve + Diagnostik.

    Raises:
        ValueError: bei < 3 Punkten oder ungueltigen Maturitaeten.
    """
    if len(yields_by_maturity_bps) < 3:
        raise ValueError(
            f"Mindestens 3 Markt-Yields noetig fuer NS-Kalibrierung, "
            f"erhalten: {len(yields_by_maturity_bps)}"
        )
    items = sorted(yields_by_maturity_bps.items())
    maturities = np.array([m for m, _ in items], dtype=np.float64)
    yields = np.array([y for _, y in items], dtype=np.float64)

    curve = fit_nelson_siegel(
        maturities_years=maturities,
        yields_bps=yields,
        lambda_init=lambda_init,
        lambda_fixed=lambda_fixed,
    )

    predicted = np.array([curve.yield_at(float(m)) for m in maturities])
    residuals = yields - predicted
    rss = float(np.sum(residuals ** 2))
    max_resid = float(np.max(np.abs(residuals)))

    return CalibrationResult(
        curve=curve,
        calibration_date_iso=calibration_date_iso,
        rss_bps2=rss,
        max_residual_bps=max_resid,
        n_points=len(items),
    )


def get_default_chf_2024_calibration() -> CalibrationResult:
    """Liefert die hier hinterlegte CHF-2024 Default-Kalibrierung.

    Convenience-Wrapper um calibrate_from_market_yields mit dem statischen
    CHF_SWAP_CURVE_DEC_2024_BPS-Dict. Wird vom apply_to_cma-Helper genutzt
    falls der Berater nichts Eigenes liefert.
    """
    return calibrate_from_market_yields(
        CHF_SWAP_CURVE_DEC_2024_BPS,
        calibration_date_iso=CALIBRATION_DATE_ISO,
        lambda_init=0.6,
        lambda_fixed=False,
    )


def apply_to_cma(cma, *, calibration: CalibrationResult | None = None) -> dict:
    """Setzt die 4 NS-Felder auf der CMA-Instanz aus einer Kalibrierung.

    Args:
        cma: CapitalMarketAssumption-Instanz (muss bonds_ns_*-Felder haben)
        calibration: optional, default = get_default_chf_2024_calibration()

    Returns:
        Dict mit den geschriebenen Werten zur Audit-Spur.
    """
    cal = calibration or get_default_chf_2024_calibration()
    curve = cal.curve
    # lambda_ wird als x100-Integer persistiert (siehe scenario_engine)
    lambda_x100 = int(round(curve.lambda_ * 100))
    payload = {
        "bonds_ns_beta0_bps": int(round(curve.beta0_bps)),
        "bonds_ns_beta1_bps": int(round(curve.beta1_bps)),
        "bonds_ns_beta2_bps": int(round(curve.beta2_bps)),
        "bonds_ns_lambda_x100": lambda_x100,
    }
    for field, value in payload.items():
        setattr(cma, field, value)
    return {
        "applied": payload,
        "calibration_date_iso": cal.calibration_date_iso,
        "rss_bps2": cal.rss_bps2,
        "max_residual_bps": cal.max_residual_bps,
        "n_points": cal.n_points,
    }
