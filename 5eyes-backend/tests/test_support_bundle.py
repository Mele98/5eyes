import json
import zipfile
from pathlib import Path

from config import settings
from services.maintenance import build_compliance_status, create_support_bundle


def test_create_support_bundle_writes_zip(tmp_path, monkeypatch):
    db_file = tmp_path / '5eyes.db'
    db_file.write_text('placeholder', encoding='utf-8')
    log_dir = tmp_path / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / '5eyes-app.log'
    log_file.write_text('Authorization: Bearer SECRET123\npassword=supersecret\neodhd_api_key=ABC123\n', encoding='utf-8')

    monkeypatch.setattr(settings, 'db_path', str(db_file))
    monkeypatch.setattr(settings, 'twelvedata_api_key', 'TD-SECRET')
    monkeypatch.setattr('services.maintenance.resolve_log_file', lambda: log_file)

    result = create_support_bundle()
    bundle_path = Path(result['bundle_file'])

    assert result['status'] == 'ok'
    assert bundle_path.exists()
    assert result['size_bytes'] == bundle_path.stat().st_size

    with zipfile.ZipFile(bundle_path, 'r') as zf:
        names = set(zf.namelist())
        assert 'system-info.json' in names
        assert 'logs/recent.log' in names
        assert 'logs/5eyes-app.log' not in names
        payload = json.loads(zf.read('system-info.json').decode('utf-8'))
        assert payload['database']['db_file'] == str(db_file)
        assert payload['settings']['secret_key'] == '***REDACTED***'
        assert payload['settings']['twelvedata_api_key'] == '***REDACTED***'
        assert payload['support_bundle_policy']['raw_log_file_included'] is False
        redacted_log = zf.read('logs/recent.log').decode('utf-8')
        assert 'SECRET123' not in redacted_log
        assert 'supersecret' not in redacted_log
        assert 'ABC123' not in redacted_log
        assert '***REDACTED***' in redacted_log


def test_build_compliance_status_exposes_security_controls(monkeypatch):
    monkeypatch.setattr(settings, 'app_env', 'development')
    monkeypatch.setattr(settings, 'db_use_sqlcipher', False)
    monkeypatch.setattr(settings, 'db_key', None)
    payload = build_compliance_status()

    assert payload['controls']['client_scope_enforced'] is True
    assert payload['controls']['support_bundle_raw_logs_included'] is False
    assert payload['controls']['browser_token_fallback_storage'] == 'sessionStorage'
