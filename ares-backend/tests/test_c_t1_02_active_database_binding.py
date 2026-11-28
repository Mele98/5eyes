"""C-T1-02/03: Backup, Restore, Pfadanzeige und Start folgen der AKTIVEN Datenbank.

Aktiv ist, was auch die App-Engine nutzt: ``DATABASE_URL`` vor ``DB_PATH``.
Ein abweichendes ``DB_PATH`` (Decoy) darf weder gesichert noch ueberschrieben
noch als aktive DB angezeigt werden. PostgreSQL sperrt die SQLite-Dateipfade
typisiert; dabei bleiben alle Dateien digest-identisch.

Gegenprobe: in maintenance/backup_scheduler/init_db wieder ``settings.db_path``
verwenden -> die Decoy-/Sperrtests werden rot.
"""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

import backup_scheduler
import database
from config import settings
from database import ActiveDatabaseNotFileBacked, active_sqlite_file, sqlite_file_from_url
from services import maintenance

PG_URL = "postgresql://ares@127.0.0.1:1/ares_ct102"


def _sqlite_db(path: Path, marker: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE marker (name TEXT)")
    con.execute("INSERT INTO marker VALUES (?)", (marker,))
    con.commit()
    con.close()
    return path.resolve()


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _marker(path: Path) -> str:
    con = sqlite3.connect(path)
    try:
        return con.execute("SELECT name FROM marker").fetchone()[0]
    finally:
        con.close()


@pytest.fixture
def decoy_setup(monkeypatch, tmp_path):
    active = _sqlite_db(tmp_path / "aktiv" / "active.db", "aktiv")
    decoy = _sqlite_db(tmp_path / "decoy" / "decoy.db", "decoy")
    backups = tmp_path / "backups"
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{active.as_posix()}", raising=False)
    monkeypatch.setattr(settings, "db_path", str(decoy), raising=False)
    monkeypatch.setattr(settings, "backup_dir", str(backups), raising=False)
    monkeypatch.setattr(settings, "backup_offsite_enabled", False, raising=False)
    monkeypatch.setattr(settings, "db_use_sqlcipher", False, raising=False)
    return active, decoy, backups


def test_active_file_follows_database_url_and_db_path_without_url(decoy_setup, monkeypatch):
    active, decoy, _ = decoy_setup
    assert active_sqlite_file() == active
    monkeypatch.setattr(settings, "database_url", None, raising=False)
    assert active_sqlite_file() == decoy


def test_url_forms_without_file_are_refused_typed():
    assert sqlite_file_from_url("sqlite://") is None
    assert sqlite_file_from_url("sqlite:///:memory:") is None
    with pytest.raises(ActiveDatabaseNotFileBacked):
        sqlite_file_from_url(PG_URL)
    with pytest.raises(ActiveDatabaseNotFileBacked):
        sqlite_file_from_url("sqlite:///file:x?mode=memory&uri=true")


def test_real_manual_backup_snapshots_active_file_not_decoy(decoy_setup):
    active, decoy, _ = decoy_setup
    decoy_before = _digest(decoy)
    result = maintenance.create_backup()
    assert _marker(Path(result["backup_file"])) == "aktiv"
    assert _digest(decoy) == decoy_before


def test_database_paths_show_active_file(decoy_setup):
    active, _decoy, _ = decoy_setup
    paths = maintenance.database_paths()
    assert paths["db_backend"] == "sqlite"
    assert Path(paths["db_file"]) == active


@pytest.fixture
def postgres_setup(monkeypatch, tmp_path):
    decoy = _sqlite_db(tmp_path / "decoy" / "decoy.db", "decoy")
    backups = tmp_path / "backups"
    backups.mkdir()
    backup_file = _sqlite_db(tmp_path / "sicherung.db", "sicherung")
    monkeypatch.setattr(settings, "database_url", PG_URL, raising=False)
    monkeypatch.setattr(settings, "db_path", str(decoy), raising=False)
    monkeypatch.setattr(settings, "backup_dir", str(backups), raising=False)
    monkeypatch.setattr(settings, "backup_offsite_enabled", False, raising=False)
    return decoy, backups, backup_file


def _state(*paths: Path) -> dict:
    out = {}
    for p in paths:
        if p.is_dir():
            out[str(p)] = sorted(x.name for x in p.iterdir())
        else:
            out[str(p)] = _digest(p)
    return out


def test_postgres_manual_backup_refused_without_touching_files(postgres_setup):
    decoy, backups, backup_file = postgres_setup
    before = _state(decoy, backups, backup_file)
    with pytest.raises(ActiveDatabaseNotFileBacked):
        maintenance.create_backup()
    assert _state(decoy, backups, backup_file) == before


def test_postgres_default_restore_refused_before_any_check(postgres_setup, monkeypatch):
    decoy, backups, backup_file = postgres_setup
    before = _state(decoy, backups, backup_file)
    called = []
    monkeypatch.setattr(maintenance, "_assert_restorable_single_company", lambda *a, **k: called.append(1))
    monkeypatch.setattr(maintenance.backup_engine, "restore_database", lambda **k: called.append(2))
    with pytest.raises(ActiveDatabaseNotFileBacked):
        maintenance.restore_backup(backup_file, verify_hash=False, verify_hmac=False)
    assert called == []
    assert _state(decoy, backups, backup_file) == before


def test_postgres_scheduled_backup_alerts_and_never_copies_db_path(postgres_setup, monkeypatch):
    decoy, backups, backup_file = postgres_setup
    before = _state(decoy, backups, backup_file)
    alerts, copies = [], []
    monkeypatch.setattr(backup_scheduler, "_alert_backup_problem", lambda **k: alerts.append(k))
    monkeypatch.setattr("services.backup.backup_database", lambda **k: copies.append(k))
    backup_scheduler._run_backup_job()
    assert copies == []
    assert len(alerts) == 1 and "ActiveDatabaseNotFileBacked" in alerts[0]["detail"]
    assert _state(decoy, backups, backup_file) == before


def test_postgres_database_paths_never_show_db_path(postgres_setup):
    paths = maintenance.database_paths()
    assert paths["db_backend"] == "postgresql"
    assert paths["db_file"] == "" and paths["db_dir"] == ""


def test_postgres_init_db_skips_sqlite_bootstrap_and_quarantine(postgres_setup, monkeypatch):
    called = []

    class Probe(RuntimeError):
        pass

    def stop(*_a, **_k):
        raise Probe

    monkeypatch.setattr(settings, "db_bootstrap_schema_on_startup", True, raising=False)
    monkeypatch.setattr(database, "bootstrap_sqlite_schema", lambda **k: called.append(k))
    monkeypatch.setattr(database, "_create_or_migrate_schema", stop)
    with pytest.raises(Probe):
        database.init_db()
    assert called == []


def test_init_db_quarantine_follows_active_url_not_decoy(decoy_setup, monkeypatch):
    from services.sqlite_check_constraint_upgrade import quarantine_marker_path

    active, decoy, _ = decoy_setup
    quarantine_marker_path(active).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(database, "_create_or_migrate_schema", lambda *a, **k: pytest.fail("Schema trotz Quarantaene"))
    with pytest.raises(Exception) as excinfo:
        database.init_db()
    assert "quarant" in str(excinfo.value).lower()
    assert not quarantine_marker_path(decoy).exists()
