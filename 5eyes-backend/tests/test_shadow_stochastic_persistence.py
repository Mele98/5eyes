from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for path in (BACKEND_ROOT, TESTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from database import get_db
from main import app
from models.allocation import TargetAllocation
from models.mandates import Mandate
from models.review import AuditLog
from services.auth import require_admin
from services.optimizer.solver import OptimizerResult
from services.shadow_comparison import build_shadow_comparison_payload
from test_optimizer_shadow_mode import _seed_realistic_mandate, session_factory

import services.portfolio_engine as pe


FAKE_STOCHASTIC_WEIGHTS = {
    "equities": 6200,
    "bonds": 2400,
    "real_estate": 700,
    "alternatives": 500,
    "liquidity": 200,
}


def _fake_optimizer_result(**kwargs):
    if kwargs.get("apply_targets"):
        kwargs["targets"].update(FAKE_STOCHASTIC_WEIGHTS)
    result = OptimizerResult(
        weights_bps=dict(FAKE_STOCHASTIC_WEIGHTS),
        objective_value=12.345,
        iterations=3,
        seed=20260523,
        status="converged",
        method="stochastic",
        reasoning=["Fake stochastic result for Stage-5 persistence test."],
        n_paths=2000,
        n_starts_attempted=2,
        goal_achievability=(
            {
                "goal_id": "goal-test",
                "label": "Pension",
                "probability": 0.86,
                "tau": 0.8,
                "status": "erreichbar",
                "hardness": "hart",
            },
        ),
    )
    object.__setattr__(result, "elapsed_ms", 250)
    return result


def _weights_from_ta(ta: TargetAllocation) -> dict[str, int]:
    return {
        "equities": ta.target_equities_bps,
        "bonds": ta.target_bonds_bps,
        "real_estate": ta.target_real_estate_bps,
        "alternatives": ta.target_alternatives_bps,
        "liquidity": ta.target_liquidity_bps,
    }


def _client_with_admin(session_factory, admin_id: str = "admin-stage5"):
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    # role/tenant_id ergaenzt (2026-06-11): der Shadow-Comparison-Endpoint hat seit
    # dem Tenant-Guard (#261) get_mandate_for_user_or_404, das current_user.role
    # (has_global_client_access) + tenant_id liest. Realer require_admin liefert ein
    # vollstaendiges User-Objekt; der Mock muss das spiegeln.
    admin_user = SimpleNamespace(id=admin_id, full_name="Admin Stage5", email="admin@example.test", role="admin", tenant_id=None)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_admin] = lambda: admin_user
    return TestClient(app)


def test_shadow_stochastic_persists_shadow_json_and_keeps_house_targets(
    session_factory,
    monkeypatch,
):
    advisor_id, _cid, mid, _aid, _gid = _seed_realistic_mandate(session_factory, suffix="s5persist")

    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        house = pe.generate_target_allocation(s, mandate, advisor_id, preferences=None)
        house_weights = _weights_from_ta(house["target_allocation"])
        s.commit()

    monkeypatch.setattr(pe.settings, "optimizer_mode", "shadow_stochastic")
    monkeypatch.setattr(pe, "_run_stochastic_optimizer_pass", _fake_optimizer_result)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = pe.generate_target_allocation(s, mandate, advisor_id, preferences=None)
        ta = result["target_allocation"]
        s.commit()

        assert _weights_from_ta(ta) == house_weights
        assert ta.optimization_method is None
        assert ta.optimizer_reasoning_json is None
        assert ta.shadow_optimization_json is not None

        payload = json.loads(ta.shadow_optimization_json)
        assert payload["engine"] == "stochastic"
        assert payload["allocation_bps"] == FAKE_STOCHASTIC_WEIGHTS
        assert payload["active_allocation_bps"] == house_weights
        assert payload["optimization_status"] == "converged"
        assert payload["elapsed_ms"] == 250
        assert payload["budget_compliance"] is True
        assert payload["achievability"][0]["status"] == "erreichbar"


def test_house_matrix_and_active_stochastic_do_not_persist_shadow_json(
    session_factory,
    monkeypatch,
):
    advisor_id, _cid, mid, _aid, _gid = _seed_realistic_mandate(session_factory, suffix="s5modes")

    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        house = pe.generate_target_allocation(s, mandate, advisor_id, preferences=None)
        assert house["target_allocation"].shadow_optimization_json is None

    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    monkeypatch.setattr(pe, "_run_stochastic_optimizer_pass", _fake_optimizer_result)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        stochastic = pe.generate_target_allocation(s, mandate, advisor_id, preferences=None)
        assert stochastic["target_allocation"].shadow_optimization_json is None
        assert _weights_from_ta(stochastic["target_allocation"]) == FAKE_STOCHASTIC_WEIGHTS


def test_admin_shadow_comparison_endpoint_returns_methodology_metrics(
    session_factory,
    monkeypatch,
):
    advisor_id, _cid, mid, _aid, _gid = _seed_realistic_mandate(session_factory, suffix="s5admin")
    monkeypatch.setattr(pe.settings, "optimizer_mode", "shadow_stochastic")
    monkeypatch.setattr(pe, "_run_stochastic_optimizer_pass", _fake_optimizer_result)

    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        pe.generate_target_allocation(s, mandate, advisor_id, preferences=None)
        s.commit()

    with _client_with_admin(session_factory, admin_id=advisor_id) as client:
        response = client.get(f"/admin/system/shadow-comparison/{mid}")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()
    assert data["mandate_id"] == mid
    assert data["shadow_engine"] == "stochastic"
    assert data["shadow_allocation_bps"] == FAKE_STOCHASTIC_WEIGHTS
    assert isinstance(data["total_drift_bps"], int)
    assert data["budget_compliance"]["stochastic"] is True
    assert data["goal_counts"]["n_goals_achievable_st"] == 1
    assert data["goal_counts"]["n_hard_unreachable_st"] == 0
    assert data["elapsed_ms"]["stochastic"] == 250
    assert data["optimization_status"] == "converged"
    assert data["per_bucket_bps"]["equities"]["stochastic"] == FAKE_STOCHASTIC_WEIGHTS["equities"]
    assert data["per_bucket_bps"]["equities"]["drift"] == abs(
        data["shadow_allocation_bps"]["equities"] - data["active_allocation_bps"]["equities"]
    )
    assert data["verdict"] in {"green", "yellow", "red"}
    assert isinstance(data["verdict_notes"], list)
    assert data["raw_shadow_payload"]["engine"] == "stochastic"

    with session_factory() as s:
        direct = build_shadow_comparison_payload(s, mid)
    assert direct["total_drift_bps"] == data["total_drift_bps"]


def test_put_optimizer_mode_validates_and_audits(session_factory, monkeypatch):
    old_mode = pe.settings.optimizer_mode
    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")
    try:
        with _client_with_admin(session_factory, admin_id="admin-mode") as client:
            invalid = client.put("/admin/system/optimizer-mode", json={"optimizer_mode": "iterative"})
            assert invalid.status_code == 422

            ok = client.put("/admin/system/optimizer-mode", json={"optimizer_mode": "shadow_stochastic"})
            assert ok.status_code == 200
            payload = ok.json()
            assert payload["changed"] is True
            assert payload["old_value"] == "house_matrix"
            assert payload["new_value"] == "shadow_stochastic"
    finally:
        app.dependency_overrides.clear()
        pe.settings.optimizer_mode = old_mode

    with session_factory() as s:
        rows = s.query(AuditLog).filter(AuditLog.action == "OPTIMIZER_MODE_CHANGE").all()
        assert len(rows) == 1
        assert rows[0].old_value == "house_matrix"
        assert rows[0].new_value == "shadow_stochastic"


def test_put_optimizer_mode_cannot_disable_stochastic_in_production(
    session_factory, monkeypatch,
):
    old_mode = pe.settings.optimizer_mode
    old_env = pe.settings.app_env
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    monkeypatch.setattr(pe.settings, "app_env", "production")
    try:
        with _client_with_admin(session_factory, admin_id="admin-mode-prod") as client:
            response = client.put(
                "/admin/system/optimizer-mode",
                json={"optimizer_mode": "house_matrix"},
            )
        assert response.status_code == 409, response.text
        assert pe.settings.optimizer_mode == "stochastic"
    finally:
        app.dependency_overrides.clear()
        pe.settings.optimizer_mode = old_mode
        pe.settings.app_env = old_env

    with session_factory() as session:
        assert session.query(AuditLog).filter(
            AuditLog.action == "OPTIMIZER_MODE_CHANGE"
        ).count() == 0
