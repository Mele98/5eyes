"""AUTH-TEN-07 (Codex-Audit 2026-08-25): Login-Guard war auf PostgreSQL
fail-open, weil ``services/login_guard.py::_ensure_tables()`` rohes
SQLite-DDL (``... AUTOINCREMENT ...``) verwendete -- keine gueltige
PostgreSQL-Syntax, wirft dort bei JEDEM Aufruf einen Syntaxfehler, der von
den ``except SQLAlchemyError``-Faengern als fail-open interpretiert wurde.

Verifiziert:
  - Die kompilierte DDL (ueber die echten ORM-Modelle) enthaelt fuer KEINEN
    Dialekt SQLite-spezifische Syntax und ist fuer Postgres UND SQLite
    gueltig (Regressions-Guard gegen erneutes rohes Dialekt-spezifisches
    DDL-Literal).
  - Gegen eine echte PostgreSQL-Instanz (gated hinter
    POSTGRES_TEST_DATABASE_URL, wie tests/test_postgres_rls_adversarial.py):
    zwei unabhaengige Guard-Instanzen (= zwei "Worker") auf demselben Schema
    teilen sich einen Lockout -- der urspruengliche Fund ("Login-Guard ist
    PostgreSQL-faehig und nicht fail-open") ist damit live widerlegt.
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.schema import CreateIndex, CreateTable

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from models.login_attempt import LoginAttempt, LoginLockout
from services.login_guard import LoginAttemptGuard


# ---------------------------------------------------------------------------
# Dialect-Portabilitaet (laeuft immer, keine echte DB noetig)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("dialect_factory", [postgresql.dialect, sqlite.dialect])
def test_ensure_tables_ddl_has_no_sqlite_only_syntax(dialect_factory):
    dialect = dialect_factory()
    for table in (LoginAttempt.__table__, LoginLockout.__table__):
        ddl = str(CreateTable(table, if_not_exists=True).compile(dialect=dialect))
        assert "AUTOINCREMENT" not in ddl
        for index in table.indexes:
            # Kompiliert ohne Fehler -- wuerfe bei ungueltiger Syntax.
            str(CreateIndex(index, if_not_exists=True).compile(dialect=dialect))


def test_ensure_tables_is_race_safe_under_concurrent_first_call(tmp_path):
    """Regressions-Test fuer die TOCTOU-Race von Table.create(checkfirst=True):
    mehrere Threads rufen _ensure_tables() auf einer frischen (leeren) DB
    gleichzeitig auf -- keiner darf mit 'table already exists' fail-open
    gehen."""
    import threading

    engine = create_engine(f"sqlite:///{tmp_path / 'race.db'}", connect_args={"check_same_thread": False})
    guard = LoginAttemptGuard(engine=engine)

    errors: list[Exception] = []

    def _call():
        try:
            with guard._bind().begin() as conn:
                guard._ensure_tables(conn)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=_call) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors


# ---------------------------------------------------------------------------
# Echte PostgreSQL-Instanz (zwei "Worker" teilen sich einen Lockout)
# ---------------------------------------------------------------------------

POSTGRES_URL = os.getenv("POSTGRES_TEST_DATABASE_URL")

pytestmark_pg = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="POSTGRES_TEST_DATABASE_URL nicht gesetzt; SQLite-Suite ueberspringt Postgres-Login-Guard-Test",
)


def _attach_search_path(engine, schema: str) -> None:
    """Setzt search_path auf jeder neuen physischen DBAPI-Connection --
    analog zum bestehenden event.listens_for-Muster in
    services/tenant_context.py::attach_tenant_context_reset (dort fuer
    checkout/checkin, hier fuer connect: search_path muss nur einmal pro
    physischer Connection gesetzt werden, nicht pro Pool-Checkout)."""
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _set_search_path(dbapi_connection, _record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute(f'SET search_path TO "{schema}"')
        cursor.close()


@pytestmark_pg
def test_two_workers_share_lockout_on_postgres():
    from sqlalchemy import text

    pytest.importorskip("psycopg")
    token = uuid.uuid4().hex[:12]
    schema = f"authten07_{token}"

    admin_engine = create_engine(POSTGRES_URL, future=True)
    with admin_engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))

    try:
        # Zwei unabhaengige Engines/Connections simulieren zwei Worker-
        # Prozesse, die sich (wie in Produktion) dieselbe DB teilen.
        engine_worker_a = create_engine(POSTGRES_URL, future=True)
        engine_worker_b = create_engine(POSTGRES_URL, future=True)
        _attach_search_path(engine_worker_a, schema)
        _attach_search_path(engine_worker_b, schema)
        guard_a = LoginAttemptGuard(engine=engine_worker_a)
        guard_b = LoginAttemptGuard(engine=engine_worker_b)

        from config import settings as _settings
        old_enabled = _settings.login_rate_limit_enabled
        old_max = _settings.login_max_attempts
        _settings.login_rate_limit_enabled = True
        _settings.login_max_attempts = 3
        try:
            username = f"pg-worker-test-{token}"
            # Worker A registriert 2 Fehlversuche, Worker B den dritten ->
            # Lockout muss fuer BEIDE Worker sichtbar sein (geteilter State).
            guard_a.register_failure(username)
            guard_a.register_failure(username)
            decision = guard_b.register_failure(username)
            assert decision.allowed is False, decision

            check_a = guard_a.check(username)
            check_b = guard_b.check(username)
            assert check_a.allowed is False
            assert check_b.allowed is False
        finally:
            _settings.login_rate_limit_enabled = old_enabled
            _settings.login_max_attempts = old_max
            engine_worker_a.dispose()
            engine_worker_b.dispose()
    finally:
        with admin_engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()


@pytestmark_pg
def test_concurrent_register_failure_does_not_bypass_lockout_on_postgres():
    """Kontrollrunde 2026-09-24: register_failure()s Docstring behauptete,
    "die Transaktion serialisiert die konkurrierenden Insert/Count-
    Sequenzen" -- das stimmt nur fuer SQLite (Datei-Lock). Unter Postgres'
    Standard-Isolation (READ COMMITTED) sieht eine laufende Transaktion die
    INSERTs anderer, noch nicht committeter Transaktionen NICHT: mehrere
    echt gleichzeitige register_failure()-Aufrufe fuer denselben Key
    konnten dadurch alle einen Count unterhalb des Limits lesen, obwohl die
    kumulierte Anzahl das Limit laengst ueberschritten hatte -- der Lockout
    wurde faktisch umgangen (z.B. ein paralleler Credential-Stuffing-Burst).

    Dieser Test feuert echte, gleichzeitige register_failure()-Aufrufe
    (nicht sequenziell wie test_two_workers_share_lockout_on_postgres oben)
    gegen eine reale Postgres-Instanz und prueft, dass NACH allen Aufrufen
    ein Lockout aktiv ist, sobald die kumulierte Anzahl das Limit erreicht."""
    import threading

    from sqlalchemy import text

    pytest.importorskip("psycopg")
    token = uuid.uuid4().hex[:12]
    schema = f"authten07_concurrent_{token}"

    admin_engine = create_engine(POSTGRES_URL, future=True)
    with admin_engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))

    try:
        from config import settings as _settings
        old_enabled = _settings.login_rate_limit_enabled
        old_max = _settings.login_max_attempts
        _settings.login_rate_limit_enabled = True
        _settings.login_max_attempts = 5
        try:
            username = f"pg-concurrent-test-{token}"
            n_threads = 8  # > login_max_attempts, garantiert Ueberschreitung
            engines = [create_engine(POSTGRES_URL, future=True) for _ in range(n_threads)]
            for eng in engines:
                _attach_search_path(eng, schema)
            guards = [LoginAttemptGuard(engine=eng) for eng in engines]

            barrier = threading.Barrier(n_threads)
            results: list = [None] * n_threads

            def _call(idx: int) -> None:
                barrier.wait()  # alle Threads starten so gleichzeitig wie moeglich
                results[idx] = guards[idx].register_failure(username)

            threads = [threading.Thread(target=_call, args=(i,)) for i in range(n_threads)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # Ohne die Serialisierung koennten mehrere/alle Aufrufe einen
            # Count unterhalb des Limits sehen und faelschlich allowed=True
            # zurueckgeben -- mindestens EINER muss den Lockout ausgeloest
            # haben (er sieht dann alle vorherigen commiteten Faelle).
            assert any(r.allowed is False for r in results), (
                "Kein einziger Aufruf loeste den Lockout aus trotz "
                f"{n_threads} gleichzeitiger Fehlversuche > "
                f"login_max_attempts={_settings.login_max_attempts} -- "
                "Race erlaubt Umgehung des Brute-Force-Schutzes."
            )
            # Und der Guard-Zustand danach muss konsistent gesperrt sein.
            check_engine = create_engine(POSTGRES_URL, future=True)
            _attach_search_path(check_engine, schema)
            final_check = LoginAttemptGuard(engine=check_engine).check(username)
            assert final_check.allowed is False
            check_engine.dispose()

            for eng in engines:
                eng.dispose()
        finally:
            _settings.login_rate_limit_enabled = old_enabled
            _settings.login_max_attempts = old_max
    finally:
        with admin_engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()
