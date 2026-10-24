"""AUTH-TEN-06 (Codex-Audit 2026-08-25): FX-Kurse (models/fx_rate.py,
asset_class_fx_history) sind GLOBAL -- sie wirken auf ALLE Tenants, nicht
nur den des aendernden Users. require_advisor (PUT /fx-rates) bzw.
require_admin (POST /admin/system/fx-rates/refresh-now) liessen bisher
JEDEN Berater bzw. jeden firmengebundenen Admin diese globalen Kurse
aendern -- in einer echten Multi-Tenant-Installation eine Firma-A-User-
aendert-globale-Daten-Luecke.

Verifiziert:
  - strict_tenant_isolation=True: advisor/admin -> 403 auf beiden Endpoints.
  - strict_tenant_isolation=True: super_admin/portfolio_management -> 200.
  - Tier-1 Default (kein strict_tenant_isolation): advisor/admin bleiben
    wie bisher erlaubt (Zero-Regression fuer die echte Produktivinstanz).
"""
from __future__ import annotations

import datetime
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


def _now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'authten06_fx.db'}",
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
        id=f"{role}-authten06", full_name=f"{role} AUTHTEN06", email=f"{role}@test.local", role=role,
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


_PUT_PAYLOAD = {"rates": [{"currency": "EUR", "rate": 0.95}]}


# ---------------------------------------------------------------------------
# PUT /fx-rates
# ---------------------------------------------------------------------------

def test_advisor_blocked_from_upsert_fx_rates_when_strict_tenant_isolation(client, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "strict_tenant_isolation", True)
    _login_as("advisor")
    resp = client.put("/fx-rates", json=_PUT_PAYLOAD)
    assert resp.status_code == 403, resp.text


def test_admin_blocked_from_upsert_fx_rates_when_strict_tenant_isolation(client, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "strict_tenant_isolation", True)
    _login_as("admin")
    resp = client.put("/fx-rates", json=_PUT_PAYLOAD)
    assert resp.status_code == 403, resp.text


def test_super_admin_still_allowed_to_upsert_fx_rates_when_strict_tenant_isolation(client, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "strict_tenant_isolation", True)
    _login_as("super_admin")
    resp = client.put("/fx-rates", json=_PUT_PAYLOAD)
    assert resp.status_code == 200, resp.text


def test_portfolio_management_still_allowed_to_upsert_fx_rates_when_strict_tenant_isolation(client, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "strict_tenant_isolation", True)
    _login_as("portfolio_management")
    resp = client.put("/fx-rates", json=_PUT_PAYLOAD)
    assert resp.status_code == 200, resp.text


def test_advisor_still_allowed_to_upsert_fx_rates_on_tier1_default(client):
    """Zero-Regression: Tier-1 (kein strict_tenant_isolation) -- FX-Pflege
    bleibt Berater-Aufgabe, wie im Modul-Docstring von routers/fx_rates.py
    dokumentiert."""
    _login_as("advisor")
    resp = client.put("/fx-rates", json=_PUT_PAYLOAD)
    assert resp.status_code == 200, resp.text


def test_admin_still_allowed_to_upsert_fx_rates_on_tier1_default(client):
    _login_as("admin")
    resp = client.put("/fx-rates", json=_PUT_PAYLOAD)
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# POST /admin/system/fx-rates/refresh-now
# ---------------------------------------------------------------------------

def _patch_refresh(monkeypatch):
    import services.fx_rate_daily_refresh as fxr
    monkeypatch.setattr(
        fxr, "run_daily_fx_refresh",
        lambda db: {
            "status": "ok", "scope": "fx_only",
            "started_at": "2026-08-25T10:00:00.000Z",
            "finished_at": "2026-08-25T10:00:01.000Z",
            "duration_seconds": 1.0, "fx_added": 3, "errors": [],
        },
    )


def test_advisor_blocked_from_refresh_now_when_strict_tenant_isolation(client, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "strict_tenant_isolation", True)
    _patch_refresh(monkeypatch)
    _login_as("advisor")
    resp = client.post("/admin/system/fx-rates/refresh-now")
    assert resp.status_code == 403, resp.text


def test_admin_blocked_from_refresh_now_when_strict_tenant_isolation(client, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "strict_tenant_isolation", True)
    _patch_refresh(monkeypatch)
    _login_as("admin")
    resp = client.post("/admin/system/fx-rates/refresh-now")
    assert resp.status_code == 403, resp.text


def test_super_admin_still_allowed_to_refresh_now_when_strict_tenant_isolation(client, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "strict_tenant_isolation", True)
    _patch_refresh(monkeypatch)
    _login_as("super_admin")
    resp = client.post("/admin/system/fx-rates/refresh-now")
    assert resp.status_code == 200, resp.text


def test_portfolio_management_still_allowed_to_refresh_now_when_strict_tenant_isolation(client, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "strict_tenant_isolation", True)
    _patch_refresh(monkeypatch)
    _login_as("portfolio_management")
    resp = client.post("/admin/system/fx-rates/refresh-now")
    assert resp.status_code == 200, resp.text


def test_admin_still_allowed_to_refresh_now_on_tier1_default(client, monkeypatch):
    """Zero-Regression: Tier-1 (kein strict_tenant_isolation) -- Endpoint
    blieb bisher require_admin, bleibt fuer admin weiterhin erlaubt."""
    _patch_refresh(monkeypatch)
    _login_as("admin")
    resp = client.post("/admin/system/fx-rates/refresh-now")
    assert resp.status_code == 200, resp.text


def test_advisor_still_blocked_from_refresh_now_on_tier1_default(client, monkeypatch):
    """Zero-Regression: anders als PUT /fx-rates (vorher require_advisor)
    war dieser Ops-Endpoint schon immer require_admin -- advisor war auf
    Tier-1 nie erlaubt und bleibt es auch mit dem neuen Dependency nicht
    (require_admin_or_platform_scope_for_global_reference_data haelt die
    urspruengliche admin/super_admin-Basis exakt bei, keine Erweiterung)."""
    _patch_refresh(monkeypatch)
    _login_as("advisor")
    resp = client.post("/admin/system/fx-rates/refresh-now")
    assert resp.status_code == 403, resp.text
