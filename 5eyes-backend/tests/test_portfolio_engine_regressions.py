import json
import math
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import clients as _clients_models  # noqa: F401
from models import mandates as _mandates_models  # noqa: F401
from models import profiling as _profiling_models  # noqa: F401
from models import snapshots as _snapshots_models  # noqa: F401
from models import wealth as _wealth_models  # noqa: F401
from models.allocation import CapitalMarketAssumption
from models.review import PriceHistory, Product
from models.users import User  # noqa: F401
import services.portfolio_engine as portfolio_engine
from services.portfolio_engine import (
    PortfolioSummary,
    _asset_class_expected_metrics,
    _bucket_expected_metrics,
    _build_bucket_response,
    _build_live_bucket_drifts,
    _build_simulation_payload,
    _build_sub_allocations,
    _coerce_band_bps,
    _compute_reserve_requirements,
    _goal_timing_label,
    _implementation_steps,
    _reference_price_snapshot_for_run,
    _simulate_bucket_path,
    _target_allocation_context_warnings,
    _target_allocation_reserve_warnings,
)


@pytest.fixture()
def session_factory(tmp_path):
    db_path = tmp_path / "test_portfolio_engine_regressions.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    testing_session_local = sessionmaker(
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
        bind=engine,
    )
    Base.metadata.create_all(bind=engine)
    try:
        yield testing_session_local
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _make_cma(**overrides) -> CapitalMarketAssumption:
    defaults = {
        "id": "cma-1",
        "assumption_set_name": "Test",
        "version": 1,
        "valid_from": "2026-04-20",
        "is_current": 1,
        "bonds_chf_ig_return_bps": 220,
        "bonds_chf_ig_vol_bps": 350,
        "bonds_fx_hedged_return_bps": 220,
        "bonds_fx_hedged_vol_bps": 430,
        "equity_ch_return_bps": 620,
        "equity_ch_vol_bps": 1450,
        "equity_intl_return_bps": 700,
        "equity_intl_vol_bps": 1600,
        "real_estate_ch_return_bps": 450,
        "real_estate_ch_vol_bps": 820,
        "alternatives_gold_return_bps": 300,
        "alternatives_gold_vol_bps": 1200,
        "liquidity_return_bps": 80,
        "liquidity_vol_bps": 20,
        "correlation_matrix_json": "",
        "sub_asset_class_assumptions_json": json.dumps(
            {
                "Aktien Schweiz": {
                    "asset_class": "Aktien",
                    "expected_return_bps": 100,
                    "expected_volatility_bps": 100,
                }
            }
        ),
        "created_by": "advisor-1",
        "created_at": "2026-04-20T00:00:00.000Z",
        "updated_at": "2026-04-20T00:00:00.000Z",
    }
    defaults.update(overrides)
    return CapitalMarketAssumption(**defaults)


def test_asset_class_expected_metrics_respects_cma_bucket_fields():
    baseline = _make_cma()
    higher_ch_equity = _make_cma(equity_ch_return_bps=800)

    baseline_returns, _ = _asset_class_expected_metrics(baseline)
    updated_returns, _ = _asset_class_expected_metrics(higher_ch_equity)

    assert baseline_returns["equities"] == 660
    assert updated_returns["equities"] == 750


def test_reference_price_snapshot_keeps_same_day_price_even_if_fetched_later(session_factory):
    with session_factory() as session:
        session.add(
            Product(
                id="product-1",
                product_name="Testfonds",
                product_type="ETF",
                asset_class="Aktien",
                currency="CHF",
                is_active=1,
                created_at="2026-04-20T00:00:00.000Z",
                updated_at="2026-04-20T00:00:00.000Z",
            )
        )
        session.add_all(
            [
                PriceHistory(
                    id="price-same-day",
                    product_id="product-1",
                    price_date="2026-04-20",
                    price_rappen=101000,
                    currency="CHF",
                    source="manual",
                    fetched_at="2026-04-20T12:00:05.000Z",
                ),
                PriceHistory(
                    id="price-prior-day",
                    product_id="product-1",
                    price_date="2026-04-19",
                    price_rappen=99000,
                    currency="CHF",
                    source="manual-prev",
                    fetched_at="2026-04-20T11:00:00.000Z",
                ),
            ]
        )
        session.commit()

        snapshots = _reference_price_snapshot_for_run(
            session,
            ["product-1"],
            "2026-04-20T12:00:00.000Z",
        )

    assert snapshots["product-1"].id == "price-same-day"


def test_run_allocation_monte_carlo_seed_changes_for_transaction_cost_and_correlation(monkeypatch):
    monkeypatch.setattr(portfolio_engine, "_monte_carlo_simulations", lambda prefs: 1)

    advisory_summary = PortfolioSummary(
        amounts_rappen={
            "equities": 600000,
            "bonds": 400000,
            "real_estate": 0,
            "alternatives": 0,
            "liquidity": 0,
        },
        total_rappen=1000000,
    )
    targets = {
        "equities": 6000,
        "bonds": 4000,
        "real_estate": 0,
        "alternatives": 0,
        "liquidity": 0,
    }
    minimums = {
        "equities": 5000,
        "bonds": 3000,
        "real_estate": 0,
        "alternatives": 0,
        "liquidity": 0,
    }
    maximums = {
        "equities": 7000,
        "bonds": 5000,
        "real_estate": 0,
        "alternatives": 0,
        "liquidity": 0,
    }

    base_result = portfolio_engine._run_allocation_monte_carlo(
        advisory_summary=advisory_summary,
        cashflow_projection_series_rappen=[0],
        goal_inflation_series_bps=[0],
        targets=targets,
        minimums=minimums,
        maximums=maximums,
        cma=_make_cma(),
        goals=[],
        advisory_wealth_rappen=1000000,
        total_wealth_rappen=1000000,
        policy=None,
        mandate_id="mandate-1",
        simulation_prefs={"transactionCostBps": 0, "rebalanceMode": "bands"},
        start_year=2026,
    )
    cost_result = portfolio_engine._run_allocation_monte_carlo(
        advisory_summary=advisory_summary,
        cashflow_projection_series_rappen=[0],
        goal_inflation_series_bps=[0],
        targets=targets,
        minimums=minimums,
        maximums=maximums,
        cma=_make_cma(),
        goals=[],
        advisory_wealth_rappen=1000000,
        total_wealth_rappen=1000000,
        policy=None,
        mandate_id="mandate-1",
        simulation_prefs={"transactionCostBps": 15, "rebalanceMode": "bands"},
        start_year=2026,
    )
    correlation_result = portfolio_engine._run_allocation_monte_carlo(
        advisory_summary=advisory_summary,
        cashflow_projection_series_rappen=[0],
        goal_inflation_series_bps=[0],
        targets=targets,
        minimums=minimums,
        maximums=maximums,
        cma=_make_cma(
            correlation_matrix_json=json.dumps(
                [
                    [1.0, 0.1, 0.0, 0.0, 0.0],
                    [0.1, 1.0, 0.0, 0.0, 0.0],
                    [0.0, 0.0, 1.0, 0.0, 0.0],
                    [0.0, 0.0, 0.0, 1.0, 0.0],
                    [0.0, 0.0, 0.0, 0.0, 1.0],
                ]
            )
        ),
        goals=[],
        advisory_wealth_rappen=1000000,
        total_wealth_rappen=1000000,
        policy=None,
        mandate_id="mandate-1",
        simulation_prefs={"transactionCostBps": 0, "rebalanceMode": "bands"},
        start_year=2026,
    )

    assert base_result["seed"] != cost_result["seed"]
    assert base_result["seed"] != correlation_result["seed"]


def test_coerce_band_bps_interprets_numeric_percent_values_correctly():
    assert _coerce_band_bps(50.0) == 5000
    assert _coerce_band_bps(0.05) == 500
    assert _coerce_band_bps(500) == 500
    assert _coerce_band_bps("50%") == 5000


def test_build_sub_allocations_renormalizes_bond_splits_after_filtering():
    sub_allocations = _build_sub_allocations(
        targets={
            "equities": 0,
            "bonds": 3000,
            "real_estate": 0,
            "alternatives": 0,
            "liquidity": 0,
        },
        preferences={
            "assetClasses": {
                "bondsHighYield": False,
                "bondsEmerging": False,
            }
        },
    )

    bond_weights = {
        item["sub_asset_class"]: item["target_weight_bps"]
        for item in sub_allocations
        if item["asset_class"] == "Obligationen"
    }

    assert bond_weights == {
        "Obligationen CHF IG": 1833,
        "Obligationen Global Hedged": 1167,
    }
    assert sum(bond_weights.values()) == 3000


def test_build_sub_allocations_renormalizes_alternative_splits_after_filtering():
    sub_allocations = _build_sub_allocations(
        targets={
            "equities": 0,
            "bonds": 0,
            "real_estate": 0,
            "alternatives": 600,
            "liquidity": 0,
        },
        preferences={
            "assetClasses": {
                "altsGold": True,
                "altsLiquidAlts": True,
                "altsHedge": True,
                "altsPe": False,
                "altsCrypto": False,
            }
        },
    )

    alt_weights = {
        item["sub_asset_class"]: item["target_weight_bps"]
        for item in sub_allocations
        if item["asset_class"] == "Alternative"
    }

    assert alt_weights == {
        "Gold / Rohstoffe": 320,
        "Liquid Alternatives": 160,
        "Hedge Funds": 120,
    }
    assert sum(alt_weights.values()) == 600


def test_simulate_bucket_path_uses_geometric_growth_and_ignores_zero_bands():
    totals, events = _simulate_bucket_path(
        start_values={
            "equities": 100000,
            "bonds": 0,
            "real_estate": 0,
            "alternatives": 0,
            "liquidity": 0,
        },
        returns_by_asset={
            "equities": 500,
            "bonds": 0,
            "real_estate": 0,
            "alternatives": 0,
            "liquidity": 0,
        },
        vols_by_asset={
            "equities": 1500,
            "bonds": 0,
            "real_estate": 0,
            "alternatives": 0,
            "liquidity": 0,
        },
        cashflow_series_rappen=[0],
        targets={
            "equities": 10000,
            "bonds": 0,
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
            "equities": 0,
            "bonds": 0,
            "real_estate": 0,
            "alternatives": 0,
            "liquidity": 0,
        },
        start_year=2026,
        rebalance_mode="bands",
        transaction_cost_bps=0,
    )

    expected_total = int(round(100000 * math.exp(0.05 - 0.5 * 0.15 * 0.15)))
    assert totals == [100000, expected_total]
    assert events == []


def test_build_live_bucket_drifts_ignores_zero_bands():
    allocation = SimpleNamespace(
        target_equities_bps=10000,
        band_equities_min_bps=0,
        band_equities_max_bps=0,
        target_bonds_bps=0,
        band_bonds_min_bps=0,
        band_bonds_max_bps=0,
        target_real_estate_bps=0,
        band_real_estate_min_bps=0,
        band_real_estate_max_bps=0,
        target_alternatives_bps=0,
        band_alternatives_min_bps=0,
        band_alternatives_max_bps=0,
        target_liquidity_bps=0,
        band_liquidity_min_bps=0,
        band_liquidity_max_bps=0,
    )

    bucket_drifts, breached_asset_classes, _ = _build_live_bucket_drifts(
        allocation=allocation,
        entries=[
            {
                "asset_class": "Aktien",
                "current_market_value_rappen": 100000,
            }
        ],
        live_total_value_rappen=100000,
    )

    equities_bucket = next(item for item in bucket_drifts if item["asset_class"] == "Aktien")
    assert equities_bucket["breached"] is False
    assert equities_bucket["breach_bps"] == 0
    assert breached_asset_classes == []


def test_bucket_expected_metrics_weight_sub_asset_class_tilts():
    cma = _make_cma(
        sub_asset_class_assumptions_json=json.dumps(
            {
                "Aktien Schweiz": {
                    "asset_class": "Aktien",
                    "expected_return_bps": 620,
                    "expected_volatility_bps": 1450,
                },
                "Aktien Global": {
                    "asset_class": "Aktien",
                    "expected_return_bps": 700,
                    "expected_volatility_bps": 1600,
                },
                "Aktien Europa": {
                    "asset_class": "Aktien",
                    "expected_return_bps": 640,
                    "expected_volatility_bps": 1500,
                },
                "Aktien Schwellenlaender": {
                    "asset_class": "Aktien",
                    "expected_return_bps": 760,
                    "expected_volatility_bps": 1800,
                },
            }
        )
    )

    returns, vols = _bucket_expected_metrics(
        cma,
        [
            {"asset_class": "Aktien", "sub_asset_class": "Aktien Schweiz", "target_weight_bps": 4500},
            {"asset_class": "Aktien", "sub_asset_class": "Aktien Global", "target_weight_bps": 4000},
            {"asset_class": "Aktien", "sub_asset_class": "Aktien Schwellenlaender", "target_weight_bps": 1000},
            {"asset_class": "Aktien", "sub_asset_class": "Aktien Europa", "target_weight_bps": 500},
        ],
    )

    assert returns["equities"] == 667
    assert vols["equities"] == 1548


def test_compute_reserve_requirements_matches_goal_and_external_reserve_logic():
    reserve_needed_rappen, external_reserve_rappen = _compute_reserve_requirements(
        goals=[
            SimpleNamespace(
                goal_type="Einmalige_Ausgabe",
                target_amount_rappen=4000000,
                start_date=None,
                target_date=None,
                horizon_years=2,
                is_ongoing=0,
                frequency=None,
                label="Steuern",
            ),
            SimpleNamespace(
                goal_type="Wiederkehrende_Ausgabe",
                target_amount_rappen=2000000,
                start_date=None,
                target_date=None,
                horizon_years=6,
                is_ongoing=0,
                frequency="jährlich",
                label="Ausbildung",
            ),
        ],
        limits_prefs={"minReserve": "10000"},
        asset_class_prefs={"liquidityReserveTarget": "15000"},
        recurring_net_cashflow_rappen=-200000,
        recurring_cashflow_projection_series_rappen=[-100000, -150000, 0],
        advisory_wealth_rappen=10000000,
        saa_liq_ceiling_bps=2000,
    )

    assert reserve_needed_rappen == 4000000
    assert external_reserve_rappen == 2000000


def test_target_allocation_reserve_warning_detects_rebuilt_external_reserve_drift():
    warnings = _target_allocation_reserve_warnings(
        SimpleNamespace(external_reserve_at_generation_rappen=0),
        external_reserve_rappen=2500000,
    )

    assert warnings
    assert "Externer Reservebedarf hat sich seit Allocation-Erstellung" in warnings[0]
    assert "alt: CHF 0" in warnings[0]
    assert "neu: CHF 25'000" in warnings[0]


def test_target_allocation_reserve_warning_skips_legacy_allocations_without_snapshot():
    warnings = _target_allocation_reserve_warnings(
        SimpleNamespace(external_reserve_at_generation_rappen=None),
        external_reserve_rappen=2500000,
    )

    assert warnings == []


def test_target_allocation_context_warns_when_assessment_changed():
    warnings = _target_allocation_context_warnings(
        SimpleNamespace(based_on_assessment_id="assessment-old", capital_market_assumptions_id="cma-1"),
        SimpleNamespace(id="assessment-new"),
        SimpleNamespace(id="cma-1"),
    )

    assert warnings == [
        "Hinweis: Aktuelle Soll-Allokation basiert auf einem frueheren Risikoprofil. Bitte Strategie neu berechnen."
    ]


def test_target_allocation_context_warns_when_cma_changed():
    warnings = _target_allocation_context_warnings(
        SimpleNamespace(based_on_assessment_id="assessment-1", capital_market_assumptions_id="cma-old"),
        SimpleNamespace(id="assessment-1"),
        SimpleNamespace(id="cma-new"),
    )

    assert warnings == [
        "Hinweis: Kapitalmarktannahmen haben sich seit Allocation-Erstellung geaendert. Bitte Strategie neu berechnen."
    ]


def test_implementation_steps_use_actual_bucket_amounts_when_available():
    steps = _implementation_steps(
        [
            {
                "asset_class": "Aktien",
                "delta_weight_bps": 1000,
                "current_amount_rappen": 30_000_000,
                "target_amount_rappen": 32_000_000,
            }
        ],
        target_total_rappen=80_000_000,
    )

    assert steps == ["Aktien aufbauen: ca. CHF 20'000"]


def test_goal_timing_label_uses_normalized_one_time_goal_type():
    goal = SimpleNamespace(
        goal_type=" Einmalige_Ausgabe ",
        start_date="2028-06-30",
        target_date=None,
        frequency=None,
        is_ongoing=0,
    )

    assert _goal_timing_label(goal, years=2) == "am 2028-06-30"


def test_build_bucket_response_uses_investable_target_base_for_target_amounts():
    allocation = SimpleNamespace(
        target_equities_bps=6000,
        band_equities_min_bps=5000,
        band_equities_max_bps=7000,
        target_bonds_bps=4000,
        band_bonds_min_bps=3000,
        band_bonds_max_bps=5000,
        target_real_estate_bps=0,
        band_real_estate_min_bps=0,
        band_real_estate_max_bps=0,
        target_alternatives_bps=0,
        band_alternatives_min_bps=0,
        band_alternatives_max_bps=0,
        target_liquidity_bps=0,
        band_liquidity_min_bps=0,
        band_liquidity_max_bps=0,
    )

    buckets = _build_bucket_response(
        allocation,
        {
            "equities": 600000,
            "bonds": 400000,
            "real_estate": 0,
            "alternatives": 0,
            "liquidity": 0,
        },
        advisory_wealth_rappen=1000000,
        target_base_rappen=800000,
    )

    equities_bucket = next(item for item in buckets if item["asset_class"] == "Aktien")
    bonds_bucket = next(item for item in buckets if item["asset_class"] == "Obligationen")

    assert equities_bucket["current_weight_bps"] == 6000
    assert equities_bucket["target_amount_rappen"] == 480000
    assert bonds_bucket["target_amount_rappen"] == 320000


def test_build_simulation_payload_uses_target_start_value_without_changing_current_path():
    simulation = _build_simulation_payload(
        advisory_summary=PortfolioSummary(
            amounts_rappen={
                "equities": 600000,
                "bonds": 400000,
                "real_estate": 0,
                "alternatives": 0,
                "liquidity": 0,
            },
            total_rappen=1000000,
        ),
        cashflow_projection_series_rappen=[0],
        cma=_make_cma(
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
        ),
        targets={
            "equities": 6000,
            "bonds": 4000,
            "real_estate": 0,
            "alternatives": 0,
            "liquidity": 0,
        },
        minimums={key: 0 for key in portfolio_engine.BUCKET_FIELDS},
        maximums={key: 0 for key in portfolio_engine.BUCKET_FIELDS},
        start_year=2026,
        simulation_prefs={"rebalanceMode": "bands", "transactionCostBps": 0},
        target_start_value_rappen=800000,
    )

    assert simulation["current_mix_series_rappen"][0] == 1000000
    assert simulation["target_mix_series_rappen"][0] == 800000


def test_run_allocation_monte_carlo_uses_target_start_value_for_target_path_and_downside_baseline(monkeypatch):
    monkeypatch.setattr(portfolio_engine, "_monte_carlo_simulations", lambda prefs: 1)

    result = portfolio_engine._run_allocation_monte_carlo(
        advisory_summary=PortfolioSummary(
            amounts_rappen={
                "equities": 600000,
                "bonds": 400000,
                "real_estate": 0,
                "alternatives": 0,
                "liquidity": 0,
            },
            total_rappen=1000000,
        ),
        cashflow_projection_series_rappen=[0],
        goal_inflation_series_bps=[0],
        targets={
            "equities": 6000,
            "bonds": 4000,
            "real_estate": 0,
            "alternatives": 0,
            "liquidity": 0,
        },
        minimums={key: 0 for key in portfolio_engine.BUCKET_FIELDS},
        maximums={key: 0 for key in portfolio_engine.BUCKET_FIELDS},
        cma=_make_cma(
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
        ),
        goals=[],
        advisory_wealth_rappen=800000,
        total_wealth_rappen=1000000,
        policy=None,
        mandate_id="mandate-1",
        simulation_prefs={"transactionCostBps": 0, "rebalanceMode": "bands"},
        start_year=2026,
        target_start_value_rappen=800000,
    )

    assert result["current_p50_series_rappen"][0] == 1000000
    assert result["target_p50_series_rappen"][0] == 800000
    assert result["target_downside_probability_pct"] == 0
