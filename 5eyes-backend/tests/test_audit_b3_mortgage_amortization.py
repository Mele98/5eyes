"""B3 - Hypothek-Tilgung darf nicht als Cashflow erfasst werden.

Bilanzielle Sicht (Swiss GAAP FER 16, OR 957a): Tilgung ist Reklassifikation
(Vermoegen sinkt, Liability sinkt um den selben Betrag), KEIN Aufwand.
Wenn als Expense-Cashflow erfasst UND eine Hypothek-Liability existiert,
fuehrt das zu Doppel-Belastung der Strategie (Vermoegen schrumpft scheinbar
schneller -> falsche Reserve -> falsche Asset-Allokation).

Backend-Validierung: Cashflow Create/Update mit Expense + Label
"Tilgung/Amortisation" + bestehender Hypothek-Liability -> 422.
"""
from __future__ import annotations
import sys
import datetime
import uuid
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
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
configure_mappers()

from main import app
from models.clients import Client
from models.users import User
from models.wealth import Cashflow, WealthPosition
from services.auth import get_current_user, require_advisor


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'audit_b3.db'}",
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
def advisor():
    return User(id="user-b3-1", username="adv", password_hash="h",
                full_name="Adv", role="advisor", is_active=1,
                created_at=_now(), updated_at=_now())


@pytest.fixture()
def auth_client(session_factory, advisor):
    def _odb():
        with session_factory() as s:
            yield s
    app.dependency_overrides[get_db] = _odb
    app.dependency_overrides[get_current_user] = lambda: advisor
    app.dependency_overrides[require_advisor] = lambda: advisor
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _make_client_with_mortgage(session_factory, advisor) -> str:
    cid = str(uuid.uuid4())
    now = _now()
    with session_factory() as s:
        if not s.query(User).filter(User.id == advisor.id).first():
            s.add(advisor)
        s.add(Client(id=cid, client_number=f"C-{cid[:6]}",
                     first_name="T", last_name="X",
                     advisor_id=advisor.id,
                     created_at=now, updated_at=now))
        s.add(WealthPosition(
            id=f"hypo-{cid[:6]}", client_id=cid,
            label="Hypothek Eigenheim", position_type="Hypothek",
            assignment="Verbindlichkeit",
            current_value_rappen=600_000_00, currency="CHF",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.commit()
    return cid


def _make_client_without_mortgage(session_factory, advisor) -> str:
    cid = str(uuid.uuid4())
    now = _now()
    with session_factory() as s:
        if not s.query(User).filter(User.id == advisor.id).first():
            s.add(advisor)
        s.add(Client(id=cid, client_number=f"C-{cid[:6]}",
                     first_name="T", last_name="X",
                     advisor_id=advisor.id,
                     created_at=now, updated_at=now))
        s.commit()
    return cid


# ============================================================================
# B3.1 - Validierung beim CREATE
# ============================================================================

def test_b3_create_amortization_with_mortgage_returns_422(
    auth_client, session_factory, advisor
):
    cid = _make_client_with_mortgage(session_factory, advisor)
    resp = auth_client.post(
        f"/clients/{cid}/cashflows",
        json={
            "cashflow_type": "Expense",
            "label": "Hypothek-Tilgung",
            "amount_rappen": 5_000_00,
            "frequency": "jährlich",
        },
    )
    assert resp.status_code == 422, resp.text
    assert "Tilgung" in resp.text or "Amortisation" in resp.text or "Hypothek" in resp.text


def test_b3_create_amortization_without_mortgage_allowed(
    auth_client, session_factory, advisor
):
    """Wenn keine Hypothek-Liability existiert, ist 'Tilgung'-Label
    semantisch fragwuerdig aber kein Doppel-Counting."""
    cid = _make_client_without_mortgage(session_factory, advisor)
    resp = auth_client.post(
        f"/clients/{cid}/cashflows",
        json={
            "cashflow_type": "Expense",
            "label": "Tilgung",
            "amount_rappen": 5_000_00,
            "frequency": "jährlich",
        },
    )
    assert resp.status_code == 201, resp.text


def test_b3_create_zinsen_with_mortgage_allowed(
    auth_client, session_factory, advisor
):
    """Hypothek-Zinsen sind echter Aufwand und MUESSEN als Cashflow erfasst werden."""
    cid = _make_client_with_mortgage(session_factory, advisor)
    resp = auth_client.post(
        f"/clients/{cid}/cashflows",
        json={
            "cashflow_type": "Expense",
            "label": "Hypothek-Zinsen",
            "amount_rappen": 9_000_00,
            "frequency": "jährlich",
        },
    )
    assert resp.status_code == 201, resp.text


def test_b3_create_income_with_amortization_label_allowed(
    auth_client, session_factory, advisor
):
    """Income-Cashflow mit zufaelligem 'Tilgung'-Label ist kein Doppel-Counting."""
    cid = _make_client_with_mortgage(session_factory, advisor)
    resp = auth_client.post(
        f"/clients/{cid}/cashflows",
        json={
            "cashflow_type": "Income",
            "label": "Erstattung Tilgung Vorperiode",
            "amount_rappen": 5_000_00,
            "frequency": "einmalig",
            "valid_from": "2026-06-01",
        },
    )
    assert resp.status_code == 201, resp.text


# ============================================================================
# B3.2 - Validierung beim UPDATE
# ============================================================================

def test_b3_update_label_to_amortization_returns_422(
    auth_client, session_factory, advisor
):
    """Bestehender Cashflow wird auf 'Tilgung' umbenannt -> 422."""
    cid = _make_client_with_mortgage(session_factory, advisor)
    resp_create = auth_client.post(
        f"/clients/{cid}/cashflows",
        json={
            "cashflow_type": "Expense",
            "label": "Hypothek-Zinsen",
            "amount_rappen": 9_000_00,
            "frequency": "jährlich",
        },
    )
    assert resp_create.status_code == 201
    cf_id = resp_create.json()["id"]

    resp_update = auth_client.put(
        f"/clients/{cid}/cashflows/{cf_id}",
        json={"label": "Hypothek-Amortisation"},
    )
    assert resp_update.status_code == 422, resp_update.text


# ============================================================================
# B3.3 - Diverse Schreibweisen erkennen
# ============================================================================

@pytest.mark.parametrize("label", [
    "Tilgung",
    "Hypothek-Tilgung",
    "Amortisation",
    "Hypothek Amortisation",
    "Hypothek - amortization plan",
    "TILGUNG",
    "tilgung 2026",
])
def test_b3_create_various_amortization_labels_blocked(
    auth_client, session_factory, advisor, label
):
    cid = _make_client_with_mortgage(session_factory, advisor)
    resp = auth_client.post(
        f"/clients/{cid}/cashflows",
        json={
            "cashflow_type": "Expense",
            "label": label,
            "amount_rappen": 5_000_00,
            "frequency": "jährlich",
        },
    )
    assert resp.status_code == 422, f"Label '{label}' sollte blockiert sein, war {resp.status_code}"
