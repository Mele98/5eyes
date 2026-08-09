"""FINIG-Gate fuer diskretionaere Vermoegensverwaltung (2026-08-09).

Seit FINIG braucht eine Firma eine FINMA-Bewilligung/AO-Anschluss, um
diskretionaere Vermoegensverwaltung anzubieten -- reine Anlageberatung
(mandate_type="Anlageberatung") braucht nur den leichteren Beraterregister-
Eintrag. Diese Tests sperren: (1) neue Tenants starten OHNE die
Freischaltung (Opt-in, kein Opt-out), (2) Bestandstenants werden durch das
Anlegen der Spalte NICHT rueckwirkend blockiert (DB-Backfill auf 1), (3) das
Backend-Enforcement in create_mandate/update_mandate greift unabhaengig von
der (rein optischen) Frontend-Gate-Logik.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base
from models.clients import Client
from models.mandates import Mandate
from models.tenant import Tenant
from models.users import User
# Mehrere Modelle referenzieren einander per String-Relationship (z.B.
# Mandate->RiskAssessment, Client->WealthPosition) -- alle muessen vor der
# ersten Mapper-Konfiguration importiert sein, sonst schlaegt jede erste ORM-
# Instanziierung mit InvalidRequestError fehl. Identische Modul-Liste wie
# tests/test_alembic_baseline_migration.py, das aus demselben Grund alle
# Model-Module explizit importiert.
import models.allocation  # noqa: F401
import models.profiling  # noqa: F401
import models.review  # noqa: F401
import models.wealth  # noqa: F401
from routers.mandates import create_mandate, update_mandate
from schemas.mandates import MandateCreate, MandateUpdate
from services.tenant_licensing import enforce_discretionary_management_license


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class _FakeRequest:
    def __init__(self, host="127.0.0.1"):
        self.headers = {}
        self.client = type("C", (), {"host": host})()


@pytest.fixture()
def session_factory(tmp_path):
    db_path = tmp_path / "test_finig_gate.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    sf = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield sf
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _seed_advisor_and_client(session, tenant_id: str, advisor_id="advisor-1", client_id="client-1") -> User:
    advisor = User(
        id=advisor_id, username=advisor_id, password_hash="hash", full_name="Advisor",
        role="advisor", is_active=1, tenant_id=tenant_id,
        created_at=_now(), updated_at=_now(),
    )
    session.add(advisor)
    session.add(Client(
        id=client_id, client_number="C-" + client_id, first_name="Max", last_name="Muster",
        country_of_residence="CH", language="DE", household_type="Einzelperson",
        client_classification="Privatkunde", is_professional_opt_out=0, is_qualified_investor=0,
        advisor_id=advisor_id, tenant_id=tenant_id,
        created_at=_now(), updated_at=_now(),
    ))
    session.commit()
    return advisor


def _seed_tenant(session, tenant_id: str, licensed: int) -> None:
    session.add(Tenant(
        id=tenant_id, display_name="Test Firma AG", slug=tenant_id,
        hosting_tier="tier2", license_status="active",
        discretionary_management_licensed=licensed,
        is_active=1, created_at=_now(), updated_at=_now(),
    ))
    session.commit()


# ===========================================================================
# services/tenant_licensing.py -- reine Logik-Tests
# ===========================================================================


def test_advisory_mandate_type_never_blocked_regardless_of_license():
    unlicensed = Tenant(discretionary_management_licensed=0)
    enforce_discretionary_management_license(unlicensed, "Anlageberatung")
    enforce_discretionary_management_license(unlicensed, "Finanzplanung")
    enforce_discretionary_management_license(unlicensed, "Reporting only")
    enforce_discretionary_management_license(None, "Vermögensverwaltung")  # kein Tenant-Kontext -> fail-open


def test_discretionary_mandate_type_blocked_when_not_licensed():
    unlicensed = Tenant(discretionary_management_licensed=0)
    with pytest.raises(HTTPException) as exc:
        enforce_discretionary_management_license(unlicensed, "Vermögensverwaltung")
    assert exc.value.status_code == 403


def test_discretionary_mandate_type_allowed_when_licensed():
    licensed = Tenant(discretionary_management_licensed=1)
    enforce_discretionary_management_license(licensed, "Vermögensverwaltung")  # kein Raise


# ===========================================================================
# routers/mandates.py -- create_mandate/update_mandate Enforcement
# ===========================================================================


def test_create_mandate_403_for_unlicensed_tenant(session_factory):
    with session_factory() as session:
        _seed_tenant(session, "tenant-unlicensed", licensed=0)
        advisor = _seed_advisor_and_client(session, "tenant-unlicensed")

        with pytest.raises(HTTPException) as exc:
            create_mandate(
                client_id="client-1",
                body=MandateCreate(mandate_number="M-1", mandate_type="Vermögensverwaltung"),
                request=_FakeRequest(), db=session, current_user=advisor,
            )
        assert exc.value.status_code == 403


def test_create_mandate_allowed_for_licensed_tenant(session_factory):
    with session_factory() as session:
        _seed_tenant(session, "tenant-licensed", licensed=1)
        advisor = _seed_advisor_and_client(session, "tenant-licensed")

        mandate = create_mandate(
            client_id="client-1",
            body=MandateCreate(mandate_number="M-1", mandate_type="Vermögensverwaltung"),
            request=_FakeRequest(), db=session, current_user=advisor,
        )
        assert mandate.mandate_type == "Vermögensverwaltung"


def test_create_mandate_advisory_type_always_allowed_even_unlicensed(session_factory):
    with session_factory() as session:
        _seed_tenant(session, "tenant-unlicensed-2", licensed=0)
        advisor = _seed_advisor_and_client(session, "tenant-unlicensed-2")

        mandate = create_mandate(
            client_id="client-1",
            body=MandateCreate(mandate_number="M-1", mandate_type="Anlageberatung"),
            request=_FakeRequest(), db=session, current_user=advisor,
        )
        assert mandate.mandate_type == "Anlageberatung"


def test_update_mandate_to_discretionary_blocked_when_not_licensed(session_factory):
    with session_factory() as session:
        _seed_tenant(session, "tenant-unlicensed-3", licensed=0)
        advisor = _seed_advisor_and_client(session, "tenant-unlicensed-3")
        mandate = create_mandate(
            client_id="client-1",
            body=MandateCreate(mandate_number="M-1", mandate_type="Anlageberatung"),
            request=_FakeRequest(), db=session, current_user=advisor,
        )

        with pytest.raises(HTTPException) as exc:
            update_mandate(
                mandate_id=mandate.id,
                body=MandateUpdate(mandate_type="Vermögensverwaltung"),
                request=_FakeRequest(), db=session, current_user=advisor,
            )
        assert exc.value.status_code == 403
        # Unveraendert geblieben -- kein Teil-Update trotz Fehlschlag.
        assert mandate.mandate_type == "Anlageberatung"


def test_update_mandate_unrelated_field_unaffected_by_gate(session_factory):
    """Ein Update, das mandate_type NICHT anfasst, darf durch die Lizenz-
    Pruefung nicht blockiert werden -- selbst wenn das Mandat bereits
    Vermögensverwaltung ist und die Firma (nachtraeglich) unlizenziert waere."""
    with session_factory() as session:
        _seed_tenant(session, "tenant-4", licensed=1)
        advisor = _seed_advisor_and_client(session, "tenant-4")
        mandate = create_mandate(
            client_id="client-1",
            body=MandateCreate(mandate_number="M-1", mandate_type="Vermögensverwaltung"),
            request=_FakeRequest(), db=session, current_user=advisor,
        )
        updated = update_mandate(
            mandate_id=mandate.id,
            body=MandateUpdate(depot_bank="Bank XY"),
            request=_FakeRequest(), db=session, current_user=advisor,
        )
        assert updated.depot_bank == "Bank XY"
        assert updated.mandate_type == "Vermögensverwaltung"


# ===========================================================================
# Backwards-Compat: ORM-Default schuetzt jeden Code-Pfad ohne explizite Angabe
# ===========================================================================


def test_tenant_orm_default_is_licensed_for_backwards_compat(session_factory):
    """SQLAlchemy-Column-Default (nicht der Pydantic-Schema-Default in
    schemas.tenants.TenantCreate) ist 1 -- das Sicherheitsnetz fuer JEDEN
    Code-Pfad, der eine Tenant-Zeile ohne explizite Angabe des Felds anlegt
    (z.B. aeltere interne Skripte). database.py::ensure_runtime_columns()
    nutzt denselben int-Default (3-Tupel-Form) fuer den SQLite-ALTER-TABLE-
    Backfill auf echten Bestands-DBs -- identischer, bereits an
    default_retrocession_reimbursement/reimbursed_to_client erprobter
    Mechanismus (siehe database.py:552-571), hier nur eine neue
    Konfigurationszeile, keine neue Logik. Nur der API-Layer
    (schemas.tenants.TenantCreate) erzwingt bewusst den strengeren
    False-Default fuer NEU angelegte Firmen."""
    with session_factory() as session:
        tenant = Tenant(
            id="tenant-orm-default", display_name="ORM Default AG", slug="orm-default",
            hosting_tier="tier1", license_status="active",
            is_active=1, created_at=_now(), updated_at=_now(),
        )
        session.add(tenant)
        session.commit()
        session.refresh(tenant)
        assert tenant.discretionary_management_licensed == 1


# ===========================================================================
# Frontend-Wiring -- Provisioning-Checkbox (Quelltext-Assertion, konsistent
# mit den uebrigen test_frontend_*-Tests)
# ===========================================================================


def test_frontend_provisioning_has_finig_checkbox_wired():
    html_path = Path(__file__).resolve().parents[2] / "5eyes-electron" / "frontend" / "5eyes_v2.html"
    html = html_path.read_text(encoding="utf-8")
    assert 'id="prov-t-vv-licensed"' in html
    start = html.index("async function provCreateTenant()")
    end = html.index("\n}", start)
    body = html[start:end]
    assert "discretionary_management_licensed:vvLicensed" in body
