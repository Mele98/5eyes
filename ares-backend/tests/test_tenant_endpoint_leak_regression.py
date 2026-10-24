"""Regressionstests fuer die 2026-06-10 gefundenen Cross-Tenant-Leaks.

Kontext: Audit der Mandanten-Trennung fand 6 Endpoints, bei denen ein
tenant-gebundener Admin (role='admin', tenant_id='firm-A') Daten eines
FREMDEN Tenants ('firm-B') lesen konnte — weil der Admin-Pfad den zentralen
Tenant-Filter uebersprang.

Diese Tests wuerden VOR dem Fix fehlschlagen (Leak) und sind danach gruen.
Sie ergaenzen tests/test_repository_tenant_scoping.py (Helper-Ebene) um die
Endpoint-Ebene.
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
import models.users  # noqa: E402,F401
import models.clients  # noqa: E402,F401
import models.client_login  # noqa: E402,F401
import models.mandates  # noqa: E402,F401
import models.tenant  # noqa: E402,F401
import models.protocol_bausteine  # noqa: E402,F401
from models.users import User  # noqa: E402
from models.clients import Client  # noqa: E402
from models.mandates import Mandate  # noqa: E402

from routers.clients import list_clients  # noqa: E402
from routers.protocol_bausteine import list_mandate_selections  # noqa: E402
from routers.system import get_shadow_comparison  # noqa: E402


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'leak_regression.db'}",
        connect_args={"check_same_thread": False},
    )
    sf = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield sf
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _user(uid: str, tenant_id: str | None, role: str = "advisor") -> User:
    return User(
        id=uid, username=uid, password_hash="h", full_name=uid,
        role=role, is_active=1, tenant_id=tenant_id,
        created_at=_now(), updated_at=_now(),
    )


def _client(cid: str, advisor_id: str, tenant_id: str | None) -> Client:
    return Client(
        id=cid, client_number=cid, first_name=cid, last_name="Test",
        advisor_id=advisor_id, tenant_id=tenant_id,
        household_type="Einzelperson", client_classification="Privatkunde",
        country_of_residence="CH", language="DE",
        created_at=_now(), updated_at=_now(),
    )


def _mandate(mid: str, client_id: str, tenant_id: str | None) -> Mandate:
    now = _now()
    return Mandate(
        id=mid, mandate_number=mid, client_id=client_id, tenant_id=tenant_id,
        mandate_type="Anlageberatung", status="Aktiv",
        base_currency="CHF", advisory_language="DE",
        opened_at=now, created_at=now, updated_at=now,
    )


def _seed_two_tenants(db):
    """Firma A (admin + Client/Mandat) und Firma B (Client/Mandat)."""
    admin_a = _user("admin-a", tenant_id="firm-A", role="admin")
    advisor_b = _user("adv-b", tenant_id="firm-B", role="advisor")
    client_a = _client("c-a", advisor_id="admin-a", tenant_id="firm-A")
    client_b = _client("c-b", advisor_id="adv-b", tenant_id="firm-B")
    mandate_b = _mandate("m-b", client_id="c-b", tenant_id="firm-B")
    db.add_all([admin_a, advisor_b, client_a, client_b, mandate_b])
    db.commit()
    return admin_a


# ---------------------------------------------------------------------------
# #1 GET /clients (list_clients) — Admin-Pfad hatte KEINEN Tenant-Filter
# ---------------------------------------------------------------------------

def test_list_clients_admin_sieht_keine_fremden_tenant_clients(session_factory):
    with session_factory() as db:
        admin_a = _seed_two_tenants(db)
        result = list_clients(search=None, advisor_id=None, db=db, current_user=admin_a)
        ids = {c.id for c in result}
        assert "c-a" in ids
        assert "c-b" not in ids, "LEAK: Firma-A-Admin sieht Client von Firma B"


def test_list_clients_admin_enumeration_via_advisor_id_geblockt(session_factory):
    """Auch gezieltes ?advisor_id=<fremder Berater> darf nichts leaken."""
    with session_factory() as db:
        admin_a = _seed_two_tenants(db)
        result = list_clients(search=None, advisor_id="adv-b", db=db, current_user=admin_a)
        assert [c.id for c in result] == [], "LEAK: Enumeration fremder Berater-Kunden moeglich"


# ---------------------------------------------------------------------------
# #4 GET /mandates/{id}/protocol-bausteine — lokaler Helper ohne Tenant-Filter
# ---------------------------------------------------------------------------

def test_protocol_bausteine_fremdes_mandat_404(session_factory):
    with session_factory() as db:
        admin_a = _seed_two_tenants(db)
        with pytest.raises(HTTPException) as exc:
            list_mandate_selections(mandate_id="m-b", db=db, current_user=admin_a)
        assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# #6 GET /admin/system/shadow-comparison/{id} — fehlender Ownership-Guard
# ---------------------------------------------------------------------------

def test_shadow_comparison_fremdes_mandat_404(session_factory):
    with session_factory() as db:
        admin_a = _seed_two_tenants(db)
        with pytest.raises(HTTPException) as exc:
            get_shadow_comparison(mandate_id="m-b", db=db, current_user=admin_a)
        assert exc.value.status_code == 404
        # Muss der OWNERSHIP-Guard sein (nicht der "keine Shadow-Daten"-404),
        # sonst wuerde der Test auch ohne Fix gruen sein.
        assert exc.value.detail == "Mandat nicht gefunden"
