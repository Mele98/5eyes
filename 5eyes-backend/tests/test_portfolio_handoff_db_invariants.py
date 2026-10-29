"""HANDOFF-DB-INVARIANT-001: DB-seitige Invarianten fuer ``portfolio_handoffs``.

Vertrag auf allen Pfaden (ORM/create_all, Runtime-Patch fuer Bestands-DBs,
Alembic-Kette, PostgreSQL): Status nur aus der Zustandsmaschine,
``position_count >= 0``, ``snapshot_sha256`` Pflicht und 64 Hex-Zeichen fuer
neue Zeilen, ``holdings_basis`` nur aus der Wertemenge. Altzeilen (z.B. Hash
NULL, vor den Triggern geschrieben) bleiben lesbar und abschliessbar.
"""
from __future__ import annotations

import hashlib
import os
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

REVISION = "d2f8b6a1c4e9"
DOWN_REVISION = "c8e2f4a6b1d3"
TRIGGERS = ("trg_portfolio_handoffs_invariants_insert", "trg_portfolio_handoffs_invariants_update")
VALID_SHA = hashlib.sha256(b"[]").hexdigest()

_INSERT = (
    "INSERT INTO portfolio_handoffs (id, mandate_id, trade_list_snapshot_json, "
    "live_total_value_rappen, position_count, recipient_name, status, created_by, "
    "created_at, updated_at, snapshot_sha256{extra_cols}) "
    "VALUES (?, 'm-1', '[]', 1, ?, 'A', ?, 'u-1', 't', 't', ?{extra_vals})"
)


def _insert(conn, handoff_id, *, status="Vorbereitet", count=0, sha=VALID_SHA, basis=None, with_basis=True):
    extra_cols, extra_vals, params = "", "", [handoff_id, count, status, sha]
    if with_basis:
        extra_cols, extra_vals = ", holdings_basis", ", ?"
        params.append(basis)
    conn.execute(_INSERT.format(extra_cols=extra_cols, extra_vals=extra_vals), params)


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys=OFF")
    return conn


def _trigger_names(db_path: Path) -> set[str]:
    with sqlite3.connect(str(db_path)) as conn:
        return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}


def _columns(db_path: Path) -> set[str]:
    with sqlite3.connect(str(db_path)) as conn:
        return {row[1] for row in conn.execute("PRAGMA table_info(portfolio_handoffs)")}


_BAD_INSERTS = (
    {"status": "BROKEN"},
    {"status": "Sent"},
    {"count": -1},
    {"sha": None},
    {"sha": "abc"},
    {"sha": "A" * 64},
    {"sha": "g" * 64},
    {"basis": "implied"},
)


def _assert_invariants(db_path: Path) -> None:
    with _connect(db_path) as conn:
        _insert(conn, "ok-1")
        _insert(conn, "ok-2", status="Gesendet", count=3, basis="recorded_depot")
        _insert(conn, "ok-3", basis="confirmed_no_holdings")
        for index, bad in enumerate(_BAD_INSERTS):
            with pytest.raises(sqlite3.IntegrityError):
                _insert(conn, f"bad-{index}", **bad)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE portfolio_handoffs SET status='BROKEN' WHERE id='ok-1'")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE portfolio_handoffs SET position_count=-5 WHERE id='ok-1'")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE portfolio_handoffs SET snapshot_sha256=NULL WHERE id='ok-1'")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE portfolio_handoffs SET holdings_basis='x' WHERE id='ok-1'")
        conn.execute("UPDATE portfolio_handoffs SET status='Storniert', cancelled_at='t' WHERE id='ok-1'")
        conn.commit()
        assert conn.execute("SELECT status FROM portfolio_handoffs WHERE id='ok-1'").fetchone()[0] == "Storniert"


def _assert_legacy_row_stays_closable(db_path: Path, legacy_id: str) -> None:
    with _connect(db_path) as conn:
        conn.execute(f"UPDATE portfolio_handoffs SET recommendation_run_id=NULL WHERE id='{legacy_id}'")
        conn.execute(f"UPDATE portfolio_handoffs SET status='Ausgeführt', executed_at='t' WHERE id='{legacy_id}'")
        conn.commit()
        row = conn.execute(f"SELECT status, snapshot_sha256 FROM portfolio_handoffs WHERE id='{legacy_id}'").fetchone()
    assert row == ("Ausgeführt", None)


def test_create_all_installs_invariant_triggers(tmp_path):
    db_path = tmp_path / "fresh.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=engine)
    engine.dispose()
    assert set(TRIGGERS) <= _trigger_names(db_path)
    assert "holdings_basis" in _columns(db_path)
    _assert_invariants(db_path)


def test_runtime_patch_installs_triggers_and_keeps_legacy_rows(tmp_path, monkeypatch):
    import database as db_module

    db_path = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=engine)
    engine.dispose()
    with _connect(db_path) as conn:
        for name in TRIGGERS:
            conn.execute(f"DROP TRIGGER {name}")
        conn.execute("ALTER TABLE portfolio_handoffs DROP COLUMN holdings_basis")
        # Altzeile vor den Invarianten: kein Hash, Status "Gesendet".
        _insert(conn, "legacy-1", status="Gesendet", sha=None, with_basis=False)
        conn.commit()
    assert not (set(TRIGGERS) & _trigger_names(db_path))

    engine = create_engine(f"sqlite:///{db_path}")
    monkeypatch.setattr(db_module, "engine", engine)
    db_module.ensure_runtime_columns()
    db_module.ensure_runtime_columns()  # idempotent
    engine.dispose()

    assert set(TRIGGERS) <= _trigger_names(db_path)
    assert "holdings_basis" in _columns(db_path)
    _assert_legacy_row_stays_closable(db_path, "legacy-1")
    _assert_invariants(db_path)


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
    with _connect(db_path) as conn:
        _insert(conn, "legacy-1", status="Gesendet", sha=None, with_basis=False)
        conn.commit()

    command.upgrade(cfg, REVISION)
    assert set(TRIGGERS) <= _trigger_names(db_path)
    _assert_legacy_row_stays_closable(db_path, "legacy-1")
    _assert_invariants(db_path)

    command.downgrade(cfg, DOWN_REVISION)
    assert not (set(TRIGGERS) & _trigger_names(db_path))
    assert "holdings_basis" not in _columns(db_path)


POSTGRES_URL = os.getenv("POSTGRES_TEST_DATABASE_URL")


@pytest.mark.skipif(not POSTGRES_URL, reason="POSTGRES_TEST_DATABASE_URL nicht gesetzt")
def test_postgres_alembic_invariant_trigger():
    import uuid

    from alembic import command
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    schema = f"hoinv_{uuid.uuid4().hex[:10]}"
    admin = create_engine(POSTGRES_URL, future=True)
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped = f"{POSTGRES_URL}{'&' if '?' in POSTGRES_URL else '?'}options=-csearch_path%3D{schema}"
    insert = text(
        "INSERT INTO portfolio_handoffs (id, mandate_id, trade_list_snapshot_json, "
        "live_total_value_rappen, position_count, recipient_name, status, created_by, "
        "created_at, updated_at, snapshot_sha256) "
        "VALUES (:id, 'm-1', '[]', 1, :count, 'A', :status, 'u-1', 't', 't', :sha)"
    )

    def _run(engine, statement, **params):
        with engine.begin() as conn:
            # FK-Pruefung aus (keine Elternzeilen); der Invarianten-Trigger
            # feuert per ENABLE ALWAYS trotzdem.
            conn.execute(text("SET session_replication_role = replica"))
            conn.execute(statement, params)

    try:
        cfg = _alembic_cfg(scoped.replace("%", "%%"))
        command.upgrade(cfg, DOWN_REVISION)
        engine = create_engine(scoped, future=True)
        _run(engine, insert, id="legacy-1", count=0, status="Gesendet", sha=None)
        command.upgrade(cfg, REVISION)
        with engine.begin() as conn:
            conn.execute(text(
                "ALTER TABLE portfolio_handoffs ENABLE ALWAYS TRIGGER trg_portfolio_handoffs_invariants"
            ))
        _run(engine, insert, id="ok-1", count=0, status="Vorbereitet", sha=VALID_SHA)
        for index, (count, status, sha) in enumerate([
            (0, "BROKEN", VALID_SHA), (-1, "Vorbereitet", VALID_SHA),
            (0, "Vorbereitet", None), (0, "Vorbereitet", "A" * 64),
        ]):
            with pytest.raises(DBAPIError):
                _run(engine, insert, id=f"bad-{index}", count=count, status=status, sha=sha)
        # Altzeile ohne Hash bleibt abschliessbar.
        _run(engine, text("UPDATE portfolio_handoffs SET status='Storniert', cancelled_at='t' WHERE id='legacy-1'"))
        with pytest.raises(DBAPIError):
            _run(engine, text("UPDATE portfolio_handoffs SET status='BROKEN' WHERE id='ok-1'"))
        engine.dispose()
        command.downgrade(cfg, DOWN_REVISION)
    finally:
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
