from __future__ import annotations

import sys
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base
from models import allocation, clients, mandates, profiling, review, snapshots, users, wealth  # noqa: F401
from models.allocation import OptimizerPolicy
from models.clients import Client
from models.mandates import Mandate
from models.review import PriceHistory, Product, RecommendationPosition, RecommendationRun
from models.snapshots import AssetClassFxHistory, AssetClassPriceHistory
from models.users import User
from price_updater import PricePoint
from services.market_data.annual_returns_backfill import DEFAULT_SYMBOL_MAP
from services.market_data.base import Bar
from services.market_data_daily_refresh import run_daily_market_data_refresh

configure_mappers()


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'daily_market_data.db'}",
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
def db_session(session_factory):
    with session_factory() as session:
        yield session
        session.rollback()


class FakeAggregator:
    def __init__(self, *, fail_symbols: set[str] | None = None):
        self.fail_symbols = fail_symbols or set()
        self.calls: list[str] = []

    def get_eod(self, symbol: str, on_date: date) -> Bar:
        self.calls.append(symbol)
        if symbol in self.fail_symbols:
            raise RuntimeError(f"{symbol} failed")
        currency = "CHF" if symbol.endswith("CHF=X") else "USD"
        return Bar(
            symbol=symbol,
            date=on_date,
            open=Decimal("100.00"),
            high=Decimal("101.00"),
            low=Decimal("99.00"),
            close=Decimal("100.00"),
            adjusted_close=Decimal("100.00"),
            currency=currency,
            source="fake",
        )


def _now() -> str:
    return "2026-06-04T06:00:00.000Z"


def _seed_position_product(db_session, product_id: str = "prod-1", *, current_amount: int | None = 100_000_00):
    advisor_id = f"adv-{uuid.uuid4().hex[:6]}"
    client_id = f"client-{uuid.uuid4().hex[:6]}"
    mandate_id = f"mandate-{uuid.uuid4().hex[:6]}"
    policy_id = f"policy-{uuid.uuid4().hex[:6]}"
    run_id = f"run-{uuid.uuid4().hex[:6]}"
    position_id = f"pos-{uuid.uuid4().hex[:6]}"
    db_session.add(User(
        id=advisor_id,
        username=advisor_id,
        password_hash="hash",
        full_name="Advisor",
        role="advisor",
        is_active=1,
        created_at=_now(),
        updated_at=_now(),
    ))
    db_session.add(Client(
        id=client_id,
        client_number=client_id,
        first_name="Daily",
        last_name="Refresh",
        advisor_id=advisor_id,
        created_at=_now(),
        updated_at=_now(),
    ))
    db_session.add(Mandate(
        id=mandate_id,
        client_id=client_id,
        mandate_number=mandate_id,
        mandate_type="Anlageberatung",
        opened_at=_now(),
        created_at=_now(),
        updated_at=_now(),
    ))
    db_session.add(OptimizerPolicy(
        id=policy_id,
        policy_name="Policy",
        version=1,
        is_current=1,
        valid_from=_now(),
        optimizer_engine="goal_based_v1",
        max_real_estate_bps=2000,
        max_alternatives_bps=1000,
        min_liquidity_bps=0,
        created_by=advisor_id,
        created_at=_now(),
        updated_at=_now(),
    ))
    db_session.add(Product(
        id=product_id,
        isin=f"CH{uuid.uuid4().int % 10**10:010d}",
        symbol=f"T{uuid.uuid4().hex[:4]}",
        product_name=f"Product {product_id}",
        provider="Test",
        product_type="ETF",
        asset_class="Aktien",
        currency="CHF",
        is_active=1,
        created_at=_now(),
        updated_at=_now(),
    ))
    db_session.add(RecommendationRun(
        id=run_id,
        mandate_id=mandate_id,
        client_id=client_id,
        policy_id=policy_id,
        run_type="initial",
        created_by=advisor_id,
        created_at=_now(),
        updated_at=_now(),
    ))
    db_session.add(RecommendationPosition(
        id=position_id,
        run_id=run_id,
        product_id=product_id,
        target_weight_bps=10000,
        target_amount_rappen=100_000_00,
        current_amount_rappen=current_amount,
        created_at=_now(),
        updated_at=_now(),
    ))
    db_session.commit()
    return product_id, position_id


def test_empty_db_refreshes_asset_classes_and_fx(monkeypatch, db_session):
    fake_aggregator = FakeAggregator()
    monkeypatch.setattr(
        "services.market_data.factory.build_default_aggregator",
        lambda: fake_aggregator,
    )

    summary = run_daily_market_data_refresh(db_session)

    assert summary["products_refreshed"] == 0
    assert summary["prices_added"] == len(DEFAULT_SYMBOL_MAP)
    assert summary["fx_added"] == 4
    assert summary["errors"] == []
    assert db_session.query(AssetClassPriceHistory).count() == len(DEFAULT_SYMBOL_MAP)
    assert db_session.query(AssetClassFxHistory).count() == 4


def test_product_price_lands_in_price_history_and_reference_fields(monkeypatch, db_session):
    product_id, position_id = _seed_position_product(db_session)
    monkeypatch.setattr(
        "price_updater.fetch_latest_prices_batch",
        lambda products: (
            {product_id: PricePoint("2026-06-04", 12345, "CHF", "yfinance")},
            {},
        ),
    )
    monkeypatch.setattr(
        "services.market_data.factory.build_default_aggregator",
        lambda: FakeAggregator(),
    )

    summary = run_daily_market_data_refresh(db_session)

    assert summary["products_refreshed"] == 1
    assert summary["product_positions_updated"] == 1
    price = db_session.query(PriceHistory).filter_by(product_id=product_id).one()
    assert price.price_rappen == 12345
    position = db_session.query(RecommendationPosition).filter_by(id=position_id).one()
    assert position.reference_price_rappen == 12345
    assert position.reference_price_date == "2026-06-04"
    assert position.reference_price_source == "yfinance"


def test_product_provider_fallback_source_is_persisted(monkeypatch, db_session):
    product_id, _ = _seed_position_product(db_session)
    monkeypatch.setattr(
        "price_updater.fetch_latest_prices_batch",
        lambda products: (
            {product_id: PricePoint("2026-06-04", 9900, "CHF", "stooq")},
            {},
        ),
    )
    monkeypatch.setattr(
        "services.market_data.factory.build_default_aggregator",
        lambda: FakeAggregator(),
    )

    summary = run_daily_market_data_refresh(db_session)

    assert summary["product_failures"] == 0
    assert db_session.query(PriceHistory).filter_by(product_id=product_id).one().source == "stooq"


def test_max_symbols_cap_is_respected(monkeypatch, db_session):
    for index in range(3):
        _seed_position_product(db_session, product_id=f"prod-cap-{index}")
    seen = {"count": 0}

    def fake_fetch(products):
        seen["count"] = len(products)
        return {
            product.id: PricePoint("2026-06-04", 10000, "CHF", "mock")
            for product in products
        }, {}

    monkeypatch.setattr("price_updater.fetch_latest_prices_batch", fake_fetch)
    monkeypatch.setattr(
        "services.market_data.factory.build_default_aggregator",
        lambda: FakeAggregator(),
    )
    monkeypatch.setattr(
        "services.market_data_daily_refresh.settings.market_data_daily_refresh_max_symbols",
        2,
    )

    summary = run_daily_market_data_refresh(db_session)

    assert seen["count"] == 2
    assert summary["products_considered"] == 2
    assert summary["products_refreshed"] == 2


def test_errors_are_collected_without_killing_successful_refresh(monkeypatch, db_session):
    product_id, _ = _seed_position_product(db_session)
    first_asset_symbol = next(iter(DEFAULT_SYMBOL_MAP.values()))
    fake_aggregator = FakeAggregator(fail_symbols={first_asset_symbol, "EURCHF=X"})
    monkeypatch.setattr(
        "price_updater.fetch_latest_prices_batch",
        lambda products: ({}, {
            product_id: {
                "lookup_symbol": "FAIL",
                "error": "provider unavailable",
            }
        }),
    )
    monkeypatch.setattr(
        "services.market_data.factory.build_default_aggregator",
        lambda: fake_aggregator,
    )

    summary = run_daily_market_data_refresh(db_session)

    assert summary["status"] == "degraded"
    assert summary["duration_seconds"] > 0
    assert summary["products_refreshed"] == 0
    assert len(summary["errors"]) >= 3
    assert db_session.query(AssetClassPriceHistory).count() == len(DEFAULT_SYMBOL_MAP) - 1
    assert db_session.query(AssetClassFxHistory).count() == 3


def test_positions_without_current_amount_are_not_refreshed(monkeypatch, db_session):
    product_id, _ = _seed_position_product(db_session, current_amount=None)
    called = {"fetch": False}

    def fake_fetch(products):
        called["fetch"] = True
        return {}, {}

    monkeypatch.setattr("price_updater.fetch_latest_prices_batch", fake_fetch)
    monkeypatch.setattr(
        "services.market_data.factory.build_default_aggregator",
        lambda: FakeAggregator(),
    )

    summary = run_daily_market_data_refresh(db_session)

    assert called["fetch"] is False
    assert summary["products_considered"] == 0
    assert db_session.query(PriceHistory).filter_by(product_id=product_id).count() == 0


# ---------------------------------------------------------------------------
# MD-06: target_date = jüngster Werktag
# ---------------------------------------------------------------------------

from datetime import date, timedelta  # noqa: E402
from services.market_data_daily_refresh import _most_recent_business_day  # noqa: E402


def test_md06_most_recent_business_day_rolls_back_weekend():
    # 2026-06-27 ist Samstag, 2026-06-28 Sonntag, 2026-06-26 Freitag
    assert _most_recent_business_day(date(2026, 6, 27)) == date(2026, 6, 26)  # Sa -> Fr
    assert _most_recent_business_day(date(2026, 6, 28)) == date(2026, 6, 26)  # So -> Fr
    assert _most_recent_business_day(date(2026, 6, 26)) == date(2026, 6, 26)  # Fr unverändert
    assert _most_recent_business_day(date(2026, 6, 29)) == date(2026, 6, 29)  # Mo unverändert


def test_md06_asset_class_and_fx_requested_on_business_day(monkeypatch, db_session):
    """get_eod darf für asset-class/FX nie mit einem Wochenend-Datum aufgerufen werden."""
    seen_dates: list[date] = []

    class _CapturingAggregator(FakeAggregator):
        def get_eod(self, symbol: str, on_date: date) -> Bar:
            seen_dates.append(on_date)
            return super().get_eod(symbol, on_date)

    monkeypatch.setattr(
        "services.market_data.factory.build_default_aggregator",
        lambda: _CapturingAggregator(),
    )
    run_daily_market_data_refresh(db_session)
    assert seen_dates, "get_eod sollte für asset-class/FX aufgerufen werden"
    for d in seen_dates:
        assert d.weekday() < 5, f"{d} ist ein Wochenendtag (weekday={d.weekday()})"
