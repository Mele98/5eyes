"""Endpunkte der Vor-Ort-Signatur mit kundeneigenem Faktor (SIGN-001).

Produktiv gesperrt: ohne freigegebene Policy antwortet jeder schreibende
Schritt mit 409 ``ONSITE_SIGNATURE_NOT_RELEASED`` (inkl. offener Punkte);
``GET /onsite-signature/policy`` zeigt den Freigabestand ehrlich an.

Fachliche Blocks (``svc.OnsiteSignatureError``, ein ``DomainError``) bildet
der zentrale Handler ``core/middleware.py`` auf HTTP ab (K-2); die
Endpunkte fangen sie nicht mehr einzeln ab. Die Antworten sind byte-gleich
zur frueheren ``HTTPException``-Umwandlung
(``tests/test_onsite_signature_http_error_parity.py``).

* Berater-Schritte (require_advisor + Mandatszugriff): eroeffnen,
  Identitaetspruefung, Code an den Kundenkanal senden, Zeugenerklaerung,
  signieren, Kundenkopie zustellen, abbrechen.
* Kundenfaktor (require_client, verknuepfter Kunde): nur ueber
  ``/client-portal/onsite-signature/...`` -- ein Berater-Login erreicht ihn nie.

Vor Eroeffnen und Signieren laufen dieselben fachlichen Freigabe-Gates wie
bei ``routers/review.py::sign_document`` (Risikoprofil-Signoff, Risikobudget).
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from models.review import ContractDocument
from models.users import User
from services.audit import release_block_audit
from services.auth import (
    extract_client_ip,
    get_current_user,
    get_linked_client_for_user_or_404,
    get_mandate_for_user_or_404,
    require_advisor,
    require_client,
    set_tenant_context,
)
from services.onsite_signature import service as svc
from services.onsite_signature import state_machine as sm
from services.onsite_signature.runtime import OnsiteSignatureRuntime, get_onsite_signature_runtime
from services.recommendation_release_gate import (
    CHANNEL_SIGNATURE,
    RECOMMENDATION_DOCUMENT_TYPES,
    SIGNOFF_BOUND_DOCUMENT_TYPES,
    assert_recommendation_release_eligible,
    assert_retrocession_release_eligible,
    assert_risk_signoff_release_eligible,
)

router = APIRouter(tags=["Vor-Ort-Signatur"])

_HASH = Field(min_length=64, max_length=64, pattern=r"^[0-9a-fA-F]{64}$")


class OpenRequest(BaseModel):
    displayed_document_hash: str = _HASH
    language: str = Field(min_length=2, max_length=8)
    device_app_version: str = Field(min_length=1, max_length=100)


class IdentityCheckRequest(BaseModel):
    method: str = Field(min_length=1, max_length=100)
    result: Literal["verified", "failed"]
    id_document_kind: str = Field(min_length=1, max_length=40)
    id_document_country: str = Field(min_length=2, max_length=3)
    id_document_valid: bool


class WitnessRequest(BaseModel):
    statement_version: str = Field(min_length=1, max_length=100)
    statement_hash: str = _HASH
    confirmed: bool


class FinalizeRequest(BaseModel):
    qes_receipt: Optional[dict[str, Any]] = None


class AbortRequest(BaseModel):
    reason_code: Literal["OFFLINE_ABORT", "CUSTOMER_DECLINED", "ADVISOR_CANCELLED"]


class CustomerConfirmRequest(BaseModel):
    challenge_id: str = Field(min_length=1, max_length=64)
    code: str = Field(min_length=1, max_length=32)
    displayed_document_hash: str = _HASH
    consent_text_hash: str = _HASH


def _advisor(user: User) -> svc.AdvisorActor:
    return svc.AdvisorActor(user_id=user.id, role=str(user.role), totp_enabled=bool(user.totp_enabled))


def _release_gates(
    db: Session, mandate, document: ContractDocument, *, current_user: User, request: Optional[Request],
    on_blocked=None,
) -> None:
    """Freigabe-Gates der Vor-Ort-Signatur. H7 N-884-07: jede Sperre (Risiko-
    profil-Signoff, Empfehlungsfreigabe, Retrozession) wird im Audit-Log
    festgehalten (``onsite_signature_blocked``); ``on_blocked(reason_code)``
    erlaubt dem Aufrufer, einen offenen Vorgang danach sauber zu schliessen."""
    audit = release_block_audit(
        db, user=current_user,
        ip_address=extract_client_ip(request) if request is not None else None,
        mandate_id=mandate.id, field_name="onsite_signature_blocked",
        set_tenant_context=set_tenant_context,
    )
    document_type = str(document.document_type or "")
    try:
        if document_type in SIGNOFF_BOUND_DOCUMENT_TYPES:
            assert_risk_signoff_release_eligible(db, mandate, channel=CHANNEL_SIGNATURE)
        if document_type in RECOMMENDATION_DOCUMENT_TYPES:
            assert_recommendation_release_eligible(db, mandate, channel=CHANNEL_SIGNATURE)
            # H7 N-884-04: Retro-Gate auch fuer finale Laeufe (fail-closed).
            assert_retrocession_release_eligible(db, mandate, channel=CHANNEL_SIGNATURE)
    except Exception as exc:
        # Gates werfen DomainError (reason_code im Detail); alles andere
        # (Programmfehler) geht unveraendert weiter.
        as_detail = getattr(exc, "as_detail", None)
        if not callable(as_detail):
            raise
        detail = as_detail()
        reason_code = str(detail.get("reason_code") or "RELEASE_BLOCKED")
        audit(reason_code, detail.get("recommendation_run_id"))
        if on_blocked is not None:
            on_blocked(reason_code)
        raise


def _view(db: Session, transaction_id: str) -> dict[str, Any]:
    tx = svc.load_transaction(db, transaction_id)
    events, evidence = svc.transaction_events_and_evidence(db, transaction_id)
    return {
        "transaction_id": tx.transaction_id,
        "state": tx.state,
        "mandate_id": tx.mandate_id,
        "document_id": tx.document_id,
        "document_hash": tx.document_hash,
        "document_class": tx.opened.get("document_class"),
        "consent_text_hash": tx.opened.get("consent_text_hash"),
        "followup_allowed": tx.state not in sm.FOLLOWUP_BLOCKING_STATES,
        "evidence_hash": evidence.evidence_hash if evidence else None,
        "events": [
            {
                "sequence_no": e.sequence_no,
                "event_type": e.event_type,
                "state": e.state,
                "reason_code": e.reason_code,
                "occurred_at": e.occurred_at,
            }
            for e in events
        ],
    }


def _tx_for_mandate(db: Session, mandate_id: str, transaction_id: str, user: User) -> svc.Transaction:
    get_mandate_for_user_or_404(mandate_id, db, user)
    tx = svc.load_transaction(db, transaction_id)
    if tx.mandate_id != mandate_id:
        raise svc.OnsiteSignatureError(svc.TRANSACTION_NOT_FOUND, "Signaturvorgang nicht gefunden.", http_status=404)
    return tx


@router.get("/onsite-signature/policy")
def get_onsite_signature_policy(
    runtime: OnsiteSignatureRuntime = Depends(get_onsite_signature_runtime),
    current_user: User = Depends(get_current_user),
):
    view = runtime.policy.public_view()
    view["message"] = (
        "Vor-Ort-Signatur freigegeben." if view["released"] else
        "Vor-Ort-Signatur nicht freigegeben: Owner-/Legal-Freigabe der Policy fehlt."
    )
    view["qes_provider_configured"] = bool(runtime.qes_provider.configured)
    view["customer_channel"] = runtime.channel.name
    return view


@router.post("/mandates/{mandate_id}/documents/{doc_id}/onsite-signature", status_code=201)
def open_onsite_signature(
    mandate_id: str, doc_id: str, body: OpenRequest, request: Request = None,
    db: Session = Depends(get_db),
    runtime: OnsiteSignatureRuntime = Depends(get_onsite_signature_runtime),
    current_user: User = Depends(require_advisor),
):
    mandate = get_mandate_for_user_or_404(mandate_id, db, current_user)
    document = db.query(ContractDocument).filter(
        ContractDocument.id == doc_id,
        ContractDocument.mandate_id == mandate_id,
        ContractDocument.deleted_at.is_(None),
    ).first()
    if document is None:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
    svc.require_released(runtime.policy)
    _release_gates(db, mandate, document, current_user=current_user, request=request)
    tx = svc.open_transaction(
        db, policy=runtime.policy, time_source=runtime.time_source,
        qes_provider=runtime.qes_provider, advisor=_advisor(current_user), mandate=mandate,
        document=document, displayed_document_hash=body.displayed_document_hash,
        language=body.language, device_app_version=body.device_app_version,
    )
    return _view(db, tx.transaction_id)


@router.get("/mandates/{mandate_id}/onsite-signature/{transaction_id}")
def get_onsite_signature(
    mandate_id: str, transaction_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_advisor),
):
    _tx_for_mandate(db, mandate_id, transaction_id, current_user)
    return _view(db, transaction_id)


@router.post("/mandates/{mandate_id}/onsite-signature/{transaction_id}/identity-check")
def onsite_identity_check(
    mandate_id: str, transaction_id: str, body: IdentityCheckRequest,
    db: Session = Depends(get_db),
    runtime: OnsiteSignatureRuntime = Depends(get_onsite_signature_runtime),
    current_user: User = Depends(require_advisor),
):
    _tx_for_mandate(db, mandate_id, transaction_id, current_user)
    svc.record_identity_check(
        db, policy=runtime.policy, time_source=runtime.time_source,
        advisor=_advisor(current_user), transaction_id=transaction_id, method=body.method,
        result=body.result, id_document_kind=body.id_document_kind,
        id_document_country=body.id_document_country, id_document_valid=body.id_document_valid,
    )
    return _view(db, transaction_id)


@router.post("/mandates/{mandate_id}/onsite-signature/{transaction_id}/challenge")
def onsite_issue_challenge(
    mandate_id: str, transaction_id: str,
    db: Session = Depends(get_db),
    runtime: OnsiteSignatureRuntime = Depends(get_onsite_signature_runtime),
    current_user: User = Depends(require_advisor),
):
    """Sendet den Einmalcode an den Kundenkanal. Die Antwort enthaelt ihn nie."""
    _tx_for_mandate(db, mandate_id, transaction_id, current_user)
    return svc.issue_customer_challenge(
        db, policy=runtime.policy, time_source=runtime.time_source,
        channel=runtime.channel, advisor=_advisor(current_user), transaction_id=transaction_id,
    )


@router.post("/mandates/{mandate_id}/onsite-signature/{transaction_id}/witness")
def onsite_witness(
    mandate_id: str, transaction_id: str, body: WitnessRequest,
    db: Session = Depends(get_db),
    runtime: OnsiteSignatureRuntime = Depends(get_onsite_signature_runtime),
    current_user: User = Depends(require_advisor),
):
    _tx_for_mandate(db, mandate_id, transaction_id, current_user)
    svc.record_witness_statement(
        db, policy=runtime.policy, time_source=runtime.time_source,
        advisor=_advisor(current_user), transaction_id=transaction_id,
        statement_version=body.statement_version, statement_hash=body.statement_hash,
        confirmed=body.confirmed,
    )
    return _view(db, transaction_id)


@router.post("/mandates/{mandate_id}/onsite-signature/{transaction_id}/finalize")
def onsite_finalize(
    mandate_id: str, transaction_id: str, body: FinalizeRequest, request: Request = None,
    db: Session = Depends(get_db),
    runtime: OnsiteSignatureRuntime = Depends(get_onsite_signature_runtime),
    current_user: User = Depends(require_advisor),
):
    tx = _tx_for_mandate(db, mandate_id, transaction_id, current_user)
    svc.require_released(runtime.policy)
    document = db.query(ContractDocument).filter(ContractDocument.id == tx.document_id).first()
    if document is not None:
        def _close_open_transaction(reason_code: str) -> None:
            # H7 N-884-07: offener Vorgang wird mit dem Gate-Reason-Code
            # geschlossen (Ereigniskette); scheitert das (z.B. Zeitquelle),
            # bleibt die Sperre bestehen und der Audit-Eintrag steht.
            try:
                svc.abort_for_release_block(
                    db, policy=runtime.policy, time_source=runtime.time_source,
                    advisor=_advisor(current_user), transaction_id=transaction_id,
                    reason_code=reason_code,
                )
            except Exception:  # noqa: BLE001 -- Sperre bleibt, Audit steht
                db.rollback()

        _release_gates(
            db, get_mandate_for_user_or_404(mandate_id, db, current_user), document,
            current_user=current_user, request=request, on_blocked=_close_open_transaction,
        )
    svc.finalize_signature(
        db, policy=runtime.policy, time_source=runtime.time_source,
        qes_provider=runtime.qes_provider, advisor=_advisor(current_user),
        transaction_id=transaction_id, qes_receipt=body.qes_receipt,
    )
    return _view(db, transaction_id)


@router.post("/mandates/{mandate_id}/onsite-signature/{transaction_id}/deliver")
def onsite_deliver_copy(
    mandate_id: str, transaction_id: str,
    db: Session = Depends(get_db),
    runtime: OnsiteSignatureRuntime = Depends(get_onsite_signature_runtime),
    current_user: User = Depends(require_advisor),
):
    _tx_for_mandate(db, mandate_id, transaction_id, current_user)
    svc.deliver_customer_copy(
        db, policy=runtime.policy, time_source=runtime.time_source,
        channel=runtime.channel, advisor=_advisor(current_user), transaction_id=transaction_id,
    )
    return _view(db, transaction_id)


@router.post("/mandates/{mandate_id}/onsite-signature/{transaction_id}/abort")
def onsite_abort(
    mandate_id: str, transaction_id: str, body: AbortRequest,
    db: Session = Depends(get_db),
    runtime: OnsiteSignatureRuntime = Depends(get_onsite_signature_runtime),
    current_user: User = Depends(require_advisor),
):
    _tx_for_mandate(db, mandate_id, transaction_id, current_user)
    svc.abort_transaction(
        db, policy=runtime.policy, time_source=runtime.time_source,
        advisor=_advisor(current_user), transaction_id=transaction_id,
        reason_code=body.reason_code,
    )
    return _view(db, transaction_id)


@router.post("/client-portal/onsite-signature/{transaction_id}/confirm")
def client_confirm_onsite_signature(
    transaction_id: str, body: CustomerConfirmRequest,
    db: Session = Depends(get_db),
    runtime: OnsiteSignatureRuntime = Depends(get_onsite_signature_runtime),
    current_user: User = Depends(require_client),
):
    """Kundeneigener Faktor: der eingeloggte Kunde bestaetigt Code, angezeigten
    Dokument-Hash und Einwilligung auf seinem eigenen Geraet."""
    client = get_linked_client_for_user_or_404(current_user, db)
    actor = svc.CustomerActor(user_id=current_user.id, role=str(current_user.role), linked_client_id=client.id)
    # Fremde Vorgaenge sind fuer den Kunden unsichtbar (kein Leak, und ein
    # Fremder kann den Code des echten Kunden nicht verbrauchen).
    if svc.load_transaction(db, transaction_id).client_id != client.id:
        raise svc.OnsiteSignatureError(
            svc.TRANSACTION_NOT_FOUND, "Signaturvorgang nicht gefunden.", http_status=404,
        )
    tx = svc.verify_customer_factor(
        db, policy=runtime.policy, time_source=runtime.time_source, actor=actor,
        transaction_id=transaction_id, challenge_id=body.challenge_id, code=body.code,
        displayed_document_hash=body.displayed_document_hash,
        consent_text_hash=body.consent_text_hash,
    )
    return {"transaction_id": tx.transaction_id, "state": tx.state}
