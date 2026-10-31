"""MD-03: erfolgreicher, aber veralteter Fetch darf nicht still als frischer Kurs
(inserted/updated) verbucht werden.

- Helper _is_stale_redundant_fetch: reine Logik (älter als Schwelle UND strikt
  älter als Bestand -> stale; Same-Date-Korrektur und Erst-Kurs bleiben erlaubt).
- refresh_all_prices end-to-end: alter Fetch gegen frischen Bestand -> summary['stale'].
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base
from main import app  # noqa: F401  (lädt alle Models + Mapper)
from models.review import PriceHistory, Product
from price_updater import (
    PricePoint,
    _is_stale_redundant_fetch,
    refresh_all_prices,
    utc_now_iso,
)


@pytest.fixture()
def db_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path/'md03.db'}", connect_args={"check_same_thread": False})
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
        id=pid, symbol="VT", isin="CH0000000001",
        product_name="World ETF", provider="P", product_type="ETF",
        asset_class="Equities", currency="CHF", is_active=1,
        created_at="2026-03-20T00:00:00.000Z", updated_at="2026-03-20T00:00:00.000Z",
    )


def _pp(d: date, rappen: int = 12345) -> PricePoint:
    return PricePoint(price_date=d.isoformat(), price_rappen=rappen, currency="CHF")


# ── Helper-Unit ──────────────────────────────────────────────────────────────

def test_helper_fresh_not_stale():
    today = date(2026, 6, 27)
    is_stale, age = _is_stale_redundant_fetch(_pp(date(2026, 6, 25)), None, today, 5)
    assert is_stale is False
    assert age == 2


def test_helper_old_without_existing_not_stale():
    """Kein Bestandskurs -> auch alter Wert wird gespeichert (besser als nichts)."""
    today = date(2026, 6, 27)
    is_stale, age = _is_stale_redundant_fetch(_pp(date(2026, 5, 1)), None, today, 5)
    assert is_stale is False
    assert age > 5


def test_helper_old_and_older_than_existing_is_stale():
    today = date(2026, 6, 27)
    existing = SimpleNamespace(price_date="2026-06-26")
    is_stale, age = _is_stale_redundant_fetch(_pp(date(2026, 5, 1)), existing, today, 5)
    assert is_stale is True
    assert age > 5


def test_helper_old_same_date_correction_not_stale():
    """Same-Date-Preis-Korrektur (strikt-älter-Regel) bleibt erlaubt."""
    today = date(2026, 6, 27)
    existing = SimpleNamespace(price_date="2026-05-01")
    is_stale, _ = _is_stale_redundant_fetch(_pp(date(2026, 5, 1)), existing, today, 5)
    assert is_stale is False


# ── End-to-end ───────────────────────────────────────────────────────────────

def test_refresh_counts_stale_and_skips_upsert(monkeypatch, db_session):
    import price_updater as mod

    product = _product("prod-stale")
    db_session.add(product)
    # frischer Bestandskurs (gestern)
    fresh_date = (date.today() - timedelta(days=1)).isoformat()
    db_session.add(PriceHistory(
        id="ph-1", product_id=product.id, price_date=fresh_date,
        price_rappen=10000, currency="CHF", source="x", fetched_at=utc_now_iso(),
    ))
    db_session.commit()

    # Provider liefert einen 40 Tage alten Kurs -> stale & älter als Bestand
    old = date.today() - timedelta(days=40)
    monkeypatch.setattr(mod, "fetch_latest_prices_batch",
                        lambda products: ({product.id: _pp(old, 9999)}, {}))

    summary = refresh_all_prices(db_session)
    assert summary["stale"] == 1
    assert summary["inserted"] == 0
    assert summary["updated"] == 0
    # kein neuer (alter) Kurs eingefügt
    assert db_session.query(PriceHistory).filter(
        PriceHistory.product_id == product.id,
        PriceHistory.price_date == old.isoformat(),
    ).count() == 0


def test_refresh_fresh_fetch_still_inserts(monkeypatch, db_session):
    import price_updater as mod

    product = _product("prod-fresh")
    db_session.add(product)
    db_session.commit()

    monkeypatch.setattr(mod, "fetch_latest_prices_batch",
                        lambda products: ({product.id: _pp(date.today(), 13000)}, {}))

    summary = refresh_all_prices(db_session)
    assert summary["stale"] == 0
    assert summary["inserted"] == 1
