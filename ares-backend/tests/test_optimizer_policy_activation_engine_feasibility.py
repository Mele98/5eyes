"""ADMIN-HOUSE-MATRIX-PERCENT-001 / CIO-Entscheid 3: Aktivierung fail-closed.

``POST /admin/optimizer-policies/{id}/activate`` (und Create mit
``activate=true``) prueft die Engine-Machbarkeit jeder Hausmatrix-Zeile unter
der Policy -- wirksame Minima <= 100 % <= wirksame Maxima inkl.
Aktien-Mindestquote und Policy-Grenzen (services/house_matrix_feasibility.py).
Bei Verstoss: 409 mit Reason-Code und betroffenen Zeilen, keine Aktivierung,
die bisher aktive Policy bleibt aktiv.

Die Beispielzeilen sind schema-gueltig (Zielsumme 100 %, min <= Ziel <= max,
Mindestquote <= Aktien-Max) -- das Schema allein haette sie durchgelassen.
"""
from __future__ import annotations

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
from models.allocation import OptimizerPolicy
from services.auth import require_admin
from services.house_matrix_feasibility import (
    REASON_CODE_INFEASIBLE,
    REASON_MAX_SUM_UNDER_100,
    REASON_MIN_SUM_OVER_100,
    house_matrix_row_feasibility,
)
from test_optimizer_shadow_mode import session_factory  # noqa: F401

_ADMIN_ID = "admin-a16-feas"

FEASIBLE_ROW = {
    "score_from": 1, "score_to": 10, "profile_name": "Machbar",
    "liq_min_bps": 0, "liq_target_bps": 500, "liq_max_bps": 1000,
    "bonds_min_bps": 0, "bonds_target_bps": 4000, "bonds_max_bps": 6000,
    "equity_min_bps": 0, "equity_target_bps": 4000, "equity_max_bps": 6000,
    "real_estate_min_bps": 0, "real_estate_target_bps": 1000, "real_estate_max_bps": 2000,
    "alt_min_bps": 0, "alt_target_bps": 500, "alt_max_bps": 1000,
    "equity_minimum_bps": 0, "max_risky_fraction_bps": 9500,
}
# Schema-gueltig, aber die Aktien-Mindestquote hebt das Aktien-Minimum auf
# 60 %: wirksame Minima 45 % + 60 % = 105 %.
MIN_OVER_ROW = dict(
    FEASIBLE_ROW, profile_name="Minima-ueber-100",
    bonds_min_bps=4500, bonds_target_bps=4500, equity_target_bps=3500, equity_minimum_bps=6000,
)


def _ensure_admin(session_factory) -> None:
    from models.users import User as UserModel

    now = "2026-10-21T10:00:00.000Z"
    with session_factory() as s:
        if not s.query(UserModel).filter(UserModel.id == _ADMIN_ID).first():
            s.add(UserModel(id=_ADMIN_ID, username=_ADMIN_ID, password_hash="x", full_name="Admin A16",
                            role="admin", is_active=1, created_at=now, updated_at=now))
            s.commit()


def _client(session_factory) -> TestClient:
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_admin] = lambda: SimpleNamespace(
        id=_ADMIN_ID, full_name="Admin A16", email="a16@test.local")
    return TestClient(app)


def _payload(name: str, rows: list[dict], **caps) -> dict:
    body = {"policy_name": name, "optimizer_engine": "goal_based_v1", "max_real_estate_bps": 2000,
            "max_alternatives_bps": 1000, "min_liquidity_bps": 0, "notes": "a16",
            "house_matrix_rows": rows}
    body.update(caps)
    return body


def _current_ids(session_factory) -> list[str]:
    with session_factory() as s:
        return [p.id for p in s.query(OptimizerPolicy).filter(OptimizerPolicy.is_current == 1).all()]


def test_feasibility_function_reports_reasons_and_sums():
    pol = SimpleNamespace(max_real_estate_bps=2000, max_alternatives_bps=1000, min_liquidity_bps=0)
    ok = house_matrix_row_feasibility(SimpleNamespace(**FEASIBLE_ROW), pol)
    assert ok == {"feasible": True, "reasons": [], "effective_min_sum_bps": 0, "effective_max_sum_bps": 16000}
    bad = house_matrix_row_feasibility(SimpleNamespace(**MIN_OVER_ROW), pol)
    assert bad["feasible"] is False and bad["reasons"] == [REASON_MIN_SUM_OVER_100]
    assert bad["effective_min_sum_bps"] == 10500
    # Policy-Caps 0 auf Immobilien/Alternative + enge Maxima: wirksame Maxima < 100 %.
    tight = dict(FEASIBLE_ROW, liq_max_bps=500, bonds_max_bps=4000, equity_max_bps=4000)
    zero = SimpleNamespace(max_real_estate_bps=0, max_alternatives_bps=0, min_liquidity_bps=0)
    capped = house_matrix_row_feasibility(SimpleNamespace(**tight), zero)
    assert capped["reasons"] == [REASON_MAX_SUM_UNDER_100] and capped["effective_max_sum_bps"] == 8500


def test_activate_rejects_engine_infeasible_policy_and_keeps_previous_current(session_factory):
    _ensure_admin(session_factory)
    try:
        with _client(session_factory) as client:
            good = client.post("/admin/optimizer-policies", params={"activate": "true"},
                               json=_payload("A16-Good", [FEASIBLE_ROW]))
            assert good.status_code == 201, good.text
            good_id = good.json()["id"]

            draft = client.post("/admin/optimizer-policies", json=_payload("A16-Draft", [MIN_OVER_ROW]))
            assert draft.status_code == 201, draft.text  # Entwurf speichern bleibt erlaubt
            draft_id = draft.json()["id"]

            resp = client.post(f"/admin/optimizer-policies/{draft_id}/activate", json={})
            assert resp.status_code == 409, resp.text
            detail = resp.json()["detail"]
            assert detail["reason_code"] == REASON_CODE_INFEASIBLE
            assert detail["rows"] == [{
                "score_from": 1, "score_to": 10, "profile_name": "Minima-ueber-100",
                "reasons": [REASON_MIN_SUM_OVER_100],
                "effective_min_sum_bps": 10500, "effective_max_sum_bps": 16000,
            }]
            assert "1-10 Minima-ueber-100" in detail["message"]
            assert _current_ids(session_factory) == [good_id]

            # Policy-Grenze macht eine sonst gueltige Zeile unmachbar.
            tight = dict(FEASIBLE_ROW, profile_name="Eng", liq_max_bps=500, bonds_max_bps=4000, equity_max_bps=4000)
            capped = client.post("/admin/optimizer-policies",
                                 json=_payload("A16-Capped", [tight], max_real_estate_bps=0, max_alternatives_bps=0))
            assert capped.status_code == 201, capped.text
            resp2 = client.post(f"/admin/optimizer-policies/{capped.json()['id']}/activate", json={})
            assert resp2.status_code == 409
            assert resp2.json()["detail"]["rows"][0]["reasons"] == [REASON_MAX_SUM_UNDER_100]
            assert _current_ids(session_factory) == [good_id]

            # Machbare Policy wird weiterhin aktiviert.
            ok = client.post("/admin/optimizer-policies", json=_payload("A16-Ok", [FEASIBLE_ROW]))
            act = client.post(f"/admin/optimizer-policies/{ok.json()['id']}/activate", json={})
            assert act.status_code == 200, act.text
            assert _current_ids(session_factory) == [ok.json()["id"]]
    finally:
        app.dependency_overrides.clear()


def test_create_with_activate_uses_the_same_gate(session_factory):
    _ensure_admin(session_factory)
    try:
        with _client(session_factory) as client:
            good = client.post("/admin/optimizer-policies", params={"activate": "true"},
                               json=_payload("A16-Good2", [FEASIBLE_ROW]))
            assert good.status_code == 201
            bad = client.post("/admin/optimizer-policies", params={"activate": "true"},
                              json=_payload("A16-Bad2", [MIN_OVER_ROW]))
            assert bad.status_code == 409, bad.text
            assert bad.json()["detail"]["reason_code"] == REASON_CODE_INFEASIBLE
            assert _current_ids(session_factory) == [good.json()["id"]]
        with session_factory() as s:
            assert not s.query(OptimizerPolicy).filter(OptimizerPolicy.policy_name == "A16-Bad2").all()
    finally:
        app.dependency_overrides.clear()
