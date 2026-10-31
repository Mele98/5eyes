"""Workflow der Vor-Ort-Signatur mit kundeneigenem Faktor (SIGN-001, Variante b).

Jeder Schritt prueft VOR jeder Schreiboperation:

1. Policy produktiv freigegeben (sonst ``ONSITE_SIGNATURE_NOT_RELEASED``);
2. verlaessliche, monotone Zeitquelle;
3. erlaubter Zustandsuebergang (``state_machine.TRANSITIONS``);
4. Rolle/Identitaet des Akteurs (Berater-Schritte nur durch den eroeffnenden,
   stark authentisierten Berater; der Kundenfaktor nur durch den Kunden
   selbst -- nie durch einen Berater).

Ein Uebergang ist genau eine neue Zeile in ``onsite_signature_events``
(``UNIQUE(transaction_id, sequence_no)``): parallele oder doppelte Requests
koennen nie beide gewinnen. SIGNED und das Evidence-Paket werden in derselben
DB-Transaktion geschrieben.

Bestehende Signaturpfade (``routers/review.py::sign_document``,
Risikoprofil-Signoff, Kundenportal) bleiben unberuehrt; wiederverwendet wird
das Archiv-Gate ``services.signature_artifact.assert_signable_artifact``.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Mapping

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.reason_codes import DomainError, ReasonCode
from models.mandates import Mandate
from models.onsite_signature import (
    OnsiteSignatureChallenge,
    OnsiteSignatureEvent,
    OnsiteSignatureEvidence,
)
from models.review import ContractDocument
from services.onsite_signature import state_machine as sm
from services.onsite_signature.policy import (
    CLASS_FORM_REQUIRED,
    QES_REQUIRED_CLASSES,
    OnsiteSignaturePolicy,
)

if TYPE_CHECKING:  # Provider-Protokolle nur fuer Annotationen (K-2: Fan-out-Ratsche)
    from services.onsite_signature.providers import (
        CustomerChannel,
        QesProvider,
        TimeReading,
        TimeSource,
    )

CHALLENGE_PURPOSE = "ONSITE_DOCUMENT_SIGNATURE"
SIGNER_ROLE_CLIENT = "client"
ROLE_CLIENT = "client"
IDENTITY_RESULT_VERIFIED = "verified"
ADVISOR_AUTH_PASSWORD_TOTP = "password+totp"
ABORT_REASONS = frozenset({
    ReasonCode.OFFLINE_ABORT.value, ReasonCode.CUSTOMER_DECLINED.value, ReasonCode.ADVISOR_CANCELLED.value,
})

# Reason-Codes (API-Vertrag, englisch wie die uebrigen reason_codes). Werte aus dem
# zentralen Katalog core.reason_codes.ReasonCode (K-2), als reine str 1:1 unveraendert.
NOT_RELEASED = ReasonCode.ONSITE_SIGNATURE_NOT_RELEASED.value
DOCUMENT_CLASS_UNCLASSIFIED = ReasonCode.DOCUMENT_CLASS_UNCLASSIFIED.value
FORM_REQUIRES_QES_OR_WET_INK = ReasonCode.FORM_REQUIRES_QES_OR_WET_INK.value
QES_REQUIRED_NOT_AVAILABLE = ReasonCode.QES_REQUIRED_NOT_AVAILABLE.value
QES_INVALID = ReasonCode.QES_INVALID.value
DOCUMENT_HASH_MISMATCH = ReasonCode.DOCUMENT_HASH_MISMATCH.value
DOCUMENT_CHANGED_AFTER_DISPLAY = ReasonCode.DOCUMENT_CHANGED_AFTER_DISPLAY.value
DOCUMENT_NOT_SIGNABLE = ReasonCode.DOCUMENT_NOT_SIGNABLE.value
DOCUMENT_CLASS_CHANGED = ReasonCode.DOCUMENT_CLASS_CHANGED.value
TIME_SOURCE_UNRELIABLE = ReasonCode.TIME_SOURCE_UNRELIABLE.value
TIME_NOT_MONOTONIC = ReasonCode.TIME_NOT_MONOTONIC.value
INVALID_STATE = ReasonCode.ONSITE_SIGNATURE_INVALID_STATE.value
CONCURRENT_TRANSITION = ReasonCode.ONSITE_SIGNATURE_CONCURRENT_TRANSITION.value
TRANSACTION_NOT_FOUND = ReasonCode.ONSITE_SIGNATURE_NOT_FOUND.value
ADVISOR_NOT_OWNER = ReasonCode.ADVISOR_NOT_TRANSACTION_OWNER.value
ADVISOR_STRONG_AUTH_REQUIRED = ReasonCode.ADVISOR_STRONG_AUTH_REQUIRED.value
ADVISOR_CANNOT_ENTER_CUSTOMER_FACTOR = ReasonCode.ADVISOR_CANNOT_ENTER_CUSTOMER_FACTOR.value
WRONG_CUSTOMER = ReasonCode.WRONG_CUSTOMER.value
CHALLENGE_UNKNOWN = ReasonCode.CHALLENGE_UNKNOWN.value
CHALLENGE_SUPERSEDED = ReasonCode.CHALLENGE_SUPERSEDED.value
CHALLENGE_ALREADY_USED = ReasonCode.CHALLENGE_ALREADY_USED.value
CHALLENGE_EXPIRED = ReasonCode.CHALLENGE_EXPIRED.value
CHALLENGE_BINDING_MISMATCH = ReasonCode.CHALLENGE_BINDING_MISMATCH.value
CHALLENGE_CODE_INVALID = ReasonCode.CHALLENGE_CODE_INVALID.value
CONSENT_MISMATCH = ReasonCode.CONSENT_MISMATCH.value
LANGUAGE_NOT_SUPPORTED = ReasonCode.LANGUAGE_NOT_SUPPORTED.value
IDENTITY_METHOD_NOT_ACCEPTED = ReasonCode.IDENTITY_METHOD_NOT_ACCEPTED.value
IDENTITY_CHECK_FAILED = ReasonCode.IDENTITY_CHECK_FAILED.value
WITNESS_STATEMENT_MISMATCH = ReasonCode.WITNESS_STATEMENT_MISMATCH.value
ABORT_REASON_INVALID = ReasonCode.ABORT_REASON_INVALID.value
DELIVERY_PROOF_MISSING = ReasonCode.DELIVERY_PROOF_MISSING.value
FOLLOWUP_BLOCKED_DELIVERY_PENDING = ReasonCode.FOLLOWUP_BLOCKED_DELIVERY_PENDING.value
INPUT_MISSING = ReasonCode.ONSITE_SIGNATURE_INPUT_MISSING.value


class OnsiteSignatureError(DomainError):
    """Fachlicher Block; ``http_status`` + ``reason_code`` fuer das API.

    K-2: Unterklasse von ``DomainError``. Konstruktor (``reason_code, message,
    *, http_status=409, details=None``) und ``as_detail()`` (``reason_code``,
    ``message``, ``channel``, optional ``details``) sind unveraendert; die
    HTTP-Abbildung macht der zentrale Handler (``core/error_handlers.py``)
    statt eines try/except in jedem Endpunkt.
    """

    channel = "onsite_signature"


@dataclass(frozen=True)
class AdvisorActor:
    user_id: str
    role: str
    totp_enabled: bool


@dataclass(frozen=True)
class CustomerActor:
    """Der handelnde Benutzer beim Kundenfaktor (``role`` aus users.role)."""

    user_id: str
    role: str
    linked_client_id: str | None


@dataclass(frozen=True)
class Transaction:
    transaction_id: str
    state: str
    sequence_no: int
    mandate_id: str
    client_id: str
    document_id: str
    document_hash: str
    advisor_id: str
    opened: Mapping[str, Any]
    last_event_hash: str
    last_occurred_at: str
    # PG-002: Mandant des Vorgangs (aus dem Mandat, nicht Teil der Hashes).
    tenant_id: str | None = None


# ── Hilfsfunktionen ───────────────────────────────────────────────────────────

def _canonical(data: Mapping[str, Any]) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _iso(instant: datetime) -> str:
    return instant.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _parse(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)


def require_released(policy: OnsiteSignaturePolicy) -> None:
    problems = policy.release_problems()
    if problems:
        raise OnsiteSignatureError(
            NOT_RELEASED,
            "Die Vor-Ort-Signatur ist nicht freigegeben (Owner-/Legal-Freigabe "
            "der Policy fehlt). Bitte den bestehenden Signaturweg verwenden.",
            details={"policy_version": policy.policy_version, "release_problems": problems},
        )


def _read_time(policy: OnsiteSignaturePolicy, time_source: TimeSource,
               not_before: str | None = None) -> TimeReading:
    reading = time_source.now()
    if (not reading.reliable or reading.source not in policy.accepted_time_sources
            or reading.instant.tzinfo is None):
        raise OnsiteSignatureError(
            TIME_SOURCE_UNRELIABLE,
            "Keine verlaessliche Zeitquelle verfuegbar -- Signaturschritt gesperrt.",
            details={"time_source": reading.source},
        )
    if not_before is not None and reading.instant < _parse(not_before):
        raise OnsiteSignatureError(
            TIME_NOT_MONOTONIC,
            "Die Zeitquelle liegt vor dem letzten Signaturereignis -- Schritt gesperrt.",
        )
    return reading


def _event_hash_material(row: Mapping[str, Any]) -> str:
    keys = (
        "transaction_id", "sequence_no", "event_type", "state", "mandate_id",
        "client_id", "document_id", "document_hash", "challenge_id", "reason_code",
        "payload_json", "actor_id", "actor_role", "occurred_at", "time_source",
        "previous_event_hash",
    )
    return _canonical({key: row.get(key) for key in keys})


def compute_event_hash(event: OnsiteSignatureEvent) -> str:
    return _sha256(_event_hash_material({c: getattr(event, c) for c in (
        "transaction_id", "sequence_no", "event_type", "state", "mandate_id",
        "client_id", "document_id", "document_hash", "challenge_id", "reason_code",
        "payload_json", "actor_id", "actor_role", "occurred_at", "time_source",
        "previous_event_hash",
    )}))


def _events(db: Session, transaction_id: str) -> list[OnsiteSignatureEvent]:
    return (
        db.query(OnsiteSignatureEvent)
        .filter(OnsiteSignatureEvent.transaction_id == transaction_id)
        .order_by(OnsiteSignatureEvent.sequence_no.asc())
        .all()
    )


def load_transaction(db: Session, transaction_id: str) -> Transaction:
    events = _events(db, transaction_id)
    if not events:
        raise OnsiteSignatureError(TRANSACTION_NOT_FOUND, "Signaturvorgang nicht gefunden.", http_status=404)
    first, last = events[0], events[-1]
    return Transaction(
        transaction_id=transaction_id,
        state=last.state,
        sequence_no=last.sequence_no,
        mandate_id=first.mandate_id,
        client_id=first.client_id,
        document_id=first.document_id,
        document_hash=first.document_hash,
        advisor_id=first.actor_id,
        opened=json.loads(first.payload_json),
        last_event_hash=last.event_hash,
        last_occurred_at=last.occurred_at,
        tenant_id=first.tenant_id,
    )


def _new_event(tx: Transaction | None, *, event_type: str, actor_id: str, actor_role: str,
               reading: TimeReading, payload: Mapping[str, Any], reason_code: str | None = None,
               challenge_id: str | None = None, base: Mapping[str, str] | None = None,
               ) -> OnsiteSignatureEvent:
    current = tx.state if tx else None
    target = sm.next_state(current, event_type)
    if target is None:
        raise OnsiteSignatureError(
            INVALID_STATE,
            f"Schritt {event_type} ist im Zustand {current} nicht erlaubt.",
            details={"state": current, "event_type": event_type},
        )
    ident = base or {
        "transaction_id": tx.transaction_id, "mandate_id": tx.mandate_id,
        "client_id": tx.client_id, "document_id": tx.document_id,
        "document_hash": tx.document_hash, "tenant_id": tx.tenant_id,
    }
    now = _iso(reading.instant)
    event = OnsiteSignatureEvent(
        id=str(uuid.uuid4()),
        schema_version="OnsiteSignatureEventV1",
        sequence_no=(tx.sequence_no + 1) if tx else 1,
        event_type=event_type,
        state=target,
        challenge_id=challenge_id,
        reason_code=reason_code,
        payload_json=_canonical(payload),
        actor_id=actor_id,
        actor_role=actor_role,
        occurred_at=now,
        time_source=reading.source,
        previous_event_hash=tx.last_event_hash if tx else None,
        created_at=now,
        **ident,
    )
    event.event_hash = compute_event_hash(event)
    return event


def _commit(db: Session, *rows: Any) -> None:
    for row in rows:
        db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise OnsiteSignatureError(
            CONCURRENT_TRANSITION,
            "Der Signaturvorgang wurde gleichzeitig veraendert -- Schritt nicht ausgefuehrt.",
        ) from exc


def _require_owner(tx: Transaction, advisor: AdvisorActor) -> None:
    if advisor.user_id != tx.advisor_id:
        raise OnsiteSignatureError(
            ADVISOR_NOT_OWNER, "Nur der eroeffnende Berater darf diesen Schritt ausfuehren.",
            http_status=403,
        )


def _require_strong_advisor(advisor: AdvisorActor) -> None:
    if advisor.role == ROLE_CLIENT or not advisor.totp_enabled:
        raise OnsiteSignatureError(
            ADVISOR_STRONG_AUTH_REQUIRED,
            "Vor-Ort-Signatur nur fuer Berater mit aktiver Zwei-Faktor-Anmeldung.",
            http_status=403,
        )


def _signable_hash(document: ContractDocument) -> str:
    from services.signature_artifact import assert_signable_artifact

    try:
        assert_signable_artifact(document)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        raise OnsiteSignatureError(
            DOCUMENT_NOT_SIGNABLE,
            str(detail.get("message") or "Dokument ist nicht signierbar."),
            details={"artifact_reason_code": detail.get("reason_code")},
        ) from exc
    return str(document.checksum_sha256).strip().lower()


def _document_class_or_block(policy: OnsiteSignaturePolicy, document_type: str,
                             qes_provider: QesProvider) -> str:
    document_class = policy.document_class(document_type)
    if document_class is None:
        raise OnsiteSignatureError(
            DOCUMENT_CLASS_UNCLASSIFIED,
            "Fuer diesen Dokumenttyp liegt keine genehmigte Klassifikation vor -- "
            "Vor-Ort-Signatur gesperrt.",
            details={"document_type": document_type},
        )
    if document_class in QES_REQUIRED_CLASSES and not qes_provider.configured:
        code = FORM_REQUIRES_QES_OR_WET_INK if document_class == CLASS_FORM_REQUIRED else QES_REQUIRED_NOT_AVAILABLE
        raise OnsiteSignatureError(
            code,
            "Dieser Dokumenttyp verlangt eine qualifizierte elektronische Signatur "
            "(oder eigenhaendige Unterschrift); es ist kein QES-Anbieter angebunden.",
            details={"document_type": document_type, "document_class": document_class},
        )
    return document_class


# ── Schritte ──────────────────────────────────────────────────────────────────

def open_transaction(
    db: Session, *, policy: OnsiteSignaturePolicy, time_source: TimeSource,
    qes_provider: QesProvider, advisor: AdvisorActor, mandate: Mandate,
    document: ContractDocument, displayed_document_hash: str, language: str,
    device_app_version: str, template_version: str | None = None,
) -> Transaction:
    require_released(policy)
    _require_strong_advisor(advisor)
    if document.mandate_id != mandate.id or document.deleted_at is not None:
        raise OnsiteSignatureError(TRANSACTION_NOT_FOUND, "Dokument nicht gefunden.", http_status=404)
    if not str(device_app_version or "").strip():
        raise OnsiteSignatureError(INPUT_MISSING, "Geraete-/App-Version fehlt.", http_status=422)
    if language not in policy.consent_texts:
        raise OnsiteSignatureError(
            LANGUAGE_NOT_SUPPORTED, "Fuer diese Sprache ist kein genehmigter Einwilligungstext hinterlegt.",
            http_status=422,
        )
    document_class = _document_class_or_block(policy, str(document.document_type or ""), qes_provider)
    current_hash = _signable_hash(document)
    if str(displayed_document_hash or "").strip().lower() != current_hash:
        raise OnsiteSignatureError(
            DOCUMENT_HASH_MISMATCH,
            "Der angezeigte Dokument-Hash entspricht nicht dem archivierten Dokument.",
        )
    reading = _read_time(policy, time_source)
    transaction_id = str(uuid.uuid4())
    consent = policy.consent_texts[language]
    payload = {
        "document_type": document.document_type,
        "document_version": int(document.version or 0),
        "document_content_hash": document.content_hash,
        "template_version": template_version,
        "document_class": document_class,
        "policy_version": policy.policy_version,
        "language": language,
        "consent_text_version": consent.version,
        "consent_text_hash": consent.text_hash,
        "device_app_version": str(device_app_version).strip(),
        "advisor_auth_method": ADVISOR_AUTH_PASSWORD_TOTP,
        "timezone": reading.timezone,
    }
    event = _new_event(
        None, event_type=sm.EV_OPENED, actor_id=advisor.user_id, actor_role=advisor.role,
        reading=reading, payload=payload,
        base={
            "transaction_id": transaction_id, "mandate_id": mandate.id,
            "client_id": mandate.client_id, "document_id": document.id,
            "document_hash": current_hash, "tenant_id": mandate.tenant_id,
        },
    )
    _commit(db, event)
    return load_transaction(db, transaction_id)


def record_identity_check(
    db: Session, *, policy: OnsiteSignaturePolicy, time_source: TimeSource,
    advisor: AdvisorActor, transaction_id: str, method: str, result: str,
    id_document_kind: str, id_document_country: str, id_document_valid: bool,
) -> Transaction:
    require_released(policy)
    _require_strong_advisor(advisor)
    tx = load_transaction(db, transaction_id)
    _require_owner(tx, advisor)
    if method not in policy.accepted_identity_check_methods:
        raise OnsiteSignatureError(
            IDENTITY_METHOD_NOT_ACCEPTED, "Diese Identifikationsmethode ist nicht genehmigt.",
            http_status=422,
        )
    if not str(id_document_kind or "").strip() or not str(id_document_country or "").strip():
        raise OnsiteSignatureError(INPUT_MISSING, "Ausweisart und Ausstellerstaat fehlen.", http_status=422)
    reading = _read_time(policy, time_source, tx.last_occurred_at)
    payload = {
        "method": method,
        "result": result,
        "id_document_kind": str(id_document_kind).strip(),
        "id_document_country": str(id_document_country).strip().upper(),
        "id_document_valid": bool(id_document_valid),
    }
    if result != IDENTITY_RESULT_VERIFIED or not id_document_valid:
        _commit(db, _new_event(
            tx, event_type=sm.EV_ABORTED, actor_id=advisor.user_id, actor_role=advisor.role,
            reading=reading, payload=payload, reason_code=IDENTITY_CHECK_FAILED,
        ))
        raise OnsiteSignatureError(
            IDENTITY_CHECK_FAILED, "Identitaetspruefung nicht bestanden -- Vorgang abgebrochen.",
        )
    _commit(db, _new_event(
        tx, event_type=sm.EV_IDENTITY_VERIFIED, actor_id=advisor.user_id,
        actor_role=advisor.role, reading=reading, payload=payload,
    ))
    return load_transaction(db, transaction_id)


def challenge_binding_hash(*, document_hash: str, transaction_id: str, customer_id: str,
                           purpose: str, nonce: str, expires_at: str, mandate_id: str,
                           consent_text_hash: str, policy_version: str) -> str:
    return _sha256(_canonical({
        "document_hash": document_hash,
        "transaction_id": transaction_id,
        "customer_id": customer_id,
        "purpose": purpose,
        "nonce": nonce,
        "expires_at": expires_at,
        "mandate_id": mandate_id,
        "consent_text_hash": consent_text_hash,
        "policy_version": policy_version,
    }))


def _code_hmac(salt: str, binding_hash: str, code: str) -> str:
    return hmac.new(bytes.fromhex(salt), f"{binding_hash}:{code}".encode("utf-8"), hashlib.sha256).hexdigest()


def issue_customer_challenge(
    db: Session, *, policy: OnsiteSignaturePolicy, time_source: TimeSource,
    channel: CustomerChannel, advisor: AdvisorActor, transaction_id: str,
) -> dict[str, Any]:
    """Erzeugt und versendet den dokumentgebundenen Einmalcode.

    Die Rueckgabe enthaelt den Code NICHT -- er existiert nur im Kanal.
    """
    require_released(policy)
    _require_strong_advisor(advisor)
    tx = load_transaction(db, transaction_id)
    _require_owner(tx, advisor)
    if sm.next_state(tx.state, sm.EV_CHALLENGE_ISSUED) is None:
        raise OnsiteSignatureError(INVALID_STATE, f"Challenge im Zustand {tx.state} nicht erlaubt.")
    reading = _read_time(policy, time_source, tx.last_occurred_at)
    issued_at = _iso(reading.instant)
    expires_at = _iso(reading.instant + timedelta(seconds=int(policy.challenge_ttl_seconds)))
    nonce = secrets.token_hex(16)
    salt = secrets.token_hex(16)
    code = "".join(secrets.choice("0123456789") for _ in range(int(policy.code_digits)))
    binding = challenge_binding_hash(
        document_hash=tx.document_hash, transaction_id=tx.transaction_id,
        customer_id=tx.client_id, purpose=CHALLENGE_PURPOSE, nonce=nonce,
        expires_at=expires_at, mandate_id=tx.mandate_id,
        consent_text_hash=tx.opened["consent_text_hash"], policy_version=policy.policy_version,
    )
    challenge = OnsiteSignatureChallenge(
        id=str(uuid.uuid4()), schema_version="OnsiteSignatureChallengeV1", tenant_id=tx.tenant_id,
        transaction_id=tx.transaction_id, mandate_id=tx.mandate_id, client_id=tx.client_id,
        document_hash=tx.document_hash, purpose=CHALLENGE_PURPOSE, nonce=nonce,
        issued_at=issued_at, expires_at=expires_at, delivery_channel=channel.name,
        code_salt=salt, code_hmac=_code_hmac(salt, binding, code), binding_hash=binding,
        policy_version=policy.policy_version, actor_id=advisor.user_id, created_at=issued_at,
    )
    result = channel.send_challenge_code(
        client_id=tx.client_id, transaction_id=tx.transaction_id, challenge_id=challenge.id,
        code=code, document_hash=tx.document_hash, expires_at=expires_at,
    )
    del code
    delivered = bool(result.delivered and result.reference)
    event = _new_event(
        tx,
        event_type=sm.EV_CHALLENGE_ISSUED if delivered else sm.EV_CHALLENGE_DELIVERY_FAILED,
        actor_id=advisor.user_id, actor_role=advisor.role, reading=reading,
        payload={"channel": result.channel, "delivery_reference": result.reference,
                 "expires_at": expires_at, "binding_hash": binding},
        reason_code=None if delivered else (result.reason_code or DELIVERY_PROOF_MISSING),
        challenge_id=challenge.id,
    )
    _commit(db, challenge, event)
    if not delivered:
        raise OnsiteSignatureError(
            event.reason_code,
            "Der Einmalcode konnte nicht an den Kunden zugestellt werden.",
        )
    return {
        "transaction_id": tx.transaction_id,
        "challenge_id": challenge.id,
        "expires_at": expires_at,
        "channel": result.channel,
        "binding_hash": binding,
    }


def _reject_factor(db: Session, tx: Transaction, reading: TimeReading, actor: CustomerActor,
                   challenge_id: str, reason_code: str, message: str, http_status: int = 409) -> None:
    """Verbraucht die Challenge (einmalig) und blockiert."""
    _commit(db, _new_event(
        tx, event_type=sm.EV_FACTOR_REJECTED, actor_id=actor.user_id, actor_role=actor.role,
        reading=reading, payload={"reason": reason_code}, reason_code=reason_code,
        challenge_id=challenge_id,
    ))
    raise OnsiteSignatureError(reason_code, message, http_status=http_status)


def verify_customer_factor(
    db: Session, *, policy: OnsiteSignaturePolicy, time_source: TimeSource,
    actor: CustomerActor, transaction_id: str, challenge_id: str, code: str,
    displayed_document_hash: str, consent_text_hash: str,
) -> Transaction:
    """Kunde bestaetigt auf dem eigenen Kanal: Code + Dokument-Hash + Einwilligung.

    Jeder Fehlversuch mit einer bekannten Challenge verbraucht sie (einmalig).
    """
    require_released(policy)
    tx = load_transaction(db, transaction_id)
    challenge = (
        db.query(OnsiteSignatureChallenge)
        .filter(OnsiteSignatureChallenge.id == challenge_id,
                OnsiteSignatureChallenge.transaction_id == tx.transaction_id)
        .first()
    )
    if challenge is None:
        raise OnsiteSignatureError(CHALLENGE_UNKNOWN, "Unbekannte Challenge.", http_status=404)
    used = (
        db.query(OnsiteSignatureEvent.id)
        .filter(OnsiteSignatureEvent.challenge_id == challenge.id,
                OnsiteSignatureEvent.event_type.in_((sm.EV_FACTOR_VERIFIED, sm.EV_FACTOR_REJECTED)))
        .first()
    )
    if used is not None:
        raise OnsiteSignatureError(CHALLENGE_ALREADY_USED, "Dieser Code wurde bereits verwendet.")
    if tx.state != sm.CHALLENGE_ISSUED:
        raise OnsiteSignatureError(INVALID_STATE, f"Kundenfaktor im Zustand {tx.state} nicht erlaubt.")
    reading = _read_time(policy, time_source, tx.last_occurred_at)

    if actor.role != ROLE_CLIENT:
        _reject_factor(db, tx, reading, actor, challenge.id, ADVISOR_CANNOT_ENTER_CUSTOMER_FACTOR,
                       "Der Kundenfaktor darf nur vom Kunden selbst bestaetigt werden. "
                       "Der Code ist verbraucht.", http_status=403)
    if actor.linked_client_id != tx.client_id:
        _reject_factor(db, tx, reading, actor, challenge.id, WRONG_CUSTOMER,
                       "Der angemeldete Kunde ist nicht der Unterzeichner dieses Dokuments.",
                       http_status=403)
    latest = (
        db.query(OnsiteSignatureChallenge)
        .filter(OnsiteSignatureChallenge.transaction_id == tx.transaction_id)
        .order_by(OnsiteSignatureChallenge.issued_at.desc(), OnsiteSignatureChallenge.created_at.desc())
        .first()
    )
    if latest is None or latest.id != challenge.id:
        _reject_factor(db, tx, reading, actor, challenge.id, CHALLENGE_SUPERSEDED,
                       "Es gilt nur der zuletzt versandte Code.")
    if reading.instant > _parse(challenge.expires_at):
        _reject_factor(db, tx, reading, actor, challenge.id, CHALLENGE_EXPIRED,
                       "Der Code ist abgelaufen -- bitte einen neuen anfordern.")
    expected_binding = challenge_binding_hash(
        document_hash=tx.document_hash, transaction_id=tx.transaction_id,
        customer_id=tx.client_id, purpose=CHALLENGE_PURPOSE, nonce=challenge.nonce,
        expires_at=challenge.expires_at, mandate_id=tx.mandate_id,
        consent_text_hash=tx.opened["consent_text_hash"], policy_version=challenge.policy_version,
    )
    if (not hmac.compare_digest(expected_binding, challenge.binding_hash)
            or challenge.document_hash != tx.document_hash
            or challenge.client_id != tx.client_id
            or challenge.purpose != CHALLENGE_PURPOSE):
        _reject_factor(db, tx, reading, actor, challenge.id, CHALLENGE_BINDING_MISMATCH,
                       "Der Code ist nicht an dieses Dokument gebunden.")
    if str(displayed_document_hash or "").strip().lower() != tx.document_hash:
        _reject_factor(db, tx, reading, actor, challenge.id, DOCUMENT_HASH_MISMATCH,
                       "Der beim Kunden angezeigte Dokument-Hash weicht ab.")
    if not hmac.compare_digest(str(consent_text_hash or ""), tx.opened["consent_text_hash"]):
        _reject_factor(db, tx, reading, actor, challenge.id, CONSENT_MISMATCH,
                       "Die bestaetigte Einwilligung entspricht nicht dem genehmigten Text.")
    if not hmac.compare_digest(_code_hmac(challenge.code_salt, challenge.binding_hash, str(code or "")),
                               challenge.code_hmac):
        _reject_factor(db, tx, reading, actor, challenge.id, CHALLENGE_CODE_INVALID,
                       "Der Code ist ungueltig. Der Code ist verbraucht.")
    _commit(db, _new_event(
        tx, event_type=sm.EV_FACTOR_VERIFIED, actor_id=actor.user_id, actor_role=actor.role,
        reading=reading, challenge_id=challenge.id,
        payload={"factor_kind": policy.factor_kind, "binding_hash": challenge.binding_hash,
                 "channel": challenge.delivery_channel,
                 "consent_text_hash": tx.opened["consent_text_hash"]},
    ))
    return load_transaction(db, transaction_id)


def record_witness_statement(
    db: Session, *, policy: OnsiteSignaturePolicy, time_source: TimeSource,
    advisor: AdvisorActor, transaction_id: str, statement_version: str,
    statement_hash: str, confirmed: bool,
) -> Transaction:
    """Getrennte Zeugenerklaerung des Beraters (genehmigter Text, kein Freitext)."""
    require_released(policy)
    _require_strong_advisor(advisor)
    tx = load_transaction(db, transaction_id)
    _require_owner(tx, advisor)
    witness = policy.witness_statement
    if (not confirmed or witness is None or statement_version != witness.version
            or not hmac.compare_digest(str(statement_hash or ""), witness.text_hash)):
        raise OnsiteSignatureError(
            WITNESS_STATEMENT_MISMATCH,
            "Die Zeugenerklaerung muss dem genehmigten Text entsprechen und bestaetigt sein.",
            http_status=422,
        )
    if sm.next_state(tx.state, sm.EV_WITNESSED) is None:
        raise OnsiteSignatureError(INVALID_STATE, f"Zeugenerklaerung im Zustand {tx.state} nicht erlaubt.")
    reading = _read_time(policy, time_source, tx.last_occurred_at)
    _commit(db, _new_event(
        tx, event_type=sm.EV_WITNESSED, actor_id=advisor.user_id, actor_role=advisor.role,
        reading=reading,
        payload={"witness_statement_version": witness.version, "witness_statement_hash": witness.text_hash},
    ))
    return load_transaction(db, transaction_id)


def _last_event_of(db: Session, transaction_id: str, event_type: str) -> OnsiteSignatureEvent | None:
    return (
        db.query(OnsiteSignatureEvent)
        .filter(OnsiteSignatureEvent.transaction_id == transaction_id,
                OnsiteSignatureEvent.event_type == event_type)
        .order_by(OnsiteSignatureEvent.sequence_no.desc())
        .first()
    )


EVIDENCE_HASH_FIELDS = (
    "transaction_id", "mandate_id", "client_id", "document_id", "document_type",
    "document_version", "document_content_hash", "template_version", "document_class",
    "policy_version", "language", "displayed_document_hash", "final_document_hash",
    "signer_role", "consent_text_version", "consent_text_hash", "signed_at", "time_source",
    "timezone", "identity_check_result", "identity_check_method", "id_document_kind",
    "id_document_country", "id_document_valid", "customer_factor_kind",
    "customer_factor_challenge_id", "customer_factor_binding_hash", "customer_factor_channel",
    "customer_factor_verified_at", "customer_factor_actor_id", "advisor_id",
    "advisor_auth_method", "witness_statement_version", "witness_statement_hash",
    "device_app_version", "qes_provider", "qes_receipt_hash", "qes_certificate_chain_hash",
    "qes_timestamp", "qes_validation_result", "signed_event_hash",
)


def compute_evidence_hash(evidence: OnsiteSignatureEvidence) -> str:
    return _sha256(_canonical({name: getattr(evidence, name) for name in EVIDENCE_HASH_FIELDS}))


def finalize_signature(
    db: Session, *, policy: OnsiteSignaturePolicy, time_source: TimeSource,
    qes_provider: QesProvider, advisor: AdvisorActor, transaction_id: str,
    qes_receipt: Mapping[str, Any] | None = None,
) -> OnsiteSignatureEvidence:
    """SIGNED + Evidence-Paket atomar. Angezeigter Hash == finaler Hash, sonst Abbruch."""
    require_released(policy)
    _require_strong_advisor(advisor)
    tx = load_transaction(db, transaction_id)
    _require_owner(tx, advisor)
    if tx.state != sm.WITNESSED:
        raise OnsiteSignatureError(INVALID_STATE, f"Signatur im Zustand {tx.state} nicht erlaubt.")
    reading = _read_time(policy, time_source, tx.last_occurred_at)
    document = db.query(ContractDocument).filter(ContractDocument.id == tx.document_id).first()
    final_hash = None
    if document is not None and document.deleted_at is None:
        try:
            final_hash = _signable_hash(document)
        except OnsiteSignatureError:
            final_hash = None
    if final_hash != tx.document_hash:
        _commit(db, _new_event(
            tx, event_type=sm.EV_ABORTED, actor_id=advisor.user_id, actor_role=advisor.role,
            reading=reading, payload={"final_document_hash": final_hash},
            reason_code=DOCUMENT_CHANGED_AFTER_DISPLAY,
        ))
        raise OnsiteSignatureError(
            DOCUMENT_CHANGED_AFTER_DISPLAY,
            "Das Dokument wurde nach der Anzeige veraendert -- Signatur blockiert, "
            "Vorgang abgebrochen.",
        )
    document_class = _document_class_or_block(policy, str(document.document_type or ""), qes_provider)
    if document_class != tx.opened["document_class"]:
        raise OnsiteSignatureError(
            DOCUMENT_CLASS_CHANGED, "Die Dokumentklassifikation hat sich seit Eroeffnung geaendert.",
        )
    qes = None
    if document_class in QES_REQUIRED_CLASSES:
        qes = qes_provider.verify_receipt(
            qes_receipt, document_hash=final_hash, customer_id=tx.client_id,
            transaction_id=tx.transaction_id,
        )
        if not qes.valid:
            raise OnsiteSignatureError(
                QES_INVALID, "Die qualifizierte elektronische Signatur ist ungueltig.",
                details={"provider": qes.provider, "provider_reason": qes.reason_code},
            )
    identity = _last_event_of(db, tx.transaction_id, sm.EV_IDENTITY_VERIFIED)
    factor = _last_event_of(db, tx.transaction_id, sm.EV_FACTOR_VERIFIED)
    witness = _last_event_of(db, tx.transaction_id, sm.EV_WITNESSED)
    if identity is None or factor is None or witness is None:
        raise OnsiteSignatureError(INVALID_STATE, "Evidence unvollstaendig -- Signatur blockiert.")
    identity_payload = json.loads(identity.payload_json)
    factor_payload = json.loads(factor.payload_json)
    witness_payload = json.loads(witness.payload_json)
    signed_event = _new_event(
        tx, event_type=sm.EV_SIGNED, actor_id=advisor.user_id, actor_role=advisor.role,
        reading=reading, payload={"final_document_hash": final_hash, "document_class": document_class},
    )
    opened = tx.opened
    evidence = OnsiteSignatureEvidence(
        id=str(uuid.uuid4()), schema_version="OnsiteSignatureEvidenceV1", tenant_id=tx.tenant_id,
        transaction_id=tx.transaction_id, mandate_id=tx.mandate_id, client_id=tx.client_id,
        document_id=tx.document_id, document_type=opened["document_type"],
        document_version=int(opened["document_version"]),
        document_content_hash=str(opened["document_content_hash"] or ""),
        template_version=opened.get("template_version"), document_class=document_class,
        policy_version=opened["policy_version"], language=opened["language"],
        displayed_document_hash=tx.document_hash, final_document_hash=final_hash,
        signer_role=SIGNER_ROLE_CLIENT, consent_text_version=opened["consent_text_version"],
        consent_text_hash=opened["consent_text_hash"], signed_at=signed_event.occurred_at,
        time_source=reading.source, timezone=reading.timezone,
        identity_check_result=identity_payload["result"],
        identity_check_method=identity_payload["method"],
        id_document_kind=identity_payload["id_document_kind"],
        id_document_country=identity_payload["id_document_country"],
        id_document_valid=1 if identity_payload["id_document_valid"] else 0,
        customer_factor_kind=factor_payload["factor_kind"],
        customer_factor_challenge_id=factor.challenge_id,
        customer_factor_binding_hash=factor_payload["binding_hash"],
        customer_factor_channel=factor_payload["channel"],
        customer_factor_verified_at=factor.occurred_at,
        customer_factor_actor_id=factor.actor_id,
        advisor_id=tx.advisor_id, advisor_auth_method=opened["advisor_auth_method"],
        witness_statement_version=witness_payload["witness_statement_version"],
        witness_statement_hash=witness_payload["witness_statement_hash"],
        device_app_version=opened["device_app_version"],
        qes_provider=qes.provider if qes else None,
        qes_receipt_hash=qes.receipt_hash if qes else None,
        qes_certificate_chain_hash=qes.certificate_chain_hash if qes else None,
        qes_timestamp=qes.qualified_timestamp if qes else None,
        qes_validation_result=qes.validation_result if qes else None,
        signed_event_hash=signed_event.event_hash, created_at=signed_event.occurred_at,
    )
    evidence.evidence_hash = compute_evidence_hash(evidence)
    _commit(db, signed_event, evidence)
    return evidence


def deliver_customer_copy(
    db: Session, *, policy: OnsiteSignaturePolicy, time_source: TimeSource,
    channel: CustomerChannel, advisor: AdvisorActor, transaction_id: str,
) -> Transaction:
    """SIGNED -> DELIVERY_PENDING -> DELIVERED (nur mit Zustellnachweis).

    Ein Fehlschlag bleibt in DELIVERY_PENDING (erneut versuchen oder einen
    dokumentierten Ersatzkanal als ``channel`` verwenden).
    """
    require_released(policy)
    _require_strong_advisor(advisor)
    tx = load_transaction(db, transaction_id)
    _require_owner(tx, advisor)
    if tx.state not in (sm.SIGNED, sm.DELIVERY_PENDING):
        raise OnsiteSignatureError(INVALID_STATE, f"Zustellung im Zustand {tx.state} nicht erlaubt.")
    reading = _read_time(policy, time_source, tx.last_occurred_at)
    if tx.state == sm.SIGNED:
        _commit(db, _new_event(
            tx, event_type=sm.EV_DELIVERY_REQUESTED, actor_id=advisor.user_id,
            actor_role=advisor.role, reading=reading, payload={"channel": channel.name},
        ))
        tx = load_transaction(db, transaction_id)
    evidence = (
        db.query(OnsiteSignatureEvidence)
        .filter(OnsiteSignatureEvidence.transaction_id == tx.transaction_id)
        .first()
    )
    result = channel.send_signed_copy(
        client_id=tx.client_id, transaction_id=tx.transaction_id, document_id=tx.document_id,
        document_hash=tx.document_hash, evidence_hash=evidence.evidence_hash if evidence else "",
    )
    delivered = bool(result.delivered and result.reference and evidence is not None)
    payload = {"channel": result.channel, "delivery_reference": result.reference}
    if delivered:
        _commit(db, _new_event(
            tx, event_type=sm.EV_DELIVERED, actor_id=advisor.user_id, actor_role=advisor.role,
            reading=reading, payload=payload,
        ))
        return load_transaction(db, transaction_id)
    reason = result.reason_code or DELIVERY_PROOF_MISSING
    _commit(db, _new_event(
        tx, event_type=sm.EV_DELIVERY_FAILED, actor_id=advisor.user_id, actor_role=advisor.role,
        reading=reading, payload=payload, reason_code=reason,
    ))
    raise OnsiteSignatureError(
        reason, "Die Kundenkopie konnte nicht zugestellt werden -- Folgeprozess bleibt gesperrt.",
    )


def abort_transaction(
    db: Session, *, policy: OnsiteSignaturePolicy, time_source: TimeSource,
    advisor: AdvisorActor, transaction_id: str, reason_code: str,
) -> Transaction:
    """Abbruch vor der Signatur (z. B. Verbindungsabbruch, Kunde lehnt ab).

    Bewusst ohne Freigabe-Gate: ein offener Vorgang muss sich immer schliessen
    lassen. Die Zeit muss trotzdem verlaesslich sein (Evidence).
    """
    if reason_code not in ABORT_REASONS:
        raise OnsiteSignatureError(ABORT_REASON_INVALID, "Unbekannter Abbruchgrund.", http_status=422)
    tx = load_transaction(db, transaction_id)
    _require_owner(tx, advisor)
    if sm.next_state(tx.state, sm.EV_ABORTED) is None:
        raise OnsiteSignatureError(INVALID_STATE, f"Abbruch im Zustand {tx.state} nicht erlaubt.")
    reading = _read_time(policy, time_source, tx.last_occurred_at)
    _commit(db, _new_event(
        tx, event_type=sm.EV_ABORTED, actor_id=advisor.user_id, actor_role=advisor.role,
        reading=reading, payload={}, reason_code=reason_code,
    ))
    return load_transaction(db, transaction_id)


def assert_followup_allowed(db: Session, document_id: str) -> None:
    """Folgeprozesse eines Dokuments sperren, solange eine Vor-Ort-Signatur
    signiert, die Kundenkopie aber nicht nachweislich zugestellt ist."""
    transaction_ids = {
        row[0] for row in db.query(OnsiteSignatureEvent.transaction_id)
        .filter(OnsiteSignatureEvent.document_id == document_id).all()
    }
    for transaction_id in sorted(transaction_ids):
        tx = load_transaction(db, transaction_id)
        if tx.state in sm.FOLLOWUP_BLOCKING_STATES:
            raise OnsiteSignatureError(
                FOLLOWUP_BLOCKED_DELIVERY_PENDING,
                "Die Kundenkopie der Vor-Ort-Signatur ist noch nicht zugestellt -- "
                "Folgeprozess gesperrt.",
                details={"transaction_id": transaction_id, "state": tx.state},
            )


def verify_event_chain(db: Session, transaction_id: str) -> list[str]:
    """Leere Liste = Ereigniskette lueckenlos und unveraendert."""
    problems: list[str] = []
    previous_hash = None
    for expected_seq, event in enumerate(_events(db, transaction_id), start=1):
        if event.sequence_no != expected_seq:
            problems.append(f"sequence_gap:{expected_seq}")
        if event.previous_event_hash != previous_hash:
            problems.append(f"chain_break:{event.sequence_no}")
        if compute_event_hash(event) != event.event_hash:
            problems.append(f"event_hash_mismatch:{event.sequence_no}")
        previous_hash = event.event_hash
    return problems
