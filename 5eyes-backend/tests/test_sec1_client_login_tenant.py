"""SEC-1 (2026-07-04): Client-Login-User erbt tenant_id (kein NULL-Tenant mehr).

Deckt alle Akzeptanzkriterien aus docs/planning/2026-07-03-top10-implementation-specs.md
Abschnitt "1. SEC-1":
  - Berater A (tenant firma-a) legt Client-Login an -> User.tenant_id == "firma-a".
  - Client mit eigenem Tenant -> User erbt Client-Tenant (Vorrang vor Berater-Tenant).
  - Legacy (beide NULL, single, non-strict) -> erlaubt, NULL bleibt (BC).
  - tenancy_mode="multi"/strict + kein Tenant ableitbar -> 409, kein User in DB.
  - Backfill: NULL-User + Client firma-b -> nach Backfill firma-b (NICHT main);
    2. Lauf idempotent; fehlende Tabelle crasht nicht.
  - Regression: fremder Firmen-Admin (firma-b) sieht den neuen Client-User nicht.
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base  # noqa: E402
from main import app  # noqa: E402,F401  (registriert alle Models fuer FK-Aufloesung)
import database as database_mod  # noqa: E402
from models.users import User  # noqa: E402
from models.clients import Client  # noqa: E402
from models.client_login import ClientLogin  # noqa: E402
from routers.clients import create_client_login  # noqa: E402


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture
def engine(tmp_path):
    eng = create_engine(
        f"sqlite:///{tmp_path / 'sec1_client_login.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=eng)
    try:
        yield eng
    finally:
        Base.metadata.drop_all(bind=eng)
        eng.dispose()


@pytest.fixture
def session_factory(engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _user(uid, tenant_id, role="advisor"):
    return User(
        id=uid, username=uid, password_hash="h", full_name=uid, role=role,
        is_active=1, tenant_id=tenant_id, created_at=_now(), updated_at=_now(),
    )


def _client(cid, advisor_id, tenant_id):
    return Client(
        id=cid, client_number=cid, first_name=cid, last_name="Test",
        advisor_id=advisor_id, tenant_id=tenant_id, household_type="Einzelperson",
        client_classification="Privatkunde", country_of_residence="CH", language="DE",
        created_at=_now(), updated_at=_now(),
    )


def _body(username="kunde1", password="password123"):
    return {"username": username, "password": password}


# ── Akzeptanzkriterium 1: Berater-Tenant vererbt ──────────────────────────────

def test_client_login_inherits_advisor_tenant(session_factory):
    with session_factory() as db:
        adv = _user("adv-a", tenant_id="firma-a")
        db.add_all([adv, _client("c-a", advisor_id="adv-a", tenant_id="firma-a")])
        db.commit()
        res = create_client_login(
            client_id="c-a", body=_body(), db=db, current_user=adv,
        )
        created = db.query(User).filter(User.id == res["user_id"]).one()
        assert created.role == "client"
        assert created.tenant_id == "firma-a"


# ── Akzeptanzkriterium 2: Client-Tenant hat Vorrang ───────────────────────────

def test_client_tenant_takes_precedence_over_advisor(session_factory):
    # Berater ohne eigenen Tenant (Legacy, kein Tenant-Filter greift -> sieht den
    # Client), der Client selbst gehoert firma-x. Der abgeleitete Tenant MUSS der
    # des Clients sein (Vorrang vor dem — hier leeren — Berater-Tenant).
    with session_factory() as db:
        adv = _user("adv-a2", tenant_id=None)
        db.add_all([adv, _client("c-x", advisor_id="adv-a2", tenant_id="firma-x")])
        db.commit()
        res = create_client_login(
            client_id="c-x", body=_body(), db=db, current_user=adv,
        )
        created = db.query(User).filter(User.id == res["user_id"]).one()
        assert created.tenant_id == "firma-x"


# ── Akzeptanzkriterium 3: Legacy (beide NULL, single/non-strict) -> NULL bleibt

def test_legacy_null_tenant_allowed_in_single_nonstrict(session_factory, monkeypatch):
    monkeypatch.setattr(database_mod.settings, "tenancy_mode", "single", raising=False)
    monkeypatch.setattr(database_mod.settings, "strict_tenant_isolation", False, raising=False)
    with session_factory() as db:
        adv = _user("adv-legacy", tenant_id=None)
        db.add_all([adv, _client("c-legacy", advisor_id="adv-legacy", tenant_id=None)])
        db.commit()
        res = create_client_login(
            client_id="c-legacy", body=_body(), db=db, current_user=adv,
        )
        created = db.query(User).filter(User.id == res["user_id"]).one()
        assert created.tenant_id is None


# ── Akzeptanzkriterium 4a: multi + kein Tenant -> 409, kein User ──────────────

def test_multi_mode_without_tenant_raises_409(session_factory, monkeypatch):
    monkeypatch.setattr(database_mod.settings, "tenancy_mode", "multi", raising=False)
    monkeypatch.setattr(database_mod.settings, "strict_tenant_isolation", False, raising=False)
    with session_factory() as db:
        adv = _user("adv-multi", tenant_id=None)
        db.add_all([adv, _client("c-multi", advisor_id="adv-multi", tenant_id=None)])
        db.commit()
        with pytest.raises(HTTPException) as exc:
            create_client_login(
                client_id="c-multi", body=_body(), db=db, current_user=adv,
            )
        assert exc.value.status_code == 409
        db.rollback()
        # Kein Client-User in der DB angelegt.
        assert db.query(User).filter(User.role == "client").count() == 0
        assert db.query(ClientLogin).count() == 0


# ── Akzeptanzkriterium 4b: strict + kein Tenant -> 409 ────────────────────────

def test_strict_mode_without_tenant_raises_409(session_factory, monkeypatch):
    monkeypatch.setattr(database_mod.settings, "tenancy_mode", "single", raising=False)
    monkeypatch.setattr(database_mod.settings, "strict_tenant_isolation", True, raising=False)
    with session_factory() as db:
        adv = _user("adv-strict", tenant_id=None)
        db.add_all([adv, _client("c-strict", advisor_id="adv-strict", tenant_id=None)])
        db.commit()
        with pytest.raises(HTTPException) as exc:
            create_client_login(
                client_id="c-strict", body=_body(), db=db, current_user=adv,
            )
        assert exc.value.status_code == 409
        db.rollback()
        assert db.query(User).filter(User.role == "client").count() == 0


def test_strict_mode_with_derivable_tenant_succeeds(session_factory, monkeypatch):
    # Strict aktiv, aber Tenant ist ableitbar -> kein 409, User bekommt Tenant.
    monkeypatch.setattr(database_mod.settings, "strict_tenant_isolation", True, raising=False)
    with session_factory() as db:
        adv = _user("adv-strict-ok", tenant_id="firma-a")
        db.add_all([adv, _client("c-strict-ok", advisor_id="adv-strict-ok", tenant_id="firma-a")])
        db.commit()
        res = create_client_login(
            client_id="c-strict-ok", body=_body(), db=db, current_user=adv,
        )
        created = db.query(User).filter(User.id == res["user_id"]).one()
        assert created.tenant_id == "firma-a"


# ── Akzeptanzkriterium 5: Backfill zieht Client-Tenant (nicht 'main') ─────────

def test_backfill_sets_client_tenant_not_main(session_factory, engine):
    with session_factory() as db:
        # Legacy-Zustand simulieren: Client-User mit NULL-Tenant + Linkage.
        adv = _user("adv-b", tenant_id="firma-b")
        cl = _client("c-b", advisor_id="adv-b", tenant_id="firma-b")
        legacy_user = User(
            id="legacy-client-user", username="legacy", password_hash="h",
            full_name="Legacy", role="client", is_active=1, tenant_id=None,
            created_at=_now(), updated_at=_now(),
        )
        link = ClientLogin(
            id="link-b", user_id="legacy-client-user", client_id="c-b",
            created_by="adv-b", created_at=_now(), is_active=1,
        )
        db.add_all([adv, cl, legacy_user, link])
        db.commit()

    database_mod.ensure_client_login_user_tenant_backfill(engine_to_use=engine)

    with session_factory() as db:
        u = db.query(User).filter(User.id == "legacy-client-user").one()
        assert u.tenant_id == "firma-b"  # NICHT 'main'


def test_backfill_is_idempotent(session_factory, engine):
    with session_factory() as db:
        adv = _user("adv-idem", tenant_id="firma-c")
        cl = _client("c-idem", advisor_id="adv-idem", tenant_id="firma-c")
        legacy_user = User(
            id="idem-user", username="idem", password_hash="h", full_name="Idem",
            role="client", is_active=1, tenant_id=None,
            created_at=_now(), updated_at=_now(),
        )
        link = ClientLogin(
            id="link-idem", user_id="idem-user", client_id="c-idem",
            created_by="adv-idem", created_at=_now(), is_active=1,
        )
        db.add_all([adv, cl, legacy_user, link])
        db.commit()

    database_mod.ensure_client_login_user_tenant_backfill(engine_to_use=engine)
    # Zweiter Lauf trifft 0 Rows, aendert nichts.
    database_mod.ensure_client_login_user_tenant_backfill(engine_to_use=engine)

    with session_factory() as db:
        u = db.query(User).filter(User.id == "idem-user").one()
        assert u.tenant_id == "firma-c"


def test_backfill_missing_table_does_not_crash(tmp_path):
    # Engine ohne client_logins-Tabelle -> Backfill darf nicht crashen.
    eng = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    try:
        database_mod.ensure_client_login_user_tenant_backfill(engine_to_use=eng)
    finally:
        eng.dispose()


def test_backfill_leaves_null_client_tenant_untouched(session_factory, engine):
    # Client selbst ohne Tenant -> Backfill kann keinen Wert ableiten,
    # zieht die Row NICHT faelschlich nach 'main' (das macht der generische Backfill).
    with session_factory() as db:
        adv = _user("adv-null", tenant_id=None)
        cl = _client("c-null", advisor_id="adv-null", tenant_id=None)
        legacy_user = User(
            id="null-user", username="nulluser", password_hash="h", full_name="Null",
            role="client", is_active=1, tenant_id=None,
            created_at=_now(), updated_at=_now(),
        )
        link = ClientLogin(
            id="link-null", user_id="null-user", client_id="c-null",
            created_by="adv-null", created_at=_now(), is_active=1,
        )
        db.add_all([adv, cl, legacy_user, link])
        db.commit()

    database_mod.ensure_client_login_user_tenant_backfill(engine_to_use=engine)

    with session_factory() as db:
        u = db.query(User).filter(User.id == "null-user").one()
        assert u.tenant_id is None


# ── Akzeptanzkriterium 6: Cross-Tenant-Unsichtbarkeit (Regression) ────────────

def test_cross_tenant_user_not_visible_to_foreign_admin(session_factory):
    # Neuer Client-User von firma-a ist NICHT mehr fuer firma-b sichtbar, weil
    # er einen echten Tenant traegt (statt NULL, das fuer jeden Tenant sichtbar waere).
    with session_factory() as db:
        adv_a = _user("adv-a3", tenant_id="firma-a")
        db.add_all([adv_a, _client("c-a3", advisor_id="adv-a3", tenant_id="firma-a")])
        db.commit()
        res = create_client_login(
            client_id="c-a3", body=_body(), db=db, current_user=adv_a,
        )
        created = db.query(User).filter(User.id == res["user_id"]).one()

    # Sichtbarkeitslogik aus routers/auth.update_user (non-strict): sichtbar, wenn
    # Tenant-Match ODER (non-strict UND Row-Tenant leer). firma-b sieht firma-a
    # nur, wenn der User NULL-Tenant haette -> genau das verhindert SEC-1.
    foreign_tid = "firma-b"
    row_tid = (getattr(created, "tenant_id", None) or "").strip()
    visible_nonstrict = (row_tid == foreign_tid) or (row_tid == "")
    assert row_tid == "firma-a"
    assert visible_nonstrict is False
