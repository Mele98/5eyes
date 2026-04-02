from __future__ import annotations
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
from models.wealth import Cashflow
from models.users import User
from services.auth import get_current_user
import uuid, datetime


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test_cf_proj.db'}",
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
        id="user-cfp-1", username="advisor", password_hash="h",
        full_name="Advisor", role="advisor", is_active=1,
        created_at="2026-04-02T00:00:00.000Z",
        updated_at="2026-04-02T00:00:00.000Z",
    )


@pytest.fixture()
def auth_client(session_factory, advisor_user):
    def override_db():
        with session_factory() as s:
            yield s
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: advisor_user
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _make_client(session_factory, advisor_id: str) -> str:
    cid = str(uuid.uuid4())
    now = datetime.datetime.utcnow().isoformat() + "Z"
    with session_factory() as s:
        s.add(Client(
            id=cid, client_number="CF-001", first_name="Hans", last_name="Muster",
            advisor_id=advisor_id, created_at=now, updated_at=now,
        ))
        s.commit()
    return cid


def _add_cashflow(session_factory, client_id: str, amount_rappen: int,
                  cf_type: str = "Income", frequency: str = "Jährlich") -> None:
    now = datetime.datetime.utcnow().isoformat() + "Z"
    with session_factory() as s:
        s.add(Cashflow(
            id=str(uuid.uuid4()), client_id=client_id,
            cashflow_type=cf_type, label="Test CF",
            amount_rappen=amount_rappen, frequency=frequency,
            is_active=1, created_at=now, updated_at=now,
        ))
        s.commit()


def test_cashflow_projection_returns_5_years(session_factory, auth_client, advisor_user):
    cid = _make_client(session_factory, advisor_user.id)
    _add_cashflow(session_factory, cid, 12_000_000)  # CHF 120k Income

    resp = auth_client.get(f"/clients/{cid}/cashflow-projection")

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["years"]) == 5
    assert all(row["income_rappen"] == 12_000_000 for row in data["years"])


def test_cashflow_projection_net_calculation(session_factory, auth_client, advisor_user):
    cid = _make_client(session_factory, advisor_user.id)
    _add_cashflow(session_factory, cid, 10_000_000, "Income")
    _add_cashflow(session_factory, cid, 4_000_000, "Expense")

    resp = auth_client.get(f"/clients/{cid}/cashflow-projection")

    assert resp.status_code == 200
    rows = resp.json()["years"]
    assert rows[0]["net_rappen"] == 6_000_000


def test_cashflow_projection_empty_client_returns_zeros(session_factory, auth_client, advisor_user):
    cid = _make_client(session_factory, advisor_user.id)

    resp = auth_client.get(f"/clients/{cid}/cashflow-projection")

    assert resp.status_code == 200
    rows = resp.json()["years"]
    assert all(r["net_rappen"] == 0 for r in rows)
