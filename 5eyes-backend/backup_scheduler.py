"""Sprint U-8 (2026-05-30): APScheduler-Hook fuer taegliche DB-Backups.

Analog `price_updater.start_price_scheduler` — eigener BackgroundScheduler
fuer DB-Backups. Bewusst getrennt gehalten, damit:
- Backup-Probleme nicht das Price-Refresh-Setup beruehren
- start/stop unabhaengig via main.py-lifecycle steuerbar sind
- der Scheduler im Test-Pfad einfach abschaltbar ist

Eintrag-Point: `start_backup_scheduler()` aus main.py lifespan.
"""
from __future__ import annotations

import logging
from typing import Any

from config import settings

logger = logging.getLogger(__name__)

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
except ImportError:
    BackgroundScheduler = None  # type: ignore[assignment]
    CronTrigger = None  # type: ignore[assignment]


_scheduler: Any | None = None


def _run_backup_job() -> None:
    """APScheduler-Wrapper: lazy-import + Exceptions schlucken, damit ein
    Backup-Fehler den Scheduler nicht killt."""
    try:
        from services.backup import backup_database, replicate_offsite

        result = backup_database(
            target_dir=settings.backup_dir,
            source_db_path=settings.db_path,
            retain_days=settings.backup_retain_days,
            keep_minimum=settings.backup_keep_minimum,
        )
        logger.info(
            "Scheduled DB-backup ok | path=%s bytes=%d retained=%d pruned=%d",
            result.path,
            result.bytes_written,
            result.retained_files,
            result.pruned_files,
        )

        # Roadmap #15 (Off-Site-Backup-Replikation): erst NACH einem
        # erfolgreichen lokalen Backup versuchen, das lokale Backup ist die
        # primaere Schutzmassnahme und darf nie von einem Offsite-Problem
        # abhaengen (replicate_offsite() wirft nie, siehe Docstring dort).
        if settings.backup_offsite_enabled:
            offsite = replicate_offsite(
                result.path,
                settings.backup_offsite_target,
                ssh_key_path=settings.backup_offsite_ssh_key_path,
                ssh_port=settings.backup_offsite_ssh_port,
                timeout_seconds=settings.backup_offsite_timeout_seconds,
            )
            if offsite.ok:
                logger.info("Scheduled offsite-backup-replication ok | target=%s", offsite.target)
            else:
                logger.warning(
                    "Scheduled offsite-backup-replication failed | target=%s detail=%s",
                    offsite.target, offsite.detail,
                )
    except Exception:  # noqa: BLE001 — Scheduler soll nicht crashen
        logger.exception("Scheduled DB-backup failed")


def start_backup_scheduler() -> None:
    """Startet den taeglichen Backup-Job. No-Op wenn deaktiviert oder
    APScheduler nicht installiert.

    Idempotent: zweiter Aufruf laesst den bestehenden Scheduler in Ruhe.
    """
    global _scheduler

    if not settings.backup_enabled or not settings.backup_scheduler_enabled:
        logger.info("Backup scheduler disabled by configuration")
        return

    if BackgroundScheduler is None or CronTrigger is None:
        logger.warning(
            "APScheduler ist nicht installiert. Backup-Scheduler bleibt deaktiviert."
        )
        return

    if _scheduler and _scheduler.running:
        return

    _scheduler = BackgroundScheduler(
        timezone=settings.backup_scheduler_timezone,
        job_defaults={"coalesce": True, "max_instances": 1},
    )
    _scheduler.add_job(
        _run_backup_job,
        trigger=CronTrigger(
            hour=settings.backup_scheduler_hour,
            minute=settings.backup_scheduler_minute,
            timezone=settings.backup_scheduler_timezone,
        ),
        id="daily_db_backup",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info(
        "Backup scheduler started for %02d:%02d %s -> %s",
        settings.backup_scheduler_hour,
        settings.backup_scheduler_minute,
        settings.backup_scheduler_timezone,
        settings.backup_dir,
    )


def stop_backup_scheduler() -> None:
    """Stoppt den Scheduler sauber (no-wait). Idempotent."""
    global _scheduler

    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
    _scheduler = None
