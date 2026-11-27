"""N-912-05 (Pruefung H-164, Kern-Integration): ``current_approval_key_version``
faengt nur noch die konkreten DB-Fehler eines Altschemas (SQLite
``OperationalError``, PostgreSQL ``ProgrammingError``) und bleibt dort
fail-closed (``ApprovalKeyUnavailable``). Andere Fehler werden nicht maskiert.

Auf PostgreSQL bricht ein fehlgeschlagenes Statement die Transaktion ab; der
SELECT laeuft dort deshalb in einem SAVEPOINT. Die Session bleibt benutzbar und
fruehere Arbeit derselben Transaktion geht nicht verloren (Live-Test, nur mit
``POSTGRES_TEST_DATABASE_URL``; CI-Job ``postgres-rls``).
"""
from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import services.allocation_publication_approval as approval
from services.allocation_publication_approval import ApprovalKeyUnavailable

POSTGRES_URL = os.getenv("POSTGRES_TEST_DATABASE_URL")


@pytest.fixture(autouse=True)
def _no_dek(monkeypatch):
    # Der DEK ist nicht Gegenstand dieser Tests (eigene H12-Tests).
    monkeypatch.setattr(approval, "_approval_key", lambda _db, _tenant: b"k" * 32)


def _sqlite_session(tmp_path, ddl, rows):
    engine = create_engine(f"sqlite:///{tmp_path / 'n912_05.db'}")
    with engine.begin() as conn:
        conn.execute(text(ddl))
        for row in rows:
            conn.execute(text(row))
    return engine, sessionmaker(bind=engine)()


def test_reads_the_dek_version(tmp_path):
    engine, db = _sqlite_session(
        tmp_path, "CREATE TABLE tenants (id TEXT PRIMARY KEY, dek_version INTEGER)",
        ["INSERT INTO tenants VALUES ('t-1', 3)"])
    try:
        assert approval.current_approval_key_version(db, "t-1") == 3
    finally:
        db.close()
        engine.dispose()


def test_legacy_schema_without_column_fails_closed_and_session_stays_usable(tmp_path):
    engine, db = _sqlite_session(
        tmp_path, "CREATE TABLE tenants (id TEXT PRIMARY KEY)", ["INSERT INTO tenants VALUES ('t-1')"])
    try:
        db.execute(text("INSERT INTO tenants VALUES ('t-2')"))  # fruehere Arbeit derselben Transaktion
        with pytest.raises(ApprovalKeyUnavailable, match="DEK-Version nicht lesbar"):
            approval.current_approval_key_version(db, "t-1")
        assert db.execute(text("SELECT count(*) FROM tenants")).scalar() == 2
        db.commit()
    finally:
        db.close()
        engine.dispose()


def test_non_db_errors_are_not_masked_as_missing_key(tmp_path, monkeypatch):
    """Gegenprobe zum frueheren ``except Exception``: ein Programmfehler beim
    Lesen ist kein fehlender Schluessel und wird nicht zu BINDING_MISSING."""
    engine, db = _sqlite_session(
        tmp_path, "CREATE TABLE tenants (id TEXT PRIMARY KEY, dek_version INTEGER)",
        ["INSERT INTO tenants VALUES ('t-1', 1)"])

    class Programmfehler(LookupError):
        pass

    def boom(_db, _tenant):
        raise Programmfehler("Programmfehler")

    monkeypatch.setattr(approval, "_read_dek_version", boom)
    try:
        with pytest.raises(Programmfehler) as raised:
            approval.current_approval_key_version(db, "t-1")
        assert type(raised.value) is Programmfehler  # nicht in ApprovalKeyUnavailable umgedeutet
    finally:
        db.close()
        engine.dispose()


@pytest.mark.skipif(not POSTGRES_URL, reason="POSTGRES_TEST_DATABASE_URL nicht gesetzt")
def test_postgres_failed_read_keeps_the_transaction_usable():
    schema = f"n912_05_{uuid.uuid4().hex[:10]}"
    admin = create_engine(POSTGRES_URL)
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        conn.execute(text(f'CREATE TABLE "{schema}".tenants (id TEXT PRIMARY KEY)'))
        conn.execute(text(f'CREATE TABLE "{schema}".probe (id TEXT PRIMARY KEY)'))
        conn.execute(text(f"INSERT INTO \"{schema}\".tenants VALUES ('t-1')"))
    separator = "&" if "?" in POSTGRES_URL else "?"
    engine = create_engine(f"{POSTGRES_URL}{separator}options=-csearch_path%3D{schema}")
    try:
        db = sessionmaker(bind=engine)()
        try:
            db.execute(text("INSERT INTO probe VALUES ('vorher')"))
            with pytest.raises(ApprovalKeyUnavailable, match="DEK-Version nicht lesbar"):
                approval.current_approval_key_version(db, "t-1")
            # Ohne Savepoint: InFailedSqlTransaction ("current transaction is aborted").
            assert db.execute(text("SELECT count(*) FROM tenants")).scalar() == 1
            db.execute(text("INSERT INTO probe VALUES ('nachher')"))
            db.commit()
        finally:
            db.close()
        with engine.connect() as conn:
            assert sorted(conn.execute(text("SELECT id FROM probe")).scalars()) == ["nachher", "vorher"]
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
