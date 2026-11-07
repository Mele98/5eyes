"""H-865-3 gegen ECHTES PostgreSQL: UNIQUE auf audit_log.sequence.

Revision e2f9a4c7b1d8 legt ``ux_audit_log_sequence`` (partiell, ``sequence IS
NOT NULL``, global ueber alle Tenants: eine Kette) an. Geprueft:

* nach dem Upgrade scheitert eine zweite Zeile mit derselben Sequenz;
* liegen schon doppelte Sequenzen vor, bricht die Revision fail-closed mit
  der Liste ab und legt nichts an;
* Downgrade entfernt den Index, erneutes Upgrade ist gruen.

Eigenes Schema je Test (search_path). Ohne ``POSTGRES_TEST_DATABASE_URL``
uebersprungen; in CI setzt der ``postgres-rls``-Job sie.
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

REVISION = "e2f9a4c7b1d8"
INDEX_NAME = "ux_audit_log_sequence"
# Kettenbasiert: Vorgaenger aus der Revision selbst, nie "ist Head".
PREVIOUS_REVISION = ScriptDirectory(str(BACKEND_ROOT / "alembic")).get_revision(REVISION).down_revision


def _qi(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


@pytest.fixture()
def pg_schema():
    pytest.importorskip("psycopg")
    assert POSTGRES_URL is not None
    schema = f"auditseq_{uuid.uuid4().hex[:12]}"
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


def _insert(engine, sequence: int) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO audit_log (id, user_name, table_name, record_id, action, created_at,"
                " sequence, integrity_hash, previous_hash)"
                " VALUES (:id, 'probe', 'probe_table', 'r1', 'CREATE', '2026-11-07T00:00:00Z',"
                " :seq, :hash, '')"
            ),
            {"id": f"audit-{uuid.uuid4().hex[:8]}", "seq": sequence, "hash": f"h-{uuid.uuid4().hex[:8]}"},
        )


def _index(engine, schema: str):
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT indexdef FROM pg_indexes WHERE schemaname = :s AND indexname = :i"),
            {"s": schema, "i": INDEX_NAME},
        ).scalar()


def test_duplicate_sequences_abort_the_upgrade(pg_schema):
    cfg, engine, schema = pg_schema
    command.upgrade(cfg, PREVIOUS_REVISION)
    _insert(engine, 7)
    _insert(engine, 7)
    with pytest.raises(RuntimeError, match=r"doppelt vergebene Sequenznummern: 7 \(2x\)"):
        command.upgrade(cfg, REVISION)
    assert _index(engine, schema) is None


def test_unique_index_blocks_duplicate_and_round_trips(pg_schema):
    cfg, engine, schema = pg_schema
    command.upgrade(cfg, PREVIOUS_REVISION)
    _insert(engine, 1)
    command.upgrade(cfg, REVISION)
    indexdef = _index(engine, schema)
    assert indexdef and "UNIQUE" in indexdef.upper() and "sequence IS NOT NULL" in indexdef
    _insert(engine, 2)
    with pytest.raises(IntegrityError, match=INDEX_NAME):
        _insert(engine, 2)
    command.downgrade(cfg, PREVIOUS_REVISION)
    assert _index(engine, schema) is None
    command.upgrade(cfg, REVISION)
    assert _index(engine, schema) is not None
