"""Audit 2026-11 / 05, T1, Pruefrunde #863 H-1: Migration e1c5a7b9d3f2
(Hausstandard versioniert). SQLite upgrade/downgrade/upgrade mit Bestand,
Postgres-DDL offline, Vier-Augen-CHECK und partielle Unique-Indizes."""
from __future__ import annotations

import io
import sqlite3
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

REVISION = "e1c5a7b9d3f2"
DOWN_REVISION = "d7f3b1a9c5e2"
TABLE = "sustainability_exclusion_standards"
NEW_COLUMNS = {"is_disabled", "status", "created_by", "approved_by", "approved_at",
               "approval_mode", "valid_from", "valid_to"}


def _cfg(url, buf=None):
    from alembic.config import Config

    cfg = Config(str(BACKEND_ROOT / "alembic.ini"), output_buffer=buf)
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return cfg


def _columns(db):
    with sqlite3.connect(str(db)) as conn:
        return {r[1] for r in conn.execute(f"PRAGMA table_info({TABLE})")}


def _indexes(db):
    with sqlite3.connect(str(db)) as conn:
        return {r[1] for r in conn.execute(f"PRAGMA index_list({TABLE})")}


def test_chain():
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_cfg("sqlite://"))
    assert len(script.get_heads()) == 1
    assert script.get_revision(REVISION).down_revision == DOWN_REVISION


def test_upgrade_downgrade_upgrade_sqlite_keeps_existing_value(tmp_path):
    from alembic import command

    db = tmp_path / "ses.db"
    cfg = _cfg(f"sqlite:///{db}")
    command.upgrade(cfg, DOWN_REVISION)
    with sqlite3.connect(str(db)) as conn:
        conn.execute(f"INSERT INTO {TABLE} (id, tenant_id, category, max_revenue_threshold_bps, updated_by, "
                     "created_at, updated_at) VALUES ('s1', 't', 'tobacco', 0, 'u1', 'x', '2026-11-01')")
    command.upgrade(cfg, REVISION)
    assert NEW_COLUMNS <= _columns(db)
    assert {"ux_ses_tenant_category_current", "ux_ses_tenant_category_pending"} <= _indexes(db)
    with sqlite3.connect(str(db)) as conn:
        row = conn.execute(f"SELECT status, is_disabled, valid_from, approval_mode, approved_by FROM {TABLE}").fetchone()
        assert row == ("approved", 0, "2026-11-01", "pre_versioning", "u1")
        # Vier-Augen-CHECK: Lockerung durch den Ersteller selbst ohne Ausnahme-Modus
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(f"INSERT INTO {TABLE} (id, tenant_id, category, max_revenue_threshold_bps, updated_by, "
                         "created_by, approved_by, approval_mode, status, created_at, updated_at) VALUES "
                         "('s2', 't', 'alcohol', 5000, 'u1', 'u1', 'u1', 'four_eyes', 'approved', 'x', 'x')")
        # Zweite aktuelle Version derselben Kategorie -> Unique-Verletzung
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(f"INSERT INTO {TABLE} (id, tenant_id, category, max_revenue_threshold_bps, updated_by, "
                         "status, created_at, updated_at) VALUES ('s3', 't', 'tobacco', 100, 'u1', 'approved', 'x', 'x')")
        conn.execute(f"INSERT INTO {TABLE} (id, tenant_id, category, max_revenue_threshold_bps, updated_by, "
                     "status, valid_to, created_at, updated_at) VALUES "
                     "('s4', 't', 'tobacco', 100, 'u1', 'retired', '2026-10-01', 'x', 'x')")
    command.downgrade(cfg, DOWN_REVISION)
    assert not NEW_COLUMNS & _columns(db)
    assert "ux_ses_tenant_category" in _indexes(db)
    with sqlite3.connect(str(db)) as conn:
        assert conn.execute(f"SELECT id FROM {TABLE}").fetchall() == [("s1",)]
    command.upgrade(cfg, REVISION)
    assert NEW_COLUMNS <= _columns(db)


def test_postgres_ddl_up_and_down():
    from alembic import command

    up = io.StringIO()
    command.upgrade(_cfg("postgresql://u:p@localhost/db", up), f"{DOWN_REVISION}:{REVISION}", sql=True)
    ddl = up.getvalue()
    assert "ADD COLUMN status VARCHAR DEFAULT 'approved' NOT NULL" in ddl
    assert "ck_ses_four_eyes" in ddl
    assert "CREATE UNIQUE INDEX ux_ses_tenant_category_current" in ddl and "WHERE status = 'approved' AND valid_to IS NULL" in ddl
    assert "ROW LEVEL SECURITY" not in ddl and "DROP POLICY" not in ddl, "RLS-Policy bleibt unberuehrt"
    down = io.StringIO()
    command.downgrade(_cfg("postgresql://u:p@localhost/db", down), f"{REVISION}:{DOWN_REVISION}", sql=True)
    assert "DROP COLUMN status" in down.getvalue()
    assert "CREATE UNIQUE INDEX ux_ses_tenant_category ON" in down.getvalue()
