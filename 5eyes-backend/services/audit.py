from sqlalchemy.orm import Session
from models.review import AuditLog
from database import new_uuid
from datetime import datetime, timezone


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
    entry = AuditLog(
        id=new_uuid(),
        user_id=user_id,
        user_name=user_name,
        table_name=table_name,
        record_id=record_id,
        action=action,
        field_name=field_name,
        old_value=str(old_value) if old_value is not None else None,
        new_value=str(new_value) if new_value is not None else None,
        mandate_id=mandate_id,
        client_id=client_id,
        created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
    )
    db.add(entry)
    # Note: caller must db.commit() — we don't commit here
