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
from models.review import PriceHistory, Product
from models.users import User
from price_updater import PricePoint, fetch_latest_prices_batch, refresh_all_prices
from routers.prices import require_admin
from services.product_market_data import lookup_symbol_for_provider, resolve_market_profile


@pytest.fixture()
def session_factory(tmp_path):
    db_path = tmp_path / "test_prices.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield TestingSessionLocal
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def db_session(session_factory):
    with session_factory() as session:
        yield session
        session.rollback()


@pytest.fixture()
def admin_user():
    return User(
        id="admin-1",
        username="admin",
        password_hash="hash",
        full_name="Admin User",
        role="admin",
        is_active=1,
        created_at="2026-03-20T00:00:00.000Z",
        updated_at="2026-03-20T00:00:00.000Z",
    )


@pytest.fixture()
def client(session_factory, admin_user):
    def override_get_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_admin] = lambda: admin_user
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def make_product(
    product_id: str,
    symbol: str | None = "VT",
    name: str = "Vanguard Total World",
    isin: str | None = "CH0000000001",
) -> Product:
    return Product(
        id=product_id,
        symbol=symbol,
        isin=isin,
        product_name=name,
        provider="Test Provider",
        product_type="ETF",
        asset_class="Equities",
        currency="CHF",
        is_active=1,
        created_at="2026-03-20T00:00:00.000Z",
        updated_at="2026-03-20T00:00:00.000Z",
    )


def test_refresh_all_prices_inserts_then_updates_then_unchanged(monkeypatch, db_session):
    import price_updater as price_updater_module

    product = make_product("prod-1")
    db_session.add(product)
    db_session.commit()

    monkeypatch.setattr(
        price_updater_module,
        "fetch_latest_prices_batch",
        lambda products: (
            {
                product.id: PricePoint(
                    price_date="2026-03-19",
                    price_rappen=12345,
                    currency="USD",
                )
            },
            {},
        ),
    )

    first = refresh_all_prices(db_session)
    assert first["processed"] == 1
    assert first["inserted"] == 1
    assert first["updated"] == 0
    assert first["unchanged"] == 0
    assert first["failed"] == 0

    stored = db_session.query(PriceHistory).filter(PriceHistory.product_id == product.id).one()
    assert stored.price_rappen == 12345
    assert stored.currency == "USD"

    monkeypatch.setattr(
        price_updater_module,
        "fetch_latest_prices_batch",
        lambda products: (
            {
                product.id: PricePoint(
                    price_date="2026-03-19",
                    price_rappen=12700,
                    currency="USD",
                )
            },
            {},
        ),
    )
    second = refresh_all_prices(db_session)
    assert second["inserted"] == 0
    assert second["updated"] == 1
    assert second["unchanged"] == 0

    monkeypatch.setattr(
        price_updater_module,
        "fetch_latest_prices_batch",
        lambda products: (
            {
                product.id: PricePoint(
                    price_date="2026-03-19",
                    price_rappen=12700,
                    currency="USD",
                )
            },
            {},
        ),
    )
    third = refresh_all_prices(db_session)
    assert third["unchanged"] == 1


def test_refresh_endpoint_returns_summary_and_logs_failures(monkeypatch, session_factory, client):
    import price_updater as price_updater_module

    with session_factory() as session:
        session.add_all(
            [
                make_product("prod-ok", symbol="VT", name="Working Product"),
                make_product("prod-fail", symbol=None, isin=None, name="Broken Product"),
            ]
        )
        session.commit()

    def fake_batch(products: list[Product]):
        points = {}
        failures = {}
        for product in products:
            if product.id == "prod-fail":
                failures[product.id] = {
                    "product": product,
                    "lookup_mode": "unmapped",
                    "lookup_symbol": None,
                    "error": "lookup missing",
                }
            else:
                points[product.id] = PricePoint(
                    price_date="2026-03-19",
                    price_rappen=10050,
                    currency="CHF",
                )
        return points, failures

    monkeypatch.setattr(price_updater_module, "fetch_latest_prices_batch", fake_batch)

    response = client.post("/admin/prices/refresh")
    assert response.status_code == 200

    payload = response.json()
    assert payload["processed"] == 2
    assert payload["inserted"] == 1
    assert payload["failed"] == 1
    assert payload["failures"][0]["product_id"] == "prod-fail"

    with session_factory() as session:
        prices = session.query(PriceHistory).all()
        assert len(prices) == 1
        assert prices[0].product_id == "prod-ok"


def test_price_status_and_mapping_gap_endpoints(session_factory, client):
    with session_factory() as session:
        session.add_all(
            [
                make_product("prod-gap", symbol=None, isin=None, name="Gap Product"),
                make_product("prod-ok", symbol="VT", name="Mapped Product"),
            ]
        )
        session.commit()

    status_response = client.get("/admin/prices/status")
    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert "scheduler_enabled" in status_payload
    assert status_payload["provider"] == "yfinance"
    assert status_payload["provider_roles"]["market_prices"]["current"]["primary"]["name"] == "yfinance"
    assert status_payload["provider_roles"]["market_prices"]["target"]["primary"]["name"] == "twelvedata"
    assert status_payload["provider_roles"]["reference_data"]["target"]["primary"]["name"] == "eodhd"
    assert status_payload["provider_roles"]["id_mapping"]["target"]["primary"]["name"] == "openfigi"
    assert status_payload["provider_roles"]["macro_core"]["target"]["primary"]["name"] == "fred"
    assert status_payload["provider_roles"]["macro_switzerland"]["target"]["primary"]["name"] == "snb"
    assert "setup" in status_payload
    assert isinstance(status_payload["setup"]["env_file"], str)
    assert isinstance(status_payload["setup"]["env_file_exists"], bool)
    assert isinstance(status_payload["setup"]["current_ready"], bool)
    assert isinstance(status_payload["setup"]["target_key_ready"], bool)
    assert isinstance(status_payload["setup"]["warnings"], list)

    gaps_response = client.get("/admin/prices/mapping-gaps")
    assert gaps_response.status_code == 200
    payload = gaps_response.json()
    assert payload["count"] == 1
    assert payload["items"][0]["product_id"] == "prod-gap"


def test_market_data_status_endpoint_exposes_mapping_and_reference_counts(session_factory, client):
    with session_factory() as session:
        session.add_all(
            [
                Product(
                    id="prod-market-ready",
                    isin="CH0000000001",
                    symbol="UBSG",
                    product_name="Ready Product",
                    provider="Test Provider",
                    product_type="ETF",
                    asset_class="Aktien",
                    currency="CHF",
                    mapping_provider="openfigi",
                    reference_data_provider="eodhd",
                    reference_data_refreshed_at="2026-03-28T09:00:00.000Z",
                    is_active=1,
                    created_at="2026-03-28T00:00:00.000Z",
                    updated_at="2026-03-28T00:00:00.000Z",
                ),
                Product(
                    id="prod-market-pending",
                    isin="CH0000000002",
                    symbol=None,
                    product_name="Pending Product",
                    provider="Test Provider",
                    product_type="ETF",
                    asset_class="Aktien",
                    currency="CHF",
                    is_active=1,
                    created_at="2026-03-28T00:00:00.000Z",
                    updated_at="2026-03-28T00:00:00.000Z",
                ),
            ]
        )
        session.commit()

    response = client.get("/products/market-data/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["active_products"] == 2
    assert payload["lookup_mode_override_count"] == 0
    assert payload["openfigi_mapped_count"] == 1
    assert payload["reference_synced_count"] == 1
    assert payload["openfigi_pending_count"] == 1
    assert payload["reference_pending_count"] >= 1
    assert payload["price_quality"]["active_products_count"] == 2


def test_fetch_latest_prices_batch_uses_twelvedata_when_configured(monkeypatch):
    import price_updater as price_updater_module

    monkeypatch.setattr(price_updater_module, "PRICE_SOURCE", "twelvedata")
    monkeypatch.setattr(price_updater_module, "FALLBACK_PRICE_SOURCE", "stooq")
    monkeypatch.setattr(
        price_updater_module,
        "_fetch_twelvedata_symbol_points",
        lambda symbols: (
            {"VT": ("2026-03-28", 12055, "twelvedata")},
            {},
        ),
    )
    monkeypatch.setattr(
        price_updater_module,
        "_fetch_fallback_symbol_points",
        lambda symbols, product_by_symbol: ({}, {}),
    )

    product = make_product("prod-td-1", symbol="VT", name="Twelve Data Product")
    points, failures = fetch_latest_prices_batch([product])

    assert not failures
    assert points[product.id].source == "twelvedata"
    assert points[product.id].price_rappen == 12055


def test_fetch_latest_prices_batch_falls_back_from_twelvedata_to_stooq(monkeypatch):
    import price_updater as price_updater_module

    monkeypatch.setattr(price_updater_module, "PRICE_SOURCE", "twelvedata")
    monkeypatch.setattr(price_updater_module, "FALLBACK_PRICE_SOURCE", "stooq")
    monkeypatch.setattr(
        price_updater_module,
        "_fetch_twelvedata_symbol_points",
        lambda symbols: ({}, {"VT": "upstream error"}),
    )
    monkeypatch.setattr(
        price_updater_module,
        "_fetch_fallback_symbol_points",
        lambda symbols, product_by_symbol: (
            {"VT": ("2026-03-28", 11995, "stooq")},
            {},
        ),
    )

    product = make_product("prod-td-fallback", symbol="VT", name="Fallback Product")
    points, failures = fetch_latest_prices_batch([product])

    assert not failures
    assert points[product.id].source == "stooq"
    assert points[product.id].price_rappen == 11995


def test_fetch_latest_prices_batch_handles_twelvedata_runtime_error_per_product(monkeypatch):
    import price_updater as price_updater_module

    monkeypatch.setattr(price_updater_module, "PRICE_SOURCE", "twelvedata")
    monkeypatch.setattr(price_updater_module, "FALLBACK_PRICE_SOURCE", "")
    monkeypatch.setattr(
        price_updater_module,
        "fetch_twelvedata_latest_prices",
        lambda symbols: (_ for _ in ()).throw(RuntimeError("Twelve Data API Key ist nicht konfiguriert")),
    )

    product = make_product("prod-td-missing-key", symbol="VT", name="Missing Key Product")
    points, failures = fetch_latest_prices_batch([product])

    assert not points
    assert failures[product.id]["lookup_symbol"] == "VT"
    assert "API Key" in failures[product.id]["error"]


def test_provider_lookup_symbol_normalizes_swiss_symbols_by_provider():
    product = Product(
        id="prod-swiss-symbols",
        isin="CH0001341608",
        symbol="UBSG",
        exchange_code="SW",
        product_name="Swiss Equity",
        provider="Test Provider",
        product_type="ETF",
        asset_class="Aktien",
        currency="CHF",
        is_active=1,
        created_at="2026-03-28T00:00:00.000Z",
        updated_at="2026-03-28T00:00:00.000Z",
    )
    profile = resolve_market_profile(product)

    assert lookup_symbol_for_provider(profile, "yfinance") == "UBSG.SW"
    assert lookup_symbol_for_provider(profile, "stooq") == "ubsg.sw"
    assert lookup_symbol_for_provider(profile, "twelvedata") == "UBSG:SIX"


def test_fetch_latest_prices_batch_uses_normalized_yfinance_symbol_for_swiss_equity(monkeypatch):
    import price_updater as price_updater_module

    captured = {}
    monkeypatch.setattr(price_updater_module, "PRICE_SOURCE", "yfinance")
    monkeypatch.setattr(price_updater_module, "FALLBACK_PRICE_SOURCE", "stooq")

    def fake_primary(symbols, product_by_symbol):
        captured["symbols"] = list(symbols)
        return {"UBSG.SW": ("2026-03-28", 22150, "yfinance")}, {}

    monkeypatch.setattr(price_updater_module, "_fetch_primary_symbol_points", fake_primary)
    monkeypatch.setattr(price_updater_module, "_fetch_fallback_symbol_points", lambda symbols, product_by_symbol: ({}, {}))

    product = Product(
        id="prod-swiss-price",
        isin="CH0001341608",
        symbol="UBSG",
        exchange_code="SW",
        product_name="Swiss Equity",
        provider="Test Provider",
        product_type="ETF",
        asset_class="Aktien",
        currency="CHF",
        is_active=1,
        created_at="2026-03-28T00:00:00.000Z",
        updated_at="2026-03-28T00:00:00.000Z",
    )

    points, failures = fetch_latest_prices_batch([product])

    assert not failures
    assert captured["symbols"] == ["UBSG.SW"]
    assert points[product.id].source == "yfinance"
    assert points[product.id].price_rappen == 22150


def test_fetch_latest_prices_batch_adds_market_hint_for_swiss_stooq_fallback(monkeypatch):
    import price_updater as price_updater_module

    monkeypatch.setattr(price_updater_module, "PRICE_SOURCE", "yfinance")
    monkeypatch.setattr(price_updater_module, "FALLBACK_PRICE_SOURCE", "stooq")
    monkeypatch.setattr(
        price_updater_module,
        "_fetch_primary_symbol_points",
        lambda symbols, product_by_symbol: ({}, {"NOVN.SW": "rate limit"}),
    )
    monkeypatch.setattr(
        price_updater_module,
        "_fetch_fallback_symbol_points",
        lambda symbols, product_by_symbol: ({}, {"novn.sw": "N/D"}),
    )

    product = Product(
        id="prod-swiss-fallback-note",
        isin="CH0012005267",
        symbol="NOVN",
        exchange_code="SW",
        product_name="Novartis AG",
        provider="Test Provider",
        product_type="Equity",
        asset_class="Aktien",
        currency="CHF",
        is_active=1,
        created_at="2026-03-28T00:00:00.000Z",
        updated_at="2026-03-28T00:00:00.000Z",
    )

    points, failures = fetch_latest_prices_batch([product])

    assert not points
    assert failures[product.id]["lookup_symbol"] == "novn.sw"
    assert "SIX/Schweiz" in failures[product.id]["error"]


def test_require_admin_is_overridden_for_endpoint(client):
    response = client.post("/admin/prices/refresh")
    assert response.status_code == 200
