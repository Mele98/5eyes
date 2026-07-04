import sqlite3
from pathlib import Path

from services import maintenance
from services.maintenance import create_backup, database_paths


def _seed_sqlite_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute('CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)')
        conn.execute("INSERT INTO t (v) VALUES ('x')")
        conn.commit()
    finally:
        conn.close()


def test_database_paths(tmp_path, monkeypatch):
    db_file = tmp_path / 'app.db'
    monkeypatch.setattr('services.maintenance.resolve_db_file', lambda *_args, **_kwargs: db_file)
    payload = database_paths()
    assert payload['db_file'].endswith('app.db')
    assert 'backup_dir' in payload


def test_create_backup(tmp_path, monkeypatch):
    # AB-2: create_backup delegiert an die atomare WAL-aware Engine, die eine
    # echte SQLite-DB erwartet (kein shutil.copy2 einer Dummy-Datei mehr).
    db_file = tmp_path / 'sample.db'
    _seed_sqlite_db(db_file)
    monkeypatch.setattr('services.maintenance.resolve_db_file', lambda *_args, **_kwargs: db_file)
    monkeypatch.setattr(maintenance.settings, 'backup_dir', str(tmp_path / 'backups'))
    payload = create_backup()
    assert payload['status'] == 'ok'
    assert Path(payload['backup_file']).exists()
