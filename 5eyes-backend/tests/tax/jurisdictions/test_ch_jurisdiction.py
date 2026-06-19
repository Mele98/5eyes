from __future__ import annotations

from schemas.tax import TaxProfileInput
from services.tax.jurisdictions.ch import SwissTaxJurisdiction
from services.tax.registry import get_jurisdiction


def _profile(**overrides) -> TaxProfileInput:
    data = {
        "country_code": "CH",
        "region": "ZH",
        "year": 2026,
        "taxable_income_rappen": 12_000_000,
        "taxable_wealth_rappen": 100_000_000,
        "capital_gains_rappen": 20_000_000,
        "marital_status": "single",
    }
    data.update(overrides)
    return TaxProfileInput(**data)


def test_ch_jurisdiction_registered():
    plugin = get_jurisdiction("CH")
    assert isinstance(plugin, SwissTaxJurisdiction)
    assert plugin.metadata.currency == "CHF"
    assert "ZH" in plugin.metadata.supported_regions


def test_income_tax_known_zurich_case_with_documented_tolerance():
    result = SwissTaxJurisdiction().estimate_income_tax(_profile())
    # Approximation tolerance: simplified direct-federal tariff plus canton-level
    # parameter, not an exact municipal filing calculator.
    assert 1_500_000 <= result.income_tax_rappen <= 2_600_000
    assert result.effective_tax_bps > 0
    assert "Parameterjahr" in " ".join(result.assumptions)


def test_zug_lower_than_geneva_for_same_profile():
    plugin = SwissTaxJurisdiction()
    zug = plugin.estimate(_profile(region="ZG"))
    geneva = plugin.estimate(_profile(region="GE"))
    assert zug.total_tax_rappen < geneva.total_tax_rappen
    assert zug.wealth_tax_rappen < geneva.wealth_tax_rappen


def test_private_capital_gains_are_zero_with_assumption():
    result = SwissTaxJurisdiction().estimate_capital_gains(
        _profile(capital_gains_realization="private")
    )
    assert result.capital_gains_tax_rappen == 0
    assert result.total_tax_rappen == 0
    assert "Private Kapitalgewinne" in " ".join(result.assumptions)


def test_business_capital_gains_are_taxed_as_income():
    result = SwissTaxJurisdiction().estimate_capital_gains(
        _profile(capital_gains_realization="business")
    )
    assert result.capital_gains_tax_rappen > 0
    assert result.effective_tax_bps > 0
    assert result.breakdown["capital_gains_realization"] == "business"


def test_unknown_region_uses_conservative_fallback():
    result = SwissTaxJurisdiction().estimate(_profile(region="XX"))
    assert result.region == "CH-CONSERVATIVE"
    assert "konservativer CH-Fallback" in " ".join(result.assumptions)


def test_ch_estimate_is_deterministic():
    plugin = SwissTaxJurisdiction()
    profile = _profile(region="GE", capital_gains_realization="business")
    assert plugin.estimate(profile) == plugin.estimate(profile)

