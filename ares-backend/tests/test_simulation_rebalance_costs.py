from services.portfolio_engine import _simulate_bucket_path


def test_simulate_bucket_path_deducts_transaction_costs_on_rebalance():
    totals_free, _ = _simulate_bucket_path(
        start_values={
            "equities": 1_000_000,
            "bonds": 0,
            "real_estate": 0,
            "alternatives": 0,
            "liquidity": 0,
        },
        returns_by_asset={
            "equities": 0,
            "bonds": 0,
            "real_estate": 0,
            "alternatives": 0,
            "liquidity": 0,
        },
        cashflow_series_rappen=[0],
        targets={
            "equities": 5000,
            "bonds": 5000,
            "real_estate": 0,
            "alternatives": 0,
            "liquidity": 0,
        },
        minimums={
            "equities": 0,
            "bonds": 0,
            "real_estate": 0,
            "alternatives": 0,
            "liquidity": 0,
        },
        maximums={
            "equities": 10000,
            "bonds": 10000,
            "real_estate": 10000,
            "alternatives": 10000,
            "liquidity": 10000,
        },
        start_year=2026,
        rebalance_mode="calendar",
        transaction_cost_bps=0,
    )
    totals_cost, events = _simulate_bucket_path(
        start_values={
            "equities": 1_000_000,
            "bonds": 0,
            "real_estate": 0,
            "alternatives": 0,
            "liquidity": 0,
        },
        returns_by_asset={
            "equities": 0,
            "bonds": 0,
            "real_estate": 0,
            "alternatives": 0,
            "liquidity": 0,
        },
        cashflow_series_rappen=[0],
        targets={
            "equities": 5000,
            "bonds": 5000,
            "real_estate": 0,
            "alternatives": 0,
            "liquidity": 0,
        },
        minimums={
            "equities": 0,
            "bonds": 0,
            "real_estate": 0,
            "alternatives": 0,
            "liquidity": 0,
        },
        maximums={
            "equities": 10000,
            "bonds": 10000,
            "real_estate": 10000,
            "alternatives": 10000,
            "liquidity": 10000,
        },
        start_year=2026,
        rebalance_mode="calendar",
        transaction_cost_bps=100,
    )

    assert totals_free == [1_000_000, 1_000_000]
    assert totals_cost == [1_000_000, 995_000]
    assert events[0]["turnover_rappen"] == 500_000
