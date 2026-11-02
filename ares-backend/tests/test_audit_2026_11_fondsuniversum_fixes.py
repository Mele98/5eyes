"""Audit 2026-11 / 03 (Fondsuniversum und Eingrenzung): Regressionstests.

Uebernimmt die Reproduzenten R1, R3, R5, R6 und R7 aus Anhang A des
Audit-Berichts als regulaere Tests, mit umgedrehten Erwartungen (der
Reproducer assertete den fehlerhaften Ist-Zustand). R2, R4, R8 und R9 sind
Owner-Entscheide und bewusst nicht Teil dieser Datei.

Isolation: jede Testfunktion hat eine eigene SQLite-Datei unter tmp_path
(session_factory aus test_rec001_cross_tenant_product_visibility); die
TestClient-Lifespan laeuft gegen die per conftest isolierte DB_PATH.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(BACKEND_ROOT / "tests"))

import test_rec001_cross_tenant_product_visibility as h  # noqa: E402
from database import get_db  # noqa: E402
from main import app  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from models.product_eligibility import ProductEligibilityRule  # noqa: E402
from models.review import AuditLog, Product, ProductUniverseEntry  # noqa: E402
from models.tenant import Tenant  # noqa: E402
from models.users import User  # noqa: E402
from services.auth import get_current_user  # noqa: E402
from services.portfolio_engine import ensure_default_products, generate_recommendation_run  # noqa: E402

session_factory = h.session_factory  # fixture re-export

def _gen(SF, mid, adv):
    with SF() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        res = generate_recommendation_run(s, mandate, adv, preferences=None)
        s.commit()
    return res


@pytest.fixture()
def client(session_factory):
    def override_db():
        with session_factory() as s:
            yield s
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _as(user_id, role, tenant_id):
    u = User(id=user_id, username=user_id, password_hash="h", full_name=user_id,
             role=role, is_active=1, tenant_id=tenant_id)
    app.dependency_overrides[get_current_user] = lambda: u


def _strict(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "strict_tenant_isolation", True)


def _two_tenants_and_global_product(session_factory):
    now = h._now()
    with session_factory() as s:
        for tid in ("firm-a", "firm-b"):
            s.add(Tenant(id=tid, display_name=tid, slug=tid, hosting_tier="tier2",
                         license_status="active", is_active=1, created_at=now, updated_at=now))
        s.add(Product(id="g1", product_name="Globaler Fonds", asset_class="Aktien", product_type="ETF",
                      currency="CHF", ter_bps=20, is_active=1, created_at=now, updated_at=now))
        s.add(Product(id="own-a", product_name="Eigener Fonds A", asset_class="Aktien", product_type="Fonds",
                      currency="CHF", ter_bps=30, is_active=1, tenant_id="firm-a",
                      created_at=now, updated_at=now))
        s.commit()


# --- R3: Tenant-Admin darf globale Produkte nicht aendern ------------------
def test_r3_tenant_admin_cannot_mutate_global_product(session_factory, client, monkeypatch):
    _strict(monkeypatch)
    _two_tenants_and_global_product(session_factory)
    _as("admin-a", "admin", "firm-a")
    r = client.put("/products/g1", json={"ter_bps": 999, "is_active": 0})
    r_override = client.put("/products/g1/market-override", json={"lookup_symbol_override": "X"})
    _as("adv-b", "advisor", "firm-b")
    seen_b = [p for p in client.get("/products").json() if p["id"] == "g1"]
    with session_factory() as s:
        g = s.get(Product, "g1")
        state = (g.ter_bps, g.is_active, g.lookup_symbol_override)
    assert r.status_code == 403, r.text
    assert "Globale Katalogfonds" in r.json()["detail"]
    assert r_override.status_code == 403, r_override.text
    assert state == (20, 1, None)
    assert seen_b, "firm-b sieht den globalen Fonds weiterhin"


def test_r3_tenant_admin_can_still_edit_own_product(session_factory, client, monkeypatch):
    _strict(monkeypatch)
    _two_tenants_and_global_product(session_factory)
    _as("admin-a", "admin", "firm-a")
    r = client.put("/products/own-a", json={"ter_bps": 25})
    assert r.status_code == 200, r.text
    assert r.json()["ter_bps"] == 25


def test_r3_super_admin_may_edit_global_product(session_factory, client, monkeypatch):
    _strict(monkeypatch)
    _two_tenants_and_global_product(session_factory)
    _as("root", "super_admin", None)
    r = client.put("/products/g1", json={"ter_bps": 22})
    assert r.status_code == 200, r.text
    with session_factory() as s:
        assert s.get(Product, "g1").ter_bps == 22


def test_r3_batch_write_pool_excludes_global_catalog_for_tenant_admin(session_factory, monkeypatch):
    _strict(monkeypatch)
    _two_tenants_and_global_product(session_factory)
    from routers.review import _writable_products_query
    admin_a = User(id="admin-a", username="admin-a", password_hash="h", full_name="a",
                   role="admin", is_active=1, tenant_id="firm-a")
    root = User(id="root", username="root", password_hash="h", full_name="r",
                role="super_admin", is_active=1, tenant_id=None)
    with session_factory() as s:
        assert {p.id for p in _writable_products_query(s, admin_a).all()} == {"own-a"}
        assert "g1" in {p.id for p in _writable_products_query(s, root).all()}
