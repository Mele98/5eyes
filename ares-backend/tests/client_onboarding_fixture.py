"""H8 C-2/C-5: Testhilfe fuer Finalisierungs-/Signatur-Fixtures.

Seit dem Kundeninformations-/KYC-Gate
(services/recommendation_release_gate.py::client_onboarding_findings) sind
Finalisierung und Vertragsunterzeichnung nur mit vollstaendigen rechtlichen
Angaben der Firma, vor Vertragsabschluss abgegebener Kundeninformation und
GwG-Bestaetigung moeglich (fail-closed). Bestehende Tests, die etwas anderes
pruefen, erfuellen diese Voraussetzungen ausdruecklich mit offen als
Testwerte gekennzeichneten Angaben -- nie stillschweigend.

Die Testwerte sind keine Vorbelegung des Produkts: Ares selbst belegt keine
rechtliche Angabe vor.
"""
from __future__ import annotations

import hashlib

from database import new_uuid
from models.clients import Client
from models.review import ClientInformationDelivery, ContractDocument
from models.tenant import Tenant, TenantLegalProfile
from services.recommendation_release_gate import (
    CLIENT_INFORMATION_DOCUMENT_TYPE,
    CLIENT_INFORMATION_TEMPLATE_VERSION,
    LEGAL_PROFILE_FIELDS,
    legal_profile_hash,
)

TEST_MARKER = "Testfixture H8"
_PAST = "2000-01-01T00:00:00.000Z"

TEST_LEGAL_PROFILE = {
    "legal_name": f"{TEST_MARKER} Vermoegensverwaltung (Testwert)",
    "address_street": "Teststrasse 1",
    "address_postal_code": "0000",
    "address_city": "Testort",
    "address_country": "CH",
    "business_activity": "Vermoegensverwaltung und Anlageberatung (Testwert)",
    "supervision_type": "vermoegensverwalter_finig",
    "supervisory_authority": "Aufsichtsbehoerde (Testwert)",
    "supervisory_organisation": "Aufsichtsorganisation (Testwert)",
    "license_reference": None,
    "ombudsman_name": "Ombudsstelle (Testwert)",
    "ombudsman_address": "Testadresse Ombudsstelle (Testwert)",
    "contact_phone": None,
    "contact_email": "test@example.invalid",
    "contact_website": None,
}


def ensure_test_legal_profile(db, tenant_id: str, **overrides) -> TenantLegalProfile:
    values = {**TEST_LEGAL_PROFILE, **overrides}
    profile = db.query(TenantLegalProfile).filter(TenantLegalProfile.tenant_id == tenant_id).first()
    if profile is None:
        profile = TenantLegalProfile(tenant_id=tenant_id, created_at=_PAST, updated_at=_PAST)
        db.add(profile)
    for name, value in values.items():
        setattr(profile, name, value)
    profile.revision = int(profile.revision or 0) + 1
    profile.profile_hash = legal_profile_hash({n: getattr(profile, n) for n, _l in LEGAL_PROFILE_FIELDS})
    db.flush()
    return profile


def _tenant_for(db, mandate) -> str:
    if getattr(mandate, "tenant_id", None):
        return str(mandate.tenant_id)
    client = db.query(Client).filter(Client.id == mandate.client_id).first()
    if client is not None and client.tenant_id:
        return str(client.tenant_id)
    tenant = db.query(Tenant).order_by(Tenant.created_at).first()
    if tenant is None:
        tenant = Tenant(id="main", display_name=f"{TEST_MARKER} Tenant", slug="main",
                        created_at=_PAST, updated_at=_PAST)
        db.add(tenant)
        db.flush()
    mandate.tenant_id = tenant.id
    db.flush()
    return str(tenant.id)


def record_test_client_information(db, mandate, *, actor_id: str, delivered_at: str = _PAST):
    tenant_id = _tenant_for(db, mandate)
    profile = db.query(TenantLegalProfile).filter(TenantLegalProfile.tenant_id == tenant_id).first()
    pdf_bytes = f"%PDF-1.4 {TEST_MARKER} Kundeninformation {mandate.id}".encode("utf-8")
    checksum = hashlib.sha256(pdf_bytes).hexdigest()
    doc = ContractDocument(
        id=new_uuid(), mandate_id=mandate.id, document_type=CLIENT_INFORMATION_DOCUMENT_TYPE,
        title=f"Kundeninformation ({TEST_MARKER})", status="Archiviert",
        checksum_sha256=checksum, content_hash=checksum, pdf_generated_at=_PAST,
        signed_by_advisor=0, signed_by_client=0, version=1,
        created_by=actor_id, created_at=_PAST, updated_at=_PAST,
    )
    db.add(doc)
    db.flush()
    db.add(ClientInformationDelivery(
        id=new_uuid(), tenant_id=tenant_id, mandate_id=mandate.id, client_id=mandate.client_id,
        contract_document_id=doc.id, template_version=CLIENT_INFORMATION_TEMPLATE_VERSION,
        legal_profile_revision=int(profile.revision or 0) if profile else 0,
        legal_profile_hash=(profile.profile_hash if profile else "") or "",
        pdf_sha256=checksum, delivered_at=delivered_at, delivery_channel="persoenlich_papier",
        recorded_by=actor_id, recorded_at=_PAST, delivery_hash=checksum,
    ))
    db.flush()
    return doc


def satisfy_client_onboarding(db, mandate, *, actor_id: str | None = None) -> None:
    """Rechtliche Angaben (Testwerte) und Kundeninformation vor Vertragsabschluss
    fuer ``mandate`` erfassen (idempotent genug fuer
    wiederholte Aufrufe innerhalb eines Tests)."""
    client = db.query(Client).filter(Client.id == mandate.client_id).first()
    actor = actor_id or (client.advisor_id if client is not None else None)
    if actor is None:
        raise RuntimeError("Testfixture H8: kein Akteur (Berater) bekannt")
    tenant_id = _tenant_for(db, mandate)
    ensure_test_legal_profile(db, tenant_id)
    existing = db.query(ClientInformationDelivery).filter(
        ClientInformationDelivery.mandate_id == mandate.id
    ).first()
    if existing is None:
        record_test_client_information(db, mandate, actor_id=actor)


def satisfy_client_onboarding_for_all_mandates(db) -> None:
    """Fuer Fixtures, die den Mandatsbezug nicht in der Hand haben."""
    from models.mandates import Mandate

    for mandate in db.query(Mandate).all():
        satisfy_client_onboarding(db, mandate)
