"""Sprint U-P17 (2026-05-21): Unit-Tests fuer Strategie-Backtest (Annual MVP).

Verifiziert:
- compound_wealth_path mit bekannten Returns (Rebal vs No-Rebal)
- compute_metrics: CAGR / Vol / Sharpe / Max-Drawdown / Best+Worst Year /
  Win-Rate / Total-Return aus determistischen Inputs
- compute_drawdown_path_bps: 0 wenn nur steigend, negativ nach Crash
- load_annual_returns_matrix filtert unvollstaendige Jahre
- _normalize_benchmark_weights: Summen-Normalisierung
- run_strategy_backtest happy-path (mit TA + Annual-Returns + Benchmark)
- run_strategy_backtest defensive paths: keine TA, keine Annual-Returns,
  Zeitraum ohne Daten
- Read-only: keine DB-Mutation
"""
from __future__ import annotations

import datetime
import sys
import uuid
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, configure_mappers

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
configure_mappers()

from models.allocation import OptimizerPolicy, TargetAllocation
from models.clients import Client
from models.mandates import Mandate
from models.snapshots import AssetClassAnnualReturn
from models.users import User
from models.wealth import WealthPosition
from services.backtest_strategy import (
    BUCKETS,
    _normalize_benchmark_weights,
    compound_wealth_path,
    compute_drawdown_path_bps,
    compute_metrics,
    load_annual_returns_matrix,
    run_strategy_backtest,
)


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'bt_strategy.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


# ============================================================================
# compound_wealth_path
# ============================================================================


def test_compound_wealth_path_rebal_60_40_constant_returns():
    """60/40 mit Aktien +10%, Bonds +5% jedes Jahr -> 8% p.a. mit Rebal."""
    weights = {"equities": 6000, "bonds": 4000, "real_estate": 0, "alternatives": 0, "liquidity": 0}
    years = [(2020, {"equities": 1000, "bonds": 500, "real_estate": 0, "alternatives": 0, "liquidity": 0})] * 3
    years = [(2020 + i, y[1]) for i, y in enumerate(years)]
    result = compound_wealth_path(100_000_00, weights, years, rebalance=True)
    assert result["annual_returns_bps"] == [800, 800, 800]
    # 100k * 1.08^3 = 125'971.20
    end = result["wealth_path_rappen"][-1][1]
    assert abs(end - 125_971_20) <= 100  # erlaubt Rundungsdrift in Rappen
    # Initial-Eintrag = 100k im Jahr 2019 (Jahr VOR erstem Year)
    assert result["wealth_path_rappen"][0] == (2019, 100_000_00)


def test_compound_wealth_path_no_rebal_drift():
    """Ohne Rebal: nach 3 Jahren ist Aktien-Anteil hoeher als 60%."""
    weights = {"equities": 6000, "bonds": 4000, "real_estate": 0, "alternatives": 0, "liquidity": 0}
    years = [(2020 + i, {"equities": 1000, "bonds": 500, "real_estate": 0, "alternatives": 0, "liquidity": 0}) for i in range(3)]
    result = compound_wealth_path(100_000_00, weights, years, rebalance=False)
    # Initial-Eintrag erhalten
    assert result["wealth_path_rappen"][0][1] == 100_000_00
    # Annual-Returns sollten NICHT konstant 800 sein (drift)
    assert result["annual_returns_bps"][0] == 800  # erstes Jahr noch sauber
    assert result["annual_returns_bps"][1] > 800   # Aktien-Anteil gewachsen
    assert result["annual_returns_bps"][2] > result["annual_returns_bps"][1]
    # End-Wealth bei NoRebal > Rebal weil Aktien overperformen
    rebal_result = compound_wealth_path(100_000_00, weights, years, rebalance=True)
    assert result["wealth_path_rappen"][-1][1] > rebal_result["wealth_path_rappen"][-1][1]


def test_compound_wealth_path_negative_returns_compound_correctly():
    """Aktien -30%, Bonds 0% -> 60/40 verliert 18% im ersten Jahr."""
    weights = {"equities": 6000, "bonds": 4000, "real_estate": 0, "alternatives": 0, "liquidity": 0}
    years = [(2008, {"equities": -3000, "bonds": 0, "real_estate": 0, "alternatives": 0, "liquidity": 0})]
    result = compound_wealth_path(100_000_00, weights, years, rebalance=True)
    assert result["annual_returns_bps"][0] == -1800  # 0.6 * -0.30 + 0.4 * 0 = -0.18 = -1800 bps
    assert result["wealth_path_rappen"][-1][1] == 82_000_00


def test_compound_wealth_path_raises_on_zero_weights():
    weights = {"equities": 0, "bonds": 0, "real_estate": 0, "alternatives": 0, "liquidity": 0}
    years = [(2020, {b: 0 for b in BUCKETS})]
    with pytest.raises(ValueError, match="0"):
        compound_wealth_path(100_000_00, weights, years, rebalance=True)


# ============================================================================
# compute_metrics
# ============================================================================


def test_compute_metrics_constant_growth_8pct():
    """3-Jahre konstantes 8% Wachstum -> CAGR 800, Vol 0, MaxDD 0, WinRate 100%."""
    path = [(2019, 100_000_00), (2020, 108_000_00), (2021, 116_640_00), (2022, 125_971_20)]
    rets = [800, 800, 800]
    m = compute_metrics(path, rets)
    assert m["cagr_bps"] == 800
    assert m["vol_bps"] == 0
    assert m["max_drawdown_bps"] == 0
    assert m["best_year_bps"] == 800
    assert m["worst_year_bps"] == 800
    assert m["positive_years"] == 3
    assert m["negative_years"] == 0
    assert m["win_rate_x100"] == 10000
    assert m["years_count"] == 3
    assert m["best_year_label"] == 2020
    assert m["start_value_rappen"] == 100_000_00
    assert m["end_value_rappen"] == 125_971_20


def test_compute_metrics_max_drawdown_after_crash():
    """Path: 100 -> 110 -> 70 -> 90 -> Peak war 110, Tief 70 -> DD = (110-70)/110 = 36.36%."""
    path = [(2019, 100_000_00), (2020, 110_000_00), (2021, 70_000_00), (2022, 90_000_00)]
    rets = [1000, -3636, 2857]
    m = compute_metrics(path, rets)
    assert m["max_drawdown_bps"] == 3636
    assert m["best_year_label"] == 2022
    assert m["worst_year_label"] == 2021
    assert m["positive_years"] == 2
    assert m["negative_years"] == 1
    assert m["win_rate_x100"] == int(round(2/3 * 10000))


def test_compute_metrics_empty_input():
    m = compute_metrics([], [])
    assert m["cagr_bps"] == 0
    assert m["years_count"] == 0
    assert m["best_year_label"] is None


def test_compute_metrics_sharpe_with_vol():
    """Vol = 2000 bps, CAGR = 800 bps, RF = 80 -> Sharpe = (800-80)/2000 = 0.36 -> 36 x100."""
    # Construct returns so that mean=800 and stddev ≈ 2000
    rets = [2800, -1200, 2800, -1200]  # mean = 800; sample std ≈ 2309
    # synthetic path that satisfies start/end for CAGR=8%
    n = len(rets)
    end_val = int(round(100_000_00 * (1.08 ** n)))
    path = [(2019 + i, 100_000_00) for i in range(n+1)]
    path[-1] = (path[-1][0], end_val)
    m = compute_metrics(path, rets)
    assert m["vol_bps"] > 0
    assert m["sharpe_x100"] != 0  # nicht zero division


# ============================================================================
# Drawdown-Pfad
# ============================================================================


def test_drawdown_path_zero_when_only_rising():
    path = [(2019, 100_000_00), (2020, 108_000_00), (2021, 116_000_00)]
    dd = compute_drawdown_path_bps(path)
    assert dd == [
        {"year": 2019, "drawdown_bps": 0},
        {"year": 2020, "drawdown_bps": 0},
        {"year": 2021, "drawdown_bps": 0},
    ]


def test_drawdown_path_negative_after_crash():
    path = [(2019, 100_000_00), (2020, 120_000_00), (2021, 60_000_00)]
    dd = compute_drawdown_path_bps(path)
    assert dd[0]["drawdown_bps"] == 0
    assert dd[1]["drawdown_bps"] == 0
    # Peak 120k, Wert 60k -> dd = (60-120)/120 = -50% = -5000bps
    assert dd[2]["drawdown_bps"] == -5000


# ============================================================================
# Datenquellen-Helper
# ============================================================================


def test_load_annual_returns_matrix_filters_incomplete_years(session_factory):
    now = _now()
    with session_factory() as s:
        # Vollstaendiges Jahr 2020 (alle 5)
        for ac in ["Aktien", "Obligationen", "Immobilien", "Alternative", "Liquiditaet"]:
            s.add(AssetClassAnnualReturn(id=str(uuid.uuid4()), year=2020,
                                         asset_class=ac, return_bps=500,
                                         source="t", created_at=now, updated_at=now))
        # Unvollstaendiges Jahr 2021 (nur 3)
        for ac in ["Aktien", "Obligationen", "Immobilien"]:
            s.add(AssetClassAnnualReturn(id=str(uuid.uuid4()), year=2021,
                                         asset_class=ac, return_bps=300,
                                         source="t", created_at=now, updated_at=now))
        s.commit()
        matrix = load_annual_returns_matrix(s)
    assert 2020 in matrix
    assert 2021 not in matrix  # incomplete -> filtered out
    assert set(matrix[2020].keys()) == set(BUCKETS)


# ============================================================================
# Benchmark-Normalisierung
# ============================================================================


def test_normalize_benchmark_weights_already_100():
    norm = _normalize_benchmark_weights({"equities": 6000, "bonds": 4000})
    assert sum(norm.values()) == 10000
    assert norm["equities"] == 6000
    assert norm["bonds"] == 4000


def test_normalize_benchmark_weights_scales_to_100():
    norm = _normalize_benchmark_weights({"equities": 60, "bonds": 40})
    assert sum(norm.values()) == 10000
    # 60% / 40% (rounded)
    assert abs(norm["equities"] - 6000) <= 1
    assert abs(norm["bonds"] - 4000) <= 1


def test_normalize_benchmark_weights_none_when_empty():
    assert _normalize_benchmark_weights(None) is None
    assert _normalize_benchmark_weights({}) is None
    assert _normalize_benchmark_weights({"equities": 0, "bonds": 0}) is None


# ============================================================================
# run_strategy_backtest — End-to-End
# ============================================================================


def _seed_backtest_fixture(session_factory, *, with_annual_returns: bool = True,
                            advisory_wealth_rappen: int = 500_000_00):
    """Mandant + Policy + TargetAllocation + (optional) Annual-Returns."""
    suffix = str(uuid.uuid4())[:6]
    advisor_id = f"adv-{suffix}"
    cid = str(uuid.uuid4())
    mid = str(uuid.uuid4())
    ta_id = str(uuid.uuid4())
    pid = str(uuid.uuid4())
    now = _now()
    with session_factory() as s:
        s.add(User(id=advisor_id, username=f"adv-{suffix}", password_hash="h",
                   full_name="Adv BT", role="advisor", is_active=1,
                   created_at=now, updated_at=now))
        s.add(Client(id=cid, client_number=f"C-{cid[:6]}",
                     first_name="Test", last_name="BT",
                     advisor_id=advisor_id, created_at=now, updated_at=now))
        s.add(Mandate(id=mid, client_id=cid, mandate_number=f"M-{mid[:6]}",
                      mandate_type="Anlageberatung", opened_at=now,
                      created_at=now, updated_at=now))
        s.add(OptimizerPolicy(id=pid, policy_name="T", version=1, is_current=1,
                              valid_from=now, optimizer_engine="goal_based_v1",
                              max_real_estate_bps=2000, max_alternatives_bps=1000,
                              min_liquidity_bps=0, created_by=advisor_id,
                              created_at=now, updated_at=now))
        s.add(TargetAllocation(
            id=ta_id, mandate_id=mid, version=1, is_current=1,
            target_equities_bps=6000, target_bonds_bps=3000,
            target_real_estate_bps=500, target_alternatives_bps=0,
            target_liquidity_bps=500,
            band_equities_min_bps=4500, band_equities_max_bps=7500,
            band_bonds_min_bps=1500, band_bonds_max_bps=4500,
            band_real_estate_min_bps=0, band_real_estate_max_bps=2000,
            band_alternatives_min_bps=0, band_alternatives_max_bps=1000,
            band_liquidity_min_bps=200, band_liquidity_max_bps=2000,
            advisory_wealth_at_generation_rappen=advisory_wealth_rappen,
            policy_id=pid, set_by=advisor_id, set_at=now,
            created_at=now, updated_at=now,
        ))
        if with_annual_returns:
            # 4 Jahre Daten: 2018-2021 mit realistisch wirkenden Returns
            data = [
                (2018, {"Aktien": -1000, "Obligationen": 100, "Immobilien": -500, "Alternative": -300, "Liquiditaet": 50}),
                (2019, {"Aktien": 2800, "Obligationen": 600, "Immobilien": 1500, "Alternative": 1000, "Liquiditaet": 40}),
                (2020, {"Aktien": 1500, "Obligationen": 700, "Immobilien": -200, "Alternative": 800, "Liquiditaet": 20}),
                (2021, {"Aktien": 2200, "Obligationen": -150, "Immobilien": 2400, "Alternative": 1200, "Liquiditaet": 10}),
            ]
            for yr, returns in data:
                for ac_de, bps in returns.items():
                    s.add(AssetClassAnnualReturn(
                        id=str(uuid.uuid4()), year=yr, asset_class=ac_de,
                        return_bps=bps, source="test",
                        created_at=now, updated_at=now,
                    ))
        s.commit()
    return mid


def test_run_strategy_backtest_happy_path(session_factory):
    mid = _seed_backtest_fixture(session_factory)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = run_strategy_backtest(s, mandate)
    assert result["mandate_id"] == mid
    assert result["initial_value_rappen"] == 500_000_00
    assert result["available_years"] == [2018, 2019, 2020, 2021]
    assert result["start_year"] == 2018
    assert result["end_year"] == 2021
    assert result["soll"] is not None
    assert result["benchmark"] is None
    # Beide Varianten enthalten
    assert "rebalanced" in result["soll"]
    assert "no_rebalance" in result["soll"]
    # Metriken-Block ist nicht leer
    m_reb = result["soll"]["rebalanced"]["metrics"]
    assert m_reb["years_count"] == 4
    assert m_reb["start_value_rappen"] == 500_000_00
    # Wealth-Pfad inkl. Initial-Eintrag (2017 = year-before)
    assert result["soll"]["rebalanced"]["wealth_path_rappen"][0][0] == 2017
    assert len(result["soll"]["rebalanced"]["wealth_path_rappen"]) == 5  # 4 years + initial


def test_run_strategy_backtest_with_benchmark(session_factory):
    mid = _seed_backtest_fixture(session_factory)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = run_strategy_backtest(
            s, mandate, benchmark_weights_bps={"equities": 6000, "bonds": 4000},
        )
    assert result["benchmark"] is not None
    bm_w = result["benchmark"]["weights_bps"]
    assert bm_w["equities"] == 6000
    assert bm_w["bonds"] == 4000
    assert sum(bm_w.values()) == 10000
    # Benchmark hat seinen eigenen Pfad
    assert len(result["benchmark"]["rebalanced"]["wealth_path_rappen"]) == 5


def test_run_strategy_backtest_custom_year_range(session_factory):
    mid = _seed_backtest_fixture(session_factory)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = run_strategy_backtest(s, mandate, start_year=2019, end_year=2020)
    assert result["start_year"] == 2019
    assert result["end_year"] == 2020
    assert result["soll"]["rebalanced"]["metrics"]["years_count"] == 2
    # Available years unverandert (zeigt was insgesamt da ist)
    assert result["available_years"] == [2018, 2019, 2020, 2021]


def test_run_strategy_backtest_no_ta_returns_warning(session_factory):
    suffix = str(uuid.uuid4())[:6]
    now = _now()
    advisor_id = f"adv-{suffix}"
    cid = str(uuid.uuid4())
    mid = str(uuid.uuid4())
    with session_factory() as s:
        s.add(User(id=advisor_id, username=f"adv-{suffix}", password_hash="h",
                   full_name="Adv", role="advisor", is_active=1,
                   created_at=now, updated_at=now))
        s.add(Client(id=cid, client_number=f"C-{cid[:6]}",
                     first_name="No", last_name="TA",
                     advisor_id=advisor_id, created_at=now, updated_at=now))
        s.add(Mandate(id=mid, client_id=cid, mandate_number=f"M-{mid[:6]}",
                      mandate_type="Anlageberatung", opened_at=now,
                      created_at=now, updated_at=now))
        s.commit()
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = run_strategy_backtest(s, mandate)
    assert result["soll"] is None
    assert any("Target-Allocation" in w for w in result["warnings"])


def test_run_strategy_backtest_no_annual_returns_returns_warning(session_factory):
    mid = _seed_backtest_fixture(session_factory, with_annual_returns=False)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = run_strategy_backtest(s, mandate)
    assert result["soll"] is None
    assert result["available_years"] == []
    assert any("Jahresrenditen" in w for w in result["warnings"])


def test_run_strategy_backtest_year_range_with_no_data_returns_warning(session_factory):
    mid = _seed_backtest_fixture(session_factory)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = run_strategy_backtest(s, mandate, start_year=2030, end_year=2040)
    assert result["soll"] is None
    assert any("Zeitraum" in w for w in result["warnings"])
    assert result["available_years"] == [2018, 2019, 2020, 2021]


def test_run_strategy_backtest_fallback_to_wealth_positions_for_initial(session_factory):
    """advisory_wealth_at_generation_rappen=0 -> fallback auf WealthPosition-Summe."""
    suffix = str(uuid.uuid4())[:6]
    now = _now()
    advisor_id = f"adv-{suffix}"
    cid = str(uuid.uuid4())
    mid = str(uuid.uuid4())
    ta_id = str(uuid.uuid4())
    pid = str(uuid.uuid4())
    with session_factory() as s:
        s.add(User(id=advisor_id, username=f"adv-{suffix}", password_hash="h",
                   full_name="Adv", role="advisor", is_active=1,
                   created_at=now, updated_at=now))
        s.add(Client(id=cid, client_number=f"C-{cid[:6]}",
                     first_name="Fb", last_name="Wealth",
                     advisor_id=advisor_id, created_at=now, updated_at=now))
        s.add(Mandate(id=mid, client_id=cid, mandate_number=f"M-{mid[:6]}",
                      mandate_type="Anlageberatung", opened_at=now,
                      created_at=now, updated_at=now))
        s.add(OptimizerPolicy(id=pid, policy_name="T", version=1, is_current=1,
                              valid_from=now, optimizer_engine="goal_based_v1",
                              max_real_estate_bps=2000, max_alternatives_bps=1000,
                              min_liquidity_bps=0, created_by=advisor_id,
                              created_at=now, updated_at=now))
        s.add(TargetAllocation(
            id=ta_id, mandate_id=mid, version=1, is_current=1,
            target_equities_bps=5000, target_bonds_bps=3000,
            target_real_estate_bps=0, target_alternatives_bps=0,
            target_liquidity_bps=2000,
            band_equities_min_bps=4000, band_equities_max_bps=6000,
            band_bonds_min_bps=2000, band_bonds_max_bps=4000,
            band_real_estate_min_bps=0, band_real_estate_max_bps=1000,
            band_alternatives_min_bps=0, band_alternatives_max_bps=500,
            band_liquidity_min_bps=1000, band_liquidity_max_bps=3000,
            advisory_wealth_at_generation_rappen=0,  # explizit 0
            policy_id=pid, set_by=advisor_id, set_at=now,
            created_at=now, updated_at=now,
        ))
        s.add(WealthPosition(
            id=str(uuid.uuid4()), client_id=cid, label="Depot",
            position_type="Depot", assignment="Beratungsvermögen",
            current_value_rappen=250_000_00, currency="CHF",
            alloc_equities_bps=5000, alloc_bonds_bps=3000,
            alloc_real_estate_bps=0, alloc_alternatives_bps=0,
            alloc_liquidity_bps=2000,
            is_active=1, created_at=now, updated_at=now,
        ))
        # Annual-Returns
        for ac in ["Aktien", "Obligationen", "Immobilien", "Alternative", "Liquiditaet"]:
            s.add(AssetClassAnnualReturn(
                id=str(uuid.uuid4()), year=2020, asset_class=ac, return_bps=500,
                source="t", created_at=now, updated_at=now,
            ))
        s.commit()
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = run_strategy_backtest(s, mandate)
    assert result["initial_value_rappen"] == 250_000_00


def test_run_strategy_backtest_does_not_mutate_db(session_factory):
    mid = _seed_backtest_fixture(session_factory)
    with session_factory() as s:
        ta_count_before = s.query(TargetAllocation).count()
        ar_count_before = s.query(AssetClassAnnualReturn).count()
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        run_strategy_backtest(s, mandate, benchmark_weights_bps={"equities": 10000})
        s.commit()
        ta_count_after = s.query(TargetAllocation).count()
        ar_count_after = s.query(AssetClassAnnualReturn).count()
    assert ta_count_before == ta_count_after
    assert ar_count_before == ar_count_after
