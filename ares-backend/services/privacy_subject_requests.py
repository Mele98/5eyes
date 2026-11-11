"""H10 C-DSG-02: Betroffenenanfragen (Auskunft, Herausgabe, Berichtigung,
Loeschung) als nachvollziehbarer Fall.

Ablauf und Gates (fail-closed):

1. Eingang (``RECEIVED``): Kunde des Mandanten, Art, Eingangszeitpunkt (nicht
   in der Zukunft), Kanal. Faelligkeit = Eingangsdatum + 30 Kalendertage
   (technische Umsetzung der 30-Tage-Frist der DSV fuer die Auskunft; fuer
   die anderen Anfragearten wird dieselbe Frist als interne Ziellinie
   gefuehrt). Verlaengerung nur mit Begruendung und Mitteilung.
2. Identitaetspruefung: Methode + Nachweis-Referenz; ohne ``VERIFIED`` gibt es
   weder Entscheid (ausser Ablehnung) noch Export noch Zustellung.
3. Entscheid: ``FULFILL``, ``RESTRICT`` (eingeschraenkte Auskunft: Sektionen +
   Begruendung) oder ``REFUSE`` (Begruendung).
4. Auskunft/Herausgabe: Export nur ueber den Fall, mit den Angaben zur
   Bearbeitung aus dem Bearbeitungsverzeichnis. Offene Pflicht-Owner-Felder
   sperren den Export (kundenwirksame Ausgabe). Berichtigung/Loeschung: Nachweis
   der Umsetzung (Notiz bzw. ausgefuehrter Loeschvorgang desselben Kunden).
5. Zustellnachweis (``COMPLETED``): Zeitpunkt, Kanal, Referenz; frist-
   gerecht ja/nein wird festgehalten.

Rollen: Administration oder benannte Legal-/Datenschutzperson
(``privacy_role_designations``). Mandantentrennung ueber ``tenant_id``.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from core.reason_codes import DomainError, ReasonCode
from database import new_uuid
from models.privacy import PrivacyErasureCase, PrivacySubjectRequest
from services import data_export
from services import privacy_owner_values as owner_values_module
from services import processing_activity_register as register_module

REQUEST_TYPES = ("ACCESS", "PORTABILITY", "RECTIFICATION", "ERASURE")
EXPORT_REQUEST_TYPES = ("ACCESS", "PORTABILITY")
CHANNELS = ("EMAIL", "LETTER", "IN_PERSON", "PORTAL", "OTHER")
RELATIONS = ("SELF", "REPRESENTATIVE")
IDENTITY_METHODS = (
    "ID_DOCUMENT_IN_PERSON", "KNOWN_PERSON_IN_PERSON", "CERTIFIED_COPY", "VIDEO_IDENTIFICATION", "OTHER",
)
DECISIONS = ("FULFILL", "RESTRICT", "REFUSE")
CLOSED_STATUSES = ("COMPLETED", "WITHDRAWN")
DEADLINE_DAYS = 30
EXPORT_KIND = "PrivacySubjectRequestExportV1"

# Sektionen des Kundendatenexports (services/data_export.py); ein Test haelt
# die Liste deckungsgleich mit dem echten Export.
EXPORT_SECTIONS = (
    "client", "client_nationalities", "client_opt_history", "client_knowledge", "mandates",
    "risk_assessments", "risk_assessment_answers", "suitability_checks", "target_allocations",
    "recommendation_runs", "recommendation_positions", "recommendation_holdings", "advisory_log",
    "wealth_positions", "cashflows", "wealth_inflows", "goals", "planning_assumptions",
    "contract_documents", "conflict_of_interest_disclosure", "mandate_report_notes", "review_trigger",
    "strategy_snapshots", "protocol_baustein_selections", "audit_log",
)
EXECUTED_ERASURE_STATUSES = ("EXECUTED", "PARTIALLY_EXECUTED")


def _utc(now: datetime | None) -> datetime:
    value = now or datetime.now(timezone.utc)
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _parse_moment(value: str | None, field: str) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise DomainError(ReasonCode.SUBJECT_REQUEST_INPUT_INVALID, f"{field} fehlt", http_status=422)
    try:
        if len(raw) == 10:
            parsed = datetime.combine(date.fromisoformat(raw), datetime.min.time())
        else:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DomainError(
            ReasonCode.SUBJECT_REQUEST_INPUT_INVALID, f"{field} ist kein gueltiges Datum", http_status=422,
        ) from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _not_future(moment: datetime, field: str, now: datetime) -> None:
    if moment > now + timedelta(minutes=5):
        raise DomainError(ReasonCode.SUBJECT_REQUEST_INPUT_INVALID, f"{field} liegt in der Zukunft", http_status=422)


def _choice(value: str | None, allowed: tuple[str, ...], field: str) -> str:
    if value not in allowed:
        raise DomainError(
            ReasonCode.SUBJECT_REQUEST_INPUT_INVALID, f"{field} muss einer der Werte {allowed} sein", http_status=422,
        )
    return str(value)


def _text(value: str | None, field: str, *, required: bool) -> str | None:
    cleaned = str(value or "").strip()
    if required and not cleaned:
        raise DomainError(ReasonCode.SUBJECT_REQUEST_INPUT_INVALID, f"{field} ist Pflicht", http_status=422)
    return cleaned or None


def effective_due_date(case: PrivacySubjectRequest) -> date:
    return date.fromisoformat(case.extended_due_at or case.due_at)


def case_out(case: PrivacySubjectRequest, *, now: datetime | None = None) -> dict[str, Any]:
    today = _utc(now).date()
    due = effective_due_date(case)
    closed = case.status in CLOSED_STATUSES
    delivered_on = date.fromisoformat(case.delivered_at[:10]) if case.delivered_at else None
    return {
        "id": case.id, "client_id": case.client_id, "request_type": case.request_type, "status": case.status,
        "received_at": case.received_at, "received_channel": case.received_channel,
        "requester_relation": case.requester_relation, "request_summary": case.request_summary,
        "due_at": case.due_at, "extended_due_at": case.extended_due_at,
        "extension_reason": case.extension_reason, "extension_notified_at": case.extension_notified_at,
        "effective_due_at": due.isoformat(),
        "days_remaining": None if closed else (due - today).days,
        "overdue": (not closed) and today > due,
        "delivered_on_time": None if delivered_on is None else delivered_on <= due,
        "identity_verified_at": case.identity_verified_at, "identity_verified_by": case.identity_verified_by,
        "identity_method": case.identity_method, "identity_evidence_reference": case.identity_evidence_reference,
        "identity_failure_reason": case.identity_failure_reason,
        "decision": case.decision, "decision_reason": case.decision_reason,
        "decision_scope": json.loads(case.decision_scope_json) if case.decision_scope_json else [],
        "decided_by": case.decided_by, "decided_at": case.decided_at,
        "completion_note": case.completion_note, "linked_erasure_case_id": case.linked_erasure_case_id,
        "action_completed_at": case.action_completed_at,
        "export_sha256": case.export_sha256, "exported_at": case.exported_at, "exported_by": case.exported_by,
        "delivered_at": case.delivered_at, "delivery_channel": case.delivery_channel,
        "delivery_reference": case.delivery_reference, "delivered_by": case.delivered_by,
        "withdrawn_at": case.withdrawn_at, "withdrawn_reason": case.withdrawn_reason,
        "opened_by": case.opened_by, "created_at": case.created_at, "updated_at": case.updated_at,
    }


def _require_open(case: PrivacySubjectRequest) -> None:
    if case.status in CLOSED_STATUSES:
        raise DomainError(
            ReasonCode.SUBJECT_REQUEST_STATE_INVALID, f"Fall ist abgeschlossen ({case.status})", http_status=409,
        )


def open_request(
    db: Session, *, tenant_id: str, client_id: str, request_type: str, received_at: str, received_channel: str,
    requester_relation: str, request_summary: str | None, opened_by: str, now: datetime | None = None,
) -> PrivacySubjectRequest:
    moment = _utc(now)
    received = _parse_moment(received_at, "Eingang")
    _not_future(received, "Eingang", moment)
    case = PrivacySubjectRequest(
        id=new_uuid(), tenant_id=tenant_id, client_id=client_id,
        request_type=_choice(request_type, REQUEST_TYPES, "Anfrageart"), status="RECEIVED",
        received_at=_iso(received), received_channel=_choice(received_channel, CHANNELS, "Eingangskanal"),
        requester_relation=_choice(requester_relation, RELATIONS, "Anfragende Person"),
        request_summary=_text(request_summary, "Zusammenfassung", required=False),
        due_at=(received.date() + timedelta(days=DEADLINE_DAYS)).isoformat(),
        opened_by=opened_by, created_at=_iso(moment), updated_at=_iso(moment),
    )
    db.add(case)
    db.flush()
    return case


def verify_identity(
    db: Session, case: PrivacySubjectRequest, *, outcome: str, method: str, evidence_reference: str | None,
    failure_reason: str | None, actor_id: str, now: datetime | None = None,
) -> PrivacySubjectRequest:
    _require_open(case)
    if case.status not in ("RECEIVED", "IDENTITY_FAILED"):
        raise DomainError(
            ReasonCode.SUBJECT_REQUEST_STATE_INVALID, "Identitaet ist bereits bestaetigt", http_status=409,
        )
    outcome = _choice(outcome, ("VERIFIED", "FAILED"), "Ergebnis")
    stamp = _iso(_utc(now))
    case.identity_method = _choice(method, IDENTITY_METHODS, "Pruefmethode")
    case.identity_evidence_reference = _text(evidence_reference, "Nachweis-Referenz", required=True)
    case.identity_verified_by = actor_id
    if outcome == "VERIFIED":
        case.status = "IDENTITY_VERIFIED"
        case.identity_verified_at = stamp
        case.identity_failure_reason = None
    else:
        case.status = "IDENTITY_FAILED"
        case.identity_verified_at = None
        case.identity_failure_reason = _text(failure_reason, "Grund", required=True)
    case.updated_at = stamp
    return case


def extend_deadline(
    db: Session, case: PrivacySubjectRequest, *, extended_due_at: str, reason: str | None, notified_at: str,
    now: datetime | None = None,
) -> PrivacySubjectRequest:
    _require_open(case)
    moment = _utc(now)
    try:
        new_due = date.fromisoformat(str(extended_due_at)[:10])
    except ValueError as exc:
        raise DomainError(
            ReasonCode.SUBJECT_REQUEST_INPUT_INVALID, "Neue Frist ist kein gueltiges Datum", http_status=422,
        ) from exc
    if new_due <= effective_due_date(case):
        raise DomainError(
            ReasonCode.SUBJECT_REQUEST_INPUT_INVALID, "Neue Frist muss nach der bisherigen liegen", http_status=422,
        )
    notified = _parse_moment(notified_at, "Mitteilung an die betroffene Person")
    _not_future(notified, "Mitteilung", moment)
    if notified.date() > effective_due_date(case):
        raise DomainError(
            ReasonCode.SUBJECT_REQUEST_EXTENSION_TOO_LATE,
            "Die Verlaengerung muss innerhalb der laufenden Frist mitgeteilt werden", http_status=409,
        )
    case.extended_due_at = new_due.isoformat()
    case.extension_reason = _text(reason, "Begruendung der Verlaengerung", required=True)
    case.extension_notified_at = _iso(notified)
    case.updated_at = _iso(moment)
    return case


def decide(
    db: Session, case: PrivacySubjectRequest, *, decision: str, reason: str | None, scope: list[str] | None,
    actor_id: str, now: datetime | None = None,
) -> PrivacySubjectRequest:
    _require_open(case)
    decision = _choice(decision, DECISIONS, "Entscheid")
    if case.status == "IDENTITY_FAILED" and decision != "REFUSE":
        raise DomainError(
            ReasonCode.SUBJECT_REQUEST_IDENTITY_NOT_VERIFIED,
            "Identitaet nicht bestaetigt: nur eine begruendete Ablehnung ist moeglich", http_status=409,
        )
    if case.status not in ("IDENTITY_VERIFIED", "IDENTITY_FAILED", "DECIDED"):
        raise DomainError(
            ReasonCode.SUBJECT_REQUEST_IDENTITY_NOT_VERIFIED,
            "Vor dem Entscheid muss die Identitaet geprueft sein", http_status=409,
        )
    if case.exported_at:
        raise DomainError(
            ReasonCode.SUBJECT_REQUEST_STATE_INVALID, "Nach dem Export ist der Entscheid fest", http_status=409,
        )
    sections = sorted(set(scope or []))
    if decision == "RESTRICT":
        if case.request_type not in EXPORT_REQUEST_TYPES:
            raise DomainError(
                ReasonCode.SUBJECT_REQUEST_INPUT_INVALID,
                "Eine Einschraenkung nach Sektionen gibt es nur fuer Auskunft/Herausgabe", http_status=422,
            )
        unknown = [name for name in sections if name not in EXPORT_SECTIONS]
        if not sections or unknown:
            raise DomainError(
                ReasonCode.SUBJECT_REQUEST_INPUT_INVALID,
                f"Einschraenkung braucht bekannte Sektionen (unbekannt: {unknown})", http_status=422,
            )
    elif sections:
        raise DomainError(
            ReasonCode.SUBJECT_REQUEST_INPUT_INVALID, "Sektionen nur bei Einschraenkung", http_status=422,
        )
    stamp = _iso(_utc(now))
    case.decision = decision
    case.decision_reason = _text(reason, "Begruendung", required=decision in ("RESTRICT", "REFUSE"))
    case.decision_scope_json = json.dumps(sections) if sections else None
    case.decided_by = actor_id
    case.decided_at = stamp
    case.status = "DECIDED"
    case.updated_at = stamp
    return case


def _privacy_information(db: Session, tenant_id: str) -> dict[str, Any]:
    register = register_module.load_register()
    values = owner_values_module.owner_values(db, tenant_id)
    resolved = register_module.resolve_owner_fields(register, values)
    activities = [
        {
            "id": activity["id"], "name": activity["name"], "purpose": activity["purpose"],
            "data_categories": activity["data_categories"], "recipients": activity["recipients"],
            "egress_channels": activity["egress_channels"],
            "retention": {"source": activity["retention"]["source"], "basis": activity["retention"]["basis"]},
        }
        for activity in resolved["activities"]
        if {"clients", "client_partners", "representatives", "portal_users"} & set(activity["data_subjects"])
    ]
    return {
        "register_version": register["register_version"],
        "register_sha256": register_module.document_sha256(register),
        "controller": resolved["controller"],
        "additional_recipients": resolved["register_owner_fields"]["additional_recipients"],
        "activities": activities,
    }


def build_export(
    db: Session, case: PrivacySubjectRequest, *, actor_id: str, now: datetime | None = None,
) -> dict[str, Any]:
    _require_open(case)
    if case.request_type not in EXPORT_REQUEST_TYPES:
        raise DomainError(
            ReasonCode.SUBJECT_REQUEST_STATE_INVALID, "Export nur fuer Auskunft/Herausgabe", http_status=409,
        )
    if case.identity_verified_at is None:
        raise DomainError(
            ReasonCode.SUBJECT_REQUEST_IDENTITY_NOT_VERIFIED, "Identitaet nicht bestaetigt", http_status=409,
        )
    if case.status != "DECIDED" or case.decision not in ("FULFILL", "RESTRICT"):
        raise DomainError(
            ReasonCode.SUBJECT_REQUEST_DECISION_MISSING,
            "Export erst nach dem Entscheid 'erfuellen' oder 'einschraenken'", http_status=409,
        )
    blocking = owner_values_module.open_blocking_fields(db, case.tenant_id)
    if blocking:
        raise DomainError(
            ReasonCode.PRIVACY_OWNER_VALUES_OPEN,
            "Angaben des Verantwortlichen fehlen; die Auskunft kann noch nicht ausgegeben werden",
            http_status=409, extra={"open_fields": blocking},
        )
    try:
        payload = data_export.export_client_data(db, case.client_id)
    except ValueError as exc:
        raise DomainError(ReasonCode.SUBJECT_REQUEST_STATE_INVALID, str(exc), http_status=409) from exc
    withheld: dict[str, str] = {}
    for section in json.loads(case.decision_scope_json) if case.decision_scope_json else []:
        if section in payload["sections"]:
            current = payload["sections"][section]
            payload["sections"][section] = {} if isinstance(current, dict) else []
            payload["section_status"][section] = "withheld_by_decision"
            payload["manifest"][section] = 0
            withheld[section] = case.decision_reason or ""
    stamp = _iso(_utc(now))
    document = {
        "export_kind": EXPORT_KIND,
        "subject_request_id": case.id,
        "request_type": case.request_type,
        "decision": case.decision,
        "withheld_by_decision": withheld,
        "privacy_information": _privacy_information(db, case.tenant_id),
        "generated_at": stamp,
        "export": payload,
    }
    document["export_sha256"] = register_module.document_sha256(document)
    case.export_sha256 = document["export_sha256"]
    case.export_schema_version = int(payload.get("schema_version") or 0)
    case.exported_by = actor_id
    case.exported_at = stamp
    case.updated_at = stamp
    return document


def record_action(
    db: Session, case: PrivacySubjectRequest, *, completion_note: str | None, erasure_case_id: str | None,
    actor_id: str, now: datetime | None = None,
) -> PrivacySubjectRequest:
    _require_open(case)
    if case.request_type not in ("RECTIFICATION", "ERASURE"):
        raise DomainError(
            ReasonCode.SUBJECT_REQUEST_STATE_INVALID, "Umsetzung nur fuer Berichtigung/Loeschung", http_status=409,
        )
    if case.status != "DECIDED" or case.decision != "FULFILL":
        raise DomainError(
            ReasonCode.SUBJECT_REQUEST_DECISION_MISSING, "Umsetzung erst nach dem Entscheid 'erfuellen'",
            http_status=409,
        )
    if case.request_type == "ERASURE":
        erasure = db.get(PrivacyErasureCase, erasure_case_id) if erasure_case_id else None
        if (
            erasure is None or erasure.tenant_id != case.tenant_id or erasure.client_id != case.client_id
            or erasure.status not in EXECUTED_ERASURE_STATUSES
        ):
            raise DomainError(
                ReasonCode.SUBJECT_REQUEST_ERASURE_CASE_INVALID,
                "Loeschung braucht einen ausgefuehrten Loeschvorgang desselben Kunden", http_status=409,
            )
        case.linked_erasure_case_id = erasure.id
        case.completion_note = _text(completion_note, "Notiz", required=False)
    else:
        case.completion_note = _text(completion_note, "Notiz zur Berichtigung", required=True)
    stamp = _iso(_utc(now))
    case.action_completed_by = actor_id
    case.action_completed_at = stamp
    case.updated_at = stamp
    return case


def record_delivery(
    db: Session, case: PrivacySubjectRequest, *, delivered_at: str, delivery_channel: str,
    delivery_reference: str | None, actor_id: str, now: datetime | None = None,
) -> PrivacySubjectRequest:
    _require_open(case)
    if case.status != "DECIDED":
        raise DomainError(
            ReasonCode.SUBJECT_REQUEST_DECISION_MISSING, "Zustellung erst nach dem Entscheid", http_status=409,
        )
    if case.decision in ("FULFILL", "RESTRICT"):
        if case.request_type in EXPORT_REQUEST_TYPES and not case.export_sha256:
            raise DomainError(
                ReasonCode.SUBJECT_REQUEST_EXPORT_MISSING, "Kein Export ueber diesen Fall erstellt", http_status=409,
            )
        if case.request_type not in EXPORT_REQUEST_TYPES and not case.action_completed_at:
            raise DomainError(
                ReasonCode.SUBJECT_REQUEST_ACTION_MISSING, "Umsetzung ist nicht nachgewiesen", http_status=409,
            )
    moment = _utc(now)
    delivered = _parse_moment(delivered_at, "Zustellung")
    _not_future(delivered, "Zustellung", moment)
    if delivered < _parse_moment(case.received_at, "Eingang"):
        raise DomainError(
            ReasonCode.SUBJECT_REQUEST_INPUT_INVALID, "Zustellung liegt vor dem Eingang", http_status=422,
        )
    case.delivered_at = _iso(delivered)
    case.delivery_channel = _choice(delivery_channel, CHANNELS, "Zustellkanal")
    case.delivery_reference = _text(delivery_reference, "Zustellnachweis", required=True)
    case.delivered_by = actor_id
    case.delivery_recorded_at = _iso(moment)
    case.status = "COMPLETED"
    case.updated_at = _iso(moment)
    return case


def withdraw(
    db: Session, case: PrivacySubjectRequest, *, reason: str | None, now: datetime | None = None,
) -> PrivacySubjectRequest:
    _require_open(case)
    stamp = _iso(_utc(now))
    case.withdrawn_reason = _text(reason, "Grund", required=True)
    case.withdrawn_at = stamp
    case.status = "WITHDRAWN"
    case.updated_at = stamp
    return case


def list_requests(db: Session, tenant_id: str) -> list[PrivacySubjectRequest]:
    return (
        db.query(PrivacySubjectRequest)
        .filter(PrivacySubjectRequest.tenant_id == tenant_id)
        .order_by(PrivacySubjectRequest.received_at, PrivacySubjectRequest.id)
        .all()
    )


def status_counts(db: Session, tenant_id: str, *, now: datetime | None = None) -> dict[str, int]:
    cases = [case_out(case, now=now) for case in list_requests(db, tenant_id)]
    return {
        "subject_requests_open": sum(1 for c in cases if c["status"] not in CLOSED_STATUSES),
        "subject_requests_overdue": sum(1 for c in cases if c["overdue"]),
    }
