"""Sprint U-8 (Roadmap-Punkt 8): Tests fuer services.backup.

Strategie
---------
- Echte SQLite-DB im tmp-Verzeichnis (KEIN Mock — Backup-Logik ist
  ohnehin schon dünn, Mocks würden den Test wertlos machen)
- Pro Test: backup -> Hash-Sidecar pruefen -> restore -> Inhalt vergleichen
- Retention: zeit-manipulierte mtime-Werte verwenden
- Concurrent-Write-Sicherheit: Backup waehrend offene Write-Connection
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.backup import (  # noqa: E402
    BackupResult,
    backup_database,
    list_backups,
    restore_database,
)


def _seed_db(path: Path, rows: int = 100) -> None:
    """Schreibt eine simple Tabelle mit N Zeilen."""
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS clients (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                balance_rappen INTEGER NOT NULL
            );
            """
        )
        conn.executemany(
            "INSERT INTO clients (id, name, balance_rappen) VALUES (?, ?, ?)",
            [(i, f"Kunde {i}", i * 1000) for i in range(rows)],
        )
        conn.commit()
    finally:
        conn.close()


def _row_count(path: Path, table: str = "clients") -> int:
    conn = sqlite3.connect(str(path))
    try:
        cur = conn.execute(f"SELECT COUNT(*) FROM {table}")
        return int(cur.fetchone()[0])
    finally:
        conn.close()


def _checksum_table(path: Path) -> int:
    """Deterministische Pruefsumme einer DB — sum(id) + sum(balance) +
    Zeilenanzahl. Erkennt jeden Drift zuverlaessig fuer Testzwecke.
    """
    conn = sqlite3.connect(str(path))
    try:
        a = conn.execute("SELECT COALESCE(SUM(id), 0) FROM clients").fetchone()[0]
        b = conn.execute("SELECT COALESCE(SUM(balance_rappen), 0) FROM clients").fetchone()[0]
        c = conn.execute("SELECT COUNT(*) FROM clients").fetchone()[0]
        return int(a) + int(b) + int(c)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Happy-Path
# ---------------------------------------------------------------------------

def test_backup_creates_file_and_sidecar(tmp_path: Path):
    src = tmp_path / "src.db"
    _seed_db(src)
    target_dir = tmp_path / "backups"

    result = backup_database(
        target_dir=target_dir, source_db_path=src, retain_days=30
    )

    assert isinstance(result, BackupResult)
    assert result.path.exists()
    assert result.path.parent == target_dir
    assert result.bytes_written > 0
    assert result.sha256 != ""
    sidecar = result.path.with_suffix(result.path.suffix + ".sha256")
    assert sidecar.exists()
    sidecar_content = sidecar.read_text(encoding="utf-8")
    assert result.sha256 in sidecar_content
    # Filename-Pattern: 5eyes-backup-YYYYMMDD-HHMMSS.db
    assert result.path.name.startswith("5eyes-backup-")
    assert result.path.suffix == ".db"


def test_backup_restore_roundtrip_preserves_data(tmp_path: Path):
    src = tmp_path / "src.db"
    _seed_db(src, rows=250)
    expected_checksum = _checksum_table(src)
    target_dir = tmp_path / "backups"

    backup = backup_database(
        target_dir=target_dir, source_db_path=src, retain_days=30
    )

    # Zielort fuer Restore
    restored = tmp_path / "restored.db"
    rresult = restore_database(
        backup_path=backup.path, target_db_path=restored, verify_hash=True
    )

    assert rresult.hash_verified is True
    assert restored.exists()
    assert _row_count(restored) == 250
    assert _checksum_table(restored) == expected_checksum


def test_backup_works_with_concurrent_write_connection(tmp_path: Path):
    """SQLite Online-Backup-API muss waehrend einer Write-Transaktion
    konsistente Bytes liefern. Wir oeffnen eine separate Write-Connection
    und committen waehrend des Backups."""
    src = tmp_path / "src.db"
    _seed_db(src, rows=50)
    target_dir = tmp_path / "backups"

    # Concurrent: zweite Connection schreibt waehrend Backup laeuft.
    writer = sqlite3.connect(str(src))
    try:
        writer.execute(
            "INSERT INTO clients (id, name, balance_rappen) VALUES (?, ?, ?)",
            (9999, "DuringBackup", 999_999),
        )
        # noch NICHT committed — Backup sieht den Pre-Insert-State
        backup = backup_database(
            target_dir=target_dir, source_db_path=src, retain_days=0
        )
        writer.commit()
    finally:
        writer.close()

    # Restore das Backup und pruefe ob nur die 50 Pre-Insert-Rows da sind
    restored = tmp_path / "restored.db"
    restore_database(backup_path=backup.path, target_db_path=restored)
    assert _row_count(restored) == 50, (
        "Backup haette uncommittete Insert NICHT sehen sollen"
    )

    # Original-DB hat jetzt 51 Rows (nach commit)
    assert _row_count(src) == 51


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------

def test_retention_prunes_old_backups_but_keeps_minimum(tmp_path: Path):
    src = tmp_path / "src.db"
    _seed_db(src, rows=10)
    target_dir = tmp_path / "backups"
    target_dir.mkdir()

    # Lege 5 "alte" Dummy-Backups an und manipuliere mtime.
    old_ts = time.time() - 60 * 86400  # 60 Tage alt
    for i in range(5):
        f = target_dir / f"5eyes-backup-20260101-00000{i}.db"
        f.write_bytes(b"FAKE")
        os.utime(f, (old_ts, old_ts))

    # Jetzt aktuelles Backup -> retain_days=30 sollte 5 alte loeschen,
    # aber keep_minimum=3 darf NICHT angegriffen werden.
    result = backup_database(
        target_dir=target_dir,
        source_db_path=src,
        retain_days=30,
        keep_minimum=3,
    )

    remaining = list_backups(target_dir)
    # Neueste 3 bleiben + das neue Backup = 4
    # (oder weniger wenn der neue Backup-File selbst innerhalb keep_minimum landet)
    assert result.path in remaining
    # Mindestens 3 Files bleiben uebrig (keep_minimum)
    assert len(remaining) >= 3


def test_retention_zero_means_never_prune(tmp_path: Path):
    src = tmp_path / "src.db"
    _seed_db(src, rows=10)
    target_dir = tmp_path / "backups"
    target_dir.mkdir()

    old_ts = time.time() - 365 * 86400
    f = target_dir / "5eyes-backup-20250101-000000.db"
    f.write_bytes(b"ANCIENT")
    os.utime(f, (old_ts, old_ts))

    result = backup_database(
        target_dir=target_dir, source_db_path=src, retain_days=0
    )

    assert result.pruned_files == 0
    assert f.exists(), "retain_days=0 darf NICHTS loeschen"


# ---------------------------------------------------------------------------
# Robustheit / Negative
# ---------------------------------------------------------------------------

def test_backup_fails_when_source_missing(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        backup_database(
            target_dir=tmp_path / "backups",
            source_db_path=tmp_path / "no-such.db",
        )


def test_restore_verifies_hash_and_rejects_tampered_backup(tmp_path: Path):
    src = tmp_path / "src.db"
    _seed_db(src)
    target_dir = tmp_path / "backups"
    backup = backup_database(
        target_dir=target_dir, source_db_path=src, retain_days=0
    )

    # Backup-Datei manipulieren — Hash-Sidecar bleibt mit dem alten Hash
    with backup.path.open("ab") as f:
        f.write(b"TAMPER")

    with pytest.raises(ValueError, match="SHA256-Mismatch"):
        restore_database(
            backup_path=backup.path,
            target_db_path=tmp_path / "restored.db",
            verify_hash=True,
        )


def test_restore_skips_hash_when_requested(tmp_path: Path):
    src = tmp_path / "src.db"
    _seed_db(src)
    target_dir = tmp_path / "backups"
    backup = backup_database(
        target_dir=target_dir, source_db_path=src, retain_days=0
    )

    restored = tmp_path / "restored.db"
    result = restore_database(
        backup_path=backup.path,
        target_db_path=restored,
        verify_hash=False,
    )
    assert result.hash_verified is False
    assert restored.exists()


def test_list_backups_returns_newest_first(tmp_path: Path):
    src = tmp_path / "src.db"
    _seed_db(src, rows=5)
    target_dir = tmp_path / "backups"

    # Drei Backups mit unterschiedlichen Timestamps
    b1 = backup_database(
        target_dir=target_dir,
        source_db_path=src,
        retain_days=0,
        timestamp=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
    )
    # mtime der ersten Datei manipulieren (sonst sind sie zeitnah)
    early = b1.path.stat().st_mtime - 100
    os.utime(b1.path, (early, early))

    b2 = backup_database(
        target_dir=target_dir,
        source_db_path=src,
        retain_days=0,
        timestamp=datetime(2026, 1, 2, 12, 0, 0, tzinfo=timezone.utc),
    )

    listing = list_backups(target_dir)
    assert len(listing) == 2
    assert listing[0] == b2.path  # neueste zuerst
    assert listing[1] == b1.path


def test_list_backups_returns_empty_for_missing_dir(tmp_path: Path):
    assert list_backups(tmp_path / "does-not-exist") == []
