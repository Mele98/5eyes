"""Sprint U-102 (2026-06-05): Admin-Endpoint Audit-Trail.

Pre-U-102 schrieben 6 Admin-Endpoints in routers/system.py keinen
AuditLog-Eintrag — FINMA-Audit haette diese Aktionen nicht nachvoll-
ziehen koennen. Tests verifizieren dass JEDE state-aendernde Admin-
Aktion einen Audit-Eintrag mit korrektem Action-Code hinterlaesst.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for path in (BACKEND_ROOT, TESTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from database import get_db
from main import app
from models.review import AuditLog
from routers import system as system_router
from services.auth import require_admin, require_advisor
from test_optimizer_shadow_mode import session_factory  # noqa: F401


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _client(session_factory, admin_id: str = "admin-u102") -> TestClient:
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    admin_user = SimpleNamespace(
        id=admin_id, full_name="Admin U102", email="admin@example.test"
    )
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_admin] = lambda: admin_user
    app.dependency_overrides[require_advisor] = lambda: admin_user
    return TestClient(app)


def _latest_audit(session_factory, action: str) -> AuditLog | None:
    with session_factory() as s:
        return (
            s.query(AuditLog)
            .filter(AuditLog.action == action)
            .order_by(AuditLog.created_at.desc())
            .first()
        )


# ---------------------------------------------------------------------------
# Valid-Actions-Whitelist Tests (Filter-Konsistenz)
# ---------------------------------------------------------------------------

def test_valid_actions_whitelist_includes_all_new_actions():
    """Whitelist muss neu hinzugefuegte Actions kennen (sonst GET /audit-log Filter waere broken)."""
    expected_new = {
        "BACKFILL",
        "BACKUP",
        "SUPPORT_BUNDLE",
        "MARKET_DATA_REFRESH",
        "MARKET_DATA_PURGE",
        "DB_OPTIMIZE",
        "FOUNDATION_EXAMPLE",
        "FOUNDATION_PURGE",
    }
    actual = system_router.AUDIT_LOG_VALID_ACTIONS
    for act in expected_new:
        assert act in actual, f"Action {act!r} fehlt in AUDIT_LOG_VALID_ACTIONS"


def test_valid_actions_whitelist_keeps_legacy_actions():
    """Bestehende Actions bleiben filtrierbar."""
    legacy = {"CREATE", "UPDATE", "DELETE", "LOGIN", "EXPORT",
              "PASSWORD_RESET", "OPTIMIZER_MODE_CHANGE"}
    for act in legacy:
        assert act in system_router.AUDIT_LOG_VALID_ACTIONS


# ---------------------------------------------------------------------------
# Endpoint-Tests: jeder state-aendernde Admin-Endpoint schreibt Audit
# ---------------------------------------------------------------------------

def test_db_backup_writes_audit_log(session_factory, monkeypatch):
    monkeypatch.setattr(
        system_router, "create_backup",
        lambda: {"backup_path": "/tmp/test.bak", "size_bytes": 1234, "status": "ok"},
    )
    try:
        with _client(session_factory) as client:
            response = client.post("/admin/system/db/backup")
            assert response.status_code == 200
    finally:
        app.dependency_overrides.clear()

    row = _latest_audit(session_factory, "BACKUP")
    assert row is not None
    assert row.table_name == "system_backups"
    assert "test.bak" in (row.record_id or "")


def test_support_bundle_writes_audit_log(session_factory, monkeypatch):
    monkeypatch.setattr(
        system_router, "create_support_bundle",
        lambda: {"bundle_path": "/tmp/support.zip", "size_bytes": 4567, "status": "ok"},
    )
    try:
        with _client(session_factory) as client:
            response = client.post("/admin/system/support-bundle")
            assert response.status_code == 200
    finally:
        app.dependency_overrides.clear()

    row = _latest_audit(session_factory, "SUPPORT_BUNDLE")
    assert row is not None
    assert row.table_name == "support_bundles"
    assert "support.zip" in (row.record_id or "")


def test_annual_return_upsert_create_writes_audit(session_factory):
    try:
        with _client(session_factory) as client:
            response = client.put(
                "/admin/system/annual-returns/2030/Aktien",
                json={"return_bps": 550, "source": "test"},
            )
            assert response.status_code == 200, response.text
    finally:
        app.dependency_overrides.clear()

    row = _latest_audit(session_factory, "CREATE")
    assert row is not None
    assert row.table_name == "asset_class_annual_returns"
    assert row.record_id == "2030-Aktien"
    assert row.new_value == "550"
    assert row.field_name == "return_bps"


def test_annual_return_upsert_update_writes_audit_with_old_value(session_factory):
    try:
        with _client(session_factory) as client:
            # First create
            client.put(
                "/admin/system/annual-returns/2031/Obligationen",
                json={"return_bps": 200, "source": "test"},
            )
            # Then update
            response = client.put(
                "/admin/system/annual-returns/2031/Obligationen",
                json={"return_bps": 250, "source": "test"},
            )
            assert response.status_code == 200
    finally:
        app.dependency_overrides.clear()

    # UPDATE-Row mit old_value=200 muss existieren
    with session_factory() as s:
        rows = (
            s.query(AuditLog)
            .filter(AuditLog.action == "UPDATE")
            .filter(AuditLog.record_id == "2031-Obligationen")
            .order_by(AuditLog.created_at.desc())
            .all()
        )
    assert len(rows) >= 1
    assert rows[0].old_value == "200"
    assert rows[0].new_value == "250"


# ── 2026-07-25 (Generalaudit): return_bps hatte keinen Plausibilitaets-Range-
# Check -- ein Tippfehler (zusaetzliche Null) konnte einen absurden Wert
# unbemerkt persistieren, der in JEDE Kundenempfehlung fuer diese Asset-
# Class/Jahr einfliesst (systemweiter Blast-Radius, analog SCHEMA-03 Vola>=0).

def test_annual_return_upsert_rejects_absurd_return_bps(session_factory):
    try:
        with _client(session_factory) as client:
            response = client.put(
                "/admin/system/annual-returns/2032/Aktien",
                json={"return_bps": -500_000, "source": "test"},
            )
            assert response.status_code == 422, response.text
    finally:
        app.dependency_overrides.clear()

    with session_factory() as s:
        from models.snapshots import AssetClassAnnualReturn
        assert s.query(AssetClassAnnualReturn).filter_by(
            year=2032, asset_class="Aktien",
        ).count() == 0


def test_annual_return_upsert_accepts_extreme_but_plausible_bps(session_factory):
    try:
        with _client(session_factory) as client:
            response = client.put(
                "/admin/system/annual-returns/2033/Aktien",
                json={"return_bps": -9_000, "source": "test"},
            )
            assert response.status_code == 200, response.text
            response = client.put(
                "/admin/system/annual-returns/2034/Aktien",
                json={"return_bps": 80_000, "source": "test"},
            )
            assert response.status_code == 200, response.text
    finally:
        app.dependency_overrides.clear()


def test_market_data_refresh_writes_audit(session_factory, monkeypatch):
    # Stub den Service damit kein echter yfinance-Call passiert
    import services.market_data_daily_refresh as mdr

    monkeypatch.setattr(
        mdr, "run_daily_market_data_refresh",
        lambda db: {"run_id": "run-test", "status": "ok", "providers": []},
    )
    try:
        with _client(session_factory) as client:
            response = client.post("/admin/system/market-data/refresh-now")
            assert response.status_code == 200
    finally:
        app.dependency_overrides.clear()

    row = _latest_audit(session_factory, "MARKET_DATA_REFRESH")
    assert row is not None
    assert row.table_name == "market_data_runs"
    assert row.record_id == "run-test"


def test_market_data_purge_writes_audit(session_factory, monkeypatch):
    import services.market_data.cache_purge as cp

    monkeypatch.setattr(
        cp, "run_daily_cache_purge",
        lambda db: {"run_id": "purge-test", "rows_deleted": 42, "status": "ok"},
    )
    try:
        with _client(session_factory) as client:
            response = client.post("/admin/system/market-data/purge-now")
            assert response.status_code == 200
    finally:
        app.dependency_overrides.clear()

    row = _latest_audit(session_factory, "MARKET_DATA_PURGE")
    assert row is not None
    assert row.table_name == "market_data_cache"
    assert row.record_id == "purge-test"


def test_db_optimize_writes_audit(session_factory, monkeypatch):
    monkeypatch.setattr(
        system_router, "run_optimize",
        lambda db: {"status": "ok", "vacuumed": True, "analyzed": True},
    )
    try:
        with _client(session_factory) as client:
            response = client.post("/admin/system/db/optimize")
            assert response.status_code == 200
    finally:
        app.dependency_overrides.clear()

    row = _latest_audit(session_factory, "DB_OPTIMIZE")
    assert row is not None
    assert row.table_name == "system_db"
    assert row.record_id == "optimize"


def test_foundation_example_writes_audit(session_factory, monkeypatch):
    fake_mid = str(uuid4())
    monkeypatch.setattr(
        system_router, "upsert_foundation_example_case",
        lambda db, user: {"mandate_id": fake_mid, "status": "created"},
    )
    try:
        with _client(session_factory) as client:
            response = client.post("/admin/system/foundation-example")
            assert response.status_code == 200
    finally:
        app.dependency_overrides.clear()

    row = _latest_audit(session_factory, "FOUNDATION_EXAMPLE")
    assert row is not None
    assert row.table_name == "foundation_example"
    assert row.record_id == fake_mid


# ---------------------------------------------------------------------------
# Audit-Log-Filter-Test (verifiziert dass die neuen Actions filtrierbar sind)
# ---------------------------------------------------------------------------

def test_audit_log_filter_accepts_new_actions(session_factory, monkeypatch):
    """Wenn ich nach action=BACKUP filtere, darf die Whitelist das nicht verwerfen."""
    monkeypatch.setattr(
        system_router, "create_backup",
        lambda: {"backup_path": "/tmp/f.bak", "size_bytes": 1, "status": "ok"},
    )
    try:
        with _client(session_factory) as client:
            client.post("/admin/system/db/backup")
            response = client.get("/admin/system/audit-log?action=BACKUP")
            assert response.status_code == 200
            data = response.json()
            assert data["total"] >= 1
            assert any(e["action"] == "BACKUP" for e in data["entries"])
    finally:
        app.dependency_overrides.clear()


def test_audit_log_filter_rejects_unknown_action(session_factory):
    """Unbekannte Actions werden weiter ignoriert (kein 500)."""
    try:
        with _client(session_factory) as client:
            response = client.get("/admin/system/audit-log?action=NONSENSE_ACTION")
            assert response.status_code == 200
            # Filter ignoriert unbekannte Action -> Liste ist alle Eintraege
    finally:
        app.dependency_overrides.clear()
