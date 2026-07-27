"""2026-07-27 (Retrozessions-Feature): create_conflict fuellt
reimbursed_to_client aus der firmenweiten Tenant-Vorbelegung auf, wenn der
Client es nicht explizit angibt (None = "nicht angegeben", nicht "False").
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, get_db
from main import app
from models.clients import Client
from models.mandates import Mandate
from models.tenant import Tenant
from models.users import User
from services.auth import get_current_user


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'retro_default.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _seed_mandate(SF, *, tenant_id: str | None, default_reimbursement: int = 0):
    advisor_id = "advisor-retro"
    cid = "client-retro"
    mid = "mandate-retro"
    now = _now()
    with SF() as s:
        if tenant_id:
            s.add(Tenant(
                id=tenant_id, display_name="Firma", slug=tenant_id.lower(),
                hosting_tier="tier2", license_status="active",
                default_retrocession_reimbursement=default_reimbursement,
                is_active=1, created_at=now, updated_at=now,
            ))
        s.add(User(
            id=advisor_id, username=advisor_id, password_hash="h",
            full_name="Advisor", role="advisor", is_active=1, tenant_id=tenant_id,
            created_at=now, updated_at=now,
        ))
        s.add(Client(
            id=cid, client_number="C-RETRO", first_name="T", last_name="X",
            advisor_id=advisor_id, tenant_id=tenant_id,
            created_at=now, updated_at=now,
        ))
        s.add(Mandate(
            id=mid, client_id=cid, tenant_id=tenant_id, mandate_number="M-RETRO",
            mandate_type="Anlageberatung", opened_at=now,
            created_at=now, updated_at=now,
        ))
        s.commit()
    return advisor_id, mid


@pytest.fixture()
def client(session_factory):
    def override_db():
        with session_factory() as s:
            yield s
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _login_as(advisor_id):
    with_session_user = User(id=advisor_id, username=advisor_id, password_hash="h",
                              full_name="Advisor", role="advisor", is_active=1)
    app.dependency_overrides[get_current_user] = lambda: with_session_user


def _conflict_payload(**overrides):
    base = {
        "conflict_type": "Retrozession / Inducement",
        "description": "Vertriebsentschaedigung durch Produktanbieter.",
        "inducement_amount_rappen": 5000,
        "inducement_frequency": "jährlich",
    }
    base.update(overrides)
    return base


def test_defaults_to_false_when_no_tenant_setting(client, session_factory):
    advisor_id, mid = _seed_mandate(session_factory, tenant_id=None)
    _login_as(advisor_id)
    try:
        resp = client.post(f"/mandates/{mid}/conflicts", json=_conflict_payload())
        assert resp.status_code == 201, resp.text
        assert resp.json()["reimbursed_to_client"] == 0
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_fills_from_tenant_default_true(client, session_factory):
    advisor_id, mid = _seed_mandate(session_factory, tenant_id="firm-retro-true", default_reimbursement=1)
    _login_as(advisor_id)
    try:
        resp = client.post(f"/mandates/{mid}/conflicts", json=_conflict_payload())
        assert resp.status_code == 201, resp.text
        assert resp.json()["reimbursed_to_client"] == 1
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_fills_from_tenant_default_false(client, session_factory):
    advisor_id, mid = _seed_mandate(session_factory, tenant_id="firm-retro-false", default_reimbursement=0)
    _login_as(advisor_id)
    try:
        resp = client.post(f"/mandates/{mid}/conflicts", json=_conflict_payload())
        assert resp.status_code == 201, resp.text
        assert resp.json()["reimbursed_to_client"] == 0
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_explicit_value_overrides_tenant_default(client, session_factory):
    advisor_id, mid = _seed_mandate(session_factory, tenant_id="firm-retro-override", default_reimbursement=0)
    _login_as(advisor_id)
    try:
        resp = client.post(
            f"/mandates/{mid}/conflicts",
            json=_conflict_payload(reimbursed_to_client=True, waiver_document_id="doc-123"),
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["reimbursed_to_client"] == 1
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_explicit_false_is_not_overridden_by_tenant_default_true(client, session_factory):
    """Ein explizites False darf NICHT durch den Tenant-Default (True) ueberschrieben
    werden -- nur ein tatsaechliches None ('nicht angegeben') loest den Fallback aus."""
    advisor_id, mid = _seed_mandate(session_factory, tenant_id="firm-retro-explicit-false", default_reimbursement=1)
    _login_as(advisor_id)
    try:
        resp = client.post(
            f"/mandates/{mid}/conflicts",
            json=_conflict_payload(reimbursed_to_client=False),
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["reimbursed_to_client"] == 0
    finally:
        app.dependency_overrides.pop(get_current_user, None)
