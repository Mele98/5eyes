"""Vertrag des Backend-Executable-Namens ueber Build, Bundle und Start.

PyInstaller erzeugt ``ares-api.exe``; build-backend.js kopiert genau diese
Datei nach ``bundle/backend``; electron-builder packt den Ordner per
``extraResources`` nach ``resources/backend``; main.js startet genau diese
Datei; release-check.js prueft sie vor dem Packen. Weicht einer der Namen
ab, startet die gepackte App kein Backend.

Der Vertrag gilt ausdruecklich nur fuer Windows (W2-804-03): Ares wird nur
fuer Windows ausgeliefert. Damit der ``.exe``-Name nicht still auch fuer
andere Plattformen festgeschrieben wird, prueft jede der drei Stellen die
Plattform und bricht ausserhalb von ``win32`` ab, bevor sie den Namen
verwendet; ``package.json`` bewirbt keine Nicht-Windows-Targets (siehe
``test_desktop_windows_only_contract.py``).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

DESKTOP_ROOT = Path(__file__).resolve().parents[2] / "ares-desktop"
EXE_NAME = "ares-api"


def _read(relative: str) -> str:
    return (DESKTOP_ROOT / relative).read_text(encoding="utf-8")


def test_pyinstaller_name_and_dist_copy_match():
    src = _read("scripts/build-backend.js")
    assert re.search(r"'--name',\s*'" + EXE_NAME + r"'", src)
    assert f"path.join(backendRoot, 'dist', '{EXE_NAME}.exe')" in src
    assert f"path.join(backendRoot, '{EXE_NAME}.spec')" in src
    assert f"copyIfExists(distExe, path.join(bundleBackendDir, '{EXE_NAME}.exe'))" in src


def test_extra_resources_ship_bundle_backend_folder():
    pkg = json.loads(_read("package.json"))
    resources = pkg["build"]["extraResources"]
    assert {"from": "bundle/backend", "to": "backend", "filter": ["**/*"]} in resources


def test_electron_spawns_the_bundled_exe():
    src = _read("main.js")
    assert f"path.join(process.resourcesPath, 'backend', '{EXE_NAME}.exe')" in src


def test_release_check_requires_the_bundled_exe():
    src = _read("scripts/release-check.js")
    assert f"path.join(projectRoot, 'bundle', 'backend', '{EXE_NAME}.exe')" in src


def test_no_other_exe_name_in_desktop_scripts():
    names = set()
    for rel in ("main.js", "scripts/build-backend.js", "scripts/release-check.js"):
        names |= set(re.findall(r"'([\w.-]+)\.exe'", _read(rel)))
    assert names == {EXE_NAME}


def test_exe_name_is_only_used_behind_a_windows_guard():
    """Jede Stelle, die ``ares-api.exe`` erwartet, prueft vorher ``win32``."""
    guard = re.compile(r"process\.platform\s*!==\s*'win32'")
    for rel in ("main.js", "scripts/build-backend.js", "scripts/release-check.js"):
        src = _read(rel)
        if rel == "main.js":
            body = re.search(
                r"function resolvePackagedBackendExe\(\)\s*\{(?P<body>.*?)\n\}", src, re.S
            )
            assert body is not None
            src = body.group("body")
        match = guard.search(src)
        assert match is not None, f"{rel}: keine Windows-Plattformpruefung"
        assert match.start() < src.index(f"{EXE_NAME}.exe"), (
            f"{rel}: {EXE_NAME}.exe wird vor der Plattformpruefung verwendet"
        )


def test_no_non_windows_release_target_shares_the_exe_contract():
    pkg = json.loads(_read("package.json"))
    assert not any(name.startswith(("dist:mac", "dist:linux")) for name in pkg["scripts"])
    assert "mac" not in pkg["build"] and "linux" not in pkg["build"]
