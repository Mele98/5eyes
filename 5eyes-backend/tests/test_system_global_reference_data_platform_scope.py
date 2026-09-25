"""Kontrollrunde 2026-09-24: sechs Admin-Ops-Endpoints in routers/system.py
schreiben/aendern GLOBALE, nicht-tenant-gebundene Referenzdaten (Annual-
Returns, Asset-Class-Prices, Market-Data-Refresh, Provider-Health,
Optimizer-Mode) -- sie hingen bisher an plain require_admin, wie
POST /admin/system/fx-rates/refresh-now vor dem AUTH-TEN-06-Fix (siehe
tests/test_authten06_fx_platform_scope.py). Ein firmengebundener 'admin'
konnte damit in einer echten Multi-Tenant-Installation Daten aendern, die
ALLE Tenants betreffen.

Fix: dieselbe require_admin_or_platform_scope_for_global_reference_data-
Gate wie bereits fuer die FX-Endpoints. Diese Tests verifizieren nur die
Blocking-Seite (kein Mocking der jeweiligen Backing-Services noetig, da
die Dependency VOR dem Endpoint-Body ausgewertet wird) plus je einen
Zero-Regression-Nachweis, dass admin auf Tier-1-Default weiterhin erlaubt
bleibt.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, get_db
from main import app
from services.auth import get_current_user


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'system_refdata_scope.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _user(role: str):
    return SimpleNamespace(
        id=f"{role}-refdata-scope", full_name=f"{role} RefdataScope",
        email=f"{role}@test.local", role=role,
    )


@pytest.fixture()
def client(session_factory):
    def override_db():
        with session_factory() as s:
            yield s
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _login_as(role: str):
    app.dependency_overrides[get_current_user] = lambda: _user(role)


# (method, path, json_body) for each of the six endpoints.
_ENDPOINTS = [
    ("put", "/admin/system/optimizer-mode", {"optimizer_mode": "stochastic"}),
    ("post", "/admin/system/annual-returns/backfill", None),
    ("put", "/admin/system/annual-returns/2030/Aktien", {"return_bps": 500}),
    ("post", "/admin/system/asset-class-prices/backfill", None),
    ("post", "/admin/system/market-data/refresh-now", None),
    ("post", "/admin/system/market-data/provider-health/reset", None),
]


@pytest.mark.parametrize("method, path, body", _ENDPOINTS)
def test_admin_blocked_when_strict_tenant_isolation(client, monkeypatch, method, path, body):
    from config import settings
    monkeypatch.setattr(settings, "strict_tenant_isolation", True)
    _login_as("admin")
    resp = getattr(client, method)(path, json=body)
    assert resp.status_code == 403, resp.text


@pytest.mark.parametrize("method, path, body", _ENDPOINTS)
def test_advisor_blocked_when_strict_tenant_isolation(client, monkeypatch, method, path, body):
    from config import settings
    monkeypatch.setattr(settings, "strict_tenant_isolation", True)
    _login_as("advisor")
    resp = getattr(client, method)(path, json=body)
    assert resp.status_code == 403, resp.text


def test_admin_still_allowed_optimizer_mode_on_tier1_default(client):
    """Zero-Regression: das billigste der sechs Endpoints (keine externen
    Service-Aufrufe) beweist, dass Tier-1-Default (kein strict_tenant_
    isolation) admin weiterhin durchlaesst."""
    _login_as("admin")
    resp = client.put("/admin/system/optimizer-mode", json={"optimizer_mode": "stochastic"})
    assert resp.status_code == 200, resp.text


def test_super_admin_still_allowed_market_data_refresh_when_strict(client, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "strict_tenant_isolation", True)
    import services.market_data_daily_refresh as mdr
    monkeypatch.setattr(
        mdr, "run_daily_market_data_refresh",
        lambda db: {"status": "ok", "run_id": "test-run"},
    )
    _login_as("super_admin")
    resp = client.post("/admin/system/market-data/refresh-now")
    assert resp.status_code == 200, resp.text
