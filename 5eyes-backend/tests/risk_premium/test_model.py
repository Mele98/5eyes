"""RiskPremiumModel Tests."""
from __future__ import annotations

import pytest

from services.risk_premium.model import RiskPremiumModel


def test_asset_class_must_be_non_empty():
    with pytest.raises(ValueError, match="asset_class"):
        RiskPremiumModel(asset_class="", premium_bps=200)


def test_asset_class_must_be_string():
    with pytest.raises(ValueError, match="asset_class"):
        RiskPremiumModel(asset_class=None, premium_bps=200)  # type: ignore[arg-type]


def test_basic_addition():
    """expected_return = risk_free + premium."""
    model = RiskPremiumModel(asset_class="real_estate", premium_bps=200)
    assert model.expected_return_bps(300) == 500


def test_zero_risk_free_returns_only_premium():
    model = RiskPremiumModel(asset_class="alternatives", premium_bps=300)
    assert model.expected_return_bps(0) == 300


def test_zero_premium_returns_only_risk_free():
    """Premium=0 → return = risk_free (kein Effekt)."""
    model = RiskPremiumModel(asset_class="re", premium_bps=0)
    assert model.expected_return_bps(400) == 400


def test_high_risk_free_environment():
    """Bei hohem Zinsniveau (z.B. 6%) entsprechend hoeher Returns."""
    model = RiskPremiumModel(asset_class="real_estate", premium_bps=200)
    assert model.expected_return_bps(600) == 800


def test_negative_premium_allowed():
    """Negative Premia (Convenience-Yield) sind technisch erlaubt."""
    model = RiskPremiumModel(asset_class="gold", premium_bps=-100)
    assert model.expected_return_bps(400) == 300


def test_float_inputs_handled():
    """Floats werden korrekt verarbeitet."""
    model = RiskPremiumModel(asset_class="re", premium_bps=200.5)
    assert model.expected_return_bps(300.25) == 500.75


def test_to_from_dict_roundtrip():
    original = RiskPremiumModel(asset_class="alternatives", premium_bps=350)
    d = original.to_dict()
    restored = RiskPremiumModel.from_dict(d)
    assert restored == original


def test_typical_real_estate_premium_range():
    """Typisches RE-Premium 150-250 bps mit 200 bps risk_free → 350-450 bps."""
    for premium in [150, 200, 250]:
        model = RiskPremiumModel(asset_class="re", premium_bps=premium)
        ret = model.expected_return_bps(200)
        assert 350 <= ret <= 450


def test_typical_alternatives_premium_range():
    """Typisches Alts-Premium 200-400 bps mit 200 bps risk_free → 400-600 bps."""
    for premium in [200, 300, 400]:
        model = RiskPremiumModel(asset_class="alt", premium_bps=premium)
        ret = model.expected_return_bps(200)
        assert 400 <= ret <= 600


def test_immutable():
    """Dataclass ist frozen — kein in-place Aendern."""
    model = RiskPremiumModel(asset_class="re", premium_bps=200)
    with pytest.raises(AttributeError):
        model.premium_bps = 300  # type: ignore[misc]
