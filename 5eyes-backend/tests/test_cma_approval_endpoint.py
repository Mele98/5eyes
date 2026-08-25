"""WP3 (Backend-Router fuer Jurisdiktions-Verwaltung + CMA-Freigabe, 2026-07-31):
Tests fuer POST /capital-market-assumptions/{id}/approve (routers/jurisdiction.py).

Verifiziert:
  - 404 fuer unbekannte id.
  - Status-Uebergang "data_derived" -> "committee_approved" fuer eine
    Nicht-CH-Zeile, inkl. is_current-Promotion (die zuvor aktuelle Zeile
    DERSELBEN Jurisdiktion+Tenant-Scope wird superseded).
  - Audit-Log-Eintrag (action="APPROVE", table_name="capital_market_assumptions").
  - Rollen-Gate: advisor -> 403, portfolio_management/admin -> 200.
  - CH-Zeile (bereits committee_approved+is_current) -> No-Op-Erfolg, kein
    Fehler, keine ungewollte Nebenwirkung.
  - Andere Jurisdiktion/Tenant-Scope bleibt von der Promotion unberuehrt.
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
from models.review import AuditLog
from models.tenant import Tenant
from models.users import User
from services.auth import get_current_user


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'cma_approval.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _make_cma(row_id, *, jurisdiction=None, tenant_id=None, status="committee_approved", is_current=0):
    now = _now()
    return CapitalMarketAssumption(
        id=row_id, assumption_set_name=f"Standard-{row_id}", version=1,
        valid_from="2026-01-01", is_current=is_current, jurisdiction=jurisdiction,
        tenant_id=tenant_id, status=status,
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


def test_approve_unknown_id_404(client, session_factory):
    _seed_users(session_factory)
    _login_as("pm-a", "portfolio_management")
    try:
        resp = client.post("/capital-market-assumptions/does-not-exist/approve")
        assert resp.status_code == 404
    finally:
        _logout()


def test_advisor_forbidden(client, session_factory):
    _seed_users(session_factory)
    with session_factory() as s:
        s.add(_make_cma("cma-de-1", jurisdiction="DE", status="data_derived", is_current=0))
        s.commit()
    _login_as("advisor-a", "advisor")
    try:
        resp = client.post("/capital-market-assumptions/cma-de-1/approve")
        assert resp.status_code == 403
    finally:
        _logout()


def test_approve_de_candidate_promotes_to_current_and_supersedes_previous(client, session_factory):
    with session_factory() as s:
        s.add(_make_cma("cma-de-old", jurisdiction="DE", tenant_id=None,
                         status="committee_approved", is_current=1))
        s.add(_make_cma("cma-de-candidate", jurisdiction="DE", tenant_id=None,
                         status="data_derived", is_current=0))
        s.commit()
    _seed_users(session_factory)

    _login_as("pm-a", "portfolio_management")
    try:
        resp = client.post("/capital-market-assumptions/cma-de-candidate/approve")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "committee_approved"
        assert body["is_current"] == 1
    finally:
        _logout()

    with session_factory() as s:
        old = s.query(CapitalMarketAssumption).filter(CapitalMarketAssumption.id == "cma-de-old").first()
        assert old.is_current == 0

        new = s.query(CapitalMarketAssumption).filter(CapitalMarketAssumption.id == "cma-de-candidate").first()
        assert new.is_current == 1
        assert new.status == "committee_approved"

        audit = s.query(AuditLog).filter(
            AuditLog.table_name == "capital_market_assumptions",
            AuditLog.record_id == "cma-de-candidate",
            AuditLog.action == "APPROVE",
        ).all()
        assert len(audit) == 1
        assert audit[0].user_id == "pm-a"


def test_admin_can_also_approve(client, session_factory):
    with session_factory() as s:
        s.add(_make_cma("cma-de-2", jurisdiction="DE", status="data_derived", is_current=0))
        s.commit()
    _seed_users(session_factory)

    _login_as("admin-a", "admin")
    try:
        resp = client.post("/capital-market-assumptions/cma-de-2/approve")
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "committee_approved"
    finally:
        _logout()


def test_approve_ch_row_is_noop_success(client, session_factory):
    """CH-Zeilen sind bereits committee_approved+is_current -- ein Aufruf
    darauf ist ein No-Op-Erfolg, kein Fehler (harte Vorgabe der
    Aufgabenstellung)."""
    with session_factory() as s:
        s.add(_make_cma("cma-ch-1", jurisdiction=None, tenant_id=None,
                         status="committee_approved", is_current=1))
        s.commit()
    _seed_users(session_factory)

    _login_as("pm-a", "portfolio_management")
    try:
        resp = client.post("/capital-market-assumptions/cma-ch-1/approve")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "committee_approved"
        assert body["is_current"] == 1
    finally:
        _logout()

    with session_factory() as s:
        ch_row = s.query(CapitalMarketAssumption).filter(CapitalMarketAssumption.id == "cma-ch-1").first()
        assert ch_row.is_current == 1
        assert ch_row.status == "committee_approved"


def test_approve_does_not_affect_other_tenant_scope(client, session_factory):
    """Ein DE-Kandidat fuer Tenant 'firm-a' darf die firmenweite DE-Zeile
    (tenant_id IS NULL) nicht superseden -- unterschiedlicher Scope."""
    with session_factory() as s:
        s.add(_make_cma("cma-de-firmwide", jurisdiction="DE", tenant_id=None,
                         status="committee_approved", is_current=1))
        s.add(_make_cma("cma-de-tenant-candidate", jurisdiction="DE", tenant_id="firm-a",
                         status="data_derived", is_current=0))
        s.commit()
    _seed_users(session_factory)

    _login_as("pm-a", "portfolio_management")
    try:
        resp = client.post("/capital-market-assumptions/cma-de-tenant-candidate/approve")
        assert resp.status_code == 200, resp.text
    finally:
        _logout()

    with session_factory() as s:
        firmwide = s.query(CapitalMarketAssumption).filter(CapitalMarketAssumption.id == "cma-de-firmwide").first()
        assert firmwide.is_current == 1  # unberuehrt, anderer Tenant-Scope

        tenant_row = s.query(CapitalMarketAssumption).filter(
            CapitalMarketAssumption.id == "cma-de-tenant-candidate"
        ).first()
        assert tenant_row.is_current == 1
        assert tenant_row.status == "committee_approved"
