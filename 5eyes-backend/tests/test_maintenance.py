from pathlib import Path

from services.maintenance import create_backup, database_paths


def test_database_paths(tmp_path, monkeypatch):
    db_file = tmp_path / 'app.db'
    monkeypatch.setattr('services.maintenance.resolve_db_file', lambda *_args, **_kwargs: db_file)
    payload = database_paths()
    assert payload['db_file'].endswith('app.db')
    assert 'backup_dir' in payload


def test_create_backup(tmp_path, monkeypatch):
    db_file = tmp_path / 'sample.db'
    db_file.write_text('dummy', encoding='utf-8')
    monkeypatch.setattr('services.maintenance.resolve_db_file', lambda *_args, **_kwargs: db_file)
    payload = create_backup()
    assert payload['status'] == 'ok'
    assert Path(payload['backup_file']).exists()
