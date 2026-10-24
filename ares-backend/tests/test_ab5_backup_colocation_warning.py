"""AB-5 (Audit 2026-06-24): backup_database/backup_scheduler warnten NIRGENDS
wenn settings.backup_dir im selben Verzeichnis wie die Live-DB liegt -- obwohl
der Modul-Docstring von services/backup.py genau davor warnt (bei Verlust des
Datentraegers sind DB und Backup gleichzeitig weg). Fix (2026-07-23):
build_compliance_status() (bereits der zentrale Compliance-Status-Endpoint,
siehe /admin/system) surfaced das jetzt als Warning + controls-Flag.
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from config import settings  # noqa: E402
from services.maintenance import build_compliance_status  # noqa: E402


def test_colocated_backup_dir_triggers_warning(tmp_path, monkeypatch):
    same_dir = tmp_path / "data"
    same_dir.mkdir()
    monkeypatch.setattr("services.maintenance.resolve_db_file", lambda *_a, **_kw: same_dir / "5eyes.db")
    monkeypatch.setattr(settings, "backup_dir", str(same_dir))
    monkeypatch.setattr(settings, "db_use_sqlcipher", True)
    monkeypatch.setattr(settings, "db_key", "x" * 32)

    payload = build_compliance_status()

    assert payload["controls"]["backups_colocated_with_db"] is True
    assert any("selben Verzeichnis" in w for w in payload["warnings"])
    assert payload["status"] == "warning"


def test_separate_backup_dir_does_not_warn(tmp_path, monkeypatch):
    db_dir = tmp_path / "data"
    db_dir.mkdir()
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    monkeypatch.setattr("services.maintenance.resolve_db_file", lambda *_a, **_kw: db_dir / "5eyes.db")
    monkeypatch.setattr(settings, "backup_dir", str(backup_dir))
    monkeypatch.setattr(settings, "db_use_sqlcipher", True)
    monkeypatch.setattr(settings, "db_key", "x" * 32)
    monkeypatch.setattr(settings, "login_rate_limit_enabled", True)
    monkeypatch.setattr(settings, "secret_key", "not-the-default")

    payload = build_compliance_status()

    assert payload["controls"]["backups_colocated_with_db"] is False
    assert not any("selben Verzeichnis" in w for w in payload["warnings"])
    assert payload["status"] == "ok"


def test_colocation_check_is_defensive_against_bad_paths(monkeypatch):
    """Ein Fehler bei der Pfad-Aufloesung darf den Compliance-Status nie crashen."""
    monkeypatch.setattr(
        "services.maintenance.resolve_db_file",
        lambda *_a, **_kw: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    payload = build_compliance_status()
    assert payload["controls"]["backups_colocated_with_db"] is False
