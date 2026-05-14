"""V3 Sprint 2 Tests: persistierter Audit-Trail in optimizer_runs.

Plan §4.1: eigene Tabelle fuer ALLE Solver-Laufe (auch shadow_stochastic),
damit eine 3rd-eyes-artige Risk-Engine-Historie moeglich ist.

Verifiziert:
- house_matrix-Modus persistiert keinen OptimizerRun
- shadow_stochastic-Modus persistiert OptimizerRun mit role='shadow'
  und target_allocation_id=None (TA bleibt House-Matrix)
- stochastic-Modus persistiert OptimizerRun mit role='active' und
  target_allocation_id=ta.id
- weights_bps_json ist valides JSON mit allen 5 Buckets
- mehrere generate-Aufrufe -> mehrere OptimizerRun-Eintraege (Audit-Trail)
- Endpoint GET /mandates/{id}/optimizer-runs liefert Liste sortiert
  absteigend nach run_at
"""
from __future__ import annotations

import datetime
import json
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm import configure_mappers

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
configure_mappers()

import services.portfolio_engine as pe
from models.allocation import OptimizerRun, TargetAllocation
from models.clients import Client
from models.mandates import Mandate
from models.profiling import RiskAssessment, RiskAssessmentAnswer
from models.users import User
from models.wealth import Cashflow, Goal, WealthPosition
from services.portfolio_engine import (
    ensure_runtime_reference_data,
    generate_target_allocation,
)


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'opt_runs.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _seed_realistic_mandate(session_factory, suffix: str = ""):
    suffix = suffix or str(uuid.uuid4())[:6]
    advisor_id = f"user-runs-{suffix}"
    cid = str(uuid.uuid4())
    mid = str(uuid.uuid4())
    aid = str(uuid.uuid4())
    now = _now()
    today = date.today()
    pension_start = (today + timedelta(days=365 * 5)).isoformat()
    pension_end = (today + timedelta(days=365 * 30)).isoformat()
    wealth_target_date = (today + timedelta(days=365 * 10)).isoformat()

    with session_factory() as s:
        s.add(User(id=advisor_id, username=f"adv-runs-{suffix}", password_hash="h",
                   full_name="Adv Runs", role="advisor", is_active=1,
                   created_at=now, updated_at=now))
        s.add(Client(id=cid, client_number=f"C-{cid[:6]}",
                     first_name="Runs", last_name="Mandant",
                     advisor_id=advisor_id, created_at=now, updated_at=now))
        s.add(Mandate(id=mid, client_id=cid, mandate_number=f"M-{mid[:6]}",
                      mandate_type="Anlageberatung", opened_at=now,
                      created_at=now, updated_at=now))
        s.add(WealthPosition(
            id=f"pos-runs-{suffix}", client_id=cid,
            label="Depot", position_type="Depot", assignment="Beratungsvermögen",
            current_value_rappen=500_000_00, currency="CHF",
            alloc_equities_bps=4000, alloc_bonds_bps=3000,
            alloc_real_estate_bps=0, alloc_liquidity_bps=2000,
            alloc_alternatives_bps=1000,
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(Cashflow(
            id=f"cf-runs-{suffix}", client_id=cid, label="Sparen",
            cashflow_type="Income", amount_rappen=20_000_00,
            currency="CHF", frequency="jährlich", nature="wiederkehrend",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(Goal(
            id=f"goal-runs-pension-{suffix}", mandate_id=mid, client_id=cid,
            goal_family="Lebenshaltung", goal_type="Pensionsausgabe",
            label="Pension", rank=1, weight_bps=5000,
            goal_scope="Beratungsvermögen", value_mode="real",
            target_amount_rappen=24_000_00, frequency="jährlich",
            start_date=pension_start, target_date=pension_end,
            is_ongoing=0, hardness="Hart",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(Goal(
            id=f"goal-runs-wealth-{suffix}", mandate_id=mid, client_id=cid,
            goal_family="Vermoegen", goal_type="Vermoegensziel",
            label="Eigenheim", rank=2, weight_bps=3000,
            goal_scope="Beratungsvermögen", value_mode="nominal",
            target_wealth_rappen=300_000_00, target_date=wealth_target_date,
            is_ongoing=0, hardness="Primaer",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(RiskAssessment(
            id=aid, mandate_id=mid, version=1, is_current=1, valid_from=now[:10],
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
            assessed_at=now, assessed_by=advisor_id,
            created_at=now, updated_at=now,
        ))
        for q in (3, 5, 6, 7, 8, 9, 10, 11):
            s.add(RiskAssessmentAnswer(
                id=str(uuid.uuid4()), assessment_id=aid,
                question_number=q, question_section="Risikoprofil",
                answer_label=f"A{q}", answer_points=2,
                created_at=now,
            ))
        s.commit()
        ensure_runtime_reference_data(s, advisor_id)
        s.commit()
    return advisor_id, cid, mid, aid


# ============================================================================
# Persistenz-Verhalten je nach Modus
# ============================================================================


def test_house_matrix_mode_does_not_persist_optimizer_run(session_factory, monkeypatch):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")
    advisor_id, _cid, mid, _aid = _seed_realistic_mandate(session_factory, suffix="hm")
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        generate_target_allocation(s, mandate, advisor_id, preferences=None)
        s.commit()
        runs = s.query(OptimizerRun).filter(OptimizerRun.mandate_id == mid).all()
        assert runs == []


def test_shadow_stochastic_persists_run_with_role_shadow(session_factory, monkeypatch):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "shadow_stochastic")
    advisor_id, _cid, mid, _aid = _seed_realistic_mandate(session_factory, suffix="sh")
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        generate_target_allocation(s, mandate, advisor_id, preferences=None)
        s.commit()
        runs = s.query(OptimizerRun).filter(OptimizerRun.mandate_id == mid).all()
        assert len(runs) == 1
        run = runs[0]
        assert run.optimizer_mode == "shadow_stochastic"
        assert run.role == "shadow"
        # Im Shadow-Modus haengt der Run NICHT an einer TA (TA = House Matrix)
        assert run.target_allocation_id is None
        assert run.status in (
            "converged", "diverged", "diverged_infeasible", "fallback_house_matrix",
        )
        assert run.seed > 0


def test_stochastic_persists_run_with_role_active_and_ta_link(session_factory, monkeypatch):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _cid, mid, _aid = _seed_realistic_mandate(session_factory, suffix="st")
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = generate_target_allocation(s, mandate, advisor_id, preferences=None)
        s.commit()
        ta = result["target_allocation"]
        runs = s.query(OptimizerRun).filter(OptimizerRun.mandate_id == mid).all()
        assert len(runs) == 1
        run = runs[0]
        assert run.optimizer_mode == "stochastic"
        assert run.role == "active"
        assert run.target_allocation_id == ta.id


def test_weights_bps_json_contains_all_buckets(session_factory, monkeypatch):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "shadow_stochastic")
    advisor_id, _cid, mid, _aid = _seed_realistic_mandate(session_factory, suffix="wj")
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        generate_target_allocation(s, mandate, advisor_id, preferences=None)
        s.commit()
        run = s.query(OptimizerRun).filter(OptimizerRun.mandate_id == mid).first()
        assert run is not None
        weights = json.loads(run.weights_bps_json)
        assert set(weights.keys()) == {"equities", "bonds", "real_estate", "alternatives", "liquidity"}
        for value in weights.values():
            assert isinstance(value, int) and value >= 0


def test_repeated_generate_creates_multiple_runs(session_factory, monkeypatch):
    """Audit-Trail: jeder generate-Aufruf erzeugt einen neuen Eintrag."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "shadow_stochastic")
    advisor_id, _cid, mid, _aid = _seed_realistic_mandate(session_factory, suffix="rep")
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        generate_target_allocation(s, mandate, advisor_id, preferences=None)
        s.commit()
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        generate_target_allocation(s, mandate, advisor_id, preferences=None)
        s.commit()
    with session_factory() as s:
        runs = s.query(OptimizerRun).filter(OptimizerRun.mandate_id == mid).all()
        assert len(runs) == 2


def test_run_persists_reasoning_and_seed(session_factory, monkeypatch):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "shadow_stochastic")
    advisor_id, _cid, mid, _aid = _seed_realistic_mandate(session_factory, suffix="rs")
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        generate_target_allocation(s, mandate, advisor_id, preferences=None)
        s.commit()
        run = s.query(OptimizerRun).filter(OptimizerRun.mandate_id == mid).first()
        assert run.seed > 0
        # Reasoning (auch wenn fallback) sollte gefuellt sein, weil Solver Reasoning anhängt
        assert run.reasoning_json is not None
        reasoning = json.loads(run.reasoning_json)
        assert isinstance(reasoning, list)


# ============================================================================
# Endpoint GET /mandates/{id}/optimizer-runs
# ============================================================================


def test_endpoint_returns_runs_sorted_descending(session_factory, monkeypatch):
    """GET /mandates/{id}/optimizer-runs: neueste zuerst, korrekte Felder."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "shadow_stochastic")
    advisor_id, _cid, mid, _aid = _seed_realistic_mandate(session_factory, suffix="ep")
    # Zwei Runs erzeugen
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        generate_target_allocation(s, mandate, advisor_id, preferences=None)
        s.commit()
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        generate_target_allocation(s, mandate, advisor_id, preferences=None)
        s.commit()

    # Endpoint via TestClient mit DB-Override
    from main import app
    from database import get_db

    SF = session_factory
    def override_get_db():
        db = SF()
        try:
            yield db
        finally:
            db.close()
    app.dependency_overrides[get_db] = override_get_db

    # Auth-Override
    from services.auth import get_current_user
    def override_user():
        with SF() as s:
            return s.query(User).filter(User.id == advisor_id).first()
    app.dependency_overrides[get_current_user] = override_user

    try:
        client = TestClient(app)
        r = client.get(f"/mandates/{mid}/optimizer-runs")
        assert r.status_code == 200, r.text
        runs = r.json()
        assert isinstance(runs, list)
        assert len(runs) == 2
        # Neueste zuerst -> run_at[0] >= run_at[1]
        assert runs[0]["run_at"] >= runs[1]["run_at"]
        # Pflichtfelder
        for run in runs:
            assert run["mandate_id"] == mid
            assert run["optimizer_mode"] == "shadow_stochastic"
            assert run["role"] == "shadow"
            assert run["seed"] > 0
            assert "weights_bps_json" in run
    finally:
        app.dependency_overrides.clear()


def test_endpoint_empty_list_for_house_matrix_mandate(session_factory, monkeypatch):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")
    advisor_id, _cid, mid, _aid = _seed_realistic_mandate(session_factory, suffix="ep0")
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        generate_target_allocation(s, mandate, advisor_id, preferences=None)
        s.commit()

    from main import app
    from database import get_db
    from services.auth import get_current_user
    SF = session_factory
    def override_get_db():
        db = SF()
        try:
            yield db
        finally:
            db.close()
    def override_user():
        with SF() as s:
            return s.query(User).filter(User.id == advisor_id).first()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_user
    try:
        client = TestClient(app)
        r = client.get(f"/mandates/{mid}/optimizer-runs")
        assert r.status_code == 200
        assert r.json() == []
    finally:
        app.dependency_overrides.clear()


def test_endpoint_validates_pagination_params(session_factory, monkeypatch):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")
    advisor_id, _cid, mid, _aid = _seed_realistic_mandate(session_factory, suffix="pg")
    from main import app
    from database import get_db
    from services.auth import get_current_user
    SF = session_factory
    def override_get_db():
        db = SF()
        try:
            yield db
        finally:
            db.close()
    def override_user():
        with SF() as s:
            return s.query(User).filter(User.id == advisor_id).first()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_user
    try:
        client = TestClient(app)
        r1 = client.get(f"/mandates/{mid}/optimizer-runs?limit=0")
        assert r1.status_code == 422
        r2 = client.get(f"/mandates/{mid}/optimizer-runs?limit=501")
        assert r2.status_code == 422
        r3 = client.get(f"/mandates/{mid}/optimizer-runs?offset=-1")
        assert r3.status_code == 422
    finally:
        app.dependency_overrides.clear()
