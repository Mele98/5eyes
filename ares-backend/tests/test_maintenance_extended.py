import json
from pathlib import Path

from services.maintenance import tail_app_log


def test_tail_app_log_returns_recent_lines(tmp_path, monkeypatch):
    log_file = tmp_path / '5eyes-app.log'
    log_file.write_text('a\nb\nc\n', encoding='utf-8')

    monkeypatch.setattr('services.maintenance.resolve_log_file', lambda: log_file)

    result = tail_app_log(lines=2)
    assert result['status'] == 'ok'
    assert result['lines'] == ['b', 'c']


def test_backup_manifest_shape(tmp_path):
    manifest_path = tmp_path / 'manifest.json'
    payload = {
        'created_at': '2026-03-20T00:00:00.000Z',
        'db_file': str(tmp_path / 'db.db'),
        'db_sha256': 'abc',
        'db_size_bytes': 1,
        'sidecars': [],
    }
    manifest_path.write_text(json.dumps(payload), encoding='utf-8')
    loaded = json.loads(manifest_path.read_text(encoding='utf-8'))
    assert loaded['db_sha256'] == 'abc'
