from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import (  # noqa: E402
    Base,
    PURGE_HISTORY_COLUMNS,
    ensure_purge_history_table,
    get_db,
)
from main import app  # noqa: E402
from models.market_data_cache import MarketDataCacheEntry  # noqa: E402
from models.users import User  # noqa: E402
from services.auth import require_admin, require_advisor  # noqa: E402
from services.market_data.cache_purge import (  # noqa: E402
    list_purge_history,
    run_daily_cache_purge,
)
from services.market_data.provider_health_registry import ensure_provider_health_table  # noqa: E402


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'cache_purge.db'}",
        connect_args={"check_same_thread": False},
    )
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    ensure_provider_health_table(engine)
    ensure_purge_history_table(engine)
    return engine, factory


def _user(role: str) -> User:
    return User(
        id=f"{role}-1",
        username=role,
        password_hash="hash",
        full_name=f"{role.title()} User",
        role=role,
        is_active=1,
        created_at="2026-06-05T00:00:00.000Z",
        updated_at="2026-06-05T00:00:00.000Z",
    )


def _insert_provider_health(db, provider: str, *, unhealthy_until: str) -> None:
    now = _iso(datetime.now(timezone.utc))
    db.execute(text("""
        INSERT INTO provider_health_events (
            id, provider_name, status, reason, operation, error_type,
            consecutive_errors, observed_at, unhealthy_until, recovered_at,
            source, created_at, updated_at
        ) VALUES (
            :id, :provider, 'unhealthy', 'forced-fail', 'cache_purge',
            'RuntimeError', 2, :observed_at, :unhealthy_until, NULL,
            'test', :created_at, :updated_at
        )
    """), {
        "id": f"health-{provider}",
        "provider": provider,
        "observed_at": now,
        "unhealthy_until": unhealthy_until,
        "created_at": now,
        "updated_at": now,
    })


def _insert_cache(db, *, source: str, expires_at: str) -> None:
    db.add(MarketDataCacheEntry(
        cache_kind="eod",
        cache_key=f"{source}-{expires_at}",
        value_json=json.dumps({"symbol": "X", "source": source}),
        fetched_at=_iso(datetime.now(timezone.utc) - timedelta(days=1)),
        expires_at=expires_at,
    ))


def test_run_daily_cache_purge_skips_unhealthy_provider_and_records_history(tmp_path):
    engine, factory = _session_factory(tmp_path)
    past = _iso(datetime.now(timezone.utc) - timedelta(days=1))
    future = _iso(datetime.now(timezone.utc) + timedelta(hours=2))

    with factory() as db:
        _insert_provider_health(db, "yfinance", unhealthy_until=future)
        _insert_cache(db, source="yfinance", expires_at=past)
        _insert_cache(db, source="stooq", expires_at=past)
        _insert_cache(db, source="yfinance", expires_at=future)
        db.commit()

        report = run_daily_cache_purge(db)

        remaining = db.query(MarketDataCacheEntry).all()
        history = list_purge_history(db)

    assert report["purged_rows"] == 1
    assert report["skipped_providers"] == ["yfinance"]
    assert report["errors"] == []
    assert len(remaining) == 2
    assert history[0]["purged_rows"] == 1
    assert history[0]["skipped_providers"] == ["yfinance"]
    engine.dispose()


def test_ensure_purge_history_table_idempotent_and_columns(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'purge_history.db'}")
    ensure_purge_history_table(engine)
    ensure_purge_history_table(engine)

    with engine.connect() as conn:
        columns = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info(market_data_purge_history)")).fetchall()
        }

    assert set(PURGE_HISTORY_COLUMNS).issubset(columns)
    engine.dispose()


def test_purge_now_endpoint_returns_report_for_advisor(monkeypatch, tmp_path):
    _engine, factory = _session_factory(tmp_path)
    expected = {
        "purged_rows": 2,
        "skipped_providers": ["yfinance"],
        "duration_seconds": 0.01,
        "started_at": "2026-06-05T06:00:00.000Z",
        "finished_at": "2026-06-05T06:00:00.010Z",
        "errors": [],
    }

    def override_get_db():
        with factory() as db:
            yield db

    import services.market_data.cache_purge as cache_purge

    monkeypatch.setattr(cache_purge, "run_daily_cache_purge", lambda db: expected)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_advisor] = lambda: _user("advisor")
    try:
        with TestClient(app) as client:
            response = client.post("/admin/system/market-data/purge-now")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == expected


def test_purge_history_endpoint_requires_admin(tmp_path):
    _engine, factory = _session_factory(tmp_path)

    def override_get_db():
        with factory() as db:
            yield db

    def deny_admin():
        raise HTTPException(status_code=403, detail="admin required")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_admin] = deny_admin
    try:
        with TestClient(app) as client:
            response = client.get("/admin/system/market-data/purge-history")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403


def test_purge_history_endpoint_lists_entries_for_admin(tmp_path):
    _engine, factory = _session_factory(tmp_path)
    with factory() as db:
        ensure_purge_history_table(db.get_bind())
        db.execute(text("""
            INSERT INTO market_data_purge_history (
                started_at, finished_at, purged_rows, skipped_providers_json,
                duration_seconds, errors_json
            ) VALUES (
                '2026-06-05T06:00:00.000Z', '2026-06-05T06:00:00.010Z',
                3, '["stooq"]', 0.01, '[]'
            )
        """))
        db.commit()

    def override_get_db():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_admin] = lambda: _user("admin")
    try:
        with TestClient(app) as client:
            response = client.get("/admin/system/market-data/purge-history?limit=5")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 5
    assert body["items"][0]["purged_rows"] == 3
    assert body["items"][0]["skipped_providers"] == ["stooq"]
