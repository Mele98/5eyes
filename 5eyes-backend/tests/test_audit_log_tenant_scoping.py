"""E1: Audit-Log ist mandantengetrennt.

Ein Firmen-Admin (firm-A) sieht NUR Audit-Eintraege zu eigenen Clients/Mandaten
plus eigene Aktionen — nicht fremde (firm-B) Eintraege und nicht fremde
System-/Operator-Aktionen. super_admin sieht alles.
"""
from __future__ import annotations
import datetime
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base
from main import app  # noqa: F401
from models.users import User
from models.clients import Client
from models.review import AuditLog
from routers.system import get_audit_log


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'auditscope.db'}", connect_args={"check_same_thread": False})
    sf = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield sf
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _client(cid, tid):
    return Client(id=cid, client_number=cid, first_name=cid, last_name="T", advisor_id="x",
                  tenant_id=tid, household_type="Einzelperson", client_classification="Privatkunde",
                  country_of_residence="CH", language="DE", created_at=_now(), updated_at=_now())


def _entry(eid, **kw):
    base = dict(id=eid, user_name="u", table_name="clients", record_id=eid, action="CREATE",
                created_at=_now())
    base.update(kw)
    return AuditLog(**base)


def _seed(db):
    db.add_all([
        User(id="admin-a", username="admin-a", password_hash="h", full_name="A", role="admin",
             is_active=1, tenant_id="firm-A", created_at=_now(), updated_at=_now()),
        User(id="op", username="op", password_hash="h", full_name="Op", role="super_admin",
             is_active=1, tenant_id="main", created_at=_now(), updated_at=_now()),
        _client("c-a", "firm-A"), _client("c-b", "firm-B"),
        _entry("e-a", client_id="c-a", user_id="someone"),          # firm-A client
        _entry("e-b", client_id="c-b", user_id="someone"),          # firm-B client (fremd)
        _entry("e-own", client_id=None, user_id="admin-a", table_name="users", action="LOGIN"),  # eigene Aktion
        _entry("e-foreign-sys", client_id=None, user_id="other-op", table_name="system", action="UPDATE"),
    ])
    db.commit()


def _ids(page):
    return {e.id for e in page.entries}


def test_admin_audit_scoped_to_own_tenant(session_factory):
    with session_factory() as db:
        _seed(db)
        page = get_audit_log(limit=50, offset=0, action=None, q=None, db=db,
                             current_user=db.get(User, "admin-a"))
        ids = _ids(page)
        assert "e-a" in ids            # eigener Client
        assert "e-own" in ids          # eigene Aktion
        assert "e-b" not in ids, "LEAK: fremder Tenant-Audit sichtbar"
        assert "e-foreign-sys" not in ids, "LEAK: fremde System-Aktion sichtbar"


def test_super_admin_sees_full_audit(session_factory):
    with session_factory() as db:
        _seed(db)
        page = get_audit_log(limit=50, offset=0, action=None, q=None, db=db,
                             current_user=db.get(User, "op"))
        ids = _ids(page)
        assert {"e-a", "e-b", "e-own", "e-foreign-sys"}.issubset(ids)
