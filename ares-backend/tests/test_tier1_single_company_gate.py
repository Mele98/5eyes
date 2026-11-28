"""Tier-1-Einzelfirmen-Gate (CH-RC 27.11.2026).

Eine Ares-Instanz bedient im Default ``single_company`` genau eine Firma:
- zweite Firma ueber die Tenant-API -> 409 SECOND_TENANT_FORBIDDEN (nichts angelegt)
- Default-Seed nutzt dieselbe Pruefung (assert_tenant_creation_allowed)
- Start mit mehr als einer Firma -> TENANT_COUNT_INVALID
- Restore einer Mehrfirmen-Sicherung -> abgelehnt, laufende DB byte-identisch
- Moduswechsel nur mit Bestaetigung, protokolliert als DEPLOYMENT_MODE_CHANGED
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import models  # noqa: F401  (alle Tabellen registrieren)
import models.tenant  # noqa: F401
from config import Settings, settings
from database import (
    DEPLOYMENT_MANIFEST_TABLE,
    DEPLOYMENT_MODE_CHANGED,
    SECOND_TENANT_FORBIDDEN,
    TENANT_COUNT_INVALID,
    Base,
    TenantDeploymentError,
    assert_single_company_database,
    assert_tenant_creation_allowed,
    count_tenants,
    ensure_default_tenant,
    get_db,
)
from models.review import AuditLog
from routers.tenants import enforce_deployment_mode_at_startup
from models.tenant import DEFAULT_TENANT_ID, Tenant

NOW = "2026-11-27T05:00:00.000Z"
BACKEND = Path(__file__).resolve().parents[1]


def _engine(db_file: Path):
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return engine


def _tenant(tid: str, slug: str) -> Tenant:
    return Tenant(
        id=tid, display_name=f"Firma {slug}", slug=slug, hosting_tier="tier1",
        license_status="active", max_users=1, is_active=1, created_at=NOW, updated_at=NOW,
    )


def _add(engine, *tenants: Tenant) -> None:
    with sessionmaker(bind=engine)() as db:
        db.add_all(list(tenants))
        db.commit()


@pytest.fixture()
def single(monkeypatch):
    monkeypatch.setattr(settings, "deployment_mode", "single_company", raising=False)
    monkeypatch.setattr(settings, "deployment_mode_change_confirmation", "", raising=False)


@pytest.fixture()
def engine(tmp_path):
    eng = _engine(tmp_path / "gate.db")
    yield eng
    eng.dispose()


# --- Konfiguration ----------------------------------------------------------

def test_default_mode_is_single_company():
    assert Settings.model_fields["deployment_mode"].default == "single_company"


def test_tenant_admin_ui_requires_multi_tenant():
    with pytest.raises(ValueError, match="deployment_mode=multi_tenant"):
        Settings(app_env="development", tenant_admin_ui_enabled=True, strict_tenant_isolation=True)
    cfg = Settings(app_env="development", tenant_admin_ui_enabled=True,
                   strict_tenant_isolation=True, deployment_mode="multi_tenant")
    assert cfg.deployment_mode == "multi_tenant"


def test_multi_tenant_requires_strict_isolation():
    with pytest.raises(ValueError, match="multi_tenant erfordert strikte"):
        Settings(app_env="development", deployment_tier="tier1", tenancy_mode="single",
                 strict_tenant_isolation=False, deployment_mode="multi_tenant")


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError):
        Settings(app_env="development", deployment_mode="multi")


# --- Anlegen einer Firma ----------------------------------------------------

def test_creation_gate_allows_only_first_company(single, engine):
    with sessionmaker(bind=engine)() as db:
        assert_tenant_creation_allowed(db)  # leer: 'main' darf entstehen
    _add(engine, _tenant(DEFAULT_TENANT_ID, "main"))
    with sessionmaker(bind=engine)() as db:
        with pytest.raises(TenantDeploymentError) as exc:
            assert_tenant_creation_allowed(db)
        assert exc.value.code == SECOND_TENANT_FORBIDDEN


def test_creation_gate_counts_inactive_and_deleted_companies(single, engine):
    dormant = _tenant("t-dormant", "ruhend")
    dormant.is_active = 0
    _add(engine, dormant)
    with sessionmaker(bind=engine)() as db:
        with pytest.raises(TenantDeploymentError):
            assert_tenant_creation_allowed(db)


def test_creation_gate_open_in_multi_tenant(monkeypatch, engine):
    monkeypatch.setattr(settings, "deployment_mode", "multi_tenant", raising=False)
    _add(engine, _tenant(DEFAULT_TENANT_ID, "main"))
    with sessionmaker(bind=engine)() as db:
        assert_tenant_creation_allowed(db)


def test_default_seed_uses_same_gate(single, engine):
    _add(engine, _tenant("t-foreign", "fremd"))
    with pytest.raises(TenantDeploymentError) as exc:
        ensure_default_tenant(engine)
    assert exc.value.code == SECOND_TENANT_FORBIDDEN
    with sessionmaker(bind=engine)() as db:
        assert count_tenants(db) == 1


def test_default_seed_creates_main_on_empty_db(single, engine):
    ensure_default_tenant(engine)
    ensure_default_tenant(engine)  # idempotent
    with sessionmaker(bind=engine)() as db:
        assert count_tenants(db) == 1
        assert_single_company_database(db)


def test_api_rejects_second_company(single, monkeypatch, engine):
    from main import app
    from models.users import User
    from services.auth import get_current_user

    monkeypatch.setattr(settings, "tenant_admin_ui_enabled", True, raising=False)
    _add(engine, _tenant(DEFAULT_TENANT_ID, "main"))
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    root = User(id="u-root", username="root", email="root@example.invalid", full_name="Root",
                role="super_admin", password_hash="x", is_active=1, tenant_id=DEFAULT_TENANT_ID,
                created_at=NOW, updated_at=NOW)

    def override_db():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: root
    try:
        response = TestClient(app).post("/tenants", json={
            "display_name": "Zweite Firma", "slug": "zweite", "hosting_tier": "tier1",
        })
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == SECOND_TENANT_FORBIDDEN
    with factory() as db:
        assert count_tenants(db) == 1


# --- Start --------------------------------------------------------------------

def test_startup_accepts_exactly_one_company(single, engine):
    _add(engine, _tenant(DEFAULT_TENANT_ID, "main"))
    enforce_deployment_mode_at_startup(engine)


@pytest.mark.parametrize("extra", [0, 1])
def test_startup_rejects_wrong_company_count(single, engine, extra):
    if extra:
        _add(engine, _tenant(DEFAULT_TENANT_ID, "main"), _tenant("t-2", "zwei"))
    with pytest.raises(TenantDeploymentError) as exc:
        enforce_deployment_mode_at_startup(engine)
    assert exc.value.code == TENANT_COUNT_INVALID


def test_lifespan_runs_gate_after_init_db():
    tree = ast.parse((BACKEND / "main.py").read_text(encoding="utf-8"))
    lifespan = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "lifespan")
    calls = [n.func.id for n in ast.walk(lifespan) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
    assert "init_db" in calls and "enforce_deployment_mode_at_startup" in calls
    assert calls.index("init_db") < calls.index("enforce_deployment_mode_at_startup")


# --- Moduswechsel ---------------------------------------------------------------

def _manifest_rows(engine):
    with sessionmaker(bind=engine)() as db:
        return [
            (r.old_value, r.new_value)
            for r in db.query(AuditLog).filter(
                AuditLog.table_name == DEPLOYMENT_MANIFEST_TABLE,
                AuditLog.action == DEPLOYMENT_MODE_CHANGED,
            ).order_by(AuditLog.created_at).all()
        ]


def test_mode_change_needs_confirmation_and_is_audited(single, monkeypatch, engine):
    _add(engine, _tenant(DEFAULT_TENANT_ID, "main"))
    enforce_deployment_mode_at_startup(engine)
    assert _manifest_rows(engine) == []  # Default ohne Wechsel: kein Eintrag

    monkeypatch.setattr(settings, "deployment_mode", "multi_tenant", raising=False)
    with pytest.raises(TenantDeploymentError) as exc:
        enforce_deployment_mode_at_startup(engine)
    assert exc.value.code == DEPLOYMENT_MODE_CHANGED
    monkeypatch.setattr(settings, "deployment_mode_change_confirmation", "single_company->falsch", raising=False)
    with pytest.raises(TenantDeploymentError):
        enforce_deployment_mode_at_startup(engine)
    assert _manifest_rows(engine) == []

    monkeypatch.setattr(settings, "deployment_mode_change_confirmation", "single_company->multi_tenant", raising=False)
    enforce_deployment_mode_at_startup(engine)
    assert _manifest_rows(engine) == [("single_company", "multi_tenant")]
    enforce_deployment_mode_at_startup(engine)  # gleicher Modus: kein zweiter Eintrag
    assert _manifest_rows(engine) == [("single_company", "multi_tenant")]

    # Zurueck auf single_company: Bestaetigung reicht nicht bei zwei Firmen.
    _add(engine, _tenant("t-2", "zwei"))
    monkeypatch.setattr(settings, "deployment_mode", "single_company", raising=False)
    monkeypatch.setattr(settings, "deployment_mode_change_confirmation", "", raising=False)
    with pytest.raises(TenantDeploymentError) as exc:
        enforce_deployment_mode_at_startup(engine)
    assert exc.value.code == DEPLOYMENT_MODE_CHANGED
    monkeypatch.setattr(settings, "deployment_mode_change_confirmation", "multi_tenant->single_company", raising=False)
    with pytest.raises(TenantDeploymentError) as exc:
        enforce_deployment_mode_at_startup(engine)
    assert exc.value.code == TENANT_COUNT_INVALID
    assert _manifest_rows(engine) == [("single_company", "multi_tenant")]


# --- Restore -------------------------------------------------------------------

def _db_with(path: Path, *tenants: Tenant) -> Path:
    eng = _engine(path)
    if tenants:
        _add(eng, *tenants)
    eng.dispose()
    return path


def _digest(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("configured_url", [False, True], ids=["ohne_database_url", "mit_database_url"])
def test_restore_rejects_multi_company_backup_before_overwriting(single, monkeypatch, tmp_path, configured_url):
    from services.maintenance import restore_backup

    live = _db_with(tmp_path / "live.db", _tenant(DEFAULT_TENANT_ID, "main"))
    backup = _db_with(tmp_path / "fremd.db", _tenant(DEFAULT_TENANT_ID, "main"), _tenant("t-2", "zwei"))
    # C-T1-01: eine gesetzte DATABASE_URL (zeigt auf die laufende Einfirmen-DB)
    # darf die Vorpruefung nicht von der Sicherung weglenken.
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{live.as_posix()}" if configured_url else None,
                        raising=False)
    before_live, before_backup = _digest(live), _digest(backup)
    with pytest.raises(TenantDeploymentError) as exc:
        restore_backup(backup, target_db_path=live, verify_hash=False, verify_hmac=False)
    assert exc.value.code == TENANT_COUNT_INVALID
    assert _digest(live) == before_live
    assert _digest(backup) == before_backup


@pytest.mark.parametrize("configured_url", [False, True], ids=["ohne_database_url", "mit_database_url"])
@pytest.mark.parametrize("tenants", [1, 0])
def test_restore_accepts_single_or_empty_company_backup(single, monkeypatch, tmp_path, tenants, configured_url):
    from services.maintenance import restore_backup

    live = _db_with(tmp_path / "live.db", _tenant(DEFAULT_TENANT_ID, "main"))
    rows = (_tenant(DEFAULT_TENANT_ID, "main"),) if tenants else ()
    backup = _db_with(tmp_path / "eigen.db", *rows)
    if configured_url:
        # Konfigurierte DB mit zwei Firmen: wuerde sie statt des Ziels geprueft,
        # schluege die Nachpruefung faelschlich an.
        other = _db_with(tmp_path / "konfiguriert.db", _tenant(DEFAULT_TENANT_ID, "main"), _tenant("t-2", "zwei"))
        monkeypatch.setattr(settings, "database_url", f"sqlite:///{other.as_posix()}", raising=False)
    result = restore_backup(backup, target_db_path=live, verify_hash=False, verify_hmac=False)
    assert result["status"] == "ok"


def test_explicit_database_url_wins_only_when_passed(monkeypatch, tmp_path):
    from database import create_app_engine, sqlite_file_database_url

    configured = tmp_path / "konfiguriert.db"
    probe = tmp_path / "probe.db"
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{configured.as_posix()}", raising=False)
    explicit = create_app_engine(db_path=probe, database_url=sqlite_file_database_url(probe))
    implicit = create_app_engine(db_path=probe)  # Startup-Prioritaet unveraendert
    try:
        assert Path(explicit.url.database).resolve() == probe.resolve()
        assert Path(implicit.url.database).resolve() == configured.resolve()
    finally:
        explicit.dispose()
        implicit.dispose()


def test_startup_gate_checks_same_engine_as_init_db(single, monkeypatch, engine):
    """Ohne Argument prueft das Gate die Modul-Engine zur Aufrufzeit (wie init_db),
    nicht das beim Import gebundene SessionLocal."""
    import database as db_module

    _add(engine, _tenant(DEFAULT_TENANT_ID, "main"))
    monkeypatch.setattr(db_module, "engine", engine)
    enforce_deployment_mode_at_startup()
    _add(engine, _tenant("t-2", "zwei"))
    with pytest.raises(TenantDeploymentError) as exc:
        enforce_deployment_mode_at_startup()
    assert exc.value.code == TENANT_COUNT_INVALID
