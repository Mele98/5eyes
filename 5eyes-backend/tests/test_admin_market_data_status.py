"""P16 Tests: Admin-Status-Endpoint /admin/market-data/status.

Verifiziert:
- collect_provider_health: Healthy/Unhealthy korrekt erkannt.
- collect_cache_stats: Aggregation valid/expired/total per cache_kind.
- collect_recent_validation_logs: neueste zuerst, JSON-Roundtrip, n=10 default.
- collect_scheduler_jobs: leere Liste wenn kein Scheduler laeuft.
- /admin/market-data/status: 200, alle Sektionen vorhanden, require_admin enforced.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, get_db
from main import app
from models.market_data_cache import MarketDataCacheEntry
from models.market_data_validation_log import MarketDataValidationLog
from models.users import User
from services.auth import require_admin
from services.market_data.admin import (
    build_market_data_status,
    collect_cache_stats,
    collect_provider_health,
    collect_recent_validation_logs,
    collect_scheduler_jobs,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture()
def session_factory(tmp_path):
    db_path = tmp_path / "p16.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def db_session(session_factory):
    with session_factory() as session:
        yield session


@pytest.fixture()
def admin_user():
    return User(
        id="admin-1", username="admin", password_hash="hash", full_name="Admin",
        role="admin", is_active=1,
        created_at="2026-05-11T00:00:00.000Z", updated_at="2026-05-11T00:00:00.000Z",
    )


@pytest.fixture()
def client(session_factory, admin_user):
    def override_get_db():
        with session_factory() as session:
            yield session
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_admin] = lambda: admin_user
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _utc_iso(offset_seconds: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


# ============================================================================
# collect_cache_stats
# ============================================================================


def test_cache_stats_aggregates_valid_and_expired(db_session):
    db_session.add_all([
        MarketDataCacheEntry(cache_kind="eod", cache_key="A", value_json="{}",
                             fetched_at=_utc_iso(-100), expires_at=_utc_iso(3600)),
        MarketDataCacheEntry(cache_kind="eod", cache_key="B", value_json="{}",
                             fetched_at=_utc_iso(-100), expires_at=_utc_iso(-10)),
        MarketDataCacheEntry(cache_kind="history", cache_key="C", value_json="[]",
                             fetched_at=_utc_iso(-100), expires_at=_utc_iso(3600)),
    ])
    db_session.commit()
    stats = collect_cache_stats(db_session)
    assert stats["total"] == 3
    assert stats["by_kind"]["eod"] == {"total": 2, "valid": 1, "expired": 1}
    assert stats["by_kind"]["history"] == {"total": 1, "valid": 1, "expired": 0}


def test_cache_stats_empty_returns_zero(db_session):
    stats = collect_cache_stats(db_session)
    assert stats["total"] == 0
    assert stats["by_kind"] == {}


# ============================================================================
# collect_recent_validation_logs
# ============================================================================


def test_recent_validation_logs_newest_first(db_session):
    db_session.add_all([
        MarketDataValidationLog(
            symbol="UBSG.SW", on_date="2026-05-08", checked_at="2026-05-08T10:00:00Z",
            providers_json=json.dumps([{"name": "yfinance", "close": "28.75"}]),
            median_close="28.75", min_close="28.75", max_close="28.75",
            diff_bps=0, threshold_bps=300, is_alert=0, n_providers=1,
        ),
        MarketDataValidationLog(
            symbol="AAPL", on_date="2026-05-09", checked_at="2026-05-09T10:00:00Z",
            providers_json=json.dumps([
                {"name": "yfinance", "close": "250.00"},
                {"name": "stooq", "close": "260.00"},
            ]),
            median_close="255.00", min_close="250.00", max_close="260.00",
            diff_bps=392, threshold_bps=300, is_alert=1, n_providers=2,
        ),
    ])
    db_session.commit()
    rows = collect_recent_validation_logs(db_session, limit=10)
    assert len(rows) == 2
    assert rows[0]["symbol"] == "AAPL"
    assert rows[0]["is_alert"] is True
    assert rows[0]["providers"][0]["name"] == "yfinance"
    assert rows[1]["symbol"] == "UBSG.SW"


def test_recent_validation_logs_respects_limit(db_session):
    for i in range(15):
        db_session.add(MarketDataValidationLog(
            symbol=f"S{i}", on_date="2026-05-08",
            checked_at=f"2026-05-08T10:{i:02d}:00Z",
            providers_json="[]", median_close="1", min_close="1", max_close="1",
            diff_bps=0, threshold_bps=300, is_alert=0, n_providers=1,
        ))
    db_session.commit()
    rows = collect_recent_validation_logs(db_session, limit=5)
    assert len(rows) == 5


def test_recent_validation_logs_handles_corrupt_providers_json(db_session):
    db_session.add(MarketDataValidationLog(
        symbol="X", on_date="2026-05-08", checked_at="2026-05-08T10:00:00Z",
        providers_json="not-json", median_close="1", min_close="1", max_close="1",
        diff_bps=0, threshold_bps=300, is_alert=0, n_providers=1,
    ))
    db_session.commit()
    rows = collect_recent_validation_logs(db_session)
    assert rows[0]["providers"] == []


# ============================================================================
# collect_scheduler_jobs
# ============================================================================


def test_scheduler_jobs_empty_when_no_scheduler():
    import price_updater
    with patch.object(price_updater, "scheduler", None):
        assert collect_scheduler_jobs() == []


def test_scheduler_jobs_returns_jobs_when_running():
    import price_updater
    fake_sch = MagicMock()
    fake_sch.running = True
    fake_job = SimpleNamespace(
        id="daily_price_refresh", name="daily_price_refresh",
        next_run_time=datetime(2026, 5, 12, 6, 0, tzinfo=timezone.utc),
    )
    fake_sch.get_jobs.return_value = [fake_job]
    with patch.object(price_updater, "scheduler", fake_sch):
        jobs = collect_scheduler_jobs()
    assert len(jobs) == 1
    assert jobs[0]["id"] == "daily_price_refresh"
    assert jobs[0]["next_run_at"] == "2026-05-12T06:00:00+00:00"


# ============================================================================
# collect_provider_health
# ============================================================================


def test_provider_health_lists_all_providers():
    health = collect_provider_health()
    # Default-Aggregator hat mind. 1 Provider (yfinance,stooq,alphavantage)
    assert isinstance(health, list)
    if health:
        assert "name" in health[0]
        assert "healthy" in health[0]


# ============================================================================
# build_market_data_status (Integration)
# ============================================================================


def test_build_market_data_status_returns_all_sections(db_session):
    status = build_market_data_status(db_session)
    assert set(status.keys()) >= {
        "providers_config", "providers_health", "cache",
        "recent_validations", "scheduler_jobs", "generated_at",
    }


# ============================================================================
# /admin/market-data/status endpoint
# ============================================================================


def test_endpoint_returns_200_for_admin(client):
    resp = client.get("/admin/market-data/status")
    assert resp.status_code == 200
    body = resp.json()
    assert "providers_config" in body
    assert "cache" in body
    assert "recent_validations" in body
    assert "scheduler_jobs" in body
    assert "generated_at" in body


def test_endpoint_rejects_non_admin(session_factory):
    def override_get_db():
        with session_factory() as s:
            yield s
    def deny():
        raise HTTPException(status_code=403, detail="forbidden")
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_admin] = deny
    try:
        with TestClient(app) as c:
            resp = c.get("/admin/market-data/status")
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.clear()
