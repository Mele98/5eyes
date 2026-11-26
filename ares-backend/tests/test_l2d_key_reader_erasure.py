"""C-L2D-01 (Codex-Abnahme 26.11.2026): Eine committete DSG-Schluesselvernichtung
macht jeden bereits aktiven KeyReader wirkungslos.

Vertrag: Nach Commit der Loeschung kann kein neuer oder bereits aktiver Ares-Leser
den Schluessel erneut zur Entschluesselung verwenden. PostgreSQL-Gegenstueck mit
zwei Sessions (Lesesperre, Loeschung wartet): test_postgres_l2d_key_shred_race_live.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
for _path in (str(BACKEND_ROOT), str(BACKEND_ROOT / "tests")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import pytest  # noqa: E402

from h8_support import sf  # noqa: E402,F401
from services import pii_vault  # noqa: E402

TEXT = "SYNTHETISCHER TESTTEXT"


def _sealed(db):
    envelope = pii_vault.seal_for_client(db, "c-1", TEXT)
    db.commit()
    return envelope


def test_warm_reader_cannot_decrypt_after_committed_shred(sf):
    with sf() as db:
        envelope = _sealed(db)
        reader = pii_vault.KeyReader(db)
        assert pii_vault.reveal(db, envelope, reader=reader) == TEXT
        assert pii_vault.shred_client_keys(db, "c-1") == 1
        db.commit()
        # Positivkontrolle: frischer Leser sieht die Loeschung.
        assert pii_vault.reveal(db, envelope, reader=pii_vault.KeyReader(db)) is None
        assert pii_vault.reveal(db, envelope, reader=reader) is None
        assert pii_vault.reveal_state(db, envelope, reader=reader)[1] != pii_vault.REVEAL_OPEN


def test_shred_invalidates_readers_of_the_same_session_before_commit(sf):
    with sf() as db:
        envelope = _sealed(db)
        reader = pii_vault.KeyReader(db)
        assert pii_vault.reveal(db, envelope, reader=reader) == TEXT
        pii_vault.shred_client_keys(db, "c-1")
        # Noch nicht committet: derselbe Leser sieht bereits die vernichtete Zeile.
        assert pii_vault.reveal(db, envelope, reader=reader) is None


def test_committed_shred_in_another_session_invalidates_an_active_reader(sf):
    with sf() as reading, sf() as erasing:
        envelope = _sealed(reading)
        reader = pii_vault.KeyReader(reading)
        assert pii_vault.reveal(reading, envelope, reader=reader) == TEXT
        assert pii_vault.shred_client_keys(erasing, "c-1") == 1
        erasing.commit()
        assert pii_vault.reveal(reading, envelope, reader=reader) is None


def test_reader_cache_ends_with_the_transaction(sf):
    with sf() as db:
        envelope = _sealed(db)
        reader = pii_vault.KeyReader(db)
        assert pii_vault.reveal(db, envelope, reader=reader) == TEXT
        assert reader._keys
        db.commit()
        assert reader._keys == {} and reader._erased == {} and reader._clients == {}
        assert pii_vault.reveal(db, envelope, reader=reader) == TEXT
        db.rollback()
        assert reader._keys == {}


def test_closed_reader_refuses_and_holds_no_key(sf):
    with sf() as db:
        envelope = _sealed(db)
        with pii_vault.KeyReader(db) as reader:
            assert pii_vault.reveal(db, envelope, reader=reader) == TEXT
        assert reader.closed and reader._keys == {}
        with pytest.raises(pii_vault.PiiVaultError):
            pii_vault.reveal(db, envelope, reader=reader)
        with pytest.raises(pii_vault.PiiVaultError):
            reader.client_of_mandate("m-1")
        assert reader not in pii_vault._readers()


def test_cache_still_saves_queries_within_one_transaction(sf):
    """Positivkontrolle N-938-02: innerhalb eines Aufrufs nur eine Schluesselabfrage."""
    from sqlalchemy import event

    with sf() as db:
        envelopes = [pii_vault.seal_for_client(db, "c-1", f"{TEXT} {i}") for i in range(5)]
        db.commit()
        count = 0

        def hook(_conn, _cursor, statement, *_rest):
            nonlocal count
            count += "FROM client_pii_keys" in statement

        event.listen(db.get_bind(), "before_cursor_execute", hook)
        try:
            reader = pii_vault.KeyReader(db)
            assert [pii_vault.reveal(db, e, reader=reader) for e in envelopes] == [f"{TEXT} {i}" for i in range(5)]
        finally:
            event.remove(db.get_bind(), "before_cursor_execute", hook)
        assert count == 1
