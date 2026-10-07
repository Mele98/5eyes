"""KYC-01 (Audit-Finding, 2026-10-07): GwG Art. 3-6 / FINMA-RS 2016/7
Sorgfaltspflichten -- das Datenmodell hatte bislang KEINE Felder fuer
PEP-Status, wirtschaftliche Berechtigung, Herkunft des Vermoegens,
ID-Dokument-Verifikation oder FATCA/CRS-Steuerdomizil.

Deckt ab:
1. Due-Diligence-Upsert: GET 404 solange keine Zeile existiert, PUT legt
   sie beim ersten Aufruf an (CREATE), aktualisiert sie beim zweiten
   (UPDATE) -- genau eine Zeile pro Kunde (1:1, kein zweiter INSERT).
2. Validator: beneficial_owner_name ist Pflicht, wenn
   acting_for_own_account=False (GwG Art. 4) -- positiv + negativ.
3. Steuer-Ansaessigkeiten (FATCA/CRS): mehrere Laender pro Kunde,
   is_primary-Exklusivitaet (wie ClientNationality).
4. Tenant-Isolation: ein Admin aus Tenant B bekommt fuer einen Client
   aus Tenant A 404 -- weder die Due-Diligence-Zeile noch irgendein
   Datenfragment wird geleakt.
5. Erasure (DSG Art. 32): client_due_diligence/client_tax_residencies
   werden bei services/client_erasure.py::erase_client_personal_data
   redigiert (Freitext-PII genullt), die Nicht-PII-Flags/country_code
   bleiben erhalten.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base
from models import (  # noqa: F401 -- registers all mappers for Base.metadata.create_all
    allocation,
    client_login,
    clients,
    mandates,
    profiling,
    protocol_bausteine,
    refresh_token,
    review,
    snapshots,
    tenant,
    users,
    wealth,
)
from models.clients import Client, ClientDueDiligence, ClientTaxResidency
from models.users import User
from routers.clients import (
    get_due_diligence,
    upsert_due_diligence,
    list_tax_residencies,
    add_tax_residency,
)
from schemas.clients import (
    ClientDueDiligenceUpdate,
    ClientTaxResidencyCreate,
)
from services.client_erasure import erase_client_personal_data

NOW = "2026-10-07T09:00:00.000Z"


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'client_due_diligence.db'}",
        connect_args={"check_same_thread": False},
    )
    sf = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield sf
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _advisor(user_id: str, *, tenant_id: str | None = None) -> User:
    return User(
        id=user_id, username=user_id, password_hash="x", full_name="Advisor",
        role="advisor", is_active=1, tenant_id=tenant_id,
        created_at=NOW, updated_at=NOW,
    )


def _admin(user_id: str, *, tenant_id: str | None = None) -> User:
    return User(
        id=user_id, username=user_id, password_hash="x", full_name="Admin",
        role="admin", is_active=1, tenant_id=tenant_id,
        created_at=NOW, updated_at=NOW,
    )


def _seed_client(session, *, client_id: str, advisor_id: str, tenant_id: str | None = None) -> Client:
    client = Client(
        id=client_id, client_number=f"{client_id}-NR", first_name="Hans", last_name="Muster",
        country_of_residence="CH", language="DE", household_type="Einzelperson",
        client_classification="Privatkunde", is_professional_opt_out=0,
        is_qualified_investor=0, advisor_id=advisor_id, tenant_id=tenant_id,
        created_at=NOW, updated_at=NOW,
    )
    session.add(client)
    session.commit()
    return client


# ---------------------------------------------------------------------------
# 1. Due-Diligence upsert semantics
# ---------------------------------------------------------------------------

def test_get_due_diligence_404_when_none_exists(session_factory):
    with session_factory() as db:
        advisor = _advisor("advisor-dd1")
        db.add(advisor)
        _seed_client(db, client_id="client-dd1", advisor_id=advisor.id)

        with pytest.raises(HTTPException) as exc:
            get_due_diligence("client-dd1", db=db, current_user=advisor)
        assert exc.value.status_code == 404


def test_upsert_due_diligence_creates_then_updates_same_row(session_factory):
    with session_factory() as db:
        advisor = _advisor("advisor-dd2")
        db.add(advisor)
        _seed_client(db, client_id="client-dd2", advisor_id=advisor.id)

        created = upsert_due_diligence(
            "client-dd2",
            ClientDueDiligenceUpdate(
                pep_status=False,
                source_of_wealth="Erwerbseinkommen",
                fatca_crs_self_certified=True,
                data_classification="synthetic",
            ),
            db=db, current_user=advisor,
        )
        assert created.source_of_wealth == "Erwerbseinkommen"
        assert created.fatca_crs_self_certified == 1
        first_id = created.id

    with session_factory() as db:
        # Nur genau EINE Zeile fuer diesen Client -- 1:1, kein zweiter INSERT.
        assert db.query(ClientDueDiligence).filter(
            ClientDueDiligence.client_id == "client-dd2"
        ).count() == 1

        updated = upsert_due_diligence(
            "client-dd2",
            ClientDueDiligenceUpdate(
                pep_status=True,
                pep_details="Mitglied Kantonsparlament 2018-2022",
                source_of_wealth="Erbschaft",
                fatca_crs_self_certified=True,
                data_classification="synthetic",
            ),
            db=db, current_user=advisor,
        )
        assert updated.id == first_id
        assert updated.pep_status == 1
        assert updated.pep_details == "Mitglied Kantonsparlament 2018-2022"
        assert updated.source_of_wealth == "Erbschaft"

    with session_factory() as db:
        assert db.query(ClientDueDiligence).filter(
            ClientDueDiligence.client_id == "client-dd2"
        ).count() == 1
        row = db.query(ClientDueDiligence).filter(
            ClientDueDiligence.client_id == "client-dd2"
        ).one()
        assert row.source_of_wealth == "Erbschaft"


def test_get_due_diligence_returns_record_after_upsert(session_factory):
    with session_factory() as db:
        advisor = _advisor("advisor-dd3")
        db.add(advisor)
        _seed_client(db, client_id="client-dd3", advisor_id=advisor.id)
        upsert_due_diligence(
            "client-dd3",
            ClientDueDiligenceUpdate(source_of_wealth="Unternehmensverkauf", data_classification="synthetic"),
            db=db, current_user=advisor,
        )

    with session_factory() as db:
        result = get_due_diligence("client-dd3", db=db, current_user=advisor)
        assert result.source_of_wealth == "Unternehmensverkauf"


# ---------------------------------------------------------------------------
# 2. beneficial_owner_name required when acting_for_own_account=False
# ---------------------------------------------------------------------------

def test_beneficial_owner_name_required_when_not_own_account():
    with pytest.raises(ValidationError) as exc:
        ClientDueDiligenceUpdate(
            acting_for_own_account=False,
            beneficial_owner_name=None,
            data_classification="synthetic",
        )
    assert "beneficial_owner_name" in str(exc.value)


def test_beneficial_owner_name_blank_string_also_rejected():
    with pytest.raises(ValidationError):
        ClientDueDiligenceUpdate(
            acting_for_own_account=False,
            beneficial_owner_name="   ",
            data_classification="synthetic",
        )


def test_beneficial_owner_name_present_passes_validation():
    body = ClientDueDiligenceUpdate(
        acting_for_own_account=False,
        beneficial_owner_name="Erika Muster",
        data_classification="synthetic",
    )
    assert body.beneficial_owner_name == "Erika Muster"


def test_own_account_true_does_not_require_beneficial_owner():
    body = ClientDueDiligenceUpdate(acting_for_own_account=True, data_classification="synthetic")
    assert body.beneficial_owner_name is None


def test_pep_details_optional_even_when_pep_status_true():
    # Design-Vorgabe: pep_details ist NICHT Pflicht bei pep_status=1 (kann
    # spaeter ergaenzt werden) -- anders als beneficial_owner_name.
    body = ClientDueDiligenceUpdate(pep_status=True, pep_details=None, data_classification="synthetic")
    assert body.pep_status is True
    assert body.pep_details is None


# ---------------------------------------------------------------------------
# 3. Tax residencies (FATCA/CRS): multiple countries + is_primary exclusivity
# ---------------------------------------------------------------------------

def test_tax_residency_create_and_list_multiple_countries(session_factory):
    with session_factory() as db:
        advisor = _advisor("advisor-tr1")
        db.add(advisor)
        _seed_client(db, client_id="client-tr1", advisor_id=advisor.id)

        ch = add_tax_residency(
            "client-tr1",
            ClientTaxResidencyCreate(country_code="CH", tax_id_number="756.1234.5678.90", is_primary=True, data_classification="synthetic"),
            db=db, current_user=advisor,
        )
        us = add_tax_residency(
            "client-tr1",
            ClientTaxResidencyCreate(country_code="US", tax_id_number="123-45-6789", is_primary=False, data_classification="synthetic"),
            db=db, current_user=advisor,
        )
        assert ch.country_code == "CH"
        assert us.country_code == "US"

    with session_factory() as db:
        rows = list_tax_residencies("client-tr1", db=db, current_user=advisor)
        assert {r.country_code for r in rows} == {"CH", "US"}
        assert sum(1 for r in rows if r.is_primary) == 1


def test_tax_residency_is_primary_exclusivity_switches_when_new_primary_added(session_factory):
    with session_factory() as db:
        advisor = _advisor("advisor-tr2")
        db.add(advisor)
        _seed_client(db, client_id="client-tr2", advisor_id=advisor.id)

        add_tax_residency(
            "client-tr2",
            ClientTaxResidencyCreate(country_code="CH", is_primary=True, data_classification="synthetic"),
            db=db, current_user=advisor,
        )
        add_tax_residency(
            "client-tr2",
            ClientTaxResidencyCreate(country_code="DE", is_primary=True, data_classification="synthetic"),
            db=db, current_user=advisor,
        )

    with session_factory() as db:
        rows = db.query(ClientTaxResidency).filter(ClientTaxResidency.client_id == "client-tr2").all()
        primaries = [r for r in rows if r.is_primary]
        assert len(primaries) == 1
        assert primaries[0].country_code == "DE"


# ---------------------------------------------------------------------------
# 4. Tenant isolation
# ---------------------------------------------------------------------------

def test_due_diligence_404_for_client_in_other_tenant(session_factory, monkeypatch):
    from config import settings
    # Non-strict (default) tenant mode: a set, differing tenant_id on both
    # sides is enough to prove isolation without touching global settings
    # beyond what the fixture already assumes.
    with session_factory() as db:
        advisor_a = _advisor("advisor-tenA", tenant_id="tenant-a")
        db.add(advisor_a)
        _seed_client(db, client_id="client-tenA", advisor_id=advisor_a.id, tenant_id="tenant-a")
        upsert_due_diligence(
            "client-tenA",
            ClientDueDiligenceUpdate(source_of_wealth="Erbschaft", data_classification="synthetic"),
            db=db, current_user=advisor_a,
        )

    with session_factory() as db:
        admin_b = _admin("admin-tenB", tenant_id="tenant-b")
        db.add(admin_b)
        db.commit()

        with pytest.raises(HTTPException) as exc:
            get_due_diligence("client-tenA", db=db, current_user=admin_b)
        assert exc.value.status_code == 404

        with pytest.raises(HTTPException) as exc2:
            list_tax_residencies("client-tenA", db=db, current_user=admin_b)
        assert exc2.value.status_code == 404


def test_due_diligence_visible_to_admin_in_same_tenant(session_factory):
    with session_factory() as db:
        advisor_a = _advisor("advisor-tenA2", tenant_id="tenant-a")
        db.add(advisor_a)
        _seed_client(db, client_id="client-tenA2", advisor_id=advisor_a.id, tenant_id="tenant-a")
        upsert_due_diligence(
            "client-tenA2",
            ClientDueDiligenceUpdate(source_of_wealth="Erbschaft", data_classification="synthetic"),
            db=db, current_user=advisor_a,
        )

    with session_factory() as db:
        admin_a = _admin("admin-tenA2", tenant_id="tenant-a")
        db.add(admin_a)
        db.commit()
        result = get_due_diligence("client-tenA2", db=db, current_user=admin_a)
        assert result.source_of_wealth == "Erbschaft"


# ---------------------------------------------------------------------------
# 5. Erasure redacts due-diligence + tax-residency PII fields
# ---------------------------------------------------------------------------

def _seed_erasure_fixture(session) -> str:
    client_id = "client-dd-erase1"
    advisor = User(
        id="admin-dderase", username="admin-dderase", password_hash="h",
        full_name="Admin DDErase", role="admin", is_active=1,
        created_at=NOW, updated_at=NOW,
    )
    session.add(advisor)
    client = Client(
        id=client_id, client_number="C-DDERASE-1", first_name="Hans", last_name="Muster",
        country_of_residence="CH", language="DE", household_type="Einzelperson",
        client_classification="Privatkunde", is_professional_opt_out=0,
        is_qualified_investor=0, advisor_id=advisor.id,
        created_at=NOW, updated_at=NOW,
    )
    session.add(client)
    session.add(ClientDueDiligence(
        id="dd-erase1", client_id=client_id,
        pep_status=1, pep_details="Mitglied Kantonsparlament 2018-2022",
        acting_for_own_account=0, beneficial_owner_name="Erika Muster",
        source_of_wealth="Erbschaft von Vater Muster",
        id_document_type="Pass", id_document_number="X1234567",
        id_document_issuing_country="CH", id_document_expiry="2030-01-01",
        fatca_crs_self_certified=1,
        created_at=NOW, updated_at=NOW,
    ))
    session.add(ClientTaxResidency(
        id="tr-erase1", client_id=client_id, country_code="CH",
        tax_id_number="756.1234.5678.90", is_primary=1, created_at=NOW,
    ))
    session.commit()
    return client_id


def test_erasure_redacts_due_diligence_and_tax_residency_pii(session_factory):
    with session_factory() as db:
        client_id = _seed_erasure_fixture(db)

    with session_factory() as db:
        result = erase_client_personal_data(
            db, client_id,
            reason="Kunde hat schriftlich sein Recht auf Loeschung nach DSG Art. 32 geltend gemacht.",
        )
        db.commit()
        assert result["redacted"]["client_due_diligence"] == 1
        assert result["redacted"]["client_tax_residencies"] == 1

    with session_factory() as db:
        dd = db.execute(
            text(
                "SELECT pep_details, beneficial_owner_name, source_of_wealth, "
                "id_document_number, id_document_type, pep_status, "
                "acting_for_own_account, fatca_crs_self_certified "
                "FROM client_due_diligence WHERE client_id = :id"
            ),
            {"id": client_id},
        ).one()
        # Freitext-PII genullt.
        assert dd.pep_details is None
        assert dd.beneficial_owner_name is None
        assert dd.source_of_wealth is None
        assert dd.id_document_number is None
        # Nicht-Freitext-Flags + id_document_type bleiben erhalten (kein
        # Re-Identifikationsrisiko, siehe services/client_erasure.py).
        assert dd.id_document_type == "Pass"
        assert dd.pep_status == 1
        assert dd.acting_for_own_account == 0
        assert dd.fatca_crs_self_certified == 1

        tr = db.execute(
            text("SELECT tax_id_number, country_code, is_primary FROM client_tax_residencies WHERE client_id = :id"),
            {"id": client_id},
        ).one()
        assert tr.tax_id_number is None
        assert tr.country_code == "CH"
        assert tr.is_primary == 1
