"""H10 C-DSG-01 (DSG-Technikaudit 2026-11-11): Angaben des Verantwortlichen
(Owner-Felder, C-DSG-05/06) und Sicht auf das Bearbeitungsverzeichnis.

Owner-Felder sind Angaben, die nur die Firma machen kann (Identitaet,
Kontakt, Begruendung der Aufbewahrung, Staaten/Garantien). Ares belegt sie
nie vor. Offene Pflichtfelder (Sperrwirkung ``customer_output``) sperren die
kundenwirksame Ausgabe -- etwa die Auskunft an eine betroffene Person --,
aber nie den Start der App.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from core.reason_codes import DomainError, ReasonCode
from database import Base, new_uuid
from models.privacy import PrivacyOwnerValue
from services import processing_activity_register as register_module

OWNER_VALUE_MAX_LENGTH = 2000


def now_iso(now: datetime | None = None) -> str:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


# ── Owner-Felder ───────────────────────────────────────────────────────────────

def owner_field_definitions() -> list[dict[str, Any]]:
    """Alle Owner-Felder (Register), je Schluessel einmal."""
    try:
        register = register_module.load_register()
    except register_module.RegisterUnavailable:
        return []
    fields = register_module.iter_owner_fields(register, source="register")
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for field in fields:
        if field["key"] in seen:
            continue
        seen.add(field["key"])
        unique.append(field)
    return unique


def _current_rows(db: Session, tenant_id: str) -> dict[str, PrivacyOwnerValue]:
    rows = (
        db.query(PrivacyOwnerValue)
        .filter(PrivacyOwnerValue.tenant_id == tenant_id, PrivacyOwnerValue.status == "CONFIRMED")
        .all()
    )
    return {row.field_key: row for row in rows}


def owner_values(db: Session, tenant_id: str) -> dict[str, str]:
    return {key: row.value for key, row in _current_rows(db, tenant_id).items()}


def owner_field_status(db: Session, tenant_id: str) -> list[dict[str, Any]]:
    rows = _current_rows(db, tenant_id)
    result = []
    for field in owner_field_definitions():
        row = rows.get(field["key"])
        result.append({
            **field,
            "status": "CONFIRMED" if row else "OPEN",
            "value": row.value if row else None,
            "revision": row.revision if row else 0,
            "confirmed_by": row.confirmed_by if row else None,
            "confirmed_at": row.confirmed_at if row else None,
        })
    return result


def set_owner_value(
    db: Session, *, tenant_id: str, field_key: str, value: str, actor_id: str, now: datetime | None = None,
) -> tuple[PrivacyOwnerValue, str | None]:
    """Neue Fassung eines Owner-Felds; liefert (neue Zeile, alter Wert)."""
    definitions = {field["key"]: field for field in owner_field_definitions()}
    if field_key not in definitions:
        raise DomainError(ReasonCode.PRIVACY_OWNER_FIELD_UNKNOWN, f"Unbekanntes Owner-Feld: {field_key}", http_status=422)
    cleaned = str(value or "").strip()
    if not cleaned:
        raise DomainError(ReasonCode.PRIVACY_OWNER_VALUE_INVALID, "Wert darf nicht leer sein", http_status=422)
    if len(cleaned) > OWNER_VALUE_MAX_LENGTH:
        raise DomainError(ReasonCode.PRIVACY_OWNER_VALUE_INVALID, f"Wert laenger als {OWNER_VALUE_MAX_LENGTH} Zeichen", http_status=422)
    stamp = now_iso(now)
    current = _current_rows(db, tenant_id).get(field_key)
    old_value = current.value if current else None
    if current is not None:
        if current.value == cleaned:
            return current, old_value
        current.status = "RETIRED"
        current.retired_at = stamp
    row = PrivacyOwnerValue(
        id=new_uuid(), tenant_id=tenant_id, field_key=field_key, value=cleaned,
        revision=(current.revision + 1) if current else 1, status="CONFIRMED",
        value_sha256=hashlib.sha256(cleaned.encode("utf-8")).hexdigest(),
        confirmed_by=actor_id, confirmed_at=stamp,
    )
    db.add(row)
    db.flush()
    return row, old_value


def open_blocking_fields(db: Session, tenant_id: str) -> list[dict[str, Any]]:
    """Offene Owner-Felder, die die kundenwirksame Ausgabe sperren."""
    return [
        {"key": f["key"], "label": f["label"]}
        for f in owner_field_status(db, tenant_id)
        if f["status"] == "OPEN" and f["blocking"] == register_module.BLOCKING_CUSTOMER_OUTPUT
    ]


# ── Bearbeitungsverzeichnis ────────────────────────────────────────────────────

def register_view(db: Session, tenant_id: str) -> dict[str, Any]:
    try:
        register = register_module.load_register()
    except register_module.RegisterUnavailable as exc:
        return {
            "available": False, "problems": [str(exc)], "customer_output_ready": False,
            "owner_fields": [], "open_blocking_fields": [], "register": None,
        }
    problems = register_module.register_problems(Base.metadata.tables, register, check_evidence_files=False)
    values = owner_values(db, tenant_id)
    blocking = open_blocking_fields(db, tenant_id)
    return {
        "available": True,
        **register_module.register_summary(register),
        "problems": problems,
        "complete": not problems,
        "owner_fields": owner_field_status(db, tenant_id),
        "open_blocking_fields": blocking,
        "customer_output_ready": not problems and not blocking,
        "register": register_module.resolve_owner_fields(register, values),
    }


def register_export(db: Session, tenant_id: str, *, now: datetime | None = None) -> dict[str, Any]:
    view = register_view(db, tenant_id)
    if not view["available"]:
        raise DomainError(ReasonCode.PROCESSING_REGISTER_UNAVAILABLE, "; ".join(view["problems"]), http_status=503)
    document = {
        "export_kind": "ProcessingActivityRegisterExportV1",
        "exported_at": now_iso(now),
        "tenant_id": tenant_id,
        "register_version": view["register_version"],
        "register_sha256": view["register_sha256"],
        "complete": view["complete"],
        "problems": view["problems"],
        "customer_output_ready": view["customer_output_ready"],
        "open_blocking_fields": view["open_blocking_fields"],
        "register": view["register"],
    }
    document["export_sha256"] = register_module.document_sha256(document)
    return document
