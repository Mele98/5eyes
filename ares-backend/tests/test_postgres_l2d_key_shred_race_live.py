"""C-L2D-01 live auf PostgreSQL: Schluesselvernichtung wartet auf aktive Leser.

Zwei Sessions der NICHT-Owner-Rolle (NOSUPERUSER, NOBYPASSRLS), echte Migrationskette:

* Session A liest den Schluessel (KeyReader, FOR SHARE) und haelt die Transaktion offen.
* Session B versucht die Vernichtung: sie wartet (lock_timeout greift).
* A beendet die Transaktion; B vernichtet und committet.
* Danach entschluesselt weder der alte Leser von A noch ein frischer Leser.
* Gegenprobe: ohne Lesesperre wartet die Vernichtung nicht (dieser Mechanismus
  ist es, der die Reihenfolge erzwingt).

Uebersprungen ohne ``POSTGRES_TEST_DATABASE_URL`` (CI-Job ``postgres-rls``).
"""
from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from tests.test_postgres_l2d_query_budget_rls_live import POSTGRES_URL, TENANT, pg_app  # noqa: F401
from services import pii_vault
from services.tenant_context import set_tenant_context

pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="POSTGRES_TEST_DATABASE_URL nicht gesetzt; ohne echtes Postgres nicht pruefbar",
)

TEXT = "SYNTHETISCHER TESTTEXT"


def _seal(factory):
    with factory() as db:
        set_tenant_context(db, TENANT)
        envelope = pii_vault.seal_for_client(db, "c-1", TEXT)
        db.commit()
    return envelope


def _shred_with_timeout(db):
    db.execute(text("SET LOCAL lock_timeout = '400ms'"))
    return pii_vault.shred_client_keys(db, "c-1")


def test_shred_waits_for_active_reader_and_then_nothing_decrypts(pg_app):
    envelope = _seal(pg_app)
    with pg_app() as reading, pg_app() as erasing:
        set_tenant_context(reading, TENANT)
        reader = pii_vault.KeyReader(reading)
        assert pii_vault.reveal(reading, envelope, reader=reader) == TEXT

        set_tenant_context(erasing, TENANT)
        with pytest.raises(OperationalError) as blocked:
            _shred_with_timeout(erasing)
        assert "lock" in str(blocked.value).lower()
        erasing.rollback()

        reading.commit()  # Leser beendet: Sperre frei, Cache leer
        set_tenant_context(erasing, TENANT)
        assert _shred_with_timeout(erasing) == 1
        erasing.commit()

        set_tenant_context(reading, TENANT)
        assert pii_vault.reveal(reading, envelope, reader=reader) is None
        assert pii_vault.reveal(reading, envelope, reader=pii_vault.KeyReader(reading)) is None


def test_negative_control_without_read_lock_shred_does_not_wait(pg_app, monkeypatch):
    monkeypatch.setattr(pii_vault, "_key_lock_clause", lambda _db: "")
    envelope = _seal(pg_app)
    with pg_app() as reading, pg_app() as erasing:
        set_tenant_context(reading, TENANT)
        reader = pii_vault.KeyReader(reading)
        assert pii_vault.reveal(reading, envelope, reader=reader) == TEXT
        set_tenant_context(erasing, TENANT)
        assert _shred_with_timeout(erasing) == 1  # wartet nicht: Reihenfolge nicht erzwungen
        erasing.commit()
        reading.rollback()
