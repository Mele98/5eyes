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
