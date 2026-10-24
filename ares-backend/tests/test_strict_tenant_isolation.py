"""E1: strict_tenant_isolation — NULL-tenant_id-Rows sind im Strict-Modus
unsichtbar (physische Trennung), im Default-Modus sichtbar (BC)."""
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
from main import app  # noqa: F401  (registriert alle Models)
from models.users import User
from models.clients import Client
from routers.clients import list_clients
from config import settings


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'strict.db'}",
        connect_args={"check_same_thread": False},
    )
    sf = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield sf
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _client(cid, tenant_id):
    return Client(
        id=cid, client_number=cid, first_name=cid, last_name="T",
        advisor_id="admin-a", tenant_id=tenant_id, household_type="Einzelperson",
        client_classification="Privatkunde", country_of_residence="CH", language="DE",
        created_at=_now(), updated_at=_now(),
    )


def _seed(db):
    admin = User(id="admin-a", username="admin-a", password_hash="h", full_name="A",
                 role="admin", is_active=1, tenant_id="firm-A",
                 created_at=_now(), updated_at=_now())
    db.add_all([admin, _client("c-a", "firm-A"), _client("c-null", None), _client("c-b", "firm-B")])
    db.commit()
    return admin


def test_bc_mode_sees_null_tenant(session_factory, monkeypatch):
    monkeypatch.setattr(settings, "strict_tenant_isolation", False)
    with session_factory() as db:
        admin = _seed(db)
        ids = {c.id for c in list_clients(search=None, advisor_id=None, db=db, current_user=admin)}
        assert "c-a" in ids
        assert "c-null" in ids          # BC: NULL gilt als eigener Tenant
        assert "c-b" not in ids


def test_strict_mode_hides_null_tenant(session_factory, monkeypatch):
    monkeypatch.setattr(settings, "strict_tenant_isolation", True)
    with session_factory() as db:
        admin = _seed(db)
        ids = {c.id for c in list_clients(search=None, advisor_id=None, db=db, current_user=admin)}
        assert "c-a" in ids
        assert "c-null" not in ids, "STRICT: NULL-tenant_id muss unsichtbar sein"
        assert "c-b" not in ids
