"""Drift-Schutz fuer den Plattformumfang des Desktop-Builds.

Sprint U-108 (2026-06-06) hatte macOS-/Linux-Targets eingefuehrt, die aber
nie einen nativen Backend-Pfad besassen (sie haetten die Windows-EXE
erwartet). W2-804-03 begrenzt das Release ehrlich auf Windows; diese Tests
sichern Konfiguration und Doku gegen ein stilles Wiederaufleben ab. Der
technische Vertrag liegt in ``test_desktop_windows_only_contract.py``.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ELECTRON_PKG = REPO_ROOT / "ares-desktop" / "package.json"
MULTI_PLATFORM_DOC = REPO_ROOT / "docs" / "MULTI_PLATFORM_BUILD.md"


def _pkg() -> dict:
    return json.loads(ELECTRON_PKG.read_text(encoding="utf-8"))


def test_doc_exists():
    assert MULTI_PLATFORM_DOC.exists()


def test_package_json_has_no_dist_mac_or_linux_script():
    scripts = _pkg().get("scripts", {})
    assert "dist:mac" not in scripts
    assert "dist:linux" not in scripts


def test_package_json_has_no_mac_or_linux_build_config():
    build = _pkg().get("build", {})
    assert "mac" not in build
    assert "linux" not in build


def test_win_build_config_preserved():
    """Die Windows-Konfiguration bleibt der einzige Release-Pfad."""
    pkg = _pkg()
    win = pkg.get("build", {}).get("win", {})
    assert win.get("target")
    assert any(t.get("target") == "nsis" for t in win["target"])
    assert "dist:win" in pkg["scripts"]
    assert "dist:win:portable" in pkg["scripts"]


def test_doc_declares_windows_only():
    text = MULTI_PLATFORM_DOC.read_text(encoding="utf-8")
    assert "nur fuer Windows" in text
    assert "W2-804-03" in text


def test_doc_advertises_no_non_windows_build_command():
    text = MULTI_PLATFORM_DOC.read_text(encoding="utf-8")
    for advertised in ("npm run dist:mac", "npm run dist:linux", "latest-mac.yml", "latest-linux.yml"):
        assert advertised not in text


def test_doc_links_to_auto_update_and_code_signing():
    text = MULTI_PLATFORM_DOC.read_text(encoding="utf-8")
    assert "AUTO_UPDATE.md" in text
    assert "CODE_SIGNING.md" in text


def test_package_and_lockfile_names_match():
    """npm-Name des Desktop-Pakets steht gleich in package.json und Lockfile."""
    pkg = _pkg()
    lock = json.loads((ELECTRON_PKG.parent / "package-lock.json").read_text(encoding="utf-8"))
    assert pkg["name"] == "ares-desktop"
    assert lock["name"] == pkg["name"]
    assert lock["packages"][""]["name"] == pkg["name"]
