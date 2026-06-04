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

from database import Base, get_db
from main import app
from models.users import User
from services.auth import require_admin


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'admin_refresh_now.db'}",
        connect_args={"check_same_thread": False},
    )
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
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


def test_refresh_now_endpoint_returns_summary(monkeypatch, admin_client):
    import services.market_data_daily_refresh as refresh_service

    expected = {
        "status": "ok",
        "products_refreshed": 3,
        "prices_added": 5,
        "fx_added": 4,
        "errors": [],
    }
    monkeypatch.setattr(refresh_service, "run_daily_market_data_refresh", lambda db: expected)

    response = admin_client.post("/admin/system/market-data/refresh-now")

    assert response.status_code == 200
    assert response.json() == expected


def test_refresh_now_endpoint_requires_admin(session_factory):
    def override_get_db():
        with session_factory() as session:
            yield session

    def deny():
        raise HTTPException(status_code=403, detail="admin required")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_admin] = deny
    try:
        with TestClient(app) as client:
            response = client.post("/admin/system/market-data/refresh-now")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403


def test_refresh_now_endpoint_returns_500_when_refresh_crashes(monkeypatch, admin_client):
    import services.market_data_daily_refresh as refresh_service

    def boom(db):
        raise RuntimeError("refresh exploded")

    monkeypatch.setattr(refresh_service, "run_daily_market_data_refresh", boom)

    response = admin_client.post("/admin/system/market-data/refresh-now")

    assert response.status_code == 500
    assert "refresh exploded" in response.json()["detail"]
