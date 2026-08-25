"""Sprint U-95 (2026-06-05): Tests fuer ESG/SFDR-Filter auf GET /products.

Verifiziert:
  - sfdr_class={6,8,9} filtert korrekt
  - sfdr_class mit ungueltigem Wert -> 422
  - esg_rating case-insensitive Match
  - Filter sind additiv (AND mit asset_class)
  - Endpoint ohne Filter bleibt rueckwaerts-kompatibel
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
from services.auth import get_current_user
from test_optimizer_shadow_mode import session_factory  # noqa: F401


def _add_product(
    session_factory,
    *,
    product_name: str,
    asset_class: str = "Aktien",
    sfdr_class: str | None = None,
    esg_rating: str | None = None,
) -> str:
    pid = str(uuid4())
    now = "2026-06-05T10:00:00.000Z"
    with session_factory() as s:
        s.add(Product(
            id=pid, product_name=product_name, asset_class=asset_class,
            product_type="ETF", currency="CHF", is_active=1,
            sfdr_class=sfdr_class, esg_rating=esg_rating,
            created_at=now, updated_at=now,
        ))
        s.commit()
    return pid


def _client(session_factory) -> TestClient:
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()
    current = SimpleNamespace(
        id="user-u95", full_name="Tester U95",
        email="u95@test.local", role="advisor",
    )
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: current
    return TestClient(app)


# ---------------------------------------------------------------------------
# Backward Compatibility — kein Filter
# ---------------------------------------------------------------------------

def test_list_products_without_filter_returns_all_active(session_factory):
    _add_product(session_factory, product_name="A", sfdr_class="6")
    _add_product(session_factory, product_name="B", sfdr_class="8")
    _add_product(session_factory, product_name="C", sfdr_class="9")
    try:
        with _client(session_factory) as client:
            response = client.get("/products")
            assert response.status_code == 200
            assert len(response.json()) == 3
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# sfdr_class Filter
# ---------------------------------------------------------------------------

def test_sfdr_class_8_filter_returns_only_art8(session_factory):
    _add_product(session_factory, product_name="A6", sfdr_class="6")
    _add_product(session_factory, product_name="A8", sfdr_class="8")
    _add_product(session_factory, product_name="A9", sfdr_class="9")
    try:
        with _client(session_factory) as client:
            response = client.get("/products?sfdr_class=8")
            assert response.status_code == 200
            data = response.json()
    finally:
        app.dependency_overrides.clear()
    assert len(data) == 1
    assert data[0]["product_name"] == "A8"
    assert data[0]["sfdr_class"] == "8"


def test_sfdr_class_9_filter(session_factory):
    _add_product(session_factory, product_name="X8", sfdr_class="8")
    _add_product(session_factory, product_name="X9", sfdr_class="9")
    try:
        with _client(session_factory) as client:
            response = client.get("/products?sfdr_class=9")
            data = response.json()
    finally:
        app.dependency_overrides.clear()
    assert len(data) == 1
    assert data[0]["sfdr_class"] == "9"


def test_sfdr_class_6_filter(session_factory):
    _add_product(session_factory, product_name="P6", sfdr_class="6")
    _add_product(session_factory, product_name="P8", sfdr_class="8")
    try:
        with _client(session_factory) as client:
            response = client.get("/products?sfdr_class=6")
            data = response.json()
    finally:
        app.dependency_overrides.clear()
    assert len(data) == 1
    assert data[0]["sfdr_class"] == "6"


def test_sfdr_class_invalid_value_returns_422(session_factory):
    """7 ist keine gueltige SFDR-Klasse — 6/8/9 sind erlaubt."""
    try:
        with _client(session_factory) as client:
            response = client.get("/products?sfdr_class=7")
            assert response.status_code == 422
            assert "6" in response.text and "8" in response.text and "9" in response.text
    finally:
        app.dependency_overrides.clear()


def test_sfdr_class_empty_treated_as_none(session_factory):
    """Leerer SFDR-Wert -> FastAPI parsed als None -> kein Filter."""
    _add_product(session_factory, product_name="EA", sfdr_class="6")
    try:
        with _client(session_factory) as client:
            response = client.get("/products?sfdr_class=")
            # Empty string ist '' (nicht None) -> 422 weil nicht in Whitelist
            assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# esg_rating Filter
# ---------------------------------------------------------------------------

def test_esg_rating_filter_case_insensitive(session_factory):
    _add_product(session_factory, product_name="P-AAA", esg_rating="AAA")
    _add_product(session_factory, product_name="P-aaa", esg_rating="aaa")
    _add_product(session_factory, product_name="P-BBB", esg_rating="BBB")
    try:
        with _client(session_factory) as client:
            response = client.get("/products?esg_rating=aaa")
            data = response.json()
    finally:
        app.dependency_overrides.clear()
    assert len(data) == 2  # AAA + aaa -> beide matchen
    names = sorted(p["product_name"] for p in data)
    assert names == ["P-AAA", "P-aaa"]


def test_esg_rating_empty_returns_422(session_factory):
    try:
        with _client(session_factory) as client:
            response = client.get("/products?esg_rating=%20")  # nur Whitespace
            assert response.status_code == 422
            assert "leer" in response.text or "esg" in response.text.lower()
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Kombinierter Filter (AND-Verknuepfung)
# ---------------------------------------------------------------------------

def test_combined_sfdr_and_esg_rating_filter(session_factory):
    _add_product(session_factory, product_name="A1", sfdr_class="8", esg_rating="AAA")
    _add_product(session_factory, product_name="A2", sfdr_class="8", esg_rating="BBB")
    _add_product(session_factory, product_name="A3", sfdr_class="9", esg_rating="AAA")
    try:
        with _client(session_factory) as client:
            response = client.get("/products?sfdr_class=8&esg_rating=AAA")
            data = response.json()
    finally:
        app.dependency_overrides.clear()
    assert len(data) == 1
    assert data[0]["product_name"] == "A1"


def test_asset_class_and_sfdr_combined(session_factory):
    _add_product(session_factory, product_name="Eq8", asset_class="Aktien", sfdr_class="8")
    _add_product(session_factory, product_name="Bond8", asset_class="Obligationen", sfdr_class="8")
    _add_product(session_factory, product_name="Eq6", asset_class="Aktien", sfdr_class="6")
    try:
        with _client(session_factory) as client:
            response = client.get("/products?asset_class=Aktien&sfdr_class=8")
            data = response.json()
    finally:
        app.dependency_overrides.clear()
    assert len(data) == 1
    assert data[0]["product_name"] == "Eq8"


# ---------------------------------------------------------------------------
# Products ohne SFDR/ESG bleiben unsichtbar bei Filter
# ---------------------------------------------------------------------------

def test_products_with_null_sfdr_excluded_by_filter(session_factory):
    """Produkt ohne gepflegtes sfdr_class wird bei sfdr-Filter nicht gefunden."""
    _add_product(session_factory, product_name="Tagged", sfdr_class="8")
    _add_product(session_factory, product_name="Untagged", sfdr_class=None)
    try:
        with _client(session_factory) as client:
            # Ohne Filter -> beide sichtbar
            both = client.get("/products").json()
            assert len(both) == 2
            # Mit SFDR-Filter -> nur das gepflegte
            filtered = client.get("/products?sfdr_class=8").json()
            assert len(filtered) == 1
            assert filtered[0]["product_name"] == "Tagged"
    finally:
        app.dependency_overrides.clear()
