"""Guard tests for the pytest session-end leak report (Teardown-Hang-Befund 2026-10-20).

Positive controls first: a guard that never reports anything would also be
"green". Then the real shutdown path: the FastAPI lifespan starts the price-
and backup-APScheduler and must leave neither a running scheduler nor a
non-daemon thread behind once the TestClient context is closed.
"""
from __future__ import annotations

import sys
import threading
from types import SimpleNamespace

import pytest

from tests import _session_leak_guard as guard


def _start(daemon: bool) -> tuple[threading.Thread, threading.Event]:
    release = threading.Event()
    thread = threading.Thread(target=release.wait, name=f"leak-probe-daemon={daemon}", daemon=daemon)
    thread.start()
    return thread, release


def test_non_daemon_thread_is_reported_until_joined():
    thread, release = _start(daemon=False)
    try:
        assert any(entry.startswith("leak-probe-daemon=False") for entry in guard.find_leaked_threads())
    finally:
        release.set()
        thread.join(timeout=5)
    assert not thread.is_alive()
    assert not any(entry.startswith("leak-probe-daemon=False") for entry in guard.find_leaked_threads())


def test_daemon_thread_is_not_reported():
    thread, release = _start(daemon=True)
    try:
        assert not any(entry.startswith("leak-probe-daemon=True") for entry in guard.find_leaked_threads())
    finally:
        release.set()
        thread.join(timeout=5)


def test_running_product_scheduler_is_reported(monkeypatch):
    monkeypatch.setitem(sys.modules, "price_updater", SimpleNamespace(scheduler=SimpleNamespace(running=True)))
    monkeypatch.setitem(sys.modules, "backup_scheduler", SimpleNamespace(_scheduler=SimpleNamespace(running=False)))
    assert guard.find_running_schedulers() == ("price_updater.scheduler",)
    report = guard.collect()
    assert not report.empty
    assert "Scheduler laeuft noch: price_updater.scheduler" in report.lines()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("", guard.DEFAULT_WATCHDOG_SECONDS), ("0", 0.0), ("15", 15.0), ("abc", guard.DEFAULT_WATCHDOG_SECONDS), ("-3", 0.0)],
)
def test_watchdog_seconds_parsing(monkeypatch, raw, expected):
    monkeypatch.setenv(guard.WATCHDOG_ENV, raw)
    assert guard.watchdog_seconds() == expected


def test_lifespan_shutdown_leaves_no_scheduler_or_non_daemon_thread():
    from fastapi.testclient import TestClient

    import backup_scheduler
    import price_updater
    from config import settings
    from main import app

    before = set(guard.find_leaked_threads())
    with TestClient(app):
        # Positive control: with the default settings the lifespan really
        # starts both schedulers -- otherwise this test would prove nothing.
        if settings.price_scheduler_enabled:
            assert price_updater.scheduler is not None and price_updater.scheduler.running
        if settings.backup_enabled and settings.backup_scheduler_enabled:
            assert backup_scheduler._scheduler is not None and backup_scheduler._scheduler.running
    assert guard.find_running_schedulers() == ()
    assert set(guard.find_leaked_threads()) - before == set()
