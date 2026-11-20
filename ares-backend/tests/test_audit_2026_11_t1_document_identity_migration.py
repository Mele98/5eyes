"""Audit 2026-11 / 05, T1, Pruefrunde #863 (FINMA 9b/9c): Migration
f2d6b8c0e4a3 -- Dokumentidentitaet und neutrale Kunden-Quellbezeichnung."""
from __future__ import annotations

import io
import sqlite3
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from models.product_eligibility import ProductSustainabilityAttribute  # noqa: E402

REVISION = "f2d6b8c0e4a3"
DOWN_REVISION = "e1c5a7b9d3f2"
COLUMNS = {"source_document_title", "source_document_version", "source_document_date",
           "source_document_sha256", "client_source_label"}


def _cfg(url, buf=None):
    from alembic.config import Config

    cfg = Config(str(BACKEND_ROOT / "alembic.ini"), output_buffer=buf)
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return cfg


def _columns(db):
    with sqlite3.connect(str(db)) as conn:
        return {r[1] for r in conn.execute("PRAGMA table_info(product_sustainability_attributes)")}


def test_orm_and_chain():
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_cfg("sqlite://"))
    assert script.get_revision(REVISION).down_revision == DOWN_REVISION
    cols = ProductSustainabilityAttribute.__table__.columns
    for name in COLUMNS:
        assert cols[name].nullable and cols[name].server_default is None, name


def test_upgrade_downgrade_upgrade_sqlite(tmp_path):
    from alembic import command

    db = tmp_path / "doc.db"
    cfg = _cfg(f"sqlite:///{db}")
    command.upgrade(cfg, DOWN_REVISION)
    assert not COLUMNS & _columns(db)
    command.upgrade(cfg, REVISION)
    assert COLUMNS <= _columns(db)
    command.downgrade(cfg, DOWN_REVISION)
    assert not COLUMNS & _columns(db)
    command.upgrade(cfg, REVISION)
    assert COLUMNS <= _columns(db)


def test_postgres_ddl():
    from alembic import command

    up = io.StringIO()
    command.upgrade(_cfg("postgresql://u:p@localhost/db", up), f"{DOWN_REVISION}:{REVISION}", sql=True)
    for name in COLUMNS:
        assert f"ALTER TABLE product_sustainability_attributes ADD COLUMN {name} VARCHAR" in up.getvalue()
    down = io.StringIO()
    command.downgrade(_cfg("postgresql://u:p@localhost/db", down), f"{REVISION}:{DOWN_REVISION}", sql=True)
    for name in COLUMNS:
        assert f"DROP COLUMN {name}" in down.getvalue()
