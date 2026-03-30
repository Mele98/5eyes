from __future__ import annotations

import hashlib
import json
import re
import shutil
import zipfile
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from config import DEFAULT_SECRET_KEY, settings
from core.logging_setup import resolve_log_file
from database import SQLCIPHER_AVAILABLE, resolve_db_file


_SENSITIVE_SETTING_KEYS = {
    'secret_key',
    'db_key',
    'twelvedata_api_key',
    'eodhd_api_key',
    'openfigi_api_key',
    'fred_api_key',
    'six_api_key',
}
_LOG_REDACTION_PATTERNS = (
    (
        re.compile(r'(?i)(authorization\s*:\s*bearer\s+)([A-Za-z0-9\-._~+/=]+)'),
        r'\1***REDACTED***',
    ),
    (
        re.compile(r'(?i)(bearer\s+)([A-Za-z0-9\-._~+/=]+)'),
        r'\1***REDACTED***',
    ),
    (
        re.compile(
            r'(?i)\b(secret_key|db_key|password|passwd|token|access_token|refresh_token|api[_-]?key|twelvedata_api_key|eodhd_api_key|openfigi_api_key|fred_api_key|six_api_key)\b(\s*[=:]\s*)([^,\s]+)'
        ),
        r'\1\2***REDACTED***',
    ),
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def ensure_backup_dir() -> Path:
    backup_dir = resolve_db_file(settings.db_path).parent / 'backups'
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def ensure_support_bundle_dir() -> Path:
    bundle_dir = resolve_db_file(settings.db_path).parent / 'support-bundles'
    bundle_dir.mkdir(parents=True, exist_ok=True)
    return bundle_dir


def build_redacted_settings_snapshot() -> dict[str, Any]:
    snapshot = settings.model_dump()
    for sensitive_key, value in list(snapshot.items()):
        normalized = str(sensitive_key).strip().lower()
        if normalized in _SENSITIVE_SETTING_KEYS or normalized.endswith('_token'):
            if value:
                snapshot[sensitive_key] = '***REDACTED***'
        elif 'password' in normalized or 'secret' in normalized:
            snapshot[sensitive_key] = '***REDACTED***'
    return snapshot


def redact_log_lines(lines: list[str]) -> list[str]:
    redacted: list[str] = []
    for line in lines:
        clean = line
        for pattern, replacement in _LOG_REDACTION_PATTERNS:
            clean = pattern.sub(replacement, clean)
        redacted.append(clean)
    return redacted


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def database_paths() -> dict[str, str]:
    db_file = resolve_db_file(settings.db_path)
    return {
        'db_file': str(db_file),
        'db_dir': str(db_file.parent),
        'backup_dir': str(ensure_backup_dir()),
        'support_bundle_dir': str(ensure_support_bundle_dir()),
        'log_file': str(resolve_log_file()),
    }


def create_backup() -> dict[str, Any]:
    db_file = resolve_db_file(settings.db_path)
    if not db_file.exists():
        raise FileNotFoundError(f'Datenbankdatei nicht gefunden: {db_file}')

    backup_dir = ensure_backup_dir()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup_path = backup_dir / f'5eyes-backup-{stamp}.db'
    shutil.copy2(db_file, backup_path)

    sidecars: list[dict[str, str | int]] = []
    for suffix in ('-wal', '-shm'):
        sidecar = Path(str(db_file) + suffix)
        if sidecar.exists():
            target = backup_dir / f'{backup_path.name}{suffix}'
            shutil.copy2(sidecar, target)
            sidecars.append({
                'file': str(target),
                'sha256': _sha256(target),
                'size_bytes': target.stat().st_size,
            })

    manifest = {
        'created_at': utc_now_iso(),
        'db_file': str(backup_path),
        'db_sha256': _sha256(backup_path),
        'db_size_bytes': backup_path.stat().st_size,
        'sidecars': sidecars,
    }
    manifest_path = backup_dir / f'{backup_path.name}.json'
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')

    return {
        'status': 'ok',
        'created_at': manifest['created_at'],
        'backup_file': str(backup_path),
        'manifest_file': str(manifest_path),
        'sha256': manifest['db_sha256'],
    }


def list_backups() -> dict[str, Any]:
    backup_dir = ensure_backup_dir()
    backups: list[dict[str, Any]] = []
    for db_file in sorted(backup_dir.glob('5eyes-backup-*.db'), reverse=True):
        manifest_file = backup_dir / f'{db_file.name}.json'
        manifest = None
        if manifest_file.exists():
            try:
                manifest = json.loads(manifest_file.read_text(encoding='utf-8'))
            except json.JSONDecodeError:
                manifest = {'status': 'invalid_manifest'}
        backups.append({
            'backup_file': str(db_file),
            'size_bytes': db_file.stat().st_size,
            'modified_at': datetime.fromtimestamp(db_file.stat().st_mtime, tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z',
            'manifest_file': str(manifest_file) if manifest_file.exists() else None,
            'manifest': manifest,
        })
    return {
        'status': 'ok',
        'count': len(backups),
        'backups': backups,
    }


def tail_app_log(lines: int | None = None) -> dict[str, Any]:
    requested = lines or settings.recent_log_lines_default
    line_count = min(max(int(requested), 1), settings.recent_log_lines_max)
    log_file = resolve_log_file()
    if not log_file.exists():
        return {
            'status': 'ok',
            'log_file': str(log_file),
            'lines': [],
            'requested_lines': line_count,
        }

    with log_file.open('r', encoding='utf-8', errors='replace') as fh:
        recent = list(deque(fh, maxlen=line_count))

    return {
        'status': 'ok',
        'log_file': str(log_file),
        'requested_lines': line_count,
        'lines': [line.rstrip('\n') for line in recent],
    }


def create_support_bundle() -> dict[str, Any]:
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    bundle_dir = ensure_support_bundle_dir()
    bundle_path = bundle_dir / f'5eyes-support-{stamp}.zip'

    log_payload = tail_app_log(lines=min(settings.recent_log_lines_max, 300))
    backup_payload = list_backups()
    redacted_log_lines = redact_log_lines(list(log_payload.get('lines') or []))
    system_info = {
        'created_at': utc_now_iso(),
        'app_name': settings.app_name,
        'app_version': settings.app_version,
        'app_env': settings.app_env,
        'database': database_paths(),
        'backups': backup_payload,
        'recent_logs': {
            **log_payload,
            'lines': redacted_log_lines,
            'redacted': True,
        },
        'settings': build_redacted_settings_snapshot(),
        'support_bundle_policy': {
            'raw_log_file_included': False,
            'settings_redacted': True,
            'logs_redacted': True,
        },
    }

    with zipfile.ZipFile(bundle_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('system-info.json', json.dumps(system_info, ensure_ascii=False, indent=2))
        if redacted_log_lines:
            zf.writestr('logs/recent.log', '\n'.join(redacted_log_lines) + '\n')

        backup_dir = ensure_backup_dir()
        for manifest_path in sorted(backup_dir.glob('5eyes-backup-*.db.json'), reverse=True)[:10]:
            zf.write(manifest_path, arcname=f'backup-manifests/{manifest_path.name}')

    return {
        'status': 'ok',
        'created_at': system_info['created_at'],
        'bundle_file': str(bundle_path),
        'sha256': _sha256(bundle_path),
        'size_bytes': bundle_path.stat().st_size,
    }


def run_integrity_check(db: Session) -> dict[str, Any]:
    quick = db.execute(text('PRAGMA quick_check')).scalar()
    integrity_rows = db.execute(text('PRAGMA integrity_check')).fetchall()
    integrity = [row[0] for row in integrity_rows]
    return {
        'status': 'ok' if quick == 'ok' and integrity == ['ok'] else 'warning',
        'quick_check': quick,
        'integrity_check': integrity,
        'checked_at': utc_now_iso(),
    }


def run_optimize(db: Session) -> dict[str, Any]:
    db.execute(text('PRAGMA wal_checkpoint(TRUNCATE)'))
    db.execute(text('PRAGMA optimize'))
    db.commit()
    return {
        'status': 'ok',
        'optimized_at': utc_now_iso(),
    }


def build_compliance_status() -> dict[str, Any]:
    db_encryption_enabled = bool(settings.db_use_sqlcipher and settings.db_key)
    warnings: list[str] = []
    if settings.secret_key == DEFAULT_SECRET_KEY:
        warnings.append('secret_key ist noch auf dem Defaultwert und muss ausserhalb von Development/Test ersetzt werden.')
    if not db_encryption_enabled:
        warnings.append('DB-Verschluesselung ist aktuell nicht aktiviert. Fuer reale Kundendaten sollte SQLCipher mit DB_KEY aktiviert werden.')
    if not settings.login_rate_limit_enabled:
        warnings.append('Login-Rate-Limit ist deaktiviert.')
    return {
        'status': 'ok' if not warnings else 'warning',
        'environment': settings.app_env,
        'controls': {
            'client_scope_enforced': True,
            'login_rate_limit_enabled': settings.login_rate_limit_enabled,
            'db_encryption_enabled': db_encryption_enabled,
            'sqlcipher_available': SQLCIPHER_AVAILABLE,
            'default_secret_key_in_use': settings.secret_key == DEFAULT_SECRET_KEY,
            'support_bundle_raw_logs_included': False,
            'support_bundle_redacts_settings': True,
            'support_bundle_redacts_logs': True,
            'browser_token_fallback_storage': 'sessionStorage',
            'electron_token_storage': 'safeStorage',
        },
        'warnings': warnings,
    }
