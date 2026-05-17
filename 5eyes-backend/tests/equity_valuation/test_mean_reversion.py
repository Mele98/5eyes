"""KGVMeanReversionModel Tests."""
from __future__ import annotations

import pytest

from services.equity_valuation.mean_reversion import KGVMeanReversionModel


def test_kgv_current_must_be_positive():
    with pytest.raises(ValueError, match="kgv_current"):
        KGVMeanReversionModel(kgv_current=-1, kgv_fair=17)
    with pytest.raises(ValueError, match="kgv_current"):
        KGVMeanReversionModel(kgv_current=0, kgv_fair=17)


def test_kgv_fair_must_be_positive():
    with pytest.raises(ValueError, match="kgv_fair"):
        KGVMeanReversionModel(kgv_current=20, kgv_fair=-1)


def test_alpha_must_be_in_unit_interval():
    with pytest.raises(ValueError, match="alpha"):
        KGVMeanReversionModel(kgv_current=20, kgv_fair=17, alpha=-0.1)
    with pytest.raises(ValueError, match="alpha"):
        KGVMeanReversionModel(kgv_current=20, kgv_fair=17, alpha=1.5)


def test_no_adjustment_when_fair_value():
    """KGV-Current = KGV-Fair → Adjustment = 0."""
    model = KGVMeanReversionModel(kgv_current=17, kgv_fair=17)
    assert model.expected_annual_return_adjustment_bps(10) == 0.0


def test_overvaluation_negative_adjustment():
    """KGV-Current > KGV-Fair → negativer Adjustment."""
    model = KGVMeanReversionModel(kgv_current=22, kgv_fair=17, alpha=0.15)
    adj = model.expected_annual_return_adjustment_bps(10)
    assert adj < 0


def test_undervaluation_positive_adjustment():
    """KGV-Current < KGV-Fair → positiver Adjustment."""
    model = KGVMeanReversionModel(kgv_current=12, kgv_fair=17, alpha=0.15)
    adj = model.expected_annual_return_adjustment_bps(10)
    assert adj > 0


def test_zero_alpha_returns_zero_adjustment():
    """alpha=0 → kein Effekt unabhaengig von KGV-Difference."""
    model = KGVMeanReversionModel(kgv_current=25, kgv_fair=17, alpha=0)
    assert model.expected_annual_return_adjustment_bps(10) == 0.0


def test_zero_horizon_returns_zero():
    """horizon=0 oder negativ → Adjustment=0."""
    model = KGVMeanReversionModel(kgv_current=22, kgv_fair=17, alpha=0.15)
    assert model.expected_annual_return_adjustment_bps(0) == 0.0
    assert model.expected_annual_return_adjustment_bps(-1) == 0.0


def test_overvaluation_pct():
    """current_overvaluation_pct: KGV-22 vs Fair-17 → ~29%."""
    model = KGVMeanReversionModel(kgv_current=22, kgv_fair=17)
    pct = model.current_overvaluation_pct()
    assert abs(pct - (22 - 17) / 17 * 100) < 0.01


def test_undervaluation_pct_negative():
    model = KGVMeanReversionModel(kgv_current=14, kgv_fair=17)
    pct = model.current_overvaluation_pct()
    assert pct < 0


def test_adjustment_dampening_for_long_horizon():
    """Bei langem Horizont schwaecheres Signal als bei kurz."""
    model = KGVMeanReversionModel(kgv_current=22, kgv_fair=17, alpha=0.15)
    short_adj = abs(model.expected_annual_return_adjustment_bps(5))
    long_adj = abs(model.expected_annual_return_adjustment_bps(30))
    # 30J Horizont sollte deutlich schwaecheres jaehrliches Adj haben
    assert long_adj < short_adj


def test_adjustment_minimum_dampening_30pct():
    """Sehr lange Horizonte (50+ J) → minimum 30% Dampening verbleibt."""
    model = KGVMeanReversionModel(kgv_current=22, kgv_fair=17, alpha=0.15)
    very_long = abs(model.expected_annual_return_adjustment_bps(100))
    base = 0.15 * (17 - 22) / 17 * 10000  # = -441 bps unbedaempft
    expected_min = abs(base) * 0.3  # 30% minimum
    assert abs(very_long - expected_min) < 1.0


def test_adjustment_scales_with_alpha():
    """Doppeltes alpha → ungefaehr doppeltes Adjustment."""
    m1 = KGVMeanReversionModel(kgv_current=22, kgv_fair=17, alpha=0.10)
    m2 = KGVMeanReversionModel(kgv_current=22, kgv_fair=17, alpha=0.20)
    adj1 = m1.expected_annual_return_adjustment_bps(10)
    adj2 = m2.expected_annual_return_adjustment_bps(10)
    # adj2 sollte etwa 2x adj1 sein
    assert abs(adj2 / adj1 - 2.0) < 0.01


def test_concrete_numerical_example():
    """Berechnungsbeispiel aus Spec verifizieren.

    KGV-Current=25, KGV-Fair=17, alpha=0.15, horizon=10
    relative_undervaluation = (17-25)/17 = -0.4706
    base = 0.15 * -0.4706 * 10000 = -705.88 bps
    dampening = max(0.3, 1 - 0.03*10) = 0.7
    adj = -705.88 * 0.7 = -494 bps
    """
    model = KGVMeanReversionModel(kgv_current=25, kgv_fair=17, alpha=0.15)
    adj = model.expected_annual_return_adjustment_bps(10)
    expected = 0.15 * (17 - 25) / 17 * 10000 * 0.7
    assert abs(adj - expected) < 0.01


def test_to_from_dict_roundtrip():
    original = KGVMeanReversionModel(kgv_current=22, kgv_fair=17, alpha=0.12)
    d = original.to_dict()
    restored = KGVMeanReversionModel.from_dict(d)
    assert restored == original


def test_from_dict_default_alpha():
    """Wenn alpha fehlt im Dict, default 0.15."""
    m = KGVMeanReversionModel.from_dict({"kgv_current": 22, "kgv_fair": 17})
    assert m.alpha == 0.15
