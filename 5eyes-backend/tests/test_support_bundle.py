import json
import zipfile
from pathlib import Path

from config import settings
from services.maintenance import build_compliance_status, create_support_bundle, redact_log_lines


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


def test_create_support_bundle_redacts_sec001_previously_leaked_fields(tmp_path, monkeypatch):
    """SEC-001 (Codex-Audit 2026-08-26): database_url, tenant_master_kek,
    alphavantage_api_key, market_data_alert_webhook_url und telemetry_dsn
    fehlten in der Blocklist und wurden unredigiert ins Support-Bundle
    geschrieben -- database_url enthaelt im Realbetrieb eingebettete
    DB-Credentials."""
    db_file = tmp_path / '5eyes.db'
    db_file.write_text('placeholder', encoding='utf-8')
    log_dir = tmp_path / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / '5eyes-app.log'
    log_file.write_text('no sensitive lines here\n', encoding='utf-8')

    monkeypatch.setattr(settings, 'db_path', str(db_file))
    monkeypatch.setattr(settings, 'database_url', 'postgresql+psycopg://dbuser:DBPASS@dbhost/db')
    monkeypatch.setattr(settings, 'tenant_master_kek', 'MASTER-KEK-VALUE')
    monkeypatch.setattr(settings, 'alphavantage_api_key', 'ALPHA-KEY-VALUE')
    monkeypatch.setattr(settings, 'market_data_alert_webhook_url', 'https://hooks.example/SECRET-WEBHOOK')
    monkeypatch.setattr(settings, 'telemetry_dsn', 'https://PUBLIC:SECRET@telemetry/42')
    monkeypatch.setattr('services.maintenance.resolve_log_file', lambda: log_file)

    result = create_support_bundle()
    bundle_path = Path(result['bundle_file'])

    with zipfile.ZipFile(bundle_path, 'r') as zf:
        payload = json.loads(zf.read('system-info.json').decode('utf-8'))
        s = payload['settings']
        assert s['database_url'] == '***REDACTED***'
        assert s['tenant_master_kek'] == '***REDACTED***'
        assert s['alphavantage_api_key'] == '***REDACTED***'
        assert s['market_data_alert_webhook_url'] == '***REDACTED***'
        assert s['telemetry_dsn'] == '***REDACTED***'
        # Kein Rohwert darf irgendwo im JSON-Blob auftauchen (auch nicht als
        # Substring in einem anderen Feld).
        raw_json = zf.read('system-info.json').decode('utf-8')
        for leaked in ('DBPASS', 'MASTER-KEK-VALUE', 'ALPHA-KEY-VALUE', 'SECRET-WEBHOOK', 'PUBLIC:SECRET'):
            assert leaked not in raw_json


def test_redact_log_lines_scrubs_invite_token_from_path():
    """PRIV-006 (Codex-Audit 2026-08-14): GET /auth/invite/{token} traegt das
    Einladungs-Token als rohen Pfad-Abschnitt (kein 'Bearer '-Praefix, kein
    '=' /':' wie bei den anderen Mustern) -- ohne eigene Regel liest
    RequestContextMiddleware's 'path=...'-Log-Zeile das Token unveraendert
    durch redact_log_lines()."""
    line = (
        "Request completed | request_id=abc123 method=GET "
        "path=/auth/invite/nQ7f3z9k2LmP-x8vT1cRb4WyAoJdE6sFhU0iN5gKqXw "
        "status=200 duration_ms=4.2"
    )
    [redacted] = redact_log_lines([line])
    assert "nQ7f3z9k2LmP-x8vT1cRb4WyAoJdE6sFhU0iN5gKqXw" not in redacted
    assert "/invite/***REDACTED***" in redacted
    # Umliegende Felder (request_id, method, status, duration_ms) bleiben
    # unangetastet -- nur das Token-Segment wird ersetzt.
    assert "request_id=abc123" in redacted
    assert "status=200" in redacted


def test_redact_log_lines_does_not_touch_invite_accept_path():
    """Regression: POST /auth/invite/accept traegt das Token im Body, nicht
    im Pfad -- die neue Regel darf das statische 'accept'-Segment nicht als
    Token missverstehen und redigieren."""
    line = "Request completed | request_id=x method=POST path=/auth/invite/accept status=200 duration_ms=1.1"
    [redacted] = redact_log_lines([line])
    assert redacted == line


def test_redact_log_lines_other_patterns_still_work_unchanged():
    """Regression: bestehende Bearer- und key=value-Redaktion bleibt von der
    neuen Pfad-Regel unberuehrt."""
    lines = [
        "Authorization: Bearer abcDEF123.token-value",
        "some log line with bearer xyz789 inline",
        "password=supersecret123 more text",
        "eodhd_api_key: ABC-999",
        "harmless line with no secrets at all",
    ]
    redacted = redact_log_lines(lines)
    assert redacted[0] == "Authorization: Bearer ***REDACTED***"
    assert "xyz789" not in redacted[1] and "***REDACTED***" in redacted[1]
    assert redacted[2] == "password=***REDACTED*** more text"
    assert redacted[3] == "eodhd_api_key: ***REDACTED***"
    assert redacted[4] == "harmless line with no secrets at all"


def test_create_support_bundle_redacts_invite_token_path(tmp_path, monkeypatch):
    """PRIV-006 end-to-end: eine reale Request-Log-Zeile mit dem Invite-Token
    im Pfad darf nach create_support_bundle() nicht mehr den Rohwert
    enthalten -- weder im gezippten logs/recent.log noch als Substring
    irgendwo im Bundle."""
    db_file = tmp_path / '5eyes.db'
    db_file.write_text('placeholder', encoding='utf-8')
    log_dir = tmp_path / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / '5eyes-app.log'
    raw_token = 'nQ7f3z9k2LmP-x8vT1cRb4WyAoJdE6sFhU0iN5gKqXw'
    log_file.write_text(
        "Request completed | request_id=abc123 method=GET "
        f"path=/auth/invite/{raw_token} status=200 duration_ms=4.2\n",
        encoding='utf-8',
    )

    monkeypatch.setattr(settings, 'db_path', str(db_file))
    monkeypatch.setattr('services.maintenance.resolve_log_file', lambda: log_file)

    result = create_support_bundle()
    bundle_path = Path(result['bundle_file'])

    with zipfile.ZipFile(bundle_path, 'r') as zf:
        redacted_log = zf.read('logs/recent.log').decode('utf-8')
        assert raw_token not in redacted_log
        assert '/invite/***REDACTED***' in redacted_log
        raw_zip_bytes = zf.read('logs/recent.log')
        assert raw_token.encode('utf-8') not in raw_zip_bytes


def test_build_compliance_status_exposes_security_controls(monkeypatch):
    monkeypatch.setattr(settings, 'app_env', 'development')
    monkeypatch.setattr(settings, 'db_use_sqlcipher', False)
    monkeypatch.setattr(settings, 'db_key', None)
    payload = build_compliance_status()

    assert payload['controls']['client_scope_enforced'] is True
    assert payload['controls']['support_bundle_raw_logs_included'] is False
    assert payload['controls']['browser_token_fallback_storage'] == 'sessionStorage'
