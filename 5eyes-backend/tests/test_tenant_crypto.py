from __future__ import annotations

import datetime
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

pytest.importorskip("cryptography.fernet")

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base  # noqa: E402
import models.tenant  # noqa: F401,E402
from models.tenant import Tenant  # noqa: E402
from services.tenant_crypto import (  # noqa: E402
    TenantCryptoError,
    decrypt_for_tenant,
    encrypt_for_tenant,
    get_tenant_dek,
    rotate_tenant_dek,
)


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'tenant-crypto.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield Session, engine
    finally:
        engine.dispose()


def _seed_tenant(db, tenant_id="firm-A"):
    tenant = Tenant(
        id=tenant_id,
        display_name="Firm A",
        slug=tenant_id.lower(),
        hosting_tier="tier2",
        license_status="active",
        max_users=10,
        is_active=1,
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(tenant)
    db.commit()
    return tenant


def test_tenant_model_has_dek_columns(session_factory):
    _, engine = session_factory
    cols = {c["name"] for c in inspect(engine).get_columns("tenants")}
    assert {"encrypted_dek", "dek_version", "dek_rotated_at"}.issubset(cols)


def test_get_tenant_dek_creates_encrypted_dek_and_roundtrip(session_factory):
    Session, _ = session_factory
    with Session() as db:
        tenant = _seed_tenant(db)
        dek = get_tenant_dek(db, tenant.id, master_kek="master-one")
        assert isinstance(dek, bytes)
        assert tenant.encrypted_dek
        assert tenant.encrypted_dek.encode("utf-8") != dek
        token = encrypt_for_tenant(db, tenant.id, b"PII payload", master_kek="master-one")
        assert decrypt_for_tenant(db, tenant.id, token, master_kek="master-one") == b"PII payload"


def test_wrong_master_kek_fails_to_decrypt_dek(session_factory):
    Session, _ = session_factory
    with Session() as db:
        tenant = _seed_tenant(db)
        get_tenant_dek(db, tenant.id, master_kek="right-master")
        db.commit()
        with pytest.raises(TenantCryptoError):
            get_tenant_dek(db, tenant.id, master_kek="wrong-master")


def test_rotate_tenant_dek_increments_version_and_replaces_key(session_factory):
    Session, _ = session_factory
    with Session() as db:
        tenant = _seed_tenant(db)
        old_dek = get_tenant_dek(db, tenant.id, master_kek="master-one")
        old_encrypted = tenant.encrypted_dek
        new_dek = rotate_tenant_dek(db, tenant.id, master_kek="master-one")
        assert new_dek != old_dek
        assert tenant.encrypted_dek != old_encrypted
        assert tenant.dek_version == 2
