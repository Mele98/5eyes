"""Fondsuniversum (2026-08-05, User-Direktive): "Beim Fondsuniversum wirklich
alle Fonds anzeigen die wir ziehen und eine Suchfunktion haben und auch eine
Funktion selber unsere Fonds einzugeben ... damit jedes Assetmanagement seine
eigene Fonds der Software fuettern kann."

Verifiziert:
- create_product stampt tenant_id serverseitig aus current_user (nie aus dem
  Client-Payload -- ProductCreate hat gar kein tenant_id-Feld, ein
  Spoofing-Versuch im JSON-Body wird von Pydantic stillschweigend ignoriert).
- list_products zeigt den globalen Katalog (tenant_id IS NULL) PLUS die
  eigenen privaten Fonds -- NIE die eines anderen Tenants.
- Freitext-Suche (q) ueber Produktname/Anbieter/ISIN/Symbol.
- Ein nicht-kotierter Fonds (kein ISIN/Symbol) ist ein voll gueltiges Produkt.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for path in (BACKEND_ROOT, TESTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from database import get_db
from main import app
from models.review import Product
from models.tenant import Tenant
from services.auth import get_current_user
from test_optimizer_shadow_mode import session_factory  # noqa: F401


def _now() -> str:
    return "2026-08-05T10:00:00.000Z"


def _seed_tenants(session_factory, tenant_ids: list[str]) -> None:
    with session_factory() as s:
        for tid in tenant_ids:
            if s.get(Tenant, tid) is None:
                s.add(Tenant(
                    id=tid, display_name=tid, slug=tid.lower(),
                    hosting_tier="tier2", license_status="active",
                    is_active=1, created_at=_now(), updated_at=_now(),
                ))
        s.commit()


def _add_product(session_factory, *, product_name: str, tenant_id: str | None = None, **overrides) -> str:
    pid = str(uuid4())
    fields = dict(
        id=pid, product_name=product_name, asset_class="Aktien",
        product_type="Fonds", currency="CHF", is_active=1,
        tenant_id=tenant_id, created_at=_now(), updated_at=_now(),
    )
    fields.update(overrides)
    with session_factory() as s:
        s.add(Product(**fields))
        s.commit()
    return pid


def _client_for(session_factory, *, user_id: str, tenant_id: str | None, role: str = "admin") -> TestClient:
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()
    current = SimpleNamespace(
        id=user_id, full_name=f"Tester {user_id}",
        email=f"{user_id}@test.local", role=role, tenant_id=tenant_id,
    )
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: current
    return TestClient(app)


def test_create_product_stamps_tenant_id_from_current_user(session_factory):
    _seed_tenants(session_factory, ["firm-a"])
    try:
        with _client_for(session_factory, user_id="u-a", tenant_id="firm-a") as client:
            resp = client.post("/products", json={
                "product_name": "Firma A Hausfonds",
                "product_type": "Fonds",
                "asset_class": "Aktien",
                "currency": "CHF",
            })
            assert resp.status_code == 201, resp.text
            assert resp.json()["tenant_id"] == "firm-a"
    finally:
        app.dependency_overrides.clear()


def test_create_product_ignores_client_supplied_tenant_id_spoofing_attempt(session_factory):
    """ProductCreate hat kein tenant_id-Feld -- ein Spoofing-Versuch im
    JSON-Body wird von Pydantic stillschweigend verworfen, tenant_id kommt
    IMMER vom authentifizierten current_user."""
    _seed_tenants(session_factory, ["firm-a", "firm-b"])
    try:
        with _client_for(session_factory, user_id="u-a", tenant_id="firm-a") as client:
            resp = client.post("/products", json={
                "product_name": "Spoofed Fonds",
                "product_type": "Fonds",
                "asset_class": "Aktien",
                "currency": "CHF",
                "tenant_id": "firm-b",
            })
            assert resp.status_code == 201, resp.text
            assert resp.json()["tenant_id"] == "firm-a"
    finally:
        app.dependency_overrides.clear()


def test_list_products_shows_global_and_own_tenant_but_not_other_tenant(session_factory):
    _seed_tenants(session_factory, ["firm-a", "firm-b"])
    _add_product(session_factory, product_name="Globaler ETF", tenant_id=None)
    _add_product(session_factory, product_name="Firma A Fonds", tenant_id="firm-a")
    _add_product(session_factory, product_name="Firma B Fonds", tenant_id="firm-b")
    try:
        with _client_for(session_factory, user_id="u-a", tenant_id="firm-a") as client:
            resp = client.get("/products")
            assert resp.status_code == 200
            names = {p["product_name"] for p in resp.json()}
    finally:
        app.dependency_overrides.clear()
    assert names == {"Globaler ETF", "Firma A Fonds"}
    assert "Firma B Fonds" not in names


def test_list_products_other_tenant_sees_own_not_first_tenants(session_factory):
    _seed_tenants(session_factory, ["firm-a", "firm-b"])
    _add_product(session_factory, product_name="Globaler ETF", tenant_id=None)
    _add_product(session_factory, product_name="Firma A Fonds", tenant_id="firm-a")
    _add_product(session_factory, product_name="Firma B Fonds", tenant_id="firm-b")
    try:
        with _client_for(session_factory, user_id="u-b", tenant_id="firm-b") as client:
            resp = client.get("/products")
            names = {p["product_name"] for p in resp.json()}
    finally:
        app.dependency_overrides.clear()
    assert names == {"Globaler ETF", "Firma B Fonds"}
    assert "Firma A Fonds" not in names


def test_search_matches_product_name_provider_isin_symbol(session_factory):
    _add_product(session_factory, product_name="UBS Alpha Fund", provider="UBS")
    _add_product(session_factory, product_name="Anderer Fonds", provider="Sonstige", isin="CH0001234567")
    _add_product(session_factory, product_name="Dritter Fonds", provider="Sonstige", symbol="XYZ")
    _add_product(session_factory, product_name="Unbeteiligt", provider="Nichts")
    try:
        with _client_for(session_factory, user_id="u-search", tenant_id=None) as client:
            by_name = {p["product_name"] for p in client.get("/products?q=Alpha").json()}
            by_provider = {p["product_name"] for p in client.get("/products?q=UBS").json()}
            by_isin = {p["product_name"] for p in client.get("/products?q=CH0001234567").json()}
            by_symbol = {p["product_name"] for p in client.get("/products?q=XYZ").json()}
    finally:
        app.dependency_overrides.clear()
    assert by_name == {"UBS Alpha Fund"}
    assert by_provider == {"UBS Alpha Fund"}
    assert by_isin == {"Anderer Fonds"}
    assert by_symbol == {"Dritter Fonds"}


def test_bulk_import_json_creates_multiple_products(session_factory):
    _seed_tenants(session_factory, ["firm-a"])
    try:
        with _client_for(session_factory, user_id="u-a", tenant_id="firm-a") as client:
            resp = client.post("/products/import", json={"products": [
                {"product_name": "Fonds Eins", "product_type": "Fonds", "asset_class": "Aktien", "currency": "CHF"},
                {"product_name": "Fonds Zwei", "product_type": "Fonds", "asset_class": "Obligationen", "currency": "CHF"},
            ]})
            assert resp.status_code == 201, resp.text
            body = resp.json()
            listed = client.get("/products").json()
    finally:
        app.dependency_overrides.clear()
    assert body["processed"] == 2
    assert body["created"] == 2
    assert body["updated"] == 0
    assert body["failed"] == 0
    assert all(item["status"] == "created" for item in body["items"])
    by_name = {p["product_name"]: p for p in listed}
    assert {"Fonds Eins", "Fonds Zwei"} <= set(by_name)
    assert by_name["Fonds Eins"]["tenant_id"] == "firm-a"


def test_bulk_import_upserts_on_matching_isin_same_tenant(session_factory):
    """Re-Upload desselben Fondskatalogs (z.B. monatlich) darf keine
    Duplikate erzeugen -- ein Match auf (tenant_id, isin) aktualisiert
    das bestehende Produkt statt ein zweites anzulegen."""
    _seed_tenants(session_factory, ["firm-a"])
    try:
        with _client_for(session_factory, user_id="u-a", tenant_id="firm-a") as client:
            first = client.post("/products/import", json={"products": [
                {"product_name": "UBS Fund V1", "product_type": "Fonds", "asset_class": "Aktien",
                 "currency": "CHF", "isin": "CH0001111111", "ter_bps": 20},
            ]})
            assert first.status_code == 201, first.text
            product_id = first.json()["items"][0]["product_id"]

            second = client.post("/products/import", json={"products": [
                {"product_name": "UBS Fund V2 (umbenannt)", "product_type": "Fonds", "asset_class": "Aktien",
                 "currency": "CHF", "isin": "CH0001111111", "ter_bps": 25},
            ]})
            assert second.status_code == 201, second.text
            body = second.json()
            listed = client.get("/products?q=CH0001111111").json()
    finally:
        app.dependency_overrides.clear()
    assert body["created"] == 0
    assert body["updated"] == 1
    assert body["items"][0]["status"] == "updated"
    assert body["items"][0]["product_id"] == product_id
    assert len(listed) == 1
    assert listed[0]["product_name"] == "UBS Fund V2 (umbenannt)"
    assert listed[0]["ter_bps"] == 25


def test_bulk_import_upsert_never_crosses_tenant_boundary(session_factory):
    """Ein Re-Upload von Firma A mit derselben ISIN darf NIE ein Produkt
    von Firma B aktualisieren -- der Match ist strikt tenant-gescoped.
    products.isin ist aber GLOBAL eindeutig (siehe create_product), daher
    wird die Zeile korrekt als Konflikt gemeldet statt eine zweite,
    kollidierende Kopie der ISIN anzulegen (Live-Smoketest-Fund, 2026-08-05)."""
    _seed_tenants(session_factory, ["firm-a", "firm-b"])
    other_id = _add_product(
        session_factory, product_name="Firma B Original",
        tenant_id="firm-b", isin="CH0009999999",
    )
    try:
        with _client_for(session_factory, user_id="u-a", tenant_id="firm-a") as client:
            resp = client.post("/products/import", json={"products": [
                {"product_name": "Firma A Version", "product_type": "Fonds", "asset_class": "Aktien",
                 "currency": "CHF", "isin": "CH0009999999"},
            ]})
            assert resp.status_code == 201, resp.text
            body = resp.json()
    finally:
        app.dependency_overrides.clear()
    assert body["created"] == 0
    assert body["updated"] == 0
    assert body["failed"] == 1
    with session_factory() as s:
        untouched = s.get(Product, other_id)
        assert untouched.product_name == "Firma B Original"
        assert untouched.tenant_id == "firm-b"


def test_bulk_import_upserts_unlisted_fund_on_matching_name_same_tenant(session_factory):
    """Live-Smoketest-Fund (2026-08-05): ein nicht-kotierter Fonds hat weder
    ISIN noch Symbol -- ohne Namens-Fallback wuerde jeder Re-Upload eines
    Private-Markets-Katalogs (genau die Fondsklasse, fuer die dieser Import
    gebaut wurde) Duplikate erzeugen statt zu aktualisieren."""
    _seed_tenants(session_factory, ["firm-a"])
    try:
        with _client_for(session_factory, user_id="u-a", tenant_id="firm-a") as client:
            first = client.post("/products/import", json={"products": [
                {"product_name": "Privatmarktfonds X", "product_type": "Fonds",
                 "asset_class": "Alternative", "currency": "CHF", "ter_bps": 150},
            ]})
            assert first.status_code == 201, first.text
            product_id = first.json()["items"][0]["product_id"]

            second = client.post("/products/import", json={"products": [
                {"product_name": "Privatmarktfonds X", "product_type": "Fonds",
                 "asset_class": "Alternative", "currency": "CHF", "ter_bps": 180},
            ]})
            assert second.status_code == 201, second.text
            body = second.json()
            listed = client.get("/products?q=Privatmarktfonds+X").json()
    finally:
        app.dependency_overrides.clear()
    assert body["created"] == 0
    assert body["updated"] == 1
    assert body["items"][0]["product_id"] == product_id
    assert len(listed) == 1
    assert listed[0]["ter_bps"] == 180


def test_bulk_import_unlisted_name_match_never_overwrites_already_listed_fund(session_factory):
    """Ein gleichnamiger, aber bereits KOTIERTER Fonds darf durch einen
    Re-Upload ohne ISIN/Symbol nie versehentlich ueberschrieben werden --
    der Namens-Fallback matcht nur gegen andere ebenfalls-nicht-kotierte
    Zeilen."""
    _seed_tenants(session_factory, ["firm-a"])
    listed_id = _add_product(
        session_factory, product_name="Doppelgaenger Fonds",
        tenant_id="firm-a", isin="CH0LISTED0001",
    )
    try:
        with _client_for(session_factory, user_id="u-a", tenant_id="firm-a") as client:
            resp = client.post("/products/import", json={"products": [
                {"product_name": "Doppelgaenger Fonds", "product_type": "Fonds",
                 "asset_class": "Aktien", "currency": "CHF"},
            ]})
            assert resp.status_code == 201, resp.text
            body = resp.json()
    finally:
        app.dependency_overrides.clear()
    assert body["created"] == 1
    assert body["updated"] == 0
    with session_factory() as s:
        listed = s.get(Product, listed_id)
        assert listed.isin == "CH0LISTED0001"


def test_create_product_duplicate_isin_same_tenant_returns_409_not_500(session_factory):
    """Live-Smoketest-Fund (2026-08-05): products.isin hat einen globalen
    Unique-Index -- ohne Vorab-Check crasht ein zweiter Fonds mit derselben
    ISIN mit einem rohen 500 (IntegrityError) statt einer verstaendlichen
    Fehlermeldung. Reproduziert live beim manuellen Erfassen im Fonds-
    universum-Panel."""
    _seed_tenants(session_factory, ["firm-a"])
    _add_product(session_factory, product_name="Erster Fonds", tenant_id="firm-a", isin="CH0DUP00001")
    try:
        with _client_for(session_factory, user_id="u-a", tenant_id="firm-a") as client:
            resp = client.post("/products", json={
                "product_name": "Zweiter Fonds, gleiche ISIN",
                "product_type": "Fonds", "asset_class": "Aktien",
                "currency": "CHF", "isin": "CH0DUP00001",
            })
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 409, resp.text
    assert "CH0DUP00001" in resp.json()["detail"]


def test_create_product_duplicate_isin_across_tenants_returns_409_not_500(session_factory):
    """Dieselbe ISIN-Kollision, aber von einem VOELLIG ANDEREN Tenant --
    Firma B kann Firma As privaten Fonds gar nicht sehen (Isolation bleibt
    korrekt), bekommt aber trotzdem eine klare 409 statt eines Absturzes,
    weil die ISIN global (nicht tenant-gescoped) eindeutig sein muss."""
    _seed_tenants(session_factory, ["firm-a", "firm-b"])
    _add_product(session_factory, product_name="Firma A Fonds", tenant_id="firm-a", isin="CH0DUP00002")
    try:
        with _client_for(session_factory, user_id="u-b", tenant_id="firm-b") as client:
            resp = client.post("/products", json={
                "product_name": "Firma B Fonds, gleiche ISIN",
                "product_type": "Fonds", "asset_class": "Aktien",
                "currency": "CHF", "isin": "CH0DUP00002",
            })
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 409, resp.text


def test_bulk_import_isin_conflict_with_other_tenant_fails_row_not_whole_batch(session_factory):
    """Ein ISIN-Konflikt mit einem PRIVATEN Fonds eines anderen Tenants darf
    nur DIESE Zeile als 'failed' melden -- die restlichen Zeilen desselben
    Imports muessen trotzdem durchlaufen (partial success bleibt erhalten,
    kein roher 500 fuer den gesamten Batch)."""
    _seed_tenants(session_factory, ["firm-a", "firm-b"])
    _add_product(session_factory, product_name="Firma A Fonds", tenant_id="firm-a", isin="CH0DUP00003")
    try:
        with _client_for(session_factory, user_id="u-b", tenant_id="firm-b") as client:
            resp = client.post("/products/import", json={"products": [
                {"product_name": "Kollisions-Fonds", "product_type": "Fonds",
                 "asset_class": "Aktien", "currency": "CHF", "isin": "CH0DUP00003"},
                {"product_name": "Unbeteiligter Fonds", "product_type": "Fonds",
                 "asset_class": "Obligationen", "currency": "CHF"},
            ]})
            assert resp.status_code == 201, resp.text
            body = resp.json()
    finally:
        app.dependency_overrides.clear()
    assert body["processed"] == 2
    assert body["created"] == 1
    assert body["failed"] == 1
    failed_item = next(i for i in body["items"] if i["status"] == "failed")
    assert failed_item["product_name"] == "Kollisions-Fonds"
    assert "CH0DUP00003" in failed_item["error"]
    created_item = next(i for i in body["items"] if i["status"] == "created")
    assert created_item["product_name"] == "Unbeteiligter Fonds"


def test_bulk_import_duplicate_isin_within_same_batch_same_tenant_collapses_via_upsert(session_factory):
    """Zwei Zeilen IM SELBEN Import, selber Tenant, dieselbe (neue) ISIN --
    das ist kein Tenant-Konflikt (siehe die beiden anderen ISIN-Konflikt-
    Tests), sondern faellt unter dieselbe Upsert-Logik wie ein Re-Upload:
    die zweite Zeile aktualisiert die von der ersten Zeile soeben
    angelegte Zeile, statt als Fehler oder Duplikat zu enden."""
    _seed_tenants(session_factory, ["firm-a"])
    try:
        with _client_for(session_factory, user_id="u-a", tenant_id="firm-a") as client:
            resp = client.post("/products/import", json={"products": [
                {"product_name": "Fonds A", "product_type": "Fonds",
                 "asset_class": "Aktien", "currency": "CHF", "isin": "CH0DUP00004", "ter_bps": 10},
                {"product_name": "Fonds A (korrigiert)", "product_type": "Fonds",
                 "asset_class": "Aktien", "currency": "CHF", "isin": "CH0DUP00004", "ter_bps": 20},
            ]})
            assert resp.status_code == 201, resp.text
            body = resp.json()
    finally:
        app.dependency_overrides.clear()
    assert body["created"] == 1
    assert body["updated"] == 1
    assert body["failed"] == 0
    assert body["items"][0]["status"] == "created"
    assert body["items"][1]["status"] == "updated"
    assert body["items"][1]["product_id"] == body["items"][0]["product_id"]


def test_bulk_import_json_rejects_invalid_row_at_request_level(session_factory):
    """JSON-API validiert strikt beim Request-Parsing (ProductCreate hat
    ein Literal fuer asset_class) -- anders als beim CSV-Import (siehe
    dort) gibt es hier kein Teilerfolg-Verhalten, das ist beabsichtigt:
    ein programmatischer API-Aufrufer soll sofort und eindeutig scheitern."""
    _seed_tenants(session_factory, ["firm-a"])
    try:
        with _client_for(session_factory, user_id="u-a", tenant_id="firm-a") as client:
            resp = client.post("/products/import", json={"products": [
                {"product_name": "Schlecht", "product_type": "Fonds", "asset_class": "Bitcoin", "currency": "CHF"},
            ]})
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 422


def test_bulk_import_json_rejects_empty_products_list(session_factory):
    _seed_tenants(session_factory, ["firm-a"])
    try:
        with _client_for(session_factory, user_id="u-a", tenant_id="firm-a") as client:
            resp = client.post("/products/import", json={"products": []})
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 422


def test_import_endpoints_require_admin_role(session_factory):
    _seed_tenants(session_factory, ["firm-a"])
    try:
        with _client_for(session_factory, user_id="u-a", tenant_id="firm-a", role="advisor") as client:
            resp = client.post("/products/import", json={"products": [
                {"product_name": "X", "product_type": "Fonds", "asset_class": "Aktien", "currency": "CHF"},
            ]})
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 403


def test_csv_import_creates_listed_and_unlisted_funds(session_factory):
    _seed_tenants(session_factory, ["firm-a"])
    csv_bytes = (
        "product_name,provider,product_type,asset_class,sub_asset_class,currency,"
        "isin,symbol,ter_bps,sfdr_class,esg_rating,liquidity_tier\n"
        "Global Equity ETF,Beispiel AM,Fonds,Aktien,Global,CHF,IE00BTEST001,GEQC,25,8,AA,daily\n"
        "Privatmarktfonds,Beispiel AM,Fonds,Alternative,Private Equity,CHF,,,150,,,illiquid\n"
    ).encode("utf-8")
    try:
        with _client_for(session_factory, user_id="u-a", tenant_id="firm-a") as client:
            resp = client.post(
                "/products/import/csv",
                files={"file": ("funds.csv", csv_bytes, "text/csv")},
            )
            assert resp.status_code == 201, resp.text
            body = resp.json()
            listed = client.get("/products").json()
    finally:
        app.dependency_overrides.clear()
    assert body["processed"] == 2
    assert body["created"] == 2
    assert body["failed"] == 0
    by_name = {p["product_name"]: p for p in listed}
    assert by_name["Global Equity ETF"]["isin"] == "IE00BTEST001"
    assert by_name["Privatmarktfonds"]["isin"] is None
    assert by_name["Privatmarktfonds"]["symbol"] is None
    assert all(p["tenant_id"] == "firm-a" for p in by_name.values())


def test_csv_import_detects_semicolon_delimiter(session_factory):
    """Schweizer/deutsches Excel exportiert CSV standardmaessig mit
    Semikolon als Trennzeichen -- muss automatisch erkannt werden."""
    _seed_tenants(session_factory, ["firm-a"])
    csv_bytes = (
        "product_name;provider;product_type;asset_class;sub_asset_class;currency;"
        "isin;symbol;ter_bps;sfdr_class;esg_rating;liquidity_tier\n"
        "Schweizer Obligationenfonds;Beispiel AM;Fonds;Obligationen;CH-Bonds;CHF;;;45;;;daily\n"
    ).encode("utf-8")
    try:
        with _client_for(session_factory, user_id="u-a", tenant_id="firm-a") as client:
            resp = client.post(
                "/products/import/csv",
                files={"file": ("funds.csv", csv_bytes, "text/csv")},
            )
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["created"] == 1
    assert body["items"][0]["product_name"] == "Schweizer Obligationenfonds"


def test_csv_import_partial_failure_reports_row_and_continues(session_factory):
    """Eine fehlerhafte Zeile (ungueltige asset_class) darf den restlichen
    Import NICHT abbrechen -- partial success, Fehler landet im Report."""
    _seed_tenants(session_factory, ["firm-a"])
    csv_bytes = (
        "product_name,product_type,asset_class,currency\n"
        "Guter Fonds,Fonds,Aktien,CHF\n"
        "Schlechter Fonds,Fonds,Bitcoin,CHF\n"
    ).encode("utf-8")
    try:
        with _client_for(session_factory, user_id="u-a", tenant_id="firm-a") as client:
            resp = client.post(
                "/products/import/csv",
                files={"file": ("funds.csv", csv_bytes, "text/csv")},
            )
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["processed"] == 2
    assert body["created"] == 1
    assert body["failed"] == 1
    failed_item = next(i for i in body["items"] if i["status"] == "failed")
    assert failed_item["row"] == 2
    assert failed_item["product_name"] == "Schlechter Fonds"
    assert "asset_class" in failed_item["error"]


def test_csv_import_ignores_tenant_id_column_spoofing_attempt(session_factory):
    _seed_tenants(session_factory, ["firm-a", "firm-b"])
    csv_bytes = (
        "product_name,product_type,asset_class,currency,tenant_id\n"
        "Gespoofter Fonds,Fonds,Aktien,CHF,firm-b\n"
    ).encode("utf-8")
    try:
        with _client_for(session_factory, user_id="u-a", tenant_id="firm-a") as client:
            resp = client.post(
                "/products/import/csv",
                files={"file": ("funds.csv", csv_bytes, "text/csv")},
            )
            assert resp.status_code == 201, resp.text
            listed = client.get("/products").json()
    finally:
        app.dependency_overrides.clear()
    product = next(p for p in listed if p["product_name"] == "Gespoofter Fonds")
    assert product["tenant_id"] == "firm-a"


def test_csv_import_rejects_too_many_rows(session_factory):
    _seed_tenants(session_factory, ["firm-a"])
    header = "product_name,product_type,asset_class,currency\n"
    rows = "".join(f"Fonds {i},Fonds,Aktien,CHF\n" for i in range(1001))
    csv_bytes = (header + rows).encode("utf-8")
    try:
        with _client_for(session_factory, user_id="u-a", tenant_id="firm-a") as client:
            resp = client.post(
                "/products/import/csv",
                files={"file": ("funds.csv", csv_bytes, "text/csv")},
            )
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 422


def test_csv_import_rejects_oversized_file(session_factory):
    _seed_tenants(session_factory, ["firm-a"])
    oversized = b"product_name,product_type,asset_class,currency\n" + b"x" * (2 * 1024 * 1024 + 1)
    try:
        with _client_for(session_factory, user_id="u-a", tenant_id="firm-a") as client:
            resp = client.post(
                "/products/import/csv",
                files={"file": ("funds.csv", oversized, "text/csv")},
            )
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 413


def test_csv_template_download_has_expected_headers(session_factory):
    _seed_tenants(session_factory, ["firm-a"])
    try:
        with _client_for(session_factory, user_id="u-a", tenant_id="firm-a") as client:
            resp = client.get("/products/import/csv/template")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    first_line = resp.text.splitlines()[0]
    assert first_line == (
        "product_name,provider,product_type,asset_class,sub_asset_class,currency,"
        "isin,symbol,ter_bps,sfdr_class,esg_rating,liquidity_tier"
    )


def test_unlisted_fund_without_isin_or_symbol_is_valid(session_factory):
    """Nicht-kotierte Fonds (kein ISIN/Symbol, keine Live-Bepreisung) sind
    ein voll gueltiges Produkt -- isin/symbol sind bereits optional."""
    _seed_tenants(session_factory, ["firm-a"])
    try:
        with _client_for(session_factory, user_id="u-a", tenant_id="firm-a") as client:
            resp = client.post("/products", json={
                "product_name": "Proprietaerer Privatmarktfonds",
                "product_type": "Fonds",
                "asset_class": "Alternative",
                "currency": "CHF",
            })
            assert resp.status_code == 201, resp.text
            body = resp.json()
            assert body["isin"] is None
            assert body["symbol"] is None
            assert body["tenant_id"] == "firm-a"
    finally:
        app.dependency_overrides.clear()
