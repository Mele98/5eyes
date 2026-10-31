"""Sprint U-100 (2026-06-05): Tests fuer Nelson-Siegel CHF-2024 Kalibrierung.

Verifiziert:
  - Calibration-Helper liefert sinnvolle Curve fuer die hinterlegten
    CHF-Swap-Yields (Default-Kalibrierung)
  - calibrate_from_market_yields ist robust gegen ungueltige Inputs
  - apply_to_cma schreibt korrekt 4 NS-Felder auf CMA-Instanz
  - Roundtrip funktioniert (Kalibrierung -> CMA -> NelsonSiegelCurve
    rekonstruiert mit kleiner Toleranz)
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for path in (BACKEND_ROOT, TESTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from services.rates.nelson_siegel import NelsonSiegelCurve
from services.rates.ns_calibration_2024 import (
    CALIBRATION_DATE_ISO,
    CHF_SWAP_CURVE_DEC_2024_BPS,
    CalibrationResult,
    apply_to_cma,
    calibrate_from_market_yields,
    get_default_chf_2024_calibration,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

def test_calibration_date_is_2024_year_end():
    assert CALIBRATION_DATE_ISO.startswith("2024-")
    assert CALIBRATION_DATE_ISO == "2024-12-31"


def test_chf_swap_curve_has_at_least_8_maturities():
    """Vernuenftige Kalibrierungs-Grundlage: typischerweise 8+ Punkte
    von 3M bis 30Y."""
    assert len(CHF_SWAP_CURVE_DEC_2024_BPS) >= 8
    maturities = sorted(CHF_SWAP_CURVE_DEC_2024_BPS.keys())
    assert maturities[0] <= 1.0  # mindestens 1Y-Kurzteil vorhanden
    assert maturities[-1] >= 20.0  # mindestens 20Y-Langteil vorhanden


def test_chf_swap_curve_values_in_realistic_bps_range():
    """CHF-Yields per Ende-2024 liegen typisch zwischen 30 und 100 bps."""
    for maturity, y_bps in CHF_SWAP_CURVE_DEC_2024_BPS.items():
        assert 0 <= y_bps <= 200, f"Maturity {maturity}: yield {y_bps} bps unrealistisch"


# ---------------------------------------------------------------------------
# calibrate_from_market_yields
# ---------------------------------------------------------------------------

def test_calibrate_with_too_few_points_raises():
    with pytest.raises(ValueError, match="Mindestens 3"):
        calibrate_from_market_yields(
            {1.0: 35, 5.0: 50},
            calibration_date_iso="2024-12-31",
        )


def test_calibrate_returns_curve_and_diagnostics():
    result = calibrate_from_market_yields(
        CHF_SWAP_CURVE_DEC_2024_BPS,
        calibration_date_iso="2024-12-31",
    )
    assert isinstance(result, CalibrationResult)
    assert isinstance(result.curve, NelsonSiegelCurve)
    assert result.calibration_date_iso == "2024-12-31"
    assert result.n_points == len(CHF_SWAP_CURVE_DEC_2024_BPS)
    assert result.rss_bps2 >= 0
    assert result.max_residual_bps >= 0


def test_calibrate_fit_quality_default_chf_2024():
    """Bei realistischen CHF-Daten sollte NS gut passen (max Resid < 15 bps)."""
    result = get_default_chf_2024_calibration()
    assert result.max_residual_bps < 15, (
        f"Fit zu schlecht: max_residual_bps={result.max_residual_bps}"
    )


def test_curve_lambda_in_realistic_range():
    """Lambda fuer Jahres-Daten typisch 0.05-2.0."""
    result = get_default_chf_2024_calibration()
    assert 0.05 < result.curve.lambda_ < 5.0


def test_curve_beta0_positive_long_term_rate():
    """Long-Term-Rate (beta0) sollte positiv sein bei der 2024-Kurve."""
    result = get_default_chf_2024_calibration()
    assert result.curve.beta0_bps > 0


def test_curve_predicts_realistic_5y_yield():
    """5Y-Yield aus NS-Curve muss nahe am Markt-Wert liegen."""
    result = get_default_chf_2024_calibration()
    predicted_5y = result.curve.yield_at(5.0)
    market_5y = CHF_SWAP_CURVE_DEC_2024_BPS[5.0]
    assert abs(predicted_5y - market_5y) < 15


def test_calibrate_with_lambda_fixed_does_not_optimize():
    """Mit lambda_fixed=True bleibt lambda = lambda_init."""
    result = calibrate_from_market_yields(
        CHF_SWAP_CURVE_DEC_2024_BPS,
        calibration_date_iso="2024-12-31",
        lambda_init=0.5,
        lambda_fixed=True,
    )
    assert result.curve.lambda_ == 0.5


# ---------------------------------------------------------------------------
# apply_to_cma
# ---------------------------------------------------------------------------

def test_apply_to_cma_sets_4_fields():
    """apply_to_cma schreibt bonds_ns_beta0/1/2_bps + bonds_ns_lambda_x100."""
    cma_stub = SimpleNamespace(
        bonds_ns_beta0_bps=None,
        bonds_ns_beta1_bps=None,
        bonds_ns_beta2_bps=None,
        bonds_ns_lambda_x100=None,
    )
    audit = apply_to_cma(cma_stub)
    assert isinstance(cma_stub.bonds_ns_beta0_bps, int)
    assert isinstance(cma_stub.bonds_ns_beta1_bps, int)
    assert isinstance(cma_stub.bonds_ns_beta2_bps, int)
    assert isinstance(cma_stub.bonds_ns_lambda_x100, int)
    assert cma_stub.bonds_ns_lambda_x100 > 0
    assert audit["calibration_date_iso"] == "2024-12-31"


def test_apply_to_cma_returns_audit_dict():
    cma_stub = SimpleNamespace(
        bonds_ns_beta0_bps=None, bonds_ns_beta1_bps=None,
        bonds_ns_beta2_bps=None, bonds_ns_lambda_x100=None,
    )
    audit = apply_to_cma(cma_stub)
    assert "applied" in audit
    assert "rss_bps2" in audit
    assert "max_residual_bps" in audit
    assert audit["n_points"] == len(CHF_SWAP_CURVE_DEC_2024_BPS)
    assert audit["applied"]["bonds_ns_beta0_bps"] == cma_stub.bonds_ns_beta0_bps


def test_apply_to_cma_with_custom_calibration():
    """Custom CalibrationResult wird statt Default verwendet."""
    custom = calibrate_from_market_yields(
        {1.0: 100, 5.0: 150, 10.0: 200},
        calibration_date_iso="2025-03-31",
        lambda_fixed=True,  # bei monotonen Kurven konvergiert der Brent-Bracket nicht
    )
    cma_stub = SimpleNamespace(
        bonds_ns_beta0_bps=None, bonds_ns_beta1_bps=None,
        bonds_ns_beta2_bps=None, bonds_ns_lambda_x100=None,
    )
    audit = apply_to_cma(cma_stub, calibration=custom)
    assert audit["calibration_date_iso"] == "2025-03-31"
    # Default-Calibration haette deutlich kleinere beta0
    assert cma_stub.bonds_ns_beta0_bps > 50


# ---------------------------------------------------------------------------
# Roundtrip: CMA-Werte koennen wieder als NelsonSiegelCurve rekonstruiert werden
# ---------------------------------------------------------------------------

def test_roundtrip_cma_to_curve():
    """Apply -> Read-back -> Curve sollte selbe Yields liefern."""
    cma_stub = SimpleNamespace(
        bonds_ns_beta0_bps=None, bonds_ns_beta1_bps=None,
        bonds_ns_beta2_bps=None, bonds_ns_lambda_x100=None,
    )
    apply_to_cma(cma_stub)
    reconstructed = NelsonSiegelCurve(
        beta0_bps=float(cma_stub.bonds_ns_beta0_bps),
        beta1_bps=float(cma_stub.bonds_ns_beta1_bps),
        beta2_bps=float(cma_stub.bonds_ns_beta2_bps),
        lambda_=float(cma_stub.bonds_ns_lambda_x100) / 100.0,
    )
    # 5Y-Yield via rekonstruierter Curve <-> direkter Kalibrierungs-Wert:
    # Toleranz <= 2 bps (Rundungsverlust der x100-Lambda-Speicherung)
    direct = get_default_chf_2024_calibration().curve
    assert abs(reconstructed.yield_at(5.0) - direct.yield_at(5.0)) < 2
    assert abs(reconstructed.yield_at(10.0) - direct.yield_at(10.0)) < 2


# ---------------------------------------------------------------------------
# to_dict / CalibrationResult Serialisierung
# ---------------------------------------------------------------------------

def test_calibration_result_to_dict_serializable():
    result = get_default_chf_2024_calibration()
    d = result.to_dict()
    assert set(d.keys()) == {
        "curve", "calibration_date_iso", "rss_bps2", "max_residual_bps", "n_points",
    }
    assert set(d["curve"].keys()) == {"beta0_bps", "beta1_bps", "beta2_bps", "lambda_"}
