"""WP3 (Backend-Router fuer Jurisdiktions-Verwaltung + CMA-Freigabe, 2026-07-31):
Tests fuer routers/jurisdiction.py (JurisdictionProfile/HomeBiasDefault-CRUD
+ CMA-Kandidaten-Berechnung).

Verifiziert:
  - CH-Lock: PUT/POST/PUT/DELETE mit code="CH" -> 403, GET bleibt erlaubt.
  - Home-Bias-Default-CRUD fuer DE (admin darf, advisor -> 403).
  - compute-candidate-Endpoint: mockt die Marktdaten-Pipeline (kein Netzwerk-
    Call), verifiziert 200 (data_derived) sowie 400 bei Pipeline-Fehlern
    (KEIN 500, KEINE erfundene Zahl) und 403 fuer code="CH".
  - Rollen-Gate: advisor bekommt 403 auf mutierenden Endpoints,
    portfolio_management/admin bekommen 200 auf compute-candidate.
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
import routers.jurisdiction as jurisdiction_router_module
from models.jurisdiction import JurisdictionHomeBiasDefault, JurisdictionProfile
from models.tenant import Tenant
from models.users import User
from services.auth import get_current_user
from services.jurisdiction.data_pipeline import (
    InsufficientYieldCurveDataError,
    NoYieldCurveSourceConfiguredError,
)
from services.jurisdiction.de_seed import ensure_de_jurisdiction_seed


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'jurisdiction_router.db'}",
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
        s.add(Tenant(
            id="main", display_name="main", slug="main",
            hosting_tier="tier1", license_status="active",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(JurisdictionProfile(
            id="jp-ch", code="CH", display_name="Schweiz", home_currency="CHF",
            is_active=1, is_provisional=0, status="approved",
            created_at=now, updated_at=now,
        ))
        ensure_de_jurisdiction_seed(s)
        s.add(User(
            id="admin-a", username="admin-a", password_hash="h", full_name="Admin A",
            role="admin", is_active=1, tenant_id="main", created_at=now, updated_at=now,
        ))
        s.add(User(
            id="advisor-a", username="advisor-a", password_hash="h", full_name="Advisor A",
            role="advisor", is_active=1, tenant_id="main", created_at=now, updated_at=now,
        ))
        s.add(User(
            id="pm-a", username="pm-a", password_hash="h", full_name="PM A",
            role="portfolio_management", is_active=1, tenant_id="main", created_at=now, updated_at=now,
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


def _login_as(user_id, role):
    user = User(id=user_id, username=user_id, password_hash="h", full_name=user_id,
                role=role, is_active=1, tenant_id="main")
    app.dependency_overrides[get_current_user] = lambda: user


def _logout():
    app.dependency_overrides.pop(get_current_user, None)


# ---------------------------------------------------------------------------
# JurisdictionProfile: list/get/update + CH-Lock
# ---------------------------------------------------------------------------


def test_advisor_can_list_and_get_jurisdictions(client, session_factory):
    _seed(session_factory)
    _login_as("advisor-a", "advisor")
    try:
        listed = client.get("/jurisdictions")
        assert listed.status_code == 200
        codes = {row["code"] for row in listed.json()}
        assert codes == {"CH", "DE"}

        got = client.get("/jurisdictions/DE")
        assert got.status_code == 200
        assert got.json()["display_name"] == "Deutschland"
        assert got.json()["is_provisional"] == 1
    finally:
        _logout()


def test_get_unknown_jurisdiction_404(client, session_factory):
    _seed(session_factory)
    _login_as("advisor-a", "advisor")
    try:
        resp = client.get("/jurisdictions/XX")
        assert resp.status_code == 404
    finally:
        _logout()


def test_admin_can_update_de_jurisdiction(client, session_factory):
    _seed(session_factory)
    _login_as("admin-a", "admin")
    try:
        resp = client.put("/jurisdictions/DE", json={
            "status": "approved", "notes": "IC-Freigabe erteilt",
        })
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "approved"
        assert resp.json()["notes"] == "IC-Freigabe erteilt"
    finally:
        _logout()


def test_advisor_forbidden_from_updating_jurisdiction(client, session_factory):
    _seed(session_factory)
    _login_as("advisor-a", "advisor")
    try:
        resp = client.put("/jurisdictions/DE", json={"status": "approved"})
        assert resp.status_code == 403
    finally:
        _logout()


def test_ch_jurisdiction_is_locked_against_update(client, session_factory):
    _seed(session_factory)
    _login_as("admin-a", "admin")
    try:
        resp = client.put("/jurisdictions/CH", json={"display_name": "Helvetia"})
        assert resp.status_code == 403
        assert "gesperrt" in resp.json()["detail"]

        # Bestandszeile unveraendert.
        unchanged = client.get("/jurisdictions/CH")
        assert unchanged.json()["display_name"] == "Schweiz"
    finally:
        _logout()


def test_update_invalid_status_rejected(client, session_factory):
    _seed(session_factory)
    _login_as("admin-a", "admin")
    try:
        resp = client.put("/jurisdictions/DE", json={"status": "not-a-real-status"})
        assert resp.status_code == 422
    finally:
        _logout()


# ---------------------------------------------------------------------------
# Home-Bias-Defaults: CRUD fuer DE + CH-Lock
# ---------------------------------------------------------------------------


def test_advisor_can_list_home_bias_defaults(client, session_factory):
    _seed(session_factory)
    _login_as("advisor-a", "advisor")
    try:
        resp = client.get("/jurisdictions/DE/home-bias-defaults")
        assert resp.status_code == 200
        assert len(resp.json()) > 0

        filtered = client.get(
            "/jurisdictions/DE/home-bias-defaults",
            params={"preference_key": "equitiesGeo"},
        )
        assert filtered.status_code == 200
        assert all(row["preference_key"] == "equitiesGeo" for row in filtered.json())
    finally:
        _logout()


def test_admin_can_create_update_delete_home_bias_default(client, session_factory):
    _seed(session_factory)
    _login_as("admin-a", "admin")
    try:
        created = client.post("/jurisdictions/DE/home-bias-defaults", json={
            "preference_key": "equitiesGeo",
            "preference_value": "Testvariante",
            "sub_asset_class": "Aktien Test",
            "split_bps": 10000,
            "rationale_text": "Testzeile",
        })
        assert created.status_code == 201, created.text
        row_id = created.json()["id"]
        assert created.json()["is_provisional"] == 1

        updated = client.put(f"/jurisdictions/DE/home-bias-defaults/{row_id}", json={
            "split_bps": 9000,
        })
        assert updated.status_code == 200
        assert updated.json()["split_bps"] == 9000

        deleted = client.delete(f"/jurisdictions/DE/home-bias-defaults/{row_id}")
        assert deleted.status_code == 204

        listed = client.get(
            "/jurisdictions/DE/home-bias-defaults",
            params={"preference_key": "equitiesGeo"},
        )
        assert row_id not in {row["id"] for row in listed.json()}
    finally:
        _logout()


def test_advisor_forbidden_from_mutating_home_bias_defaults(client, session_factory):
    _seed(session_factory)
    _login_as("advisor-a", "advisor")
    try:
        resp = client.post("/jurisdictions/DE/home-bias-defaults", json={
            "preference_key": "equitiesGeo",
            "preference_value": "Testvariante",
            "sub_asset_class": "Aktien Test",
            "split_bps": 10000,
        })
        assert resp.status_code == 403
    finally:
        _logout()


def test_ch_home_bias_defaults_are_locked(client, session_factory):
    _seed(session_factory)
    _login_as("admin-a", "admin")
    try:
        create_resp = client.post("/jurisdictions/CH/home-bias-defaults", json={
            "preference_key": "equitiesGeo",
            "preference_value": "Schweiz Fokus",
            "sub_asset_class": "Aktien Schweiz",
            "split_bps": 10000,
        })
        assert create_resp.status_code == 403

        update_resp = client.put("/jurisdictions/CH/home-bias-defaults/does-not-exist", json={
            "split_bps": 1,
        })
        assert update_resp.status_code == 403

        delete_resp = client.delete("/jurisdictions/CH/home-bias-defaults/does-not-exist")
        assert delete_resp.status_code == 403
    finally:
        _logout()


def test_update_home_bias_default_wrong_jurisdiction_code_404(client, session_factory):
    """Eine DE-Zeile darf nicht ueber einen anderen Jurisdiktions-Pfad
    erreichbar sein (Isolation analog zu ProductUniverseEntry-Tenant-Checks)."""
    _seed(session_factory)
    _login_as("admin-a", "admin")
    try:
        created = client.post("/jurisdictions/DE/home-bias-defaults", json={
            "preference_key": "equitiesGeo",
            "preference_value": "Isoliert",
            "sub_asset_class": "Aktien Isoliert",
            "split_bps": 10000,
        })
        row_id = created.json()["id"]

        # Es existiert keine Jurisdiktion "FR" -- Pfad-Mismatch -> 404.
        wrong_path = client.put(f"/jurisdictions/FR/home-bias-defaults/{row_id}", json={
            "split_bps": 1,
        })
        assert wrong_path.status_code == 404
    finally:
        _logout()


# ---------------------------------------------------------------------------
# compute-candidate: mockt die Marktdaten-Pipeline (kein Netzwerk-Call)
# ---------------------------------------------------------------------------


def test_compute_candidate_ch_forbidden(client, session_factory):
    _seed(session_factory)
    _login_as("pm-a", "portfolio_management")
    try:
        resp = client.post("/jurisdictions/CH/cma/compute-candidate")
        assert resp.status_code == 403
    finally:
        _logout()


def test_compute_candidate_advisor_forbidden(client, session_factory):
    _seed(session_factory)
    _login_as("advisor-a", "advisor")
    try:
        resp = client.post("/jurisdictions/DE/cma/compute-candidate")
        assert resp.status_code == 403
    finally:
        _logout()


def test_compute_candidate_success_portfolio_management(client, session_factory, monkeypatch):
    from models.allocation import CapitalMarketAssumption

    def _fake_compute(db, jurisdiction, as_of_date):
        now = _now()
        cma = CapitalMarketAssumption(
            id="cma-de-fake-1", assumption_set_name="DE-fake", version=1,
            valid_from=as_of_date, is_current=0, jurisdiction=jurisdiction,
            status="data_derived", bonds_home_ig_return_bps=250,
            created_by="system:cma_data_pipeline", created_at=now, updated_at=now,
        )
        db.add(cma)
        db.flush()
        return cma

    monkeypatch.setattr(jurisdiction_router_module, "compute_cma_candidate_for_jurisdiction", _fake_compute)

    _seed(session_factory)
    _login_as("pm-a", "portfolio_management")
    try:
        resp = client.post("/jurisdictions/DE/cma/compute-candidate")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["jurisdiction"] == "DE"
        assert body["status"] == "data_derived"
        assert body["is_current"] == 0
    finally:
        _logout()


def test_compute_candidate_admin_also_allowed(client, session_factory, monkeypatch):
    from models.allocation import CapitalMarketAssumption

    def _fake_compute(db, jurisdiction, as_of_date):
        now = _now()
        cma = CapitalMarketAssumption(
            id="cma-de-fake-2", assumption_set_name="DE-fake-2", version=1,
            valid_from=as_of_date, is_current=0, jurisdiction=jurisdiction,
            status="data_derived", bonds_home_ig_return_bps=250,
            created_by="system:cma_data_pipeline", created_at=now, updated_at=now,
        )
        db.add(cma)
        db.flush()
        return cma

    monkeypatch.setattr(jurisdiction_router_module, "compute_cma_candidate_for_jurisdiction", _fake_compute)

    _seed(session_factory)
    _login_as("admin-a", "admin")
    try:
        resp = client.post("/jurisdictions/DE/cma/compute-candidate")
        assert resp.status_code == 200, resp.text
    finally:
        _logout()


def test_compute_candidate_no_yield_curve_source_returns_400_not_500(client, session_factory, monkeypatch):
    def _boom(db, jurisdiction, as_of_date):
        raise NoYieldCurveSourceConfiguredError(f"Keine Zinskurven-Quelle fuer {jurisdiction}")

    monkeypatch.setattr(jurisdiction_router_module, "compute_cma_candidate_for_jurisdiction", _boom)

    _seed(session_factory)
    _login_as("pm-a", "portfolio_management")
    try:
        resp = client.post("/jurisdictions/DE/cma/compute-candidate")
        assert resp.status_code == 400
        assert "Keine Zinskurven-Quelle" in resp.json()["detail"]
    finally:
        _logout()


def test_compute_candidate_insufficient_yield_curve_data_returns_400(client, session_factory, monkeypatch):
    def _boom(db, jurisdiction, as_of_date):
        raise InsufficientYieldCurveDataError("Nur 1 von 5 Punkten erhalten")

    monkeypatch.setattr(jurisdiction_router_module, "compute_cma_candidate_for_jurisdiction", _boom)

    _seed(session_factory)
    _login_as("pm-a", "portfolio_management")
    try:
        resp = client.post("/jurisdictions/DE/cma/compute-candidate")
        assert resp.status_code == 400
        assert "Nur 1 von 5 Punkten" in resp.json()["detail"]
    finally:
        _logout()
