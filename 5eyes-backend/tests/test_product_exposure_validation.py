"""PROD-DOMAIN-001 (Codex-Audit 2026-09-05): country_exposure_json/
sector_exposure_json/currency_exposure_json sowie duration_years_x10/
esg_score_x10/liquidity_tier/credit_rating/is_active hatten auf
ProductCreate/ProductUpdate keinerlei Shape-/Domain-/Bounds-Validierung.

Reproduziert vor dem Fix:
- Ein syntaktisch gueltiges, aber fachlich unmoegliches JSON (z.B. negative
  Sektorgewichte oder eine Summe weit ab von 10000bps) wurde anstandslos
  gespeichert und floss unveraendert in services/depot_check.py /
  services/advisory_report.py ein -- echte Kundenreports konnten dadurch
  unmoegliche Exposure-Prozentsaetze zeigen.
- services/product_exposures.py::_parse_or_proxy behandelte kaputtes JSON
  lautlos wie "nicht angegeben" und ersetzte es durch einen Proxy-Wert.

Dieser Test-File verifiziert die neue Schema-Validierung (rot->gruen) UND
dass legitime Produktdaten (inkl. der bereits im CSV-Template genutzten
Werte) weiterhin unveraendert durchgehen (Regression)."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for path in (BACKEND_ROOT, TESTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from database import get_db
from main import app
from models.review import Product
from models.tenant import Tenant
from schemas.review import ProductCreate, ProductUpdate
from services.auth import get_current_user
from services.product_exposures import (
    country_exposure_for_product,
    sector_exposure_for_product,
)
from test_optimizer_shadow_mode import session_factory  # noqa: F401


def _now() -> str:
    return "2026-09-05T10:00:00.000Z"


def _seed_tenant(session_factory, tenant_id: str) -> None:
    with session_factory() as s:
        if s.get(Tenant, tenant_id) is None:
            s.add(Tenant(
                id=tenant_id, display_name=tenant_id, slug=tenant_id.lower(),
                hosting_tier="tier2", license_status="active",
                is_active=1, created_at=_now(), updated_at=_now(),
            ))
        s.commit()


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


BASE_PRODUCT_PAYLOAD = {
    "product_name": "Test Fonds",
    "product_type": "Fonds",
    "asset_class": "Aktien",
    "currency": "CHF",
}


# ===== RED->GREEN: ProductCreate/ProductUpdate lehnen fachlich unmoegliche
# Exposure-JSON-Werte ab =====

def test_create_product_rejects_malformed_json_exposure():
    with pytest.raises(ValidationError):
        ProductCreate(**BASE_PRODUCT_PAYLOAD, country_exposure_json="{not valid json")


def test_create_product_rejects_non_object_exposure_json():
    with pytest.raises(ValidationError):
        ProductCreate(**BASE_PRODUCT_PAYLOAD, sector_exposure_json=json.dumps([1, 2, 3]))


def test_create_product_rejects_negative_exposure_value():
    with pytest.raises(ValidationError):
        ProductCreate(
            **BASE_PRODUCT_PAYLOAD,
            sector_exposure_json=json.dumps({"Financials": -500, "Energy": 10500}),
        )


def test_create_product_rejects_exposure_sum_far_from_10000():
    with pytest.raises(ValidationError):
        ProductCreate(
            **BASE_PRODUCT_PAYLOAD,
            country_exposure_json=json.dumps({"CH": 3000, "US": 3000}),
        )


def test_create_product_rejects_exposure_value_over_100_percent():
    """Reproduziert den Audit-Fund woertlich: eine einzelne >100%-Position."""
    with pytest.raises(ValidationError):
        ProductCreate(
            **BASE_PRODUCT_PAYLOAD,
            currency_exposure_json=json.dumps({"CHF": 15000}),
        )


def test_create_product_rejects_non_numeric_exposure_value():
    with pytest.raises(ValidationError):
        ProductCreate(**BASE_PRODUCT_PAYLOAD, country_exposure_json=json.dumps({"CH": "viel"}))


def test_update_product_rejects_malformed_exposure_json_too():
    with pytest.raises(ValidationError):
        ProductUpdate(sector_exposure_json="[[[")


# ===== Regression: legitime Werte funktionieren weiterhin =====

def test_create_product_accepts_valid_exposure_json():
    p = ProductCreate(
        **BASE_PRODUCT_PAYLOAD,
        country_exposure_json=json.dumps({"CH": 3000, "US": 6500, "RoW": 500}),
        sector_exposure_json=json.dumps({"Financials": 4000, "Health Care": 6000}),
        currency_exposure_json=json.dumps({"CHF": 10000}),
    )
    assert json.loads(p.country_exposure_json) == {"CH": 3000, "US": 6500, "RoW": 500}


def test_create_product_accepts_exposure_sum_within_rounding_tolerance():
    """±50bps Toleranz -- selbe Konvention wie
    schemas/snapshots.py::StrategySnapshotCreate.check_bps_sum."""
    p = ProductCreate(
        **BASE_PRODUCT_PAYLOAD,
        country_exposure_json=json.dumps({"CH": 3000, "US": 6960}),  # sum=9960, -40bps
    )
    assert p.country_exposure_json is not None


def test_create_product_rejects_exposure_sum_just_outside_tolerance():
    with pytest.raises(ValidationError):
        ProductCreate(
            **BASE_PRODUCT_PAYLOAD,
            country_exposure_json=json.dumps({"CH": 3000, "US": 6940}),  # sum=9940, -60bps
        )


def test_create_product_accepts_none_and_empty_exposure_json():
    p = ProductCreate(**BASE_PRODUCT_PAYLOAD, country_exposure_json=None)
    assert p.country_exposure_json is None
    p2 = ProductCreate(**BASE_PRODUCT_PAYLOAD, country_exposure_json="")
    assert p2.country_exposure_json == ""


def test_create_product_accepts_explicit_empty_object_as_no_data():
    """{} bedeutet bewusst 'keine Exposure-Daten' (Depot-Check zeigt
    'unbekannt') -- unterscheidet sich von kaputtem JSON und muss erlaubt sein."""
    p = ProductCreate(**BASE_PRODUCT_PAYLOAD, sector_exposure_json="{}")
    assert p.sector_exposure_json == "{}"


# ===== duration_years_x10 / esg_score_x10 bounds =====

def test_create_product_rejects_negative_duration():
    with pytest.raises(ValidationError):
        ProductCreate(**BASE_PRODUCT_PAYLOAD, duration_years_x10=-10)


def test_create_product_rejects_absurd_duration_typo():
    with pytest.raises(ValidationError):
        ProductCreate(**BASE_PRODUCT_PAYLOAD, duration_years_x10=500000)  # Tippfehler-Nullen


def test_create_product_accepts_legitimate_long_duration_bond():
    p = ProductCreate(**BASE_PRODUCT_PAYLOAD, duration_years_x10=250)  # 25 Jahre
    assert p.duration_years_x10 == 250


def test_create_product_rejects_esg_score_out_of_range():
    with pytest.raises(ValidationError):
        ProductCreate(**BASE_PRODUCT_PAYLOAD, esg_score_x10=1500)  # >100.0


def test_create_product_accepts_esg_score_in_range():
    p = ProductCreate(**BASE_PRODUCT_PAYLOAD, esg_score_x10=850)  # 85.0
    assert p.esg_score_x10 == 850


# ===== liquidity_tier / credit_rating enum =====

def test_create_product_rejects_unknown_liquidity_tier():
    with pytest.raises(ValidationError):
        ProductCreate(**BASE_PRODUCT_PAYLOAD, liquidity_tier="sofort-jederzeit")


@pytest.mark.parametrize("tier", ["daily", "weekly", "monthly", "illiquid"])
def test_create_product_accepts_canonical_liquidity_tiers(tier):
    p = ProductCreate(**BASE_PRODUCT_PAYLOAD, liquidity_tier=tier)
    assert p.liquidity_tier == tier


def test_create_product_rejects_unknown_credit_rating():
    with pytest.raises(ValidationError):
        ProductCreate(**BASE_PRODUCT_PAYLOAD, credit_rating="SuperSafe")


@pytest.mark.parametrize("rating", ["AAA", "AA", "A", "BBB", "BB", "B", "CCC", "NR"])
def test_create_product_accepts_canonical_credit_ratings(rating):
    p = ProductCreate(**BASE_PRODUCT_PAYLOAD, credit_rating=rating)
    assert p.credit_rating == rating


# ===== is_active bounds on ProductUpdate =====

def test_update_product_rejects_out_of_range_is_active():
    with pytest.raises(ValidationError):
        ProductUpdate(is_active=2)


def test_update_product_accepts_valid_is_active():
    assert ProductUpdate(is_active=0).is_active == 0
    assert ProductUpdate(is_active=1).is_active == 1


# ===== End-to-end via echte Router-Endpoints (Create + Update) =====

def test_create_product_endpoint_rejects_impossible_sector_exposure(session_factory):
    _seed_tenant(session_factory, "firm-exp")
    try:
        with _client_for(session_factory, user_id="u-exp", tenant_id="firm-exp") as client:
            resp = client.post("/products", json={
                **BASE_PRODUCT_PAYLOAD,
                "sector_exposure_json": json.dumps({"Financials": -2000, "Energy": 12000}),
            })
            assert resp.status_code == 422, resp.text
    finally:
        app.dependency_overrides.clear()


def test_create_product_endpoint_accepts_legitimate_exposure(session_factory):
    _seed_tenant(session_factory, "firm-exp2")
    try:
        with _client_for(session_factory, user_id="u-exp2", tenant_id="firm-exp2") as client:
            resp = client.post("/products", json={
                **BASE_PRODUCT_PAYLOAD,
                "sub_asset_class": "Aktien Global",
                "country_exposure_json": json.dumps({"US": 6500, "CH": 300, "RoW": 3200}),
                "duration_years_x10": None,
                "credit_rating": "AA",
                "esg_score_x10": 700,
                "liquidity_tier": "daily",
            })
            assert resp.status_code == 201, resp.text
            body = resp.json()
            assert json.loads(body["country_exposure_json"]) == {"US": 6500, "CH": 300, "RoW": 3200}
            assert body["credit_rating"] == "AA"
            assert body["liquidity_tier"] == "daily"
    finally:
        app.dependency_overrides.clear()


def test_update_product_endpoint_rejects_impossible_currency_exposure(session_factory):
    _seed_tenant(session_factory, "firm-exp3")
    pid = str(uuid4())
    with session_factory() as s:
        s.add(Product(
            id=pid, product_name="Update-Ziel", asset_class="Aktien",
            product_type="Fonds", currency="CHF", is_active=1,
            tenant_id="firm-exp3", created_at=_now(), updated_at=_now(),
        ))
        s.commit()
    try:
        with _client_for(session_factory, user_id="u-exp3", tenant_id="firm-exp3") as client:
            resp = client.put(f"/products/{pid}", json={
                "currency_exposure_json": json.dumps({"CHF": 20000}),
            })
            assert resp.status_code == 422, resp.text
        with session_factory() as s:
            unchanged = s.get(Product, pid)
            assert unchanged.currency_exposure_json is None
    finally:
        app.dependency_overrides.clear()


# ===== services/product_exposures.py::_parse_or_proxy: Legacy-kaputtes JSON
# faellt weiterhin fault-tolerant auf Proxy zurueck (kein Crash), statt lautlos
# wie "nicht angegeben" durchzugehen (jetzt geloggt -- siehe caplog-Test) =====

def test_parse_or_proxy_falls_back_to_proxy_for_legacy_malformed_json(caplog):
    """Simuliert eine Legacy-DB-Zeile mit kaputtem JSON, die vor dem
    Schema-Fix gespeichert wurde -- darf nicht crashen, aber der Fallback
    muss laut sein (Warnung geloggt), nicht lautlos wie 'leer' behandelt werden."""
    import logging
    with caplog.at_level(logging.WARNING, logger="services.product_exposures"):
        result = country_exposure_for_product("{not valid json", "Aktien Global")
    assert result  # Proxy fuer "Aktien Global" greift weiterhin
    assert any("ungueltig" in rec.message for rec in caplog.records)


def test_parse_or_proxy_treats_genuinely_absent_value_silently(caplog):
    """Ein echtes None (Feld nie gepflegt) ist ein normaler, erwarteter Fall
    und darf KEINE Warnung ausloesen -- nur explizit-aber-kaputt soll laut sein."""
    import logging
    with caplog.at_level(logging.WARNING, logger="services.product_exposures"):
        result = sector_exposure_for_product(None, "Aktien Global")
    assert result  # Proxy greift
    assert not any("ungueltig" in rec.message for rec in caplog.records)
