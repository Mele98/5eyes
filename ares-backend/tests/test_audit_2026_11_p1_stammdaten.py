"""Audit 2026-11, Paket P1: Produkt-Stammdaten im Fondsuniversum (Entscheid PO-6).

ISIN-Pruefziffer (ISO 6166, Luhn) -> 422; Altbestand ohne ISIN wird gekennzeichnet,
nicht gesperrt. Stammdatenfelder erfassen, validieren, importieren, exportieren,
bearbeiten, anzeigen. Der Standardkatalog erhaelt keine erfundenen Werte.
"""
from __future__ import annotations

import csv
import io
import sqlite3
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _path in (BACKEND_ROOT, TESTS_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from main import app  # noqa: E402
from models.review import ConflictOfInterestDisclosure, Product  # noqa: E402
from schemas.review import (  # noqa: E402
    declared_hedge_currency,
    isin_is_valid,
    isin_status,
    master_data_gaps,
    normalize_isin,
)
from services.cost_disclosure import build_cost_disclosure, calculate_cost_disclosure  # noqa: E402
from test_product_universe_fee_override import _mandate, _seed  # noqa: E402
from test_product_universe_fee_override import session_factory as cost_session_factory  # noqa: E402,F401
from test_products_fund_universe import _add_product, _client_for, _seed_tenants  # noqa: E402
from test_optimizer_shadow_mode import session_factory  # noqa: E402,F401

REVISION = "a8d3c5e7f9b1"
DOWN_REVISION = "f6a2c8e4b1d7"
NEW_COLUMNS = (
    "domicile", "is_hedged", "hedge_currency", "ter_source", "ter_as_of",
    "retrocession_bps", "retrocession_source", "is_house_product",
    "distribution_policy", "valor", "minimum_investment_minor_units",
)
VALID_ISIN = "ZZEXAMPLE019"  # gueltige Pruefziffer, nicht vergebenes Praefix


def _create_payload(**overrides):
    payload = {
        "product_name": "P1 Testfonds", "product_type": "ETF", "asset_class": "Aktien",
        "currency": "CHF", "suitability_profile_from": 3, "suitability_profile_to": 10,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# 1. ISIN (ISO 6166, Luhn)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("isin", ["US0378331005", "CH0012032048", "IE00B4L5Y983", VALID_ISIN])
def test_isin_check_digit_accepts_valid(isin):
    assert isin_is_valid(isin)
    assert normalize_isin(f"  {isin.lower()} ") == isin


@pytest.mark.parametrize("isin", ["US0378331006", "CH0012032040", "IE00BEXAMPLE1", "CH0000000BAD", "X"])
def test_isin_check_digit_rejects_invalid(isin):
    assert not isin_is_valid(isin)
    with pytest.raises(ValueError):
        normalize_isin(isin)


def test_invalid_isin_is_rejected_with_422(session_factory):
    _seed_tenants(session_factory, ["firm-a"])
    try:
        with _client_for(session_factory, user_id="u-a", tenant_id="firm-a") as client:
            bad = client.post("/products", json=_create_payload(isin="US0378331006"))
            good = client.post("/products", json=_create_payload(isin="us0378331005"))
    finally:
        app.dependency_overrides.clear()
    assert bad.status_code == 422, bad.text
    assert "Pruefziffer" in bad.text
    assert good.status_code == 201, good.text
    assert good.json()["isin"] == "US0378331005"
    assert good.json()["isin_status"] == "valid"


def test_invalid_isin_in_import_fails_only_that_row(session_factory):
    _seed_tenants(session_factory, ["firm-a"])
    try:
        with _client_for(session_factory, user_id="u-a", tenant_id="firm-a") as client:
            resp = client.post("/products/import", json={"products": [
                _create_payload(product_name="Gut", isin=VALID_ISIN),
            ]})
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow(["product_name", "product_type", "asset_class", "isin",
                             "suitability_profile_from", "suitability_profile_to"])
            writer.writerow(["Schlecht", "ETF", "Aktien", "US0378331006", "3", "10"])
            writer.writerow(["Ohne ISIN", "Fonds", "Aktien", "", "3", "10"])
            csv_resp = client.post(
                "/products/import/csv",
                files={"file": ("f.csv", buffer.getvalue().encode(), "text/csv")},
            )
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 201, resp.text
    assert resp.json()["created"] == 1
    body = csv_resp.json()
    assert body["created"] == 1 and body["failed"] == 1, body
    assert "isin" in body["items"][0]["error"]


def test_legacy_product_without_or_with_invalid_isin_is_marked_not_blocked(session_factory):
    _seed_tenants(session_factory, ["firm-a"])
    _add_product(session_factory, product_name="Alt ohne ISIN", tenant_id="firm-a")
    _add_product(session_factory, product_name="Alt mit kaputter ISIN", tenant_id="firm-a", isin="CH0000000BAD")
    try:
        with _client_for(session_factory, user_id="u-a", tenant_id="firm-a") as client:
            listed = {p["product_name"]: p for p in client.get("/products").json()}
            # Bearbeiten des Altbestands bleibt moeglich (gleiche ISIN mitgesendet)
            pid = listed["Alt mit kaputter ISIN"]["id"]
            edit = client.put(f"/products/{pid}", json={"isin": "CH0000000BAD", "provider": "X"})
    finally:
        app.dependency_overrides.clear()
    assert listed["Alt ohne ISIN"]["isin_status"] == "missing"
    assert listed["Alt mit kaputter ISIN"]["isin_status"] == "invalid"
    assert "isin" in listed["Alt ohne ISIN"]["master_data_gaps"]
    assert "isin" in listed["Alt mit kaputter ISIN"]["master_data_gaps"]
    assert edit.status_code == 200, edit.text


# ---------------------------------------------------------------------------
# 2. Stammdatenfelder: Erfassen, Validieren, Import, Export, Bearbeiten
# ---------------------------------------------------------------------------


def test_master_data_fields_roundtrip_and_validation(session_factory):
    _seed_tenants(session_factory, ["firm-a"])
    full = _create_payload(
        isin=VALID_ISIN, domicile="ie", is_hedged=True, hedge_currency="chf",
        ter_bps=20, ter_source="Basisinformationsblatt", ter_as_of="2026-01-31",
        retrocession_bps=35, retrocession_source="Vertriebsvertrag", is_house_product=False,
        distribution_policy="thesaurierend", valor="1'234'567", minimum_investment_minor_units=100_000,
    )
    try:
        with _client_for(session_factory, user_id="u-a", tenant_id="firm-a") as client:
            created = client.post("/products", json=full)
            rejected = {
                "domicile": client.post("/products", json=_create_payload(domicile="XX")),
                "retro_without_source": client.post("/products", json=_create_payload(retrocession_bps=10)),
                "hedge_currency_unhedged": client.post(
                    "/products", json=_create_payload(is_hedged=False, hedge_currency="CHF")),
                "ter_as_of_future": client.post(
                    "/products", json=_create_payload(ter_bps=10, ter_as_of="2999-01-01")),
                "distribution": client.post("/products", json=_create_payload(distribution_policy="monatlich")),
                "valor": client.post("/products", json=_create_payload(valor="12A")),
                "retro_negative": client.post(
                    "/products", json=_create_payload(retrocession_bps=-1, retrocession_source="x")),
            }
    finally:
        app.dependency_overrides.clear()
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["domicile"] == "IE"
    assert body["is_hedged"] is True and body["hedge_currency"] == "CHF"
    assert body["ter_source"] == "Basisinformationsblatt" and body["ter_as_of"] == "2026-01-31"
    assert body["retrocession_bps"] == 35 and body["retrocession_status"] == "present"
    assert body["is_house_product"] is False
    assert body["distribution_policy"] == "accumulating"
    assert body["valor"] == "1234567"
    assert body["minimum_investment_minor_units"] == 100_000
    assert body["master_data_gaps"] == []
    for name, resp in rejected.items():
        assert resp.status_code == 422, (name, resp.text)
    with session_factory() as s:
        stored = s.get(Product, body["id"])
        # Ja/Nein als 0/1 gespeichert (Postgres-INTEGER-Spalte)
        assert stored.is_hedged == 1 and stored.is_house_product == 0


def test_new_product_without_retro_is_unknown_never_retro_free(session_factory):
    _seed_tenants(session_factory, ["firm-a"])
    try:
        with _client_for(session_factory, user_id="u-a", tenant_id="firm-a") as client:
            body = client.post("/products", json=_create_payload()).json()
            zero = client.post("/products", json=_create_payload(
                product_name="Retrofrei", retrocession_bps=0, retrocession_source="Bestaetigung Anbieter",
            )).json()
    finally:
        app.dependency_overrides.clear()
    assert body["retrocession_bps"] is None
    assert body["retrocession_status"] == "unknown"
    assert "retrocession_bps" in body["master_data_gaps"]
    assert zero["retrocession_status"] == "none"


def test_update_sets_and_clears_master_data_with_merged_consistency(session_factory):
    _seed_tenants(session_factory, ["firm-a"])
    pid = _add_product(session_factory, product_name="Edit", tenant_id="firm-a")
    try:
        with _client_for(session_factory, user_id="u-a", tenant_id="firm-a") as client:
            no_source = client.put(f"/products/{pid}", json={"retrocession_bps": 25})
            ok = client.put(f"/products/{pid}", json={
                "retrocession_bps": 25, "retrocession_source": "Factsheet", "domicile": "LU",
                "is_hedged": True,
            })
            # Quelle allein entfernen -> Satz ohne Quelle -> 422 (gemergter Stand)
            drop_source = client.put(f"/products/{pid}", json={"retrocession_source": None})
            cleared = client.put(f"/products/{pid}", json={
                "retrocession_bps": None, "retrocession_source": None, "is_hedged": None,
            })
    finally:
        app.dependency_overrides.clear()
    assert no_source.status_code == 422, no_source.text
    assert ok.status_code == 200 and ok.json()["retrocession_bps"] == 25
    assert ok.json()["is_hedged"] is True and ok.json()["domicile"] == "LU"
    assert drop_source.status_code == 422, drop_source.text
    assert cleared.status_code == 200
    assert cleared.json()["retrocession_status"] == "unknown"
    assert cleared.json()["is_hedged"] is None
    assert cleared.json()["domicile"] == "LU"


def test_csv_template_import_export_cover_master_data(session_factory):
    _seed_tenants(session_factory, ["firm-a"])
    try:
        with _client_for(session_factory, user_id="u-a", tenant_id="firm-a") as client:
            template = client.get("/products/import/csv/template").text
            # Die Vorlage muss am eigenen Import bestehen (vorher 13-stellige ISIN).
            imported = client.post(
                "/products/import/csv",
                files={"file": ("t.csv", template.encode(), "text/csv")},
            ).json()
            exported = client.get("/products/export/csv")
            # Re-Import: leere Zelle = unveraendert (R7), Satz aendern mit Quelle.
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow(["product_name", "product_type", "asset_class", "isin",
                             "suitability_profile_from", "suitability_profile_to",
                             "retrocession_bps", "retrocession_source", "domicile"])
            writer.writerow(["Global Equity UCITS ETF", "Fonds", "Aktien", VALID_ISIN, "4", "10",
                             "40", "Vertriebsvertrag 2026", ""])
            reimport = client.post(
                "/products/import/csv",
                files={"file": ("r.csv", buffer.getvalue().encode(), "text/csv")},
            ).json()
            listed = {p["product_name"]: p for p in client.get("/products").json()}
    finally:
        app.dependency_overrides.clear()
    header = template.splitlines()[0].split(",")
    assert set(NEW_COLUMNS) <= set(header)
    assert imported["created"] == 2 and imported["failed"] == 0, imported
    assert exported.status_code == 200
    rows = list(csv.DictReader(io.StringIO(exported.text)))
    assert list(rows[0].keys()) == header
    by_name = {row["product_name"]: row for row in rows}
    assert by_name["Privatmarkt-Anlagestiftung"]["retrocession_bps"] == ""  # unbekannt bleibt leer
    assert by_name["Privatmarkt-Anlagestiftung"]["is_house_product"] == "ja"
    assert reimport["updated"] == 1, reimport
    etf = listed["Global Equity UCITS ETF"]
    assert etf["retrocession_bps"] == 40 and etf["retrocession_source"] == "Vertriebsvertrag 2026"
    assert etf["domicile"] == "IE"  # nicht geliefert -> unveraendert
    assert listed["Privatmarkt-Anlagestiftung"]["retrocession_status"] == "unknown"


def test_default_catalog_carries_no_invented_isin_or_retro(cost_session_factory):
    from services.portfolio_engine import ensure_default_products

    with cost_session_factory() as db:
        ensure_default_products(db)
        db.commit()
        seeded = db.query(Product).filter(Product.tenant_id.is_(None)).all()
        assert len(seeded) >= 10
        for product in seeded:
            for field in NEW_COLUMNS:
                assert getattr(product, field) is None, (product.product_name, field)
            assert product.isin is None, product.product_name


def test_declared_hedge_currency_hook():
    """Anbindungspunkt fuer currency_exposure_with_source (PR #856)."""
    class P:  # noqa: D401 - Testattrappe
        currency = "USD"
        is_hedged = None
        hedge_currency = None

    p = P()
    assert declared_hedge_currency(p) is None
    p.is_hedged = 1
    assert declared_hedge_currency(p) == "USD"
    p.hedge_currency = "CHF"
    assert declared_hedge_currency(p) == "CHF"
    p.is_hedged = 0
    assert declared_hedge_currency(p) is None


def test_master_data_gaps_helper():
    class P:
        isin = VALID_ISIN
        domicile = "IE"
        is_hedged = 0
        ter_bps = 20
        ter_source = "KID"
        ter_as_of = "2026-01-31"
        retrocession_bps = None
        is_house_product = 0

    assert master_data_gaps(P()) == ["retrocession_bps"]
    assert isin_status(None) == "missing"
