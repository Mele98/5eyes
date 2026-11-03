"""Audit 2026-11, Paket P1: Migration a8d3c5e7f9b1 (Produkt-Stammdaten).

ORM, Alembic upgrade/downgrade/upgrade (SQLite), Postgres-DDL (offline, up und
down) und SQLite-Runtime-Patch. Kettenbasiert. Keine server_defaults: der
Bestand bleibt "nicht erfasst".
"""
from __future__ import annotations

import io
import sqlite3
import sys
from pathlib import Path

from sqlalchemy import create_engine

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from models.review import Product  # noqa: E402

REVISION = "a8d3c5e7f9b1"
DOWN_REVISION = "f6a2c8e4b1d7"
NEW_COLUMNS = (
    "domicile", "is_hedged", "hedge_currency", "ter_source", "ter_as_of",
    "retrocession_bps", "retrocession_source", "is_house_product",
    "distribution_policy", "valor", "minimum_investment_minor_units",
)


# ---------------------------------------------------------------------------
# 6. Migration a8d3c5e7f9b1 (SQLite + Postgres-DDL + Runtime-Patch)
# ---------------------------------------------------------------------------


def _alembic_cfg(db_url, output_buffer=None):
    from alembic.config import Config as AlembicConfig

    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"), output_buffer=output_buffer)
    cfg.set_main_option("sqlalchemy.url", db_url)
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return cfg


def _columns(db_path, table="products"):
    with sqlite3.connect(str(db_path)) as conn:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def test_orm_declares_nullable_master_data_columns():
    columns = Product.__table__.columns
    for name in NEW_COLUMNS:
        assert name in columns, name
        assert columns[name].nullable, name
        assert columns[name].server_default is None, name


def test_revision_is_in_single_head_chain():
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_alembic_cfg("sqlite://"))
    heads = script.get_heads()
    assert len(heads) == 1, heads
    chain = {rev.revision for rev in script.walk_revisions("base", heads[0])}
    assert REVISION in chain
    assert script.get_revision(REVISION).down_revision == DOWN_REVISION


def test_alembic_upgrade_downgrade_upgrade_sqlite(tmp_path):
    from alembic import command

    db_path = tmp_path / "p1.db"
    cfg = _alembic_cfg(f"sqlite:///{db_path}")
    command.upgrade(cfg, DOWN_REVISION)
    assert not set(NEW_COLUMNS) & _columns(db_path)
    command.upgrade(cfg, REVISION)
    assert set(NEW_COLUMNS) <= _columns(db_path)
    command.downgrade(cfg, DOWN_REVISION)
    assert not set(NEW_COLUMNS) & _columns(db_path)
    command.upgrade(cfg, REVISION)
    assert set(NEW_COLUMNS) <= _columns(db_path)


def test_alembic_revision_postgres_ddl_up_and_down():
    from alembic import command

    up = io.StringIO()
    command.upgrade(_alembic_cfg("postgresql://u:p@localhost/db", up), f"{DOWN_REVISION}:{REVISION}", sql=True)
    for name in NEW_COLUMNS:
        assert f"ALTER TABLE products ADD COLUMN {name}" in up.getvalue(), name
    assert "BIGINT" in up.getvalue()
    assert "DEFAULT" not in up.getvalue().split("ALTER TABLE products ADD COLUMN domicile")[1].split(";")[0]
    down = io.StringIO()
    command.downgrade(_alembic_cfg("postgresql://u:p@localhost/db", down), f"{REVISION}:{DOWN_REVISION}", sql=True)
    for name in NEW_COLUMNS:
        assert f"ALTER TABLE products DROP COLUMN {name}" in down.getvalue(), name


def test_runtime_patch_adds_columns_to_bootstrapped_sqlite(tmp_path, monkeypatch):
    import database as db_module

    db_path = tmp_path / "runtime.db"
    db_module.bootstrap_sqlite_schema(db_path=db_path, schema_path=BACKEND_ROOT / "ares_schema.sql")
    test_engine = create_engine(f"sqlite:///{db_path}")
    monkeypatch.setattr(db_module, "engine", test_engine)
    db_module.ensure_runtime_columns()
    db_module.ensure_runtime_columns()  # idempotent
    test_engine.dispose()
    assert set(NEW_COLUMNS) <= _columns(db_path)


