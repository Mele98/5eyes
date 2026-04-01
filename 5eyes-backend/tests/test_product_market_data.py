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
from models.review import Product
from models.users import User
from services.auth import require_admin
from services.product_market_data import lookup_symbol_for_provider, resolve_market_profile


class P:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


@pytest.fixture()
def session_factory(tmp_path):
    db_path = tmp_path / "test_product_market_data.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    testing_session_local = sessionmaker(
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
        bind=engine,
    )
    Base.metadata.create_all(bind=engine)
    try:
        yield testing_session_local
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def admin_user():
    return User(
        id="admin-override-1",
        username="admin",
        password_hash="hash",
        full_name="Admin User",
        role="admin",
        is_active=1,
        created_at="2026-04-01T00:00:00.000Z",
        updated_at="2026-04-01T00:00:00.000Z",
    )


@pytest.fixture()
def admin_client(session_factory, admin_user):
    def override_get_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_admin] = lambda: admin_user
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def forbidden_client(session_factory):
    def override_get_db():
        with session_factory() as session:
            yield session

    def deny_admin():
        raise HTTPException(status_code=403, detail="Keine Admin-Berechtigung")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_admin] = deny_admin
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def seed_product(session_factory, **overrides) -> str:
    payload = {
        "id": "product-override-1",
        "isin": None,
        "symbol": None,
        "product_name": "ZKB Gold ETF",
        "provider": "Test Provider",
        "product_type": "ETF",
        "asset_class": "Aktien",
        "sub_asset_class": None,
        "currency": "CHF",
        "is_active": 1,
        "created_at": "2026-04-01T00:00:00.000Z",
        "updated_at": "2026-04-01T00:00:00.000Z",
    }
    payload.update(overrides)
    with session_factory() as session:
        session.add(Product(**payload))
        session.commit()
    return payload["id"]


def test_resolve_market_profile_override_wins_against_catalog():
    profile = resolve_market_profile(
        P(
            product_name="ZKB Gold ETF",
            symbol=None,
            isin=None,
            exchange_code=None,
            currency="CHF",
            lookup_mode_override="proxy",
            lookup_symbol_override="GLD",
        )
    )
    assert profile["lookup_mode"] == "proxy"
    assert profile["lookup_symbol"] == "GLD"
    assert profile["identifier_basis"] == "override"


def test_resolve_market_profile_override_wins_against_product_symbol():
    profile = resolve_market_profile(
        P(
            product_name="Swiss Equity",
            symbol="NESN",
            isin=None,
            exchange_code="SW",
            currency="CHF",
            lookup_mode_override="proxy",
            lookup_symbol_override="EWL",
        )
    )
    assert profile["lookup_mode"] == "proxy"
    assert profile["lookup_symbol"] == "EWL"
    assert lookup_symbol_for_provider(profile, "yfinance") == "EWL.SW"


def test_resolve_market_profile_synthetic_override_ignores_symbol():
    profile = resolve_market_profile(
        P(
            product_name="Cash Proxy",
            symbol=None,
            isin=None,
            exchange_code=None,
            currency="CHF",
            lookup_mode_override="synthetic_par",
            lookup_symbol_override="IGNORED",
        )
    )
    assert profile["lookup_mode"] == "synthetic_par"
    assert profile["lookup_symbol"] is None
    assert profile["synthetic_price_rappen"] == 100


def test_resolve_market_profile_symbol_override_keeps_suffix_logic():
    profile = resolve_market_profile(
        P(
            product_name="Swiss Equity",
            symbol=None,
            isin=None,
            exchange_code="SW",
            currency="CHF",
            lookup_mode_override=None,
            lookup_symbol_override="NESN",
        )
    )
    assert profile["lookup_mode"] == "direct"
    assert profile["lookup_symbol"] == "NESN"
    assert lookup_symbol_for_provider(profile, "yfinance") == "NESN.SW"
    assert lookup_symbol_for_provider(profile, "stooq") == "nesn.sw"
    assert lookup_symbol_for_provider(profile, "twelvedata") == "NESN:SIX"


def test_resolve_market_profile_without_override_uses_catalog():
    profile = resolve_market_profile(
        P(
            product_name="ZKB Gold ETF",
            symbol=None,
            isin=None,
            exchange_code=None,
            currency="CHF",
            lookup_mode_override=None,
            lookup_symbol_override=None,
        )
    )
    assert profile["lookup_mode"] == "proxy"
    assert profile["lookup_symbol"] == "GLD"
    assert profile["identifier_basis"] == "catalog"


def test_put_product_market_override_persists_and_returns_resolved_profile(session_factory, admin_client):
    product_id = seed_product(session_factory)

    response = admin_client.put(
        f"/products/{product_id}/market-override",
        json={"lookup_mode_override": "proxy", "lookup_symbol_override": "IAU"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["lookup_mode_override"] == "proxy"
    assert payload["lookup_symbol_override"] == "IAU"
    assert payload["resolved_market_profile"]["lookup_mode"] == "proxy"
    assert payload["resolved_market_profile"]["lookup_symbol"] == "IAU"

    with session_factory() as session:
        product = session.query(Product).filter(Product.id == product_id).one()
        assert product.lookup_mode_override == "proxy"
        assert product.lookup_symbol_override == "IAU"


def test_put_product_market_override_can_clear_back_to_default_catalog(session_factory, admin_client):
    product_id = seed_product(
        session_factory,
        lookup_mode_override="proxy",
        lookup_symbol_override="IAU",
    )

    response = admin_client.put(
        f"/products/{product_id}/market-override",
        json={"lookup_mode_override": None, "lookup_symbol_override": None},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["lookup_mode_override"] is None
    assert payload["lookup_symbol_override"] is None
    assert payload["resolved_market_profile"]["lookup_mode"] == "proxy"
    assert payload["resolved_market_profile"]["lookup_symbol"] == "GLD"


def test_put_product_market_override_rejects_invalid_mode(session_factory, admin_client):
    product_id = seed_product(session_factory)

    response = admin_client.put(
        f"/products/{product_id}/market-override",
        json={"lookup_mode_override": "invalid", "lookup_symbol_override": "GLD"},
    )

    assert response.status_code == 422


def test_put_product_market_override_returns_404_for_unknown_product(admin_client):
    response = admin_client.put(
        "/products/unknown-product/market-override",
        json={"lookup_mode_override": "proxy", "lookup_symbol_override": "GLD"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Produkt nicht gefunden"


def test_put_product_market_override_requires_admin(session_factory, forbidden_client):
    product_id = seed_product(session_factory)

    response = forbidden_client.put(
        f"/products/{product_id}/market-override",
        json={"lookup_mode_override": "proxy", "lookup_symbol_override": "GLD"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Keine Admin-Berechtigung"


def test_market_data_status_endpoint_exposes_override_count(session_factory, admin_client):
    seed_product(
        session_factory,
        id="product-override-count",
        product_name="Override Product",
        symbol="VT",
        lookup_mode_override="proxy",
        lookup_symbol_override="EWL",
    )
    seed_product(
        session_factory,
        id="product-standard-count",
        product_name="Standard Product",
        symbol="UBSG",
        lookup_mode_override=None,
        lookup_symbol_override=None,
    )

    response = admin_client.get("/products/market-data/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["active_products"] == 2
    assert payload["lookup_mode_override_count"] == 1


def test_resolve_market_profile_explicit_suffix_override_keeps_symbol_without_double_suffix():
    profile = resolve_market_profile(
        P(
            product_name="X",
            symbol=None,
            isin=None,
            exchange_code="SW",
            currency="CHF",
            lookup_mode_override=None,
            lookup_symbol_override="NESN.SW",
        )
    )
    assert profile["lookup_symbol"] == "NESN.SW"
    assert lookup_symbol_for_provider(profile, "yfinance") == "NESN.SW"
    assert lookup_symbol_for_provider(profile, "stooq") == "NESN.SW"


def test_resolve_market_profile_proxy_override_without_symbol():
    profile = resolve_market_profile(
        P(
            product_name="X",
            symbol=None,
            isin=None,
            exchange_code=None,
            currency="CHF",
            lookup_mode_override="proxy",
            lookup_symbol_override=None,
        )
    )
    assert profile["lookup_mode"] == "proxy"
    assert profile["lookup_symbol"] is None


def test_put_product_market_override_returns_404_for_soft_deleted_product(session_factory, admin_client):
    product_id = seed_product(
        session_factory,
        id="product-soft-deleted",
        deleted_at="2026-04-01T00:00:00.000Z",
    )

    response = admin_client.put(
        f"/products/{product_id}/market-override",
        json={"lookup_mode_override": "proxy", "lookup_symbol_override": "GLD"},
    )

    assert response.status_code == 404
