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

class _FakeBind:
    """OPS-005: database_healthcheck() liest bind.url um Postgres/SQLite
    zu unterscheiden -- die Stubs bilden hier absichtlich eine SQLite-
    Verbindung nach, damit sie den (schon vorher getesteten) SELECT-1-Pfad
    nehmen, nicht den zusaetzlichen Alembic-Head-Vergleich fuer Postgres."""
    url = "sqlite:///:memory:"


class _FakeOKSession:
    """DB-Session-Stub: SELECT 1 funktioniert."""
    def execute(self, *args, **kwargs):  # noqa: D401
        result = MagicMock()
        result.scalar.return_value = 1
        return result

    def get_bind(self):
        return _FakeBind()

    def close(self):
        pass


class _FakeBrokenSession:
    """DB-Session-Stub: SELECT 1 wirft OperationalError."""
    def execute(self, *args, **kwargs):
        raise OperationalError("SELECT 1", {}, Exception("simulated DB outage"))

    def get_bind(self):
        return _FakeBind()

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
# OPS-005 (Codex-Audit 2026-08-25): SELECT 1 allein bewies nur die
# Verbindung, nicht dass das Schema zur laufenden Code-Version passt --
# unter Postgres mit mehreren Workern konnte ein Worker "ready" melden,
# waehrend die Migration eines anderen Workers noch lief.
# ---------------------------------------------------------------------------

class _FakePostgresBind:
    url = "postgresql+psycopg://user:pw@localhost/fivetest"


class _FakePostgresSessionMismatchedSchema:
    """Verbindung ok, aber alembic_version passt nicht zum erwarteten Kopf."""
    def execute(self, *args, **kwargs):
        result = MagicMock()
        result.scalar.return_value = "some-old-revision"
        return result

    def get_bind(self):
        return _FakePostgresBind()

    def close(self):
        pass


class _FakeSqliteSessionMissingCoreTable:
    """Verbindung ok, aber das Kern-Tabellen-Read schlaegt fehl (kaputtes
    Schema statt bloss langsamer Verbindung)."""
    def execute(self, *args, **kwargs):
        sql = str(args[0]) if args else ""
        if "mandates" in sql:
            raise OperationalError(sql, {}, Exception("no such table: mandates"))
        result = MagicMock()
        result.scalar.return_value = 1
        return result

    def get_bind(self):
        return _FakeBind()

    def close(self):
        pass


@pytest.fixture
def client_postgres_schema_mismatch():
    app.dependency_overrides[get_db] = _override_with(_FakePostgresSessionMismatchedSchema)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def client_sqlite_missing_core_table():
    app.dependency_overrides[get_db] = _override_with(_FakeSqliteSessionMissingCoreTable)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_db, None)


def test_health_ready_returns_503_when_postgres_schema_not_at_expected_head(
    client_postgres_schema_mismatch,
):
    """Kernfix OPS-005: ein Postgres-Worker mit veralteter/laufender
    Migration muss NICHT mehr 'ready' melden."""
    with patch(
        "database._expected_alembic_head",
        return_value="the-real-current-head",
    ):
        r = client_postgres_schema_mismatch.get("/health/ready")
    assert r.status_code == 503
    detail = r.json().get("detail", {})
    assert detail.get("reason") == "schema_not_ready"


def test_health_ready_returns_503_when_sqlite_core_table_unreadable(
    client_sqlite_missing_core_table,
):
    """SELECT 1 allein kann eine offene Verbindung gegen eine leere/kaputte
    SQLite-Datei nicht von einer echten, initialisierten DB unterscheiden."""
    r = client_sqlite_missing_core_table.get("/health/ready")
    assert r.status_code == 503


def test_health_ready_returns_200_when_postgres_schema_matches_expected_head(
    client_postgres_schema_mismatch,
):
    """Gegenprobe: stimmt die angewendete Revision mit dem erwarteten Kopf
    ueberein, bleibt die Postgres-Probe gruen wie zuvor."""
    with patch(
        "database._expected_alembic_head",
        return_value="some-old-revision",
    ):
        r = client_postgres_schema_mismatch.get("/health/ready")
    assert r.status_code == 200


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
