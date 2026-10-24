"""Mega-Audit (2026-08-04), Business-Betriebsreife-Dimension: services/backup.py
behauptete im Modul-Docstring SQLCipher-Kompatibilitaet ("Funktioniert mit
normalem SQLite und SQLCipher (Bytes 1:1)"), importierte aber ausschliesslich
das stdlib `sqlite3`-Modul und setzte nirgends `PRAGMA key`. Ein Backup/Restore
gegen eine SQLCipher-verschluesselte Produktions-DB (settings.db_use_sqlcipher
=True) haette die Datei nicht lesen koennen -- der Berater haette sich auf
Backups verlassen, die faktisch nie funktioniert haetten.

Diese Suite verifiziert den Fix (_open_connection in services/backup.py):
* SQLCipher aktiv + Treiber verfuegbar -> Key + Cipher-Pragmas werden auf
  Source- UND Ziel-Connection gesetzt, Backup/Restore funktioniert (End-to-
  End mit einem Fake-Treiber, da `sqlcipher3` in dieser Dev-Umgebung nicht
  installiert ist -- der Fake beweist NUR, dass unser Code den Treiber
  korrekt anspricht, nicht dass sqlcipher3 selbst funktioniert).
* SQLCipher aktiv, aber Treiber NICHT installiert -> lauter RuntimeError
  statt eines verwirrenden sqlite3.DatabaseError("file is not a database")
  tief in _perform_atomic_copy.
* SQLCipher AUS (Default) -> unveraendertes Verhalten, sqlcipher3 wird nie
  angefasst (Backwards-Compat zur bisherigen, produktiv laufenden Mehrheit
  der Installationen ohne Verschluesselung).
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import services.backup as backup_mod  # noqa: E402
from services.backup import backup_database, restore_database  # noqa: E402


def _seed_db(path: Path, rows: list[tuple[int, str]]) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, val TEXT)")
        conn.executemany("INSERT INTO t (id, val) VALUES (?, ?)", rows)
        conn.commit()
    finally:
        conn.close()


def _read_rows(path: Path) -> list[tuple[int, str]]:
    conn = sqlite3.connect(str(path))
    try:
        return conn.execute("SELECT id, val FROM t ORDER BY id").fetchall()
    finally:
        conn.close()


class _RecordingConnection:
    """Wickelt eine echte sqlite3-Connection, faengt aber SQLCipher-
    spezifische PRAGMAs ab (echtes stdlib-sqlite3 kennt sie nicht -- die
    parametrisierte Form 'PRAGMA key = ?' waere dort sogar ein Syntax-Error).
    """

    def __init__(self, real: sqlite3.Connection) -> None:
        self._real = real
        self.executed: list[tuple[str, tuple | None]] = []

    def execute(self, sql: str, params=None):
        self.executed.append((sql, tuple(params) if params else None))
        upper = sql.strip().upper()
        if upper.startswith("PRAGMA KEY") or "CIPHER_" in upper:
            return None
        if params is not None:
            return self._real.execute(sql, params)
        return self._real.execute(sql)

    def backup(self, target: "_RecordingConnection") -> None:
        self._real.backup(target._real)

    def close(self) -> None:
        self._real.close()


class _FakeSqlcipherModule:
    """Steht fuer das echte `sqlcipher3`-Paket -- beweist nur, dass
    services.backup._open_connection den Treiber korrekt anspricht
    (Key setzen, Cipher-Pragmas, backup()), nicht dass sqlcipher3 selbst
    funktioniert (dafuer braeuchte es die echte Native-Extension)."""

    def __init__(self) -> None:
        self.connections: list[_RecordingConnection] = []

    def connect(self, path_or_uri: str, uri: bool = False) -> _RecordingConnection:
        real = sqlite3.connect(path_or_uri, uri=uri)
        rc = _RecordingConnection(real)
        self.connections.append(rc)
        return rc


def _enable_fake_sqlcipher(monkeypatch, db_key: str = "s3cr3t-key") -> _FakeSqlcipherModule:
    fake = _FakeSqlcipherModule()
    monkeypatch.setattr(backup_mod, "SQLCIPHER_AVAILABLE", True)
    monkeypatch.setattr(backup_mod, "sqlcipher3", fake)
    monkeypatch.setattr(backup_mod.settings, "db_use_sqlcipher", True)
    monkeypatch.setattr(backup_mod.settings, "db_key", db_key)
    return fake


def test_backup_and_restore_roundtrip_uses_sqlcipher_driver_when_enabled(tmp_path, monkeypatch):
    fake = _enable_fake_sqlcipher(monkeypatch)

    src = tmp_path / "src.db"
    _seed_db(src, [(1, "alpha"), (2, "beta")])
    target_dir = tmp_path / "backups"

    result = backup_database(target_dir=target_dir, source_db_path=src, retain_days=0)

    assert result.path.exists()
    assert fake.connections, "sqlcipher3.connect() sollte fuer Source und Ziel aufgerufen worden sein"

    key_statements = [
        params for sql, params in fake.connections[0].executed if sql.strip().upper().startswith("PRAGMA KEY")
    ]
    assert key_statements == [("s3cr3t-key",)], "PRAGMA key muss mit dem konfigurierten db_key gesetzt werden"

    cipher_pragmas = {
        sql
        for conn in fake.connections
        for sql, _ in conn.executed
        if "CIPHER_" in sql.upper() or "KDF_ITER" in sql.upper()
    }
    assert any("cipher_page_size" in p.lower() for p in cipher_pragmas)
    assert any("kdf_iter" in p.lower() for p in cipher_pragmas)

    restored = tmp_path / "restored.db"
    restore_result = restore_database(backup_path=result.path, target_db_path=restored)
    assert restore_result.hash_verified is True
    assert _read_rows(restored) == [(1, "alpha"), (2, "beta")]


def test_sqlcipher_enabled_but_driver_missing_raises_loud_runtime_error(tmp_path, monkeypatch):
    monkeypatch.setattr(backup_mod, "SQLCIPHER_AVAILABLE", False)
    monkeypatch.setattr(backup_mod.settings, "db_use_sqlcipher", True)
    monkeypatch.setattr(backup_mod.settings, "db_key", "s3cr3t-key")

    src = tmp_path / "src.db"
    _seed_db(src, [(1, "alpha")])
    target_dir = tmp_path / "backups"

    with pytest.raises(RuntimeError, match="sqlcipher3"):
        backup_database(target_dir=target_dir, source_db_path=src, retain_days=0)

    # Kein halb-geschriebenes Backup darf sichtbar zurueckbleiben.
    assert list(target_dir.glob("*.db")) == []


def test_sqlcipher_disabled_never_touches_sqlcipher_driver(tmp_path, monkeypatch):
    """Default-Verhalten (kein SQLCipher) bleibt unveraendert: sqlcipher3
    wird nicht mal importiert/aufgerufen, auch wenn ein Fake-Modul im
    Namespace steckt."""
    fake = _FakeSqlcipherModule()
    monkeypatch.setattr(backup_mod, "SQLCIPHER_AVAILABLE", True)
    monkeypatch.setattr(backup_mod, "sqlcipher3", fake)
    assert backup_mod.settings.db_use_sqlcipher is False

    src = tmp_path / "src.db"
    _seed_db(src, [(1, "alpha")])
    target_dir = tmp_path / "backups"

    result = backup_database(target_dir=target_dir, source_db_path=src, retain_days=0)

    assert result.path.exists()
    assert fake.connections == [], "Ohne db_use_sqlcipher darf sqlcipher3.connect() nie aufgerufen werden"
    assert _read_rows(result.path) == [(1, "alpha")]
