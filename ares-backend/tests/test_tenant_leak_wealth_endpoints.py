"""E1 (External-Access-Rollout): Cross-Tenant-Leak-Abdeckung fuer die
datenfuehrenden Wealth-Endpoints (Cashflows, Vermoegenspositionen, Ziele,
Wealth-Inflows).

Ein tenant-gebundener Admin (role='admin', tenant_id='firm-A') darf NICHT auf
Client-/Mandats-gebundene Daten eines fremden Tenants ('firm-B') zugreifen —
der Ownership-/Tenant-Guard muss 404 werfen. Ergaenzt
tests/test_tenant_endpoint_leak_regression.py um die Wealth-Ebene.
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
from main import app  # noqa: E402,F401  (registriert ALLE Models + FK-Ziele)
from models.users import User  # noqa: E402
from models.clients import Client  # noqa: E402
from models.mandates import Mandate  # noqa: E402

from routers.wealth import (  # noqa: E402
    list_wealth_positions,
    list_cashflows,
    list_goals,
    list_wealth_inflows,
)


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'leak_wealth.db'}",
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
        id=uid, username=uid, password_hash="h", full_name=uid,
        role=role, is_active=1, tenant_id=tenant_id,
        created_at=_now(), updated_at=_now(),
    )


def _client(cid, advisor_id, tenant_id):
    return Client(
        id=cid, client_number=cid, first_name=cid, last_name="Test",
        advisor_id=advisor_id, tenant_id=tenant_id,
        household_type="Einzelperson", client_classification="Privatkunde",
        country_of_residence="CH", language="DE",
        created_at=_now(), updated_at=_now(),
    )


def _mandate(mid, client_id, tenant_id):
    now = _now()
    return Mandate(
        id=mid, mandate_number=mid, client_id=client_id, tenant_id=tenant_id,
        mandate_type="Anlageberatung", status="Aktiv",
        base_currency="CHF", advisory_language="DE",
        opened_at=now, created_at=now, updated_at=now,
    )


def _seed(db):
    """Firma-A-Admin + Firma-B-Client/Mandat (fremder Tenant)."""
    admin_a = _user("admin-a", tenant_id="firm-A", role="admin")
    advisor_b = _user("adv-b", tenant_id="firm-B", role="advisor")
    client_b = _client("c-b", advisor_id="adv-b", tenant_id="firm-B")
    mandate_b = _mandate("m-b", client_id="c-b", tenant_id="firm-B")
    db.add_all([admin_a, advisor_b, client_b, mandate_b])
    db.commit()
    return admin_a


def test_wealth_positions_fremder_tenant_404(session_factory):
    with session_factory() as db:
        admin_a = _seed(db)
        with pytest.raises(HTTPException) as exc:
            list_wealth_positions(client_id="c-b", db=db, current_user=admin_a)
        assert exc.value.status_code == 404, "LEAK: fremde Vermoegenspositionen sichtbar"


def test_cashflows_fremder_tenant_404(session_factory):
    with session_factory() as db:
        admin_a = _seed(db)
        with pytest.raises(HTTPException) as exc:
            list_cashflows(client_id="c-b", db=db, current_user=admin_a)
        assert exc.value.status_code == 404, "LEAK: fremde Cashflows sichtbar"


def test_goals_fremder_tenant_404(session_factory):
    with session_factory() as db:
        admin_a = _seed(db)
        with pytest.raises(HTTPException) as exc:
            list_goals(mandate_id="m-b", db=db, current_user=admin_a)
        assert exc.value.status_code == 404, "LEAK: fremde Ziele sichtbar"


def test_wealth_inflows_fremder_tenant_404(session_factory):
    with session_factory() as db:
        admin_a = _seed(db)
        with pytest.raises(HTTPException) as exc:
            list_wealth_inflows(client_id="c-b", db=db, current_user=admin_a)
        assert exc.value.status_code == 404, "LEAK: fremde Wealth-Inflows sichtbar"
