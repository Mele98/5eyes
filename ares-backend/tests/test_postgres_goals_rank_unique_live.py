"""N-868-1 gegen ECHTES PostgreSQL: ux_goals_rank_active + CHECK (rank >= 1).

Revision f8c1d5a3e7b2 bringt die Paritaet zum Rohschema der Desktop-App.
Geprueft:

* doppelte aktive Raenge je Mandat bzw. Raenge < 1 brechen die Revision
  fail-closed mit der Liste ab, es entsteht weder Index noch CHECK;
* nach dem Upgrade scheitern eine Neuanlage und eine Reaktivierung auf
  einem belegten Rang (Fehler nennt den Indexnamen, den der Router per
  is_goal_rank_unique_violation auf 409 abbildet) sowie ein Rang 0;
  inaktive und geloeschte Ziele bleiben ausserhalb des Index;
* Downgrade entfernt beides, erneutes Upgrade ist gruen.

Fremdschluessel (mandates) werden fuer die Probezeilen per
``session_replication_role = replica`` ausgesetzt; Unique-Index und CHECK
gelten davon unberuehrt. Eigenes Schema je Test. Ohne
``POSTGRES_TEST_DATABASE_URL`` uebersprungen (CI-Job ``postgres-rls``).
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

POSTGRES_URL = os.getenv("POSTGRES_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="POSTGRES_TEST_DATABASE_URL nicht gesetzt; ohne echtes Postgres nicht pruefbar",
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.goal_reorder import is_goal_rank_unique_violation  # noqa: E402

REVISION = "f8c1d5a3e7b2"
INDEX_NAME = "ux_goals_rank_active"
CHECK_NAME = "ck_goals_rank_positive"
PREVIOUS_REVISION = ScriptDirectory(str(BACKEND_ROOT / "alembic")).get_revision(REVISION).down_revision
NOW = "2026-11-07T00:00:00.000Z"


def _qi(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


@pytest.fixture()
def pg_schema():
    pytest.importorskip("psycopg")
    assert POSTGRES_URL is not None
    schema = f"goalrank_{uuid.uuid4().hex[:12]}"
    admin = create_engine(POSTGRES_URL, future=True)
    with admin.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA {_qi(schema)}"))
    sep = "&" if "?" in POSTGRES_URL else "?"
    scoped_url = f"{POSTGRES_URL}{sep}options=-csearch_path%3D{schema}"
    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", scoped_url.replace("%", "%%"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    engine = create_engine(scoped_url, future=True)
    try:
        yield cfg, engine, schema
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f"DROP SCHEMA {_qi(schema)} CASCADE"))
        admin.dispose()


def _goal(engine, gid: str, rank: int, *, mandate: str = "m-1", active: int = 1, deleted: str | None = None):
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL session_replication_role = replica"))
        conn.execute(text(
            "INSERT INTO goals (id, mandate_id, client_id, goal_family, goal_type, label, rank, goal_scope,"
            " value_mode, is_ongoing, hardness, is_active, created_at, updated_at, deleted_at)"
            " VALUES (:id, :m, 'c-1', 'Vermögen', 'Vermögensziel', :id, :rank, 'Beratungsvermögen',"
            " 'nominal', 0, 'Primär', :active, :now, :now, :deleted)"
        ), {"id": gid, "m": mandate, "rank": rank, "active": active, "now": NOW, "deleted": deleted})


def _state(engine, schema: str) -> tuple[str | None, str | None]:
    with engine.connect() as conn:
        index = conn.execute(
            text("SELECT indexdef FROM pg_indexes WHERE schemaname = :s AND indexname = :i"),
            {"s": schema, "i": INDEX_NAME},
        ).scalar()
        check = conn.execute(
            text(
                "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c"
                " JOIN pg_namespace n ON n.oid = c.connamespace"
                " WHERE n.nspname = :s AND c.conname = :c"
            ),
            {"s": schema, "c": CHECK_NAME},
        ).scalar()
    return index, check


def test_duplicate_and_non_positive_ranks_abort_the_upgrade(pg_schema):
    cfg, engine, schema = pg_schema
    command.upgrade(cfg, PREVIOUS_REVISION)
    _goal(engine, "g-a", 1)
    _goal(engine, "g-b", 1)
    _goal(engine, "g-c", 0, mandate="m-2")
    with pytest.raises(RuntimeError) as exc_info:
        command.upgrade(cfg, REVISION)
    message = str(exc_info.value)
    assert "N-868-1-Migration abgebrochen" in message
    assert "m-1/1/2" in message and "g-c/0" in message
    assert _state(engine, schema) == (None, None)


def test_index_and_check_enforce_rank_contract_and_round_trip(pg_schema):
    cfg, engine, schema = pg_schema
    command.upgrade(cfg, PREVIOUS_REVISION)
    _goal(engine, "g-1", 1)
    _goal(engine, "g-2", 2)
    _goal(engine, "g-off", 1, active=0)
    _goal(engine, "g-del", 1, deleted=NOW)
    command.upgrade(cfg, REVISION)
    index, check = _state(engine, schema)
    assert index and "UNIQUE" in index.upper() and "is_active = 1" in index and "deleted_at IS NULL" in index
    assert check and "rank >= 1" in check

    with pytest.raises(IntegrityError) as dup:
        _goal(engine, "g-dup", 2)
    assert is_goal_rank_unique_violation(dup.value)
    with pytest.raises(IntegrityError) as reactivate:
        with engine.begin() as conn:
            conn.execute(text("UPDATE goals SET is_active = 1 WHERE id = 'g-off'"))
    assert is_goal_rank_unique_violation(reactivate.value)
    with pytest.raises(IntegrityError, match=CHECK_NAME):
        _goal(engine, "g-zero", 0, mandate="m-3")

    command.downgrade(cfg, PREVIOUS_REVISION)
    assert _state(engine, schema) == (None, None)
    command.upgrade(cfg, REVISION)
    assert all(_state(engine, schema))


def test_reorder_lock_timeout_is_classified_as_lock_conflict(pg_schema):
    """N-873-08 / H-868-D1 live: Haelt ein Reorder die Zeilensperren
    (SELECT ... ORDER BY id FOR UPDATE), endet ein zweiter mit lock_timeout
    in einem echten PG-Fehler 55P03, den der Router als Sperrkonflikt (409)
    erkennt."""
    from sqlalchemy.exc import OperationalError

    from services.goal_reorder import is_goal_order_lock_conflict

    cfg, engine, _schema = pg_schema
    command.upgrade(cfg, REVISION)
    _goal(engine, "g-1", 1)
    _goal(engine, "g-2", 2)
    lock_sql = text(
        "SELECT id FROM goals WHERE mandate_id = 'm-1' AND is_active = 1 AND deleted_at IS NULL"
        " ORDER BY id FOR UPDATE"
    )
    with engine.connect() as holder:
        holder.begin()
        assert [r[0] for r in holder.execute(lock_sql)] == ["g-1", "g-2"]
        with engine.connect() as waiter:
            waiter.begin()
            waiter.execute(text("SET LOCAL lock_timeout = '200ms'"))
            with pytest.raises(OperationalError) as exc_info:
                waiter.execute(lock_sql).all()
            waiter.rollback()
        holder.rollback()
    assert is_goal_order_lock_conflict(exc_info.value)
