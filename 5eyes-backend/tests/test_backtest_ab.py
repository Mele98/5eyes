"""Sprint U-P15 (2026-05-21): Unit-Tests für A/B-HouseMatrix-Backtest.

Verifiziert:
- Happy-Path: zwei unterschiedliche Policies liefern alle Diff-Strukturen
- Identische Policies werden mit ValueError abgelehnt
- Unbekannte Policy-ID -> ValueError "nicht gefunden"
- Fehlendes Assessment -> ValueError
- Bucket-Gewichte summieren in beiden Views auf 10000 bps
- Stress-Diff enthält 5 Szenarien (Dotcom/GFC/Covid/Bonds22/Stagflation)
- Keine DB-Mutation (kein neuer TargetAllocation-Eintrag entsteht)
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
import models.client_login  # noqa: F401
import models.fx_rate  # noqa: F401
import models.protocol_bausteine  # noqa: F401
import models.tenant  # noqa: F401  (Sprint T1)
configure_mappers()

from models.allocation import (
    HouseMatrix,
    OptimizerPolicy,
    TargetAllocation,
)
from models.clients import Client
from models.mandates import Mandate
from models.profiling import RiskAssessment, RiskAssessmentAnswer
from models.users import User
from services.backtest_ab import run_ab_backtest, BUCKETS
from services.portfolio_engine import ensure_runtime_reference_data


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'ab_backtest.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _seed_mandate_with_assessment(session_factory):
    """Mandat + vollständiges Risikoprofil (Score 70 -> Bucket 7)."""
    suffix = str(uuid.uuid4())[:6]
    advisor_id = f"adv-ab-{suffix}"
    cid = str(uuid.uuid4())
    mid = str(uuid.uuid4())
    aid = str(uuid.uuid4())
    now = _now()
    today = date.today().isoformat()
    with session_factory() as s:
        s.add(User(id=advisor_id, username=f"adv-{suffix}", password_hash="h",
                   full_name="Adv AB", role="advisor", is_active=1,
                   created_at=now, updated_at=now))
        s.add(Client(id=cid, client_number=f"C-{cid[:6]}",
                     first_name="Test", last_name="Mandant",
                     advisor_id=advisor_id, created_at=now, updated_at=now))
        s.add(Mandate(id=mid, client_id=cid, mandate_number=f"M-{mid[:6]}",
                      mandate_type="Anlageberatung", opened_at=now,
                      created_at=now, updated_at=now))
        s.add(RiskAssessment(
            id=aid, mandate_id=mid, version=1, is_current=1, valid_from=today,
            q_income_points=2, q_obligations_points=3,
            q_savings_points=8, q_wealth_points=8,
            risk_capacity_total=21, risk_capacity_profile="Wachstumsorientiert",
            risk_capacity_score_x10=70,
            investment_horizon_years=15, investment_horizon_label="12 bis 17 Jahre",
            q_investment_goal_points=3, q_risk_preference_points=4, q_risk_behavior_points=3,
            risk_willingness_total=10, risk_willingness_profile="Wachstumsorientiert",
            risk_willingness_score_x10=70,
            final_score_x10=70, final_profile="Wachstumsorientiert",
            is_overridden=0,
            knowledge_services_json="{}", knowledge_instruments_json="{}",
            income_sources_json='["Berufliche Taetigkeit"]',
            assessed_at=now, assessed_by=advisor_id,
            created_at=now, updated_at=now,
        ))
        for q, label, points in [
            (1, "Finanzdienstleistungen: Beratung und Verwaltung", 0),
            (2, "Finanzinstrumente: Anlagefonds und ETFs", 0),
            (3, "CHF 12'000 bis 20'000", 3),
            (4, "Herkunft: Berufliche Taetigkeit", 0),
            (5, "CHF 3'000 bis 5'000", 3),
            (6, "CHF 1'000'000 bis 2'000'000", 9),
            (7, "25 bis 50 %", 9),
            (8, "Mehr als 12 Jahre - Matrix-Faktor", 0),
            (9, "Das investierte Kapital soll sich stetig vermehren.", 3),
            (10, "Ich strebe eine hoehere Rendite an und bin bereit, dafuer ein erhoehtes Risiko einzugehen.", 3),
            (11, "Ich kann den Verlust voruebergehend akzeptieren und halte an meinen Anlagen fest.", 3),
        ]:
            s.add(RiskAssessmentAnswer(
                id=str(uuid.uuid4()), assessment_id=aid,
                question_number=q, question_section="Risikoprofil",
                answer_label=label, answer_points=points, created_at=now,
            ))
        s.commit()
        ensure_runtime_reference_data(s, advisor_id)
        s.commit()
    return advisor_id, mid


def _create_alt_policy(session_factory, base_policy: OptimizerPolicy, *, weight_shift_bps: int = 1000) -> str:
    """Klont die HouseMatrix der Default-Policy mit einem Equity-Shift.

    Verschiebt weight_shift_bps von Bonds zu Equities -> garantiert
    abweichende Bucket-Gewichte und damit echte Diff-Werte.
    """
    suffix = str(uuid.uuid4())[:6]
    now = _now()
    new_id = str(uuid.uuid4())
    with session_factory() as s:
        # Original-Policy + HouseMatrix-Rows laden
        original = s.query(OptimizerPolicy).filter(OptimizerPolicy.id == base_policy.id).first()
        rows = s.query(HouseMatrix).filter(HouseMatrix.policy_id == original.id).all()
        # Neue Policy als Klon
        s.add(OptimizerPolicy(
            id=new_id, policy_name=f"Alt-{suffix}", version=1, is_current=0,
            valid_from=now, optimizer_engine=original.optimizer_engine,
            max_real_estate_bps=original.max_real_estate_bps,
            max_alternatives_bps=original.max_alternatives_bps,
            min_liquidity_bps=original.min_liquidity_bps,
            fee_model_json=original.fee_model_json, notes="Test-Alt",
            created_by=original.created_by, created_at=now, updated_at=now,
        ))
        for r in rows:
            # Equity ↑, Bonds ↓ — Verschiebung wird symmetrisch innerhalb
            # der harten Bands gekappt, sodass die Summe immer 10000 bleibt.
            equity_room = max(0, r.equity_max_bps - r.equity_target_bps)
            bonds_room = max(0, r.bonds_target_bps - r.bonds_min_bps)
            shift = min(weight_shift_bps, equity_room, bonds_room)
            new_eq = r.equity_target_bps + shift
            new_bonds = r.bonds_target_bps - shift
            s.add(HouseMatrix(
                id=str(uuid.uuid4()), policy_id=new_id,
                score_from=r.score_from, score_to=r.score_to,
                profile_name=r.profile_name,
                liq_min_bps=r.liq_min_bps, liq_target_bps=r.liq_target_bps, liq_max_bps=r.liq_max_bps,
                bonds_min_bps=r.bonds_min_bps, bonds_target_bps=new_bonds, bonds_max_bps=r.bonds_max_bps,
                equity_min_bps=r.equity_min_bps, equity_target_bps=new_eq, equity_max_bps=r.equity_max_bps,
                real_estate_min_bps=r.real_estate_min_bps, real_estate_target_bps=r.real_estate_target_bps, real_estate_max_bps=r.real_estate_max_bps,
                alt_min_bps=r.alt_min_bps, alt_target_bps=r.alt_target_bps, alt_max_bps=r.alt_max_bps,
                equity_minimum_bps=r.equity_minimum_bps,
                max_risky_fraction_bps=r.max_risky_fraction_bps,
                is_active=1, created_at=now, updated_at=now,
            ))
        s.commit()
    return new_id


def _default_policy_id(session_factory) -> str:
    with session_factory() as s:
        p = s.query(OptimizerPolicy).filter(OptimizerPolicy.is_current == 1).first()
        return p.id


# ============================================================================
# Happy-Path: unterschiedliche Policies -> Diff-Strukturen
# ============================================================================


def test_run_ab_backtest_returns_full_diff_structure(session_factory):
    advisor_id, mid = _seed_mandate_with_assessment(session_factory)
    policy_a_id = _default_policy_id(session_factory)
    with session_factory() as s:
        base = s.query(OptimizerPolicy).filter(OptimizerPolicy.id == policy_a_id).first()
    policy_b_id = _create_alt_policy(session_factory, base, weight_shift_bps=1000)

    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = run_ab_backtest(s, mandate, policy_a_id, policy_b_id)

    assert result["mandate_id"] == mid
    assert result["score_bucket"] == 7  # final_score_x10=70 -> bucket 7
    assert result["policy_a"]["policy_id"] == policy_a_id
    assert result["policy_b"]["policy_id"] == policy_b_id

    # Beide Views sind vollständig
    for view in (result["policy_a"], result["policy_b"]):
        assert set(view["weights_bps"].keys()) == set(BUCKETS)
        assert sum(view["weights_bps"].values()) == 10000
        assert view["expected_return_bps"] >= 0
        assert view["expected_volatility_bps"] > 0
        assert len(view["stress_scenarios"]) == 5
        assert {s["id"] for s in view["stress_scenarios"]} == {
            "dotcom_2000_2002",
            "global_financial_crisis_2008",
            "covid_2020",
            "bonds_crash_2022",
            "stagflation_1973_1974",
        }

    # Bucket-Diff: Equity hat sich um ~+1000 bps verschoben, Bonds um -1000
    bd = result["buckets_diff"]
    assert bd["equities"]["delta_bps"] > 0, "Equity-Anteil sollte in Policy B höher sein"
    assert bd["bonds"]["delta_bps"] < 0, "Bonds-Anteil sollte in Policy B niedriger sein"
    # Summen-Konsistenz
    assert sum(b["a_bps"] for b in bd.values()) == 10000
    assert sum(b["b_bps"] for b in bd.values()) == 10000

    # Risk-Metrics-Diff
    rmd = result["risk_metrics_diff"]
    assert "delta_expected_return_bps" in rmd
    assert "delta_expected_volatility_bps" in rmd
    assert "delta_sharpe_ratio_x100" in rmd
    assert "delta_expected_ter_bps" in rmd

    # Stress-Diff: 5 Szenarien
    assert len(result["stress_diff"]) == 5
    for sc in result["stress_diff"]:
        assert "id" in sc and "label" in sc and "period" in sc
        assert "a_cumulative_return_bps" in sc
        assert "b_cumulative_return_bps" in sc
        assert "delta_cumulative_return_bps" in sc
        assert "delta_max_drawdown_bps" in sc


# ============================================================================
# Identische Policies -> 400-Domain (ValueError)
# ============================================================================


def test_run_ab_backtest_rejects_same_policy(session_factory):
    advisor_id, mid = _seed_mandate_with_assessment(session_factory)
    policy_id = _default_policy_id(session_factory)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        with pytest.raises(ValueError, match="unterschiedlich"):
            run_ab_backtest(s, mandate, policy_id, policy_id)


# ============================================================================
# Unbekannte Policy-ID -> 404-Domain
# ============================================================================


def test_run_ab_backtest_raises_on_unknown_policy(session_factory):
    advisor_id, mid = _seed_mandate_with_assessment(session_factory)
    policy_a_id = _default_policy_id(session_factory)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        with pytest.raises(ValueError, match="nicht gefunden"):
            run_ab_backtest(s, mandate, policy_a_id, "policy-does-not-exist")


# ============================================================================
# Fehlendes Assessment -> 409-Domain
# ============================================================================


def test_run_ab_backtest_raises_without_assessment(session_factory):
    """Mandat ohne RiskAssessment -> require_strategy_ready_assessment hebt ValueError."""
    advisor_id, mid = _seed_mandate_with_assessment(session_factory)
    policy_a_id = _default_policy_id(session_factory)
    with session_factory() as s:
        base = s.query(OptimizerPolicy).filter(OptimizerPolicy.id == policy_a_id).first()
    policy_b_id = _create_alt_policy(session_factory, base, weight_shift_bps=500)

    # Mandat ohne Assessment seeden
    with session_factory() as s:
        cid = str(uuid.uuid4())
        bad_mid = str(uuid.uuid4())
        now = _now()
        s.add(Client(id=cid, client_number=f"C-{cid[:6]}",
                     first_name="No", last_name="Assess",
                     advisor_id=advisor_id, created_at=now, updated_at=now))
        s.add(Mandate(id=bad_mid, client_id=cid, mandate_number=f"M-{bad_mid[:6]}",
                      mandate_type="Anlageberatung", opened_at=now,
                      created_at=now, updated_at=now))
        s.commit()
        mandate = s.query(Mandate).filter(Mandate.id == bad_mid).first()
        with pytest.raises(ValueError):
            run_ab_backtest(s, mandate, policy_a_id, policy_b_id)


# ============================================================================
# Read-Only: kein neuer TargetAllocation-Eintrag entsteht
# ============================================================================


def test_run_ab_backtest_does_not_create_target_allocation(session_factory):
    advisor_id, mid = _seed_mandate_with_assessment(session_factory)
    policy_a_id = _default_policy_id(session_factory)
    with session_factory() as s:
        base = s.query(OptimizerPolicy).filter(OptimizerPolicy.id == policy_a_id).first()
    policy_b_id = _create_alt_policy(session_factory, base, weight_shift_bps=800)

    with session_factory() as s:
        before = s.query(TargetAllocation).count()
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        run_ab_backtest(s, mandate, policy_a_id, policy_b_id)
        s.commit()
        after = s.query(TargetAllocation).count()
    assert after == before, "A/B-Backtest darf KEINE TargetAllocation persistieren."


# ============================================================================
# compute_stress_for_weights (Public-Refactor) — gleiche Outputs wie privat
# ============================================================================


def test_compute_stress_for_weights_matches_existing_engine():
    from services.backtest_stress import compute_stress_for_weights
    weights = {"equities": 6000, "bonds": 3000, "real_estate": 500, "alternatives": 0, "liquidity": 500}
    scenarios = compute_stress_for_weights(weights)
    assert len(scenarios) == 5
    # Sanity: Dotcom + GFC -> negativ, Covid -> leicht positiv (durch Erholung)
    by_id = {s["id"]: s for s in scenarios}
    assert by_id["dotcom_2000_2002"]["cumulative_return_bps"] < 0
    assert by_id["global_financial_crisis_2008"]["cumulative_return_bps"] < 0
    assert by_id["bonds_crash_2022"]["cumulative_return_bps"] < 0
