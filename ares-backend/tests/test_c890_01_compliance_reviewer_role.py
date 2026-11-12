"""C-890-01 Nachtrag 1: externe Compliance-Person einer Ein-Personen-Firma.

Rolle ``compliance_reviewer``: darf die KYC-Wiedervorlage-Policy der eigenen
Firma lesen und als zweite Person freigeben -- sonst nichts (keine Policy
erfassen, keine Kunden-/Mandatsdaten lesen oder aendern, keine Systemdaten).
Die Sperre sitzt zentral in ``services.auth.get_current_user``
(Pfad-Allowlist) und zusaetzlich an jedem Endpoint (Rollen-Dependency).

Alle Fristen sind TESTWERTE (``TEST-C890``), keine Owner-Frist.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
TESTS_ROOT = Path(__file__).resolve().parent
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from database import Base, get_db  # noqa: E402
from main import app  # noqa: E402
from models.clients import Client  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from models.tenant import KycReviewPolicyActivation, Tenant  # noqa: E402
from models.users import User  # noqa: E402
from services.auth import COMPLIANCE_REVIEWER_SCOPE, compliance_reviewer_may_call, hash_password  # noqa: E402

from client_onboarding_fixture import ensure_test_legal_profile  # noqa: E402

NOW = "2026-11-12T09:00:00.000Z"
TENANT = "t-rev"
PW = "Testpasswort-C890-1"


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'rev.db'}", connect_args={"check_same_thread": False})
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    with factory() as db:
        for tid in (TENANT, "t-fremd"):
            db.add(Tenant(id=tid, display_name=tid, slug=tid, created_at=NOW, updated_at=NOW))
        for uid, role, tid in (("adm-1", "admin", TENANT), ("adm-2", "admin", TENANT),
                               ("adv-1", "advisor", TENANT), ("rev-1", "compliance_reviewer", TENANT),
                               ("rev-f", "compliance_reviewer", "t-fremd")):
            db.add(User(id=uid, username=uid, password_hash=hash_password(PW), full_name=uid.upper(),
                        role=role, is_active=1, tenant_id=tid, created_at=NOW, updated_at=NOW))
        db.add(Client(id="c-1", tenant_id=TENANT, client_number="K-1", first_name="Eva", last_name="Muster",
                      advisor_id="adv-1", created_at=NOW, updated_at=NOW))
        db.add(Mandate(id="m-1", tenant_id=TENANT, client_id="c-1", mandate_number="M-1",
                       mandate_type="Anlageberatung", opened_at=NOW, created_at=NOW, updated_at=NOW))
        ensure_test_legal_profile(db, TENANT)
        db.commit()
    try:
        yield factory
    finally:
        engine.dispose()


@pytest.fixture()
def client(session_factory):
    from services.login_guard import login_attempt_guard

    def override_db():
        with session_factory() as s:
            yield s
    app.dependency_overrides[get_db] = override_db
    login_attempt_guard._failures.clear()
    login_attempt_guard._locked_until.clear()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    login_attempt_guard._failures.clear()
    login_attempt_guard._locked_until.clear()


def _auth(client, uid: str) -> dict:
    r = client.post("/auth/login", json={"username": uid, "password": PW})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _propose(client, headers, **overrides) -> dict:
    body = {"jurisdiction": "CH", "policy_id": "TEST-C890-REV", "normal_max_months": 24,
            "elevated_max_months": 12, "valid_from": datetime.now(timezone.utc).date().isoformat(),
            "source_reference": "TEST-C890 Testwert (keine Owner-Frist)"}
    body.update(overrides)
    r = client.post("/compliance/kyc-review-policies", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _activate(client, headers, row: dict):
    return client.post(f"/compliance/kyc-review-policies/{row['id']}/activate", headers=headers,
                       json={"policy_hash": row["policy_hash"], "approval_reference": "TEST-C890 Freigabe extern"})


def test_reviewer_can_read_and_approve_but_not_capture(client, session_factory):
    admin, reviewer = _auth(client, "adm-1"), _auth(client, "rev-1")
    assert client.get("/auth/me", headers=reviewer).json()["role"] == "compliance_reviewer"
    r = client.post("/compliance/kyc-review-policies", headers=reviewer, json={
        "jurisdiction": "CH", "policy_id": "TEST-C890-X", "normal_max_months": 12,
        "valid_from": datetime.now(timezone.utc).date().isoformat(), "source_reference": "TEST-C890"})
    assert r.status_code == 403
    row = _propose(client, admin)
    overview = client.get("/compliance/kyc-review-policies", headers=reviewer)
    assert overview.status_code == 200 and overview.json()["status"] == "policy_unapproved"
    r = _activate(client, reviewer, row)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "wirksam" and r.json()["approved_by"] == "rev-1"
    assert client.get("/compliance/kyc-review-policies", headers=admin).json()["status"] == "effective"


@pytest.mark.parametrize("method, path, body", [
    ("GET", "/clients", None),
    ("GET", "/clients/c-1", None),
    ("PUT", "/clients/c-1", {"first_name": "X"}),
    ("GET", "/clients/c-1/kyc-confirmations", None),
    ("POST", "/clients/c-1/kyc-confirmations", {}),
    ("POST", "/clients/c-1/kyc-confirmations/k-1/approve", {}),
    ("GET", "/mandates/m-1", None),
    ("GET", "/mandates/m-1/client-onboarding/status", None),
    ("GET", "/compliance/legal-profile", None),
    ("PUT", "/compliance/legal-profile", {"legal_name": "X"}),
    ("GET", "/users", None),
    ("GET", "/admin/system/audit-log", None),
    ("GET", "/mandates/m-1/reports/vertrag.pdf", None),
])
def test_reviewer_has_no_access_to_client_or_system_routes(client, method, path, body):
    reviewer = _auth(client, "rev-1")
    r = client.request(method, path, headers=reviewer, json=body)
    assert r.status_code == 403, (path, r.status_code, r.text)
    assert r.json()["detail"]["reason_code"] == COMPLIANCE_REVIEWER_SCOPE


def test_reviewer_cannot_change_client_data_even_with_valid_body(client, session_factory):
    reviewer = _auth(client, "rev-1")
    r = client.put("/clients/c-1", headers=reviewer, json={"first_name": "Geaendert"})
    assert r.status_code == 403
    with session_factory() as db:
        assert db.get(Client, "c-1").first_name == "Eva"


def test_reviewer_of_another_tenant_cannot_see_or_approve(client):
    admin, foreign = _auth(client, "adm-1"), _auth(client, "rev-f")
    row = _propose(client, admin)
    assert _activate(client, foreign, row).status_code == 404
    assert client.get("/compliance/kyc-review-policies", headers=foreign).json()["policies"] == []


def test_self_approval_is_refused_for_admin_and_second_admin_still_works(client, session_factory):
    admin, second = _auth(client, "adm-1"), _auth(client, "adm-2")
    row = _propose(client, admin)
    r = _activate(client, admin, row)
    assert r.status_code == 403 and r.json()["detail"]["reason_code"] == "KYC_REVIEW_POLICY_SAME_PERSON"
    with session_factory() as db:
        assert db.query(KycReviewPolicyActivation).count() == 0
    assert _activate(client, second, row).status_code == 200


def test_advisor_can_neither_capture_nor_approve(client):
    admin, advisor = _auth(client, "adm-1"), _auth(client, "adv-1")
    row = _propose(client, admin)
    assert _activate(client, advisor, row).status_code == 403
    r = client.post("/compliance/kyc-review-policies", headers=advisor, json={
        "jurisdiction": "CH", "policy_id": "TEST-C890-X", "normal_max_months": 12,
        "valid_from": datetime.now(timezone.utc).date().isoformat(), "source_reference": "TEST-C890"})
    assert r.status_code == 403


def test_allowlist_is_exact():
    assert compliance_reviewer_may_call("GET", "/compliance/kyc-review-policies")
    assert compliance_reviewer_may_call("POST", "/compliance/kyc-review-policies/abc/activate")
    assert compliance_reviewer_may_call("GET", "/auth/me")
    for method, path in (("POST", "/compliance/kyc-review-policies"),
                         ("GET", "/compliance/kyc-review-policies/abc/activate"),
                         ("POST", "/compliance/kyc-review-policies/abc/activate/x"),
                         ("GET", "/compliance/legal-profile"),
                         ("GET", "/clients"),
                         ("DELETE", "/compliance/kyc-review-policies/abc")):
        assert not compliance_reviewer_may_call(method, path), (method, path)


def test_role_is_accepted_by_bootstrap_schema_and_user_schemas(tmp_path):
    import sqlite3

    import database as db_module
    from schemas.users import UserCreate, UserUpdate

    path = tmp_path / "boot.db"
    db_module.bootstrap_sqlite_schema(db_path=path, schema_path=BACKEND_ROOT / "ares_schema.sql")
    con = sqlite3.connect(path)
    con.execute("INSERT INTO users (id, username, password_hash, full_name, role, is_active, created_at, "
                "updated_at) VALUES ('r','r','x','R','compliance_reviewer',1,'n','n')")
    con.close()
    assert UserCreate(username="r", password="x" * 12, full_name="R", role="compliance_reviewer").role == (
        "compliance_reviewer")
    assert UserUpdate(role="compliance_reviewer").role == "compliance_reviewer"
