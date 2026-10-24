"""SEC-004 (Codex-Audit 2026-08-26, docs/audits/2026-08-26-data-lifecycle-
crypto-browser-followup-audit.md): migrate_to_sqlcipher.py hat nachgewiesene
Sicherheits-/Korrektheitsluecken (Key sichtbar in argv/stdout, hinterlaesst
ein Klartext-Backup neben der DB, kann Trigger wie die Audit-Log-
Unveraenderlichkeit lautlos durch falsche Schema-Erstellungsreihenfolge
verlieren, unzureichende Erfolgspruefung). Das Tool muss bis zu einem
sicheren Ersatz gesperrt sein.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = BACKEND_ROOT / "migrate_to_sqlcipher.py"


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=str(BACKEND_ROOT),
        env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"},
    )


def test_running_without_acknowledgement_flag_refuses_and_exits_nonzero():
    result = _run(["--key", "some-key", "--db-path", "does-not-exist.db"])
    assert result.returncode != 0
    assert "gesperrt" in result.stdout.lower()
    # Darf NICHT bis zum eigentlichen Migrationscode vordringen (kein
    # sqlcipher3-Importversuch, keine Backup-/DB-Operation).
    assert "sqlcipher3" not in result.stdout.lower()


def test_running_without_acknowledgement_flag_never_touches_the_db_file(tmp_path):
    db_file = tmp_path / "real.db"
    db_file.write_text("not touched", encoding="utf-8")
    result = _run(["--key", "some-key", "--db-path", str(db_file)])
    assert result.returncode != 0
    assert db_file.read_text(encoding="utf-8") == "not touched"
    assert not (tmp_path / "real.db.pre-sqlcipher-backup").exists()


def test_acknowledgement_flag_is_documented_in_help():
    result = _run(["--help"])
    assert result.returncode == 0
    assert "--i-understand-this-tool-is-broken-and-unsafe" in result.stdout
