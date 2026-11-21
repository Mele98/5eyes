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
    # N-897-04: das Gate rechnet die Vier-Augen-Regel per Person nach -- die
    # zweite Person muss eine Freigaberolle haben (Admin).
    other = db.query(User).filter(User.id != actor_id, User.role.in_(("admin", "super_admin"))).order_by(User.id).first()
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
    # H-179 L2/L3: Owner-Inhalte, Depotbank-Angabe, W033 (Testwerte).
    satisfy_contract_layer(db, mandate, actor_id=actor)


def satisfy_client_onboarding_for_all_mandates(db) -> None:
    """Fuer Fixtures, die den Mandatsbezug nicht in der Hand haben."""
    from models.mandates import Mandate

    for mandate in db.query(Mandate).all():
        satisfy_client_onboarding(db, mandate)


# ---------------------------------------------------------------------------
# H-179 L2/L3 Vertragsschicht: TESTWERTE der Owner-Inhalte (keine Owner-Texte,
# kein Produktdefault). Jeder Text traegt den Marker und ist sofort als
# Testwert erkennbar; das Produkt selbst belegt keinen Inhalt vor.
# ---------------------------------------------------------------------------

TEST_CONTRACT_MARKER = "Testfixture H-179"
TEST_DEPOT_BANK = "Testbank H-179 (Testwert)"
# Bewusst 1 Jahr: kein Owner-Wert; sorgt dafuer, dass Bestandstests nicht in
# den Abraten-Pfad laufen (der eigene Test setzt einen hoeheren Testwert).
TEST_MIN_HORIZON_YEARS = 1


def _owner_content_test_keys() -> list[tuple[str, str | None, dict | None]]:
    from services import recommendation_release_gate as oc

    keys: list[tuple[str, str | None, dict | None]] = []
    for clause in oc.CONTRACT_CLAUSE_KEYS:
        key = oc.contract_clause_key(oc.CONTRACT_SHARED_SLUG, clause)
        keys.append((key, f"{TEST_CONTRACT_MARKER} Testwert, kein Owner-Text: {oc.CONTRACT_CLAUSE_LABELS[clause]}", None))
    for section, label, *_rest in oc.PRIVACY_SECTIONS:
        key = oc.PRIVACY_KEY_PREFIX + section
        keys.append((key, f"{TEST_CONTRACT_MARKER} Testwert, kein Owner-Text: {label}", None))
    for key, label in ((oc.W033_DECLARATION_KEY, "Erklärung des Kunden"),
                       (oc.W033_HORIZON_ADVICE_KEY, "Hinweis zum Anlagehorizont")):
        keys.append((key, f"{TEST_CONTRACT_MARKER} Testwert, kein Owner-Text: {label}", None))
    keys.append((oc.W033_MIN_HORIZON_KEY, None, TEST_MIN_HORIZON_YEARS))
    return keys


def _test_owner_approver(db, actor_id: str, tenant_id: str) -> str:
    """N-927-02: zweite Person mit Freigaberolle in DERSELBEN Firma und mit
    anderer Postfach-Identitaet (das Gate rechnet beides beim Lesen nach)."""
    from services.auth import normalize_email_identity

    actor = db.query(User).filter(User.id == actor_id).first()
    actor_mail = normalize_email_identity(getattr(actor, "email", None))
    tenant_filter = (User.tenant_id.is_(None) | (User.tenant_id == "main")) if tenant_id == "main"         else (User.tenant_id == tenant_id)
    for other in db.query(User).filter(
        User.id != actor_id, User.role.in_(("admin", "super_admin")), tenant_filter,
    ).order_by(User.id).all():
        if not actor_mail or normalize_email_identity(other.email) != actor_mail:
            return str(other.id)
    approver_id = f"testfixture-h179-zweitfreigabe-{tenant_id}"
    if db.query(User).filter(User.id == approver_id).first() is None:
        db.add(User(
            id=approver_id, username=approver_id, password_hash="x",
            full_name=f"{TEST_CONTRACT_MARKER} Zweitfreigabe (Testwert)", role="admin", is_active=0,
            tenant_id=None if tenant_id == "main" else tenant_id, created_at=_PAST, updated_at=_PAST,
        ))
        db.flush()
    return approver_id


def ensure_test_owner_content(
    db, tenant_id: str, *, actor_id: str, key: str, body_text: str | None = None,
    value=None, approve: bool = True,
):
    """Neue Version (+ Vier-Augen-Freigabe) eines Owner-Inhalts als TESTWERT."""
    from models.tenant import OWNER_CONTENT_GENESIS, OwnerContentApproval, OwnerContentVersion
    from services import recommendation_release_gate as oc

    head = oc.resolve_owner_content(db, tenant_id, key)
    entry = oc.owner_catalog_entry(key)
    stored_text, stored_value = oc.normalize_owner_payload(entry, body_text, value)
    versions, _approvals = oc.owner_content_chain(db, tenant_id, key)
    version = OwnerContentVersion(
        id=new_uuid(), tenant_id=tenant_id, content_key=key, catalog_version=oc.OWNER_CATALOG_VERSION,
        version=max((int(v["version"]) for v in versions.values()), default=0) + 1,
        body_text=stored_text, value_json=stored_value,
        source_reference=f"{TEST_CONTRACT_MARKER} Testwert", created_by=actor_id, created_at=_PAST,
    )
    version.content_hash = _seal(version, "content_hash")
    db.add(version)
    db.flush()
    if approve:
        approval = OwnerContentApproval(
            id=new_uuid(), tenant_id=tenant_id, content_key=key, content_row_id=version.id,
            predecessor_approval_id=(head["approval"]["id"] if head["status"] == oc.OWNER_STATUS_APPROVED
                                     else OWNER_CONTENT_GENESIS),
            approved_by=_test_owner_approver(db, actor_id, tenant_id), approved_at=_PAST,
            approval_reference=f"{TEST_CONTRACT_MARKER} Testfreigabe", content_hash=version.content_hash,
        )
        approval.approval_hash = _seal(approval, "approval_hash")
        db.add(approval)
        db.flush()
    return oc.resolve_owner_content(db, tenant_id, key)


def ensure_test_contract_layer_tenant(db, tenant_id: str, *, actor_id: str) -> None:
    from services import recommendation_release_gate as oc

    for key, text, value in _owner_content_test_keys():
        if oc.resolve_owner_content(db, tenant_id, key)["status"] == oc.OWNER_STATUS_APPROVED:
            continue
        ensure_test_owner_content(db, tenant_id, actor_id=actor_id, key=key, body_text=text, value=value)


def ensure_test_depot_bank_inducement(db, mandate, *, actor_id: str) -> None:
    from services import recommendation_release_gate as oc

    from services.recommendation_release_gate import DEPOT_BANK_REQUIRED_MANDATE_TYPES

    if not str(getattr(mandate, "depot_bank", "") or "").strip():
        if str(getattr(mandate, "mandate_type", "") or "") not in DEPOT_BANK_REQUIRED_MANDATE_TYPES:
            return
        mandate.depot_bank = TEST_DEPOT_BANK
        db.flush()
    tenant_id = _tenant_for(db, mandate)
    key = oc.depot_bank_key(mandate.depot_bank)
    if oc.resolve_owner_content(db, tenant_id, key)["status"] == oc.OWNER_STATUS_APPROVED:
        return
    ensure_test_owner_content(db, tenant_id, actor_id=actor_id, key=key, value={
        "depot_bank": mandate.depot_bank, "status": "keine",
        "evidence_reference": f"{TEST_CONTRACT_MARKER} Testbeleg", "valid_from": "2000-01-01",
    })


def confirm_test_w033(db, mandate, *, actor_id: str) -> None:
    """W033-Bestaetigungen (Testwert) zum aktuellen Risikoprofil, falls vorhanden."""
    from models.review import W033ClientDeclaration
    from services.recommendation_release_gate import w033_state

    state = w033_state(db, mandate)
    if state["assessment_id"] is None:
        return
    todo = []
    if not state["declaration_confirmed"] and state["declaration_binding"]:
        todo.append(("angaben_wahr_meldepflicht", state["declaration_binding"]))
    if state["advice_required"] and not state["advice_confirmed"] and state["advice_binding"]:
        todo.append(("horizont_abraten", state["advice_binding"]))
    for kind, binding in todo:
        record = W033ClientDeclaration(
            id=new_uuid(), tenant_id=mandate.tenant_id, mandate_id=mandate.id, client_id=mandate.client_id,
            risk_assessment_id=state["assessment_id"], declaration_kind=kind,
            content_key=binding["key"], content_row_id=binding["content_row_id"],
            content_hash=binding["content_hash"], horizon_years=state["horizon_years"],
            min_horizon_years=state["min_horizon_years"], capture_channel="persoenlich_papier",
            confirmed_at=_PAST, recorded_by=actor_id, recorded_at=_PAST,
        )
        record.declaration_hash = _seal(record, "declaration_hash")
        db.add(record)
    db.flush()


def record_test_advice_rationale(db, mandate, run_id: str, *, actor_id: str) -> None:
    from models.review import AdviceRationale
    from services.recommendation_release_gate import latest_advice_rationale

    if latest_advice_rationale(db, str(mandate.id), run_id):
        return
    record = AdviceRationale(
        id=new_uuid(), tenant_id=mandate.tenant_id, mandate_id=mandate.id, client_id=mandate.client_id,
        recommendation_run_id=run_id,
        client_needs=f"{TEST_CONTRACT_MARKER} Testwert Bedürfnisse",
        recommendation_reasons=f"{TEST_CONTRACT_MARKER} Testwert Gründe",
        recorded_by=actor_id, recorded_at=_PAST,
    )
    record.rationale_hash = _seal(record, "rationale_hash")
    db.add(record)
    db.flush()


def satisfy_contract_layer(db, mandate, *, actor_id: str | None = None, run_id: str | None = None) -> None:
    """H-179: alle L2/L3-Voraussetzungen (Testwerte) fuer ``mandate``;
    mit ``run_id`` zusaetzlich die Gruende der Empfehlung (P-1)."""
    client = db.query(Client).filter(Client.id == mandate.client_id).first()
    actor = actor_id or (client.advisor_id if client is not None else None)
    if actor is None:
        raise RuntimeError("Testfixture H-179: kein Akteur (Berater) bekannt")
    tenant_id = _tenant_for(db, mandate)
    ensure_test_contract_layer_tenant(db, tenant_id, actor_id=actor)
    ensure_test_depot_bank_inducement(db, mandate, actor_id=actor)
    confirm_test_w033(db, mandate, actor_id=actor)
    bind_test_contract_documents(db, mandate)
    from models.review import RecommendationRun

    run_ids = [run_id] if run_id else [
        r.id for r in db.query(RecommendationRun).filter(RecommendationRun.mandate_id == mandate.id).all()
    ]
    for rid in run_ids:
        record_test_advice_rationale(db, mandate, rid, actor_id=actor)


def satisfy_contract_layer_for_all_mandates(db) -> None:
    """H-179: ``satisfy_contract_layer`` fuer jedes Mandat (inkl. Gruende der
    Empfehlung je vorhandenem Lauf), direkt vor einer Freigabeaktion."""
    from models.mandates import Mandate

    for mandate in db.query(Mandate).all():
        client = db.query(Client).filter(Client.id == mandate.client_id).first()
        if client is None or client.advisor_id is None:
            continue
        satisfy_contract_layer(db, mandate, actor_id=client.advisor_id)


def bind_test_contract_documents(db, mandate) -> None:
    """H-179: unsignierte Beratungsvertraege der Testwelt erhalten einen Ort
    (Testwert) und die Bindung an die aktuelle Vertragsvorlage -- so, wie sie
    das Vertrags-PDF beim finalen Archivieren setzt."""
    import json as _json

    from services.recommendation_release_gate import CONTRACT_DOCUMENT_TYPE, contract_template_binding

    binding = contract_template_binding(db, mandate)
    if binding is None:
        return
    docs = db.query(ContractDocument).filter(
        ContractDocument.mandate_id == mandate.id,
        ContractDocument.document_type == CONTRACT_DOCUMENT_TYPE,
        ContractDocument.deleted_at.is_(None),
        ContractDocument.signed_by_advisor == 0,
        ContractDocument.signed_by_client == 0,
    ).all()
    for doc in docs:
        try:
            content = _json.loads(doc.content_json) if doc.content_json else {}
        except (TypeError, ValueError):
            content = {}
        if not isinstance(content, dict):
            content = {}
        content.setdefault("ort_unterzeichnung", f"Testort ({TEST_CONTRACT_MARKER})")
        content["contract_template"] = binding
        doc.content_json = _json.dumps(content, sort_keys=True, ensure_ascii=False)
    db.flush()
