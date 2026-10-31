"""W2-804-04: Interne npm-Pakete sind gegen ``npm publish`` gesperrt.

Alle ``package.json`` im Repository beschreiben interne Pakete (Desktop-Shell,
Reporting-Sub-App); keines wird in eine Registry veroeffentlicht, kein
Workflow und kein Skript ruft ``npm publish`` auf. ``"private": true`` ist
die von npm selbst erzwungene Sperre: ``npm publish`` bricht damit ab, auch
bei versehentlichem Aufruf mit gueltigem Registry-Token. ``"license":
"UNLICENSED"`` allein verhindert keinen Publish.

Der Vertrag erfasst jede ``package.json`` ausserhalb von ``node_modules``,
damit ein spaeter hinzugefuegtes Paket nicht still ohne Sperre bleibt.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DESKTOP_PACKAGE = REPO_ROOT / "ares-desktop" / "package.json"
EXCLUDED_PARTS = {"node_modules", ".git", "dist", "build", "bundle", ".venv", "venv"}


def _repo_package_files() -> list[Path]:
    # os.walk mit Pruning statt rglob: node_modules wird gar nicht betreten.
    found = []
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_PARTS]
        if "package.json" in filenames:
            found.append(Path(dirpath) / "package.json")
    return sorted(found)


def _publish_protection_errors(rel: str, package: dict) -> list[str]:
    errors = []
    if package.get("private") is not True:
        errors.append(f"{rel}: \"private\": true fehlt (npm publish nicht gesperrt)")
    if "publishConfig" in package:
        errors.append(f"{rel}: publishConfig deutet auf einen Registry-Publish hin")
    return errors


def test_internal_desktop_package_is_publish_protected():
    """Abnahme-Reproducer W2-804-04, unveraendert uebernommen."""
    package = json.loads(DESKTOP_PACKAGE.read_text(encoding="utf-8"))
    assert package.get("private") is True


def test_every_repo_package_is_publish_protected():
    files = _repo_package_files()
    rels = {path.relative_to(REPO_ROOT).as_posix() for path in files}
    # Bekannte interne Pakete muessen erfasst sein, sonst ist der Scan blind.
    assert {
        "ares-desktop/package.json",
        "ares-desktop/frontend/reporting/package.json",
    } <= rels
    errors = []
    for path in files:
        rel = path.relative_to(REPO_ROOT).as_posix()
        errors += _publish_protection_errors(rel, json.loads(path.read_text(encoding="utf-8")))
    assert errors == []


def test_protection_check_rejects_unprotected_package():
    """Negativkontrolle: der Pruefer erkennt eine fehlende oder falsche Sperre."""
    assert _publish_protection_errors("x/package.json", {"name": "x", "license": "UNLICENSED"})
    assert _publish_protection_errors("x/package.json", {"name": "x", "private": "true"})
    assert _publish_protection_errors(
        "x/package.json", {"name": "x", "private": True, "publishConfig": {"access": "public"}}
    )
    assert _publish_protection_errors("x/package.json", {"name": "x", "private": True}) == []
