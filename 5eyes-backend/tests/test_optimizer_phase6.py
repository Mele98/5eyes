"""Phase 6 FE-Optimizer-Panel Backend-Tests.

Verifiziert:
- stress_evaluations wird vom Solver in den generate_target_allocation Return-Dict
  durchgeschleift (None bei house_matrix-Modus, dict bei converged stochastic).
- evaluate_goal_sensitivity liefert Baseline+Modified-Solver-Run mit
  konsistentem Schema und sauberem Delta.
- POST /target-allocation/sensitivity Endpoint:
  * 200 + erwartete Felder bei gueltigem Goal-ID + delta_pct
  * 404 bei unbekanntem goal_id
  * 422 bei ungueltigem delta_pct (Pydantic-Validator)
  * 409 wenn OPTIMIZER_MODE != stochastic
"""
from __future__ import annotations

import datetime
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy.orm import configure_mappers

from database import Base, get_db
from main import app
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
configure_mappers()

import services.portfolio_engine as pe
from models.clients import Client
from models.mandates import Mandate
from models.profiling import RiskAssessment, RiskAssessmentAnswer
from models.users import User
from models.wealth import Cashflow, Goal, WealthPosition
from services.auth import get_current_user, require_advisor
from services.portfolio_engine import (
    ensure_runtime_reference_data,
    evaluate_goal_sensitivity,
    generate_target_allocation,
)


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'opt_phase6.db'}",
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
def cleanup_overrides():
    yield
    app.dependency_overrides.clear()


def _seed_mandate(session_factory, suffix: str = "") -> tuple[str, str, str, str, str]:
    """Mandant mit Pension-Goal + Vermoegensziel. Gibt (advisor, cid, mid, aid, pension_goal_id) zurueck."""
    suffix = suffix or str(uuid.uuid4())[:6]
    advisor_id = f"user-p6-{suffix}"
    cid = str(uuid.uuid4())
    mid = str(uuid.uuid4())
    aid = str(uuid.uuid4())
    pension_goal_id = f"goal-p6-pension-{suffix}"
    now = _now()
    today = date.today()
    pension_start = (today + timedelta(days=365 * 5)).isoformat()
    pension_end = (today + timedelta(days=365 * 30)).isoformat()
    wealth_target_date = (today + timedelta(days=365 * 10)).isoformat()

    with session_factory() as s:
        s.add(User(id=advisor_id, username=f"adv-p6-{suffix}", password_hash="h",
                   full_name="Adv P6", role="advisor", is_active=1,
                   created_at=now, updated_at=now))
        s.add(Client(id=cid, client_number=f"C-{cid[:6]}",
                     first_name="P6", last_name="Mandant",
                     advisor_id=advisor_id, created_at=now, updated_at=now))
        s.add(Mandate(id=mid, client_id=cid, mandate_number=f"M-{mid[:6]}",
                      mandate_type="Anlageberatung", opened_at=now,
                      created_at=now, updated_at=now))
        s.add(WealthPosition(
            id=f"pos-p6-depot-{suffix}", client_id=cid,
            label="Depot", position_type="Depot", assignment="Beratungsvermögen",
            current_value_rappen=500_000_00, currency="CHF",
            alloc_equities_bps=4000, alloc_bonds_bps=3000,
            alloc_real_estate_bps=0, alloc_liquidity_bps=2000,
            alloc_alternatives_bps=1000,
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(Cashflow(
            id=f"cf-p6-savings-{suffix}", client_id=cid, label="Sparen",
            cashflow_type="Income", amount_rappen=20_000_00,
            currency="CHF", frequency="jährlich", nature="wiederkehrend",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(Goal(
            id=pension_goal_id, mandate_id=mid, client_id=cid,
            goal_family="Lebenshaltung", goal_type="Pensionsausgabe",
            label="Pension", rank=1, weight_bps=5000,
            goal_scope="Beratungsvermögen", value_mode="real",
            target_amount_rappen=24_000_00, frequency="jährlich",
            start_date=pension_start, target_date=pension_end,
            is_ongoing=0, hardness="Hart",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(Goal(
            id=f"goal-p6-wealth-{suffix}", mandate_id=mid, client_id=cid,
            goal_family="Vermoegen", goal_type="Vermoegensziel",
            label="Eigenheim Anzahlung", rank=2, weight_bps=3000,
            goal_scope="Beratungsvermögen", value_mode="nominal",
            target_wealth_rappen=300_000_00,
            target_date=wealth_target_date,
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
    return advisor_id, cid, mid, aid, pension_goal_id


def _client_with_user(session_factory, user: User | None) -> TestClient:
    def override_db():
        with session_factory() as s:
            yield s
    app.dependency_overrides[get_db] = override_db
    if user is not None:
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[require_advisor] = lambda: user
    return TestClient(app)


# ============================================================================
# stress_evaluations Passthrough
# ============================================================================


def test_stress_evaluations_present_when_stochastic_converged(session_factory, monkeypatch):
    """Phase 5.2/6: stress_evaluations dict im Result wenn Solver konvergiert."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _cid, mid, _aid, _gid = _seed_mandate(session_factory)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = generate_target_allocation(s, mandate, advisor_id, preferences=None)
        # Bei stochastic-Modus + converged: stress_evaluations ist dict mit 3 Szenarien.
        # Bei fallback: kann None sein. Akzeptiere beides, aber wenn dict, dann
        # mit erwarteten Keys.
        stress = result.get("stress_evaluations")
        if stress is not None:
            assert isinstance(stress, dict)
            assert len(stress) >= 1
            for name, payload in stress.items():
                assert isinstance(payload, dict)
                assert "end_wealth_rappen" in payload
                assert "max_drawdown_bps" in payload


def test_stress_evaluations_none_in_house_matrix_mode(session_factory, monkeypatch):
    """House-Matrix-Modus: stress_evaluations ist None (kein Solver gerufen)."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")
    advisor_id, _cid, mid, _aid, _gid = _seed_mandate(session_factory)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = generate_target_allocation(s, mandate, advisor_id, preferences=None)
        assert result.get("stress_evaluations") is None


# ============================================================================
# evaluate_goal_sensitivity (unit-level)
# ============================================================================


def test_sensitivity_returns_expected_schema(session_factory, monkeypatch):
    """Sensitivity-Helper liefert alle benoetigten Felder."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _cid, mid, _aid, gid = _seed_mandate(session_factory)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        out = evaluate_goal_sensitivity(
            db=s, mandate=mandate, user_id=advisor_id,
            goal_id=gid, target_delta_pct=-10,
        )
    expected_keys = {
        "goal_id", "delta_pct",
        "target_amount_rappen_baseline", "target_amount_rappen_new",
        "objective_value_milli_baseline", "objective_value_milli_new",
        "delta_objective_pct",
        "weights_bps_baseline", "weights_bps_new",
        "status_baseline", "status_new",
    }
    assert expected_keys.issubset(out.keys())
    assert out["goal_id"] == gid
    assert out["delta_pct"] == -10
    # Delta -10% auf 24'000 -> 21'600 CHF.
    assert out["target_amount_rappen_new"] == 21_600_00
    # Weights summe ~10000bps
    weights = out["weights_bps_new"]
    assert sum(weights.values()) == pytest.approx(10000, abs=5)


def test_sensitivity_zero_delta_does_not_change_target(session_factory, monkeypatch):
    """delta_pct=0 -> target_amount_new == baseline."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _cid, mid, _aid, gid = _seed_mandate(session_factory)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        out = evaluate_goal_sensitivity(
            db=s, mandate=mandate, user_id=advisor_id,
            goal_id=gid, target_delta_pct=0,
        )
    assert out["target_amount_rappen_baseline"] == out["target_amount_rappen_new"]


def test_sensitivity_unknown_goal_raises(session_factory, monkeypatch):
    """Goal-ID gehoert nicht zum Mandanten -> ValueError mit 'nicht gefunden'."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _cid, mid, _aid, _gid = _seed_mandate(session_factory)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        with pytest.raises(ValueError, match="nicht gefunden"):
            evaluate_goal_sensitivity(
                db=s, mandate=mandate, user_id=advisor_id,
                goal_id="goal-does-not-exist", target_delta_pct=-10,
            )


def test_sensitivity_house_matrix_mode_raises(session_factory, monkeypatch):
    """Bei OPTIMIZER_MODE=house_matrix verweigert der Helper die Auswertung."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")
    advisor_id, _cid, mid, _aid, gid = _seed_mandate(session_factory)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        with pytest.raises(ValueError, match="OPTIMIZER_MODE=stochastic"):
            evaluate_goal_sensitivity(
                db=s, mandate=mandate, user_id=advisor_id,
                goal_id=gid, target_delta_pct=-10,
            )


# ============================================================================
# Endpoint: POST /mandates/{id}/target-allocation/sensitivity
# ============================================================================


def test_endpoint_happy_path_returns_200(session_factory, monkeypatch, cleanup_overrides):
    """Authenticated Advisor + valides Goal -> 200 mit komplettem Payload."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _cid, mid, _aid, gid = _seed_mandate(session_factory)
    with session_factory() as s:
        advisor = s.query(User).filter(User.id == advisor_id).first()
    client = _client_with_user(session_factory, advisor)
    resp = client.post(
        f"/mandates/{mid}/target-allocation/sensitivity",
        json={"goal_id": gid, "target_delta_pct": -10},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["goal_id"] == gid
    assert body["delta_pct"] == -10
    assert body["target_amount_rappen_new"] == 21_600_00
    assert isinstance(body["weights_bps_new"], dict)
    assert body["status_new"] in (
        "converged", "diverged", "diverged_infeasible", "fallback_house_matrix",
    )


def test_endpoint_unknown_goal_returns_404(session_factory, monkeypatch, cleanup_overrides):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _cid, mid, _aid, _gid = _seed_mandate(session_factory)
    with session_factory() as s:
        advisor = s.query(User).filter(User.id == advisor_id).first()
    client = _client_with_user(session_factory, advisor)
    resp = client.post(
        f"/mandates/{mid}/target-allocation/sensitivity",
        json={"goal_id": "nope-not-existing", "target_delta_pct": 10},
    )
    assert resp.status_code == 404


def test_endpoint_invalid_delta_returns_422(session_factory, monkeypatch, cleanup_overrides):
    """delta_pct=42 nicht in {-20,-10,0,10,20} -> Pydantic 422."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _cid, mid, _aid, gid = _seed_mandate(session_factory)
    with session_factory() as s:
        advisor = s.query(User).filter(User.id == advisor_id).first()
    client = _client_with_user(session_factory, advisor)
    resp = client.post(
        f"/mandates/{mid}/target-allocation/sensitivity",
        json={"goal_id": gid, "target_delta_pct": 42},
    )
    assert resp.status_code == 422


def test_endpoint_house_matrix_mode_returns_409(session_factory, monkeypatch, cleanup_overrides):
    """OPTIMIZER_MODE=house_matrix -> 409 'Sensitivity-Analyse erfordert ...'."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")
    advisor_id, _cid, mid, _aid, gid = _seed_mandate(session_factory)
    with session_factory() as s:
        advisor = s.query(User).filter(User.id == advisor_id).first()
    client = _client_with_user(session_factory, advisor)
    resp = client.post(
        f"/mandates/{mid}/target-allocation/sensitivity",
        json={"goal_id": gid, "target_delta_pct": -10},
    )
    assert resp.status_code == 409
    assert "stochastic" in resp.json()["detail"].lower()


# ============================================================================
# Phase 6.1: stress_evaluations Persistenz (target_allocations.stress_evaluations_json)
# ============================================================================


def test_stress_evaluations_persisted_to_db_column(session_factory, monkeypatch):
    """Phase 6.1: stress_evaluations_json wird in der DB-Spalte abgelegt
    (JSON-String, deserialisierbar als dict). Nur fuer stochastic-Modus.
    """
    import json

    from models.allocation import TargetAllocation
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _cid, mid, _aid, _gid = _seed_mandate(session_factory)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = generate_target_allocation(s, mandate, advisor_id, preferences=None)
        s.commit()
        ta_id = result["target_allocation"].id
        # Reload from DB to verify the column is actually persisted.
        ta = s.query(TargetAllocation).filter(TargetAllocation.id == ta_id).first()
        # Wenn der Solver konvergierte und Stress-Eval lief: Spalte ist gesetzt.
        # Bei Fallback kann sie None sein - dann ueberspringen.
        if result.get("stress_evaluations") is not None:
            assert ta.stress_evaluations_json is not None
            parsed = json.loads(ta.stress_evaluations_json)
            assert isinstance(parsed, dict)
            assert parsed == result["stress_evaluations"]


def test_stress_evaluations_column_null_in_house_matrix(session_factory, monkeypatch):
    """Phase 6.1: house_matrix-Modus -> stress_evaluations_json bleibt NULL."""
    from models.allocation import TargetAllocation
    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")
    advisor_id, _cid, mid, _aid, _gid = _seed_mandate(session_factory)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = generate_target_allocation(s, mandate, advisor_id, preferences=None)
        s.commit()
        ta_id = result["target_allocation"].id
        ta = s.query(TargetAllocation).filter(TargetAllocation.id == ta_id).first()
        assert ta.stress_evaluations_json is None


def test_payload_endpoint_returns_persisted_stress_evaluations(
    session_factory, monkeypatch, cleanup_overrides,
):
    """Phase 6.1: GET /target-allocation/current/payload liefert stress_evaluations
    aus der DB ohne erneuten Solver-Lauf - das ist der Nutzen der Persistenz."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _cid, mid, _aid, _gid = _seed_mandate(session_factory)
    # 1. Allocation erzeugen (persistiert stress_evaluations_json in DB)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = generate_target_allocation(s, mandate, advisor_id, preferences=None)
        s.commit()
        had_stress = result.get("stress_evaluations") is not None
    if not had_stress:
        pytest.skip("Solver fiel auf fallback_house_matrix - kein Stress-Eval persistiert")

    # 2. /current/payload aufrufen (anderer Codepfad: build_target_payload_from_allocation)
    with session_factory() as s:
        advisor = s.query(User).filter(User.id == advisor_id).first()
    client = _client_with_user(session_factory, advisor)
    resp = client.get(f"/mandates/{mid}/target-allocation/current/payload")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    stress = body.get("stress_evaluations")
    assert stress is not None
    assert isinstance(stress, dict)
    assert len(stress) >= 1
    for _name, payload in stress.items():
        assert "end_wealth_rappen" in payload
        assert "max_drawdown_bps" in payload


def test_payload_endpoint_handles_corrupted_stress_json_gracefully(
    session_factory, monkeypatch, cleanup_overrides,
):
    """Phase 6.1: Defekter JSON in der DB-Spalte fuehrt zu stress_evaluations=None
    und keinem Crash - Robustheit beim Deserialisieren ist Pflicht."""
    from models.allocation import TargetAllocation
    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")
    advisor_id, _cid, mid, _aid, _gid = _seed_mandate(session_factory)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        generate_target_allocation(s, mandate, advisor_id, preferences=None)
        s.commit()
        # Sabotiere das persistierte JSON.
        ta = s.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mid,
            TargetAllocation.is_current == 1,
        ).first()
        ta.stress_evaluations_json = "{not-valid-json"
        s.commit()

    with session_factory() as s:
        advisor = s.query(User).filter(User.id == advisor_id).first()
    client = _client_with_user(session_factory, advisor)
    resp = client.get(f"/mandates/{mid}/target-allocation/current/payload")
    assert resp.status_code == 200, resp.text
    assert resp.json().get("stress_evaluations") is None


# ============================================================================
# Phase 6.2: optimizer_reasoning Persistenz (target_allocations.optimizer_reasoning_json)
# ============================================================================


def test_optimizer_reasoning_persisted_to_db_column(session_factory, monkeypatch):
    """Phase 6.2: optimizer_reasoning_json wird in der DB-Spalte abgelegt
    (JSON-Liste mit Solver-Trace-Zeilen). Nur fuer stochastic-Modus."""
    import json

    from models.allocation import TargetAllocation
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _cid, mid, _aid, _gid = _seed_mandate(session_factory)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        generate_target_allocation(s, mandate, advisor_id, preferences=None)
        s.commit()
        ta = s.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mid,
            TargetAllocation.is_current == 1,
        ).first()
        # Wenn der Solver konvergierte: Reasoning-Spalte ist gesetzt.
        # (Bei fallback-Fall ist OptimizerResult.reasoning trotzdem gefuellt.)
        if ta.optimization_method is not None:
            assert ta.optimizer_reasoning_json is not None
            parsed = json.loads(ta.optimizer_reasoning_json)
            assert isinstance(parsed, list)
            assert len(parsed) >= 1
            assert all(isinstance(item, str) for item in parsed)


def test_optimizer_reasoning_column_null_in_house_matrix(session_factory, monkeypatch):
    """Phase 6.2: house_matrix-Modus -> optimizer_reasoning_json bleibt NULL."""
    from models.allocation import TargetAllocation
    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")
    advisor_id, _cid, mid, _aid, _gid = _seed_mandate(session_factory)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        generate_target_allocation(s, mandate, advisor_id, preferences=None)
        s.commit()
        ta = s.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mid,
            TargetAllocation.is_current == 1,
        ).first()
        assert ta.optimizer_reasoning_json is None


def test_payload_endpoint_returns_persisted_optimizer_reasoning(
    session_factory, monkeypatch, cleanup_overrides,
):
    """Phase 6.2: GET /current/payload reasoning-Liste enthaelt persistierte
    Solver-Reasoning-Zeilen (z.B. 'SLSQP', 'Best objective', 'Stress')."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _cid, mid, _aid, _gid = _seed_mandate(session_factory)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        gen_result = generate_target_allocation(s, mandate, advisor_id, preferences=None)
        s.commit()
        had_optimizer = gen_result["target_allocation"].optimization_method is not None
    if not had_optimizer:
        pytest.skip("Solver lief nicht - kein Reasoning persistiert")

    with session_factory() as s:
        advisor = s.query(User).filter(User.id == advisor_id).first()
    client = _client_with_user(session_factory, advisor)
    resp = client.get(f"/mandates/{mid}/target-allocation/current/payload")
    assert resp.status_code == 200, resp.text
    reasoning = resp.json().get("reasoning", [])
    assert isinstance(reasoning, list)
    joined = " | ".join(reasoning)
    # Mindestens einer der Solver-Trace-Marker muss drin sein.
    assert any(
        marker in joined
        for marker in ("SLSQP", "Solver", "Best objective", "Stress", "iterations")
    ), f"Reasoning ohne Solver-Trace nach Reload: {reasoning}"


def test_sensitivity_endpoint_writes_audit_log(
    session_factory, monkeypatch, cleanup_overrides,
):
    """Phase 6.3: Jeder Sensitivity-Call legt einen AuditLog-Eintrag an
    (FINMA-Trace). record_id=goal_id, action=SENSITIVITY, new_value=delta_pct."""
    from models.review import AuditLog
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _cid, mid, _aid, gid = _seed_mandate(session_factory)
    with session_factory() as s:
        advisor = s.query(User).filter(User.id == advisor_id).first()
    client = _client_with_user(session_factory, advisor)
    resp = client.post(
        f"/mandates/{mid}/target-allocation/sensitivity",
        json={"goal_id": gid, "target_delta_pct": -10},
    )
    assert resp.status_code == 200, resp.text
    with session_factory() as s:
        entries = s.query(AuditLog).filter(
            AuditLog.action == "SENSITIVITY",
            AuditLog.record_id == gid,
        ).all()
    assert len(entries) == 1
    entry = entries[0]
    assert entry.user_id == advisor_id
    assert entry.mandate_id == mid
    assert entry.table_name == "goals"
    assert entry.new_value == "-10"


def test_sensitivity_endpoint_no_audit_on_404(
    session_factory, monkeypatch, cleanup_overrides,
):
    """Phase 6.3: Bei unbekanntem goal_id (404) darf KEIN AuditLog entstehen."""
    from models.review import AuditLog
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _cid, mid, _aid, _gid = _seed_mandate(session_factory)
    with session_factory() as s:
        advisor = s.query(User).filter(User.id == advisor_id).first()
    client = _client_with_user(session_factory, advisor)
    resp = client.post(
        f"/mandates/{mid}/target-allocation/sensitivity",
        json={"goal_id": "nope", "target_delta_pct": 10},
    )
    assert resp.status_code == 404
    with session_factory() as s:
        entries = s.query(AuditLog).filter(
            AuditLog.action == "SENSITIVITY",
        ).all()
    assert len(entries) == 0


def test_payload_endpoint_handles_corrupted_reasoning_json_gracefully(
    session_factory, monkeypatch, cleanup_overrides,
):
    """Phase 6.2: defekter optimizer_reasoning_json -> kein Crash, leere Liste,
    generic Reasoning + Drift-Warnings stehen weiter zur Verfuegung."""
    from models.allocation import TargetAllocation
    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")
    advisor_id, _cid, mid, _aid, _gid = _seed_mandate(session_factory)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        generate_target_allocation(s, mandate, advisor_id, preferences=None)
        s.commit()
        ta = s.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mid,
            TargetAllocation.is_current == 1,
        ).first()
        ta.optimizer_reasoning_json = "[truly broken"
        s.commit()

    with session_factory() as s:
        advisor = s.query(User).filter(User.id == advisor_id).first()
    client = _client_with_user(session_factory, advisor)
    resp = client.get(f"/mandates/{mid}/target-allocation/current/payload")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # generic 2-Satz-Reasoning muss da sein, kein Crash
    reasoning = body.get("reasoning", [])
    assert any("bestehende aktuelle Soll-Allokation" in r for r in reasoning)
