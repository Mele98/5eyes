"""E1: User-Verwaltung ist mandantengetrennt.

- Firmen-Admin (firm-A) sieht via list_users NUR eigene User (nicht firm-B).
- super_admin (Operator) sieht alle.
- Firmen-Admin kann fremde (firm-B) User NICHT aendern (404).
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
from main import app  # noqa: F401
from models.users import User
from routers.auth import list_users, update_user
from schemas.users import UserUpdate


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'usc.db'}", connect_args={"check_same_thread": False})
    sf = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield sf
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _u(uid, role, tid):
    return User(id=uid, username=uid, password_hash="h", full_name=uid, role=role,
                is_active=1, tenant_id=tid, created_at=_now(), updated_at=_now())


def _seed(db):
    db.add_all([
        _u("admin-a", "admin", "firm-A"), _u("a1", "advisor", "firm-A"),
        _u("admin-b", "admin", "firm-B"), _u("b1", "advisor", "firm-B"),
        _u("op", "super_admin", "main"),
    ])
    db.commit()


def test_admin_sees_only_own_tenant_users(session_factory):
    with session_factory() as db:
        _seed(db)
        ids = {u.id for u in list_users(db=db, current_user=db.get(User, "admin-a"))}
        assert "admin-a" in ids and "a1" in ids
        assert "admin-b" not in ids and "b1" not in ids, "LEAK: fremde Tenant-User sichtbar"


def test_super_admin_sees_all_users(session_factory):
    with session_factory() as db:
        _seed(db)
        ids = {u.id for u in list_users(db=db, current_user=db.get(User, "op"))}
        assert {"admin-a", "a1", "admin-b", "b1", "op"}.issubset(ids)


def test_admin_cannot_update_foreign_user(session_factory):
    with session_factory() as db:
        _seed(db)
        with pytest.raises(HTTPException) as exc:
            update_user("b1", UserUpdate(full_name="Hacked"), db=db, current_user=db.get(User, "admin-a"))
        assert exc.value.status_code == 404, "LEAK: fremder Tenant-User aenderbar"


def test_admin_can_update_own_tenant_user(session_factory):
    with session_factory() as db:
        _seed(db)
        out = update_user("a1", UserUpdate(full_name="Neuer Name"), db=db, current_user=db.get(User, "admin-a"))
        assert out.full_name == "Neuer Name"
