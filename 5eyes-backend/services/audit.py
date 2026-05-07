import hashlib
from datetime import datetime, timezone

from sqlalchemy.orm import Session
from models.review import AuditLog
from database import new_uuid


def _audit_integrity_payload(
    *,
    entry_id: str,
    user_id: str | None,
    user_name: str | None,
    table_name: str | None,
    record_id: str | None,
    action: str | None,
    field_name: str | None,
    old_value: str | None,
    new_value: str | None,
    mandate_id: str | None,
    client_id: str | None,
    created_at: str,
    previous_hash: str,
) -> str:
    return "|".join(
        [
            str(entry_id or ""),
            str(user_id or ""),
            str(user_name or ""),
            str(table_name or ""),
            str(record_id or ""),
            str(action or ""),
            str(field_name or ""),
            str(old_value if old_value is not None else ""),
            str(new_value if new_value is not None else ""),
            str(mandate_id or ""),
            str(client_id or ""),
            str(created_at),
            str(previous_hash or ""),
        ]
    )


def log(
    db: Session,
    *,
    user_id: str,
    user_name: str,
    table_name: str,
    record_id: str,
    action: str,
    field_name: str | None = None,
    old_value: str | None = None,
    new_value: str | None = None,
    mandate_id: str | None = None,
    client_id: str | None = None,
) -> None:
    """Write an immutable audit log entry. Call after every mutating operation."""
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    previous_entry = (
        db.query(AuditLog)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .first()
    )
    previous_hash = str(previous_entry.integrity_hash or "") if previous_entry else ""
    entry_id = new_uuid()
    stored_old_value = str(old_value) if old_value is not None else None
    stored_new_value = str(new_value) if new_value is not None else None
    payload = _audit_integrity_payload(
        entry_id=entry_id,
        user_id=user_id,
        user_name=user_name,
        table_name=table_name,
        record_id=record_id,
        action=action,
        field_name=field_name,
        old_value=stored_old_value,
        new_value=stored_new_value,
        mandate_id=mandate_id,
        client_id=client_id,
        created_at=created_at,
        previous_hash=previous_hash,
    )
    integrity_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    entry = AuditLog(
        id=entry_id,
        user_id=user_id,
        user_name=user_name,
        table_name=table_name,
        record_id=record_id,
        action=action,
        field_name=field_name,
        old_value=stored_old_value,
        new_value=stored_new_value,
        mandate_id=mandate_id,
        client_id=client_id,
        integrity_hash=integrity_hash,
        created_at=created_at,
    )
    db.add(entry)
    # Note: caller must db.commit() — we don't commit here
