"""H-865-3 ohne PostgreSQL: Alembic-DDL und SQLite-Pfad der Revision
e2f9a4c7b1d8 (UNIQUE auf audit_log.sequence). Das Verhalten gegen echtes
PostgreSQL prueft test_postgres_audit_sequence_unique_live.py (CI-Job
postgres-rls)."""
from __future__ import annotations

import sys
from io import StringIO
from pathlib import Path

from alembic import command
from sqlalchemy import create_engine, inspect

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from tests.test_postgres_bootstrap_migrations import _alembic_config  # noqa: E402


def _pg_ddl() -> str:
    output = StringIO()
    command.upgrade(
        _alembic_config("postgresql://migration-test:unused@localhost/unused", output_buffer=output),
        "head",
        sql=True,
    )
    return " ".join(output.getvalue().lower().split())


def test_postgres_ddl_has_global_unique_sequence_index():
    ddl = _pg_ddl()
    assert "create unique index ux_audit_log_sequence on audit_log (sequence) where sequence is not null" in ddl


def test_sqlite_alembic_path_leaves_audit_log_untouched(tmp_path):
    url = f"sqlite:///{tmp_path / 'h865_3.db'}"
    command.upgrade(_alembic_config(url), "head")
    engine = create_engine(url)
    try:
        names = {index["name"] for index in inspect(engine).get_indexes("audit_log")}
    finally:
        engine.dispose()
    assert "ux_audit_log_sequence" not in names
