"""Sprint U-99 (2026-06-05): Tests fuer dedicated FX-Refresh-Trigger.

Verifiziert
  - Service liefert FX-Result-Schema mit fx_added/scope='fx_only'/timestamps
  - delegiert an existierende _refresh_fx_rates-Logik (kein Drift)
  - Endpoint POST /admin/system/fx-rates/refresh-now ruft Service +
    schreibt Audit (MARKET_DATA_REFRESH, table=asset_class_fx_history)
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
from models.review import AuditLog
from services.auth import require_admin, require_admin_or_platform_scope_for_global_reference_data
from test_optimizer_shadow_mode import session_factory  # noqa: F401


def _client(session_factory) -> TestClient:
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()
    admin = SimpleNamespace(id="admin-u99", full_name="Admin U99", email="admin@test.local")
    app.dependency_overrides[get_db] = override_get_db
    # AUTH-TEN-06 (Codex-Audit 2026-08-25): /fx-rates/refresh-now nutzt jetzt
    # require_admin_or_platform_scope_for_global_reference_data statt
    # require_admin -- beide Overrides gesetzt (require_admin bleibt fuer
    # andere Endpoints in diesem Modul falls je genutzt).
    app.dependency_overrides[require_admin] = lambda: admin
    app.dependency_overrides[require_admin_or_platform_scope_for_global_reference_data] = lambda: admin
    return TestClient(app)


# ---------------------------------------------------------------------------
# Service-Layer Tests
# ---------------------------------------------------------------------------

def test_service_returns_fx_only_scope(session_factory, monkeypatch):
    """run_daily_fx_refresh delegiert an _refresh_fx_rates und liefert scope=fx_only."""
    import services.market_data_daily_refresh as mdr

    monkeypatch.setattr(
        "services.market_data.factory.build_default_aggregator",
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(mdr, "_refresh_fx_rates", lambda db, agg, errors: 5)

    from services.fx_rate_daily_refresh import run_daily_fx_refresh
    with session_factory() as s:
        result = run_daily_fx_refresh(s)
    assert result["scope"] == "fx_only"
    assert result["fx_added"] == 5
    assert result["status"] == "ok"
    assert result["errors"] == []
    assert result["started_at"].endswith("Z")
    assert result["finished_at"].endswith("Z")


def test_service_reports_degraded_on_errors(session_factory, monkeypatch):
    import services.market_data_daily_refresh as mdr

    monkeypatch.setattr(
        "services.market_data.factory.build_default_aggregator",
        lambda: SimpleNamespace(),
    )

    def _fake_refresh(db, agg, errors):
        errors.append({"scope": "fx", "currency": "USD", "reason": "Provider down"})
        return 0

    monkeypatch.setattr(mdr, "_refresh_fx_rates", _fake_refresh)

    from services.fx_rate_daily_refresh import run_daily_fx_refresh
    with session_factory() as s:
        result = run_daily_fx_refresh(s)
    assert result["status"] == "degraded"
    assert result["fx_added"] == 0
    assert len(result["errors"]) == 1
    assert result["errors"][0]["scope"] == "fx"


def test_service_propagates_commit_failure(session_factory, monkeypatch):
    """Bei DB-Commit-Fehler -> rollback + Exception weitergereicht."""
    import services.market_data_daily_refresh as mdr

    monkeypatch.setattr(
        "services.market_data.factory.build_default_aggregator",
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(mdr, "_refresh_fx_rates", lambda db, agg, errors: 0)

    class _BrokenSession:
        def commit(self):
            raise RuntimeError("simulated db down")

        def rollback(self):
            pass

    from services.fx_rate_daily_refresh import run_daily_fx_refresh
    try:
        run_daily_fx_refresh(_BrokenSession())
    except RuntimeError as exc:
        assert "simulated db down" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError")


# ---------------------------------------------------------------------------
# Endpoint Tests
# ---------------------------------------------------------------------------

def test_endpoint_returns_fx_result_and_writes_audit(session_factory, monkeypatch):
    """Happy path: Endpoint ruft Service + schreibt Audit."""
    import services.fx_rate_daily_refresh as fxr

    monkeypatch.setattr(
        fxr, "run_daily_fx_refresh",
        lambda db: {
            "status": "ok",
            "scope": "fx_only",
            "started_at": "2026-06-05T10:00:00.000Z",
            "finished_at": "2026-06-05T10:00:01.000Z",
            "duration_seconds": 1.0,
            "fx_added": 7,
            "errors": [],
        },
    )

    try:
        with _client(session_factory) as client:
            response = client.post("/admin/system/fx-rates/refresh-now")
            assert response.status_code == 200, response.text
            data = response.json()
            assert data["scope"] == "fx_only"
            assert data["fx_added"] == 7
    finally:
        app.dependency_overrides.clear()

    # Audit-Row muss existieren
    with session_factory() as s:
        rows = (
            s.query(AuditLog)
            .filter(AuditLog.table_name == "asset_class_fx_history")
            .filter(AuditLog.action == "MARKET_DATA_REFRESH")
            .order_by(AuditLog.created_at.desc())
            .all()
        )
    assert len(rows) >= 1
    assert rows[0].field_name == "fx_only_refresh"
    assert "fx_added=7" in (rows[0].new_value or "")
    assert "status=ok" in (rows[0].new_value or "")


def test_endpoint_returns_500_on_service_exception(session_factory, monkeypatch):
    import services.fx_rate_daily_refresh as fxr

    def _broken(db):
        raise RuntimeError("aggregator down")

    monkeypatch.setattr(fxr, "run_daily_fx_refresh", _broken)

    try:
        with _client(session_factory) as client:
            response = client.post("/admin/system/fx-rates/refresh-now")
            assert response.status_code == 500
            assert "aggregator down" in response.text
    finally:
        app.dependency_overrides.clear()


def test_endpoint_audit_filtered_via_market_data_refresh_action(session_factory, monkeypatch):
    """GET /admin/system/audit-log?action=MARKET_DATA_REFRESH findet den FX-Eintrag."""
    import services.fx_rate_daily_refresh as fxr

    monkeypatch.setattr(
        fxr, "run_daily_fx_refresh",
        lambda db: {
            "status": "ok", "scope": "fx_only",
            "started_at": "2026-06-05T11:00:00.000Z",
            "finished_at": "2026-06-05T11:00:01.000Z",
            "duration_seconds": 1.0, "fx_added": 3, "errors": [],
        },
    )
    try:
        with _client(session_factory) as client:
            client.post("/admin/system/fx-rates/refresh-now")
            response = client.get("/admin/system/audit-log?action=MARKET_DATA_REFRESH")
            assert response.status_code == 200
            data = response.json()
            assert data["total"] >= 1
            assert any(
                e["table_name"] == "asset_class_fx_history"
                for e in data["entries"]
            )
    finally:
        app.dependency_overrides.clear()
