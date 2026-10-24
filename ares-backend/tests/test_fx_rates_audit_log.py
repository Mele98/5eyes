"""2026-07-24 (Generalaudit): PUT /fx-rates aenderte Wechselkurse (global,
wirkt auf ALLE Tenants, kein tenant_id auf FXRate) ohne jeden zentralen
AuditLog-Eintrag -- im Nachhinein war nicht nachvollziehbar, wer wann
welchen Kurs auf welchen Wert gesetzt hat. Falsche/manipulierte FX-Kurse
verzerren Fremdwaehrungs-Betraege systemweit in Beratungsdokumenten.
"""
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
from models.review import AuditLog
from models.users import User
from services.auth import get_current_user


def _now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'fx_rates_audit.db'}",
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
        id="advisor-fx-audit", username="advisor-fx-audit", password_hash="h",
        full_name="FX Advisor", role="advisor", is_active=1,
        created_at=_now_iso(), updated_at=_now_iso(),
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


def test_upsert_writes_audit_log_entry(auth_client, session_factory, advisor_user):
    resp = auth_client.put(
        "/fx-rates",
        json={"rates": [{"currency": "usd", "rate": 0.9, "source": "Manual"}]},
    )
    assert resp.status_code == 200, resp.text

    with session_factory() as s:
        rows = s.query(AuditLog).filter(
            AuditLog.table_name == "fx_rates",
            AuditLog.action == "UPSERT",
        ).all()
    assert len(rows) == 1
    assert rows[0].field_name == "USD"
    assert rows[0].new_value == "0.9000"
    assert rows[0].old_value is None  # erste Version, kein Vorgaenger
    assert rows[0].user_id == advisor_user.id


def test_second_upsert_logs_old_and_new_value(auth_client, session_factory, advisor_user):
    auth_client.put("/fx-rates", json={"rates": [{"currency": "eur", "rate": 0.95}]})
    resp = auth_client.put("/fx-rates", json={"rates": [{"currency": "eur", "rate": 0.97}]})
    assert resp.status_code == 200, resp.text

    with session_factory() as s:
        rows = s.query(AuditLog).filter(
            AuditLog.table_name == "fx_rates",
            AuditLog.field_name == "EUR",
        ).order_by(AuditLog.created_at.asc()).all()
    assert len(rows) == 2
    assert rows[1].old_value == "0.9500"
    assert rows[1].new_value == "0.9700"


def test_multiple_currencies_in_one_request_each_logged_separately(auth_client, session_factory):
    resp = auth_client.put(
        "/fx-rates",
        json={"rates": [
            {"currency": "usd", "rate": 0.9},
            {"currency": "gbp", "rate": 1.12},
        ]},
    )
    assert resp.status_code == 200, resp.text
    with session_factory() as s:
        rows = s.query(AuditLog).filter(AuditLog.table_name == "fx_rates").all()
    assert {r.field_name for r in rows} == {"USD", "GBP"}
