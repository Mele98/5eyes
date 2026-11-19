"""N-868-1 ohne PostgreSQL: Alembic-DDL und SQLite-Pfad der Revision
f8c1d5a3e7b2 (ux_goals_rank_active + CHECK rank >= 1, fail-closed
Vorpruefung). Das Verhalten gegen echtes PostgreSQL prueft
test_postgres_goals_rank_unique_live.py (CI-Job postgres-rls)."""
from __future__ import annotations

import sys
from io import StringIO
from pathlib import Path

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from tests.test_postgres_bootstrap_migrations import _alembic_config  # noqa: E402

REVISION = "f8c1d5a3e7b2"
PREVIOUS_REVISION = ScriptDirectory(str(BACKEND_ROOT / "alembic")).get_revision(REVISION).down_revision
NOW = "2026-11-07T00:00:00.000Z"


def _goal(conn, gid: str, rank: int, *, mandate: str = "m-1", active: int = 1, deleted: str | None = None):
    conn.execute(text(
        "INSERT INTO goals (id, mandate_id, client_id, goal_family, goal_type, label, rank, goal_scope,"
        " value_mode, is_ongoing, hardness, is_active, created_at, updated_at, deleted_at)"
        " VALUES (:id, :m, 'c-1', 'Vermögen', 'Vermögensziel', :id, :rank, 'Beratungsvermögen',"
        " 'nominal', 0, 'Primär', :active, :now, :now, :deleted)"
    ), {"id": gid, "m": mandate, "rank": rank, "active": active, "now": NOW, "deleted": deleted})


def test_postgres_ddl_has_index_and_check():
    output = StringIO()
    command.upgrade(
        _alembic_config("postgresql://migration-test:unused@localhost/unused", output_buffer=output),
        "head",
        sql=True,
    )
    ddl = " ".join(output.getvalue().lower().split())
    assert (
        "create unique index ux_goals_rank_active on goals (mandate_id, rank) "
        "where is_active = 1 and deleted_at is null"
    ) in ddl
    assert "alter table goals add constraint ck_goals_rank_positive check (rank >= 1)" in ddl


def test_sqlite_upgrade_aborts_on_duplicate_active_ranks(tmp_path):
    url = f"sqlite:///{tmp_path / 'n868_1_dup.db'}"
    command.upgrade(_alembic_config(url), PREVIOUS_REVISION)
    engine = create_engine(url)
    with engine.begin() as conn:
        _goal(conn, "g-a", 1)
        _goal(conn, "g-b", 1)
        _goal(conn, "g-c", 0, mandate="m-2")
    with pytest.raises(RuntimeError) as exc_info:
        command.upgrade(_alembic_config(url), REVISION)
    message = str(exc_info.value)
    assert "N-868-1-Migration abgebrochen" in message
    assert "m-1/1/2" in message
    assert "g-c/0" in message
    assert "ux_goals_rank_active" not in {i["name"] for i in inspect(engine).get_indexes("goals")}
    engine.dispose()


def test_sqlite_upgrade_creates_index_ignoring_inactive_and_deleted(tmp_path):
    url = f"sqlite:///{tmp_path / 'n868_1_ok.db'}"
    command.upgrade(_alembic_config(url), PREVIOUS_REVISION)
    engine = create_engine(url)
    with engine.begin() as conn:
        _goal(conn, "g-1", 1)
        _goal(conn, "g-2", 2)
        _goal(conn, "g-off", 1, active=0)
        _goal(conn, "g-del", 1, deleted=NOW)
    command.upgrade(_alembic_config(url), REVISION)
    assert "ux_goals_rank_active" in {i["name"] for i in inspect(engine).get_indexes("goals")}
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            _goal(conn, "g-dup", 2)
    command.downgrade(_alembic_config(url), PREVIOUS_REVISION)
    assert "ux_goals_rank_active" not in {i["name"] for i in inspect(engine).get_indexes("goals")}
    engine.dispose()
