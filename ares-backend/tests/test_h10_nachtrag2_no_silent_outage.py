"""H10 Nachtrag 2: kein stiller Ausfall bei gesperrter Datenuebermittlung.

* ``GET /privacy/egress-status`` meldet gesperrte Kanaele mangels Freigabe,
  den Kurs-Datenstand und ob der Benutzer Admin ist (Banner/Direktlink);
  nach der Freigabe ist der Status frei.
* Ein Kursabruf bei gesperrtem Egress schreibt nichts: kein neuer Preis, kein
  0- oder Ersatzkurs; der Fehler nennt den Egress-Code, der Datenstand bleibt
  der alte (veraltet statt neuer Werte).
Werte sind Testwerte.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from services import egress_manifest as em
from tests.h10_support import OTHER_TENANT, api, user


def _seed_price(factory) -> None:
    from models.review import PriceHistory, Product

    with factory() as s:
        s.add(Product(id="p-1", isin="CH0012032048", symbol="ROG", product_name="Testprodukt", product_type="Aktie",
                      asset_class="Aktien", sub_asset_class="Aktien Schweiz", currency="CHF", ter_bps=0,
                      provider="Test", is_active=1, created_at="2026-11-01", updated_at="2026-11-01"))
        s.flush()
        s.add(PriceHistory(id="ph-1", product_id="p-1", price_date="2026-11-03", price_rappen=25000,
                           currency="CHF", source="stooq", fetched_at="2026-11-03T18:00:00Z"))
        s.commit()


def test_status_reports_blocked_channels_and_data_as_of_until_approved(tmp_path):
    with api(tmp_path) as (client, current, factory):
        _seed_price(factory)
        status = client.get("/privacy/egress-status").json()
        assert status["approved"] is False and status["is_admin"] is True
        assert "market_data" in status["blocked_classes"]
        assert status["message"].startswith("Datenübermittlung gesperrt – Marktdaten, Updates und E-Mail")
        assert status["market_data_status"] == "NOT_UPDATED_EGRESS_BLOCKED"
        assert status["market_data_message"] == "nicht aktualisiert – Datenübermittlung nicht freigegeben"
        assert status["data_as_of"]["product_prices"] == "2026-11-03"

        current["user"] = user("advisor-1", role="advisor")
        advisor = client.get("/privacy/egress-status").json()
        assert advisor["is_admin"] is False and advisor["approved"] is False
        current["user"] = user("advisor-1", role="client")
        assert client.get("/privacy/egress-status").status_code == 403

        current["user"] = user("qb-admin")
        assert client.post("/privacy/egress-manifest/approve", json={}).status_code == 200
        status = client.get("/privacy/egress-status").json()
        assert status["approved"] is True and status["message"] is None
        assert status["market_data_status"] == "EGRESS_APPROVED"


def test_blocked_price_refresh_writes_no_new_or_placeholder_price(tmp_path, monkeypatch):
    import database
    import price_updater
    from routers.privacy import install_egress_guard, uninstall_egress_guard
    from services.market_data_daily_refresh import _refresh_product_prices

    with api(tmp_path) as (client, _current, factory):
        _seed_price(factory)
        monkeypatch.setattr(database, "SessionLocal", factory)
        monkeypatch.setattr(price_updater, "PRICE_SOURCE", "stooq")
        monkeypatch.setattr(price_updater, "FALLBACK_PRICE_SOURCE", "stooq")
        monkeypatch.setattr(price_updater.time, "sleep", lambda *_a, **_k: None)
        install_egress_guard()
        try:
            from models.review import Product

            errors: list[dict] = []
            with factory() as s:
                counts = _refresh_product_prices(s, [s.get(Product, "p-1")], errors)
                s.commit()
        finally:
            uninstall_egress_guard()
        assert counts["products_refreshed"] == 0 and counts["product_failures"] == 1
        assert "EGRESS_MANIFEST_MISSING" in errors[0]["reason"]
        with factory() as s:
            prices = s.execute(text("SELECT price_date, price_rappen FROM price_history")).all()
        assert [tuple(p) for p in prices] == [("2026-11-03", 25000)], "kein neuer, kein 0-/Ersatzkurs"
        status = client.get("/privacy/egress-status").json()
        assert status["data_as_of"]["product_prices"] == "2026-11-03"
        assert status["market_data_status"] == "NOT_UPDATED_EGRESS_BLOCKED"
        assert any(e["reason_code"] == "EGRESS_MANIFEST_MISSING" for e in client.get("/privacy/egress-events").json())


def test_other_tenant_admin_sees_installation_status(tmp_path):
    """Egress ist eine Installationseinstellung (Mandant main): auch ein Admin
    eines anderen Mandanten sieht die Sperre, kann sie aber nicht fuer main
    freigeben."""
    with api(tmp_path) as (client, current, _factory):
        current["user"] = user("admin-b", tenant=OTHER_TENANT)
        assert client.get("/privacy/egress-status").json()["approved"] is False
        client.post("/privacy/egress-manifest/approve", json={})
        assert client.get("/privacy/egress-status").json()["approved"] is False


@pytest.fixture(autouse=True)
def _guard_off():
    yield
    em.deactivate()
