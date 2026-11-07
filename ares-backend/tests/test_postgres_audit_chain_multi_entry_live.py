"""N-862-1: Hash-Kette bei mehreren Audit-Eintraegen pro Transaktion gegen
ECHTES PostgreSQL (Nebenlaeufigkeit unter READ COMMITTED).

Unter PostgreSQL serialisiert der Row-Lock auf ``audit_log_sequence_counter``
(``UPDATE ... SET value = value + 1``) konkurrierende log()-Aufrufe bis zum
Commit der haltenden Transaktion; der Wartende liest danach den neuen
Zaehlerstand (READ COMMITTED) und per neuem Statement-Snapshot den
committeten Vorgaenger. Innerhalb der eigenen Transaktion liegt der
Vorgaenger dagegen nur in den pending objects (autoflush=False) -- genau
das prueft dieser Test zusammen mit der Nebenlaeufigkeit: mehrere Threads,
je mehrere Eintraege pro Transaktion, muessen eine lineare, lueckenlose
Kette ergeben.

Eigenes Schema je Lauf (search_path). Ohne ``POSTGRES_TEST_DATABASE_URL``
wird uebersprungen; in CI setzt der ``postgres-rls``-Job sie.
"""
from __future__ import annotations

import os
import sys
import threading
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

POSTGRES_URL = os.getenv("POSTGRES_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="POSTGRES_TEST_DATABASE_URL nicht gesetzt; ohne echtes Postgres nicht pruefbar",
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _qi(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


@pytest.fixture()
def pg_engine():
    pytest.importorskip("psycopg")
    from models.review import AuditLog, AuditLogSequenceCounter

    assert POSTGRES_URL is not None
    schema = f"auditchain_{uuid.uuid4().hex[:12]}"
    admin = create_engine(POSTGRES_URL, future=True)
    with admin.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA {_qi(schema)}"))
    sep = "&" if "?" in POSTGRES_URL else "?"
    scoped_url = f"{POSTGRES_URL}{sep}options=-csearch_path%3D{schema}"
    engine = create_engine(scoped_url, future=True)
    AuditLog.__table__.create(bind=engine)
    AuditLogSequenceCounter.__table__.create(bind=engine)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO audit_log_sequence_counter (id, value) VALUES ('singleton', 0)"))
    try:
        yield scoped_url, engine
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f"DROP SCHEMA {_qi(schema)} CASCADE"))
        admin.dispose()


def _log(session, record_id: str) -> None:
    from services.audit import log

    log(session, user_id="u1", user_name="A", table_name="t", record_id=record_id,
        action="UPDATE", tenant_id="tenant-1")


def test_postgres_concurrent_multi_entry_transactions_form_one_linear_chain(pg_engine):
    from models.review import AuditLog
    from services.audit import verify_audit_chain

    scoped_url, engine = pg_engine
    workers = 4
    per_tx = 3
    barrier = threading.Barrier(workers)
    errors: list[Exception] = []

    def _worker(idx: int) -> None:
        own = create_engine(scoped_url, future=True)
        sl = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=own)
        try:
            with sl() as s:
                barrier.wait(timeout=10)
                for n in range(per_tx):
                    _log(s, f"w{idx}-{n}")
                s.commit()
        except Exception as exc:  # noqa: BLE001 -- im Haupt-Thread pruefen
            errors.append(exc)
        finally:
            own.dispose()

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not errors, errors

    sl = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    with sl() as s:
        result = verify_audit_chain(s)
        assert result["ok"] is True, result["errors"]
        rows = s.query(AuditLog).order_by(AuditLog.sequence).all()
        assert [r.sequence for r in rows] == list(range(1, workers * per_tx + 1))
        for start in range(0, len(rows), per_tx):
            block = {r.record_id.split("-")[0] for r in rows[start:start + per_tx]}
            assert len(block) == 1, [r.record_id for r in rows]


def test_postgres_rollback_after_partial_logs_leaves_no_gap(pg_engine):
    from services.audit import verify_audit_chain

    _url, engine = pg_engine
    sl = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    with sl() as s:
        _log(s, "kept-1")
        s.commit()
        _log(s, "lost-1")
        _log(s, "lost-2")
        s.rollback()
        _log(s, "kept-2")
        _log(s, "kept-3")
        s.commit()
        result = verify_audit_chain(s)
        assert result["ok"] is True, result["errors"]
        assert result["checked"] == 3
