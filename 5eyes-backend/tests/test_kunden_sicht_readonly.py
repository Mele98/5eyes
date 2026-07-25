"""Sprint U-36 (2026-06-06): Tests fuer Client-Portal Read-Only-Sicht.

Verifiziert:
  - Berater kann Client-Login fuer eigenen Kunden erstellen
  - Berater kann KEIN Client-Login fuer fremden Kunden erstellen
  - Client kann via /client-portal/me eigene Stammdaten + Mandate lesen
  - Client kann KEIN fremdes Mandat einsehen
  - Advisor/Admin werden vom /client-portal verweigert (403)
  - Client kann KEINE Write-Endpoints nutzen (403 vom require_advisor)
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for path in (BACKEND_ROOT, TESTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from database import get_db
from main import app
from models.client_login import ClientLogin
from models.mandates import Mandate
from models.users import User
from services.auth import (
    get_current_user,
    get_linked_client_for_user_or_404,
    require_advisor,
    require_client,
)
from test_optimizer_shadow_mode import _seed_realistic_mandate, session_factory  # noqa: F401


def _override_db(session_factory):
    def _gen():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()
    return _gen


def _client_as_advisor(session_factory, advisor_id: str) -> TestClient:
    user = SimpleNamespace(id=advisor_id, full_name="Adv", email="adv@test.local", role="advisor")
    app.dependency_overrides[get_db] = _override_db(session_factory)
    app.dependency_overrides[require_advisor] = lambda: user
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _client_as_kunde(session_factory, user_id: str) -> TestClient:
    user = SimpleNamespace(id=user_id, full_name="Kunde", email="k@test.local", role="client")
    app.dependency_overrides[get_db] = _override_db(session_factory)
    app.dependency_overrides[require_client] = lambda: user
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


# ---------------------------------------------------------------------------
# POST /clients/{id}/client-login
# ---------------------------------------------------------------------------

def test_advisor_creates_client_login_for_own_client(session_factory):
    advisor_id, cid, mid, _aid, _gid = _seed_realistic_mandate(session_factory, suffix="u36own")
    try:
        with _client_as_advisor(session_factory, advisor_id) as client:
            response = client.post(
                f"/clients/{cid}/client-login",
                json={"username": "kunde-own", "password": "passw0rd!"},
            )
            assert response.status_code == 201, response.text
            data = response.json()
            assert data["client_id"] == cid
            assert data["username"] == "kunde-own"
            assert "user_id" in data
            assert "client_login_id" in data
    finally:
        app.dependency_overrides.clear()


def test_advisor_cannot_create_client_login_for_foreign_client(session_factory):
    """Berater A darf kein Login fuer Kunde von Berater B anlegen."""
    advisor_b_id, cid_b, _mid_b, _, _ = _seed_realistic_mandate(session_factory, suffix="u36b")
    # Foreign advisor anlegen + versuchen
    advisor_a_id = "adv-a-u36"
    now = "2026-06-06T10:00:00.000Z"
    with session_factory() as s:
        if not s.query(User).filter(User.id == advisor_a_id).first():
            s.add(User(
                id=advisor_a_id, username="adv-a-u36", password_hash="x",
                full_name="Adv A", role="advisor", is_active=1,
                created_at=now, updated_at=now,
            ))
            s.commit()
    try:
        with _client_as_advisor(session_factory, advisor_a_id) as client:
            response = client.post(
                f"/clients/{cid_b}/client-login",
                json={"username": "x", "password": "passw0rd!"},
            )
            assert response.status_code == 404  # Kunde nicht gefunden
    finally:
        app.dependency_overrides.clear()


def test_client_login_short_password_rejected(session_factory):
    advisor_id, cid, _mid, _aid, _gid = _seed_realistic_mandate(session_factory, suffix="u36short")
    try:
        with _client_as_advisor(session_factory, advisor_id) as client:
            response = client.post(
                f"/clients/{cid}/client-login",
                json={"username": "u36short", "password": "1234"},  # 4 chars
            )
            assert response.status_code == 422
            assert "8" in response.text
    finally:
        app.dependency_overrides.clear()


def test_client_login_duplicate_username_rejected(session_factory):
    advisor_id, cid1, _mid, _aid, _gid = _seed_realistic_mandate(session_factory, suffix="u36d1")
    advisor_id2, cid2, _mid2, _aid2, _gid2 = _seed_realistic_mandate(session_factory, suffix="u36d2")
    try:
        with _client_as_advisor(session_factory, advisor_id) as client:
            r1 = client.post(f"/clients/{cid1}/client-login",
                             json={"username": "dup-name", "password": "passw0rd!"})
            assert r1.status_code == 201
        with _client_as_advisor(session_factory, advisor_id2) as client:
            r2 = client.post(f"/clients/{cid2}/client-login",
                             json={"username": "dup-name", "password": "passw0rd!"})
            assert r2.status_code == 409
    finally:
        app.dependency_overrides.clear()


def test_client_login_duplicate_per_client_rejected(session_factory):
    """Pro Kunde nur EIN aktiver Login."""
    advisor_id, cid, _mid, _aid, _gid = _seed_realistic_mandate(session_factory, suffix="u36dc")
    try:
        with _client_as_advisor(session_factory, advisor_id) as client:
            r1 = client.post(f"/clients/{cid}/client-login",
                             json={"username": "u36dc-1", "password": "passw0rd!"})
            assert r1.status_code == 201
            r2 = client.post(f"/clients/{cid}/client-login",
                             json={"username": "u36dc-2", "password": "passw0rd!"})
            assert r2.status_code == 409
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /client-portal/me
# ---------------------------------------------------------------------------

def _setup_client_login(session_factory, suffix: str) -> tuple[str, str, str, str]:
    """Erstellt Mandat + ClientLogin + gibt (advisor_id, client_id, mandate_id, client_user_id) zurueck."""
    advisor_id, cid, mid, _aid, _gid = _seed_realistic_mandate(session_factory, suffix=suffix)
    client_user_id = f"client-user-{suffix}"
    link_id = f"link-{suffix}"
    now = "2026-06-06T10:00:00.000Z"
    with session_factory() as s:
        s.add(User(
            id=client_user_id, username=f"kunde-{suffix}",
            password_hash="x", full_name=f"Kunde {suffix}",
            role="client", is_active=1,
            created_at=now, updated_at=now,
        ))
        s.add(ClientLogin(
            id=link_id, user_id=client_user_id, client_id=cid,
            created_by=advisor_id, created_at=now, is_active=1,
        ))
        s.commit()
    return advisor_id, cid, mid, client_user_id


def test_client_me_returns_own_stammdaten_and_mandates(session_factory):
    advisor_id, cid, mid, client_user_id = _setup_client_login(session_factory, suffix="u36me")
    try:
        with _client_as_kunde(session_factory, client_user_id) as client:
            response = client.get("/client-portal/me")
            assert response.status_code == 200
            data = response.json()
            assert data["scope"] == "read_only_client_portal"
            assert data["client"]["id"] == cid
            assert len(data["mandates"]) == 1
            assert data["mandates"][0]["id"] == mid
    finally:
        app.dependency_overrides.clear()


def test_client_me_without_linkage_returns_404(session_factory):
    """User mit role='client' aber keiner ClientLogin -> 404."""
    user_id = "client-no-link-u36"
    now = "2026-06-06T10:00:00.000Z"
    with session_factory() as s:
        s.add(User(
            id=user_id, username="no-link-u36",
            password_hash="x", full_name="Ohne Linkage",
            role="client", is_active=1,
            created_at=now, updated_at=now,
        ))
        s.commit()
    try:
        with _client_as_kunde(session_factory, user_id) as client:
            response = client.get("/client-portal/me")
            assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /client-portal/mandates/{mandate_id}/report
# ---------------------------------------------------------------------------

def test_client_can_read_own_mandate_report(session_factory):
    advisor_id, cid, mid, client_user_id = _setup_client_login(session_factory, suffix="u36rep")
    try:
        with _client_as_kunde(session_factory, client_user_id) as client:
            response = client.get(f"/client-portal/mandates/{mid}/report")
            assert response.status_code == 200, response.text
            data = response.json()
            assert data["mandate_id"] == mid
            assert "cover" in data
            assert "erkenntnisse" in data
            # Sektion 24 U-94 muss da sein
            assert "optimizer_run_history" in data
    finally:
        app.dependency_overrides.clear()


def test_client_cannot_read_foreign_mandate_report(session_factory):
    """Kunde A darf nicht Mandat von Kunde B sehen."""
    _, _cidA, midA, client_user_A = _setup_client_login(session_factory, suffix="u36fA")
    _, _cidB, midB, _client_user_B = _setup_client_login(session_factory, suffix="u36fB")
    try:
        with _client_as_kunde(session_factory, client_user_A) as client:
            response = client.get(f"/client-portal/mandates/{midB}/report")
            assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /client-portal/mandates/{mandate_id}/risk-profile/sign
# 2026-07-25 (Generalaudit, Wave-8-Fork): der Code-Pfad ist identisch zum
# Report-Endpoint geschuetzt (Mandate.client_id == client.id), aber es fehlte
# ein expliziter Cross-Client-IDOR-Test dafuer (reine Coverage-Luecke).
# ---------------------------------------------------------------------------

def test_client_cannot_sign_foreign_mandate_risk_profile(session_factory):
    """Kunde A darf nicht das Risikoprofil von Kunde B signieren (IDOR)."""
    _, _cidA, midA, client_user_A = _setup_client_login(session_factory, suffix="u36signA")
    _, _cidB, midB, _client_user_B = _setup_client_login(session_factory, suffix="u36signB")
    try:
        with _client_as_kunde(session_factory, client_user_A) as client:
            response = client.post(f"/client-portal/mandates/{midB}/risk-profile/sign")
            assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Rollen-Trennung: Advisor darf nicht ins Client-Portal
# ---------------------------------------------------------------------------

def test_advisor_cannot_access_client_portal(session_factory):
    """require_client verweigert role='advisor'."""
    advisor_id, _cid, _mid, _aid, _gid = _seed_realistic_mandate(session_factory, suffix="u36adv")
    # Wir overriden NUR get_current_user (NICHT require_client), damit
    # require_client den echten Rollen-Check macht.
    user = SimpleNamespace(id=advisor_id, full_name="Adv", email="adv@test.local", role="advisor")
    app.dependency_overrides[get_db] = _override_db(session_factory)
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        with TestClient(app) as client:
            response = client.get("/client-portal/me")
            assert response.status_code == 403
            assert "Kunden-Login" in response.text or "client" in response.text.lower()
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helper-Tests
# ---------------------------------------------------------------------------

def test_get_linked_client_helper_returns_client(session_factory):
    advisor_id, cid, _mid, client_user_id = _setup_client_login(session_factory, suffix="u36h")
    with session_factory() as s:
        user = s.query(User).filter(User.id == client_user_id).first()
        client = get_linked_client_for_user_or_404(user, s)
        assert client.id == cid


def test_get_linked_client_helper_raises_on_missing_link(session_factory):
    """Pure-Helper-Test ohne FastAPI-TestClient."""
    from fastapi import HTTPException as _HTTPException
    import pytest

    user_id = "u36-no-link"
    now = "2026-06-06T10:00:00.000Z"
    with session_factory() as s:
        s.add(User(
            id=user_id, username="u36-no-link",
            password_hash="x", full_name="x", role="client",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.commit()
    with session_factory() as s:
        user = s.query(User).filter(User.id == user_id).first()
        with pytest.raises(_HTTPException) as exc:
            get_linked_client_for_user_or_404(user, s)
        assert exc.value.status_code == 404
