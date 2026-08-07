"""E1 (External-Access-Rollout): neue Mandate erben tenant_id vom Parent-Client
(Fallback: Tenant des anlegenden Users). Vorbedingung fuer NOT-NULL + Entfernen
der 'OR tenant_id IS NULL'-Klausel.
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base  # noqa: E402
from main import app  # noqa: E402,F401  (registriert alle Models)
from models.users import User  # noqa: E402
from models.clients import Client  # noqa: E402
from routers.mandates import create_mandate  # noqa: E402
from schemas.mandates import MandateCreate  # noqa: E402


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


class _FakeClient:
    def __init__(self, host="127.0.0.1"):
        self.host = host


class _FakeRequest:
    def __init__(self, host="127.0.0.1"):
        self.headers = {}
        self.client = _FakeClient(host)


@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'mandate_tenant.db'}",
        connect_args={"check_same_thread": False},
    )
    sf = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield sf
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


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


def test_mandate_inherits_tenant_from_client(session_factory):
    with session_factory() as db:
        adv = _user("adv-a", tenant_id="firm-A")
        db.add_all([adv, _client("c-a", advisor_id="adv-a", tenant_id="firm-A")])
        db.commit()
        m = create_mandate(
            client_id="c-a", body=MandateCreate(mandate_number="M-001"),
            request=_FakeRequest(), db=db, current_user=adv,
        )
        assert m.tenant_id == "firm-A"


def test_mandate_falls_back_to_user_tenant(session_factory):
    # Client ohne tenant_id (Legacy) -> Mandat erbt Tenant des Users.
    with session_factory() as db:
        adv = _user("adv-b", tenant_id="firm-B")
        db.add_all([adv, _client("c-b", advisor_id="adv-b", tenant_id=None)])
        db.commit()
        m = create_mandate(
            client_id="c-b", body=MandateCreate(mandate_number="M-002"),
            request=_FakeRequest(), db=db, current_user=adv,
        )
        assert m.tenant_id == "firm-B"
