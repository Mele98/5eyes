"""AB-1: Wirklich atomares SQLite-Backup (2026-07-03-Spec).

Deckt die Akzeptanzkriterien ab:
  (1) Abbruch zwischen Temp-Schreiben und Rename -> KEINE finale
      5eyes-backup-*.db; list_backups unveraendert.
  (2) Normaler Lauf -> Backup + Sidecar existieren, SHA256 match,
      PRAGMA integrity_check == "ok".
  (3) Korruptes Backup -> restore(..., verify_hash=True) wirft ValueError,
      produktive Ziel-DB unveraendert.
  (4) Verwaiste *.partial werden aufgeraeumt und nie gelistet.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services import backup as backup_mod  # noqa: E402
from services.backup import (  # noqa: E402
    backup_database,
    list_backups,
    restore_database,
)


def _seed_db(path: Path, rows: int = 50) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS clients (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL
            );
            """
        )
        conn.executemany(
            "INSERT INTO clients (id, name) VALUES (?, ?)",
            [(i, f"Kunde {i}") for i in range(rows)],
        )
        conn.commit()
    finally:
        conn.close()


def _integrity_ok(path: Path) -> bool:
    conn = sqlite3.connect(str(path))
    try:
        rows = conn.execute("PRAGMA integrity_check").fetchall()
    finally:
        conn.close()
    return len(rows) == 1 and str(rows[0][0]).lower() == "ok"


# ---------------------------------------------------------------------------
# (1) Abbruch zwischen Temp-Schreiben und Rename
# ---------------------------------------------------------------------------

def test_aborted_replace_leaves_no_final_backup(tmp_path: Path, monkeypatch):
    """os.replace wirft -> kein 5eyes-backup-*.db, kein Temp-Ruine,
    list_backups unveraendert."""
    src = tmp_path / "src.db"
    _seed_db(src)
    target_dir = tmp_path / "backups"

    # Ein erfolgreiches Baseline-Backup, damit list_backups nicht leer ist.
    baseline = backup_database(
        target_dir=target_dir, source_db_path=src, retain_days=0
    )
    before = list_backups(target_dir)
    assert baseline.path in before

    # Simulierter Abbruch genau zwischen Temp-Schreiben und Rename.
    def _boom(*_a, **_k):
        raise OSError("simulierter Absturz vor Rename")

    monkeypatch.setattr(backup_mod.os, "replace", _boom)

    with pytest.raises(OSError):
        backup_database(target_dir=target_dir, source_db_path=src, retain_days=0)

    # Keine NEUE finale Backup-Datei entstanden.
    after = list_backups(target_dir)
    assert after == before, "abgebrochener Lauf darf list_backups nicht aendern"

    # Keine Temp-Ruine liegen geblieben (cleanup im except-Block).
    partials = list(target_dir.glob("*.partial"))
    assert partials == [], f"Temp-Datei nicht aufgeraeumt: {partials}"


def test_aborted_on_integrity_failure_leaves_no_final_backup(
    tmp_path: Path, monkeypatch
):
    """integrity_check meldet nicht 'ok' -> kein sichtbares Backup."""
    src = tmp_path / "src.db"
    _seed_db(src)
    target_dir = tmp_path / "backups"

    monkeypatch.setattr(backup_mod, "_integrity_check_ok", lambda _p: False)

    with pytest.raises(ValueError, match="integrity_check"):
        backup_database(target_dir=target_dir, source_db_path=src, retain_days=0)

    assert list_backups(target_dir) == []
    assert list(target_dir.glob("*.partial")) == []


# ---------------------------------------------------------------------------
# (2) Normaler Lauf
# ---------------------------------------------------------------------------

def test_normal_run_backup_sidecar_hash_and_integrity(tmp_path: Path):
    src = tmp_path / "src.db"
    _seed_db(src, rows=120)
    target_dir = tmp_path / "backups"

    result = backup_database(
        target_dir=target_dir, source_db_path=src, retain_days=0
    )

    assert result.path.exists()
    sidecar = result.path.with_suffix(result.path.suffix + ".sha256")
    assert sidecar.exists()
    assert result.sha256 in sidecar.read_text(encoding="utf-8")

    # SHA256 des Files stimmt mit dem gemeldeten Hash ueberein.
    assert backup_mod._sha256_file(result.path) == result.sha256

    # PRAGMA integrity_check == "ok" auf dem Backup.
    assert _integrity_ok(result.path)

    # Keine Temp-Reste.
    assert list(target_dir.glob("*.partial")) == []


# ---------------------------------------------------------------------------
# (3) Korruptes Backup -> Restore lehnt strikt ab, Live-DB unveraendert
# ---------------------------------------------------------------------------

def test_corrupt_backup_restore_raises_and_target_unchanged(tmp_path: Path):
    src = tmp_path / "src.db"
    _seed_db(src)
    target_dir = tmp_path / "backups"
    backup = backup_database(
        target_dir=target_dir, source_db_path=src, retain_days=0
    )

    # Produktive Ziel-DB mit bekanntem Inhalt vorbelegen.
    live = tmp_path / "live.db"
    _seed_db(live, rows=7)
    live_bytes_before = live.read_bytes()

    # Backup nachtraeglich manipulieren (Sidecar bleibt alter Hash).
    with backup.path.open("ab") as fh:
        fh.write(b"TAMPER")

    with pytest.raises(ValueError, match="SHA256-Mismatch"):
        restore_database(
            backup_path=backup.path, target_db_path=live, verify_hash=True
        )

    # Live-DB unveraendert.
    assert live.read_bytes() == live_bytes_before


def test_missing_sidecar_strict_restore_raises_and_target_unchanged(tmp_path: Path):
    """Fehlendes Sidecar im strict-Modus -> ValueError, Live-DB unangetastet."""
    src = tmp_path / "src.db"
    _seed_db(src)
    target_dir = tmp_path / "backups"
    backup = backup_database(
        target_dir=target_dir, source_db_path=src, retain_days=0
    )
    # Sidecar entfernen -> kein Integritaetsbeweis mehr.
    sidecar = backup.path.with_suffix(backup.path.suffix + ".sha256")
    sidecar.unlink()

    live = tmp_path / "live.db"
    _seed_db(live, rows=3)
    live_bytes_before = live.read_bytes()

    with pytest.raises(ValueError, match="Sidecar"):
        restore_database(
            backup_path=backup.path, target_db_path=live, verify_hash=True
        )
    assert live.read_bytes() == live_bytes_before


def test_restore_atomic_replace_leaves_live_db_unchanged_on_abort(
    tmp_path: Path, monkeypatch
):
    """Abgebrochener Restore (os.replace wirft) laesst Live-DB unveraendert."""
    src = tmp_path / "src.db"
    _seed_db(src, rows=40)
    target_dir = tmp_path / "backups"
    backup = backup_database(
        target_dir=target_dir, source_db_path=src, retain_days=0
    )

    live = tmp_path / "live.db"
    _seed_db(live, rows=5)
    live_bytes_before = live.read_bytes()

    monkeypatch.setattr(
        backup_mod.os, "replace",
        lambda *a, **k: (_ for _ in ()).throw(OSError("abort")),
    )

    with pytest.raises(OSError):
        restore_database(
            backup_path=backup.path, target_db_path=live, verify_hash=True
        )

    assert live.read_bytes() == live_bytes_before
    assert list(live.parent.glob("*.partial")) == []


# ---------------------------------------------------------------------------
# (4) Verwaiste *.partial werden aufgeraeumt und nie gelistet
# ---------------------------------------------------------------------------

def test_orphaned_partials_removed_and_never_listed(tmp_path: Path):
    src = tmp_path / "src.db"
    _seed_db(src)
    target_dir = tmp_path / "backups"
    target_dir.mkdir()

    # Ruinen frueherer Laeufe.
    orphan1 = target_dir / "5eyes-backup-20260101-000000.db.abc.partial"
    orphan2 = target_dir / "5eyes-backup-20260102-000000.db.xyz.partial"
    orphan1.write_bytes(b"RUIN")
    orphan2.write_bytes(b"RUIN")

    # Partials tauchen NIE in list_backups auf.
    assert list_backups(target_dir) == []

    result = backup_database(
        target_dir=target_dir, source_db_path=src, retain_days=0
    )

    # Nach dem Lauf sind die Waisen weg.
    assert not orphan1.exists()
    assert not orphan2.exists()

    # Nur das echte Backup wird gelistet, kein partial.
    listing = list_backups(target_dir)
    assert result.path in listing
    assert all(not p.name.endswith(".partial") for p in listing)


def test_partial_excluded_from_pruning_and_count(tmp_path: Path):
    """Ein waehrend des Laufs kuenstlich vorhandenes partial darf weder
    gezaehlt noch gepruned werden (Ausschluss im Glob)."""
    src = tmp_path / "src.db"
    _seed_db(src)
    target_dir = tmp_path / "backups"
    target_dir.mkdir()

    # partial, das ein _remove_orphaned_partials NICHT trifft (anderer Name),
    # um den Glob-Ausschluss in _list_backup_files direkt zu pruefen.
    stray = target_dir / "5eyes-backup-20260103-000000.db.keep.partial"
    stray.write_bytes(b"STRAY")

    assert backup_mod._count_backups(target_dir) == 0
    files = backup_mod._list_backup_files(target_dir)
    assert stray not in files
