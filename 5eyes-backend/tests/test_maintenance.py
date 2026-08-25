import sqlite3
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from services import maintenance
from services.maintenance import create_backup, database_paths, run_integrity_check


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


def test_run_integrity_check_ok_on_healthy_db(tmp_path):
    """AB-6: run_integrity_check() muss auf einer gesunden DB weiterhin 'ok'
    liefern (Regression fuer den PRAGMA-Cap-Fix)."""
    db_file = tmp_path / 'healthy.db'
    _seed_sqlite_db(db_file)
    engine = create_engine(f'sqlite:///{db_file}')
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        result = run_integrity_check(db)
    finally:
        db.close()
        engine.dispose()
    assert result['status'] == 'ok'
    assert result['integrity_check'] == ['ok']
    assert result['quick_check'] == 'ok'


def test_run_integrity_check_caps_pragma_argument(tmp_path, monkeypatch):
    """AB-6: PRAGMA integrity_check wird mit einem Problem-Cap aufgerufen
    (statt unbeschraenkt), damit eine stark korrupte, grosse DB nicht
    unbegrenzt lange laeuft / ein unbeschraenktes Result-Set liefert."""
    db_file = tmp_path / 'capped.db'
    _seed_sqlite_db(db_file)
    engine = create_engine(f'sqlite:///{db_file}')
    Session = sessionmaker(bind=engine)
    db = Session()
    executed_sql: list[str] = []
    real_execute = db.execute

    def _spy_execute(clause, *args, **kwargs):
        executed_sql.append(str(clause))
        return real_execute(clause, *args, **kwargs)

    monkeypatch.setattr(db, 'execute', _spy_execute)
    try:
        run_integrity_check(db)
    finally:
        db.close()
        engine.dispose()
    integrity_calls = [sql for sql in executed_sql if 'integrity_check' in sql]
    assert len(integrity_calls) == 1
    assert 'integrity_check(50)' in integrity_calls[0]
