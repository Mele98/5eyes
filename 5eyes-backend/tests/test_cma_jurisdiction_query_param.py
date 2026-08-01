"""WP3 (Backend-Router fuer Jurisdiktions-Verwaltung + CMA-Freigabe, 2026-07-31):
Tests fuer den additiven jurisdiction/tenant_id Query-Parameter auf
GET/PUT /capital-market-assumptions[/current] (routers/allocation.py).

Verifiziert:
  - Ohne Query-Parameter (Default "CH") bleibt das Verhalten fuer Bestands-
    CH-Zeilen (jurisdiction IS NULL) UNVERAENDERT -- inkl. 404-Message.
  - jurisdiction=DE liest/versioniert eine separate DE-Zeile, ohne die
    CH-Zeile zu beruehren.
  - tenant_id-Override fuer Nicht-CH-Jurisdiktionen (Tenant-Zeile hat
    Vorrang vor der firmenweiten Zeile, analog resolve_cma_for_jurisdiction).
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

from database import Base, get_db
from main import app
from models.allocation import CapitalMarketAssumption
from models.tenant import Tenant
from models.users import User
from services.auth import get_current_user


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'cma_jurisdiction_query.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _make_cma(row_id, *, jurisdiction=None, tenant_id=None, status="committee_approved",
              is_current=1, equity_ch_return_bps=None):
    now = _now()
    return CapitalMarketAssumption(
        id=row_id, assumption_set_name=f"Standard-{row_id}", version=1,
        valid_from="2026-01-01", is_current=is_current, jurisdiction=jurisdiction,
        tenant_id=tenant_id, status=status, equity_ch_return_bps=equity_ch_return_bps,
        created_by="tester", created_at=now, updated_at=now,
    )


def _seed_users(SF):
    now = _now()
    with SF() as s:
        s.add(Tenant(
            id="main", display_name="main", slug="main",
            hosting_tier="tier1", license_status="active",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(User(
            id="admin-a", username="admin-a", password_hash="h", full_name="Admin A",
            role="admin", is_active=1, tenant_id="main", created_at=now, updated_at=now,
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


def _login_admin():
    user = User(id="admin-a", username="admin-a", password_hash="h", full_name="Admin A",
                role="admin", is_active=1, tenant_id="main")
    app.dependency_overrides[get_current_user] = lambda: user


def _logout():
    app.dependency_overrides.pop(get_current_user, None)


def test_get_current_cma_default_ch_unchanged_404_message(client, session_factory):
    _seed_users(session_factory)
    _login_admin()
    try:
        resp = client.get("/capital-market-assumptions/current")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Keine Kapitalmarktannahmen gefunden"
    finally:
        _logout()


def test_get_current_cma_default_ch_returns_ch_row(client, session_factory):
    with session_factory() as s:
        s.add(_make_cma("cma-ch-1", jurisdiction=None, equity_ch_return_bps=650))
        s.commit()
    _seed_users(session_factory)
    _login_admin()
    try:
        resp = client.get("/capital-market-assumptions/current")
        assert resp.status_code == 200
        assert resp.json()["id"] == "cma-ch-1"
        assert resp.json()["equity_ch_return_bps"] == 650

        # Explizites jurisdiction=CH ist aequivalent zum Default.
        explicit = client.get("/capital-market-assumptions/current", params={"jurisdiction": "CH"})
        assert explicit.status_code == 200
        assert explicit.json()["id"] == "cma-ch-1"
    finally:
        _logout()


def test_get_current_cma_de_returns_de_row_not_ch(client, session_factory):
    with session_factory() as s:
        s.add(_make_cma("cma-ch-1", jurisdiction=None, equity_ch_return_bps=650))
        s.add(_make_cma("cma-de-1", jurisdiction="DE", tenant_id=None))
        s.commit()
    _seed_users(session_factory)
    _login_admin()
    try:
        resp = client.get("/capital-market-assumptions/current", params={"jurisdiction": "DE"})
        assert resp.status_code == 200
        assert resp.json()["id"] == "cma-de-1"
        assert resp.json()["jurisdiction"] == "DE"
    finally:
        _logout()


def test_get_current_cma_de_tenant_override_takes_precedence(client, session_factory):
    with session_factory() as s:
        s.add(_make_cma("cma-de-firmwide", jurisdiction="DE", tenant_id=None))
        s.add(_make_cma("cma-de-tenant", jurisdiction="DE", tenant_id="firm-a"))
        s.commit()
    _seed_users(session_factory)
    _login_admin()
    try:
        resp = client.get("/capital-market-assumptions/current", params={
            "jurisdiction": "DE", "tenant_id": "firm-a",
        })
        assert resp.status_code == 200
        assert resp.json()["id"] == "cma-de-tenant"
    finally:
        _logout()


def test_get_current_cma_unknown_jurisdiction_404(client, session_factory):
    _seed_users(session_factory)
    _login_admin()
    try:
        resp = client.get("/capital-market-assumptions/current", params={"jurisdiction": "FR"})
        assert resp.status_code == 404
    finally:
        _logout()


def test_update_cma_default_ch_unchanged_behavior(client, session_factory):
    """CH-Pfad (kein jurisdiction-Query-Param): Versionierung bleibt exakt
    wie vor WP3 -- Vorgaenger wird superseded, version+1, kein jurisdiction/
    tenant_id auf der neuen Zeile gesetzt."""
    with session_factory() as s:
        s.add(_make_cma("cma-ch-old", jurisdiction=None, equity_ch_return_bps=600))
        s.commit()
    _seed_users(session_factory)
    _login_admin()
    try:
        resp = client.put("/capital-market-assumptions", json={
            "valid_from": "2026-08-01", "equity_ch_return_bps": 700,
        })
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["version"] == 2
        assert body["equity_ch_return_bps"] == 700
        assert body["jurisdiction"] is None
    finally:
        _logout()

    with session_factory() as s:
        old = s.query(CapitalMarketAssumption).filter(CapitalMarketAssumption.id == "cma-ch-old").first()
        assert old.is_current == 0


def test_update_cma_de_creates_separate_versioned_row_without_touching_ch(client, session_factory):
    with session_factory() as s:
        s.add(_make_cma("cma-ch-1", jurisdiction=None, equity_ch_return_bps=650))
        s.add(_make_cma("cma-de-old", jurisdiction="DE", tenant_id=None, status="data_derived"))
        s.commit()
    _seed_users(session_factory)
    _login_admin()
    try:
        resp = client.put(
            "/capital-market-assumptions",
            params={"jurisdiction": "DE"},
            json={"valid_from": "2026-08-01", "bonds_chf_ig_return_bps": 200, "notes": "DE-Update"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["jurisdiction"] == "DE"
        assert body["version"] == 2
    finally:
        _logout()

    with session_factory() as s:
        de_old = s.query(CapitalMarketAssumption).filter(CapitalMarketAssumption.id == "cma-de-old").first()
        assert de_old.is_current == 0

        ch_row = s.query(CapitalMarketAssumption).filter(CapitalMarketAssumption.id == "cma-ch-1").first()
        assert ch_row.is_current == 1  # CH bleibt komplett unberuehrt


def test_update_cma_de_first_version_has_no_previous_row(client, session_factory):
    _seed_users(session_factory)
    _login_admin()
    try:
        resp = client.put(
            "/capital-market-assumptions",
            params={"jurisdiction": "DE", "tenant_id": "firm-a"},
            json={"valid_from": "2026-08-01", "bonds_chf_ig_return_bps": 180},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["version"] == 1
        assert body["jurisdiction"] == "DE"
        assert body["tenant_id"] == "firm-a"
        assert body["is_current"] == 1
    finally:
        _logout()
