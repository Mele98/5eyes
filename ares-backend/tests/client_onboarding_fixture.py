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

C-890-01: Seit der Wiedervorlage-Policy braucht jede KYC-Bestaetigung die
Bindung an eine freigegebene Policy. Die Fixture-Policy (``TEST_KYC_REVIEW_
POLICY``) ist ausdruecklich ein TESTWERT -- keine Owner-Frist und kein
Produktdefault; das Produkt selbst kennt keine Frist.
"""
from __future__ import annotations

import hashlib
from datetime import date, timedelta

from database import new_uuid
from models.clients import Client, ClientDueDiligence, KycConfirmation
from models.review import ClientInformationDelivery, ContractDocument
from models.tenant import (
    KYC_REVIEW_GENESIS,
    KycReviewPolicy,
    KycReviewPolicyActivation,
    Tenant,
    TenantLegalProfile,
)
from models.users import User
from services.recommendation_release_gate import (
    CLIENT_INFORMATION_DOCUMENT_TYPE,
    CLIENT_INFORMATION_TEMPLATE_VERSION,
    LEGAL_PROFILE_FIELDS,
    add_months_clamped,
    kyc_review_interval_months,
    kyc_review_risk_class,
    legal_profile_hash,
    row_seal,
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
        profile = TenantLegalProfile(id=new_uuid(), tenant_id=tenant_id, created_at=_PAST, updated_at=_PAST)
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


def _seal(record, column: str) -> str:
    return row_seal({c.name: getattr(record, c.name) for c in record.__table__.columns}, column)


# C-890-01: TESTWERTE der Wiedervorlage-Policy (keine Owner-Frist, kein
# Produktdefault). Bewusst ungewoehnliche Zahlen, damit sie nie mit einer
# echten Frist verwechselt werden.
TEST_KYC_REVIEW_POLICY = {
    "policy_id": "TESTFIXTURE-C890-KYC-REVIEW",
    "normal_max_months": 23,
    "elevated_max_months": 11,
    "source_reference": f"{TEST_MARKER}/C-890-01 Testwert -- keine Owner-Frist",
}
TEST_KYC_REVIEW_APPROVER_ID = "testfixture-c890-zweitfreigabe"


def _test_review_approver(db, actor_id: str) -> str:
    other = db.query(User).filter(User.id != actor_id).order_by(User.id).first()
    if other is not None:
        return str(other.id)
    db.add(User(
        id=TEST_KYC_REVIEW_APPROVER_ID, username=TEST_KYC_REVIEW_APPROVER_ID, password_hash="x",
        full_name=f"{TEST_MARKER} Zweitfreigabe (Testwert)", role="admin", is_active=0,
        created_at=_PAST, updated_at=_PAST,
    ))
    db.flush()
    return TEST_KYC_REVIEW_APPROVER_ID


def ensure_test_kyc_review_policy(
    db, tenant_id: str, *, actor_id: str, jurisdiction: str = "CH",
    approved_at: str = _PAST, **overrides,
):
    """Aktivierte TEST-Policy (Version + Vier-Augen-Aktivierung) fuer
    ``tenant_id``/``jurisdiction``; idempotent, solange schon eine Version
    aktiviert ist. Gibt (policy, activation) zurueck."""
    activation = db.query(KycReviewPolicyActivation).filter(
        KycReviewPolicyActivation.tenant_id == tenant_id,
        KycReviewPolicyActivation.jurisdiction == jurisdiction,
    ).order_by(KycReviewPolicyActivation.approved_at.desc()).first()
    if activation is not None and not overrides:
        policy = db.query(KycReviewPolicy).filter(KycReviewPolicy.id == activation.policy_row_id).first()
        return policy, activation
    values = {**TEST_KYC_REVIEW_POLICY, **overrides}
    head = activation
    version = 1 + max(
        [int(p.version) for p in db.query(KycReviewPolicy).filter(
            KycReviewPolicy.tenant_id == tenant_id, KycReviewPolicy.jurisdiction == jurisdiction).all()] or [0]
    )
    policy = KycReviewPolicy(
        id=new_uuid(), tenant_id=tenant_id, jurisdiction=jurisdiction,
        policy_id=values["policy_id"], version=version,
        normal_max_months=values["normal_max_months"],
        elevated_max_months=values.get("elevated_max_months"),
        valid_from=values.get("valid_from", "2000-01-01"), valid_until=values.get("valid_until"),
        source_reference=values["source_reference"], created_by=actor_id, created_at=_PAST,
    )
    policy.policy_hash = _seal(policy, "policy_hash")
    db.add(policy)
    db.flush()
    activation = KycReviewPolicyActivation(
        id=new_uuid(), tenant_id=tenant_id, jurisdiction=jurisdiction, policy_row_id=policy.id,
        predecessor_activation_id=head.id if head is not None else KYC_REVIEW_GENESIS,
        approved_by=_test_review_approver(db, actor_id), approved_at=approved_at,
        approval_reference=f"{TEST_MARKER}/C-890-01 Testfreigabe", policy_hash=policy.policy_hash,
    )
    activation.activation_hash = _seal(activation, "activation_hash")
    db.add(activation)
    db.flush()
    return policy, activation


def record_test_client_information(
    db, mandate, *, actor_id: str, delivered_at: str = _PAST, recorded_at: str = _PAST,
):
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
    delivery = ClientInformationDelivery(
        id=new_uuid(), tenant_id=tenant_id, mandate_id=mandate.id, client_id=mandate.client_id,
        contract_document_id=doc.id, template_version=CLIENT_INFORMATION_TEMPLATE_VERSION,
        legal_profile_revision=int(profile.revision or 0) if profile else 0,
        legal_profile_hash=(profile.profile_hash if profile else "") or "",
        pdf_sha256=checksum, delivered_at=delivered_at, delivery_channel="persoenlich_papier",
        delivery_timing="vor_vertragsabschluss",
        recorded_by=actor_id, recorded_at=recorded_at,
    )
    delivery.delivery_hash = _seal(delivery, "delivery_hash")
    db.add(delivery)
    db.flush()
    return doc


def confirm_test_kyc(db, client_id: str, *, actor_id: str, tenant_id: str | None = None) -> KycConfirmation:
    dd = db.query(ClientDueDiligence).filter(ClientDueDiligence.client_id == client_id).first()
    if dd is None:
        dd = ClientDueDiligence(id=new_uuid(), client_id=client_id, created_at=_PAST, updated_at=_PAST)
        db.add(dd)
    if not int(dd.acting_for_own_account_answered or 0):
        dd.acting_for_own_account = 1
        dd.acting_for_own_account_answered = 1
    today = date.today()
    tenant = tenant_id or "main"
    policy, activation = ensure_test_kyc_review_policy(db, tenant, actor_id=actor_id)
    completed = (today - timedelta(days=1)).isoformat()
    risk_class = kyc_review_risk_class("normal", dd.pep_status)
    interval = kyc_review_interval_months(
        {"normal_max_months": policy.normal_max_months, "elevated_max_months": policy.elevated_max_months},
        risk_class,
    )
    max_due = add_months_clamped(completed, interval)
    record = KycConfirmation(
        id=new_uuid(), tenant_id=tenant_id, client_id=client_id, mandate_id=None,
        process_scope="sro_oder_fremdprozess", form_type="A",
        form_completed_on=completed,
        external_reference=f"{TEST_MARKER} KYC", risk_category="normal",
        is_pep=int(dd.pep_status or 0), identification_confirmed=1,
        identification_date=completed,
        next_review_due=max_due,
        requires_second_approval=int(dd.pep_status or 0),
        recorded_by=actor_id, recorded_at=activation.approved_at,
        review_policy_row_id=policy.id, review_policy_activation_id=activation.id,
        review_policy_id=policy.policy_id, review_policy_version=policy.version,
        review_policy_hash=policy.policy_hash, review_risk_class=risk_class,
        review_interval_months=interval, review_max_due=max_due,
    )
    record.confirmation_hash = _seal(record, "confirmation_hash")
    db.add(record)
    db.flush()
    return record


def satisfy_client_onboarding(db, mandate, *, actor_id: str | None = None) -> None:
    """Rechtliche Angaben (Testwerte), Kundeninformation vor Vertragsabschluss
    und GwG-Bestaetigung fuer ``mandate`` erfassen (idempotent genug fuer
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
    has_kyc = db.query(KycConfirmation).filter(KycConfirmation.client_id == mandate.client_id).first()
    if has_kyc is None:
        confirm_test_kyc(db, mandate.client_id, actor_id=actor, tenant_id=tenant_id)


def satisfy_client_onboarding_for_all_mandates(db) -> None:
    """Fuer Fixtures, die den Mandatsbezug nicht in der Hand haben."""
    from models.mandates import Mandate

    for mandate in db.query(Mandate).all():
        satisfy_client_onboarding(db, mandate)
