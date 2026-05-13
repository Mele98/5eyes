"""APScheduler-Hooks fuer den Multi-Source-Aggregator (P13).

Zwei Jobs:
- daily_cache_purge_job(): loescht expired Cache-Eintraege (z.B. 03:00 UTC)
- weekly_validation_job(): laeuft Cross-Validation fuer eine konfigurierbare
  Symbol-Liste, schreibt market_data_validation_log (z.B. So 04:00 UTC)

Diese Jobs werden vom price_updater bereits genutzten APScheduler
registriert (siehe price_updater.start_price_scheduler). Falls dort
keine Hook-Slots sind, kann das Modul standalone laufen.
"""
from __future__ import annotations

import logging
from datetime import date as Date
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable

logger = logging.getLogger(__name__)


def daily_cache_purge_job(
    session_factory: Callable[[], object],
) -> int:
    """Purge expired Cache-Eintraege. Returns Count geloeschter Eintraege."""
    from .cache import CachedAggregator
    from .factory import build_default_aggregator
    # Wir bauen einen leichten Wrapper nur fuer Cache-Methoden (Aggregator
    # selbst wird hier nicht aufgerufen).
    cached = CachedAggregator(
        base=build_default_aggregator(),
        session_factory=session_factory,
    )
    purged = cached.purge_expired()
    logger.info("daily_cache_purge_job: %d expired entries removed", purged)
    return purged


def weekly_validation_job(
    symbols: Iterable[str],
    session_factory: Callable[[], object],
    on_date: Date | None = None,
    threshold_bps: int = 300,
    webhook_url: str | None = None,
    webhook_timeout_seconds: float | None = None,
) -> tuple[int, int]:
    """Cross-Validation fuer eine Liste von Symbolen.

    Returns (n_checked, n_alerts).

    Wenn webhook_url gesetzt UND mindestens 1 Alert -> POST an Webhook
    (siehe services.market_data.notifier).
    """
    from .factory import build_default_aggregator
    from .notifier import notify_validation_alerts, DEFAULT_TIMEOUT_SECONDS
    from .validation import validate_batch

    target_date = on_date or (
        datetime.now(timezone.utc).date() - timedelta(days=1)
    )
    aggregator = build_default_aggregator()
    providers = aggregator.providers

    db = session_factory()
    try:
        results = validate_batch(
            symbols=list(symbols),
            on_date=target_date,
            providers=providers,
            threshold_bps=threshold_bps,
            db=db,
        )
    finally:
        try:
            db.close()
        except Exception:  # noqa: BLE001
            pass

    n_alerts = sum(1 for r in results if r.is_alert)
    logger.info(
        "weekly_validation_job: checked=%d alerts=%d on_date=%s",
        len(results), n_alerts, target_date,
    )

    if webhook_url:
        try:
            _, sent = notify_validation_alerts(
                results,
                webhook_url=webhook_url,
                threshold_bps=threshold_bps,
                on_date=target_date.isoformat(),
                timeout_seconds=(
                    webhook_timeout_seconds
                    if webhook_timeout_seconds is not None
                    else DEFAULT_TIMEOUT_SECONDS
                ),
            )
            if n_alerts > 0:
                logger.info(
                    "weekly_validation_job: webhook sent=%s for %d alerts",
                    sent, n_alerts,
                )
        except Exception:  # noqa: BLE001
            logger.exception("weekly_validation_job: webhook dispatch failed")

    return len(results), n_alerts
