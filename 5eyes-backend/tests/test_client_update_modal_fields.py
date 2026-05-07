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

from database import Base, get_db
from main import app
from models.clients import Client
from models.users import User
from services.auth import get_current_user


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test_client_update.db'}",
        connect_args={"check_same_thread": False},
    )
    sf = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield sf
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def advisor_user():
    return User(
        id="user-client-update-1",
        username="advisor",
        password_hash="h",
        full_name="Advisor",
        role="advisor",
        is_active=1,
        created_at="2026-04-04T00:00:00.000Z",
        updated_at="2026-04-04T00:00:00.000Z",
    )


@pytest.fixture()
def auth_client(session_factory, advisor_user):
    def override_db():
        with session_factory() as s:
            yield s

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: advisor_user
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def _make_client(session_factory, advisor_id: str) -> str:
    cid = str(uuid.uuid4())
    now = _utc_now_iso()
    with session_factory() as s:
        s.add(
            Client(
                id=cid,
                client_number="CL-001",
                salutation="Herr",
                first_name="Andreas",
                last_name="Mueller",
                advisor_id=advisor_id,
                household_type="Paar",
                profession="CFO",
                employer="Muster AG",
                partner_salutation="Frau",
                partner_first_name="Sandra",
                partner_last_name="Weber",
                partner_date_of_birth="1978-06-01",
                partner_profession="Beraterin",
                created_at=now,
                updated_at=now,
            )
        )
        s.commit()
    return cid


def test_update_client_allows_explicit_null_partner_fields(session_factory, auth_client, advisor_user):
    cid = _make_client(session_factory, advisor_user.id)

    resp = auth_client.put(
        f"/clients/{cid}",
        json={
            "household_type": "Einzelperson",
            "partner_salutation": None,
            "partner_first_name": None,
            "partner_last_name": None,
            "partner_date_of_birth": None,
            "partner_profession": None,
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["household_type"] == "Einzelperson"
    assert data["partner_salutation"] is None
    assert data["partner_first_name"] is None
    assert data["partner_last_name"] is None
    assert data["partner_date_of_birth"] is None
    assert data["partner_profession"] is None

    with session_factory() as s:
        client = s.query(Client).filter(Client.id == cid).first()
        assert client is not None
        assert client.household_type == "Einzelperson"
        assert client.partner_salutation is None
        assert client.partner_first_name is None
        assert client.partner_last_name is None
        assert client.partner_date_of_birth is None
        assert client.partner_profession is None


def test_update_client_persists_salutation_and_employer(session_factory, auth_client, advisor_user):
    cid = _make_client(session_factory, advisor_user.id)
    with session_factory() as s:
        before = s.query(Client).filter(Client.id == cid).one().updated_at

    resp = auth_client.put(
        f"/clients/{cid}",
        json={
            "salutation": "Divers",
            "employer": "Neue Arbeit AG",
            "profession": "Unternehmer",
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["salutation"] == "Divers"
    assert data["employer"] == "Neue Arbeit AG"
    assert data["profession"] == "Unternehmer"

    with session_factory() as s:
        client = s.query(Client).filter(Client.id == cid).one()
        assert client.updated_at != before
