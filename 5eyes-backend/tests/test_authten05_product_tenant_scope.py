"""AUTH-TEN-05 (Codex-Audit 2026-08-25, docs/audits/2026-08-25-auth-execution-
operations-followup-audit.md): der zentrale Produktlookup
(routers/review.py::_get_product_or_404) hatte keinen Tenantfilter -- ein
Admin von Firma A konnte ein PRIVATES Produkt von Firma B lesen/aendern/
mappen oder in die eigene Fondsuniversum-Kuratierung uebernehmen.

Diese Tests decken die neue, opt-in Durchsetzung ab (nur bei
strict_tenant_isolation -- Tier-1 bleibt unveraendert). Globale Produkte
(tenant_id IS NULL) und das eigene Tenant-Produkt bleiben in JEDEM Modus
editierbar.
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, get_db  # noqa: E402
from main import app  # noqa: E402
from models.review import Product  # noqa: E402
from models.tenant import Tenant  # noqa: E402
from models.users import User  # noqa: E402
from services.auth import get_current_user  # noqa: E402


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'authten05.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _seed(SF):
    now = _now()
    with SF() as s:
        for tid in ("firm-a", "firm-b"):
            s.add(Tenant(
                id=tid, display_name=tid, slug=tid,
                hosting_tier="tier2", license_status="active",
                is_active=1, created_at=now, updated_at=now,
            ))
        s.add(User(
            id="admin-a", username="admin-a", password_hash="h", full_name="Admin A",
            role="admin", is_active=1, tenant_id="firm-a", created_at=now, updated_at=now,
        ))
        s.add(User(
            id="advisor-a", username="advisor-a", password_hash="h", full_name="Advisor A",
            role="advisor", is_active=1, tenant_id="firm-a", created_at=now, updated_at=now,
        ))
        s.add(Product(
            id="prod-global", product_name="Global Fund", asset_class="Aktien",
            product_type="ETF", currency="CHF", is_active=1, ter_bps=20,
            tenant_id=None, created_at=now, updated_at=now,
        ))
        s.add(Product(
            id="prod-firm-a-private", product_name="Firm A Private Fund", asset_class="Aktien",
            product_type="ETF", currency="CHF", is_active=1, ter_bps=20,
            tenant_id="firm-a", created_at=now, updated_at=now,
        ))
        s.add(Product(
            id="prod-firm-b-private", product_name="Firm B Private Fund", asset_class="Aktien",
            product_type="ETF", currency="CHF", is_active=1, ter_bps=20,
            tenant_id="firm-b", created_at=now, updated_at=now,
        ))
        s.commit()


@pytest.fixture()
def client(session_factory):
    def override_db():
        with session_factory() as s:
            yield s
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _login_admin_a():
    user = User(id="admin-a", username="admin-a", password_hash="h", full_name="Admin A",
                role="admin", is_active=1, tenant_id="firm-a")
    app.dependency_overrides[get_current_user] = lambda: user


def _logout():
    app.dependency_overrides.pop(get_current_user, None)


# ---------------------------------------------------------------------------
# update_product (PUT /products/{id})
# ---------------------------------------------------------------------------

def test_update_foreign_private_product_blocked_when_strict_tenant_isolation(client, session_factory, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "strict_tenant_isolation", True)
    _seed(session_factory)
    _login_admin_a()
    try:
        resp = client.put("/products/prod-firm-b-private", json={"ter_bps": 99})
        assert resp.status_code == 404, resp.text
    finally:
        _logout()


def test_update_foreign_private_product_allowed_by_default_tier1(client, session_factory):
    """Tier-1 (Default, kein strict_tenant_isolation): unveraendertes
    Verhalten -- das ist genau das bestehende, bereits vor diesem Fix
    getestete Verhalten (siehe test_cma_jurisdiction_query_param.py fuer
    den analogen CMA-Fall)."""
    _seed(session_factory)
    _login_admin_a()
    try:
        resp = client.put("/products/prod-firm-b-private", json={"ter_bps": 99})
        assert resp.status_code == 200, resp.text
    finally:
        _logout()


def test_update_own_private_product_always_allowed(client, session_factory, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "strict_tenant_isolation", True)
    _seed(session_factory)
    _login_admin_a()
    try:
        resp = client.put("/products/prod-firm-a-private", json={"ter_bps": 15})
        assert resp.status_code == 200, resp.text
    finally:
        _logout()


def test_update_global_product_always_allowed(client, session_factory, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "strict_tenant_isolation", True)
    _seed(session_factory)
    _login_admin_a()
    try:
        resp = client.put("/products/prod-global", json={"ter_bps": 25})
        assert resp.status_code == 200, resp.text
    finally:
        _logout()


# ---------------------------------------------------------------------------
# create_product_universe_entry (POST /product-universe)
# ---------------------------------------------------------------------------

def test_universe_entry_for_foreign_private_product_blocked_when_strict(client, session_factory, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "strict_tenant_isolation", True)
    _seed(session_factory)
    _login_admin_a()
    try:
        resp = client.post("/product-universe", json={
            "jurisdiction": "CH", "product_id": "prod-firm-b-private",
        })
        assert resp.status_code == 404, resp.text
    finally:
        _logout()


def test_universe_entry_for_global_product_allowed_when_strict(client, session_factory, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "strict_tenant_isolation", True)
    _seed(session_factory)
    _login_admin_a()
    try:
        resp = client.post("/product-universe", json={
            "jurisdiction": "CH", "product_id": "prod-global",
        })
        assert resp.status_code == 201, resp.text
    finally:
        _logout()


# ---------------------------------------------------------------------------
# add_position (manuelle Position) -- POST .../recommendations/{run_id}/positions
# ---------------------------------------------------------------------------

def test_manual_position_referencing_foreign_private_product_blocked_when_strict(
    client, session_factory, monkeypatch,
):
    from config import settings
    from models.allocation import OptimizerPolicy
    from models.clients import Client
    from models.mandates import Mandate
    from models.review import RecommendationRun

    monkeypatch.setattr(settings, "strict_tenant_isolation", True)
    _seed(session_factory)
    now = _now()
    with session_factory() as s:
        s.add(Client(
            id="cl-1", client_number="C-1", first_name="Hans", last_name="Muster",
            advisor_id="advisor-a", tenant_id="firm-a", household_type="Einzelperson",
            client_classification="Privatkunde", country_of_residence="CH", language="DE",
            created_at=now, updated_at=now,
        ))
        s.add(Mandate(
            id="man-1", client_id="cl-1", mandate_number="M-1", mandate_type="Anlageberatung",
            opened_at=now, created_at=now, updated_at=now,
        ))
        s.add(OptimizerPolicy(
            id="policy-1", policy_name="Policy-1",
            version=1, is_current=0, valid_from=now,
            optimizer_engine="goal_based_v1",
            max_real_estate_bps=2000, max_alternatives_bps=1000,
            min_liquidity_bps=0, created_by="advisor-a",
            created_at=now, updated_at=now,
        ))
        s.add(RecommendationRun(
            id="run-1", mandate_id="man-1", client_id="cl-1", policy_id="policy-1",
            run_type="Optimizer", result_status="Draft",
            created_by="advisor-a", created_at=now, updated_at=now,
        ))
        s.commit()

    user = User(id="advisor-a", username="advisor-a", password_hash="h", full_name="Advisor A",
                role="advisor", is_active=1, tenant_id="firm-a")
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        resp = client.post(
            "/mandates/man-1/recommendations/run-1/positions",
            json={"product_id": "prod-firm-b-private", "target_weight_bps": 1000},
        )
        assert resp.status_code == 404, resp.text
    finally:
        _logout()
