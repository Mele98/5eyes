"""H10 Nachtrag 1 (Codex-Vertrag 2026-11-12): append-only, verkettete
Ereignisse der Datenschutzfaelle (Betroffenenanfragen, Sicherheitsvorfaelle).

Jedes Ereignis traegt Laufnummer je Fall (eindeutig: zwei gleichzeitige
Schritte koennen nicht dieselbe Nummer belegen), den Hash des Vorgaengers und
den eigenen Hash ueber die kanonische Form; Nachweise zusaetzlich den Hash
des Artefakts. ``chain_problems`` rechnet die Kette nach.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from core.evidence import SCHEME_V1, evidence_hash
from database import new_uuid


def _iso(now: datetime | None = None) -> str:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def _event_hash(row_values: dict[str, Any]) -> str:
    """SHA-256 ueber die kanonische Form (core.evidence, Schema V1)."""
    return evidence_hash(row_values, scheme=SCHEME_V1)


def _hash_fields(row) -> dict[str, Any]:
    return {
        "case_id": row.case_id, "sequence": row.sequence, "event_type": row.event_type, "actor_id": row.actor_id,
        "occurred_at": row.occurred_at, "payload": json.loads(row.payload_json),
        "artifact_sha256": row.artifact_sha256, "previous_sha256": row.previous_sha256,
    }


def append_event(db: Session, model, *, tenant_id: str, case_id: str, event_type: str, actor_id: str,
                 payload: dict[str, Any] | None = None, artifact_sha256: str | None = None,
                 now: datetime | None = None):
    last = db.query(model).filter(model.case_id == case_id).order_by(model.sequence.desc()).first()
    row = model(
        id=new_uuid(), tenant_id=tenant_id, case_id=case_id, sequence=(last.sequence + 1) if last else 1,
        event_type=event_type, actor_id=actor_id, occurred_at=_iso(now),
        payload_json=json.dumps(payload or {}, sort_keys=True, ensure_ascii=False),
        artifact_sha256=artifact_sha256, previous_sha256=last.event_sha256 if last else None,
    )
    row.event_sha256 = _event_hash(_hash_fields(row))
    db.add(row)
    db.flush()
    return row


def list_events(db: Session, model, case_id: str) -> list:
    return db.query(model).filter(model.case_id == case_id).order_by(model.sequence).all()


def chain_problems(db: Session, model, case_id: str) -> list[str]:
    problems: list[str] = []
    previous = None
    for expected, row in enumerate(list_events(db, model, case_id), start=1):
        if row.sequence != expected:
            problems.append(f"Ereignis {row.id}: Laufnummer {row.sequence} statt {expected}")
        if row.previous_sha256 != previous:
            problems.append(f"Ereignis {row.sequence}: Vorgaenger-Hash passt nicht")
        if _event_hash(_hash_fields(row)) != row.event_sha256:
            problems.append(f"Ereignis {row.sequence}: Inhalt passt nicht zum Hash")
        previous = row.event_sha256
    return problems


def events_out(db: Session, model, case_id: str) -> list[dict[str, Any]]:
    return [
        {"sequence": r.sequence, "event_type": r.event_type, "actor_id": r.actor_id, "occurred_at": r.occurred_at,
         "payload": json.loads(r.payload_json), "artifact_sha256": r.artifact_sha256, "event_sha256": r.event_sha256}
        for r in list_events(db, model, case_id)
    ]
