"""Audit 2026-11 / 05, Paket T1: Migration d7f3b1a9c5e2.

Neue Tabellen ``product_sustainability_attributes`` und
``sustainability_exclusion_standards``: ORM, Alembic upgrade/downgrade/upgrade
(SQLite), Postgres-DDL offline (up und down, inkl. RLS-Policies),
create_all-Pfad (Desktop/SQLCipher) und DB-seitige Vier-Augen-/Unique-Regeln.
Kein Backfill: Seed-Werte auf ``products`` werden nicht uebernommen (T-E2).
"""
from __future__ import annotations

import io
import sqlite3
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base  # noqa: E402
from models.product_eligibility import (  # noqa: E402
    ProductSustainabilityAttribute,
    SustainabilityExclusionStandard,
)

REVISION = "d7f3b1a9c5e2"
DOWN_REVISION = "d4f7a9c2e1b6"
TABLES = ("product_sustainability_attributes", "sustainability_exclusion_standards")


def _alembic_cfg(db_url, output_buffer=None):
    from alembic.config import Config as AlembicConfig

    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"), output_buffer=output_buffer)
    cfg.set_main_option("sqlalchemy.url", db_url)
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return cfg


def _tables(db_path):
    with sqlite3.connect(str(db_path)) as conn:
        return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _indexes(db_path, table):
    with sqlite3.connect(str(db_path)) as conn:
        return {row[1] for row in conn.execute(f"PRAGMA index_list({table})")}


def test_revision_is_in_single_head_chain():
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_alembic_cfg("sqlite://"))
    heads = script.get_heads()
    assert len(heads) == 1, heads
    assert REVISION in {rev.revision for rev in script.walk_revisions("base", heads[0])}
    assert script.get_revision(REVISION).down_revision == DOWN_REVISION


def test_orm_declares_tables_with_source_and_four_eyes_columns():
    cols = ProductSustainabilityAttribute.__table__.columns
    for name in ("source_type", "source_reference", "as_of", "valid_until", "status", "created_by"):
        assert not cols[name].nullable, name
    for name in ("tenant_id", "revenue_threshold_bps", "measured_exposure_bps", "approved_by"):
        assert cols[name].nullable, name
    assert all(c.server_default is None for c in cols), "keine erfundenen DB-Defaults"
    assert not SustainabilityExclusionStandard.__table__.columns["tenant_id"].nullable


def test_alembic_upgrade_downgrade_upgrade_sqlite(tmp_path):
    from alembic import command

    db_path = tmp_path / "t1.db"
    cfg = _alembic_cfg(f"sqlite:///{db_path}")
    command.upgrade(cfg, DOWN_REVISION)
    assert not set(TABLES) & _tables(db_path)
    command.upgrade(cfg, REVISION)
    assert set(TABLES) <= _tables(db_path)
    assert {"ux_psa_active_tenant", "ux_psa_active_global"} <= _indexes(db_path, TABLES[0])
    command.downgrade(cfg, DOWN_REVISION)
    assert not set(TABLES) & _tables(db_path)
    command.upgrade(cfg, REVISION)
    assert set(TABLES) <= _tables(db_path)
    with sqlite3.connect(str(db_path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM product_sustainability_attributes").fetchone()[0] == 0


def test_alembic_postgres_ddl_up_and_down_with_rls():
    from alembic import command

    up = io.StringIO()
    command.upgrade(_alembic_cfg("postgresql://u:p@localhost/db", up), f"{DOWN_REVISION}:{REVISION}", sql=True)
    ddl = up.getvalue()
    for table in TABLES:
        assert f"CREATE TABLE {table}" in ddl, table
        assert f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY' in ddl, table
    assert 'CREATE POLICY tenant_reference_select ON "product_sustainability_attributes" FOR SELECT' in ddl
    assert "tenant_id IS NULL" in ddl.split('CREATE POLICY tenant_reference_select ON "product_sustainability_attributes"')[1].split(";")[0]
    for cmd in ("INSERT", "UPDATE", "DELETE"):
        stmt = ddl.split(f'CREATE POLICY tenant_reference_{cmd.lower()} ON "product_sustainability_attributes"')[1].split(";")[0]
        assert "IS NULL" not in stmt, cmd
    standards = ddl.split('CREATE POLICY tenant_isolation ON "sustainability_exclusion_standards"')[1].split(";")[0]
    assert "IS NULL" not in standards
    assert "CREATE UNIQUE INDEX ux_psa_active_global ON product_sustainability_attributes" in ddl
    assert "ck_psa_four_eyes" in ddl
    down = io.StringIO()
    command.downgrade(_alembic_cfg("postgresql://u:p@localhost/db", down), f"{REVISION}:{DOWN_REVISION}", sql=True)
    for table in TABLES:
        assert f"DROP TABLE {table}" in down.getvalue(), table


def test_runtime_rls_classifies_attributes_as_reference_and_standards_strict():
    from services.postgres_rls import is_global_reference_table, rls_policy_sql

    assert is_global_reference_table("product_sustainability_attributes")
    assert not is_global_reference_table("sustainability_exclusion_standards")
    strict = " ;; ".join(rls_policy_sql("sustainability_exclusion_standards"))
    assert "CREATE POLICY tenant_isolation" in strict and "IS NULL" not in strict


@pytest.fixture()
def sqlite_conn(tmp_path):
    """create_all-Pfad der Desktop-Installation (SQLite/SQLCipher)."""
    engine = create_engine(f"sqlite:///{tmp_path / 'create_all.db'}")
    Base.metadata.create_all(bind=engine)
    engine.dispose()
    conn = sqlite3.connect(str(tmp_path / "create_all.db"))
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        yield conn
    finally:
        conn.close()


_INSERT = (
    "INSERT INTO product_sustainability_attributes (id, product_id, tenant_id, category, kind, "
    "revenue_threshold_bps, source_type, source_reference, as_of, valid_until, status, created_by, "
    "created_at, approved_by, approval_mode, updated_at) VALUES "
    "(?, 'p1', ?, 'tobacco', 'exclusion_policy', 500, 'kid', 'KID S. 2', ?, '2027-06-30', ?, 'u1', 'x', ?, ?, 'x')"
)


def test_create_all_db_rejects_self_approval_without_attestation(sqlite_conn):
    with pytest.raises(sqlite3.IntegrityError):
        sqlite_conn.execute(_INSERT, ("a1", None, "2026-06-30", "approved", "u1", "four_eyes"))
    sqlite_conn.execute(_INSERT, ("a2", None, "2026-06-30", "approved", "u2", "four_eyes"))
    sqlite_conn.execute(_INSERT, ("a3", "t1", "2026-05-31", "approved", "u1", "single_approver_attested"))


def test_create_all_db_unique_per_tenant_and_global_but_not_for_retired(sqlite_conn):
    sqlite_conn.execute(_INSERT, ("g1", None, "2026-06-30", "draft", None, None))
    with pytest.raises(sqlite3.IntegrityError):
        sqlite_conn.execute(_INSERT, ("g2", None, "2026-06-30", "draft", None, None))
    sqlite_conn.execute(_INSERT, ("t1", "t-a", "2026-06-30", "draft", None, None))
    sqlite_conn.execute(_INSERT, ("t2", "t-b", "2026-06-30", "draft", None, None))
    with pytest.raises(sqlite3.IntegrityError):
        sqlite_conn.execute(_INSERT, ("t3", "t-a", "2026-06-30", "draft", None, None))
    sqlite_conn.execute(_INSERT, ("g3", None, "2026-06-30", "retired", None, None))


def test_create_all_db_rejects_out_of_range_threshold_and_inverted_validity(sqlite_conn):
    with pytest.raises(sqlite3.IntegrityError):
        sqlite_conn.execute(_INSERT.replace("500, 'kid'", "10001, 'kid'"), ("x1", None, "2026-06-30", "draft", None, None))
    with pytest.raises(sqlite3.IntegrityError):
        sqlite_conn.execute(_INSERT, ("x2", None, "2027-07-01", "draft", None, None))
