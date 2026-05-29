"""Sprint U-FINMA-2.1 — Service-Layer fuer AdvisoryLog.

Zentralisiert:
- JSON-Serialisierung der List-Felder (participants, topics, risk_warnings, …)
- Integrity-Hash-Berechnung beim Persist
- retain_until-Berechnung (= entry_datetime + 10 Jahre)
- Versions-Geschichte: Update legt neue Zeile an, alte wird superseded
- Response-Serialisierung (DB-Strings -> Python-Listen)
- Read-Audit (last_read_at / last_read_by)

So bleiben die Router-Endpoints dünn und die FINMA-Logik an einer Stelle
testbar.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from database import new_uuid
from models.review import AdvisoryLog
from models.users import User
from services.advisory_log_integrity import (
    compute_integrity_hash,
    compute_retain_until,
)


_LIST_FIELDS = (
    ("participants", "participants_json"),
    ("topics", "topics_json"),
    ("risk_warnings_given", "risk_warnings_given_json"),
    ("conflict_disclosure_ids", "conflict_disclosure_ids_json"),
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _dump_json(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        # Bereits JSON? Pass-through nur wenn parsebar.
        try:
            json.loads(value)
            return value
        except (TypeError, ValueError):
            return json.dumps([value])
    # Pydantic-Model-Liste -> dict-Liste serialisierbar machen
    serialized = []
    for item in value:
        if hasattr(item, "model_dump"):
            serialized.append(item.model_dump())
        else:
            serialized.append(item)
    return json.dumps(serialized, ensure_ascii=False)


def _load_json(raw: str | None) -> list:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def build_hash_payload(entry: AdvisoryLog) -> dict:
    """Snapshot der hash-relevanten Felder für `compute_integrity_hash`."""
    return {
        "mandate_id": entry.mandate_id,
        "advisor_id": entry.advisor_id,
        "entry_type": entry.entry_type,
        "entry_datetime": entry.entry_datetime,
        "duration_minutes": entry.duration_minutes,
        "communication_channel": entry.communication_channel,
        "language": entry.language,
        "location": entry.location,
        "title": entry.title,
        "description": entry.description,
        "decision": entry.decision,
        "status": entry.status,
        "participants_json": entry.participants_json,
        "topics_json": entry.topics_json,
        "risk_warnings_given_json": entry.risk_warnings_given_json,
        "cost_disclosure_given": entry.cost_disclosure_given,
        "conflict_disclosure_ids_json": entry.conflict_disclosure_ids_json,
        "suitability_check_id": entry.suitability_check_id,
        "recommendation_run_id": entry.recommendation_run_id,
        "client_signed": entry.client_signed,
        "client_signed_at": entry.client_signed_at,
        "version": entry.version,
    }


def create_advisory_log(
    db: Session,
    *,
    mandate_id: str,
    advisor: User,
    payload,
) -> AdvisoryLog:
    """Persist einen neuen AdvisoryLog-Eintrag mit Hash + retain_until.

    `payload` ist eine `AdvisoryLogCreate`-Instanz.
    """
    now = _now_iso()
    entry_datetime = payload.entry_datetime
    entry_date = payload.entry_date or entry_datetime[:10]

    entry = AdvisoryLog(
        id=new_uuid(),
        mandate_id=mandate_id,
        advisor_id=advisor.id,
        entry_type=payload.entry_type,
        title=payload.title,
        description=payload.description,
        decision=payload.decision,
        trigger_id=payload.trigger_id,
        recommendation_run_id=payload.recommendation_run_id,
        status=payload.status or "Empfohlen",
        client_signed=1 if payload.client_signed else 0,
        client_signed_at=payload.client_signed_at,
        document_id=payload.document_id,
        entry_date=entry_date,
        # FINMA-Erweiterung
        entry_datetime=entry_datetime,
        duration_minutes=payload.duration_minutes,
        communication_channel=payload.communication_channel,
        language=payload.language,
        location=payload.location,
        participants_json=_dump_json(payload.participants),
        topics_json=_dump_json(payload.topics),
        risk_warnings_given_json=_dump_json(payload.risk_warnings_given),
        cost_disclosure_given=1 if payload.cost_disclosure_given else 0,
        conflict_disclosure_ids_json=_dump_json(payload.conflict_disclosure_ids),
        suitability_check_id=payload.suitability_check_id,
        retain_until=compute_retain_until(entry_datetime),
        version=1,
        created_at=now,
        updated_at=now,
    )
    entry.integrity_hash = compute_integrity_hash(payload=build_hash_payload(entry))
    db.add(entry)
    return entry


def supersede_advisory_log(
    db: Session,
    *,
    previous: AdvisoryLog,
    advisor: User,
    update,
) -> AdvisoryLog:
    """Erzeugt eine neue Version mit den geänderten Feldern; markiert den
    Vorgänger als superseded. FINMA-Pflicht: keine destructive Updates.

    `update` ist eine `AdvisoryLogUpdate`-Instanz.
    """
    now = _now_iso()

    new = AdvisoryLog(
        id=new_uuid(),
        mandate_id=previous.mandate_id,
        advisor_id=advisor.id,
        entry_type=previous.entry_type,
        title=previous.title,
        description=update.description if update.description is not None else previous.description,
        decision=update.decision if update.decision is not None else previous.decision,
        trigger_id=previous.trigger_id,
        recommendation_run_id=(
            update.recommendation_run_id
            if update.recommendation_run_id is not None
            else previous.recommendation_run_id
        ),
        status=update.status or previous.status,
        client_signed=(
            (1 if update.client_signed else 0)
            if update.client_signed is not None
            else previous.client_signed
        ),
        client_signed_at=(
            update.client_signed_at
            if update.client_signed_at is not None
            else previous.client_signed_at
        ),
        document_id=previous.document_id,
        entry_date=previous.entry_date,
        # FINMA-Felder bleiben weitestgehend aus previous (außer revisierte)
        entry_datetime=previous.entry_datetime,
        duration_minutes=previous.duration_minutes,
        communication_channel=previous.communication_channel,
        language=previous.language,
        location=previous.location,
        participants_json=previous.participants_json,
        topics_json=(
            _dump_json(update.topics) if update.topics is not None else previous.topics_json
        ),
        risk_warnings_given_json=(
            _dump_json(update.risk_warnings_given)
            if update.risk_warnings_given is not None
            else previous.risk_warnings_given_json
        ),
        cost_disclosure_given=previous.cost_disclosure_given,
        conflict_disclosure_ids_json=previous.conflict_disclosure_ids_json,
        suitability_check_id=previous.suitability_check_id,
        retain_until=previous.retain_until,
        version=previous.version + 1,
        supersedes_id=previous.id,
        created_at=now,
        updated_at=now,
    )
    new.integrity_hash = compute_integrity_hash(payload=build_hash_payload(new))
    db.add(new)
    db.flush()

    # Vorgänger als superseded markieren
    previous.superseded_by_id = new.id
    previous.updated_at = now

    return new


def mark_read(db: Session, *, entry: AdvisoryLog, reader: User) -> None:
    """FINMA-Pflicht: Access-Tracking bei sensiblen Daten."""
    entry.last_read_at = _now_iso()
    entry.last_read_by = reader.id


def serialize_response(entry: AdvisoryLog) -> dict:
    """Wandelt AdvisoryLog-Row in API-Response-Dict (JSON-Felder → Listen)."""
    return {
        "id": entry.id,
        "mandate_id": entry.mandate_id,
        "entry_type": entry.entry_type,
        "title": entry.title,
        "description": entry.description,
        "decision": entry.decision,
        "trigger_id": entry.trigger_id,
        "recommendation_run_id": entry.recommendation_run_id,
        "status": entry.status,
        "advisor_id": entry.advisor_id,
        "client_signed": entry.client_signed,
        "client_signed_at": entry.client_signed_at,
        "document_id": entry.document_id,
        "entry_date": entry.entry_date,
        "created_at": entry.created_at,
        "updated_at": entry.updated_at,
        # FINMA-Erweiterung
        "entry_datetime": entry.entry_datetime,
        "duration_minutes": entry.duration_minutes,
        "communication_channel": entry.communication_channel,
        "language": entry.language,
        "location": entry.location,
        "participants": _load_json(entry.participants_json),
        "topics": _load_json(entry.topics_json),
        "risk_warnings_given": _load_json(entry.risk_warnings_given_json),
        "cost_disclosure_given": entry.cost_disclosure_given,
        "conflict_disclosure_ids": _load_json(entry.conflict_disclosure_ids_json),
        "suitability_check_id": entry.suitability_check_id,
        "integrity_hash": entry.integrity_hash,
        "retain_until": entry.retain_until,
        "version": entry.version,
        "supersedes_id": entry.supersedes_id,
        "superseded_by_id": entry.superseded_by_id,
        "last_read_at": entry.last_read_at,
        "last_read_by": entry.last_read_by,
    }
