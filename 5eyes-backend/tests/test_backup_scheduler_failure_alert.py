"""BACKUP-FAILURE-SILENT-LOG-ONLY-001 (Kontrollrunde 2026-09-27).

_run_backup_job() fing bisher jeden Backup-Fehler mit `except Exception:
logger.exception(...)` -- kein Mechanismus informierte den Betreiber aktiv.
Bei einem Tier-1-Self-Hosted-Betrieb (kein zentrales Log-Monitoring) koennten
Backups wochenlang ausfallen, ohne dass es jemand bemerkt.

Fix: opt-in Webhook-Alert (derselbe Mechanismus wie services/market_data/
notifier.py, P22) bei (a) fehlgeschlagenem lokalem Backup und (b)
fehlgeschlagener Offsite-Replikation. Default (settings.backup_alert_
webhook_url leer) bleibt No-Op -- kein Verhaltenswechsel fuer bestehende
Installationen ohne konfigurierten Webhook.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import backup_scheduler
from services.backup import BackupResult, OffsiteReplicationResult


def _make_backup_result(**overrides) -> BackupResult:
    from datetime import datetime, timezone

    defaults = dict(
        path=Path("/tmp/backup-2026-09-27.db"),
        bytes_written=1024,
        sha256="deadbeef",
        timestamp=datetime.now(timezone.utc),
        retained_files=3,
        pruned_files=0,
    )
    defaults.update(overrides)
    return BackupResult(**defaults)


@pytest.fixture(autouse=True)
def _reset_settings(monkeypatch):
    """Isoliert jeden Test von der echten .env-Konfiguration."""
    monkeypatch.setattr(backup_scheduler.settings, "backup_alert_webhook_url", "")
    monkeypatch.setattr(backup_scheduler.settings, "backup_offsite_enabled", False)


def test_alert_is_noop_when_webhook_not_configured(monkeypatch):
    """Default (kein Webhook konfiguriert): kein POST-Versuch, egal was passiert."""
    calls = []
    monkeypatch.setattr(
        "services.market_data.notifier.post_alert",
        lambda *a, **kw: calls.append((a, kw)),
    )
    backup_scheduler._alert_backup_problem(text="x", detail="y")
    assert calls == []


def test_alert_posts_webhook_when_configured(monkeypatch):
    monkeypatch.setattr(backup_scheduler.settings, "backup_alert_webhook_url", "https://hooks.example/alert")
    calls = []
    monkeypatch.setattr(
        "services.market_data.notifier.post_alert",
        lambda url, payload, timeout_seconds=None: calls.append((url, payload, timeout_seconds)),
    )
    backup_scheduler._alert_backup_problem(text="Backup fehlgeschlagen", detail="boom")
    assert len(calls) == 1
    url, payload, timeout = calls[0]
    assert url == "https://hooks.example/alert"
    assert payload["text"] == "Backup fehlgeschlagen"
    assert payload["detail"] == "boom"


def test_alert_never_raises_even_if_post_alert_itself_raises(monkeypatch):
    """_alert_backup_problem() wird aus einem except-Block heraus aufgerufen
    -- eine hier durchschlagende Exception wuerde den Scheduler-Job crashen,
    genau das soll dieser Guard verhindern."""
    monkeypatch.setattr(backup_scheduler.settings, "backup_alert_webhook_url", "https://hooks.example/alert")

    def _boom(*a, **kw):
        raise RuntimeError("webhook client exploded")

    monkeypatch.setattr("services.market_data.notifier.post_alert", _boom)
    backup_scheduler._alert_backup_problem(text="x", detail="y")  # must not raise


def test_run_backup_job_alerts_on_local_backup_failure(monkeypatch):
    monkeypatch.setattr(backup_scheduler.settings, "backup_alert_webhook_url", "https://hooks.example/alert")

    def _boom(**kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr("services.backup.backup_database", _boom)
    calls = []
    monkeypatch.setattr(
        "services.market_data.notifier.post_alert",
        lambda url, payload, timeout_seconds=None: calls.append(payload),
    )

    backup_scheduler._run_backup_job()  # must not raise

    assert len(calls) == 1
    assert "fehlgeschlagen" in calls[0]["text"]
    assert "disk full" in calls[0]["detail"]


def test_run_backup_job_no_alert_on_success_without_offsite(monkeypatch):
    monkeypatch.setattr(backup_scheduler.settings, "backup_alert_webhook_url", "https://hooks.example/alert")
    monkeypatch.setattr("services.backup.backup_database", lambda **kwargs: _make_backup_result())
    calls = []
    monkeypatch.setattr(
        "services.market_data.notifier.post_alert",
        lambda url, payload, timeout_seconds=None: calls.append(payload),
    )

    backup_scheduler._run_backup_job()

    assert calls == []


def test_run_backup_job_alerts_on_offsite_replication_failure(monkeypatch):
    monkeypatch.setattr(backup_scheduler.settings, "backup_alert_webhook_url", "https://hooks.example/alert")
    monkeypatch.setattr(backup_scheduler.settings, "backup_offsite_enabled", True)
    monkeypatch.setattr("services.backup.backup_database", lambda **kwargs: _make_backup_result())
    monkeypatch.setattr(
        "services.backup.replicate_offsite",
        lambda *a, **kw: OffsiteReplicationResult(ok=False, target="host:/path", detail="ssh timeout"),
    )
    calls = []
    monkeypatch.setattr(
        "services.market_data.notifier.post_alert",
        lambda url, payload, timeout_seconds=None: calls.append(payload),
    )

    backup_scheduler._run_backup_job()

    assert len(calls) == 1
    assert "Offsite" in calls[0]["text"]
    assert "ssh timeout" in calls[0]["detail"]


def test_run_backup_job_no_alert_on_successful_offsite_replication(monkeypatch):
    monkeypatch.setattr(backup_scheduler.settings, "backup_alert_webhook_url", "https://hooks.example/alert")
    monkeypatch.setattr(backup_scheduler.settings, "backup_offsite_enabled", True)
    monkeypatch.setattr("services.backup.backup_database", lambda **kwargs: _make_backup_result())
    monkeypatch.setattr(
        "services.backup.replicate_offsite",
        lambda *a, **kw: OffsiteReplicationResult(ok=True, target="host:/path", detail="ok"),
    )
    calls = []
    monkeypatch.setattr(
        "services.market_data.notifier.post_alert",
        lambda url, payload, timeout_seconds=None: calls.append(payload),
    )

    backup_scheduler._run_backup_job()

    assert calls == []
