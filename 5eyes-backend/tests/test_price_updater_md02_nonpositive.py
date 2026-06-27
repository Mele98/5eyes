"""MD-02: nicht-positive Kurse (price_rappen<=0) dürfen nie als gültiger Kurs
durchrutschen oder persistiert werden.

Deckt alle Verteidigungslinien des Fixes:
1. _collect_symbol_points: Provider-Payload mit fehlendem/0/negativem price_rappen
   -> symbol_errors statt 0-Kurs (kein 'or 0'-Masking mehr).
2. upsert_price_history: defensiver raise bei <=0.
3. refresh_all_prices: zentraler Filter -> Produkt wird als 'failed' gezählt,
   kein 0-Kurs landet in PriceHistory; Batch läuft weiter.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base
from main import app  # noqa: F401  (lädt alle Models + konfiguriert Mapper -> FK-Auflösung)
from models.review import PriceHistory, Product
from price_updater import (
    PricePoint,
    _collect_symbol_points,
    refresh_all_prices,
    upsert_price_history,
)


@pytest.fixture()
def db_session(tmp_path):
    db_path = tmp_path / "md02.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Session = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _product(pid: str) -> Product:
    return Product(
        id=pid,
        symbol="VT",
        isin="CH0000000001",
        product_name="Vanguard Total World",
        provider="Test Provider",
        product_type="ETF",
        asset_class="Equities",
        currency="CHF",
        is_active=1,
        created_at="2026-03-20T00:00:00.000Z",
        updated_at="2026-03-20T00:00:00.000Z",
    )


# ── 1. _collect_symbol_points ────────────────────────────────────────────────

def test_collect_keeps_positive_price():
    points, errors = _collect_symbol_points(
        {"VT": {"price_date": "2026-06-20", "price_rappen": 9900, "source": "twelvedata"}},
        default_source="twelvedata",
    )
    assert points == {"VT": ("2026-06-20", 9900, "twelvedata")}
    assert errors == {}


@pytest.mark.parametrize("bad", [0, -5, None, "abc", ""])
def test_collect_routes_nonpositive_or_missing_to_errors(bad):
    points, errors = _collect_symbol_points(
        {"VT": {"price_date": "2026-06-20", "price_rappen": bad, "source": "aggregator"}},
        default_source="aggregator",
    )
    assert "VT" not in points
    assert "VT" in errors
    assert "Ungültiger Kurs" in errors["VT"]


# ── 2. upsert_price_history ──────────────────────────────────────────────────

def test_upsert_rejects_nonpositive(db_session):
    product = _product("prod-up")
    db_session.add(product)
    db_session.commit()
    with pytest.raises(ValueError):
        upsert_price_history(db_session, product, PricePoint(price_date="2026-06-20", price_rappen=0, currency="CHF"))
    with pytest.raises(ValueError):
        upsert_price_history(db_session, product, PricePoint(price_date="2026-06-20", price_rappen=-1, currency="CHF"))
    # nichts persistiert
    assert db_session.query(PriceHistory).filter(PriceHistory.product_id == product.id).count() == 0


def test_upsert_accepts_positive(db_session):
    product = _product("prod-ok")
    db_session.add(product)
    db_session.commit()
    row, outcome = upsert_price_history(db_session, product, PricePoint(price_date="2026-06-20", price_rappen=10000, currency="CHF"))
    db_session.commit()
    assert outcome == "inserted"
    assert row.price_rappen == 10000


# ── 3. refresh_all_prices end-to-end (zentraler Filter) ──────────────────────

def test_refresh_zero_price_counts_failed_not_persisted(monkeypatch, db_session):
    import price_updater as mod

    product = _product("prod-zero")
    db_session.add(product)
    db_session.commit()

    # Provider liefert (fälschlich) einen 0-Kurs als 'resolved'.
    monkeypatch.setattr(
        mod,
        "fetch_latest_prices_batch",
        lambda products: (
            {product.id: PricePoint(price_date="2026-06-20", price_rappen=0, currency="CHF")},
            {},
        ),
    )

    summary = refresh_all_prices(db_session)
    assert summary["processed"] == 1
    assert summary["inserted"] == 0
    assert summary["failed"] == 1
    assert summary["failures"][0]["product_id"] == product.id
    # KEIN 0-Kurs in der DB
    assert db_session.query(PriceHistory).filter(PriceHistory.product_id == product.id).count() == 0


def test_refresh_mixed_batch_keeps_valid_drops_invalid(monkeypatch, db_session):
    import price_updater as mod

    good = _product("prod-good")
    bad = _product("prod-bad")
    db_session.add_all([good, bad])
    db_session.commit()

    monkeypatch.setattr(
        mod,
        "fetch_latest_prices_batch",
        lambda products: (
            {
                good.id: PricePoint(price_date="2026-06-20", price_rappen=12345, currency="CHF"),
                bad.id: PricePoint(price_date="2026-06-20", price_rappen=0, currency="CHF"),
            },
            {},
        ),
    )

    summary = refresh_all_prices(db_session)
    assert summary["inserted"] == 1
    assert summary["failed"] == 1
    assert db_session.query(PriceHistory).filter(PriceHistory.product_id == good.id).count() == 1
    assert db_session.query(PriceHistory).filter(PriceHistory.product_id == bad.id).count() == 0
