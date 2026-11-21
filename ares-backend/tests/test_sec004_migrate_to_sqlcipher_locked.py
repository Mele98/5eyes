"""SEC-004 (Codex-Audit 2026-08-26) + Pruefrunde #864 S-3: migrate_to_sqlcipher.py
ist stillgelegt.

Vorher gab es einen Bypass (``--i-understand-this-tool-is-broken-and-unsafe``):
mit ihm legte das Skript zuerst per ``shutil.copy2`` eine vollstaendige
Klartext-Kopie (``*.pre-sqlcipher-backup``) neben der DB an und scheiterte
danach an ``PRAGMA key = ?``. Jetzt endet es mit und ohne Flag immer mit Exit 1,
verweist auf den Migrator und beruehrt keine Datei.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = BACKEND_ROOT / "migrate_to_sqlcipher.py"
BYPASS = "--i-understand-this-tool-is-broken-and-unsafe"


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        timeout=120,
    )


@pytest.mark.parametrize(
    "extra",
    [[], [BYPASS], ["--help"], [BYPASS, "--help"]],
    ids=["plain", "bypass", "help", "bypass-help"],
)
def test_always_exits_1_and_never_touches_files(tmp_path, extra):
    db_file = tmp_path / "real.db"
    db_file.write_bytes(b"SQLite format 3\x00not touched")
    before = sorted(p.name for p in tmp_path.iterdir())
    result = _run(["--key", "k" * 64, "--db-path", str(db_file), *extra], cwd=tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "stillgelegt" in result.stdout
    assert "ares-migrator" in result.stdout
    assert db_file.read_bytes() == b"SQLite format 3\x00not touched"
    assert sorted(p.name for p in tmp_path.iterdir()) == before, "keine Kopie, keine .encrypted-Datei"
    assert "k" * 64 not in result.stdout + result.stderr


def test_script_has_no_bypass_and_no_migration_code():
    source = SCRIPT.read_text(encoding="utf-8")
    code = source.split('"""', 2)[2]  # ohne Modul-Docstring
    for forbidden in ("argparse", "shutil", "sqlcipher3", "import sqlite3", "from config", BYPASS):
        assert forbidden not in code, forbidden
