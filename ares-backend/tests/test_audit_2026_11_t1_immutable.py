"""Audit 2026-11 / 05, T1, Pruefrunde #863 H-6: freigegebene Nachweise sind in
der DB unveraenderlich (Migration a3e7c9d1f5b4 und create_all-Pfad).
Postgres live: tests/test_postgres_rls_global_reference_rows.py."""
from __future__ import annotations

import importlib.util
import io
import sqlite3
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import models.product_eligibility as model  # noqa: E402
from database import Base  # noqa: E402

REVISION = "a3e7c9d1f5b4"
DOWN_REVISION = "f2d6b8c0e4a3"
MIGRATION = BACKEND_ROOT / "alembic" / "versions" / "a3e7c9d1f5b4_sustainability_attributes_immutable.py"

_INSERT = (
    "INSERT INTO product_sustainability_attributes (id, product_id, category, kind, revenue_threshold_bps, "
    "source_type, source_reference, as_of, valid_until, status, created_by, created_at, approved_by, "
    "approval_mode, updated_at) VALUES (?, 'p1', 'tobacco', 'exclusion_policy', 500, 'kid', 'KID', "
    "'2026-06-30', '2027-06-30', ?, 'u1', 'x', ?, ?, 'x')"
)


def _migration():
    spec = importlib.util.spec_from_file_location("_psa_immutable", MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _cfg(url, buf=None):
    from alembic.config import Config

    cfg = Config(str(BACKEND_ROOT / "alembic.ini"), output_buffer=buf)
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return cfg


def test_frozen_migration_matches_model():
    mod = _migration()
    assert mod.IMMUTABLE_COLUMNS == model.SUSTAINABILITY_ATTRIBUTE_IMMUTABLE_COLUMNS
    assert mod.SQLITE_TRIGGERS == model.SUSTAINABILITY_ATTRIBUTE_SQLITE_TRIGGERS
    all_columns = {c.name for c in model.ProductSustainabilityAttribute.__table__.columns}
    assert all_columns == set(mod.IMMUTABLE_COLUMNS) | set(model.SUSTAINABILITY_ATTRIBUTE_MUTABLE_ON_RETIRE)


def _seed(conn):
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute(_INSERT, ("draft", "draft", None, None))
    conn.execute(_INSERT.replace("'2026-06-30'", "'2026-05-31'"), ("appr", "approved", "u2", "four_eyes"))
    conn.execute(_INSERT.replace("'2026-06-30'", "'2026-04-30'"), ("ret", "retired", "u2", "four_eyes"))


def _assert_rules(conn):
    # Entwurf: frei aenderbar und loeschbar
    conn.execute("UPDATE product_sustainability_attributes SET revenue_threshold_bps = 0 WHERE id = 'draft'")
    conn.execute("UPDATE product_sustainability_attributes SET status = 'approved', approved_by = 'u2', "
                 "approval_mode = 'four_eyes' WHERE id = 'draft'")
    # Freigegeben: Inhalt, Gueltigkeit, Freigeber unveraenderlich
    for stmt in (
        "UPDATE product_sustainability_attributes SET revenue_threshold_bps = 0 WHERE id = 'appr'",
        "UPDATE product_sustainability_attributes SET valid_until = '2099-01-01' WHERE id = 'appr'",
        "UPDATE product_sustainability_attributes SET approved_by = 'u3' WHERE id = 'appr'",
        "UPDATE product_sustainability_attributes SET status = 'draft' WHERE id = 'appr'",
        "UPDATE product_sustainability_attributes SET status = 'retired', source_reference = 'neu' WHERE id = 'appr'",
        "UPDATE product_sustainability_attributes SET status = 'approved' WHERE id = 'ret'",
        "UPDATE product_sustainability_attributes SET note = 'x' WHERE id = 'ret'",
        "DELETE FROM product_sustainability_attributes WHERE id = 'appr'",
        "DELETE FROM product_sustainability_attributes WHERE id = 'ret'",
    ):
        with pytest.raises(sqlite3.DatabaseError, match="unveraenderlich"):
            conn.execute(stmt)
    # Erlaubt: approved -> retired mit retired_by/retired_at/updated_at
    conn.execute("UPDATE product_sustainability_attributes SET status = 'retired', retired_by = 'u3', "
                 "retired_at = 'y', updated_at = 'y' WHERE id = 'appr'")
    conn.execute(_INSERT.replace("'2026-06-30'", "'2026-03-31'"), ("draft2", "draft", None, None))
    conn.execute("DELETE FROM product_sustainability_attributes WHERE id = 'draft2'")


def test_create_all_path_enforces_immutability(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'ca.db'}")
    Base.metadata.create_all(bind=engine)
    engine.dispose()
    with sqlite3.connect(str(tmp_path / "ca.db")) as conn:
        _seed(conn)
        _assert_rules(conn)


def test_alembic_upgrade_downgrade_upgrade_sqlite(tmp_path):
    from alembic import command

    db = tmp_path / "al.db"
    cfg = _cfg(f"sqlite:///{db}")
    command.upgrade(cfg, DOWN_REVISION)
    with sqlite3.connect(str(db)) as conn:
        _seed(conn)
        conn.execute("UPDATE product_sustainability_attributes SET note = 'vorher erlaubt' WHERE id = 'appr'")
    command.upgrade(cfg, REVISION)
    with sqlite3.connect(str(db)) as conn:
        with pytest.raises(sqlite3.DatabaseError, match="unveraenderlich"):
            conn.execute("UPDATE product_sustainability_attributes SET note = 'x' WHERE id = 'appr'")
    command.downgrade(cfg, DOWN_REVISION)
    with sqlite3.connect(str(db)) as conn:
        conn.execute("UPDATE product_sustainability_attributes SET note = 'nach downgrade' WHERE id = 'appr'")
    command.upgrade(cfg, REVISION)
    with sqlite3.connect(str(db)) as conn:
        with pytest.raises(sqlite3.DatabaseError, match="unveraenderlich"):
            conn.execute("DELETE FROM product_sustainability_attributes WHERE id = 'appr'")


def test_postgres_ddl_offline():
    from alembic import command

    up = io.StringIO()
    command.upgrade(_cfg("postgresql://u:p@localhost/db", up), f"{DOWN_REVISION}:{REVISION}", sql=True)
    ddl = up.getvalue()
    assert "CREATE OR REPLACE FUNCTION product_sustainability_attributes_immutable()" in ddl
    assert "BEFORE UPDATE OR DELETE ON product_sustainability_attributes" in ddl
    assert "NEW.valid_until IS NOT DISTINCT FROM OLD.valid_until" in ddl
    assert "NEW.status IS NOT DISTINCT FROM" not in ddl
    down = io.StringIO()
    command.downgrade(_cfg("postgresql://u:p@localhost/db", down), f"{REVISION}:{DOWN_REVISION}", sql=True)
    assert "DROP FUNCTION IF EXISTS product_sustainability_attributes_immutable()" in down.getvalue()
