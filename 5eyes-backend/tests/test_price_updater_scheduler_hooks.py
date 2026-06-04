"""P15: Tests fuer market-data-Scheduler-Hooks im price_updater.

Verifiziert:
- _register_market_data_jobs registriert daily_cache_purge wenn enabled.
- weekly_market_data_validation wird nur registriert wenn validation_enabled.
- _daily_cache_purge_wrapper und _weekly_validation_wrapper rufen die
  P13-Hooks korrekt auf, swallowen Exceptions.
- weekly_validation_wrapper skippt wenn keine Symbole konfiguriert.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import price_updater


@pytest.fixture()
def fake_scheduler():
    sch = MagicMock()
    sch.add_job = MagicMock()
    return sch


@pytest.fixture(autouse=True)
def disable_daily_market_data_refresh(monkeypatch):
    monkeypatch.setattr(price_updater.settings, "market_data_daily_refresh_enabled", False)


# ============================================================================
# _register_market_data_jobs — Registrierung
# ============================================================================


def test_cache_purge_registered_when_enabled(monkeypatch, fake_scheduler):
    monkeypatch.setattr(price_updater.settings, "market_data_cache_purge_enabled", True)
    monkeypatch.setattr(price_updater.settings, "market_data_validation_enabled", False)
    price_updater._register_market_data_jobs(fake_scheduler)
    job_ids = [call.kwargs["id"] for call in fake_scheduler.add_job.call_args_list]
    assert "daily_cache_purge" in job_ids
    assert "weekly_market_data_validation" not in job_ids


def test_cache_purge_skipped_when_disabled(monkeypatch, fake_scheduler):
    monkeypatch.setattr(price_updater.settings, "market_data_cache_purge_enabled", False)
    monkeypatch.setattr(price_updater.settings, "market_data_validation_enabled", False)
    price_updater._register_market_data_jobs(fake_scheduler)
    assert fake_scheduler.add_job.call_count == 0


def test_validation_registered_when_enabled(monkeypatch, fake_scheduler):
    monkeypatch.setattr(price_updater.settings, "market_data_cache_purge_enabled", False)
    monkeypatch.setattr(price_updater.settings, "market_data_validation_enabled", True)
    price_updater._register_market_data_jobs(fake_scheduler)
    job_ids = [call.kwargs["id"] for call in fake_scheduler.add_job.call_args_list]
    assert job_ids == ["weekly_market_data_validation"]


def test_both_jobs_registered_when_both_enabled(monkeypatch, fake_scheduler):
    monkeypatch.setattr(price_updater.settings, "market_data_cache_purge_enabled", True)
    monkeypatch.setattr(price_updater.settings, "market_data_validation_enabled", True)
    price_updater._register_market_data_jobs(fake_scheduler)
    job_ids = [call.kwargs["id"] for call in fake_scheduler.add_job.call_args_list]
    assert set(job_ids) == {"daily_cache_purge", "weekly_market_data_validation"}


def test_daily_market_data_refresh_registered_when_enabled(monkeypatch, fake_scheduler):
    monkeypatch.setattr(price_updater.settings, "market_data_cache_purge_enabled", False)
    monkeypatch.setattr(price_updater.settings, "market_data_validation_enabled", False)
    monkeypatch.setattr(price_updater.settings, "market_data_daily_refresh_enabled", True)
    monkeypatch.setattr(price_updater.settings, "market_data_daily_refresh_hour", 6)
    monkeypatch.setattr(price_updater.settings, "market_data_daily_refresh_minute", 15)

    price_updater._register_market_data_jobs(fake_scheduler)

    assert fake_scheduler.add_job.call_count == 1
    call = fake_scheduler.add_job.call_args
    assert call.kwargs["id"] == "daily_market_data_refresh"
    assert call.kwargs["replace_existing"] is True
    assert call.kwargs["misfire_grace_time"] == 7200


def test_register_no_crash_when_crontrigger_missing(monkeypatch, fake_scheduler):
    """Wenn APScheduler nicht installiert ist, soll register() lautlos
    skippen (kein Crash)."""
    monkeypatch.setattr(price_updater, "CronTrigger", None)
    monkeypatch.setattr(price_updater.settings, "market_data_cache_purge_enabled", True)
    monkeypatch.setattr(price_updater.settings, "market_data_validation_enabled", True)
    price_updater._register_market_data_jobs(fake_scheduler)
    assert fake_scheduler.add_job.call_count == 0


# ============================================================================
# Wrapper-Funktionen
# ============================================================================


def test_daily_cache_purge_wrapper_returns_count():
    with patch("services.market_data.daily_cache_purge_job", return_value=7) as job:
        result = price_updater._daily_cache_purge_wrapper()
    assert result == 7
    assert job.call_count == 1


def test_daily_cache_purge_wrapper_swallows_exception():
    with patch("services.market_data.daily_cache_purge_job", side_effect=RuntimeError("db down")):
        result = price_updater._daily_cache_purge_wrapper()
    assert result == 0


def test_weekly_validation_wrapper_passes_symbols(monkeypatch):
    monkeypatch.setattr(
        price_updater.settings, "market_data_validation_symbols",
        "UBSG.SW, AAPL ,MSFT",
    )
    monkeypatch.setattr(
        price_updater.settings, "market_data_validation_threshold_bps", 250,
    )
    with patch(
        "services.market_data.weekly_validation_job",
        return_value=(3, 0),
    ) as job:
        result = price_updater._weekly_validation_wrapper()
    assert result == (3, 0)
    _, kwargs = job.call_args
    assert kwargs["symbols"] == ["UBSG.SW", "AAPL", "MSFT"]
    assert kwargs["threshold_bps"] == 250


def test_weekly_validation_wrapper_skips_empty_symbol_list(monkeypatch):
    monkeypatch.setattr(price_updater.settings, "market_data_validation_symbols", "")
    with patch("services.market_data.weekly_validation_job") as job:
        result = price_updater._weekly_validation_wrapper()
    assert result == (0, 0)
    assert job.call_count == 0  # nie aufgerufen ohne Symbole


def test_weekly_validation_wrapper_swallows_exception(monkeypatch):
    monkeypatch.setattr(price_updater.settings, "market_data_validation_symbols", "X")
    with patch(
        "services.market_data.weekly_validation_job",
        side_effect=RuntimeError("aggregator init failed"),
    ):
        result = price_updater._weekly_validation_wrapper()
    assert result == (0, 0)


def test_daily_market_data_refresh_wrapper_returns_summary():
    expected = {"status": "ok", "products_refreshed": 1}
    with patch(
        "services.market_data_daily_refresh.run_daily_market_data_refresh",
        return_value=expected,
    ) as job:
        result = price_updater._daily_market_data_refresh_wrapper()
    assert result == expected
    assert job.call_count == 1


def test_daily_market_data_refresh_wrapper_swallows_exception():
    with patch(
        "services.market_data_daily_refresh.run_daily_market_data_refresh",
        side_effect=RuntimeError("db down"),
    ):
        result = price_updater._daily_market_data_refresh_wrapper()
    assert result["status"] == "failed"
    assert result["products_refreshed"] == 0
    assert result["errors"]
