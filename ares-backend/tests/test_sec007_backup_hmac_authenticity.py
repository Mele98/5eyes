"""SEC-007 (Codex-Audit 2026-08-26, docs/audits/2026-08-26-data-lifecycle-
crypto-browser-followup-audit.md): der bisherige `.sha256`-Sidecar neben
jedem Backup ist UNKEYED -- er beweist nur Zufallsintegritaet, nicht
Authentizitaet. Ein Angreifer mit Schreibrecht auf das Backup-Verzeichnis
kann Backup UND Sidecar gemeinsam ersetzen und der Restore-Pfad wuerde das
klaglos akzeptieren.

Diese Tests decken die neue, opt-in HMAC-SHA256-Sidecar-Authentisierung ab
(`settings.backup_hmac_key`) -- die weitergehenden Forderungen des Audits
(versioniertes Manifest mit Artifact-ID/Schema-Head/Schluesselversion,
object-locked/unveraenderliches Ziel, echter Restore-Drill) bleiben ein
groesseres, separates Vorhaben und sind bewusst NICHT Teil dieses Fixes.
"""
from __future__ import annotations

import hashlib
import hmac
import sqlite3
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from config import settings  # noqa: E402
from services.backup import (  # noqa: E402
    BackupResult,
    RestoreResult,
    backup_database,
    replicate_offsite,
    restore_database,
)


def _seed_db(path: Path, rows: int = 10) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(
            "CREATE TABLE clients (id INTEGER PRIMARY KEY, name TEXT NOT NULL);"
        )
        conn.executemany(
            "INSERT INTO clients (id, name) VALUES (?, ?)",
            [(i, f"Kunde {i}") for i in range(rows)],
        )
        conn.commit()
    finally:
        conn.close()


_TEST_KEY = "sec007-test-hmac-key-do-not-use-in-prod"


# ---------------------------------------------------------------------------
# Default (kein Key konfiguriert): unveraendertes Verhalten -- kein
# Regressionsrisiko fuer bestehende Tier-1-Deployments.
# ---------------------------------------------------------------------------

def test_no_hmac_sidecar_written_when_key_unconfigured(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "backup_hmac_key", "")
    src = tmp_path / "src.db"
    _seed_db(src)
    result = backup_database(target_dir=tmp_path / "backups", source_db_path=src)

    assert isinstance(result, BackupResult)
    assert result.hmac_signed is False
    hmac_sidecar = result.path.with_suffix(result.path.suffix + ".hmac256")
    assert not hmac_sidecar.exists()


def test_restore_succeeds_without_hmac_verification_when_key_unconfigured(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "backup_hmac_key", "")
    src = tmp_path / "src.db"
    _seed_db(src)
    backup = backup_database(target_dir=tmp_path / "backups", source_db_path=src)

    result = restore_database(
        backup_path=backup.path, target_db_path=tmp_path / "restored.db"
    )
    assert isinstance(result, RestoreResult)
    assert result.hmac_verified is False
    assert result.hash_verified is True


# ---------------------------------------------------------------------------
# Key konfiguriert: HMAC-Sidecar wird geschrieben, Restore verifiziert.
# ---------------------------------------------------------------------------

def test_hmac_sidecar_written_and_matches_expected_value_when_key_configured(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "backup_hmac_key", _TEST_KEY)
    src = tmp_path / "src.db"
    _seed_db(src)
    result = backup_database(target_dir=tmp_path / "backups", source_db_path=src)

    assert result.hmac_signed is True
    hmac_sidecar = result.path.with_suffix(result.path.suffix + ".hmac256")
    assert hmac_sidecar.exists()

    expected = hmac.new(
        _TEST_KEY.encode("utf-8"), result.path.read_bytes(), hashlib.sha256
    ).hexdigest()
    actual_in_file = hmac_sidecar.read_text(encoding="utf-8").split()[0].strip()
    assert actual_in_file == expected


def test_restore_verifies_hmac_and_succeeds_when_valid(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "backup_hmac_key", _TEST_KEY)
    src = tmp_path / "src.db"
    _seed_db(src)
    backup = backup_database(target_dir=tmp_path / "backups", source_db_path=src)

    result = restore_database(
        backup_path=backup.path, target_db_path=tmp_path / "restored.db"
    )
    assert result.hmac_verified is True
    assert result.hash_verified is True


# ---------------------------------------------------------------------------
# Fail-closed: Kernszenario des Audits -- Angreifer mit Schreibrecht ersetzt
# Backup + unkeyed SHA256-Sidecar gemeinsam. Ohne Kenntnis des HMAC-
# Schluessels kann er das HMAC-Sidecar NICHT faelschen -> Restore MUSS
# ablehnen.
# ---------------------------------------------------------------------------

def test_restore_rejects_when_hmac_sidecar_missing_but_key_configured(tmp_path, monkeypatch):
    """Reproduziert exakt das Audit-Szenario: Backup + .sha256 sind (fuer
    sich genommen) konsistent, aber es gibt gar kein HMAC-Sidecar -- die
    reine SHA256-Integritaet beweist keine Authentizitaet."""
    monkeypatch.setattr(settings, "backup_hmac_key", "")
    src = tmp_path / "src.db"
    _seed_db(src)
    backup = backup_database(target_dir=tmp_path / "backups", source_db_path=src)
    # .hmac256 existiert nicht, weil der Key beim Backup-Zeitpunkt leer war.

    # JETZT wird backup_hmac_key konfiguriert (z.B. Restore auf einer anderen
    # Maschine/nach Migration) -- Restore MUSS ablehnen statt fail-open zu
    # vertrauen.
    monkeypatch.setattr(settings, "backup_hmac_key", _TEST_KEY)
    with pytest.raises(ValueError, match="HMAC-Sidecar"):
        restore_database(
            backup_path=backup.path, target_db_path=tmp_path / "restored.db"
        )


def test_restore_rejects_tampered_backup_even_with_matching_forged_sha256(tmp_path, monkeypatch):
    """Der Kernangriff aus dem Audit: Angreifer ersetzt Backup-Datei UND
    berechnet den .sha256-Sidecar passend neu -- beide sind intern
    konsistent. Ohne den HMAC-Schluessel kann er das .hmac256-Sidecar aber
    nicht faelschen -> Restore MUSS trotz gueltigem SHA256 ablehnen."""
    monkeypatch.setattr(settings, "backup_hmac_key", _TEST_KEY)
    src = tmp_path / "src.db"
    _seed_db(src)
    backup = backup_database(target_dir=tmp_path / "backups", source_db_path=src)

    # Angreifer manipuliert die Backup-Datei...
    tampered = backup.path.read_bytes() + b"MALICIOUS_APPEND"
    backup.path.write_bytes(tampered)
    # ...und berechnet den (unkeyed) SHA256-Sidecar passend neu.
    new_sha = hashlib.sha256(tampered).hexdigest()
    sha_sidecar = backup.path.with_suffix(backup.path.suffix + ".sha256")
    sha_sidecar.write_text(f"{new_sha}  {backup.path.name}\n", encoding="utf-8")
    # Das HMAC-Sidecar bleibt UNVERAENDERT (Angreifer kennt den Key nicht).

    with pytest.raises(ValueError, match="HMAC-Mismatch"):
        restore_database(
            backup_path=backup.path, target_db_path=tmp_path / "restored.db"
        )


def test_verify_hmac_false_skips_check_even_with_key_configured(tmp_path, monkeypatch):
    """Explizites Opt-out (analog verify_hash=False) bleibt moeglich --
    z.B. fuer Notfall-Restores wenn der HMAC-Key selbst verloren ging."""
    monkeypatch.setattr(settings, "backup_hmac_key", _TEST_KEY)
    src = tmp_path / "src.db"
    _seed_db(src)
    backup = backup_database(target_dir=tmp_path / "backups", source_db_path=src)
    hmac_sidecar = backup.path.with_suffix(backup.path.suffix + ".hmac256")
    hmac_sidecar.unlink()  # Sidecar fehlt

    result = restore_database(
        backup_path=backup.path,
        target_db_path=tmp_path / "restored.db",
        verify_hmac=False,
    )
    assert result.hmac_verified is False  # explizit uebersprungen, nicht "bewiesen"


# ---------------------------------------------------------------------------
# Pruning + Offsite-Replikation muessen das neue Sidecar mitbehandeln.
# ---------------------------------------------------------------------------

def test_prune_removes_hmac_sidecar_alongside_backup(tmp_path, monkeypatch):
    import os as _os
    from datetime import datetime, timedelta, timezone

    monkeypatch.setattr(settings, "backup_hmac_key", _TEST_KEY)
    src = tmp_path / "src.db"
    _seed_db(src)
    target_dir = tmp_path / "backups"

    old = backup_database(
        target_dir=target_dir, source_db_path=src,
        timestamp=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    hmac_sidecar = old.path.with_suffix(old.path.suffix + ".hmac256")
    assert hmac_sidecar.exists()

    # os.utime zurueckdatieren -- _prune_old_backups vergleicht gegen die
    # echte Dateisystem-mtime, nicht gegen den Timestamp im Dateinamen
    # (siehe tests/test_backup.py fuer denselben etablierten Test-Pattern).
    old_ts = (datetime.now(timezone.utc) - timedelta(days=400)).timestamp()
    _os.utime(old.path, (old_ts, old_ts))
    _os.utime(hmac_sidecar, (old_ts, old_ts))

    # Zweites (juengeres) Backup ausloesen, damit Retention das alte pruned
    # (retain_days=1, keep_minimum=1 -> nur das neueste bleibt).
    backup_database(
        target_dir=target_dir, source_db_path=src, retain_days=1, keep_minimum=1,
    )

    assert not old.path.exists()
    assert not hmac_sidecar.exists()


def test_replicate_offsite_includes_hmac_sidecar_in_rsync_sources(tmp_path, monkeypatch):
    import services.backup as backup_mod

    monkeypatch.setattr(settings, "backup_hmac_key", _TEST_KEY)
    src = tmp_path / "src.db"
    _seed_db(src)
    backup = backup_database(target_dir=tmp_path / "backups", source_db_path=src)

    monkeypatch.setattr(backup_mod.shutil, "which", lambda _name: "/usr/bin/rsync")
    captured = {}

    class _FakeCompletedProcess:
        returncode = 0
        stdout = ""
        stderr = ""

    def _fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _FakeCompletedProcess()

    monkeypatch.setattr(backup_mod.subprocess, "run", _fake_run)

    result = replicate_offsite(backup.path, "user@host:/srv/offsite/")
    assert result.ok is True
    hmac_sidecar = backup.path.with_suffix(backup.path.suffix + ".hmac256")
    assert str(hmac_sidecar) in captured["cmd"]
