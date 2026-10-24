"""Roadmap #15 (Standpunkt 2026-08-07): Off-Site-Backup-Replikation.

services.backup.replicate_offsite() kopiert ein bereits erstelltes lokales
Backup via rsync/SSH an einen zweiten CH-Standort. Anders als test_backup.py
(das bewusst ohne Mocks gegen echte SQLite-Dateien testet) mocken wir hier
`subprocess.run` -- wir testen die Kommando-Konstruktion + das Fail-soft-
Verhalten, nicht eine echte Netzwerk-Uebertragung (die in CI nicht verfuegbar
ist und auch nicht sein muss: rsync selbst ist nicht unser Code).

Kernprinzip, das jeder Test hier absichert: ein Offsite-Problem darf NIE
eine Exception werfen oder das bereits erfolgreiche lokale Backup als
Fehlschlag erscheinen lassen (siehe replicate_offsite()-Docstring).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.backup import OffsiteReplicationResult, replicate_offsite  # noqa: E402


@pytest.fixture()
def backup_file(tmp_path) -> Path:
    f = tmp_path / "5eyes-backup-20260807-030000.db"
    f.write_bytes(b"fake-encrypted-backup-bytes")
    return f


def test_missing_backup_file_fails_soft(tmp_path):
    missing = tmp_path / "does-not-exist.db"
    result = replicate_offsite(missing, "user@host:/srv/offsite/")
    assert result == OffsiteReplicationResult(
        ok=False, target="user@host:/srv/offsite/",
        detail=f"Backup-Datei nicht gefunden: {missing}",
    )


def test_empty_target_fails_soft(backup_file):
    result = replicate_offsite(backup_file, "")
    assert result.ok is False
    assert "kein" in result.detail.lower() or "Ziel" in result.detail


def test_rsync_not_installed_fails_soft(monkeypatch, backup_file):
    monkeypatch.setattr("services.backup.shutil.which", lambda name: None)
    result = replicate_offsite(backup_file, "user@host:/srv/offsite/")
    assert result.ok is False
    assert "rsync" in result.detail.lower()


def test_successful_replication_invokes_rsync_with_correct_args(monkeypatch, backup_file):
    monkeypatch.setattr("services.backup.shutil.which", lambda name: "/usr/bin/rsync")
    captured = {}

    def _fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr("services.backup.subprocess.run", _fake_run)

    result = replicate_offsite(
        backup_file, "user@host:/srv/offsite/",
        ssh_key_path="/home/x/.ssh/id_ed25519", ssh_port=2222, timeout_seconds=60,
    )

    assert result.ok is True
    assert result.target == "user@host:/srv/offsite/"
    cmd = captured["cmd"]
    assert cmd[0] == "rsync"
    assert str(backup_file) in cmd
    assert "user@host:/srv/offsite/" == cmd[-1]
    ssh_idx = cmd.index("-e")
    assert "ssh -p 2222" in cmd[ssh_idx + 1]
    assert "-i /home/x/.ssh/id_ed25519" in cmd[ssh_idx + 1]
    assert captured["kwargs"]["timeout"] == 60


def test_sidecar_included_when_present(monkeypatch, backup_file):
    sidecar = backup_file.with_suffix(backup_file.suffix + ".sha256")
    sidecar.write_text("abc123  " + backup_file.name + "\n")
    monkeypatch.setattr("services.backup.shutil.which", lambda name: "/usr/bin/rsync")
    captured = {}

    def _fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr("services.backup.subprocess.run", _fake_run)
    replicate_offsite(backup_file, "user@host:/srv/offsite/")

    assert str(sidecar) in captured["cmd"]


def test_sidecar_omitted_when_absent(monkeypatch, backup_file):
    monkeypatch.setattr("services.backup.shutil.which", lambda name: "/usr/bin/rsync")
    captured = {}

    def _fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr("services.backup.subprocess.run", _fake_run)
    replicate_offsite(backup_file, "user@host:/srv/offsite/")

    assert not any(str(backup_file.name) + ".sha256" in part for part in captured["cmd"])


def test_nonzero_exit_code_fails_soft_with_stderr_detail(monkeypatch, backup_file):
    monkeypatch.setattr("services.backup.shutil.which", lambda name: "/usr/bin/rsync")

    def _fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, returncode=23, stdout="", stderr="rsync: connection refused")

    monkeypatch.setattr("services.backup.subprocess.run", _fake_run)
    result = replicate_offsite(backup_file, "user@host:/srv/offsite/")

    assert result.ok is False
    assert "connection refused" in result.detail


def test_timeout_fails_soft_without_raising(monkeypatch, backup_file):
    monkeypatch.setattr("services.backup.shutil.which", lambda name: "/usr/bin/rsync")

    def _raise_timeout(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=60)

    monkeypatch.setattr("services.backup.subprocess.run", _raise_timeout)
    result = replicate_offsite(backup_file, "user@host:/srv/offsite/", timeout_seconds=60)

    assert result.ok is False
    assert "60" in result.detail or "timeout" in result.detail.lower()


def test_ssh_key_omitted_when_not_configured(monkeypatch, backup_file):
    monkeypatch.setattr("services.backup.shutil.which", lambda name: "/usr/bin/rsync")
    captured = {}

    def _fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr("services.backup.subprocess.run", _fake_run)
    replicate_offsite(backup_file, "user@host:/srv/offsite/", ssh_key_path=None)

    ssh_idx = captured["cmd"].index("-e")
    assert "-i" not in captured["cmd"][ssh_idx + 1]


def test_scheduler_skips_offsite_when_disabled(monkeypatch):
    """Default backup_offsite_enabled=False -> replicate_offsite wird nie aufgerufen."""
    import backup_scheduler
    from config import settings

    monkeypatch.setattr(settings, "backup_offsite_enabled", False)
    fake_result = MagicMock(path="ignored", bytes_written=1, retained_files=1, pruned_files=0)
    monkeypatch.setattr("services.backup.backup_database", lambda **kw: fake_result)
    replicate_spy = MagicMock()
    monkeypatch.setattr("services.backup.replicate_offsite", replicate_spy)

    backup_scheduler._run_backup_job()

    replicate_spy.assert_not_called()


def test_scheduler_calls_offsite_when_enabled(monkeypatch):
    import backup_scheduler
    from config import settings

    monkeypatch.setattr(settings, "backup_offsite_enabled", True)
    monkeypatch.setattr(settings, "backup_offsite_target", "user@host:/srv/offsite/")
    monkeypatch.setattr(settings, "backup_offsite_ssh_key_path", "")
    monkeypatch.setattr(settings, "backup_offsite_ssh_port", 22)
    monkeypatch.setattr(settings, "backup_offsite_timeout_seconds", 120)

    fake_result = MagicMock(path="/tmp/fake-backup.db", bytes_written=1, retained_files=1, pruned_files=0)
    monkeypatch.setattr("services.backup.backup_database", lambda **kw: fake_result)
    replicate_spy = MagicMock(return_value=OffsiteReplicationResult(ok=True, target="x", detail="ok"))
    monkeypatch.setattr("services.backup.replicate_offsite", replicate_spy)

    backup_scheduler._run_backup_job()

    replicate_spy.assert_called_once()
    _, kwargs = replicate_spy.call_args
    assert kwargs["ssh_port"] == 22
