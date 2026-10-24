"""AUDIT-FIX: Demo-/Staging-Passwoerter stehen nicht im Quellcode.

Vorher setzten ``seed_external_demo.py`` und ``make_demo_accounts_easy.py``
feste Passwort-Literale fuer alle Demo-Accounts, und das Staging-Tunnel-
Skript gab eines davon aus. Wer das Repository lesen konnte, kannte damit das
Login jeder per Tunnel erreichbaren Staging-Instanz. Jetzt kommt das Passwort
aus einer Umgebungsvariable oder wird pro Lauf zufaellig erzeugt und einmal
ausgegeben.
"""
from __future__ import annotations

import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.demo_credentials import MIN_PASSWORD_LENGTH, demo_password  # noqa: E402


def test_env_value_is_used(monkeypatch):
    monkeypatch.setenv("DEMO_X_PASSWORD", "  ein-langes-testpasswort  ")
    assert demo_password("DEMO_X_PASSWORD") == ("ein-langes-testpasswort", "DEMO_X_PASSWORD")


def test_short_env_value_is_refused(monkeypatch):
    monkeypatch.setenv("DEMO_X_PASSWORD", "x" * (MIN_PASSWORD_LENGTH - 1))
    with pytest.raises(SystemExit):
        demo_password("DEMO_X_PASSWORD")


def test_random_value_without_env(monkeypatch):
    monkeypatch.delenv("DEMO_X_PASSWORD", raising=False)
    first, source = demo_password("DEMO_X_PASSWORD")
    second, _ = demo_password("DEMO_X_PASSWORD")
    assert source == "zufaellig"
    assert len(first) >= MIN_PASSWORD_LENGTH
    assert first != second


@pytest.mark.parametrize("name", ["seed_external_demo.py", "make_demo_accounts_easy.py"])
def test_scripts_contain_no_password_literal(name):
    src = (BACKEND_ROOT / name).read_text(encoding="utf-8")
    assert "demo_password(" in src
    assert not re.search(r"^(INITIAL_PW|DEMO_PW)\s*=\s*['\"]", src, re.M)
    assert not re.search(r"hash_password\(\s*['\"]", src)


def test_staging_script_prints_no_password_literal():
    text = (BACKEND_ROOT.parent / "docs" / "deploy" / "start-external-staging.ps1").read_text(encoding="utf-8")
    login_lines = [ln for ln in text.splitlines() if "Initial-PW" in ln]
    assert login_lines == [
        "Write-Host ' Logins (Initial-PW: Ausgabe von seed_external_demo.py, 2FA-Pflicht beim 1. Login):' -ForegroundColor Green"
    ]


def _run(script: str, db: Path, home: Path, **extra: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items()
           if k not in {"DB_PATH", "DATABASE_URL", "DEMO_INITIAL_PASSWORD", "DEMO_PASSWORD"}}
    env.update({"HOME": str(home), "USERPROFILE": str(home), "PYTHONDONTWRITEBYTECODE": "1"})
    env.update(extra)
    return subprocess.run(
        [sys.executable, str(BACKEND_ROOT / script), str(db)],
        cwd=str(BACKEND_ROOT), env=env, capture_output=True, text=True, timeout=300,
    )


def _hashes(db: Path) -> dict[str, str]:
    conn = sqlite3.connect(db)
    try:
        return dict(conn.execute("SELECT username, password_hash FROM users"))
    finally:
        conn.close()


def test_seed_and_easy_accounts_end_to_end(tmp_path):
    from services.auth import verify_password

    home = tmp_path / "home"
    home.mkdir()
    db = tmp_path / "staging" / "demo.db"
    db.parent.mkdir()

    seeded = _run("seed_external_demo.py", db, home)
    assert seeded.returncode == 0, seeded.stderr[-2000:]
    match = re.search(r"Initial-Passwort fuer die neu angelegten Accounts \(zufaellig[^)]*\): (\S+)", seeded.stdout)
    assert match, seeded.stdout[-2000:]
    printed = match.group(1)
    hashes = _hashes(db)
    assert hashes and all(verify_password(printed, h) for h in hashes.values())

    easy = _run("make_demo_accounts_easy.py", db, home, DEMO_PASSWORD="kollegen-test-passwort")
    assert easy.returncode == 0, easy.stderr[-2000:]
    assert "Passwort fuer ALLE (DEMO_PASSWORD): kollegen-test-passwort" in easy.stdout
    hashes = _hashes(db)
    assert all(verify_password("kollegen-test-passwort", h) for h in hashes.values())
    assert not any(verify_password(printed, h) for h in hashes.values())
