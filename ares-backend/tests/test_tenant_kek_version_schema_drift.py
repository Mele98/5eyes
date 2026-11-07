"""AF-5: Schema-Drift-Tests fuer ``tenants.kek_version``.

``kek_version`` haelt die Generation der Master-KEK, unter der
``tenants.encrypted_dek`` verpackt ist. Vertrag: ``INTEGER NOT NULL DEFAULT 1``
auf allen Pfaden (ORM/create_all, frischer SQLite-Bootstrap, Runtime-Patch fuer
Bestands-DBs, Alembic). Der Spalten-Default bleibt 1 (Generation des
Bestands); neu verpackte DEKs schreibt das Produkt seit W4-c mit 2.
"""
from __future__ import annotations

import datetime
import sqlite3
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base  # noqa: E402
from main import app  # noqa: F401,E402  (registriert alle Models)
from models.tenant import Tenant  # noqa: E402

KEK_VERSION_REVISION = "2cbc77503cd9"
KEK_VERSION_DOWN_REVISION = "e2b7c4f9a1d6"


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


def _kek_column(db_path: Path):
    """(type, notnull, default) der Spalte oder None."""
    with sqlite3.connect(str(db_path)) as conn:
        for _cid, name, col_type, notnull, dflt, _pk in conn.execute(
            "PRAGMA table_info(tenants)"
        ):
            if name == "kek_version":
                return (col_type.upper(), int(notnull), str(dflt).strip("'\""))
    return None


EXPECTED = ("INTEGER", 1, "1")


def _insert_raw_tenant(db_path: Path, tenant_id: str) -> None:
    # Roh-INSERT ohne kek_version -> DB-Default muss greifen.
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            "INSERT INTO tenants (id, display_name, slug, hosting_tier, "
            "license_status, max_users, is_active, default_retrocession_reimbursement, "
            "discretionary_management_licensed, created_at, updated_at) "
            "VALUES (?, 'Raw', ?, 'tier1', 'active', 1, 1, 0, 1, ?, ?)",
            (tenant_id, tenant_id, _now(), _now()),
        )
        conn.commit()


def _kek_value(db_path: Path, tenant_id: str):
    with sqlite3.connect(str(db_path)) as conn:
        return conn.execute(
            "SELECT kek_version FROM tenants WHERE id = ?", (tenant_id,)
        ).fetchone()[0]


def test_orm_declares_kek_version_not_null_default_1():
    col = Tenant.__table__.columns["kek_version"]
    assert col.nullable is False
    assert col.default.arg == 1
    assert str(col.server_default.arg) == "1"


def test_create_all_and_fresh_bootstrap_have_kek_version(tmp_path):
    # Frische Installation: Bootstrap-SQL + create_all (tenants wird vom ORM
    # angelegt; das Bootstrap-SQL enthaelt keine tenants-Tabelle).
    import database as db_module

    fresh = tmp_path / "fresh.db"
    schema = db_module.resolve_schema_path()
    assert schema is not None and schema.exists()
    db_module.bootstrap_sqlite_schema(db_path=fresh, schema_path=schema)
    engine = create_engine(f"sqlite:///{fresh}")
    Base.metadata.create_all(bind=engine)
    engine.dispose()
    assert _kek_column(fresh) == EXPECTED
    _insert_raw_tenant(fresh, "raw-new")
    assert _kek_value(fresh, "raw-new") == 1


def test_runtime_patch_adds_kek_version_with_default_1_for_existing_rows(
    tmp_path, monkeypatch
):
    import database as db_module

    legacy = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{legacy}")
    Base.metadata.create_all(bind=engine)
    engine.dispose()
    # Bestands-DB vor AF-5 simulieren: Spalte entfernen, Zeile anlegen.
    with sqlite3.connect(str(legacy)) as conn:
        conn.execute("ALTER TABLE tenants DROP COLUMN kek_version")
        conn.commit()
    assert _kek_column(legacy) is None
    _insert_raw_tenant(legacy, "existing")

    engine = create_engine(f"sqlite:///{legacy}")
    monkeypatch.setattr(db_module, "engine", engine)
    db_module.ensure_runtime_columns()
    db_module.ensure_runtime_columns()  # idempotent
    engine.dispose()

    assert _kek_column(legacy) == EXPECTED
    assert _kek_value(legacy, "existing") == 1
    _insert_raw_tenant(legacy, "after-patch")
    assert _kek_value(legacy, "after-patch") == 1


def _alembic_cfg(db_url):
    from alembic.config import Config as AlembicConfig

    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return cfg


def test_alembic_kek_version_revision_in_chain_upgrade_and_downgrade(tmp_path):
    from alembic import command
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_alembic_cfg("sqlite://"))
    heads = script.get_heads()
    assert len(heads) == 1, heads
    chain = {rev.revision for rev in script.walk_revisions("base", heads[0])}
    assert KEK_VERSION_REVISION in chain
    assert (
        script.get_revision(KEK_VERSION_REVISION).down_revision
        == KEK_VERSION_DOWN_REVISION
    )

    db_path = tmp_path / "alembic.db"
    cfg = _alembic_cfg(f"sqlite:///{db_path}")
    command.upgrade(cfg, KEK_VERSION_DOWN_REVISION)
    assert _kek_column(db_path) is None
    _insert_raw_tenant(db_path, "pre-existing")

    command.upgrade(cfg, KEK_VERSION_REVISION)
    assert _kek_column(db_path) == EXPECTED
    assert _kek_value(db_path, "pre-existing") == 1
    _insert_raw_tenant(db_path, "post-upgrade")
    assert _kek_value(db_path, "post-upgrade") == 1

    command.downgrade(cfg, KEK_VERSION_DOWN_REVISION)
    assert _kek_column(db_path) is None


@pytest.fixture
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'kek-version.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    try:
        yield sessionmaker(bind=engine, expire_on_commit=False)
    finally:
        engine.dispose()


def test_new_dek_is_stored_with_current_kek_version_2(session_factory):
    pytest.importorskip("cryptography.fernet")
    from services.tenant_crypto import get_tenant_dek, rotate_tenant_dek

    Session = session_factory
    with Session() as db:
        db.add(
            Tenant(
                id="kv-firm",
                display_name="KV",
                slug="kv-firm",
                hosting_tier="tier2",
                license_status="active",
                max_users=1,
                is_active=1,
                created_at=_now(),
                updated_at=_now(),
            )
        )
        db.commit()
        get_tenant_dek(db, "kv-firm", master_kek="kv-test-master")
        assert db.execute(
            text("SELECT kek_version FROM tenants WHERE id = 'kv-firm'")
        ).scalar_one() == 2
        rotate_tenant_dek(db, "kv-firm", master_kek="kv-test-master")
        db.commit()
        assert db.get(Tenant, "kv-firm").kek_version == 2
