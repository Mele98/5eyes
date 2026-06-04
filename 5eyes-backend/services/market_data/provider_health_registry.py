"""Persistent provider-health observation for the market-data pipeline.

Phase 1 is passive: the registry records provider failures and recoveries,
but it does not trigger refreshes, rebalance decisions, or active failover
tuning. Runtime skipping stays in the existing in-memory HealthState.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

TABLE_NAME = "provider_health_events"
HEALTH_COLUMNS: tuple[str, ...] = (
    "id",
    "provider_name",
    "status",
    "reason",
    "operation",
    "error_type",
    "consecutive_errors",
    "observed_at",
    "unhealthy_until",
    "recovered_at",
    "source",
    "created_at",
    "updated_at",
)
COLUMN_SQL_TYPES: dict[str, str] = {
    "id": "TEXT",
    "provider_name": "TEXT",
    "status": "TEXT",
    "reason": "TEXT",
    "operation": "TEXT",
    "error_type": "TEXT",
    "consecutive_errors": "INTEGER NOT NULL DEFAULT 0",
    "observed_at": "TEXT",
    "unhealthy_until": "TEXT",
    "recovered_at": "TEXT",
    "source": "TEXT",
    "created_at": "TEXT",
    "updated_at": "TEXT",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None = None) -> str:
    value = dt or _utc_now()
    return value.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _ensure_column(conn, column_name: str, sql_type: str) -> None:
    existing = {
        str(row[1])
        for row in conn.execute(text(f"PRAGMA table_info({TABLE_NAME})")).fetchall()
    }
    if column_name in existing:
        return
    conn.execute(text(f"ALTER TABLE {TABLE_NAME} ADD COLUMN {column_name} {sql_type}"))


def ensure_provider_health_table(target_engine: Engine | None = None) -> None:
    """Create/upgrade provider_health_events idempotently."""
    if target_engine is None:
        from database import engine as target_engine  # lazy to avoid import cycles

    with target_engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS provider_health_events (
                id TEXT PRIMARY KEY,
                provider_name TEXT NOT NULL,
                status TEXT NOT NULL,
                reason TEXT,
                operation TEXT,
                error_type TEXT,
                consecutive_errors INTEGER NOT NULL DEFAULT 0,
                observed_at TEXT NOT NULL,
                unhealthy_until TEXT,
                recovered_at TEXT,
                source TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """))
        for column_name, sql_type in COLUMN_SQL_TYPES.items():
            _ensure_column(conn, column_name, sql_type)
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_provider_health_events_provider_observed
            ON provider_health_events(provider_name, observed_at)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_provider_health_events_status
            ON provider_health_events(status, recovered_at)
        """))


@dataclass(slots=True)
class ProviderHealthRegistry:
    session_factory: Callable[[], Session]
    ttl_seconds: int = 300
    source: str = "market_data_aggregator"

    def mark_unhealthy(
        self,
        provider_name: str,
        *,
        reason: str,
        operation: str | None = None,
        error_type: str | None = None,
        consecutive_errors: int = 0,
        ttl_seconds: int | None = None,
    ) -> None:
        provider = _normalise_provider_name(provider_name)
        now = _utc_now()
        unhealthy_until = now + timedelta(
            seconds=max(10, int(ttl_seconds if ttl_seconds is not None else self.ttl_seconds))
        )
        db = self.session_factory()
        try:
            ensure_provider_health_table(db.get_bind())
            db.execute(text("""
                INSERT INTO provider_health_events (
                    id, provider_name, status, reason, operation, error_type,
                    consecutive_errors, observed_at, unhealthy_until, recovered_at,
                    source, created_at, updated_at
                ) VALUES (
                    :id, :provider_name, 'unhealthy', :reason, :operation,
                    :error_type, :consecutive_errors, :observed_at,
                    :unhealthy_until, NULL, :source, :created_at, :updated_at
                )
            """), {
                "id": str(uuid4()),
                "provider_name": provider,
                "reason": _clip(str(reason or ""), 1000),
                "operation": _clip(operation, 255),
                "error_type": _clip(error_type, 120),
                "consecutive_errors": max(0, int(consecutive_errors or 0)),
                "observed_at": _iso(now),
                "unhealthy_until": _iso(unhealthy_until),
                "source": self.source,
                "created_at": _iso(now),
                "updated_at": _iso(now),
            })
            db.commit()
        except Exception:  # noqa: BLE001 - health logging must never break pricing
            db.rollback()
        finally:
            db.close()

    def mark_healthy(
        self,
        provider_name: str,
        *,
        operation: str | None = None,
    ) -> None:
        provider = _normalise_provider_name(provider_name)
        now = _utc_now()
        db = self.session_factory()
        try:
            ensure_provider_health_table(db.get_bind())
            db.execute(text("""
                UPDATE provider_health_events
                SET status = 'recovered',
                    recovered_at = COALESCE(recovered_at, :recovered_at),
                    operation = COALESCE(operation, :operation),
                    updated_at = :updated_at
                WHERE provider_name = :provider_name
                  AND status = 'unhealthy'
                  AND recovered_at IS NULL
            """), {
                "provider_name": provider,
                "operation": _clip(operation, 255),
                "recovered_at": _iso(now),
                "updated_at": _iso(now),
            })
            db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
        finally:
            db.close()


def build_default_registry() -> ProviderHealthRegistry:
    from config import settings
    from database import SessionLocal

    return ProviderHealthRegistry(
        session_factory=SessionLocal,
        ttl_seconds=int(getattr(settings, "market_data_unhealthy_ttl_seconds", 300) or 300),
    )


def list_provider_health(
    db: Session,
    *,
    provider_names: Iterable[str] | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    ensure_provider_health_table(db.get_bind())
    params: dict[str, Any] = {"limit": max(1, min(int(limit), 500))}
    where = ""
    names = [_normalise_provider_name(name) for name in provider_names or [] if str(name or "").strip()]
    if names:
        placeholders = []
        for index, name in enumerate(names):
            key = f"name_{index}"
            params[key] = name
            placeholders.append(f":{key}")
        where = f"WHERE provider_name IN ({', '.join(placeholders)})"
    rows = db.execute(text(f"""
        SELECT id, provider_name, status, reason, operation, error_type,
               consecutive_errors, observed_at, unhealthy_until, recovered_at,
               source, created_at, updated_at
        FROM provider_health_events
        {where}
        ORDER BY observed_at DESC, updated_at DESC, rowid DESC
        LIMIT :limit
    """), params).mappings().all()
    return [dict(row) for row in rows]


def latest_provider_health_by_name(
    db: Session,
    provider_names: Iterable[str] | None = None,
) -> dict[str, dict[str, Any]]:
    events = list_provider_health(db, provider_names=provider_names, limit=500)
    latest: dict[str, dict[str, Any]] = {}
    for event in events:
        name = str(event.get("provider_name") or "")
        if name and name not in latest:
            latest[name] = event
    return latest


def reset_provider_health(db: Session, provider_name: str | None = None) -> int:
    ensure_provider_health_table(db.get_bind())
    provider = _normalise_provider_name(provider_name) if provider_name else None
    if provider:
        result = db.execute(
            text("DELETE FROM provider_health_events WHERE provider_name = :provider_name"),
            {"provider_name": provider},
        )
    else:
        result = db.execute(text("DELETE FROM provider_health_events"))
    return int(result.rowcount or 0)


def _normalise_provider_name(provider_name: str | None) -> str:
    return str(provider_name or "unknown").strip().lower() or "unknown"


def _clip(value: str | None, max_len: int) -> str | None:
    if value is None:
        return None
    raw = str(value)
    return raw[:max_len]
