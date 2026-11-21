"""BBG-1 / Audit 2026-11/06 P2: Preis-Updater ohne stillen Fallback.

Befund vor dem Fix: ``price_refresh_primary_provider=bloomberg`` meldete
"nicht implementiert", der Fallback (stooq) fuellte ALLE Kurse,
``failures`` blieb leer, und der Status meldete weiter ``provider: bloomberg``.
Die Kurse kamen also still von einer Gratisquelle.

Nach dem Fix: Ist der Primaerprovider massgeblich (lizenziert, z. B.
Bloomberg) oder unbekannt, springt KEIN Fallback ein. Jedes Produkt landet
in der Fehlerliste, der Lauf meldet den Primaerstatus "nicht verfuegbar",
und der Status nennt je Kurs die tatsaechliche Quelle.

stooq/yfinance sind Fakes. Keine Netzwerkaufrufe. Der Bloomberg-Kursabruf
selbst folgt mit BBG-3; bis dahin meldet der Pfad
``BLOOMBERG_REQUEST_NOT_IMPLEMENTED``.
"""
from __future__ import annotations

import sys
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import price_updater
from database import Base
from models.review import PriceHistory, Product


def _product(pid: str, symbol: str) -> Product:
    return Product(
        id=pid,
        symbol=symbol,
        isin=None,
        product_name=f"Produkt {pid}",
        provider="Test Provider",
        product_type="ETF",
        asset_class="Equities",
        currency="CHF",
        exchange_code="SW",
        is_active=1,
        created_at="2026-10-01T00:00:00.000Z",
        updated_at="2026-10-01T00:00:00.000Z",
    )


@pytest.fixture()
def db_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'p2.db'}", connect_args={"check_same_thread": False})
    Session = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        with Session() as session:
            yield session
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def stooq_calls(monkeypatch):
    calls: list[list[str]] = []

    def fake_stooq(symbols, product_by_symbol=None):
        calls.append(list(symbols))
        return {s: (date.today().isoformat(), 1234500, "stooq") for s in symbols}, {}

    monkeypatch.setattr(price_updater, "_fetch_stooq_symbol_points", fake_stooq)
    return calls


def _set_sources(monkeypatch, primary: str, fallback: str) -> None:
    monkeypatch.setattr(price_updater, "PRICE_SOURCE", primary)
    monkeypatch.setattr(price_updater, "FALLBACK_PRICE_SOURCE", fallback)


def test_bloomberg_primary_does_not_silently_fall_back_to_stooq(monkeypatch, stooq_calls):
    monkeypatch.setitem(sys.modules, "blpapi", None)
    _set_sources(monkeypatch, "bloomberg", "stooq")
    products = [_product("p-1", "UBSG"), _product("p-2", "NESN")]

    points, failures = price_updater.fetch_latest_prices_batch(products)

    assert points == {}, "kein Kurs darf still von stooq kommen"
    assert stooq_calls == []
    assert set(failures) == {"p-1", "p-2"}
    for failure in failures.values():
        assert "nicht verfügbar" in failure["error"]
        assert "BLOOMBERG_REQUEST_NOT_IMPLEMENTED" in failure["error"]
        assert "kein Fallback" in failure["error"]


def test_bloomberg_primary_refresh_summary_reports_unavailable(monkeypatch, stooq_calls, db_session):
    monkeypatch.setitem(sys.modules, "blpapi", None)
    _set_sources(monkeypatch, "bloomberg", "stooq")
    db_session.add_all([_product("p-1", "UBSG"), _product("p-2", "NESN")])
    db_session.commit()

    summary = price_updater.refresh_all_prices(db_session)

    assert summary["failed"] == 2
    assert summary["inserted"] == 0
    assert len(summary["failures"]) == 2
    status = summary["primary_provider_status"]
    assert status["provider"] == "bloomberg"
    assert status["status"] == "nicht_verfuegbar"
    assert status["code"] == "BLOOMBERG_REQUEST_NOT_IMPLEMENTED"
    assert status["fallback_allowed"] is False
    assert summary["price_sources"] == {}
    assert db_session.query(PriceHistory).count() == 0
    assert stooq_calls == []

    runtime = price_updater.get_price_runtime_status()
    assert runtime["last_refresh_summary"]["primary_provider_status"]["status"] == "nicht_verfuegbar"


def test_unknown_primary_does_not_silently_fall_back(monkeypatch, stooq_calls):
    _set_sources(monkeypatch, "nonexistent", "stooq")
    points, failures = price_updater.fetch_latest_prices_batch([_product("p-1", "UBSG")])
    assert points == {}
    assert stooq_calls == []
    assert "nicht implementiert" in failures["p-1"]["error"]


def test_free_fallback_still_works_but_is_marked_per_price(monkeypatch, stooq_calls, db_session):
    """Positivkontrolle: Gratis-Primaer (yfinance) -> Gratis-Fallback (stooq)
    bleibt erlaubt, wird aber je Kurs sichtbar als Fallback markiert."""
    _set_sources(monkeypatch, "yfinance", "stooq")
    monkeypatch.setattr(
        price_updater,
        "_fetch_yfinance_symbol_points",
        lambda symbols: (
            {"NESN.SW": (date.today().isoformat(), 9900, "yfinance")},
            {s: "yfinance down" for s in symbols if s != "NESN.SW"},
        ),
    )
    db_session.add_all([_product("p-1", "UBSG"), _product("p-2", "NESN")])
    db_session.commit()

    points, failures = price_updater.fetch_latest_prices_batch(
        db_session.query(Product).order_by(Product.id).all()
    )
    assert failures == {}
    assert points["p-1"].source == "stooq"
    assert points["p-1"].fallback_reason and "yfinance" in points["p-1"].fallback_reason
    assert points["p-2"].source == "yfinance"
    assert points["p-2"].fallback_reason is None

    summary = price_updater.refresh_all_prices(db_session)
    assert summary["primary_provider_status"]["status"] == "teilweise"
    assert summary["price_sources"] == {"stooq": 1, "yfinance": 1}
    by_product = {row["product_id"]: row for row in summary["prices"]}
    assert by_product["p-1"]["source"] == "stooq"
    assert by_product["p-1"]["fallback_reason"]
    assert by_product["p-2"] == {
        "product_id": "p-2",
        "source": "yfinance",
        "fallback_reason": None,
    }
