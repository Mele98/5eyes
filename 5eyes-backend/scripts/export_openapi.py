#!/usr/bin/env python
"""OpenAPI-Schema ohne App-Lifespan exportieren (A3 P0-5, F0-6).

Erzeugt das committete Artefakt ``api/openapi.json`` (Repo-Root) aus
``main.app.openapi()``. Der Lifespan (``init_db``, Seeds, Scheduler) laeuft
dabei NICHT: es wird nur das Modul ``main`` importiert, nie ein Server oder
``TestClient`` gestartet. Zur Sicherheit zeigt ``DB_PATH`` auf eine
Wegwerf-Datei in einem Temp-Verzeichnis; das Skript bricht ab, falls diese
Datei trotzdem angelegt wurde (Import darf keine DB oeffnen).

Deterministisch, unabhaengig von Plattform und Konfiguration:
  * JSON mit sortierten Keys, Einrueckung 2, UTF-8, LF, Schluss-Newline;
  * ``info.title``/``info.version`` aus den Code-Defaults von ``Settings``
    (nicht aus ``.env``/Umgebung), damit eine lokale Konfiguration das
    Artefakt nicht veraendert.

Aufruf (aus Repo-Root oder Backend-Verzeichnis):
    python <backend>/scripts/export_openapi.py           # Artefakt schreiben
    python <backend>/scripts/export_openapi.py --check   # Drift pruefen (Exit 1)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
ARTIFACT_PATH = REPO_ROOT / "api" / "openapi.json"
REGENERATE_HINT = "python " + "/".join(
    (BACKEND_DIR.name, "scripts", Path(__file__).name)
)

# Umgebungsvariablen, die den Import auf eine echte Datenbank lenken koennten.
_DB_ENV_OVERRIDES = ("DATABASE_URL", "DB_KEY", "DB_USE_SQLCIPHER")


def build_schema() -> dict:
    """Schema frisch aus dem Code erzeugen, ohne Lifespan und ohne DB."""
    with tempfile.TemporaryDirectory(prefix="openapi-export-") as tmp:
        sentinel_db = Path(tmp) / "must-not-exist.db"
        os.environ["DB_PATH"] = str(sentinel_db)
        for key in _DB_ENV_OVERRIDES:
            os.environ.pop(key, None)
        if str(BACKEND_DIR) not in sys.path:
            sys.path.insert(0, str(BACKEND_DIR))

        from config import Settings  # noqa: E402
        from main import app  # noqa: E402

        schema = json.loads(json.dumps(app.openapi()))
        if sentinel_db.exists():
            raise RuntimeError(
                f"Import von main hat eine Datenbank angelegt ({sentinel_db}); "
                "der OpenAPI-Export muss ohne DB-Zugriff laufen."
            )
    schema["info"]["title"] = Settings.model_fields["app_name"].default
    schema["info"]["version"] = Settings.model_fields["app_version"].default
    return schema


def render(schema: dict) -> bytes:
    text = json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False)
    return (text + "\n").encode("utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="Nur vergleichen; Exit 1, wenn das Artefakt veraltet ist.",
    )
    args = parser.parse_args(argv)

    fresh = render(build_schema())
    if args.check:
        current = ARTIFACT_PATH.read_bytes() if ARTIFACT_PATH.is_file() else b""
        if current != fresh:
            print(
                f"OpenAPI-Artefakt {ARTIFACT_PATH.relative_to(REPO_ROOT).as_posix()} "
                "ist veraltet (Schema geaendert, Artefakt nicht nachgezogen).\n"
                f"Neu erzeugen und committen: {REGENERATE_HINT}",
                file=sys.stderr,
            )
            return 1
        print("OpenAPI-Artefakt ist aktuell.")
        return 0

    ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT_PATH.write_bytes(fresh)
    print(f"geschrieben: {ARTIFACT_PATH.relative_to(REPO_ROOT).as_posix()} ({len(fresh)} Bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
