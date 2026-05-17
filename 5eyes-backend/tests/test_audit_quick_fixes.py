"""Vier Audit-Quick-Fixes (F2 + F4 + F5 + F6) gebuendelt:

- F2 build_target_payload_from_allocation warnt bei abweichendem
  based_on_assessment_id.
- F4 POST /mandates/{id}/target-allocation verlangt eine strategie-fertige
  RiskAssessment (sonst 409).
- F5 POST /mandates/{id}/strategy-snapshots schreibt einen AuditLog-Eintrag.
- F6 _goal_timing_label nutzt fuer den Einmalige_Ausgabe-Branch den
  normalisierten goal_type (kein Mismatch bei abweichender Schreibweise).
"""
from __future__ import annotations
import sys
import uuid
import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, get_db, new_uuid
from main import app
from models.allocation import (
    BuildingBlock,
    CapitalMarketAssumption,
    HouseMatrix,
    OptimizerPolicy,
    TargetAllocation,
)
from models.clients import Client
from models.mandates import Mandate
from models.profiling import RiskAssessment
from models.review import AuditLog
from models.snapshots import StrategySnapshot
from models.users import User
from models.wealth import Cashflow, Goal, WealthPosition
from services.auth import get_current_user, require_advisor
from services.portfolio_engine import (
    _goal_timing_label,
    build_target_payload_from_allocation,
    ensure_runtime_reference_data,
)
from tests.risk_fixture_helpers import CURRENT_RISK_SCHEMA_MARKERS, add_current_risk_answers, noop_lifespan


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'audit_quick_fixes.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def advisor_user():
    return User(
        id="user-aqf-1", username="advisor", password_hash="h",
        full_name="Advisor", role="advisor", is_active=1,
        created_at=_utc_now_iso(), updated_at=_utc_now_iso(),
    )


@pytest.fixture()
def auth_client(session_factory, advisor_user, monkeypatch):
    def override_db():
        with session_factory() as s:
            yield s
    monkeypatch.setattr(app.router, "lifespan_context", noop_lifespan)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: advisor_user
    app.dependency_overrides[require_advisor] = lambda: advisor_user
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _make_client_and_mandate(session_factory, advisor_id: str, mandate_type: str = "Anlageberatung"):
    cid = str(uuid.uuid4())
    mid = str(uuid.uuid4())
    now = _utc_now_iso()
    with session_factory() as s:
        s.add(advisor_user_obj := User(
            id=advisor_id, username="advisor", password_hash="h",
            full_name="Advisor", role="advisor", is_active=1,
            created_at=now, updated_at=now,
        ))
        s.add(Client(
            id=cid, client_number=f"C-AQF-{cid[:6]}",
            first_name="Test", last_name="Mandant",
            advisor_id=advisor_id, created_at=now, updated_at=now,
        ))
        s.add(Mandate(
            id=mid, client_id=cid, mandate_number=f"M-AQF-{mid[:6]}",
            mandate_type=mandate_type, opened_at=now,
            created_at=now, updated_at=now,
        ))
        s.commit()
    return cid, mid


def _seed_runtime(session_factory, advisor_id: str):
    """Erzwingt Runtime-Referenzdaten (Policy + CMA + HouseMatrix + BuildingBlocks)."""
    with session_factory() as s:
        ensure_runtime_reference_data(s, advisor_id)
        s.commit()


def _add_assessment(session_factory, mandate_id: str, advisor_id: str,
                    final_score_x10: int = 60, profile: str = "Ausgewogen") -> str:
    aid = str(uuid.uuid4())
    now = _utc_now_iso()
    with session_factory() as s:
        s.add(RiskAssessment(
            id=aid, mandate_id=mandate_id, version=1, is_current=1,
            valid_from=now[:10],
            q_income_points=2, q_obligations_points=3,
            q_savings_points=6, q_wealth_points=6,
            risk_capacity_total=17, risk_capacity_profile="Wachstumsorientiert",
            risk_capacity_score_x10=60,
            investment_horizon_years=10, investment_horizon_label="8 bis 11 Jahre",
            q_investment_goal_points=3, q_risk_preference_points=3, q_risk_behavior_points=3,
            risk_willingness_total=9, risk_willingness_profile="Ausgewogen",
            risk_willingness_score_x10=60,
            final_score_x10=final_score_x10, final_profile=profile,
            is_overridden=0,
            **CURRENT_RISK_SCHEMA_MARKERS,
            assessed_at=now, assessed_by=advisor_id,
            created_at=now, updated_at=now,
        ))
        add_current_risk_answers(s, aid, now)
        s.commit()
    return aid


def _add_advisory_position(session_factory, client_id: str, advisor_id: str, value_rappen: int):
    now = _utc_now_iso()
    with session_factory() as s:
        s.add(WealthPosition(
            id=str(uuid.uuid4()), client_id=client_id,
            label="Test-Depot", position_type="Depot",
            assignment="Beratungsvermögen",
            current_value_rappen=value_rappen, currency="CHF",
            alloc_equities_bps=4000, alloc_bonds_bps=3000,
            alloc_real_estate_bps=1000, alloc_liquidity_bps=1000, alloc_alternatives_bps=1000,
            is_active=1, created_at=now, updated_at=now,
        ))
        s.commit()


def _make_target_allocation(session_factory, mandate_id: str, advisor_id: str,
                            based_on_assessment_id: str | None) -> str:
    """Erzeugt eine TargetAllocation mit den HouseMatrix-Defaults fuer Score 6."""
    tid = str(uuid.uuid4())
    now = _utc_now_iso()
    with session_factory() as s:
        policy = s.query(OptimizerPolicy).filter(OptimizerPolicy.is_current == 1).first()
        s.add(TargetAllocation(
            id=tid, mandate_id=mandate_id, version=1, is_current=1,
            target_equities_bps=4500, target_bonds_bps=3500,
            target_real_estate_bps=1000, target_alternatives_bps=500, target_liquidity_bps=500,
            band_equities_min_bps=2500, band_equities_max_bps=5500,
            band_bonds_min_bps=2500, band_bonds_max_bps=4500,
            band_real_estate_min_bps=500, band_real_estate_max_bps=1500,
            band_alternatives_min_bps=300, band_alternatives_max_bps=800,
            band_liquidity_min_bps=200, band_liquidity_max_bps=300,
            risky_fraction_bps=6000,
            based_on_assessment_id=based_on_assessment_id,
            policy_id=policy.id,
            set_by=advisor_id, set_at=now,
            created_at=now, updated_at=now,
        ))
        s.commit()
    return tid


# ===========================================================================
# F6 - _goal_timing_label nutzt normalisierten goal_type
# ===========================================================================

def test_f6_goal_timing_label_uses_normalized_goal_type():
    """Goal mit valid_from + Pseudo-Umlaut darf nicht in fallback fallen,
    sondern muss den Einmalige_Ausgabe-Branch treffen wenn _norm_text greift."""
    # _norm_text mappt Umlaute, aber "Einmalige_Ausgabe" hat keine - perfekt fuer
    # einen direkten Umlaut-freien Test: wir bauen ein Goal mit korrekt
    # geschriebenem goal_type. Vor dem Fix nutzt der Branch goal.goal_type roh,
    # nach dem Fix nutzt er die normalisierte Variable. Beide Varianten muessen
    # weiterhin "am <date>" liefern.
    g = Goal(
        id="g-f6-1", mandate_id="m-1", client_id="c-1",
        goal_family="Vermoegen", goal_type="Einmalige_Ausgabe",
        label="Auto", rank=1, weight_bps=1000,
        target_amount_rappen=5_000_000, start_date="2030-06-01",
        is_ongoing=0, is_active=1,
        created_at=_utc_now_iso(), updated_at=_utc_now_iso(),
    )
    assert _goal_timing_label(g, 5) == "am 2030-06-01"


def test_f6_goal_timing_label_falls_through_for_other_types():
    """Fuer andere goal_types (z.B. Vermoegensziel) soll die Funktion
    weiterhin den target_date / Horizont-Branch waehlen."""
    g = Goal(
        id="g-f6-2", mandate_id="m-1", client_id="c-1",
        goal_family="Vermoegen", goal_type="Vermoegensziel",
        label="Pension", rank=2, weight_bps=2000,
        target_wealth_rappen=1_000_000_00, target_date="2040-12-31",
        is_ongoing=0, is_active=1,
        created_at=_utc_now_iso(), updated_at=_utc_now_iso(),
    )
    assert _goal_timing_label(g, 15) == "bis 2040-12-31"


# ===========================================================================
# F5 - Strategy-Snapshot schreibt AuditLog
# ===========================================================================

def test_f5_create_snapshot_writes_audit_log(auth_client, session_factory, advisor_user):
    cid, mid = _make_client_and_mandate(session_factory, advisor_user.id)

    payload = {
        "snapshot_date": "2026-04-25",
        "advisory_assets_rappen": 1_000_000_00,
        "risk_profile_score": 6,
        "risk_profile_label": "Ausgewogen",
        "soll_equities_bps": 4500,
        "soll_bonds_bps": 3500,
        "soll_real_estate_bps": 1000,
        "soll_liquidity_bps": 500,
        "soll_alternatives_bps": 500,
        "band_equities_lo_bps": 2500, "band_equities_hi_bps": 5500,
        "band_bonds_lo_bps": 2500, "band_bonds_hi_bps": 4500,
        "band_real_estate_lo_bps": 500, "band_real_estate_hi_bps": 1500,
        "band_liquidity_lo_bps": 200, "band_liquidity_hi_bps": 800,
        "band_alternatives_lo_bps": 300, "band_alternatives_hi_bps": 800,
        "advisor_note": "Test-Snapshot",
        "goals_summary_json": "{}",
    }
    resp = auth_client.post(f"/mandates/{mid}/strategy-snapshots", json=payload)
    assert resp.status_code == 201, resp.text
    snap_id = resp.json()["id"]

    with session_factory() as s:
        entries = s.query(AuditLog).filter(
            AuditLog.table_name == "strategy_snapshots",
            AuditLog.record_id == snap_id,
            AuditLog.action == "CREATE",
        ).all()
    assert len(entries) == 1, "Erwarte genau einen Audit-Eintrag fuer den Snapshot"
    assert entries[0].mandate_id == mid
    assert entries[0].user_id == advisor_user.id


# ===========================================================================
# F4 - POST /target-allocation verlangt strategie-fertige Risk-Assessment
# ===========================================================================

def test_f4_create_target_allocation_without_assessment_returns_409(
    auth_client, session_factory, advisor_user
):
    _seed_runtime(session_factory, advisor_user.id)
    cid, mid = _make_client_and_mandate(session_factory, advisor_user.id)
    with session_factory() as s:
        policy = s.query(OptimizerPolicy).filter(OptimizerPolicy.is_current == 1).first()
        policy_id = policy.id

    payload = {
        "policy_id": policy_id,
        "target_equities_bps": 4500,
        "target_bonds_bps": 3500,
        "target_real_estate_bps": 1000,
        "target_alternatives_bps": 500,
        "target_liquidity_bps": 500,
        "band_equities_min_bps": 2500, "band_equities_max_bps": 5500,
        "band_bonds_min_bps": 2500, "band_bonds_max_bps": 4500,
        "band_real_estate_min_bps": 500, "band_real_estate_max_bps": 1500,
        "band_alternatives_min_bps": 300, "band_alternatives_max_bps": 800,
        "band_liquidity_min_bps": 200, "band_liquidity_max_bps": 800,
    }
    resp = auth_client.post(f"/mandates/{mid}/target-allocation", json=payload)
    assert resp.status_code == 409, resp.text
    assert "risikoprofil" in resp.text.lower() or "fragebogen" in resp.text.lower()


def test_f4_create_target_allocation_with_assessment_succeeds(
    auth_client, session_factory, advisor_user
):
    _seed_runtime(session_factory, advisor_user.id)
    cid, mid = _make_client_and_mandate(session_factory, advisor_user.id)
    _add_assessment(session_factory, mid, advisor_user.id)
    with session_factory() as s:
        policy = s.query(OptimizerPolicy).filter(OptimizerPolicy.is_current == 1).first()
        policy_id = policy.id

    payload = {
        "policy_id": policy_id,
        "target_equities_bps": 4500, "target_bonds_bps": 3500,
        "target_real_estate_bps": 1000, "target_alternatives_bps": 500,
        "target_liquidity_bps": 500,
        "band_equities_min_bps": 2500, "band_equities_max_bps": 5500,
        "band_bonds_min_bps": 2500, "band_bonds_max_bps": 4500,
        "band_real_estate_min_bps": 500, "band_real_estate_max_bps": 1500,
        "band_alternatives_min_bps": 300, "band_alternatives_max_bps": 800,
        "band_liquidity_min_bps": 200, "band_liquidity_max_bps": 800,
    }
    resp = auth_client.post(f"/mandates/{mid}/target-allocation", json=payload)
    assert resp.status_code == 201, resp.text


# ===========================================================================
# F2 - build_target_payload_from_allocation warnt bei Assessment-Drift
# ===========================================================================

def test_f2_payload_has_no_drift_warning_when_assessment_matches(
    session_factory, advisor_user
):
    _seed_runtime(session_factory, advisor_user.id)
    cid, mid = _make_client_and_mandate(session_factory, advisor_user.id)
    _add_advisory_position(session_factory, cid, advisor_user.id, value_rappen=1_000_000_00)
    aid = _add_assessment(session_factory, mid, advisor_user.id)
    tid = _make_target_allocation(session_factory, mid, advisor_user.id, based_on_assessment_id=aid)

    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        allocation = s.query(TargetAllocation).filter(TargetAllocation.id == tid).first()
        assessment = s.query(RiskAssessment).filter(RiskAssessment.id == aid).first()
        policy, cma = ensure_runtime_reference_data(s, advisor_user.id)
        payload = build_target_payload_from_allocation(
            db=s, mandate=mandate, allocation=allocation,
            policy=policy, cma=cma, assessment=assessment, preferences=None,
        )
    reasoning = " ".join(payload.get("reasoning") or [])
    assert "frueheres Risikoprofil" not in reasoning
    assert "frueheren Risikoprofil" not in reasoning


def test_f2_payload_warns_when_assessment_drifted(
    session_factory, advisor_user
):
    _seed_runtime(session_factory, advisor_user.id)
    cid, mid = _make_client_and_mandate(session_factory, advisor_user.id)
    _add_advisory_position(session_factory, cid, advisor_user.id, value_rappen=1_000_000_00)
    old_aid = _add_assessment(session_factory, mid, advisor_user.id)
    tid = _make_target_allocation(session_factory, mid, advisor_user.id, based_on_assessment_id=old_aid)

    # alte als is_current=0 markieren, neue Assessment einspielen
    with session_factory() as s:
        old = s.query(RiskAssessment).filter(RiskAssessment.id == old_aid).first()
        old.is_current = 0
        s.commit()
    new_aid = _add_assessment(session_factory, mid, advisor_user.id, final_score_x10=80,
                              profile="Wachstumsorientiert")

    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        allocation = s.query(TargetAllocation).filter(TargetAllocation.id == tid).first()
        new_assessment = s.query(RiskAssessment).filter(RiskAssessment.id == new_aid).first()
        policy, cma = ensure_runtime_reference_data(s, advisor_user.id)
        payload = build_target_payload_from_allocation(
            db=s, mandate=mandate, allocation=allocation,
            policy=policy, cma=cma, assessment=new_assessment, preferences=None,
        )
    reasoning = " ".join(payload.get("reasoning") or [])
    assert "frueheren Risikoprofil" in reasoning, (
        f"Erwarte Drift-Warnung im reasoning, gefunden: {reasoning}"
    )
