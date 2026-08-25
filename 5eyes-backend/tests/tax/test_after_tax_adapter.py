from __future__ import annotations

from schemas.tax import TaxProfileInput
from services.tax.after_tax import get_after_tax_return


def _profile(**overrides) -> TaxProfileInput:
    data = {
        "country_code": "CH",
        "region": "ZH",
        "year": 2026,
        "taxable_income_rappen": 12_000_000,
        "taxable_wealth_rappen": 100_000_000,
        "capital_gains_realization": "private",
    }
    data.update(overrides)
    return TaxProfileInput(**data)


def test_after_tax_private_ch_gains_have_no_drag():
    result = get_after_tax_return(
        _profile(capital_gains_realization="private"),
        gross_return_bps=500,
        return_base_rappen=10_000_000,
    )
    assert result.gross_gain_rappen == 500_000
    assert result.tax_rappen == 0
    assert result.after_tax_return_bps == 500


def test_after_tax_business_gains_reduce_return():
    result = get_after_tax_return(
        _profile(capital_gains_realization="business"),
        gross_return_bps=500,
        return_base_rappen=10_000_000,
    )
    assert result.tax_rappen > 0
    assert result.estimated_tax_drag_bps > 0
    assert result.after_tax_return_bps < result.gross_return_bps


def test_after_tax_adapter_zero_base_no_crash():
    result = get_after_tax_return(
        _profile(),
        gross_return_bps=500,
        return_base_rappen=0,
    )
    assert result.tax_rappen == 0
    assert result.after_tax_return_bps == 500


def test_after_tax_adapter_is_deterministic():
    profile = _profile(region="GE", capital_gains_realization="business")
    first = get_after_tax_return(
        profile,
        gross_return_bps=750,
        return_base_rappen=20_000_000,
    )
    second = get_after_tax_return(
        profile,
        gross_return_bps=750,
        return_base_rappen=20_000_000,
    )
    assert first == second

