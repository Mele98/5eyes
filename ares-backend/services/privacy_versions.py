"""H10 Nachtrag 1 (Codex-Vertrag 2026-11-12): versionierte, append-only
Freigaben des Bearbeitungsverzeichnisses (C-DSG-01) und des Egress-Manifests
(C-DSG-03) je Mandant.

Eine Fassung ist der Inhalt einer Bearbeitung bzw. eines Kanals aus der
Datendatei samt den aufgeloesten Angaben des Verantwortlichen, mit SHA-256
ueber die kanonische Form. Wirksam ist je Schluessel die juengste
``APPROVED``-Fassung mit ``valid_from <= jetzt``; sie gilt bis zur naechsten
(``valid_to`` abgeleitet, Zeilen bleiben unveraendert).

Gates (Reason-Codes gemaess Vertrag):

* ``*_MISSING``   keine Fassung (bzw. Kanal ohne Freigabe),
* ``*_UNAPPROVED`` nur ``INVENTORY_REQUIRED``-Fassungen (Bestand, nie
  automatisch genehmigt),
* ``*_AMBIGUOUS`` mehr als eine wirksame Fassung zum selben Zeitpunkt,
* ``*_HASH_MISMATCH`` gespeicherter Hash passt nicht zum gespeicherten Inhalt,
* ``*_STALE``     Register/Manifest oder Owner-Angaben haben sich seit der
  Freigabe geaendert (aktueller Hash != freigegebener Hash).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from core.reason_codes import DomainError, ReasonCode
from database import new_uuid
from models.privacy import OutboundManifestVersion, ProcessingActivityVersion
from services import egress_manifest
from services import processing_activity_register as register_module

INVENTORY_REQUIRED = "INVENTORY_REQUIRED"
APPROVED = "APPROVED"
OPERATOR_INFRASTRUCTURE = "OPERATOR_INFRASTRUCTURE"


def _iso(now: datetime | None = None) -> str:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def _content_hash(content: Any) -> str:
    return register_module.document_sha256(content)


# ── Inhalte ────────────────────────────────────────────────────────────────────

def activity_contents(values: dict[str, str]) -> dict[str, dict[str, Any]]:
    register = register_module.load_register()
    resolved = register_module.resolve_owner_fields(register, values)
    return {
        activity["id"]: {
            "register_version": register["register_version"],
            "activity": activity,
            "controller": resolved["controller"],
            "register_owner_fields": resolved["register_owner_fields"],
        }
        for activity in resolved["activities"]
    }


def channel_contents(values: dict[str, str]) -> dict[str, dict[str, Any]]:
    manifest = egress_manifest.load_manifest()
    resolved = register_module.resolve_owner_fields(manifest, values)
    return {
        channel["id"]: {"manifest_version": manifest["manifest_version"], "channel": channel}
        for channel in egress_manifest.channels(resolved)
    }


# ── Fassungen ──────────────────────────────────────────────────────────────────

def _rows(db: Session, model, key_column: str, tenant_id: str) -> dict[str, list]:
    rows = db.query(model).filter(model.tenant_id == tenant_id).order_by(model.valid_from, model.id).all()
    grouped: dict[str, list] = {}
    for row in rows:
        grouped.setdefault(getattr(row, key_column), []).append(row)
    return grouped


def _code(kind: str, case: str) -> str:
    """Reason-Code je Art (Bearbeitung/Kanal) und Befund (statisch aufloesbar)."""
    if kind == "activity":
        if case == "missing":
            return ReasonCode.PROCESSING_ACTIVITY_MISSING.value
        if case == "unapproved":
            return ReasonCode.PROCESSING_ACTIVITY_UNAPPROVED.value
        if case == "ambiguous":
            return ReasonCode.PROCESSING_ACTIVITY_AMBIGUOUS.value
        if case == "hash":
            return ReasonCode.PROCESSING_ACTIVITY_HASH_MISMATCH.value
        return ReasonCode.PROCESSING_ACTIVITY_STALE.value
    # Egress: ohne wirksame Freigabe gilt der Kanal als nicht im Manifest,
    # jede Abweichung der Fassung als Hash-Abweichung.
    if case in ("missing", "unapproved"):
        return ReasonCode.EGRESS_MANIFEST_MISSING.value
    return ReasonCode.EGRESS_HASH_MISMATCH.value


def _evaluate(rows: list, current_hash: str, at: str, kind: str) -> tuple[str | None, Any]:
    if not rows:
        return _code(kind, "missing"), None
    approved = [r for r in rows if r.status == APPROVED and r.valid_from <= at]
    if not approved:
        return _code(kind, "unapproved"), None
    latest = max(r.valid_from for r in approved)
    effective = [r for r in approved if r.valid_from == latest]
    if len(effective) > 1:
        return _code(kind, "ambiguous"), None
    row = effective[0]
    if _content_hash(json.loads(row.content_json)) != row.content_sha256:
        return _code(kind, "hash"), row
    if row.content_sha256 != current_hash:
        return _code(kind, "stale"), row
    return None, row


def _out(row) -> dict[str, Any] | None:
    if row is None:
        return None
    return {"id": row.id, "version": row.version, "status": row.status, "content_sha256": row.content_sha256,
            "valid_from": row.valid_from, "approved_by": row.approved_by, "approved_at": row.approved_at}


def register_gate(db: Session, tenant_id: str, values: dict[str, str], *, now: datetime | None = None) -> list[dict]:
    at = _iso(now)
    rows = _rows(db, ProcessingActivityVersion, "activity_key", tenant_id)
    result = []
    for key, content in activity_contents(values).items():
        current = _content_hash(content)
        code, effective = _evaluate(rows.get(key, []), current, at, "activity")
        result.append({"activity_key": key, "current_sha256": current, "reason_code": code,
                       "effective": _out(effective), "versions": len(rows.get(key, []))})
    return result


def channel_gate(db: Session, tenant_id: str, values: dict[str, str], *, now: datetime | None = None) -> list[dict]:
    at = _iso(now)
    rows = _rows(db, OutboundManifestVersion, "channel_id", tenant_id)
    result = []
    for key, content in channel_contents(values).items():
        current = _content_hash(content)
        code, effective = _evaluate(rows.get(key, []), current, at, "channel")
        result.append({
            "channel_id": key, "current_sha256": current, "reason_code": code,
            "approved_sha256": effective.content_sha256 if effective is not None else None,
            "effective": _out(effective), "versions": len(rows.get(key, [])),
        })
    return result


def _append(db: Session, model, key_column: str, tenant_id: str, contents: dict[str, dict], keys: list[str] | None,
            *, status: str, actor_id: str, version_field: str, version_value: str, now: datetime | None) -> list:
    stamp = _iso(now)
    existing = _rows(db, model, key_column, tenant_id)
    created = []
    for key in keys or list(contents):
        if key not in contents:
            raise DomainError(ReasonCode.PRIVACY_OWNER_FIELD_UNKNOWN, f"Unbekannter Schluessel: {key}", http_status=422)
        rows = existing.get(key, [])
        if status == INVENTORY_REQUIRED and rows:
            continue
        row = model(
            id=new_uuid(), tenant_id=tenant_id, version=len(rows) + 1, status=status,
            content_json=json.dumps(contents[key], sort_keys=True, ensure_ascii=False),
            content_sha256=_content_hash(contents[key]), valid_from=stamp, created_by=actor_id, created_at=stamp,
            approved_by=actor_id if status == APPROVED else None, approved_at=stamp if status == APPROVED else None,
        )
        setattr(row, key_column, key)
        setattr(row, version_field, version_value)
        db.add(row)
        created.append(row)
    db.flush()
    return created


def ensure_inventory_rows(db: Session, tenant_id: str, values: dict[str, str], *, actor_id: str) -> None:
    """Bestand als ``INVENTORY_REQUIRED`` (nie automatisch genehmigt)."""
    register = register_module.load_register()
    manifest = egress_manifest.load_manifest()
    _append(db, ProcessingActivityVersion, "activity_key", tenant_id, activity_contents(values), None,
            status=INVENTORY_REQUIRED, actor_id=actor_id, version_field="register_version",
            version_value=register["register_version"], now=None)
    _append(db, OutboundManifestVersion, "channel_id", tenant_id, channel_contents(values), None,
            status=INVENTORY_REQUIRED, actor_id=actor_id, version_field="manifest_version",
            version_value=manifest["manifest_version"], now=None)


def approve_register(db: Session, tenant_id: str, values: dict[str, str], *, actor_id: str,
                     keys: list[str] | None = None, now: datetime | None = None) -> list:
    register = register_module.load_register()
    return _append(db, ProcessingActivityVersion, "activity_key", tenant_id, activity_contents(values), keys,
                   status=APPROVED, actor_id=actor_id, version_field="register_version",
                   version_value=register["register_version"], now=now)


def approve_manifest(db: Session, tenant_id: str, values: dict[str, str], *, actor_id: str,
                     keys: list[str] | None = None, now: datetime | None = None) -> list:
    manifest = egress_manifest.load_manifest()
    return _append(db, OutboundManifestVersion, "channel_id", tenant_id, channel_contents(values), keys,
                   status=APPROVED, actor_id=actor_id, version_field="manifest_version",
                   version_value=manifest["manifest_version"], now=now)


def runtime_channel_states(db: Session, tenant_id: str, values: dict[str, str]) -> dict[str, dict[str, Any]]:
    """Fuer den Laufzeitschutz: je Kanal freigegebener und aktueller Hash sowie
    die Sperre wegen fehlender Owner-Angaben (Garantie bzw. Grundlage)."""
    manifest = egress_manifest.load_manifest()
    gate = {row["channel_id"]: row for row in channel_gate(db, tenant_id, values)}
    states: dict[str, dict[str, Any]] = {}
    for channel in egress_manifest.channels(manifest):
        cid = channel["id"]
        row = gate[cid]
        effective = row["effective"]
        approved = effective["content_sha256"] if effective else None
        if row["reason_code"] == ReasonCode.EGRESS_HASH_MISMATCH.value and effective is not None:
            # gespeicherter Inhalt manipuliert oder veraltet -> nie gleich dem aktuellen Hash
            approved = approved if approved != row["current_sha256"] else f"!{approved}"
        owner_block = None
        if egress_manifest.blocking_owner_keys(channel):
            guarantee_keys = [channel[k]["owner_field"] for k in ("destination_country", "guarantee")
                              if isinstance(channel.get(k), dict) and channel[k].get("owner_field")]
            basis = channel.get("legal_basis") or {}
            if not all(values.get(k) for k in guarantee_keys):
                owner_block = ReasonCode.EGRESS_GUARANTEE_MISSING.value
            elif basis.get("owner_field") and not values.get(basis["owner_field"]):
                owner_block = ReasonCode.EGRESS_CONSENT_OR_BASIS_MISSING.value
        states[cid] = {
            "approved_sha256": approved, "current_sha256": row["current_sha256"], "owner_block": owner_block,
            "approval_exempt": (channel.get("guarantee") or {}).get("status") == OPERATOR_INFRASTRUCTURE,
        }
    return states
