"""Health-aware purge for persisted market-data cache entries.

Phase 2 keeps the purge passive: it only removes expired cache rows and
skips rows whose cached provider is currently marked unhealthy. It does
not refresh prices, tune provider routing, or trigger rebalancing.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from database import ensure_purge_history_table
from models.market_data_cache import MarketDataCacheEntry
from services.market_data.provider_health_registry import latest_provider_health_by_name

logger = logging.getLogger(__name__)


def run_daily_cache_purge(db: Session) -> dict[str, Any]:
    """Purge expired cache entries, skipping currently unhealthy providers."""
    started_at = _utc_now_iso()
    started_perf = time.perf_counter()
    errors: list[dict[str, str]] = []
    purged_rows = 0
    skipped_providers: set[str] = set()

    try:
        ensure_purge_history_table(db.get_bind())
        now = datetime.now(timezone.utc)
        now_iso = _utc_now_iso(now)
        unhealthy = _active_unhealthy_providers(db, now)

        expired_rows = (
            db.query(MarketDataCacheEntry)
            .filter(MarketDataCacheEntry.expires_at <= now_iso)
            .all()
        )
        for row in expired_rows:
            providers = _providers_from_cache_value(row.value_json)
            blocked = providers.intersection(unhealthy)
            if blocked:
                skipped_providers.update(blocked)
                continue
            db.delete(row)
            purged_rows += 1

        finished_at = _utc_now_iso()
        report = _report(
            purged_rows=purged_rows,
            skipped_providers=sorted(skipped_providers),
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=time.perf_counter() - started_perf,
            errors=errors,
        )
        _insert_purge_history(db, report)
        db.commit()
        logger.info(
            "Daily market-data cache purge complete: purged=%d skipped_providers=%s",
            purged_rows,
            ",".join(report["skipped_providers"]) or "-",
        )
        return report
    except Exception as exc:  # noqa: BLE001 - scheduler/admin recovery must not crash
        logger.exception("Daily market-data cache purge failed")
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        errors.append({
            "scope": "market_data_cache",
            "reason": str(exc),
            "error_type": exc.__class__.__name__,
        })
        finished_at = _utc_now_iso()
        report = _report(
            purged_rows=0,
            skipped_providers=sorted(skipped_providers),
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=time.perf_counter() - started_perf,
            errors=errors,
        )
        try:
            ensure_purge_history_table(db.get_bind())
            _insert_purge_history(db, report)
            db.commit()
        except Exception:  # noqa: BLE001
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass
        return report


def list_purge_history(db: Session, *, limit: int = 20) -> list[dict[str, Any]]:
    """Return newest purge-history entries in descending order."""
    ensure_purge_history_table(db.get_bind())
    rows = db.execute(text("""
        SELECT id, started_at, finished_at, purged_rows,
               skipped_providers_json, duration_seconds, errors_json
        FROM market_data_purge_history
        ORDER BY started_at DESC, id DESC
        LIMIT :limit
    """), {"limit": max(1, min(int(limit), 200))}).mappings().all()
    return [_history_row_to_dict(dict(row)) for row in rows]


def _active_unhealthy_providers(db: Session, now: datetime) -> set[str]:
    latest = latest_provider_health_by_name(db)
    unhealthy: set[str] = set()
    for provider_name, event in latest.items():
        if str(event.get("status") or "").strip().lower() != "unhealthy":
            continue
        if event.get("recovered_at"):
            continue
        unhealthy_until = _parse_iso(str(event.get("unhealthy_until") or ""))
        if unhealthy_until is not None and unhealthy_until <= now:
            continue
        unhealthy.add(_normalise_provider_name(provider_name))
    return unhealthy


def _providers_from_cache_value(value_json: str | None) -> set[str]:
    try:
        payload = json.loads(value_json or "")
    except Exception:  # noqa: BLE001 - corrupt expired cache rows can be purged
        return set()

    providers: set[str] = set()
    if isinstance(payload, dict):
        _add_provider(providers, payload.get("source"))
    elif isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                _add_provider(providers, item.get("source"))
    return providers


def _add_provider(providers: set[str], source: Any) -> None:
    raw = str(source or "").strip().lower()
    if not raw:
        return
    providers.add(_normalise_provider_name(raw.split(":", 1)[0]))


def _insert_purge_history(db: Session, report: dict[str, Any]) -> None:
    ensure_purge_history_table(db.get_bind())
    db.execute(text("""
        INSERT INTO market_data_purge_history (
            started_at, finished_at, purged_rows, skipped_providers_json,
            duration_seconds, errors_json
        ) VALUES (
            :started_at, :finished_at, :purged_rows, :skipped_providers_json,
            :duration_seconds, :errors_json
        )
    """), {
        "started_at": report["started_at"],
        "finished_at": report["finished_at"],
        "purged_rows": int(report["purged_rows"]),
        "skipped_providers_json": json.dumps(report["skipped_providers"], ensure_ascii=True),
        "duration_seconds": float(report["duration_seconds"]),
        "errors_json": json.dumps(report["errors"], ensure_ascii=True),
    })


def _history_row_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "started_at": row.get("started_at"),
        "finished_at": row.get("finished_at"),
        "purged_rows": int(row.get("purged_rows") or 0),
        "skipped_providers": _loads_list(row.get("skipped_providers_json")),
        "duration_seconds": float(row.get("duration_seconds") or 0.0),
        "errors": _loads_list(row.get("errors_json")),
    }


def _loads_list(value: Any) -> list[Any]:
    try:
        parsed = json.loads(str(value or "[]"))
    except Exception:  # noqa: BLE001
        return []
    return parsed if isinstance(parsed, list) else []


def _report(
    *,
    purged_rows: int,
    skipped_providers: list[str],
    started_at: str,
    finished_at: str,
    duration_seconds: float,
    errors: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "purged_rows": int(purged_rows),
        "skipped_providers": skipped_providers,
        "duration_seconds": round(float(duration_seconds), 6),
        "started_at": started_at,
        "finished_at": finished_at,
        "errors": errors,
    }


def _parse_iso(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _utc_now_iso(value: datetime | None = None) -> str:
    dt = value or datetime.now(timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _normalise_provider_name(provider_name: str | None) -> str:
    return str(provider_name or "unknown").strip().lower() or "unknown"
