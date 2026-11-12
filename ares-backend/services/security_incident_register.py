"""H10 C-DSG-04: Register der Verletzungen der Datensicherheit (Incidents).

Ein Vorfall ist ein Fall mit

1. Entdeckung (Zeitpunkt, Art: Vertraulichkeit/Integritaet/Verfuegbarkeit,
   betroffene Datenkategorien und Personen, Sofortmassnahmen),
2. Risikobewertung (``LOW``/``HIGH`` mit Begruendung) -- ``HIGH`` steht fuer
   "voraussichtlich hohes Risiko fuer die Persoenlichkeit oder die
   Grundrechte der betroffenen Personen",
3. Meldeentscheid an den EDOEB: bei ``HIGH`` nur ``NOTIFY``; danach
   Meldenachweis (Zeitpunkt, Referenz) "so rasch als moeglich",
4. Entscheid ueber die Information der betroffenen Personen (``NOTIFY``,
   ``NOT_REQUIRED`` mit Begruendung, ``DEFERRED`` mit Begruendung) und
   Nachweis der Information,
5. Nachweisen (Referenzen) und Abschluss.

``gate_findings`` ist das Gate: ein offener Vorfall mit hohem Risiko ohne
Meldeentscheid bzw. ohne Meldenachweis ist rot (``blocked``), sofort und
ohne Karenz. Eine interne Zielfrist in Stunden kann der Verantwortliche als
Owner-Feld setzen; Ares erfindet keine. Technische Umsetzung, keine
Rechtsberatung.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from core.reason_codes import DomainError, ReasonCode
from database import new_uuid
from models.privacy import PrivacySecurityIncident

INCIDENT_TYPES = ("CONFIDENTIALITY", "INTEGRITY", "AVAILABILITY")
RISK_LEVELS = ("LOW", "HIGH", "UNKNOWN")
ESCALATING_RISKS = ("HIGH", "UNKNOWN")
NOTIFICATION_DECISIONS = ("NOTIFY", "NOT_REQUIRED")
SUBJECT_DECISIONS = ("NOTIFY", "NOT_REQUIRED", "DEFERRED")
CHANNELS = ("EMAIL", "LETTER", "IN_PERSON", "PORTAL", "PHONE", "OTHER")
EVIDENCE_KINDS = ("LOG_EXPORT", "REPORT", "CORRESPONDENCE", "EDOEB_RECEIPT", "SCREENSHOT", "OTHER")
TARGET_HOURS_FIELD = "incident.notification_target_hours"
ESCALATION_CONTACT_FIELD = "incident.escalation_contact"


def _utc(now: datetime | None) -> datetime:
    value = now or datetime.now(timezone.utc)
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _moment(value: str | None, field: str) -> datetime:
    raw = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00")) if len(raw) > 10 else datetime.fromisoformat(raw)
    except ValueError as exc:
        raise DomainError(
            ReasonCode.INCIDENT_INPUT_INVALID, f"{field} ist kein gueltiger Zeitpunkt", http_status=422,
        ) from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _past(value: str | None, field: str, now: datetime, *, not_before: str | None = None) -> datetime:
    moment = _moment(value, field)
    tolerance = timedelta(days=1) if len(str(value or "").strip()) == 10 else timedelta(minutes=5)
    if moment > now + tolerance:
        raise DomainError(ReasonCode.INCIDENT_INPUT_INVALID, f"{field} liegt in der Zukunft", http_status=422)
    if not_before and moment < _moment(not_before, "Entdeckung"):
        raise DomainError(ReasonCode.INCIDENT_INPUT_INVALID, f"{field} liegt vor der Entdeckung", http_status=422)
    return moment


def _choice(value: str | None, allowed: tuple[str, ...], field: str) -> str:
    if value not in allowed:
        raise DomainError(
            ReasonCode.INCIDENT_INPUT_INVALID, f"{field} muss einer der Werte {allowed} sein", http_status=422,
        )
    return str(value)


def _text(value: str | None, field: str, *, required: bool) -> str | None:
    cleaned = str(value or "").strip()
    if required and not cleaned:
        raise DomainError(ReasonCode.INCIDENT_INPUT_INVALID, f"{field} ist Pflicht", http_status=422)
    return cleaned or None


def _require_open(incident: PrivacySecurityIncident) -> None:
    if incident.status == "CLOSED":
        raise DomainError(ReasonCode.INCIDENT_STATE_INVALID, "Vorfall ist abgeschlossen", http_status=409)


def _touch(incident: PrivacySecurityIncident, now: datetime) -> None:
    incident.updated_at = _iso(now)


def record_incident(
    db: Session, *, tenant_id: str, discovered_at: str, incident_type: str, description: str | None,
    affected_data_categories: list[str], allowed_categories: set[str], affected_subjects_count: int | None,
    containment_measures: str | None, recorded_by: str, now: datetime | None = None,
) -> PrivacySecurityIncident:
    moment = _utc(now)
    discovered = _past(discovered_at, "Entdeckung", moment)
    categories = sorted(set(affected_data_categories or []))
    unknown = [c for c in categories if c not in allowed_categories]
    if unknown:
        raise DomainError(
            ReasonCode.INCIDENT_INPUT_INVALID, f"Unbekannte Datenkategorien: {unknown}", http_status=422,
        )
    if affected_subjects_count is not None and affected_subjects_count < 0:
        raise DomainError(ReasonCode.INCIDENT_INPUT_INVALID, "Anzahl Betroffener ist negativ", http_status=422)
    incident_id = new_uuid()
    incident = PrivacySecurityIncident(
        id=incident_id, tenant_id=tenant_id,
        reference=f"INC-{discovered.strftime('%Y%m%d')}-{incident_id[:8].upper()}",
        status="OPEN", discovered_at=_iso(discovered),
        incident_type=_choice(incident_type, INCIDENT_TYPES, "Art"),
        description=_text(description, "Beschreibung", required=True),
        affected_data_categories_json=json.dumps(categories),
        affected_subjects_count=affected_subjects_count,
        containment_measures=_text(containment_measures, "Sofortmassnahmen", required=False),
        evidence_json="[]", remediation_status="OPEN", recorded_by=recorded_by, created_at=_iso(moment), updated_at=_iso(moment),
    )
    db.add(incident)
    db.flush()
    return incident


def assess_risk(
    db: Session, incident: PrivacySecurityIncident, *, risk_level: str, rationale: str | None, actor_id: str,
    now: datetime | None = None,
) -> PrivacySecurityIncident:
    _require_open(incident)
    moment = _utc(now)
    level = _choice(risk_level, RISK_LEVELS, "Risiko")
    if incident.notification_decision == "NOT_REQUIRED" and level in ESCALATING_RISKS:
        incident.notification_decision = None
        incident.notification_decision_reason = None
        incident.notification_decided_by = None
        incident.notification_decided_at = None
    incident.risk_level = level
    incident.risk_rationale = _text(rationale, "Begruendung der Risikobewertung", required=True)
    incident.risk_assessed_by = actor_id
    incident.risk_assessed_at = _iso(moment)
    if incident.status == "OPEN" or incident.notification_decision is None:
        incident.status = "ASSESSED"
    _touch(incident, moment)
    return incident


def decide_notification(
    db: Session, incident: PrivacySecurityIncident, *, decision: str, reason: str | None, actor_id: str,
    escalation_contact: str | None = None, now: datetime | None = None,
) -> PrivacySecurityIncident:
    _require_open(incident)
    if not str(escalation_contact or "").strip():
        raise DomainError(
            ReasonCode.INCIDENT_OWNER_CONTACT_MISSING,
            "Vor dem Meldeentscheid den Eskalationskontakt erfassen (Angaben des Verantwortlichen)", http_status=409,
        )
    if not incident.risk_level:
        raise DomainError(
            ReasonCode.INCIDENT_RISK_UNASSESSED, "Vor dem Meldeentscheid das Risiko bewerten",
            http_status=409,
        )
    decision = _choice(decision, NOTIFICATION_DECISIONS, "Meldeentscheid")
    if incident.risk_level in ESCALATING_RISKS and decision != "NOTIFY":
        raise DomainError(
            ReasonCode.INCIDENT_HIGH_RISK_REQUIRES_NOTIFICATION,
            "Bei voraussichtlich hohem Risiko ist dem EDOEB zu melden", http_status=409,
        )
    moment = _utc(now)
    incident.notification_decision = decision
    incident.notification_decision_reason = _text(reason, "Begruendung", required=decision == "NOT_REQUIRED")
    incident.notification_decided_by = actor_id
    incident.notification_decided_at = _iso(moment)
    incident.status = "DECIDED"
    _touch(incident, moment)
    return incident


def record_edoeb_notification(
    db: Session, incident: PrivacySecurityIncident, *, notified_at: str, reference: str | None, actor_id: str,
    now: datetime | None = None,
) -> PrivacySecurityIncident:
    _require_open(incident)
    if incident.notification_decision != "NOTIFY":
        raise DomainError(
            ReasonCode.INCIDENT_NOTIFICATION_DECISION_MISSING, "Meldenachweis nur nach Entscheid 'melden'",
            http_status=409,
        )
    moment = _utc(now)
    notified = _past(notified_at, "Meldung", moment, not_before=incident.discovered_at)
    incident.edoeb_notified_at = _iso(notified)
    incident.edoeb_reference = _text(reference, "Referenz der Meldung", required=True)
    incident.edoeb_notified_by = actor_id
    _touch(incident, moment)
    return incident


def decide_subject_notification(
    db: Session, incident: PrivacySecurityIncident, *, decision: str, reason: str | None, actor_id: str,
    now: datetime | None = None,
) -> PrivacySecurityIncident:
    _require_open(incident)
    if not incident.risk_level:
        raise DomainError(
            ReasonCode.INCIDENT_RISK_UNASSESSED, "Vor dem Entscheid das Risiko bewerten", http_status=409,
        )
    decision = _choice(decision, SUBJECT_DECISIONS, "Entscheid Information Betroffener")
    moment = _utc(now)
    incident.subject_notification_decision = decision
    incident.subject_notification_reason = _text(reason, "Begruendung", required=decision != "NOTIFY")
    incident.subject_notification_decided_by = actor_id
    incident.subject_notification_decided_at = _iso(moment)
    _touch(incident, moment)
    return incident


def record_subject_notification(
    db: Session, incident: PrivacySecurityIncident, *, notified_at: str, channel: str, reference: str | None,
    actor_id: str, now: datetime | None = None,
) -> PrivacySecurityIncident:
    _require_open(incident)
    if incident.subject_notification_decision != "NOTIFY":
        raise DomainError(
            ReasonCode.INCIDENT_SUBJECT_DECISION_MISSING, "Nachweis nur nach Entscheid 'informieren'",
            http_status=409,
        )
    moment = _utc(now)
    notified = _past(notified_at, "Information", moment, not_before=incident.discovered_at)
    incident.subjects_notified_at = _iso(notified)
    incident.subject_notification_channel = _choice(channel, CHANNELS, "Kanal")
    incident.subject_notification_reference = _text(reference, "Nachweis", required=True)
    incident.subjects_notified_by = actor_id
    _touch(incident, moment)
    return incident


def add_evidence(
    db: Session, incident: PrivacySecurityIncident, *, kind: str, reference: str | None, actor_id: str,
    now: datetime | None = None,
) -> PrivacySecurityIncident:
    _require_open(incident)
    moment = _utc(now)
    evidence = json.loads(incident.evidence_json or "[]")
    evidence.append({
        "kind": _choice(kind, EVIDENCE_KINDS, "Nachweisart"),
        "reference": _text(reference, "Referenz", required=True),
        "recorded_by": actor_id, "recorded_at": _iso(moment),
    })
    incident.evidence_json = json.dumps(evidence)
    _touch(incident, moment)
    return incident


def record_remediation(
    db: Session, incident: PrivacySecurityIncident, *, note: str | None, actor_id: str, now: datetime | None = None,
) -> PrivacySecurityIncident:
    _require_open(incident)
    moment = _utc(now)
    incident.remediation_note = _text(note, "Massnahmen", required=True)
    incident.remediation_status = "DONE"
    incident.remediation_completed_by = actor_id
    incident.remediation_completed_at = _iso(moment)
    _touch(incident, moment)
    return incident


def close_problems(incident: PrivacySecurityIncident) -> list[str]:
    problems = []
    if incident.remediation_status != "DONE":
        problems.append("Behebung/Massnahmen nicht abgeschlossen")
    if not incident.risk_level:
        problems.append("Risikobewertung fehlt")
    if not incident.notification_decision:
        problems.append("Meldeentscheid fehlt")
    if incident.notification_decision == "NOTIFY" and not incident.edoeb_notified_at:
        problems.append("Meldenachweis an den EDOEB fehlt")
    if not incident.subject_notification_decision:
        problems.append("Entscheid zur Information der Betroffenen fehlt")
    if incident.subject_notification_decision == "DEFERRED":
        problems.append("Information der Betroffenen ist aufgeschoben")
    if incident.subject_notification_decision == "NOTIFY" and not incident.subjects_notified_at:
        problems.append("Nachweis der Information der Betroffenen fehlt")
    return problems


def close(
    db: Session, incident: PrivacySecurityIncident, *, note: str | None, actor_id: str, now: datetime | None = None,
) -> PrivacySecurityIncident:
    _require_open(incident)
    problems = close_problems(incident)
    if incident.remediation_status != "DONE":
        raise DomainError(
            ReasonCode.INCIDENT_REMEDIATION_OPEN, "Abschluss nicht moeglich: " + "; ".join(problems),
            http_status=409, extra={"problems": problems},
        )
    if problems:
        raise DomainError(
            ReasonCode.INCIDENT_CLOSE_BLOCKED, "Abschluss nicht moeglich: " + "; ".join(problems),
            http_status=409, extra={"problems": problems},
        )
    moment = _utc(now)
    incident.closure_note = _text(note, "Abschlussnotiz", required=True)
    incident.closed_by = actor_id
    incident.closed_at = _iso(moment)
    incident.status = "CLOSED"
    _touch(incident, moment)
    return incident


def incident_out(incident: PrivacySecurityIncident) -> dict[str, Any]:
    return {
        "id": incident.id, "reference": incident.reference, "status": incident.status,
        "discovered_at": incident.discovered_at, "incident_type": incident.incident_type,
        "description": incident.description,
        "affected_data_categories": json.loads(incident.affected_data_categories_json or "[]"),
        "affected_subjects_count": incident.affected_subjects_count,
        "containment_measures": incident.containment_measures,
        "risk_level": incident.risk_level, "risk_rationale": incident.risk_rationale,
        "risk_assessed_by": incident.risk_assessed_by, "risk_assessed_at": incident.risk_assessed_at,
        "notification_decision": incident.notification_decision,
        "notification_decision_reason": incident.notification_decision_reason,
        "notification_decided_by": incident.notification_decided_by,
        "notification_decided_at": incident.notification_decided_at,
        "edoeb_notified_at": incident.edoeb_notified_at, "edoeb_reference": incident.edoeb_reference,
        "subject_notification_decision": incident.subject_notification_decision,
        "subject_notification_reason": incident.subject_notification_reason,
        "subjects_notified_at": incident.subjects_notified_at,
        "subject_notification_channel": incident.subject_notification_channel,
        "subject_notification_reference": incident.subject_notification_reference,
        "evidence": json.loads(incident.evidence_json or "[]"),
        "recorded_by": incident.recorded_by, "created_at": incident.created_at, "updated_at": incident.updated_at,
        "closed_at": incident.closed_at, "closed_by": incident.closed_by, "closure_note": incident.closure_note,
        "remediation_status": incident.remediation_status, "remediation_note": incident.remediation_note,
        "remediation_completed_at": incident.remediation_completed_at,
        "close_problems": close_problems(incident) if incident.status != "CLOSED" else [],
    }


def list_incidents(db: Session, tenant_id: str) -> list[PrivacySecurityIncident]:
    return (
        db.query(PrivacySecurityIncident)
        .filter(PrivacySecurityIncident.tenant_id == tenant_id)
        .order_by(PrivacySecurityIncident.discovered_at, PrivacySecurityIncident.id)
        .all()
    )


def _base(incident: PrivacySecurityIncident, hours: float) -> dict[str, Any]:
    return {"incident_id": incident.id, "reference": incident.reference, "hours_since_discovery": round(hours, 1)}


def gate_findings(
    db: Session, tenant_id: str, *, target_hours: str | None = None, now: datetime | None = None,
) -> dict[str, Any]:
    """Offene Pflichten aus dem Incident-Register; ``blocked`` bei hohem
    Risiko ohne Meldeentscheid oder ohne Meldenachweis."""
    moment = _utc(now)
    target: float | None = None
    try:
        target = float(str(target_hours).strip()) if target_hours else None
    except ValueError:
        target = None
    findings: list[dict[str, Any]] = []
    for incident in list_incidents(db, tenant_id):
        if incident.status == "CLOSED":
            continue
        hours = (moment - _moment(incident.discovered_at, "Entdeckung")).total_seconds() / 3600
        base = _base(incident, hours)
        if not incident.risk_level:
            findings.append({**base, "reason_code": ReasonCode.INCIDENT_RISK_UNASSESSED.value,
                             "message": "Risikobewertung fehlt", "blocking": False})
            continue
        if incident.risk_level in ESCALATING_RISKS and incident.notification_decision != "NOTIFY":
            findings.append({**base, "reason_code": ReasonCode.INCIDENT_NOTIFICATION_DECISION_MISSING.value,
                             "message": "Hohes oder unbekanntes Risiko ohne Meldeentscheid an den EDOEB",
                             "blocking": True})
        elif incident.notification_decision == "NOTIFY" and not incident.edoeb_notified_at:
            findings.append({**base, "reason_code": ReasonCode.INCIDENT_EDOEB_NOTIFICATION_PENDING.value,
                             "message": "Meldung an den EDOEB so rasch als moeglich nachweisen",
                             "blocking": incident.risk_level in ESCALATING_RISKS})
            if target is not None and hours > target:
                findings.append({**base, "reason_code": ReasonCode.INCIDENT_NOTIFICATION_TARGET_EXCEEDED.value,
                                 "message": f"Interne Zielfrist von {target:g} Stunden ueberschritten",
                                 "blocking": True})
        if not incident.subject_notification_decision:
            findings.append({**base, "reason_code": ReasonCode.INCIDENT_SUBJECT_DECISION_MISSING.value,
                             "message": "Entscheid zur Information der Betroffenen fehlt", "blocking": False})
        elif incident.subject_notification_decision == "DEFERRED":
            findings.append({**base, "reason_code": ReasonCode.INCIDENT_SUBJECT_NOTIFICATION_DEFERRED.value,
                             "message": "Information der Betroffenen aufgeschoben", "blocking": False})
    return {
        "blocked": any(f["blocking"] for f in findings),
        "open_incidents": sum(1 for i in list_incidents(db, tenant_id) if i.status != "CLOSED"),
        "notification_target_hours": target,
        "findings": findings,
    }
