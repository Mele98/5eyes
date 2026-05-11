"""P16 — Admin-Status-Service fuer den Multi-Source-Aggregator.

Sammelt Diagnose-Daten:
- Provider-Konfiguration + Health-Status (yfinance, stooq, ...).
- Cache-Stats: Eintraege pro `cache_kind`, abgelaufen vs gueltig.
- Letzte Validation-Log-Eintraege.
- Scheduler-Jobs mit next_run_time (sofern verfuegbar).

Diese Daten werden vom Admin-Endpoint `/admin/market-data/status` ausgeliefert.
Bewusst nicht-invasiv: keine Schreibzugriffe, alle Fehler werden geswallowed
und als 'unavailable'-Marker ausgegeben.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def collect_provider_health() -> list[dict[str, Any]]:
    """Liest Provider-Reihenfolge aus settings und prueft is_healthy()."""
    try:
        from .factory import build_default_aggregator
        agg = build_default_aggregator()
    except Exception as exc:  # noqa: BLE001
        logger.warning("collect_provider_health: build_default_aggregator failed: %s", exc)
        return []
    out: list[dict[str, Any]] = []
    for provider in agg.providers:
        try:
            healthy = bool(provider.is_healthy())
        except Exception:  # noqa: BLE001
            healthy = False
        out.append({"name": getattr(provider, "name", "?"), "healthy": healthy})
    return out


def collect_cache_stats(db: Session) -> dict[str, Any]:
    """Aggregiert Cache-Eintraege per cache_kind in total / valid / expired."""
    from models.market_data_cache import MarketDataCacheEntry  # lazy
    try:
        rows = db.query(
            MarketDataCacheEntry.cache_kind, MarketDataCacheEntry.expires_at,
        ).all()
    except Exception as exc:  # noqa: BLE001
        logger.warning("collect_cache_stats: query failed: %s", exc)
        return {"total": 0, "by_kind": {}, "unavailable": True}
    now_iso = _now_utc_iso()
    by_kind: dict[str, dict[str, int]] = {}
    total = 0
    for kind, expires_at in rows:
        total += 1
        bucket = by_kind.setdefault(str(kind), {"total": 0, "valid": 0, "expired": 0})
        bucket["total"] += 1
        if (expires_at or "") <= now_iso:
            bucket["expired"] += 1
        else:
            bucket["valid"] += 1
    return {"total": total, "by_kind": by_kind}


def collect_recent_validation_logs(db: Session, limit: int = 10) -> list[dict[str, Any]]:
    """Liefert die letzten N Validation-Log-Eintraege (neueste zuerst)."""
    from models.market_data_validation_log import MarketDataValidationLog  # lazy
    try:
        rows = (
            db.query(MarketDataValidationLog)
            .order_by(MarketDataValidationLog.checked_at.desc())
            .limit(max(1, int(limit)))
            .all()
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("collect_recent_validation_logs: query failed: %s", exc)
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        try:
            providers = json.loads(row.providers_json or "[]")
        except (TypeError, ValueError):
            providers = []
        out.append({
            "symbol": row.symbol,
            "on_date": row.on_date,
            "checked_at": row.checked_at,
            "providers": providers,
            "median_close": row.median_close,
            "min_close": row.min_close,
            "max_close": row.max_close,
            "diff_bps": int(row.diff_bps or 0),
            "threshold_bps": int(row.threshold_bps or 0),
            "is_alert": bool(int(row.is_alert or 0)),
            "n_providers": int(row.n_providers or 0),
        })
    return out


def collect_scheduler_jobs() -> list[dict[str, Any]]:
    """Holt aktuelle APScheduler-Jobs aus price_updater.scheduler.
    next_run_time ist ein datetime-Objekt; wird in ISO konvertiert."""
    try:
        import price_updater
    except Exception:  # noqa: BLE001
        return []
    sch = getattr(price_updater, "scheduler", None)
    if sch is None or not getattr(sch, "running", False):
        return []
    out: list[dict[str, Any]] = []
    try:
        jobs = sch.get_jobs()
    except Exception:  # noqa: BLE001
        return []
    for job in jobs:
        next_run = getattr(job, "next_run_time", None)
        out.append({
            "id": getattr(job, "id", "?"),
            "name": getattr(job, "name", None) or getattr(job, "id", "?"),
            "next_run_at": next_run.isoformat() if next_run is not None else None,
        })
    return out


def build_market_data_status(db: Session) -> dict[str, Any]:
    """Aggregiert alle Diagnose-Daten in eine einzige API-Antwort."""
    from config import settings  # lazy fuer Test-Override
    return {
        "providers_config": str(settings.market_data_providers or ""),
        "providers_health": collect_provider_health(),
        "cache": collect_cache_stats(db),
        "recent_validations": collect_recent_validation_logs(db, limit=10),
        "scheduler_jobs": collect_scheduler_jobs(),
        "generated_at": _now_utc_iso(),
    }
