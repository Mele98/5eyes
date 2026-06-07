"""Sprint Bug-#1 (2026-06-08): Vermoegenswerte editieren.

User-Report: 'Vermoegenswerte koennen nach Erstellung nicht mehr bearbeitet
werden.'

Root-Cause-Befund: Frontend renderRowsSafe() renderte Edit-/Delete-Buttons
OHNE onClick-Handler. Backend-Endpoint PUT /clients/{cid}/wealth-positions/{wp_id}
funktionierte korrekt. Fix: Click-Handler nach innerHTML-Update binden
(saubere Event-Listener statt Inline-onClick).

# Tests
- Backend-Garantie: PUT-Endpoint persistiert Aenderungen
- Frontend-Source-Parse: renderWealthPositions hat Handler-Registration
- Edge-Cases: invalide Daten, fehlende Authorization
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
import models.allocation  # noqa: F401
import models.clients  # noqa: F401
import models.client_login  # noqa: F401
import models.fx_rate  # noqa: F401
import models.mandates  # noqa: F401
import models.profiling  # noqa: F401
import models.review  # noqa: F401
import models.snapshots  # noqa: F401
import models.tenant  # noqa: F401
import models.users  # noqa: F401
import models.wealth  # noqa: F401

from main import app
from models.users import User
from models.wealth import WealthPosition
from services.auth import get_current_user


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'bug1_wealth_edit.db'}",
        connect_args={"check_same_thread": False},
    )
    sf = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield sf
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def advisor_user():
    return User(
        id="advisor-bug1",
        username="advisor-bug1",
        password_hash="h",
        full_name="Test Advisor",
        role="advisor",
        is_active=1,
        created_at=_utc_now_iso(),
        updated_at=_utc_now_iso(),
    )


@pytest.fixture()
def auth_client(session_factory, advisor_user):
    def override_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: advisor_user
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def _setup_client_with_position(auth_client, advisor_user) -> tuple[str, str]:
    """Erstellt Client + Wealth-Position. Returnt (client_id, position_id)."""
    client_resp = auth_client.post(
        "/clients",
        json={
            "client_number": "BUG1-001",
            "first_name": "Bug",
            "last_name": "One",
            "advisor_id": advisor_user.id,
            "household_type": "Einzelperson",
        },
    )
    assert client_resp.status_code == 201, client_resp.text
    client_id = client_resp.json()["id"]
    pos_resp = auth_client.post(
        f"/clients/{client_id}/wealth-positions",
        json={
            "position_type": "Depot",
            "label": "Depot UBS Original",
            "assignment": "Beratungsvermögen",
            "current_value_rappen": 500_000_00,
            "depot_bank": "UBS",
            "depot_account_number": "12-345678-9",
            # Depot-Validator verlangt Summe = 10000 BP
            "alloc_equities_bps": 6000,
            "alloc_bonds_bps": 3000,
            "alloc_real_estate_bps": 0,
            "alloc_liquidity_bps": 1000,
            "alloc_alternatives_bps": 0,
        },
    )
    assert pos_resp.status_code == 201, pos_resp.text
    return client_id, pos_resp.json()["id"]


# ===========================================================================
# Backend-Garantie: PUT persistiert
# ===========================================================================


def test_put_wealth_position_persistiert_aenderung(
    auth_client, advisor_user, session_factory,
):
    """Backend-Update-Endpoint funktioniert korrekt."""
    client_id, pos_id = _setup_client_with_position(auth_client, advisor_user)
    resp = auth_client.put(
        f"/clients/{client_id}/wealth-positions/{pos_id}",
        json={
            "position_type": "Depot",
            "label": "Depot UBS AKTUALISIERT",
            "assignment": "Beratungsvermögen",
            "current_value_rappen": 600_000_00,
            "depot_bank": "UBS",
            "depot_account_number": "12-345678-9",
        },
    )
    assert resp.status_code == 200, resp.text
    with session_factory() as db:
        wp = db.query(WealthPosition).filter(WealthPosition.id == pos_id).first()
        assert wp.label == "Depot UBS AKTUALISIERT"
        assert wp.current_value_rappen == 600_000_00


def test_put_unbekannte_position_404(auth_client, advisor_user):
    """Wenn Position-ID nicht existiert → 404."""
    client_id, _ = _setup_client_with_position(auth_client, advisor_user)
    resp = auth_client.put(
        f"/clients/{client_id}/wealth-positions/does-not-exist",
        json={
            "position_type": "Depot",
            "label": "X",
            "assignment": "Beratungsvermögen",
            "current_value_rappen": 100_00,
        },
    )
    assert resp.status_code == 404


def test_put_andere_clients_position_404(
    auth_client, advisor_user, session_factory,
):
    """Position eines anderen Clients → 404 (Cross-Client-Leak verhindert)."""
    client_a, pos_a = _setup_client_with_position(auth_client, advisor_user)
    # Zweiter Client
    client_b_resp = auth_client.post(
        "/clients",
        json={
            "client_number": "BUG1-002",
            "first_name": "Other", "last_name": "Client",
            "advisor_id": advisor_user.id,
            "household_type": "Einzelperson",
        },
    )
    client_b = client_b_resp.json()["id"]
    # Versuche pos_a unter client_b zu updaten
    resp = auth_client.put(
        f"/clients/{client_b}/wealth-positions/{pos_a}",
        json={
            "position_type": "Depot",
            "label": "X",
            "assignment": "Beratungsvermögen",
            "current_value_rappen": 100_00,
        },
    )
    assert resp.status_code == 404


def test_put_audit_log_eintrag(
    auth_client, advisor_user, session_factory,
):
    """Update muss im Audit-Log erscheinen."""
    from models.review import AuditLog
    client_id, pos_id = _setup_client_with_position(auth_client, advisor_user)
    auth_client.put(
        f"/clients/{client_id}/wealth-positions/{pos_id}",
        json={
            "position_type": "Depot",
            "label": "Updated Label",
            "assignment": "Beratungsvermögen",
            "current_value_rappen": 700_000_00,
        },
    )
    with session_factory() as db:
        log_entries = (
            db.query(AuditLog)
            .filter(
                AuditLog.table_name == "wealth_positions",
                AuditLog.record_id == pos_id,
                AuditLog.action == "UPDATE",
            )
            .all()
        )
        assert len(log_entries) >= 1


# ===========================================================================
# Frontend-Source-Parse: Click-Handler werden registriert
# ===========================================================================


def test_frontend_renderwealthpositions_bindet_edit_button():
    """Sprint Bug-#1-Fix: renderWealthPositions registriert Edit-Click-Handler.

    Source-Parse-Drift-Test damit der Fix nicht regression-anfaellig ist.
    """
    html_path = (
        BACKEND_ROOT.parent / "5eyes-electron" / "frontend" / "5eyes_v2.html"
    )
    text = html_path.read_text(encoding="utf-8")
    # Marker fuer den Sprint-Bug-#1-Fix
    assert "Sprint Bug-#1 (2026-06-08)" in text, (
        "Bug-#1-Fix-Marker fehlt in 5eyes_v2.html — Fix wurde entfernt?"
    )
    # Konkrete Handler-Registration vorhanden
    assert "openWealthPositionEditor(posid)" in text, (
        "Edit-Click-Handler-Registration fehlt"
    )
    assert "deleteWealthPositionById(posid)" in text, (
        "Delete-Click-Handler-Registration fehlt"
    )


def test_frontend_renderwealthpositions_event_listener_pattern_korrekt():
    """Event-Listener-Pattern: querySelectorAll mit data-posid + btn-ico."""
    html_path = (
        BACKEND_ROOT.parent / "5eyes-electron" / "frontend" / "5eyes_v2.html"
    )
    text = html_path.read_text(encoding="utf-8")
    # Im Bug-#1-Fix-Block: querySelectorAll mit dem richtigen Selektor
    bug1_section_start = text.find("Sprint Bug-#1 (2026-06-08)")
    assert bug1_section_start > 0
    # Fenster gross genug fuer beide if-Branches (Edit + Delete)
    section = text[bug1_section_start:bug1_section_start + 2000]
    assert ".wr[data-posid] .btn-ico" in section
    assert "btn.classList.contains('e')" in section
    assert "btn.classList.contains('d')" in section
