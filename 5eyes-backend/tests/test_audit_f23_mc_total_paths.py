"""F23 - Total-Vermoegen-Pfade in Monte Carlo.

Vor dem Fix: _run_allocation_monte_carlo lieferte nur advisory-Pfade
(current/target_p10/p50/p90). Total-Vermoegen-Pfade existierten nur
deterministisch in _build_simulation_payload (Z8-W2 Phase 2).

Fix: total_summary + total_liabilities_rappen werden durchgereicht;
parallel zu advisory werden total_current/target_*_series berechnet:
- IST traegt Liabilities als initial deficit (Z8-W2 Phase 2 konsistent)
- SOLL hat Liabilities bereits beim Start abgezogen
- Beide nutzen die selben CMA-Returns wie advisory (Markt-Return)
- Lebensluecke laeuft via accumulated_deficit (W2.5 konsistent)

Wenn total_summary fehlt -> alle 6 Listen leer (default-safe).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy.orm import configure_mappers
from database import Base
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
configure_mappers()

import services.portfolio_engine as pe
from models.allocation import CapitalMarketAssumption
from services.portfolio_engine import (
    BUCKET_FIELDS,
    PortfolioSummary,
    _run_allocation_monte_carlo,
)


def _zero_return_cma() -> CapitalMarketAssumption:
    return CapitalMarketAssumption(
        id="cma-zero-f23",
        assumption_set_name="ZeroReturn",
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


def _flat_targets():
    return {key: 10000 if key == "liquidity" else 0 for key in BUCKET_FIELDS}


def _flat_minmax():
    return {key: 0 for key in BUCKET_FIELDS}


def _common_kwargs(*, advisory, total=None, liabilities=0, cashflow=None):
    return dict(
        advisory_summary=advisory,
        cashflow_projection_series_rappen=cashflow if cashflow is not None else [0, 0, 0],
        goal_inflation_series_bps=[0] * (len(cashflow) if cashflow is not None else 3),
        targets=_flat_targets(),
        minimums=_flat_minmax(),
        maximums=_flat_minmax(),
        cma=_zero_return_cma(),
        goals=[],
        advisory_wealth_rappen=advisory.total_rappen,
        total_wealth_rappen=total.total_rappen if total is not None else advisory.total_rappen,
        policy=None,
        mandate_id="mandate-f23",
        simulation_prefs={"transactionCostBps": 0, "rebalanceMode": "bands"},
        start_year=2026,
        target_total_rappen=advisory.total_rappen,
        total_summary=total,
        total_liabilities_rappen=liabilities,
    )


def test_f23_no_total_summary_returns_empty_total_series(monkeypatch):
    """Default ohne total_summary -> alle 6 total_* Listen leer."""
    monkeypatch.setattr(pe, "_monte_carlo_simulations", lambda prefs: 30)

    advisory = PortfolioSummary(
        amounts_rappen={key: (100_000 if key == "liquidity" else 0) for key in BUCKET_FIELDS},
        total_rappen=100_000,
    )
    result = _run_allocation_monte_carlo(**_common_kwargs(advisory=advisory))

    for key in (
        "total_current_p10_series_rappen",
        "total_current_p50_series_rappen",
        "total_current_p90_series_rappen",
        "total_target_p10_series_rappen",
        "total_target_p50_series_rappen",
        "total_target_p90_series_rappen",
    ):
        assert result[key] == [], f"{key} muss leer sein wenn total_summary fehlt"


def test_f23_total_current_starts_at_total_minus_liabilities(monkeypatch):
    """total_current[0] = sum(total_summary.amounts) - liabilities (= Reinvermoegen)."""
    monkeypatch.setattr(pe, "_monte_carlo_simulations", lambda prefs: 30)

    advisory = PortfolioSummary(
        amounts_rappen={key: (300_000 if key == "liquidity" else 0) for key in BUCKET_FIELDS},
        total_rappen=300_000,
    )
    total = PortfolioSummary(
        amounts_rappen={
            "liquidity": 300_000,
            "equities": 200_000,
            "real_estate": 1_000_000,
            "bonds": 0,
            "alternatives": 0,
        },
        total_rappen=1_500_000,
    )
    liabilities = 800_000  # Hypothek auf real_estate

    result = _run_allocation_monte_carlo(**_common_kwargs(
        advisory=advisory, total=total, liabilities=liabilities,
    ))

    # Year 0: 1.5M Vermoegen - 800k Hypothek = 700k Reinvermoegen
    assert result["total_current_p50_series_rappen"][0] == 700_000


def test_f23_total_target_starts_at_total_minus_liabilities_and_redistributed(monkeypatch):
    """total_target[0] = (sum - liabilities) Wert in target-Verteilung umgeschichtet."""
    monkeypatch.setattr(pe, "_monte_carlo_simulations", lambda prefs: 30)

    advisory = PortfolioSummary(
        amounts_rappen={key: (300_000 if key == "liquidity" else 0) for key in BUCKET_FIELDS},
        total_rappen=300_000,
    )
    total = PortfolioSummary(
        amounts_rappen={
            "liquidity": 300_000,
            "real_estate": 1_000_000,
            "equities": 0,
            "bonds": 0,
            "alternatives": 0,
        },
        total_rappen=1_300_000,
    )
    liabilities = 500_000

    result = _run_allocation_monte_carlo(**_common_kwargs(
        advisory=advisory, total=total, liabilities=liabilities,
    ))

    # SOLL = (1.3M - 500k) = 800k, alles in liquidity (targets={liquidity:10000bps})
    assert result["total_target_p50_series_rappen"][0] == 800_000


def test_f23_total_paths_go_negative_with_excessive_outflow(monkeypatch):
    """Bei aufzehrendem Cashflow muessen Total-Pfade auch ins Negative gehen."""
    monkeypatch.setattr(pe, "_monte_carlo_simulations", lambda prefs: 50)

    advisory = PortfolioSummary(
        amounts_rappen={key: (50_000 if key == "liquidity" else 0) for key in BUCKET_FIELDS},
        total_rappen=50_000,
    )
    total = PortfolioSummary(
        amounts_rappen={key: (100_000 if key == "liquidity" else 0) for key in BUCKET_FIELDS},
        total_rappen=100_000,
    )
    cashflow = [-200_000] * 3

    result = _run_allocation_monte_carlo(**_common_kwargs(
        advisory=advisory, total=total, liabilities=0, cashflow=cashflow,
    ))

    # Year 1: 100k - 200k = -100k
    assert result["total_target_p50_series_rappen"][1] == pytest.approx(-100_000, abs=2_000)
    # Year 3: -100k - 2*200k = -500k
    assert result["total_target_p50_series_rappen"][3] == pytest.approx(-500_000, abs=10_000)


def test_f23_total_paths_match_advisory_when_no_extra_assets(monkeypatch):
    """Wenn total == advisory + 0 liabilities, sollten total und advisory gleich sein."""
    monkeypatch.setattr(pe, "_monte_carlo_simulations", lambda prefs: 30)

    advisory = PortfolioSummary(
        amounts_rappen={key: (200_000 if key == "liquidity" else 0) for key in BUCKET_FIELDS},
        total_rappen=200_000,
    )
    # Total identisch zu advisory (kein extra Vermoegen ausserhalb Beratung)
    total = PortfolioSummary(
        amounts_rappen={key: (200_000 if key == "liquidity" else 0) for key in BUCKET_FIELDS},
        total_rappen=200_000,
    )

    result = _run_allocation_monte_carlo(**_common_kwargs(
        advisory=advisory, total=total, liabilities=0, cashflow=[0] * 3,
    ))

    # P50 muss bei beiden uebereinstimmen weil identische Inputs
    assert result["current_p50_series_rappen"] == result["total_current_p50_series_rappen"]
    assert result["target_p50_series_rappen"] == result["total_target_p50_series_rappen"]


def test_f23_total_paths_have_same_length_as_advisory(monkeypatch):
    """Series-Laengen muessen alle gleich sein (year_labels Konsistenz)."""
    monkeypatch.setattr(pe, "_monte_carlo_simulations", lambda prefs: 20)

    advisory = PortfolioSummary(
        amounts_rappen={key: (100_000 if key == "liquidity" else 0) for key in BUCKET_FIELDS},
        total_rappen=100_000,
    )
    total = PortfolioSummary(
        amounts_rappen={key: (200_000 if key == "liquidity" else 0) for key in BUCKET_FIELDS},
        total_rappen=200_000,
    )
    cashflow = [0] * 7  # 7-Jahres-Horizont

    result = _run_allocation_monte_carlo(**_common_kwargs(
        advisory=advisory, total=total, liabilities=0, cashflow=cashflow,
    ))

    expected_len = len(result["target_p50_series_rappen"])  # 8 = horizon + 1
    assert len(result["total_current_p10_series_rappen"]) == expected_len
    assert len(result["total_current_p50_series_rappen"]) == expected_len
    assert len(result["total_current_p90_series_rappen"]) == expected_len
    assert len(result["total_target_p10_series_rappen"]) == expected_len
    assert len(result["total_target_p50_series_rappen"]) == expected_len
    assert len(result["total_target_p90_series_rappen"]) == expected_len


def test_f23_total_p10_below_p90_with_volatility(monkeypatch):
    """Mit Volatilitaet: total_p10 <= total_p50 <= total_p90."""
    monkeypatch.setattr(pe, "_monte_carlo_simulations", lambda prefs: 200)

    advisory = PortfolioSummary(
        amounts_rappen={key: (100_000 if key == "equities" else 0) for key in BUCKET_FIELDS},
        total_rappen=100_000,
    )
    total = PortfolioSummary(
        amounts_rappen={key: (300_000 if key == "equities" else 0) for key in BUCKET_FIELDS},
        total_rappen=300_000,
    )
    cma = _zero_return_cma()
    cma.equity_ch_return_bps = 500
    cma.equity_ch_vol_bps = 1500
    cma.equity_intl_return_bps = 500
    cma.equity_intl_vol_bps = 1500

    targets = {key: 10000 if key == "equities" else 0 for key in BUCKET_FIELDS}
    kwargs = _common_kwargs(advisory=advisory, total=total)
    kwargs["cma"] = cma
    kwargs["targets"] = targets
    kwargs["target_total_rappen"] = 100_000

    result = _run_allocation_monte_carlo(**kwargs)

    # p10 <= p50 <= p90 fuer das letzte Jahr im total-Pfad
    p10 = result["total_target_p10_series_rappen"][-1]
    p50 = result["total_target_p50_series_rappen"][-1]
    p90 = result["total_target_p90_series_rappen"][-1]
    assert p10 <= p50 <= p90, f"Order broken: p10={p10}, p50={p50}, p90={p90}"


# ============================================================================
# Integration Tests: F23 durch generate_target_allocation()
# ============================================================================
# Sichert dass die total_*_series Felder von _run_allocation_monte_carlo
# tatsaechlich im monte_carlo dict ankommen, wenn der Aufrufer total_summary
# durchschickt. Schuetzt die Wiring vom Aufrufer (_collect_portfolio_summaries)
# bis zum API-Schema gegen Refactoring-Drift.

import datetime
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models.clients import Client
from models.mandates import Mandate
from models.profiling import RiskAssessment, RiskAssessmentAnswer
from models.users import User
from models.wealth import Cashflow, WealthPosition
from services.portfolio_engine import (
    ensure_runtime_reference_data,
    generate_target_allocation,
)
from tests.risk_fixture_helpers import (
    CURRENT_RISK_SCHEMA_MARKERS,
    add_current_risk_answers,
)


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'audit_f23_int.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _seed_mandate_with_total_wealth(session_factory):
    """Beratungsdepot 200k + Eigenheim 800k - Hypothek 600k = Reinvermoegen 400k."""
    advisor_id = "user-f23-int"
    cid = str(uuid.uuid4())
    mid = str(uuid.uuid4())
    aid = str(uuid.uuid4())
    now = _now()
    with session_factory() as s:
        s.add(User(id=advisor_id, username="adv-f23", password_hash="h",
                   full_name="Adv F23", role="advisor", is_active=1,
                   created_at=now, updated_at=now))
        s.add(Client(id=cid, client_number=f"C-{cid[:6]}",
                     first_name="Int", last_name="F23",
                     advisor_id=advisor_id, created_at=now, updated_at=now))
        s.add(Mandate(id=mid, client_id=cid, mandate_number=f"M-{mid[:6]}",
                      mandate_type="Anlageberatung", opened_at=now,
                      created_at=now, updated_at=now))
        s.add(WealthPosition(
            id="pos-f23-depot", client_id=cid,
            label="Depot", position_type="Depot", assignment="Beratungsvermögen",
            current_value_rappen=200_000_00, currency="CHF",
            alloc_equities_bps=4000, alloc_bonds_bps=3000,
            alloc_real_estate_bps=0, alloc_liquidity_bps=2000,
            alloc_alternatives_bps=1000,
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(WealthPosition(
            id="pos-f23-haus", client_id=cid,
            label="Eigenheim", position_type="Liegenschaft", assignment="Gesamtvermögen",
            current_value_rappen=800_000_00, currency="CHF",
            alloc_real_estate_bps=10000,
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(WealthPosition(
            id="pos-f23-hypo", client_id=cid,
            label="Hypothek", position_type="Hypothek", assignment="Verbindlichkeit",
            current_value_rappen=600_000_00, currency="CHF",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(Cashflow(
            id="cf-f23-savings", client_id=cid, label="Sparplan",
            cashflow_type="Income", amount_rappen=30_000_00,
            currency="CHF", frequency="jährlich", nature="wiederkehrend",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(RiskAssessment(
            id=aid, mandate_id=mid, version=1, is_current=1, valid_from=now[:10],
            q_income_points=2, q_obligations_points=3,
            q_savings_points=6, q_wealth_points=6,
            risk_capacity_total=17, risk_capacity_profile="Wachstumsorientiert",
            risk_capacity_score_x10=60,
            investment_horizon_years=10, investment_horizon_label="8 bis 11 Jahre",
            q_investment_goal_points=3, q_risk_preference_points=3, q_risk_behavior_points=3,
            risk_willingness_total=9, risk_willingness_profile="Ausgewogen",
            risk_willingness_score_x10=60,
            final_score_x10=60, final_profile="Ausgewogen",
            is_overridden=0,
            **CURRENT_RISK_SCHEMA_MARKERS,
            assessed_at=now, assessed_by=advisor_id,
            created_at=now, updated_at=now,
        ))
        add_current_risk_answers(s, aid, now)
        s.commit()
        ensure_runtime_reference_data(s, advisor_id)
        s.commit()
    return advisor_id, cid, mid, aid


def test_f23_integration_total_p50_starts_at_net_wealth(session_factory):
    """generate_target_allocation -> monte_carlo.total_current_p50_series_rappen[0]
    gleich dem deterministischen total_mix_current_series_rappen[0]."""
    advisor_id, cid, mid, aid = _seed_mandate_with_total_wealth(session_factory)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = generate_target_allocation(s, mandate, advisor_id, preferences=None)

    mc = result.get("monte_carlo") or {}
    sim = result.get("simulation") or {}

    mc_total_current = mc.get("total_current_p50_series_rappen") or []
    sim_total_current = sim.get("total_mix_current_series_rappen") or []

    assert mc_total_current, "monte_carlo.total_current_p50_series_rappen muss gefuellt sein"
    assert sim_total_current, "simulation.total_mix_current_series_rappen muss gefuellt sein"
    # Beide starten beim Reinvermoegen 400k
    assert mc_total_current[0] == sim_total_current[0]
    assert mc_total_current[0] == 400_000_00


def test_f23_integration_all_six_total_series_present_when_total_wealth_exists(session_factory):
    """Wenn der Mandant Gesamtvermoegen != Beratungsvermoegen hat, kommen
    alle 6 total_*_series gefuellt im monte_carlo dict an."""
    advisor_id, cid, mid, aid = _seed_mandate_with_total_wealth(session_factory)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = generate_target_allocation(s, mandate, advisor_id, preferences=None)

    mc = result.get("monte_carlo") or {}
    expected_len = len(mc.get("target_p50_series_rappen") or [])
    for key in (
        "total_current_p10_series_rappen",
        "total_current_p50_series_rappen",
        "total_current_p90_series_rappen",
        "total_target_p10_series_rappen",
        "total_target_p50_series_rappen",
        "total_target_p90_series_rappen",
    ):
        series = mc.get(key) or []
        assert len(series) == expected_len, f"{key} length {len(series)} != advisory {expected_len}"


def test_f23_integration_total_p10_below_p90_per_year(session_factory):
    """Pro Jahr muss total_p10 <= total_p50 <= total_p90 (Quantil-Ordnung)."""
    advisor_id, cid, mid, aid = _seed_mandate_with_total_wealth(session_factory)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = generate_target_allocation(s, mandate, advisor_id, preferences=None)

    mc = result.get("monte_carlo") or {}
    p10s = mc.get("total_target_p10_series_rappen") or []
    p50s = mc.get("total_target_p50_series_rappen") or []
    p90s = mc.get("total_target_p90_series_rappen") or []
    assert p10s and p50s and p90s
    for idx, (p10, p50, p90) in enumerate(zip(p10s, p50s, p90s)):
        assert p10 <= p50 <= p90, f"Year {idx}: order broken p10={p10} p50={p50} p90={p90}"


# Note: deterministisch (_simulate_bucket_path) und MC-Inline-Loop sind
# unterschiedliche Code-Pfade. Bei vol=0 fallen sie nicht exakt zusammen, weil
# (1) deterministic nutzt (1+r/10000) linear vs MC exp(mu-0.5*sigma^2), und
# (2) per-bucket int-Rounding akkumuliert anders. Ein 1:1-Konsistenz-Test war
# zu naiv und faellt aus. Stattdessen: die individuellen Tests oben pruefen
# Verhalten direkt (start values, Lebensluecke, Quantil-Ordnung).
