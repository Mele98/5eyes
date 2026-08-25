"""Nelson-Siegel Curve Tests.

Spec: docs/planning/2026-05-17-sprint-6-nelson-siegel.md
"""
from __future__ import annotations

import numpy as np
import pytest

from services.rates.nelson_siegel import NelsonSiegelCurve, fit_nelson_siegel


def test_lambda_must_be_positive():
    with pytest.raises(ValueError, match="lambda_"):
        NelsonSiegelCurve(beta0_bps=400, beta1_bps=-100, beta2_bps=50, lambda_=0)


def test_short_rate_is_beta0_plus_beta1():
    curve = NelsonSiegelCurve(beta0_bps=400, beta1_bps=-150, beta2_bps=0, lambda_=0.6)
    assert curve.short_rate_bps() == 400 - 150


def test_long_rate_is_beta0():
    curve = NelsonSiegelCurve(beta0_bps=400, beta1_bps=-150, beta2_bps=50, lambda_=0.6)
    assert curve.long_rate_bps() == 400


def test_yield_at_zero_plus_approaches_short_rate():
    """y(0+) -> beta0 + beta1. Wir nehmen sehr kleine Maturity."""
    curve = NelsonSiegelCurve(beta0_bps=400, beta1_bps=-150, beta2_bps=50, lambda_=0.6)
    y = curve.yield_at(0.001)
    expected = curve.short_rate_bps()
    # beta2-term: f2 = f1 - exp(-lam*tau); fuer tau->0: f2 -> 1 - 1 = 0
    # So y(0+) -> beta0 + beta1 * 1 + beta2 * 0 = beta0 + beta1 = short rate
    assert abs(y - expected) < 5.0  # < 5 bps Toleranz


def test_yield_at_infinity_approaches_long_rate():
    """y(tau)->beta0 fuer tau gross."""
    curve = NelsonSiegelCurve(beta0_bps=400, beta1_bps=-150, beta2_bps=50, lambda_=0.6)
    y = curve.yield_at(100.0)
    assert abs(y - curve.long_rate_bps()) < 5.0  # < 5 bps


def test_flat_curve_when_beta1_beta2_zero():
    """beta1=beta2=0 → flat curve at beta0."""
    curve = NelsonSiegelCurve(beta0_bps=400, beta1_bps=0, beta2_bps=0, lambda_=0.6)
    for tau in [0.5, 1, 5, 10, 30]:
        assert abs(curve.yield_at(tau) - 400) < 1e-6


def test_vectorized_yield_at():
    """yield_at akzeptiert Array und returnt Array."""
    curve = NelsonSiegelCurve(beta0_bps=400, beta1_bps=-100, beta2_bps=30, lambda_=0.6)
    maturities = np.array([1, 2, 5, 10, 30])
    yields = curve.yield_at(maturities)
    assert isinstance(yields, np.ndarray)
    assert yields.shape == (5,)
    # Sanity: alle finite
    assert np.isfinite(yields).all()


def test_scalar_yield_at_returns_float():
    curve = NelsonSiegelCurve(beta0_bps=400, beta1_bps=-100, beta2_bps=30, lambda_=0.6)
    y = curve.yield_at(5.0)
    assert isinstance(y, float)


def test_negative_maturity_raises():
    curve = NelsonSiegelCurve(beta0_bps=400, beta1_bps=-100, beta2_bps=30, lambda_=0.6)
    with pytest.raises(ValueError, match="maturity"):
        curve.yield_at(-1.0)
    with pytest.raises(ValueError, match="maturity"):
        curve.yield_at(0.0)
    with pytest.raises(ValueError, match="maturity"):
        curve.yield_at(np.array([1.0, -2.0]))


def test_ascending_curve_with_negative_beta1():
    """beta1 < 0 → ansteigende Curve (Normal-Term-Structure)."""
    curve = NelsonSiegelCurve(beta0_bps=400, beta1_bps=-200, beta2_bps=0, lambda_=0.6)
    y_short = curve.yield_at(1.0)
    y_long = curve.yield_at(10.0)
    assert y_short < y_long


def test_inverted_curve_with_positive_beta1():
    """beta1 > 0 → inverse Curve (Recessions-Signal)."""
    curve = NelsonSiegelCurve(beta0_bps=300, beta1_bps=200, beta2_bps=0, lambda_=0.6)
    y_short = curve.yield_at(1.0)
    y_long = curve.yield_at(10.0)
    assert y_short > y_long


def test_curvature_creates_hump():
    """Positive beta2 → Hump in mittleren Maturitaeten."""
    curve = NelsonSiegelCurve(beta0_bps=300, beta1_bps=0, beta2_bps=200, lambda_=0.6)
    y_short = curve.yield_at(0.5)
    y_mid = curve.yield_at(3.0)
    y_long = curve.yield_at(30.0)
    # Hump in der Mitte
    assert y_mid > y_short
    assert y_mid > y_long


def test_forward_rate_equals_yield_when_t1_zero():
    """f(0,t) = y(t)."""
    curve = NelsonSiegelCurve(beta0_bps=400, beta1_bps=-100, beta2_bps=30, lambda_=0.6)
    y5 = curve.yield_at(5.0)
    f05 = curve.forward_rate(0.0, 5.0)
    assert abs(y5 - f05) < 1e-6


def test_forward_rate_invariants():
    """Forward-Rate-Formel: f(t1,t2) = (y2*t2 - y1*t1)/(t2-t1)."""
    curve = NelsonSiegelCurve(beta0_bps=400, beta1_bps=-100, beta2_bps=30, lambda_=0.6)
    y1 = curve.yield_at(1.0)
    y10 = curve.yield_at(10.0)
    expected = (y10 * 10 - y1 * 1) / 9
    assert abs(curve.forward_rate(1.0, 10.0) - expected) < 1e-6


def test_forward_rate_invalid_args():
    curve = NelsonSiegelCurve(beta0_bps=400, beta1_bps=-100, beta2_bps=30, lambda_=0.6)
    with pytest.raises(ValueError):
        curve.forward_rate(-1, 5)
    with pytest.raises(ValueError):
        curve.forward_rate(5, 5)  # t2 <= t1
    with pytest.raises(ValueError):
        curve.forward_rate(5, 3)


def test_to_from_dict_roundtrip():
    original = NelsonSiegelCurve(beta0_bps=400, beta1_bps=-150, beta2_bps=80, lambda_=0.55)
    d = original.to_dict()
    restored = NelsonSiegelCurve.from_dict(d)
    assert restored == original


def test_fit_recovers_known_curve():
    """Synthetisch: erstelle Curve, sample yields, fit, check Parameter."""
    truth = NelsonSiegelCurve(beta0_bps=400, beta1_bps=-150, beta2_bps=50, lambda_=0.6)
    maturities = np.array([0.5, 1, 2, 3, 5, 7, 10, 15, 20, 30])
    yields = np.array([truth.yield_at(t) for t in maturities])
    fitted = fit_nelson_siegel(maturities, yields)
    # Fit sollte exakt sein (kein Noise) — Toleranz fuer Numerik
    assert abs(fitted.beta0_bps - truth.beta0_bps) < 1.0
    assert abs(fitted.beta1_bps - truth.beta1_bps) < 2.0
    assert abs(fitted.beta2_bps - truth.beta2_bps) < 5.0  # beta2 sensibler


def test_fit_with_fixed_lambda():
    """lambda_fixed=True nutzt lambda_init und optimiert nur betas."""
    truth = NelsonSiegelCurve(beta0_bps=400, beta1_bps=-150, beta2_bps=50, lambda_=0.6)
    maturities = np.array([1, 2, 5, 10, 20])
    yields = np.array([truth.yield_at(t) for t in maturities])
    fitted = fit_nelson_siegel(maturities, yields, lambda_init=0.6, lambda_fixed=True)
    assert fitted.lambda_ == 0.6


def test_fit_realistic_ch_curve():
    """Realistische CH-Eidg-Curve (approximativ 2024-Werte).
    Sehr flache Kurve mit leicht ansteigend zu langfristigen Maturitaeten."""
    maturities = np.array([0.5, 1, 2, 3, 5, 7, 10, 20, 30])
    yields_bps = np.array([60, 75, 90, 100, 120, 135, 145, 150, 150])
    curve = fit_nelson_siegel(maturities, yields_bps)
    # Fit-Quality: RMS-Error < 10 bps
    predicted = curve.yield_at(maturities)
    rms = float(np.sqrt(np.mean((yields_bps - predicted) ** 2)))
    assert rms < 10.0, f"RMS-Error {rms:.1f} bps > 10 bps"


def test_fit_too_few_data_points_raises():
    with pytest.raises(ValueError, match=">= 3"):
        fit_nelson_siegel(np.array([1, 5]), np.array([100, 150]))


def test_fit_shape_mismatch_raises():
    with pytest.raises(ValueError, match="shape mismatch"):
        fit_nelson_siegel(np.array([1, 5, 10]), np.array([100, 150]))


def test_fit_invalid_maturity_raises():
    with pytest.raises(ValueError, match="must be > 0"):
        fit_nelson_siegel(np.array([0, 5, 10]), np.array([100, 120, 150]))
