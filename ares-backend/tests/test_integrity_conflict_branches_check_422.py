"""RC-CH-1-F1 Nachtrag 2: Konflikt-Zweige (``except IntegrityError`` -> 409)
unterscheiden jetzt ueber ``core.db_integrity.raise_if_check_violation``:

* CHECK-Verstoss -> 422 ``DB_CHECK_CONSTRAINT_VIOLATION`` (zentraler Handler,
  ohne Werte) statt einer falschen Konfliktmeldung,
* UNIQUE -> unveraendert 409 mit der fachlichen Meldung der Aufrufstelle.

Echtes Schema (``init_db`` mit Rohschema-CHECKs). Den Integritaetsfehler
loest die Datenbank selbst aus: ein ``before_flush``-Hook veraendert genau im
Commit des Routers eine Zeile so, dass ein echter CHECK- bzw. UNIQUE-Verstoss
entsteht -- fuer den CHECK-Fall den Audit-Eintrag (``audit_log.action`` hat
eine CHECK-Werteliste, jeder Router schreibt ihn in derselben Transaktion).

Repraesentativ: ``POST /clients/{id}/mandates`` (mandates.py),
``PUT /fx-rates`` (fx_rates.py), ``POST /tenants`` (tenants.py).
Rueckname-Gegenprobe: ohne den Helper liefern die CHECK-Faelle 409.
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import database as db_module  # noqa: E402
from database import get_db, init_db  # noqa: E402
from main import app  # noqa: E402
from models import (  # noqa: E402,F401
    allocation, clients, mandates, profiling, review, snapshots, tenant, users, wealth,
)
from models.mandates import Mandate  # noqa: E402
from models.review import AuditLog  # noqa: E402
from models.users import User  # noqa: E402
from services.auth import get_current_user  # noqa: E402
from tests.risk_fixture_helpers import noop_lifespan  # noqa: E402

configure_mappers()


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path, monkeypatch):
    db_path = tmp_path / "conflict_branches_real_schema.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    db_module.attach_sqlite_pragmas(engine)
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module.settings, "db_bootstrap_schema_on_startup", True)
    init_db(engine)
    sf = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    try:
        yield sf
    finally:
        engine.dispose()


@pytest.fixture()
def root_user():
    return User(
        id="user-conflict-root", username="root-conflict", password_hash="h",
        full_name="Root", role="super_admin", is_active=1, tenant_id=None,
        created_at=_now(), updated_at=_now(),
    )


@pytest.fixture()
def advisor_user():
    return User(
        id="user-conflict-admin", username="admin-conflict", password_hash="h",
        full_name="Admin", role="admin", is_active=1, tenant_id="main",
        created_at=_now(), updated_at=_now(),
    )


@pytest.fixture()
def api(session_factory, root_user, advisor_user, monkeypatch):
    with session_factory() as db:
        db.merge(root_user)
        db.merge(advisor_user)
        db.commit()

    def override_db():
        with session_factory() as session:
            yield session

    from config import settings

    monkeypatch.setattr(settings, "tenant_admin_ui_enabled", True, raising=False)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: root_user
    monkeypatch.setattr(app.router, "lifespan_context", noop_lifespan)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
    app.dependency_overrides.clear()


class _Inject:
    """before_flush-Hook: veraendert im naechsten Flush eine neue Zeile."""

    def __init__(self, mutate):
        self.mutate = mutate
        self.fired = 0

    def __call__(self, session, _ctx, _instances):
        for obj in list(session.new):
            if self.mutate(obj):
                self.fired += 1

    def __enter__(self):
        event.listen(Session, "before_flush", self)
        return self

    def __exit__(self, *exc):
        event.remove(Session, "before_flush", self)


def _invalid_audit_action(obj) -> bool:
    if isinstance(obj, AuditLog):
        obj.action = "__AUSSERHALB_DER_WERTELISTE__"
        return True
    return False


def _client(api, user) -> str:
    """Mandats-Faelle laufen als Firmen-Admin (super_admin darf keine Kunden anlegen)."""
    app.dependency_overrides[get_current_user] = lambda: user
    r = api.post("/clients", json={
        "client_number": "CONFLICT-001", "first_name": "Kon", "last_name": "Flikt",
        "advisor_id": user.id, "household_type": "Einzelperson",
    })
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _assert_check_422(r, inject):
    assert inject.fired, "Vorbedingung: der Hook hat keine Zeile veraendert"
    assert r.status_code == 422, (r.status_code, r.text)
    assert r.json()["detail"]["reason_code"] == "DB_CHECK_CONSTRAINT_VIOLATION"
    assert "AUSSERHALB" not in r.text


def test_mandate_create_check_violation_is_422(api, advisor_user):
    cid = _client(api, advisor_user)
    with _Inject(_invalid_audit_action) as inject:
        r = api.post(f"/clients/{cid}/mandates", json={
            "mandate_number": "CONFLICT-M-001", "mandate_type": "Anlageberatung",
        })
    _assert_check_422(r, inject)


def test_mandate_create_unique_violation_keeps_409(api, advisor_user):
    """Gegenkontrolle: ein echter UNIQUE-Verstoss (Race nach dem Pre-Check)
    bleibt das bisherige 409 mit fachlicher Meldung."""
    cid = _client(api, advisor_user)
    first = api.post(f"/clients/{cid}/mandates", json={
        "mandate_number": "CONFLICT-M-001", "mandate_type": "Anlageberatung",
    })
    assert first.status_code == 201, first.text

    def duplicate_number(obj) -> bool:
        if isinstance(obj, Mandate) and obj.mandate_number == "CONFLICT-M-002":
            obj.mandate_number = "CONFLICT-M-001"
            return True
        return False

    with _Inject(duplicate_number) as inject:
        r = api.post(f"/clients/{cid}/mandates", json={
            "mandate_number": "CONFLICT-M-002", "mandate_type": "Anlageberatung",
        })
    assert inject.fired
    assert r.status_code == 409, (r.status_code, r.text)
    assert "DB_CHECK_CONSTRAINT_VIOLATION" not in r.text


def test_fx_rates_check_violation_is_422(api):
    with _Inject(_invalid_audit_action) as inject:
        r = api.put("/fx-rates", json={"rates": [{"currency": "usd", "rate": 0.9, "source": "Manual"}]})
    _assert_check_422(r, inject)


def test_tenant_create_check_violation_is_422(api):
    with _Inject(_invalid_audit_action) as inject:
        r = api.post("/tenants", json={"display_name": "Konflikt AG", "slug": "konflikt-ag"})
    _assert_check_422(r, inject)
