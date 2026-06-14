"""E1: neue Mitarbeiter (create_user) erben den Tenant des anlegenden Admins.

Harte Firmen-Trennung: ein von Firma-A-Admin angelegter Mitarbeiter darf NIE
tenant_id=NULL bekommen (sonst tenant-uebergreifend sichtbar via 'OR IS NULL').
"""
from __future__ import annotations
import sys
import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base
from main import app  # noqa: F401  (registriert alle Models)
from models.users import User
from routers.auth import create_user
from schemas.users import UserCreate


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'user_tenant.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _admin(uid, tenant_id):
    return User(id=uid, username=uid, password_hash="h", full_name=uid, role="admin",
                is_active=1, tenant_id=tenant_id, created_at=_now(), updated_at=_now())


def test_employee_inherits_admin_tenant(session_factory):
    with session_factory() as db:
        admin = _admin("admin-a", "firm-A")
        db.add(admin)
        db.commit()
        new = create_user(
            UserCreate(username="emp1", password="pw1234567890", full_name="Mitarbeiter 1", role="advisor"),
            db=db, current_user=admin,
        )
        assert new.tenant_id == "firm-A"
        assert new.role == "advisor"


def test_two_firms_do_not_mix(session_factory):
    with session_factory() as db:
        db.add_all([_admin("admin-a", "firm-A"), _admin("admin-b", "firm-B")])
        db.commit()
        ea = create_user(UserCreate(username="ea", password="pw1234567890", full_name="EA", role="advisor"),
                         db=db, current_user=db.get(User, "admin-a"))
        eb = create_user(UserCreate(username="eb", password="pw1234567890", full_name="EB", role="advisor"),
                         db=db, current_user=db.get(User, "admin-b"))
        assert ea.tenant_id == "firm-A"
        assert eb.tenant_id == "firm-B"
