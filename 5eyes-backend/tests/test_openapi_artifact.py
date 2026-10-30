"""OpenAPI-Artefakt und lifespan-freier Import (A3 P0-5, F0-6).

1. Der Import von ``main`` darf keine Datenbank oeffnen oder anlegen
   (Incident 2026-10-15: Tests trafen die Live-DB). Nur der Lifespan darf
   ``init_db`` ausfuehren.
2. ``api/openapi.json`` muss byte-identisch zum frisch exportierten Schema
   sein; sonst ist das Artefakt veraltet (Regeneration: siehe
   ``scripts/export_openapi.py``).
3. Das Artefakt ist deterministisch formatiert (sortierte Keys, UTF-8, LF).

Import und Export laufen in einem frischen Interpreter, damit weder bereits
importierte Module noch Test-Overrides am ``app``-Objekt das Ergebnis faerben.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
EXPORT_SCRIPT = BACKEND_DIR / "scripts" / "export_openapi.py"
ARTIFACT = BACKEND_DIR.parent / "api" / "openapi.json"


def _isolated_env(db_path: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["DB_PATH"] = str(db_path)
    for key in ("DATABASE_URL", "DB_KEY", "DB_USE_SQLCIPHER"):
        env.pop(key, None)
    return env


def test_import_main_does_not_open_database(tmp_path):
    db_file = tmp_path / "never-created" / "app.db"
    probe = (
        "import main; "
        "print('routes', len(main.app.routes))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=BACKEND_DIR,
        env=_isolated_env(db_file),
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stderr[-4000:]
    assert "routes" in result.stdout
    created = [p.name for p in db_file.parent.glob("app.db*")] if db_file.parent.exists() else []
    assert created == [], (
        f"Import von main hat Datenbankdateien angelegt: {created}. "
        "DB-Zugriff gehoert in den Lifespan (init_db), nicht in den Modul-Import."
    )


def test_openapi_artifact_matches_fresh_export(tmp_path):
    result = subprocess.run(
        [sys.executable, str(EXPORT_SCRIPT), "--check"],
        cwd=BACKEND_DIR,
        env=_isolated_env(tmp_path / "unused.db"),
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, (
        "OpenAPI-Artefakt api/openapi.json weicht vom Code ab. Neu erzeugen mit "
        "`python scripts/export_openapi.py` (aus dem Backend-Verzeichnis) und committen.\n"
        + result.stderr[-4000:]
    )


def test_openapi_artifact_is_deterministically_formatted():
    raw = ARTIFACT.read_bytes()
    assert b"\r" not in raw, "Artefakt muss LF-Zeilenenden haben (kein CRLF)."
    assert raw.endswith(b"\n") and not raw.endswith(b"\n\n")
    schema = json.loads(raw.decode("utf-8"))
    canonical = json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    assert raw == canonical.encode("utf-8"), "Artefakt ist nicht kanonisch sortiert/formatiert."
    assert schema["openapi"].startswith("3.")
    assert schema["paths"], "Artefakt enthaelt keine Pfade."
