"""TaxContext, TaxResult Protocol-Contract Tests.

Spec: docs/planning/2026-05-17-sprint-3-tax-plugin-system.md §3
"""
from __future__ import annotations

import pytest

from services.tax.base import TaxContext, TaxRegime, TaxResult


def test_tax_context_basic_construction():
    ctx = TaxContext(
        year_index=0,
        calendar_year=2026,
        wealth_rappen=1_000_000_00,
    )
    assert ctx.year_index == 0
    assert ctx.calendar_year == 2026
    assert ctx.wealth_rappen == 1_000_000_00
    assert ctx.age is None
    assert ctx.is_retired is False
    assert ctx.currency_code == "CHF"
    assert ctx.marital_status == "single"
    assert ctx.children_count == 0


def test_tax_context_immutable():
    ctx = TaxContext(year_index=0, calendar_year=2026, wealth_rappen=100_000_00)
    with pytest.raises(AttributeError):
        ctx.wealth_rappen = 200_000_00  # type: ignore[misc]


def test_tax_context_full_construction():
    ctx = TaxContext(
        year_index=5,
        calendar_year=2031,
        wealth_rappen=2_500_000_00,
        age=58,
        is_retired=False,
        currency_code="EUR",
        marital_status="married",
        children_count=2,
    )
    assert ctx.age == 58
    assert ctx.marital_status == "married"
    assert ctx.children_count == 2
    assert ctx.currency_code == "EUR"


def test_tax_result_basic_construction():
    r = TaxResult(
        amount_rappen=12_500_00,
        effective_bps=125.0,
        regime_id="CH-ZH",
        tariff_version="2026-CH-ZH-v1",
    )
    assert r.amount_rappen == 12_500_00
    assert r.effective_bps == 125.0
    assert r.regime_id == "CH-ZH"
    assert r.breakdown == {}
    assert r.used_overrides is None
    assert r.warnings == ()


def test_tax_result_with_breakdown():
    r = TaxResult(
        amount_rappen=1500.0,
        effective_bps=15.0,
        regime_id="CH-ZH",
        tariff_version="2026-CH-ZH-v1",
        breakdown={"kantonal": 8.0, "gemeinde": 7.0, "bund": 0.0},
    )
    assert r.breakdown == {"kantonal": 8.0, "gemeinde": 7.0, "bund": 0.0}
    assert sum(r.breakdown.values()) == 15.0


def test_tax_result_immutable():
    r = TaxResult(
        amount_rappen=100.0,
        effective_bps=10.0,
        regime_id="DE",
        tariff_version="2026-DE-v1",
    )
    with pytest.raises(AttributeError):
        r.amount_rappen = 200.0  # type: ignore[misc]


def test_tax_result_warnings_default_empty_tuple():
    r = TaxResult(
        amount_rappen=0.0,
        effective_bps=0.0,
        regime_id="GENERIC",
        tariff_version="GENERIC-v1",
    )
    assert isinstance(r.warnings, tuple)
    assert r.warnings == ()


def test_tax_regime_is_protocol():
    """TaxRegime ist Protocol — runtime-checkable, aber nicht direkt instanziierbar."""
    from typing import Protocol
    assert issubclass(TaxRegime, Protocol)  # type: ignore[arg-type]


def test_generic_regime_satisfies_protocol():
    """GenericFlatRateRegime erfuellt das TaxRegime-Protocol (runtime isinstance)."""
    from services.tax.regimes.generic import GenericFlatRateRegime
    regime = GenericFlatRateRegime()
    assert isinstance(regime, TaxRegime)


def test_tax_context_negative_wealth_allowed():
    """Negatives Wealth ist valides Input (Schulden-Phase, Engine handhabt das)."""
    ctx = TaxContext(year_index=0, calendar_year=2026, wealth_rappen=-50_000_00)
    assert ctx.wealth_rappen == -50_000_00


def test_tax_context_year_index_zero_based():
    """year_index=0 = erstes Simulations-Jahr (nicht 1)."""
    ctx = TaxContext(year_index=0, calendar_year=2026, wealth_rappen=0)
    assert ctx.year_index == 0


def test_tax_result_overrides_dict_separate_field():
    """used_overrides ist separates Audit-Feld, nicht mit breakdown vermischt."""
    r = TaxResult(
        amount_rappen=500.0,
        effective_bps=50.0,
        regime_id="CH-ZH",
        tariff_version="2026-CH-ZH-v1",
        breakdown={"kantonal": 50.0},
        used_overrides={"wealth_tax_bps_pa": 50.0},
    )
    assert r.breakdown == {"kantonal": 50.0}
    assert r.used_overrides == {"wealth_tax_bps_pa": 50.0}


def test_tax_context_currency_code_default_chf():
    """Default-Waehrung ist CHF (CH-First-Strategie)."""
    ctx = TaxContext(year_index=0, calendar_year=2026, wealth_rappen=100)
    assert ctx.currency_code == "CHF"


def test_tax_result_breakdown_floats():
    """Breakdown-Werte sind Floats, kein int."""
    r = TaxResult(
        amount_rappen=100.0,
        effective_bps=10.0,
        regime_id="X",
        tariff_version="v",
        breakdown={"a": 5.0, "b": 5.0},
    )
    for v in r.breakdown.values():
        assert isinstance(v, float)


def test_tax_context_marital_status_default():
    ctx = TaxContext(year_index=0, calendar_year=2026, wealth_rappen=0)
    assert ctx.marital_status == "single"
