import pytest

from services.portfolio_engine import _apply_goal_and_reserve_tilts, _rebalance_to_total


def test_rebalance_to_total_normalizes_remaining_delta_within_bounds():
    adjusted = _rebalance_to_total(
        targets={
            "equities": 5990,
            "bonds": 2500,
            "real_estate": 800,
            "alternatives": 500,
            "liquidity": 100,
        },
        minimums={
            "equities": 3000,
            "bonds": 2000,
            "real_estate": 0,
            "alternatives": 0,
            "liquidity": 0,
        },
        maximums={
            "equities": 7000,
            "bonds": 4000,
            "real_estate": 2000,
            "alternatives": 1500,
            "liquidity": 1000,
        },
    )

    assert sum(adjusted.values()) == 10000
    assert adjusted["bonds"] == 2610


def test_rebalance_to_total_raises_when_bounds_make_normalization_impossible():
    with pytest.raises(ValueError, match="cannot be normalized to 10000 bps"):
        _rebalance_to_total(
            targets={
                "equities": 1000,
                "bonds": 1000,
                "real_estate": 1000,
                "alternatives": 1000,
                "liquidity": 1000,
            },
            minimums={
                "equities": 1000,
                "bonds": 1000,
                "real_estate": 1000,
                "alternatives": 1000,
                "liquidity": 1000,
            },
            maximums={
                "equities": 1000,
                "bonds": 1000,
                "real_estate": 1000,
                "alternatives": 1000,
                "liquidity": 1000,
            },
        )


def test_goal_and_reserve_tilts_caps_liquidity_when_near_term_shortfall_exceeds_advisory_wealth():
    targets = {
        "equities": 4800,
        "bonds": 3500,
        "real_estate": 1000,
        "alternatives": 500,
        "liquidity": 200,
    }
    minimums = {
        "equities": 0,
        "bonds": 0,
        "real_estate": 0,
        "alternatives": 0,
        "liquidity": 0,
    }
    maximums = {
        "equities": 5500,
        "bonds": 4500,
        "real_estate": 1500,
        "alternatives": 800,
        "liquidity": 300,
    }
    reasoning = []

    reserve_needed_rappen, external_reserve_rappen = _apply_goal_and_reserve_tilts(
        targets=targets,
        minimums=minimums,
        maximums=maximums,
        goals=[],
        limits_prefs={},
        asset_class_prefs={},
        recurring_net_cashflow_rappen=-9_300_000,
        recurring_cashflow_projection_series_rappen=[-9_300_000, -9_300_000, -4_300_000],
        advisory_wealth_rappen=25_000_000,
        reasoning=reasoning,
    )

    assert reserve_needed_rappen == 22_900_000
    assert external_reserve_rappen == 22_150_000
    assert targets == {
        "equities": 4800,
        "bonds": 3400,
        "real_estate": 1000,
        "alternatives": 500,
        "liquidity": 300,
    }
    assert minimums["liquidity"] == 0
    assert maximums["liquidity"] == 300
    assert any("Zeitlich datierte Netto-Cashflows" in item for item in reasoning)
    assert any("externe Reserve ausserhalb des Beratungsmandats empfohlen" in item for item in reasoning)
