"""PRIVACY-001 (Teil 2): API des Loeschworkflows und Lese-Gates.

* ``GET /privacy/status`` meldet ehrlich BLOCKED und die fehlenden
  Matrixzeilen.
* Nach einem ausgefuehrten Loeschvorgang mit ``RETAIN_RESTRICTED`` sind
  Risikoprofil- und Plausibilitaetsnachweise fuer die Beratung gesperrt
  (423) und im DSG-Export als ``restricted`` ausgewiesen statt geliefert.
* Mandantentrennung: Vorgaenge, Policies und Kunden fremder Mandanten sind
  nicht erreichbar.

Die Policy-Werte sind Testplatzhalter, keine fachlichen Vorgaben.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from database import Base, get_db
from main import app
from models.users import User
from services import privacy_erasure as pe
from services import privacy_erasure_inventory as inv
from services.auth import get_current_user, require_admin, require_advisor
from tests.test_endpoint_query_budgets import (
    _ADMIN_ID,
    _CLIENT_ID,
    _MANDATE_ID,
    _NOW,
    _seed_base,
    _seed_risk_assessments,
)

TENANT = "main"
MATRIX = {key: f"TEST-{key}" for key in pe.REQUIRED_MATRIX_KEYS}


def _user(uid: str, *, tenant: str = TENANT, role: str = "admin") -> User:
    return User(id=uid, username=uid, password_hash="h", full_name=uid, role=role, tenant_id=tenant,
                is_active=1, created_at=_NOW, updated_at=_NOW)


@contextmanager
def _api(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'gates.db'}", connect_args={"check_same_thread": False})
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    with factory() as s:
        _seed_base(s)
        _seed_risk_assessments(s, 1)
        for uid in ("priv-1", "legal-1"):
            s.add(_user(uid))
        s.add(_user("admin-b", tenant="t-b"))
        s.commit()
        for table in ("users", "clients", "mandates"):
            s.execute(text(f"UPDATE {table} SET tenant_id = :t WHERE tenant_id IS NULL"), {"t": TENANT})
        s.commit()

    def override_get_db():
        with factory() as session:
            yield session

    current = {"user": _user(_ADMIN_ID)}
    app.dependency_overrides[get_db] = override_get_db
    for dependency in (get_current_user, require_admin, require_advisor):
        app.dependency_overrides[dependency] = lambda: current["user"]
    try:
        yield TestClient(app), current, factory
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _restrict_everything(client: TestClient, current: dict) -> str:
    for uid, role in (("priv-1", "PRIVACY"), ("legal-1", "LEGAL")):
        assert client.post("/privacy/roles", json={"user_id": uid, "privacy_role": role}).status_code == 201
    policy_ids = []
    for evidence_type in inv.EVIDENCE_TYPES:
        response = client.post("/privacy/policies", json={
            "evidence_type": evidence_type, "disposition": "RETAIN_RESTRICTED", "matrix": MATRIX,
            "legal_basis": "TEST-RECHTSGRUNDLAGE", "retention_trigger": "ERASURE_REQUEST",
            "retention_months": 12,
        })
        assert response.status_code == 201, response.text
        assert response.json()["status"] == "PROPOSED"
        policy_ids.append(response.json()["id"])
    # Der Admin ist nicht benannt -> keine Genehmigung.
    denied = client.post(f"/privacy/policies/{policy_ids[0]}/approve")
    assert denied.status_code == 403 and denied.json()["detail"]["code"] == "PRIVACY_ROLE_REQUIRED"
    current["user"] = _user("priv-1")
    for policy_id in policy_ids:
        assert client.post(f"/privacy/policies/{policy_id}/approve").status_code == 200
    current["user"] = _user(_ADMIN_ID)
    case = client.post("/privacy/erasure-cases", json={"client_id": _CLIENT_ID})
    assert case.status_code == 201, case.text
    assert case.json()["status"] == "READY"
    executed = client.post(f"/privacy/erasure-cases/{case.json()['id']}/execute")
    assert executed.status_code == 200, executed.text
    assert executed.json()["status"] == "EXECUTED"
    return case.json()["id"]


def test_status_is_honestly_blocked_and_pending_case_is_labelled(tmp_path):
    with _api(tmp_path) as (client, _current, _factory):
        status = client.get("/privacy/status").json()
        assert status["production_activation"] == "BLOCKED"
        assert status["matrix_complete"] is False
        assert set(status["evidence_types_without_approved_policy"]) == set(inv.EVIDENCE_TYPES)

        case = client.post("/privacy/erasure-cases", json={"client_id": _CLIENT_ID}).json()
        assert case["status"] == "DECISION_PENDING"
        assert case["status_label"] == "Entscheid ausstehend"
        assert case["decisions_pending"] > 0
        refused = client.post(f"/privacy/erasure-cases/{case['id']}/execute")
        assert refused.status_code == 409
        assert refused.json()["detail"]["code"] == "PRIVACY_DECISION_PENDING"
        # Nichts gesperrt, Beratung liest weiter.
        assert client.get(f"/mandates/{_MANDATE_ID}/risk-assessments").status_code == 200


def test_restricted_risk_and_plausibility_evidence_is_not_readable_for_advice(tmp_path):
    with _api(tmp_path) as (client, current, _factory):
        assert client.get(f"/mandates/{_MANDATE_ID}/risk-assessments").status_code == 200
        before = client.get(f"/mandates/{_MANDATE_ID}/risk-capacity-plausibility")
        assert before.status_code != 423
        evaluations = client.get(f"/mandates/{_MANDATE_ID}/risk-capacity-plausibility/evaluations")
        assert evaluations.status_code == 200, evaluations.text

        _restrict_everything(client, current)

        for path in (
            f"/mandates/{_MANDATE_ID}/risk-assessments",
            f"/mandates/{_MANDATE_ID}/risk-assessments/current",
            f"/mandates/{_MANDATE_ID}/risk-capacity-plausibility",
            f"/mandates/{_MANDATE_ID}/risk-capacity-plausibility/evaluations",
        ):
            response = client.get(path)
            assert response.status_code == 423, (path, response.text)
            assert response.json()["detail"]["code"] == "PRIVACY_EVIDENCE_RESTRICTED"


def test_export_withholds_restricted_sections_visibly(tmp_path):
    with _api(tmp_path) as (client, current, _factory):
        before = client.get(f"/clients/{_CLIENT_ID}/data-export").json()
        assert before["sections"]["risk_assessments"] and before["restricted_sections"] == {}

        _restrict_everything(client, current)

        export = client.get(f"/clients/{_CLIENT_ID}/data-export").json()
        assert export["sections"]["risk_assessments"] == []
        assert export["section_status"]["risk_assessments"] == "restricted"
        assert export["restricted_sections"]["risk_assessments"] == ["risk_profile_evidence"]
        assert export["sections"]["client"] == {}
        assert "Erika" not in str(export["sections"])
        assert export["complete"] is True


def test_privacy_api_respects_tenant_boundaries(tmp_path):
    with _api(tmp_path) as (client, current, _factory):
        case_id = _restrict_everything(client, current)
        current["user"] = _user("admin-b", tenant="t-b")
        assert client.get(f"/privacy/erasure-cases/{case_id}").status_code == 404
        assert client.post(f"/privacy/erasure-cases/{case_id}/execute").status_code == 404
        assert client.post("/privacy/erasure-cases", json={"client_id": _CLIENT_ID}).status_code == 404
        assert client.get("/privacy/policies").json() == []
        assert client.get("/privacy/roles").json() == []
        assert client.get("/privacy/status").json()["matrix_complete"] is False


def test_legal_hold_api_is_two_step_and_role_bound(tmp_path):
    with _api(tmp_path) as (client, current, _factory):
        for uid, role in (("priv-1", "PRIVACY"), ("legal-1", "LEGAL")):
            client.post("/privacy/roles", json={"user_id": uid, "privacy_role": role})
        body = {"client_id": _CLIENT_ID, "case_reference": "FALL-T", "legal_reason": "TEST-GRUND",
                "scope": ["risk_profile_evidence"], "review_date": "2027-06-30"}
        denied = client.post("/privacy/legal-holds", json=body)
        assert denied.status_code == 403
        current["user"] = _user("legal-1")
        hold = client.post("/privacy/legal-holds", json=body)
        assert hold.status_code == 201 and hold.json()["status"] == "PROPOSED"
        self_approval = client.post(f"/privacy/legal-holds/{hold.json()['id']}/approve")
        assert self_approval.status_code == 409
        current["user"] = _user("priv-1")
        approved = client.post(f"/privacy/legal-holds/{hold.json()['id']}/approve")
        assert approved.status_code == 200 and approved.json()["status"] == "ACTIVE"
        assert approved.json()["approved_by"] == "priv-1" and approved.json()["set_by"] == "legal-1"
        current["user"] = _user("admin-b", tenant="t-b")
        assert client.post(f"/privacy/legal-holds/{hold.json()['id']}/release").status_code == 404
