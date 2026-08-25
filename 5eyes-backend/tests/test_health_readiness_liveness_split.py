"""Sprint U-63 (Roadmap-Punkt 63, 2026-06-01): Health-Endpoint
Readiness/Liveness-Split Audit + Behavior-Tests.

Pre-U-63
--------
- /health, /health/ready, /health/db existierten
- KEIN expliziter /health/live -> Container-Orchestrierung musste
  /health/ready fuer Liveness MISSBRAUCHEN
- /health/ready returnte IMMER 200 — auch wenn DB nicht erreichbar.
  Traffic wurde nie aktiv abgewiesen.

Post-U-63
---------
- /health/live ohne DB-Hit, immer 200 wenn Prozess lebt
- /health/ready mit DB-Check, 503 bei SQLAlchemyError
- price_runtime_status bleibt informational (non-blocking)
- /health (root) bleibt backwards-compat
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import get_db  # noqa: E402
from main import app  # noqa: E402


# ---------------------------------------------------------------------------
# Hilfsmittel: DB-Stub via dependency_overrides
# ---------------------------------------------------------------------------

class _FakeOKSession:
    """DB-Session-Stub: SELECT 1 funktioniert."""
    def execute(self, *args, **kwargs):  # noqa: D401
        result = MagicMock()
        result.scalar.return_value = 1
        return result

    def close(self):
        pass


class _FakeBrokenSession:
    """DB-Session-Stub: SELECT 1 wirft OperationalError."""
    def execute(self, *args, **kwargs):
        raise OperationalError("SELECT 1", {}, Exception("simulated DB outage"))

    def close(self):
        pass


def _override_with(session_factory):
    def _get_db_override():
        sess = session_factory()
        try:
            yield sess
        finally:
            sess.close()
    return _get_db_override


@pytest.fixture
def client_ok_db():
    app.dependency_overrides[get_db] = _override_with(_FakeOKSession)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def client_broken_db():
    app.dependency_overrides[get_db] = _override_with(_FakeBrokenSession)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# /health (root) — backwards-compat
# ---------------------------------------------------------------------------

def test_health_root_returns_200_without_db(client_ok_db):
    """Root-Endpoint laeuft ohne DB-Abhaengigkeit."""
    r = client_ok_db.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "app" in body
    assert "version" in body


def test_health_root_returns_200_even_when_db_broken(client_broken_db):
    """Root soll NICHT auf DB-Fehler reagieren — backwards-compat."""
    r = client_broken_db.get("/health")
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# /health/live — U-63 NEU
# ---------------------------------------------------------------------------

def test_health_live_exists(client_ok_db):
    """/health/live MUSS existieren (U-63 SLO)."""
    r = client_ok_db.get("/health/live")
    assert r.status_code != 404, "/health/live nicht implementiert"


def test_health_live_returns_alive(client_ok_db):
    r = client_ok_db.get("/health/live")
    assert r.status_code == 200
    assert r.json()["status"] == "alive"


def test_health_live_no_db_dependency(client_broken_db):
    """Liveness soll NICHT auf DB-Status reagieren — sonst wuerde
    DB-Outage einen Container-Restart triggern, was Recovery
    verschlimmert."""
    r = client_broken_db.get("/health/live")
    assert r.status_code == 200, (
        "Liveness-Probe wurde durch DB-Outage gestoert — verletzt "
        "U-63 SLO. Liveness darf KEINE DB-Calls machen."
    )
    assert r.json()["status"] == "alive"


def test_health_live_includes_base_payload(client_ok_db):
    r = client_ok_db.get("/health/live")
    body = r.json()
    for key in ("app", "version", "environment", "host", "port"):
        assert key in body, f"/health/live fehlt Feld {key!r}"


# ---------------------------------------------------------------------------
# /health/ready — DB-Check + 503
# ---------------------------------------------------------------------------

def test_health_ready_returns_200_when_db_ok(client_ok_db):
    """Mit funktionierender DB -> 200 ready."""
    with patch(
        "routers.health.get_price_runtime_status",
        return_value={"status": "ok"},
    ):
        r = client_ok_db.get("/health/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready"
    assert body.get("database") == "ok"


def test_health_ready_returns_503_when_db_broken(client_broken_db):
    """U-63 KERNFIX: DB-Outage -> 503 Service Unavailable.

    Pre-U-63 war das ein 200 mit fehlerhaftem payload. Traffic
    wurde nie aktiv abgewiesen.
    """
    r = client_broken_db.get("/health/ready")
    assert r.status_code == 503, (
        f"/health/ready returnt {r.status_code} bei DB-Outage — "
        f"sollte 503 sein damit Traffic gestoppt wird."
    )
    body = r.json()
    detail = body.get("detail", {})
    if isinstance(detail, dict):
        assert detail.get("status") == "not_ready"
        assert detail.get("reason") == "database_unreachable"


def test_health_ready_price_status_failure_is_non_blocking(client_ok_db):
    """price_runtime_status-Exception -> 200, prices.status=unknown.
    Markdaten-Outage soll Beratung nicht blockieren."""
    with patch(
        "routers.health.get_price_runtime_status",
        side_effect=RuntimeError("price service unreachable"),
    ):
        r = client_ok_db.get("/health/ready")
    assert r.status_code == 200, (
        "price-Service-Outage darf NICHT 503 triggern (informational)."
    )
    body = r.json()
    assert body.get("prices", {}).get("status") == "unknown"


# ---------------------------------------------------------------------------
# /health/db
# ---------------------------------------------------------------------------

def test_health_db_returns_200_when_ok(client_ok_db):
    r = client_ok_db.get("/health/db")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body.get("database") == "ok"


# ---------------------------------------------------------------------------
# Audit: alle 4 Endpoints registriert
# ---------------------------------------------------------------------------

def test_all_four_health_routes_registered():
    """Routen-Inventar — schuetzt vor Drift wenn jemand /health/live
    entfernt."""
    paths = {r.path for r in app.routes}
    for expected in ("/health", "/health/live", "/health/ready", "/health/db"):
        assert expected in paths, (
            f"Route {expected!r} fehlt im FastAPI-App. Vorhanden: "
            f"{sorted(p for p in paths if p.startswith('/health'))}"
        )
