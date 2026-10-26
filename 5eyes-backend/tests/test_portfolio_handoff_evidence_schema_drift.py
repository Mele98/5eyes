"""CERT-HANDOFF-EXECUTION-001: Schema-Drift-Tests fuer die Evidence-Spalten
von ``portfolio_handoffs`` und den partiellen Unique-Index des fachlichen
Schluessels.

Vertrag auf allen Pfaden (ORM/create_all, Runtime-Patch fuer Bestands-DBs,
Alembic-Kette): fuenf nullable TEXT-Spalten und
``ux_portfolio_handoffs_open_business_key`` -- eindeutig nur fuer offene
Handoffs mit Schluessel.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base  # noqa: E402
from main import app  # noqa: F401,E402  (registriert alle Models)
from models.portfolio_handoff import HANDOFF_OPEN_BUSINESS_KEY_INDEX  # noqa: E402

REVISION = "c7e4a19b3d52"
DOWN_REVISION = "b5d2e8f41a73"
COLUMNS = (
    "snapshot_sha256",
    "business_key_hash",
    "execution_evidence_kind",
    "execution_external_reference",
    "execution_confirmed_on",
)


def _columns(db_path: Path) -> set[str]:
    with sqlite3.connect(str(db_path)) as conn:
        return {row[1] for row in conn.execute("PRAGMA table_info(portfolio_handoffs)")}


def _index_sql(db_path: Path):
    with sqlite3.connect(str(db_path)) as conn:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name=?",
            (HANDOFF_OPEN_BUSINESS_KEY_INDEX,),
        ).fetchone()
    return row[0] if row else None


def _seed_parents(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys=OFF")


def _insert(conn, handoff_id: str, status: str, key) -> None:
    conn.execute(
        "INSERT INTO portfolio_handoffs (id, mandate_id, trade_list_snapshot_json, "
        "live_total_value_rappen, position_count, recipient_name, status, created_by, "
        "created_at, updated_at, business_key_hash) "
        "VALUES (?, 'm-1', '[]', 1, 0, 'A', ?, 'u-1', 't', 't', ?)",
        (handoff_id, status, key),
    )


def _assert_unique_only_for_open(db_path: Path) -> None:
    with sqlite3.connect(str(db_path)) as conn:
        _seed_parents(conn)
        _insert(conn, "h-1", "Vorbereitet", "k")
        with pytest.raises(sqlite3.IntegrityError):
            _insert(conn, "h-2", "Vorbereitet", "k")
        # Abgeschlossene Zeilen und Altbestand ohne Schluessel kollidieren nie.
        _insert(conn, "h-3", "Storniert", "k")
        _insert(conn, "h-4", "Gesendet", None)
        _insert(conn, "h-5", "Gesendet", None)
        conn.commit()


def test_create_all_has_columns_and_partial_unique_index(tmp_path):
    db_path = tmp_path / "fresh.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=engine)
    engine.dispose()
    assert set(COLUMNS) <= _columns(db_path)
    sql = _index_sql(db_path)
    assert sql and "UNIQUE" in sql.upper() and "WHERE" in sql.upper()
    _assert_unique_only_for_open(db_path)


def test_runtime_patch_adds_columns_and_index_to_existing_db(tmp_path, monkeypatch):
    import database as db_module

    db_path = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=engine)
    engine.dispose()
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(f"DROP INDEX {HANDOFF_OPEN_BUSINESS_KEY_INDEX}")
        for name in COLUMNS:
            conn.execute(f"ALTER TABLE portfolio_handoffs DROP COLUMN {name}")
        conn.commit()
    assert not (set(COLUMNS) & _columns(db_path))
    assert _index_sql(db_path) is None

    engine = create_engine(f"sqlite:///{db_path}")
    monkeypatch.setattr(db_module, "engine", engine)
    db_module.ensure_runtime_columns()
    db_module.ensure_runtime_columns()  # idempotent
    engine.dispose()

    assert set(COLUMNS) <= _columns(db_path)
    assert _index_sql(db_path) is not None
    _assert_unique_only_for_open(db_path)


def _alembic_cfg(db_url):
    from alembic.config import Config as AlembicConfig

    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return cfg


def test_alembic_revision_in_chain_upgrade_and_downgrade(tmp_path):
    from alembic import command
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_alembic_cfg("sqlite://"))
    heads = script.get_heads()
    assert len(heads) == 1, heads
    chain = {rev.revision for rev in script.walk_revisions("base", heads[0])}
    assert REVISION in chain
    assert script.get_revision(REVISION).down_revision == DOWN_REVISION

    db_path = tmp_path / "alembic.db"
    cfg = _alembic_cfg(f"sqlite:///{db_path}")
    command.upgrade(cfg, DOWN_REVISION)
    assert not (set(COLUMNS) & _columns(db_path))

    command.upgrade(cfg, REVISION)
    assert set(COLUMNS) <= _columns(db_path)
    assert _index_sql(db_path) is not None
    _assert_unique_only_for_open(db_path)

    command.downgrade(cfg, DOWN_REVISION)
    assert not (set(COLUMNS) & _columns(db_path))
    assert _index_sql(db_path) is None


POSTGRES_URL = __import__("os").getenv("POSTGRES_TEST_DATABASE_URL")


@pytest.mark.skipif(not POSTGRES_URL, reason="POSTGRES_TEST_DATABASE_URL nicht gesetzt")
def test_postgres_alembic_partial_unique_index_only_for_open_handoffs():
    import uuid

    from alembic import command
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    schema = f"hoev_{uuid.uuid4().hex[:10]}"
    admin = create_engine(POSTGRES_URL, future=True)
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped = f"{POSTGRES_URL}{'&' if '?' in POSTGRES_URL else '?'}options=-csearch_path%3D{schema}"
    try:
        cfg = _alembic_cfg(scoped.replace("%", "%%"))
        command.upgrade(cfg, REVISION)
        engine = create_engine(scoped, future=True)
        insert = text(
            "INSERT INTO portfolio_handoffs (id, mandate_id, trade_list_snapshot_json, "
            "live_total_value_rappen, position_count, recipient_name, status, created_by, "
            "created_at, updated_at, business_key_hash) "
            "VALUES (:id, 'm-1', '[]', 1, 0, 'A', :status, 'u-1', 't', 't', :key)"
        )
        with engine.begin() as conn:
            conn.execute(text("SET session_replication_role = replica"))  # FKs aus
            conn.execute(insert, {"id": "h-1", "status": "Vorbereitet", "key": "k"})
            conn.execute(insert, {"id": "h-3", "status": "Storniert", "key": "k"})
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(text("SET session_replication_role = replica"))
                conn.execute(insert, {"id": "h-2", "status": "Gesendet", "key": "k"})
        engine.dispose()
        command.downgrade(cfg, DOWN_REVISION)
    finally:
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
