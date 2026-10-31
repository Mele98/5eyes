"""W2-804-03: Das Desktop-Release ist ehrlich auf Windows begrenzt.

Produktentscheid: Ares wird nur fuer Windows ausgeliefert. Der gesamte
Release-Pfad (PyInstaller-Build, Bundle, Preflight, Start der gepackten App)
kennt genau ein natives Backend-Artefakt, ``ares-api.exe``. Frueher bewarb
``package.json`` zusaetzlich macOS-/Linux-Targets, die still dieselbe
Windows-Datei erwartet, kopiert und gestartet haetten.

Vertrag:

* ``package.json`` bewirbt kein Nicht-Windows-Target, weder als npm-Script
  noch als electron-builder-Plattformblock;
* jeder electron-builder-Aufruf ist auf Windows (``--win``) oder das lokale
  ``--dir``-Staging begrenzt;
* ``build-backend.js``, ``release-check.js`` und der Packaged-Resolver in
  ``main.js`` pruefen die Plattform und brechen ausserhalb von Windows mit
  klarer Meldung ab, statt still eine ``.exe`` zu erwarten.

Abgeleitet aus dem Abnahme-Reproducer
``test_advertised_desktop_targets_resolve_native_backend_names``; dieser
verlangte als eine von zwei zulaessigen Loesungen native Namen pro Plattform.
Gewaehlt ist die andere Loesung (Windows-only), daher prueft dieser Vertrag
die Abwesenheit beworbener Nicht-Windows-Targets plus die Plattformpruefung.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

DESKTOP_ROOT = Path(__file__).resolve().parents[2] / "ares-desktop"

# electron-builder-Plattformschluessel und Target-Namen ausserhalb von Windows.
NON_WINDOWS_BUILD_KEYS = {
    "mac",
    "mas",
    "masDev",
    "dmg",
    "pkg",
    "linux",
    "appImage",
    "snap",
    "deb",
    "rpm",
    "flatpak",
    "pacman",
    "freebsd",
    "apk",
    "p5p",
}
NON_WINDOWS_CLI = re.compile(
    r"(?<![\w-])(--mac|--macos|--linux|-m|-l|-mwl|-mw|-ml|-wl)(?![\w-])"
    r"|\b(dmg|AppImage|snap|deb|rpm|flatpak|pacman|mas)\b"
)
NON_WINDOWS_SCRIPT_NAME = re.compile(r"(mac|darwin|linux|appimage|dmg)", re.I)
PLATFORM_GUARD = re.compile(r"process\.platform\s*!==\s*'win32'")


def _read(relative: str) -> str:
    return (DESKTOP_ROOT / relative).read_text(encoding="utf-8")


def _package() -> dict:
    return json.loads(_read("package.json"))


def _node() -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node binary not available")
    return node


def _run_with_platform(script: Path, platform: str) -> subprocess.CompletedProcess:
    """Fuehrt ein Desktop-Skript mit ueberschriebenem ``process.platform`` aus."""
    loader = (
        "Object.defineProperty(process, 'platform', { value: process.argv[1] });"
        "require(process.argv[2]);"
    )
    return subprocess.run(
        [_node(), "-e", loader, platform, str(script)],
        cwd=str(DESKTOP_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )


def test_package_scripts_advertise_no_non_windows_target():
    scripts = _package()["scripts"]
    advertised = sorted(name for name in scripts if NON_WINDOWS_SCRIPT_NAME.search(name))
    assert advertised == [], f"Nicht-Windows-Release-Scripts beworben: {advertised}"
    offenders = {
        name: cmd for name, cmd in scripts.items() if NON_WINDOWS_CLI.search(cmd)
    }
    assert offenders == {}, f"Scripts mit Nicht-Windows-Targets: {offenders}"


def test_every_electron_builder_call_is_windows_or_dir_staging():
    scripts = _package()["scripts"]
    builder_calls = {
        name: cmd.split("electron-builder", 1)[1]
        for name, cmd in scripts.items()
        if "electron-builder" in cmd
    }
    assert {"pack", "dist:win", "dist:win:portable"} <= set(builder_calls)
    for name, args in builder_calls.items():
        assert re.search(r"(?<![\w-])(--win|--dir)(?![\w-])", args), (
            f"{name}: electron-builder ohne --win/--dir baut fuer die Host-Plattform"
        )


def test_builder_config_has_only_windows_platform_blocks():
    build = _package()["build"]
    assert sorted(NON_WINDOWS_BUILD_KEYS & set(build)) == []
    win_targets = {t["target"] for t in build["win"]["target"]}
    assert win_targets == {"nsis", "portable"}


def test_packaged_backend_resolver_checks_platform():
    main = _read("main.js")
    resolver = re.search(
        r"function resolvePackagedBackendExe\(\)\s*\{(?P<body>.*?)\n\}",
        main,
        re.S,
    )
    assert resolver is not None
    body = resolver.group("body")
    assert PLATFORM_GUARD.search(body), "Resolver prueft die Plattform nicht"
    assert "throw new Error" in body
    # Kein stiller Pfad fuer andere Plattformen: der Resolver kennt nur win32.
    assert "darwin" not in body and "linux" not in body
    guard_pos = PLATFORM_GUARD.search(body).start()
    assert guard_pos < body.index("ares-api.exe")


def test_build_backend_aborts_before_any_filesystem_change():
    src = _read("scripts/build-backend.js")
    guard = PLATFORM_GUARD.search(src)
    assert guard is not None, "build-backend.js prueft die Plattform nicht"
    # Der Guard muss vor dem ersten Top-Level-Loeschen (Build-/Dist-/Bundle-
    # Ordner) und damit vor jedem PyInstaller-Lauf ausgewertet werden.
    assert guard.start() < src.index("\nfs.rmSync(")
    assert re.search(r"process\.exit\(1\)", src[guard.start() : src.index("\nfs.rmSync(")])


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_build_backend_rejects_non_windows_at_runtime(platform):
    # Erst der statische Vertrag: ohne Guard vor dem ersten rmSync wuerde der
    # Lauf Build-Ordner loeschen und PyInstaller starten.
    test_build_backend_aborts_before_any_filesystem_change()
    result = _run_with_platform(DESKTOP_ROOT / "scripts" / "build-backend.js", platform)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "nur fuer Windows" in result.stderr
    assert platform in result.stderr


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_release_check_rejects_non_windows(platform):
    result = _run_with_platform(DESKTOP_ROOT / "scripts" / "release-check.js", platform)
    assert result.returncode == 1, result.stdout + result.stderr
    errors = [line for line in result.stderr.splitlines() if line.startswith("FEHLER:")]
    assert errors, result.stderr
    assert "nur fuer Windows" in errors[0]
    assert platform in errors[0]


def test_release_check_has_no_platform_error_on_windows():
    result = _run_with_platform(DESKTOP_ROOT / "scripts" / "release-check.js", "win32")
    assert "nur fuer Windows" not in result.stderr
