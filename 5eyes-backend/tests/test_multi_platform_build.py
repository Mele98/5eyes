"""Sprint U-108 (2026-06-06): Drift-Schutz fuer Multi-Platform Build."""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ELECTRON_PKG = REPO_ROOT / "5eyes-electron" / "package.json"
MULTI_PLATFORM_DOC = REPO_ROOT / "docs" / "MULTI_PLATFORM_BUILD.md"


def test_doc_exists():
    assert MULTI_PLATFORM_DOC.exists()


def test_package_json_has_dist_mac_script():
    pkg = json.loads(ELECTRON_PKG.read_text(encoding="utf-8"))
    scripts = pkg.get("scripts", {})
    assert "dist:mac" in scripts
    assert "dmg" in scripts["dist:mac"]


def test_package_json_has_dist_linux_script():
    pkg = json.loads(ELECTRON_PKG.read_text(encoding="utf-8"))
    scripts = pkg.get("scripts", {})
    assert "dist:linux" in scripts
    assert "AppImage" in scripts["dist:linux"]


def test_package_json_has_mac_build_config():
    pkg = json.loads(ELECTRON_PKG.read_text(encoding="utf-8"))
    mac = pkg.get("build", {}).get("mac", {})
    assert mac.get("target")
    targets = mac["target"]
    assert any(t.get("target") == "dmg" for t in targets)


def test_mac_supports_x64_and_arm64():
    pkg = json.loads(ELECTRON_PKG.read_text(encoding="utf-8"))
    archs = pkg["build"]["mac"]["target"][0]["arch"]
    assert "x64" in archs
    assert "arm64" in archs


def test_package_json_has_linux_build_config():
    pkg = json.loads(ELECTRON_PKG.read_text(encoding="utf-8"))
    linux = pkg.get("build", {}).get("linux", {})
    assert linux.get("target")
    assert any(t.get("target") == "AppImage" for t in linux["target"])


def test_win_build_config_preserved():
    """U-108 darf bestehende Windows-Config nicht brechen."""
    pkg = json.loads(ELECTRON_PKG.read_text(encoding="utf-8"))
    win = pkg.get("build", {}).get("win", {})
    assert win.get("target")
    assert any(t.get("target") == "nsis" for t in win["target"])


def test_doc_documents_all_3_platforms():
    text = MULTI_PLATFORM_DOC.read_text(encoding="utf-8")
    assert "Windows" in text
    assert "macOS" in text
    assert "Linux" in text


def test_doc_documents_ci_matrix_as_future():
    """CI-Matrix als Folge-Sprint dokumentiert (nicht in U-108)."""
    text = MULTI_PLATFORM_DOC.read_text(encoding="utf-8")
    assert "CI-Build-Matrix" in text or "matrix" in text


def test_doc_documents_auto_update_per_platform():
    text = MULTI_PLATFORM_DOC.read_text(encoding="utf-8")
    assert "latest-mac.yml" in text
    assert "latest-linux.yml" in text


def test_doc_documents_bewusst_nicht_in_scope():
    text = MULTI_PLATFORM_DOC.read_text(encoding="utf-8")
    assert "Bewusst NICHT" in text
    assert "Notarization" in text or "Snap" in text


def test_doc_links_to_auto_update():
    text = MULTI_PLATFORM_DOC.read_text(encoding="utf-8")
    assert "AUTO_UPDATE.md" in text


def test_doc_links_to_code_signing_gap():
    text = MULTI_PLATFORM_DOC.read_text(encoding="utf-8")
    assert "#109" in text
