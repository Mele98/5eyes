"""E1: Mitarbeiter-Onboarding — erzwungener Passwortwechsel beim ersten Login.

- vom Admin angelegter User: must_change_password=1
- aendert der User SELBST das Passwort -> Flag 0 (erledigt)
- Admin-Reset eines fremden Users -> Flag 1 (muss erneut geaendert werden)
- Nicht-Admin darf fremdes Passwort NICHT aendern (403)
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
from routers.auth import create_user, reset_user_password
from schemas.users import UserCreate, UserPasswordReset


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'onb.db'}", connect_args={"check_same_thread": False})
    sf = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield sf
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _admin(uid, tid="firm-A"):
    return User(id=uid, username=uid, password_hash="h", full_name=uid, role="admin",
                is_active=1, tenant_id=tid, created_at=_now(), updated_at=_now())


def test_new_employee_must_change_password(session_factory):
    with session_factory() as db:
        db.add(_admin("admin-a")); db.commit()
        emp = create_user(UserCreate(username="emp", password="initPW12345", full_name="Emp", role="advisor"),
                          db=db, current_user=db.get(User, "admin-a"))
        assert emp.must_change_password == 1


def test_self_change_clears_flag(session_factory):
    with session_factory() as db:
        db.add(_admin("admin-a")); db.commit()
        emp = create_user(UserCreate(username="emp", password="initPW12345", full_name="Emp", role="advisor"),
                          db=db, current_user=db.get(User, "admin-a"))
        out = reset_user_password(emp.id, UserPasswordReset(new_password="myNewPW123456"),
                                  db=db, current_user=db.get(User, emp.id))
        assert out.must_change_password == 0


def test_admin_reset_sets_flag(session_factory):
    with session_factory() as db:
        db.add(_admin("admin-a")); db.commit()
        emp = create_user(UserCreate(username="emp", password="initPW12345", full_name="Emp", role="advisor"),
                          db=db, current_user=db.get(User, "admin-a"))
        # erst selbst klaeren, dann Admin-Reset -> Flag wieder 1
        reset_user_password(emp.id, UserPasswordReset(new_password="myNewPW123456"),
                            db=db, current_user=db.get(User, emp.id))
        out = reset_user_password(emp.id, UserPasswordReset(new_password="adminSet123456"),
                                  db=db, current_user=db.get(User, "admin-a"))
        assert out.must_change_password == 1


def test_non_admin_cannot_change_other(session_factory):
    with session_factory() as db:
        db.add(_admin("admin-a")); db.commit()
        e1 = create_user(UserCreate(username="e1", password="initPW12345", full_name="E1", role="advisor"),
                         db=db, current_user=db.get(User, "admin-a"))
        e2 = create_user(UserCreate(username="e2", password="initPW12345", full_name="E2", role="advisor"),
                         db=db, current_user=db.get(User, "admin-a"))
        with pytest.raises(HTTPException) as exc:
            reset_user_password(e2.id, UserPasswordReset(new_password="hackPW1234567"),
                                db=db, current_user=db.get(User, e1.id))
        assert exc.value.status_code == 403
