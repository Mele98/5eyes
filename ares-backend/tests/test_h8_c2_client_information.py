"""H8 C-2 (Compliance-Audit 2026-11-07, Dok. 104, Luecke 2): Kundeninformation
nach Art. 8/9 FIDLEG.

Rechtliche Angaben der Firma ohne Vorbelegung (auditiert), Kundeninformations-
PDF aus diesen Daten, Abgabenachweis (Zeitpunkt, Version, Hash) und Gate vor
Finalisierung/Vertragsunterzeichnung. An der Basis r5/h3-monolith-extract @
26061b77 rot: weder Tabellen noch Endpunkte noch Gate existieren.
"""
from __future__ import annotations

import sys
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parent
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from h8_support import NOW, TENANT, Req, alembic_cfg, codes, mandate, sf, user  # noqa: E402,F401

import json  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from pydantic import ValidationError  # noqa: E402
from sqlalchemy import text  # noqa: E402

from core.reason_codes import DomainError  # noqa: E402
from database import new_uuid  # noqa: E402
from models import review  # noqa: E402
from models.clients import Client  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from models.review import AuditLog, ClientInformationDelivery, ContractDocument  # noqa: E402
from models.tenant import Tenant  # noqa: E402
from models.users import User  # noqa: E402
from routers.review import (  # noqa: E402
    get_tenant_legal_profile, record_client_information_delivery, sign_document,
    update_tenant_legal_profile,
)
from schemas.review import (  # noqa: E402
    ClientInformationDeliveryCreate, ContractDocumentSign, TenantLegalProfileUpdate,
)
from services import recommendation_release_gate as gate  # noqa: E402

from client_onboarding_fixture import (  # noqa: E402
    ensure_test_legal_profile, record_test_client_information, satisfy_client_onboarding,
)
from test_optimizer_shadow_mode import session_factory  # noqa: E402,F401

def test_fresh_tenant_has_no_prefilled_legal_data_and_names_every_missing_field(sf):
    with sf() as db:
        resp = get_tenant_legal_profile(db=db, current_user=user(db, "adm-1"))
    assert resp.present is False
    for name in ("legal_name", "address_street", "ombudsman_name", "supervisory_authority",
                 "supervisory_organisation", "contact_email"):
        assert getattr(resp, name) is None, name
    assert {"legal_name", "address_street", "address_city", "address_country", "business_activity",
            "supervision_type", "ombudsman_name", "ombudsman_address", "contact_phone"} <= set(resp.missing_fields)
    assert resp.complete is False


def test_legal_profile_update_is_admin_audited_field_by_field_and_revisioned(sf):
    with sf() as db:
        body = TenantLegalProfileUpdate(legal_name="Muster VV AG", address_country="ch",
                                        supervision_type="vermoegensverwalter_finig")
        resp = update_tenant_legal_profile(body=body, request=Req(), db=db, current_user=user(db, "adm-1"))
        assert resp.revision == 1 and resp.address_country == "CH"
        # Aufsichtsstatus VV verlangt Aufsichtsbehoerde und AO.
        assert {"supervisory_authority", "supervisory_organisation"} <= set(resp.missing_fields)
        resp2 = update_tenant_legal_profile(
            body=TenantLegalProfileUpdate(legal_name="Muster VV AG"), request=Req(), db=db,
            current_user=user(db, "adm-1"),
        )
        assert resp2.revision == 1  # keine inhaltliche Aenderung -> keine neue Revision
        rows = db.query(AuditLog).filter(AuditLog.table_name == "tenant_legal_profiles").all()
        assert sorted(r.field_name for r in rows) == ["address_country", "legal_name", "supervision_type"]
        legal = next(r for r in rows if r.field_name == "legal_name")
        assert legal.old_value is None and legal.new_value == "Muster VV AG"


def test_tier1_admin_without_tenant_uses_default_tenant_like_the_rest_of_ares(sf):
    """Bootstrap-Admin (Tier 1) hat tenant_id NULL -> Standard-Mandant 'main',
    wie services/auth.py::_resolve_tenant_id_for_user und routers/mandates.py."""
    from models.tenant import DEFAULT_TENANT_ID

    assert gate._DEFAULT_TENANT_ID == DEFAULT_TENANT_ID
    with sf() as db:
        db.add(Tenant(id=DEFAULT_TENANT_ID, display_name="Main", slug="main-h8", created_at=NOW, updated_at=NOW))
        db.add(User(id="adm-t1", username="adm-t1", password_hash="x", full_name="T1", role="admin",
                    is_active=1, tenant_id=None, created_at=NOW, updated_at=NOW))
        db.add(Client(id="c-t1", tenant_id=None, client_number="K-T1", first_name="A", last_name="B",
                      advisor_id="adm-t1", created_at=NOW, updated_at=NOW))
        db.add(Mandate(id="m-t1", tenant_id=None, client_id="c-t1", mandate_number="M-T1",
                       mandate_type="Vermögensverwaltung", opened_at=NOW, created_at=NOW, updated_at=NOW))
        db.commit()
        admin = user(db, "adm-t1")
        resp = update_tenant_legal_profile(body=TenantLegalProfileUpdate(legal_name="Firma T1"),
                                           request=Req(), db=db, current_user=admin)
        assert resp.tenant_id == DEFAULT_TENANT_ID and resp.legal_name == "Firma T1"
        mandate = db.query(Mandate).filter(Mandate.id == "m-t1").first()
        assert gate.mandate_tenant_id(db, mandate) == DEFAULT_TENANT_ID
        assert gate.load_tenant_legal_profile(db, gate.mandate_tenant_id(db, mandate))["legal_name"] == "Firma T1"


def test_adviser_register_status_requires_register_reference_not_ao():
    profile = {k: "x" for k in ("legal_name", "address_street", "address_postal_code", "address_city",
                                "business_activity", "ombudsman_name", "ombudsman_address", "contact_email")}
    profile.update(address_country="CH", supervision_type="anlageberater_ohne_prudenzielle_aufsicht")
    assert gate.legal_profile_missing_fields(profile) == ["license_reference"]
    profile["license_reference"] = "Beraterregister X, Nr. 1"
    assert gate.legal_profile_missing_fields(profile) == []
    profile["supervision_type"] = "erfunden"
    assert gate.legal_profile_missing_fields(profile) == ["supervision_type"]

def test_gate_names_missing_company_data_and_missing_delivery_with_owner_hints(sf):
    with sf() as db:
        findings = gate.client_onboarding_findings(db, mandate(db))
    found = [f["reason_code"] for f in findings]
    assert found[:2] == ["CLIENT_INFORMATION_TENANT_DATA_MISSING", "CLIENT_INFORMATION_NOT_DELIVERED"]
    tenant_finding = findings[0]
    assert "Ombudsstelle: Name" in tenant_finding["owner_action"]
    assert "Administration > Rechtliche Angaben" in tenant_finding["owner_action"]
    assert all(f["owner_action"] for f in findings)


def test_foreign_seat_is_not_silently_released(sf):
    with sf() as db:
        satisfy_client_onboarding(db, mandate(db), actor_id="adv-1")
        ensure_test_legal_profile(db, TENANT, address_country="DE")
        db.commit()
        assert codes(db) == ["CLIENT_INFORMATION_REGIME_UNSUPPORTED"]


def test_client_information_deliveries_are_append_only(sf):
    with sf() as db:
        satisfy_client_onboarding(db, mandate(db), actor_id="adv-1")
        db.commit()
    with sf() as db:
        with pytest.raises(Exception, match="immutable"):
            db.execute(text("UPDATE client_information_deliveries SET delivered_at = 'x'"))
        db.rollback()
        with pytest.raises(Exception, match="immutable"):
            db.execute(text("DELETE FROM client_information_deliveries"))
        db.rollback()


def test_information_handed_over_after_contract_conclusion_blocks(sf):
    with sf() as db:
        satisfy_client_onboarding(db, mandate(db), actor_id="adv-1")
        # Die Fixture-Abgabe ungueltig machen; massgebend ist die spaete Abgabe unten.
        db.query(ContractDocument).filter(ContractDocument.document_type == "Kundeninformation").update(
            {"checksum_sha256": "0" * 64}
        )
        db.add(ContractDocument(
            id="vertrag-1", mandate_id="m-1", document_type="Beratungsvertrag", title="Vertrag",
            status="Teilweise unterzeichnet", signed_by_advisor=1, signed_by_client=0,
            signed_at="2026-01-01T10:00:00.000Z", version=1, created_by="adv-1",
            created_at=NOW, updated_at=NOW,
        ))
        record_test_client_information(db, mandate(db), actor_id="adv-1",
                                       delivered_at="2026-02-01T10:00:00.000Z")
        db.commit()
        findings = gate.client_onboarding_findings(db, mandate(db))
    assert [f["reason_code"] for f in findings] == ["CLIENT_INFORMATION_DELIVERED_AFTER_CONTRACT"]
    assert findings[0]["contract_concluded_at"] == "2026-01-01T10:00:00.000Z"


def test_delivery_whose_archived_pdf_hash_changed_does_not_count(sf):
    with sf() as db:
        satisfy_client_onboarding(db, mandate(db), actor_id="adv-1")
        db.query(ContractDocument).filter(ContractDocument.document_type == "Kundeninformation").update(
            {"checksum_sha256": "0" * 64}
        )
        db.commit()
        assert codes(db) == ["CLIENT_INFORMATION_NOT_DELIVERED"]


def test_contract_signature_blocked_before_any_mutation(sf):
    with sf() as db:
        db.add(ContractDocument(
            id="vertrag-2", mandate_id="m-1", document_type="Beratungsvertrag", title="Vertrag",
            status="Bereit", signed_by_advisor=0, signed_by_client=0, version=1,
            checksum_sha256="a" * 64, pdf_base64="JVBERg==", created_by="adv-1",
            created_at=NOW, updated_at=NOW,
        ))
        db.commit()
        body = ContractDocumentSign(signed_by_advisor=True, signature_image="data:image/png;base64,AAAA",
                                    signer_name="Berater")
        with pytest.raises(DomainError) as exc:
            sign_document(mandate_id="m-1", doc_id="vertrag-2", body=body, request=Req(), db=db,
                          current_user=user(db, "adv-1"))
        assert exc.value.reason_code == "CLIENT_ONBOARDING_INCOMPLETE"
        assert exc.value.http_status == 409
        assert "CLIENT_INFORMATION_NOT_DELIVERED" in exc.value.extra["finding_codes"]
        db.rollback()
        doc = db.query(ContractDocument).filter(ContractDocument.id == "vertrag-2").first()
        assert doc.signed_by_advisor == 0 and doc.signed_at is None


@pytest.fixture()
def ready_run(session_factory):
    from test_finalize_conflict_evidence_gate import _ready_run

    return _ready_run(session_factory, suffix="h8", client_onboarding=False)


def test_finalization_requires_client_information_and_kyc(session_factory, ready_run):
    from test_finalize_conflict_evidence_gate import _finalize

    advisor_id, mandate_id, run_id = ready_run
    with pytest.raises(DomainError) as exc:
        _finalize(session_factory, mandate_id, run_id, advisor_id)
    assert exc.value.reason_code == "CLIENT_ONBOARDING_INCOMPLETE"
    assert exc.value.http_status == 422
    assert {"CLIENT_INFORMATION_TENANT_DATA_MISSING", "CLIENT_INFORMATION_NOT_DELIVERED"} <= set(
        exc.value.extra["finding_codes"])
    with session_factory() as db:
        run = db.query(review.RecommendationRun).filter(review.RecommendationRun.id == run_id).first()
        assert run.result_status == "Draft"
        satisfy_client_onboarding(db, db.query(Mandate).filter(Mandate.id == mandate_id).first())
        db.commit()
    result = _finalize(session_factory, mandate_id, run_id, advisor_id)
    assert result.result_status == "Final"


def _archive_kundeninformation(db, profile_hash: str, version: str = gate.CLIENT_INFORMATION_TEMPLATE_VERSION):
    doc = ContractDocument(
        id=new_uuid(), mandate_id="m-1", document_type="Kundeninformation", title="KI",
        status="Archiviert", signed_by_advisor=0, signed_by_client=0, version=1,
        checksum_sha256="b" * 64, content_json=json.dumps({
            "template_version": version, "legal_profile_hash": profile_hash, "legal_profile_revision": 1,
        }), created_by="adv-1", created_at=NOW, updated_at=NOW,
    )
    db.add(doc)
    db.commit()
    return doc


def test_delivery_endpoint_records_hash_version_and_rejects_outdated_or_future(sf):
    with sf() as db:
        profile = ensure_test_legal_profile(db, TENANT)
        db.commit()
        current = _archive_kundeninformation(db, profile.profile_hash)
        stale = _archive_kundeninformation(db, "f" * 64)
        adv = user(db, "adv-1")
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        with pytest.raises(HTTPException) as exc:
            record_client_information_delivery(
                mandate_id="m-1", body=ClientInformationDeliveryCreate(
                    contract_document_id=stale.id, delivered_at=past, delivery_channel="post"),
                request=Req(), db=db, current_user=adv)
        assert exc.value.detail["reason_code"] == "CLIENT_INFORMATION_OUTDATED"
        future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        with pytest.raises(HTTPException) as exc:
            record_client_information_delivery(
                mandate_id="m-1", body=ClientInformationDeliveryCreate(
                    contract_document_id=current.id, delivered_at=future, delivery_channel="post"),
                request=Req(), db=db, current_user=adv)
        assert exc.value.detail["reason_code"] == "CLIENT_INFORMATION_DELIVERY_IN_FUTURE"
        rec = record_client_information_delivery(
            mandate_id="m-1", body=ClientInformationDeliveryCreate(
                contract_document_id=current.id, delivered_at=past, delivery_channel="persoenlich_papier"),
            request=Req(), db=db, current_user=adv)
        assert rec.pdf_sha256 == "b" * 64
        assert rec.template_version == gate.CLIENT_INFORMATION_TEMPLATE_VERSION
        assert rec.legal_profile_hash == profile.profile_hash
        assert rec.delivered_at.endswith("Z") and len(rec.delivery_hash) == 64
        assert "CLIENT_INFORMATION_NOT_DELIVERED" not in codes(db)


def test_delivered_at_without_timezone_is_rejected():
    with pytest.raises(ValidationError):
        ClientInformationDeliveryCreate(contract_document_id="d", delivered_at="2026-11-01T10:00:00",
                                        delivery_channel="post")


def test_kundeninformation_pdf_fail_closed_then_archived_with_profile_binding(sf):
    from routers.pdf_reports import get_kundeninformation_pdf

    with sf() as db:
        adv = user(db, "adv-1")
        with pytest.raises(HTTPException) as exc:
            get_kundeninformation_pdf(mandate_id="m-1", request=Req(), db=db, current_user=adv)
        assert exc.value.status_code == 409
        assert exc.value.detail["reason_code"] == "CLIENT_INFORMATION_TENANT_DATA_MISSING"
        assert "ombudsman_name" in exc.value.detail["missing_fields"]
        profile = ensure_test_legal_profile(db, TENANT)
        db.commit()
        resp = get_kundeninformation_pdf(mandate_id="m-1", request=Req(), db=db, current_user=adv)
        assert resp.body.startswith(b"%PDF")
        doc = db.query(ContractDocument).filter(ContractDocument.document_type == "Kundeninformation").one()
        meta = json.loads(doc.content_json)
        assert meta["legal_profile_hash"] == profile.profile_hash
        assert meta["template_version"] == gate.CLIENT_INFORMATION_TEMPLATE_VERSION
        assert resp.headers["X-Client-Information-Byte-Sha256"] == doc.checksum_sha256
        # Render-once: unveraenderte Daten -> dieselbe archivierte Fassung.
        again = get_kundeninformation_pdf(mandate_id="m-1", request=Req(), db=db, current_user=adv)
        assert again.body == resp.body
        assert db.query(ContractDocument).filter(ContractDocument.document_type == "Kundeninformation").count() == 1


def test_kundeninformation_text_contains_owner_data_and_no_invented_values(sf):
    from routers.pdf_reports import _build_kundeninformation_data
    from services.pdf.documents.vertrag import build_kundeninformation_flowables  # noqa: F401

    with sf() as db:
        profile = ensure_test_legal_profile(db, TENANT, ombudsman_name="Meine Ombudsstelle")
        db.commit()
        data = _build_kundeninformation_data(db, mandate(db), gate.load_tenant_legal_profile(db, TENANT))
    labels = dict(data.provider_lines)
    assert labels["Firma"] == profile.legal_name
    assert labels["Aufsichtsorganisation"] == profile.supervisory_organisation
    assert data.ombudsman_name == "Meine Ombudsstelle"
    assert data.mandate_type == "Anlageberatung"
    assert data.economic_ties == ("Für dieses Mandat sind keine wirtschaftlichen Bindungen an Dritte erfasst.",)
    assert data.cost_lines == ()  # kein Kostenausweis -> Hinweis statt erfundener Zahlen
    assert "Ex-ante-Kostenausweis" in data.cost_note


def test_single_alembic_head_is_h8_revision():
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(alembic_cfg("sqlite://"))
    assert script.get_heads() == ["d8e4b2a6c1f9"]


def test_alembic_postgres_ddl_creates_client_information_tables_and_triggers():
    from h8_support import h8_postgres_ddl

    ddl = h8_postgres_ddl()
    for table in ("tenant_legal_profiles", "client_information_deliveries"):
        assert f"CREATE TABLE {table}" in ddl, table
    assert "CREATE TRIGGER trg_client_information_deliveries_immutable" in ddl
