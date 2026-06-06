"""Sprint U-31 (2026-06-06): Drift-Schutz fuer Daily Market Data Refresh-Wiring."""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for path in (BACKEND_ROOT, TESTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

REPO_ROOT = Path(__file__).resolve().parents[2]
DAILY_MD_DOC = REPO_ROOT / "docs" / "DAILY_MARKET_DATA.md"
PRICE_UPDATER = BACKEND_ROOT / "price_updater.py"


def test_doc_exists():
    assert DAILY_MD_DOC.exists()


def test_settings_have_daily_refresh_config():
    from config import settings
    assert hasattr(settings, "market_data_daily_refresh_enabled")
    assert hasattr(settings, "market_data_daily_refresh_hour")
    assert hasattr(settings, "market_data_daily_refresh_minute")
    assert hasattr(settings, "market_data_daily_refresh_max_symbols")


def test_settings_default_enabled_true():
    from config import settings
    assert settings.market_data_daily_refresh_enabled is True


def test_settings_default_hour_in_range():
    from config import settings
    assert 0 <= int(settings.market_data_daily_refresh_hour) <= 23


def test_run_daily_market_data_refresh_callable():
    from services.market_data_daily_refresh import run_daily_market_data_refresh
    assert callable(run_daily_market_data_refresh)


def test_price_updater_registers_market_data_jobs():
    text = PRICE_UPDATER.read_text(encoding="utf-8")
    assert "_register_market_data_jobs" in text
    assert "daily_market_data_refresh" in text


def test_price_updater_has_market_data_wrapper():
    text = PRICE_UPDATER.read_text(encoding="utf-8")
    assert "_daily_market_data_refresh_wrapper" in text


def test_doc_documents_3_refresh_types():
    text = DAILY_MD_DOC.read_text(encoding="utf-8")
    assert "Produkt-Preise" in text
    assert "Asset-Class-Proxy-Preise" in text or "Asset-Class" in text
    assert "FX-Reihen" in text or "FX" in text


def test_doc_documents_admin_recovery_trigger():
    text = DAILY_MD_DOC.read_text(encoding="utf-8")
    assert "POST /admin/system/market-data/refresh-now" in text


def test_doc_documents_fx_only_trigger():
    text = DAILY_MD_DOC.read_text(encoding="utf-8")
    assert "fx-rates/refresh-now" in text  # U-99-Trigger
    assert "U-99" in text


def test_doc_documents_settings_with_env_overrides():
    text = DAILY_MD_DOC.read_text(encoding="utf-8")
    assert "MARKET_DATA_DAILY_REFRESH_ENABLED" in text
    assert "MARKET_DATA_DAILY_REFRESH_HOUR" in text


def test_doc_documents_cost_discipline_chf_0():
    text = DAILY_MD_DOC.read_text(encoding="utf-8")
    assert "CHF 0" in text
    assert "ADR-005" in text


def test_doc_documents_providers():
    text = DAILY_MD_DOC.read_text(encoding="utf-8")
    for provider in ("yfinance", "Stooq", "AlphaVantage"):
        assert provider in text


def test_doc_documents_bewusst_nicht_in_scope():
    text = DAILY_MD_DOC.read_text(encoding="utf-8")
    assert "Bewusst NICHT" in text
    assert "Echtzeit" in text or "Intraday" in text


def test_doc_documents_health_diagnose():
    text = DAILY_MD_DOC.read_text(encoding="utf-8")
    assert "provider-health" in text or "Health" in text
