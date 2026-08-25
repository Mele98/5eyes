from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, get_db  # noqa: E402
from main import app  # noqa: E402
from models import (  # noqa: F401,E402
    allocation,
    clients,
    mandates,
    profiling,
    review,
    snapshots,
    users,
    wealth,
)
from models.review import AuditLog  # noqa: E402
from models.users import User  # noqa: E402
from services.auth import require_admin  # noqa: E402
from services.market_data.provider_health_registry import (  # noqa: E402
    ProviderHealthRegistry,
    ensure_provider_health_table,
    list_provider_health,
)
from services.market_data.admin import collect_provider_health  # noqa: E402


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'admin_provider_health.db'}",
        connect_args={"check_same_thread": False},
    )
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    ensure_provider_health_table(engine)
    try:
        yield factory
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def admin_user():
    return User(
        id="admin-1",
        username="admin",
        password_hash="hash",
        full_name="Admin User",
        role="admin",
        is_active=1,
        created_at="2026-06-04T00:00:00.000Z",
        updated_at="2026-06-04T00:00:00.000Z",
    )


@pytest.fixture()
def admin_client(session_factory, admin_user):
    def override_get_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_admin] = lambda: admin_user
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def test_get_provider_health_lists_events(session_factory, admin_client):
    ProviderHealthRegistry(session_factory=session_factory).mark_unhealthy(
        "yfinance",
        reason="forced fail",
        operation="get_eod",
        error_type="ProviderError",
    )

    response = admin_client.get("/admin/system/market-data/provider-health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"][0]["provider_name"] == "yfinance"
    assert payload["items"][0]["reason"] == "forced fail"
    assert payload["items"][0]["recovered_at"] is None


def test_provider_health_reset_clears_and_audits(session_factory, admin_client):
    ProviderHealthRegistry(session_factory=session_factory).mark_unhealthy("yfinance", reason="forced fail")

    response = admin_client.post("/admin/system/market-data/provider-health/reset", json={})

    assert response.status_code == 200
    assert response.json()["deleted"] == 1
    with session_factory() as db:
        assert list_provider_health(db) == []
        audit = db.query(AuditLog).filter_by(table_name="provider_health_events").one()
    assert audit.action == "DELETE"
    assert audit.record_id == "all"


def test_provider_health_reset_can_clear_single_provider(session_factory, admin_client):
    registry = ProviderHealthRegistry(session_factory=session_factory)
    registry.mark_unhealthy("yfinance", reason="down")
    registry.mark_unhealthy("stooq", reason="down")

    response = admin_client.post(
        "/admin/system/market-data/provider-health/reset",
        json={"provider_name": "yfinance"},
    )

    assert response.status_code == 200
    assert response.json()["deleted"] == 1
    with session_factory() as db:
        remaining = list_provider_health(db)
    assert [event["provider_name"] for event in remaining] == ["stooq"]


def test_provider_health_endpoints_require_admin(session_factory):
    def override_get_db():
        with session_factory() as session:
            yield session

    def deny_admin():
        raise HTTPException(status_code=403, detail="admin required")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_admin] = deny_admin
    try:
        with TestClient(app) as client:
            get_response = client.get("/admin/system/market-data/provider-health")
            post_response = client.post("/admin/system/market-data/provider-health/reset", json={})
    finally:
        app.dependency_overrides.clear()

    assert get_response.status_code == 403
    assert post_response.status_code == 403


def test_admin_status_provider_cards_include_registry_fields(session_factory):
    ProviderHealthRegistry(session_factory=session_factory).mark_unhealthy(
        "yfinance",
        reason="forced fail",
        operation="get_eod",
    )

    with session_factory() as db:
        cards = collect_provider_health(db)

    yfinance = next(card for card in cards if card["name"] == "yfinance")
    assert yfinance["registry_status"] == "unhealthy"
    assert yfinance["healthy"] is False
    assert yfinance["reason"] == "forced fail"
