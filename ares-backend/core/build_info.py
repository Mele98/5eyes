"""Build-Kennung des ausgelieferten Artefakts (Release-Readiness H-180, EXE-03).

``ares-desktop/scripts/build-backend.js`` legt ``ares_build_info.json``
(Produktname, Version aus ``ares-desktop/package.json``, Git-SHA des Builds)
in die PyInstaller-EXE. Im Quellbetrieb gibt es die Datei nicht; dann bleibt
es bei ``settings.app_version`` und ``build_sha`` ist ``None``.

Nur Standardbibliothek, keine Import-Seiteneffekte, Ergebnis gecacht.
"""
from __future__ import annotations

import json
import sys
from functools import lru_cache
from pathlib import Path

BUILD_INFO_FILE = "ares_build_info.json"


def _candidates() -> list[Path]:
    paths: list[Path] = []
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        paths.append(Path(bundle) / BUILD_INFO_FILE)
    return paths


@lru_cache(maxsize=1)
def build_info() -> dict | None:
    """``{"product", "version", "git_sha"}`` des gepackten Builds oder ``None``."""
    for path in _candidates():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("version"):
            return {"product": str(data.get("product") or ""), "version": str(data["version"]),
                    "git_sha": str(data.get("git_sha") or "unknown")}
    return None


def effective_version(default: str) -> str:
    info = build_info()
    return info["version"] if info else default


def build_sha() -> str | None:
    info = build_info()
    return info["git_sha"] if info else None
