"""Contract for direct property in total-wealth projections.

Direct property is an external, fixed foundation.  It is not a listed-real-
estate investment and therefore must neither receive the listed-RE CMA return
nor be sold/rebalanced into the strategic financial portfolio.

The deterministic and Monte-Carlo paths consume the same position-derived
gross-property and liability series.  Rent stays in the existing cashflow
series and must not be embedded in the property series.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.orm import configure_mappers

from database import Base  # noqa: F401
from models import (  # noqa: F401
    allocation,
    clients,
    mandates,
    profiling,
    review,
    snapshots,
    users,
    wealth,
)

configure_mappers()

import services.portfolio_engine as pe
import services.portfolio_engine_mc_simulation as mc_module
from models.allocation import CapitalMarketAssumption
from services.portfolio_engine import BUCKET_FIELDS, PortfolioSummary


def _position(**overrides):
    values = dict(
        id="position",
        position_type="Immobilien",
        assignment="Anderes Vermögen",
        current_value_rappen=0,
        currency="CHF",
        asset_expected_return_bps=0,
        property_rental_income_rappen=0,
        mortgage_amortization_rappen=0,
        mortgage_amortization_type=None,
        is_active=1,
        deleted_at=None,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _foundation_projection(positions, horizon_years):
    helper = getattr(pe, "_build_external_foundation_projection", None)
    assert callable(helper), (
        "Implement _build_external_foundation_projection(positions, *, "
        "horizon_years, fx_source=None, target_currency='CHF')."
    )
    return helper(positions, horizon_years=horizon_years)


def _zero_cma() -> CapitalMarketAssumption:
    return CapitalMarketAssumption(
        id="cma-external-property-contract",
        assumption_set_name="External property contract",
        version=1,
        valid_from="2026-01-01",
        is_current=1,
        bonds_chf_ig_return_bps=0,
        bonds_chf_ig_vol_bps=0,
        bonds_fx_hedged_return_bps=0,
        bonds_fx_hedged_vol_bps=0,
        equity_ch_return_bps=0,
        equity_ch_vol_bps=0,
        equity_intl_return_bps=0,
        equity_intl_vol_bps=0,
        real_estate_ch_return_bps=0,
        real_estate_ch_vol_bps=0,
        alternatives_gold_return_bps=0,
        alternatives_gold_vol_bps=0,
        liquidity_return_bps=0,
        liquidity_vol_bps=0,
        correlation_matrix_json="",
        sub_asset_class_assumptions_json="",
        created_by="test",
        created_at="2026-01-01T00:00:00.000Z",
        updated_at="2026-01-01T00:00:00.000Z",
    )


def _summary(*, liquidity=0, equities=0, real_estate=0):
    amounts = {key: 0 for key in BUCKET_FIELDS}
    amounts.update(
        liquidity=int(liquidity),
        equities=int(equities),
        real_estate=int(real_estate),
    )
    return PortfolioSummary(amounts_rappen=amounts, total_rappen=sum(amounts.values()))


def _weights(bucket):
    return {key: 10000 if key == bucket else 0 for key in BUCKET_FIELDS}


def _deterministic(*, cma, cashflows, total_summary, foundation, target_bucket="liquidity"):
    zeros = {key: 0 for key in BUCKET_FIELDS}
    return pe._build_simulation_payload(
        advisory_summary=_summary(liquidity=100_000),
        cashflow_projection_series_rappen=list(cashflows),
        cma=cma,
        targets=_weights(target_bucket),
        minimums=zeros,
        maximums=zeros,
        start_year=2026,
        simulation_prefs={"rebalanceMode": "calendar", "transactionCostBps": 0},
        target_total_rappen=100_000,
        total_summary=total_summary,
        total_liabilities_rappen=foundation["liability_series_rappen"][0],
        external_foundation_projection=foundation,
    )


def _monte_carlo(*, monkeypatch, cma, cashflows, total_summary, foundation):
    monkeypatch.setattr(mc_module, "_monte_carlo_simulations", lambda _prefs: 40)
    zeros = {key: 0 for key in BUCKET_FIELDS}
    return pe._run_allocation_monte_carlo(
        advisory_summary=_summary(liquidity=100_000),
        cashflow_projection_series_rappen=list(cashflows),
        goal_inflation_series_bps=[0] * len(cashflows),
        targets=_weights("liquidity"),
        minimums=zeros,
        maximums=zeros,
        cma=cma,
        goals=[],
        advisory_wealth_rappen=100_000,
        total_wealth_rappen=(
            total_summary.total_rappen - foundation["liability_series_rappen"][0]
        ),
        policy=None,
        mandate_id="external-property-contract",
        simulation_prefs={"rebalanceMode": "calendar", "transactionCostBps": 0},
        start_year=2026,
        target_total_rappen=100_000,
        total_summary=total_summary,
        total_liabilities_rappen=foundation["liability_series_rappen"][0],
        external_foundation_projection=foundation,
    )


def test_foundation_projection_uses_position_price_return_and_not_rent():
    """Price growth is position-specific; rent remains a separate cashflow."""
    positions = [
        _position(
            id="house-a",
            current_value_rappen=1_000_000,
            asset_expected_return_bps=200,
            property_rental_income_rappen=90_000,
        ),
        _position(
            id="house-b",
            current_value_rappen=500_000,
            asset_expected_return_bps=0,
            property_rental_income_rappen=60_000,
        ),
    ]

    projection = _foundation_projection(positions, horizon_years=2)

    assert projection["property_series_rappen"] == [1_500_000, 1_520_000, 1_540_400]
    assert projection["liability_series_rappen"] == [0, 0, 0]
    assert projection["pledged_asset_series_rappen"] == [0, 0, 0]
    # 150k rent is deliberately absent: it is already in the cashflow engine.
    assert projection["property_series_rappen"][1] - projection["property_series_rappen"][0] == 20_000


def test_foundation_projection_reduces_only_direct_mortgage_debt():
    """Direct amortization lowers debt; indirect amortization leaves it flat."""
    positions = [
        _position(id="house", current_value_rappen=1_000_000),
        _position(
            id="direct-mortgage",
            position_type="Hypothek",
            assignment="Verbindlichkeit",
            current_value_rappen=600_000,
            mortgage_amortization_rappen=100_000,
            mortgage_amortization_type="Direkt",
        ),
        _position(
            id="indirect-mortgage",
            position_type="Hypothek",
            assignment="Verbindlichkeit",
            current_value_rappen=100_000,
            mortgage_amortization_rappen=20_000,
            mortgage_amortization_type="Indirekt (Saeule 3a)",
        ),
    ]

    projection = _foundation_projection(positions, horizon_years=2)

    assert projection["property_series_rappen"] == [1_000_000, 1_000_000, 1_000_000]
    assert projection["liability_series_rappen"] == [700_000, 600_000, 500_000]
    assert projection["pledged_asset_series_rappen"] == [0, 20_000, 40_000]


def test_foundation_projection_keeps_non_mortgage_liabilities_in_total_wealth():
    """Every explicit liability reduces total wealth, even without mortgage fields."""
    positions = [
        _position(
            id="other-debt",
            position_type="Custom",
            assignment="Verbindlichkeit",
            current_value_rappen=250_000,
        ),
    ]

    projection = _foundation_projection(positions, horizon_years=2)

    assert projection["property_series_rappen"] == [0, 0, 0]
    assert projection["liability_series_rappen"] == [250_000, 250_000, 250_000]
    assert projection["pledged_asset_series_rappen"] == [0, 0, 0]


def test_indirect_amortization_is_a_total_wealth_transfer():
    positions = [
        _position(
            id="mortgage",
            position_type="Hypothek",
            assignment="Verbindlichkeit",
            current_value_rappen=100_000,
            mortgage_amortization_rappen=20_000,
            mortgage_amortization_type="Indirekt (Säule 3a)",
        ),
    ]
    foundation = _foundation_projection(positions, horizon_years=2)

    result = _deterministic(
        cma=_zero_cma(),
        cashflows=[-20_000, -20_000],
        total_summary=_summary(liquidity=200_000),
        foundation=foundation,
    )

    assert result["total_mix_current_series_rappen"] == [100_000] * 3
    assert result["total_mix_target_series_rappen"] == [100_000] * 3


def test_deterministic_total_paths_ignore_listed_re_cma_and_count_rent_once():
    cma = _zero_cma()
    # Deliberately absurd listed-RE assumption: it must not touch the house.
    cma.real_estate_ch_return_bps = 4500
    house = _position(
        current_value_rappen=1_000_000,
        asset_expected_return_bps=0,
        property_rental_income_rappen=24_000,
    )
    foundation = _foundation_projection([house], horizon_years=2)

    result = _deterministic(
        cma=cma,
        cashflows=[24_000, 24_000],
        total_summary=_summary(liquidity=100_000, real_estate=1_000_000),
        foundation=foundation,
    )

    expected = [1_100_000, 1_124_000, 1_148_000]
    assert result["total_mix_current_series_rappen"] == expected
    assert result["total_mix_target_series_rappen"] == expected


def test_total_target_rebalances_only_financial_assets_not_the_house():
    cma = _zero_cma()
    cma.equity_ch_return_bps = 1000
    cma.equity_intl_return_bps = 1000
    house = _position(current_value_rappen=1_000_000, asset_expected_return_bps=0)
    foundation = _foundation_projection([house], horizon_years=1)

    result = _deterministic(
        cma=cma,
        cashflows=[0],
        total_summary=_summary(liquidity=100_000, real_estate=1_000_000),
        foundation=foundation,
        target_bucket="equities",
    )

    # Only CHF 100k financial wealth receives the 10% equity return.  Rebalancing
    # the CHF 1m house would incorrectly produce CHF 1.21m instead of 1.11m.
    assert result["total_mix_target_series_rappen"] == [1_100_000, 1_110_000]


def test_total_target_can_hold_listed_real_estate_beside_direct_property():
    cma = _zero_cma()
    cma.real_estate_ch_return_bps = 1000
    house = _position(current_value_rappen=1_000_000)
    foundation = _foundation_projection([house], horizon_years=1)

    result = _deterministic(
        cma=cma,
        cashflows=[0],
        total_summary=_summary(liquidity=100_000, real_estate=1_000_000),
        foundation=foundation,
        target_bucket="real_estate",
    )

    # The house stays flat. Only the CHF 100k listed-RE sleeve earns 10%.
    assert result["total_mix_target_series_rappen"] == [1_100_000, 1_110_000]


@pytest.mark.parametrize("invalid_value", [True, 1.5, "100", -1])
def test_foundation_payload_rejects_non_integer_or_negative_values(invalid_value):
    projection = {
        "property_series_rappen": [0, invalid_value],
        "liability_series_rappen": [0, 0],
        "pledged_asset_series_rappen": [0, 0],
    }

    with pytest.raises(ValueError, match="non-negative integer Rappen"):
        mc_module._coerce_external_foundation_projection(projection, 1)


def test_direct_amortization_is_net_wealth_neutral_except_for_interest():
    positions = [
        _position(id="house", current_value_rappen=1_000_000),
        _position(
            id="mortgage",
            position_type="Hypothek",
            assignment="Verbindlichkeit",
            current_value_rappen=500_000,
            mortgage_amortization_rappen=100_000,
            mortgage_amortization_type="Direkt",
        ),
    ]
    foundation = _foundation_projection(positions, horizon_years=2)

    result = _deterministic(
        cma=_zero_cma(),
        # Existing cashflow series contains principal plus declining interest:
        # year 1: 100k + 10k; year 2: 100k + 8k.
        cashflows=[-110_000, -108_000],
        total_summary=_summary(liquidity=250_000, real_estate=1_000_000),
        foundation=foundation,
    )

    # Principal repayment moves value from cash to lower debt and cancels in
    # net wealth.  Only the 10k/8k interest expense remains.
    assert result["total_mix_current_series_rappen"] == [750_000, 740_000, 732_000]
    assert result["total_mix_target_series_rappen"] == [750_000, 740_000, 732_000]


def test_mc_property_is_deterministic_and_uses_its_own_price_return(monkeypatch):
    cma = _zero_cma()
    cma.real_estate_ch_return_bps = 4500
    cma.real_estate_ch_vol_bps = 5000
    house = _position(current_value_rappen=1_000_000, asset_expected_return_bps=200)
    foundation = _foundation_projection([house], horizon_years=2)

    result = _monte_carlo(
        monkeypatch=monkeypatch,
        cma=cma,
        cashflows=[0, 0],
        total_summary=_summary(liquidity=100_000, real_estate=1_000_000),
        foundation=foundation,
    )

    expected = [1_100_000, 1_120_000, 1_140_400]
    for prefix in ("total_current", "total_target"):
        assert result[f"{prefix}_p10_series_rappen"] == expected
        assert result[f"{prefix}_p50_series_rappen"] == expected
        assert result[f"{prefix}_p90_series_rappen"] == expected
