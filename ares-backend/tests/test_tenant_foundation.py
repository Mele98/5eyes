"""Sprint T1 (2026-06-08): Tenant-Model + Foundation Tests.

Verifiziert:
1. Tenant-Model laesst sich anlegen/abfragen
2. ensure_default_tenant() ist idempotent
3. tenant_id-Columns existieren auf User/Client/Mandate (nullable)
4. Tier-Konstanten + License-Status sind exportiert
5. Settings deployment_tier / tenancy_mode / tenant_admin_ui_enabled
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base
# Import alle Models damit SQLAlchemy alle Beziehungen aufloesen kann
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
from models.tenant import (
    ALLOWED_LICENSE_STATUS,
    ALLOWED_TIERS,
    DEFAULT_TENANT_ID,
    LICENSE_STATUS_ACTIVE,
    LICENSE_STATUS_EXPIRED,
    LICENSE_STATUS_SUSPENDED,
    LICENSE_STATUS_TRIAL,
    TIER_1_SELF_HOSTED,
    TIER_2_SHARED_CLOUD,
    TIER_3_DEDICATED,
    Tenant,
)


def _utc_now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'tenant_foundation.db'}",
        connect_args={"check_same_thread": False},
    )
    sf = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield sf, engine
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


# ===========================================================================
# 1. Tier-Konstanten + License-Status
# ===========================================================================


def test_tier_constants_definiert():
    assert TIER_1_SELF_HOSTED == "tier1"
    assert TIER_2_SHARED_CLOUD == "tier2"
    assert TIER_3_DEDICATED == "tier3"
    assert ALLOWED_TIERS == (TIER_1_SELF_HOSTED, TIER_2_SHARED_CLOUD, TIER_3_DEDICATED)


def test_license_status_constants_definiert():
    assert LICENSE_STATUS_TRIAL == "trial"
    assert LICENSE_STATUS_ACTIVE == "active"
    assert LICENSE_STATUS_SUSPENDED == "suspended"
    assert LICENSE_STATUS_EXPIRED == "expired"
    assert len(ALLOWED_LICENSE_STATUS) == 4


def test_default_tenant_id_konstante():
    assert DEFAULT_TENANT_ID == "main"


# ===========================================================================
# 2. Tenant-Model
# ===========================================================================


def test_tenant_anlegbar_minimal(session_factory):
    sf, _ = session_factory
    now = _utc_now()
    with sf() as db:
        t = Tenant(
            id="t-1", display_name="Test AG", slug="test-ag",
            hosting_tier=TIER_1_SELF_HOSTED,
            license_status=LICENSE_STATUS_ACTIVE,
            max_users=5, is_active=1,
            created_at=now, updated_at=now,
        )
        db.add(t)
        db.commit()
        db.refresh(t)
        assert t.id == "t-1"
        assert t.hosting_tier == "tier1"
        assert t.license_status == "active"
        assert t.max_users == 5


def test_tenant_slug_unique(session_factory):
    sf, _ = session_factory
    now = _utc_now()
    with sf() as db:
        t1 = Tenant(
            id="t-1", display_name="A", slug="duplicate",
            hosting_tier=TIER_1_SELF_HOSTED,
            license_status=LICENSE_STATUS_ACTIVE,
            max_users=1, is_active=1, created_at=now, updated_at=now,
        )
        t2 = Tenant(
            id="t-2", display_name="B", slug="duplicate",
            hosting_tier=TIER_2_SHARED_CLOUD,
            license_status=LICENSE_STATUS_TRIAL,
            max_users=10, is_active=1, created_at=now, updated_at=now,
        )
        db.add(t1)
        db.commit()
        db.add(t2)
        with pytest.raises(Exception):  # IntegrityError
            db.commit()


def test_tenant_alle_felder_setzbar(session_factory):
    sf, _ = session_factory
    now = _utc_now()
    with sf() as db:
        t = Tenant(
            id="t-full", display_name="Full Test",
            slug="full",
            hosting_tier=TIER_3_DEDICATED,
            license_status=LICENSE_STATUS_TRIAL,
            license_valid_until="2026-12-31",
            finma_outsourcing_notified_at="2026-06-08",
            avv_signed_at="2026-06-08",
            max_users=50, max_mandates=200, storage_quota_mb=10000,
            is_active=1, created_at=now, updated_at=now,
        )
        db.add(t)
        db.commit()
        db.refresh(t)
        assert t.hosting_tier == "tier3"
        assert t.max_mandates == 200
        assert t.storage_quota_mb == 10000


# ===========================================================================
# 3. tenant_id-Columns auf existierenden Models (nullable, BC)
# ===========================================================================


def test_user_hat_tenant_id_column(session_factory):
    _, engine = session_factory
    insp = inspect(engine)
    cols = [c["name"] for c in insp.get_columns("users")]
    assert "tenant_id" in cols
    # NULLABLE fuer Backwards-Compat
    tenant_col = next(c for c in insp.get_columns("users") if c["name"] == "tenant_id")
    assert tenant_col["nullable"] is True


def test_client_hat_tenant_id_column(session_factory):
    _, engine = session_factory
    insp = inspect(engine)
    cols = [c["name"] for c in insp.get_columns("clients")]
    assert "tenant_id" in cols
    tenant_col = next(c for c in insp.get_columns("clients") if c["name"] == "tenant_id")
    assert tenant_col["nullable"] is True


def test_mandate_hat_tenant_id_column(session_factory):
    _, engine = session_factory
    insp = inspect(engine)
    cols = [c["name"] for c in insp.get_columns("mandates")]
    assert "tenant_id" in cols


# ===========================================================================
# 4. ensure_default_tenant idempotent
# ===========================================================================


def test_ensure_default_tenant_idempotent(monkeypatch, tmp_path):
    """Zwei Aufrufe von ensure_default_tenant → genau ein 'main'-Eintrag."""
    # Test verwendet eine fresh SQLite-DB via temp-path
    import database as db_mod
    fresh_engine = create_engine(
        f"sqlite:///{tmp_path / 'idem.db'}",
        connect_args={"check_same_thread": False},
    )
    fresh_sf = sessionmaker(autocommit=False, autoflush=False, bind=fresh_engine)
    Base.metadata.create_all(bind=fresh_engine)
    monkeypatch.setattr(db_mod, "SessionLocal", fresh_sf, raising=False)

    db_mod.ensure_default_tenant()
    db_mod.ensure_default_tenant()
    db_mod.ensure_default_tenant()

    with fresh_sf() as db:
        count = db.query(Tenant).filter(Tenant.id == DEFAULT_TENANT_ID).count()
        assert count == 1
    fresh_engine.dispose()


def test_ensure_default_tenant_legt_main_an(monkeypatch, tmp_path):
    import database as db_mod
    fresh_engine = create_engine(
        f"sqlite:///{tmp_path / 'main.db'}",
        connect_args={"check_same_thread": False},
    )
    fresh_sf = sessionmaker(autocommit=False, autoflush=False, bind=fresh_engine)
    Base.metadata.create_all(bind=fresh_engine)
    monkeypatch.setattr(db_mod, "SessionLocal", fresh_sf, raising=False)

    db_mod.ensure_default_tenant()

    with fresh_sf() as db:
        main = db.query(Tenant).filter(Tenant.id == DEFAULT_TENANT_ID).first()
        assert main is not None
        assert main.display_name == "Default Tenant"
        assert main.slug == "main"
        assert main.license_status == "active"
    fresh_engine.dispose()


def test_ensure_default_tenant_defensive_bei_db_error(monkeypatch):
    """Bei DB-Crash darf der Boot NICHT abbrechen."""
    import database as db_mod

    class BrokenSessionLocal:
        def __call__(self):
            raise RuntimeError("DB unavailable")

    monkeypatch.setattr(db_mod, "SessionLocal", BrokenSessionLocal(), raising=False)
    # Sollte NICHT raisen
    db_mod.ensure_default_tenant()


# ===========================================================================
# 5. Settings-Erweiterung
# ===========================================================================


def test_settings_deployment_tier_default():
    from config import settings
    assert hasattr(settings, "deployment_tier")
    assert settings.deployment_tier in ALLOWED_TIERS


def test_settings_tenancy_mode_default():
    from config import settings
    assert hasattr(settings, "tenancy_mode")
    assert settings.tenancy_mode in ("single", "multi")


def test_settings_tenant_admin_ui_default():
    from config import settings
    assert hasattr(settings, "tenant_admin_ui_enabled")
    assert isinstance(settings.tenant_admin_ui_enabled, bool)
