"""AB-2: Vereinheitlichung der zwei divergenten Backup-Implementierungen
(2026-07-03-Spec).

Deckt die Akzeptanzkriterien ab:
  (1) create_backup() schreibt in settings.backup_dir (Test mit backup_dir !=
      db_path.parent/'backups') — NICHT neben die DB.
  (2) Erzeugter Dateiname matcht 5eyes-backup-YYYYMMDD-HHMMSS.db — kein T…Z.
  (3) maintenance.list_backups und backup.list_backups ueber dasselbe
      Verzeichnis liefern dieselbe Menge.
  (4) Manuell erzeugtes Backup ist WAL-konsistent (PRAGMA integrity_check == "ok").
  (5) Der Admin-Endpoint-Response-Contract (Keys) bleibt unveraendert.
"""
from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services import backup as backup_engine  # noqa: E402
from services import maintenance  # noqa: E402


_FILENAME_RE = re.compile(r"^5eyes-backup-\d{8}-\d{6}\.db$")


def _seed_db(path: Path, rows: int = 30) -> None:
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


@pytest.fixture()
def unified_env(tmp_path: Path, monkeypatch):
    """Legt eine echte SQLite-DB an und setzt settings.backup_dir auf ein
    Verzeichnis, das BEWUSST NICHT db_path.parent/'backups' ist."""
    db_dir = tmp_path / "dbdir"
    db_dir.mkdir()
    db_file = db_dir / "app.db"
    _seed_db(db_file)

    # backup_dir liegt woanders — genau der Divergenz-Fall.
    backup_dir = tmp_path / "external-volume" / "backups"

    monkeypatch.setattr(
        "services.maintenance.resolve_db_file",
        lambda *_a, **_k: db_file,
    )
    monkeypatch.setattr(maintenance.settings, "backup_dir", str(backup_dir))

    return db_file, db_dir, backup_dir


# ---------------------------------------------------------------------------
# (1) create_backup schreibt nach settings.backup_dir, nicht neben die DB
# ---------------------------------------------------------------------------

def test_create_backup_writes_to_settings_backup_dir(unified_env):
    db_file, db_dir, backup_dir = unified_env

    payload = maintenance.create_backup()

    written = Path(payload["backup_file"])
    assert written.exists()
    # Liegt im konfigurierten backup_dir …
    assert written.parent == backup_dir.expanduser().resolve()
    # … und NICHT im alten db_path.parent/'backups'.
    legacy_dir = db_dir / "backups"
    assert not legacy_dir.exists() or list(legacy_dir.glob("5eyes-backup-*.db")) == []


# ---------------------------------------------------------------------------
# (2) Dateiname matcht 5eyes-backup-YYYYMMDD-HHMMSS.db (kein T…Z)
# ---------------------------------------------------------------------------

def test_filename_pattern_has_no_tz_marker(unified_env):
    payload = maintenance.create_backup()
    name = Path(payload["backup_file"]).name
    assert _FILENAME_RE.match(name), f"unerwarteter Name: {name}"
    # Das alte %Y%m%dT%H%M%SZ-Muster darf nicht mehr auftauchen.
    assert "T" not in name.replace("5eyes-backup-", "")
    assert "Z" not in name


# ---------------------------------------------------------------------------
# (3) maintenance.list_backups == backup.list_backups (gleiche Menge)
# ---------------------------------------------------------------------------

def test_maintenance_and_engine_list_same_set(unified_env):
    _db_file, _db_dir, backup_dir = unified_env

    maintenance.create_backup()
    maintenance.create_backup()

    engine_paths = {
        p.resolve() for p in backup_engine.list_backups(backup_dir)
    }
    maint_paths = {
        Path(entry["backup_file"]).resolve()
        for entry in maintenance.list_backups()["backups"]
    }

    assert engine_paths, "Engine sollte Backups finden"
    assert maint_paths == engine_paths


# ---------------------------------------------------------------------------
# (4) Manuelles Backup ist WAL-konsistent (integrity_check == "ok")
# ---------------------------------------------------------------------------

def test_manual_backup_is_wal_consistent(unified_env):
    db_file, _db_dir, _backup_dir = unified_env

    # WAL-Mode aktivieren + uncheckpointeter Schreibvorgang, um zu zeigen,
    # dass die Online-Backup-API (statt copy2) konsistent kopiert.
    conn = sqlite3.connect(str(db_file))
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("INSERT INTO clients (id, name) VALUES (9999, 'WAL')")
        conn.commit()
    finally:
        conn.close()

    payload = maintenance.create_backup()
    backup_path = Path(payload["backup_file"])

    assert _integrity_ok(backup_path)

    # Der uncheckpointete Datensatz ist im Backup vorhanden (WAL mitkopiert).
    conn = sqlite3.connect(f"file:{backup_path.as_posix()}?mode=ro", uri=True)
    try:
        found = conn.execute(
            "SELECT name FROM clients WHERE id = 9999"
        ).fetchone()
    finally:
        conn.close()
    assert found is not None and found[0] == "WAL"


# ---------------------------------------------------------------------------
# (5) Admin-Endpoint-Response-Contract (Keys) unveraendert
# ---------------------------------------------------------------------------

def test_response_contract_keys_unchanged(unified_env):
    payload = maintenance.create_backup()

    # Keys, die der Admin-Endpoint (routers/system.py) + bestehende Tests
    # erwarten.
    for key in ("status", "created_at", "backup_file", "manifest_file", "sha256"):
        assert key in payload, f"fehlender Contract-Key: {key}"
    assert payload["status"] == "ok"
    assert Path(payload["manifest_file"]).exists()

    listing = maintenance.list_backups()
    for key in ("status", "count", "backups"):
        assert key in listing
    assert listing["count"] == len(listing["backups"])
    if listing["backups"]:
        entry = listing["backups"][0]
        for key in ("backup_file", "size_bytes", "modified_at", "manifest_file", "manifest"):
            assert key in entry, f"fehlender list-Contract-Key: {key}"
