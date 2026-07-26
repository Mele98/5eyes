"""2026-07-25 (Generalaudit, Wave 11 -- Produkt-Katalog-Fork): ter_bps hatte
keinen Plausibilitaets-Range-Check -- fliesst in den FIDLEG-Kostenausweis
JEDES Kunden ein, der das Produkt haelt. Ein Tippfehler (negativ/zusaetzliche
Nullen) korrumpiert den Kostenausweis systemweit, analog zum bereits
gefixten return_bps-Fund (routers/system.py, Wave 9).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, get_db
from main import app
from models.review import Product
from models.users import User
from services.auth import get_current_user, require_admin


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test_ter_bps_bounds.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def admin_user():
    return User(
        id="admin-ter-bounds", username="admin-ter-bounds", password_hash="h",
        full_name="Admin", role="admin", is_active=1,
        created_at="2026-04-01T00:00:00.000Z", updated_at="2026-04-01T00:00:00.000Z",
    )


@pytest.fixture()
def admin_client(session_factory, admin_user):
    def override_get_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_admin] = lambda: admin_user
    app.dependency_overrides[get_current_user] = lambda: admin_user
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _payload(**overrides) -> dict:
    base = {
        "product_name": "Test Fund",
        "product_type": "Fonds",
        "asset_class": "Aktien",
    }
    base.update(overrides)
    return base


def test_create_product_rejects_negative_ter_bps(admin_client, session_factory):
    response = admin_client.post("/products", json=_payload(ter_bps=-500_000))
    assert response.status_code == 422, response.text
    with session_factory() as s:
        assert s.query(Product).count() == 0


def test_create_product_rejects_absurdly_high_ter_bps(admin_client, session_factory):
    response = admin_client.post("/products", json=_payload(ter_bps=95_000_00))
    assert response.status_code == 422, response.text
    with session_factory() as s:
        assert s.query(Product).count() == 0


def test_create_product_accepts_plausible_ter_bps(admin_client):
    response = admin_client.post("/products", json=_payload(ter_bps=85))
    assert response.status_code == 201, response.text
    assert response.json()["ter_bps"] == 85


def test_update_product_rejects_negative_ter_bps(admin_client):
    created = admin_client.post("/products", json=_payload(ter_bps=50)).json()
    response = admin_client.put(f"/products/{created['id']}", json={"ter_bps": -10})
    assert response.status_code == 422, response.text
    current = admin_client.get("/products").json()
    assert current[0]["ter_bps"] == 50
