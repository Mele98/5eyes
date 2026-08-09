"""Live-Playwright-Fund (2026-08-09, FINIG-Gate-Test): create_user()/
invite_user() (routers/auth.py) pruefen Quota IMMER gegen die eigene
Operator-Firma (current_user.tenant_id), auch wenn ein super_admin gerade
einen Mitarbeiter fuer eine ANDERE, frisch provisionierte Firma anlegt (der
Frontend-Flow provCreateEmployee()/provInviteEmployee() macht das planmaessig:
User anlegen -> per PUT .../assign in die Ziel-Firma verschieben). War die
(typischerweise winzige, oft max_users=1) Operator-Firma bereits ausgeschoepft,
blockte das JEDE Mitarbeiter-Provisionierung fuer JEDE neue Firma -- live im
Browser reproduziert.

Fix: UserCreate/InviteCreate bekommen ein optionales tenant_id-Feld, das NUR
fuer current_user.role=="super_admin" ausgewertet wird (Quota + tenant_id-
Zuweisung greifen dann direkt gegen die angegebene Ziel-Firma, kein Zwei-
Schritt-Umweg mehr noetig). Fuer regulaere admin-Aufrufer bleibt das Feld
wirkungslos -- kein Privilege-Escalation-Pfad, um fremde Firmen-Quotas zu
pruefen oder zu umgehen.
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

from database import Base
from main import app  # noqa: F401  register all models
from models.tenant import Tenant
from models.users import User
from routers.auth import create_user, invite_user
from schemas.users import InviteCreate, UserCreate


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'cross_tenant_provisioning.db'}",
        connect_args={"check_same_thread": False},
    )
    sf = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield sf
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


class _FakeRequest:
    def __init__(self, host="127.0.0.1"):
        self.headers = {}
        self.client = type("C", (), {"host": host})()
        self.base_url = "http://testserver/"


def _tenant(tenant_id: str, *, max_users: int | None) -> Tenant:
    return Tenant(
        id=tenant_id, display_name=f"Tenant {tenant_id}", slug=tenant_id.lower(),
        hosting_tier="tier2", license_status="active", max_users=max_users,
        is_active=1, created_at=_now(), updated_at=_now(),
    )


def _user(uid: str, tenant_id: str | None, role: str) -> User:
    return User(
        id=uid, username=uid, password_hash="h", full_name=uid, role=role,
        is_active=1, tenant_id=tenant_id, created_at=_now(), updated_at=_now(),
    )


def _user_body(username: str, tenant_id: str | None = None) -> UserCreate:
    return UserCreate(
        username=username, password="pw1234567890", full_name=f"User {username}",
        role="advisor", tenant_id=tenant_id,
    )


def _invite_body(username: str, tenant_id: str | None = None) -> InviteCreate:
    return InviteCreate(username=username, full_name=f"User {username}", role="advisor", tenant_id=tenant_id)


def test_super_admin_can_provision_into_other_tenant_despite_own_quota_full(session_factory):
    """Der Kernfund: Operator-Firma ('main') ist bei max_users=1 bereits voll
    (nur der Operator selbst) -- die Ziel-Firma hat aber Platz. Ohne den Fix
    schlaegt das mit 409 fehl, obwohl die Ziel-Firma leer ist."""
    with session_factory() as db:
        operator_tenant = _tenant("main", max_users=1)
        target_tenant = _tenant("firm-neu", max_users=10)
        operator = _user("op-1", "main", "super_admin")
        db.add_all([operator_tenant, target_tenant, operator])
        db.commit()

        user = create_user(_user_body("employee-1", tenant_id="firm-neu"), db=db, current_user=operator)

        assert user.tenant_id == "firm-neu"
        assert db.query(User).filter(User.tenant_id == "firm-neu").count() == 1
        # Operator-Firma bleibt unveraendert bei genau 1 User (dem Operator selbst).
        assert db.query(User).filter(User.tenant_id == "main").count() == 1


def test_super_admin_provisioning_still_respects_target_tenant_quota(session_factory):
    with session_factory() as db:
        operator_tenant = _tenant("main", max_users=10)
        target_tenant = _tenant("firm-voll", max_users=1)
        operator = _user("op-1", "main", "super_admin")
        existing = _user("existing-1", "firm-voll", "advisor")
        db.add_all([operator_tenant, target_tenant, operator, existing])
        db.commit()

        with pytest.raises(HTTPException) as exc:
            create_user(_user_body("employee-1", tenant_id="firm-voll"), db=db, current_user=operator)
        assert exc.value.status_code == 409


def test_regular_admin_cannot_use_tenant_id_to_target_other_tenant(session_factory):
    """Kein Privilege-Escalation-Pfad: ein regulaerer admin (nicht super_admin)
    darf tenant_id NICHT nutzen, um gegen eine fremde Firma zu pruefen/anzulegen
    -- das Feld muss fuer ihn wirkungslos bleiben (unveraendertes Verhalten:
    immer die eigene Firma)."""
    with session_factory() as db:
        own_tenant = _tenant("firm-own", max_users=10)
        other_tenant = _tenant("firm-other", max_users=10)
        admin = _user("admin-1", "firm-own", "admin")
        db.add_all([own_tenant, other_tenant, admin])
        db.commit()

        user = create_user(_user_body("employee-1", tenant_id="firm-other"), db=db, current_user=admin)

        assert user.tenant_id == "firm-own", "tenant_id-Feld darf fuer regulaere admins wirkungslos sein"


def test_invite_user_has_identical_cross_tenant_fix(session_factory):
    with session_factory() as db:
        operator_tenant = _tenant("main", max_users=1)
        target_tenant = _tenant("firm-neu-2", max_users=10)
        operator = _user("op-1", "main", "super_admin")
        db.add_all([operator_tenant, target_tenant, operator])
        db.commit()

        invited = invite_user(_invite_body("invitee-1", tenant_id="firm-neu-2"), _FakeRequest(), db=db, current_user=operator)

        stored = db.query(User).filter(User.id == invited.user_id).one()
        assert stored.tenant_id == "firm-neu-2"


def test_invite_user_regular_admin_tenant_id_ignored(session_factory):
    with session_factory() as db:
        own_tenant = _tenant("firm-own-2", max_users=10)
        other_tenant = _tenant("firm-other-2", max_users=10)
        admin = _user("admin-1", "firm-own-2", "admin")
        db.add_all([own_tenant, other_tenant, admin])
        db.commit()

        invited = invite_user(_invite_body("invitee-1", tenant_id="firm-other-2"), _FakeRequest(), db=db, current_user=admin)

        stored = db.query(User).filter(User.id == invited.user_id).one()
        assert stored.tenant_id == "firm-own-2"
