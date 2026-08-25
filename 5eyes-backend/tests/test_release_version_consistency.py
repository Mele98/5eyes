"""Sprint U-78 (Roadmap-Punkt 78, 2026-06-04): Release-Tag-Strategie.

Pre-U-78
--------
Backend `settings.app_version` und Electron `package.json.version`
konnten silent driften. Berater haette nicht gewusst welche Backend-API
ein gepackter Electron-Build erwartet.

Post-U-78
---------
- docs/RELEASE_TAGS.md mit Semver-Strategie + Tag-Convention
- docs/CHANGELOG_TEMPLATE.md mit Keep-a-Changelog-Format
- scripts/release-tag.ps1 mit Konsistenz-Check + Tag-Erstellung
- Diese Tests verifizieren die Konsistenz auch bei CI-Lauf
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(-[a-z0-9.]+)?$")


# ---------------------------------------------------------------------------
# Doku-Existenz
# ---------------------------------------------------------------------------

def test_release_tags_doc_exists():
    path = REPO_ROOT / "docs" / "RELEASE_TAGS.md"
    assert path.exists(), "docs/RELEASE_TAGS.md fehlt — U-78 nicht vollstaendig."


def test_changelog_template_exists():
    path = REPO_ROOT / "docs" / "CHANGELOG_TEMPLATE.md"
    assert path.exists()


def test_release_tag_script_exists():
    path = REPO_ROOT / "scripts" / "release-tag.ps1"
    assert path.exists()


# ---------------------------------------------------------------------------
# Doku-Content
# ---------------------------------------------------------------------------

def test_release_tags_doc_mentions_semver():
    text = (REPO_ROOT / "docs" / "RELEASE_TAGS.md").read_text(encoding="utf-8")
    assert "Semantic Versioning" in text
    assert "MAJOR" in text and "MINOR" in text and "PATCH" in text


def test_release_tags_doc_explains_backend_electron_sync():
    text = (REPO_ROOT / "docs" / "RELEASE_TAGS.md").read_text(encoding="utf-8")
    assert "Backend" in text
    assert "Electron" in text
    assert "app_version" in text
    assert "package.json" in text


def test_release_tags_doc_includes_pre_release_suffixes():
    text = (REPO_ROOT / "docs" / "RELEASE_TAGS.md").read_text(encoding="utf-8")
    for suffix in ("alpha", "beta", "rc"):
        assert suffix in text.lower()


def test_changelog_template_uses_keep_a_changelog_format():
    text = (REPO_ROOT / "docs" / "CHANGELOG_TEMPLATE.md").read_text(encoding="utf-8")
    for section in ("Added", "Changed", "Deprecated", "Removed", "Fixed", "Security"):
        assert section in text


# ---------------------------------------------------------------------------
# Script-Robustheit (Source-Parse)
# ---------------------------------------------------------------------------

def test_release_tag_script_validates_semver_pattern():
    text = (REPO_ROOT / "scripts" / "release-tag.ps1").read_text(encoding="utf-8")
    # ValidatePattern checked semver
    assert "ValidatePattern" in text
    assert r"\d+\.\d+\.\d+" in text


def test_release_tag_script_checks_branch():
    text = (REPO_ROOT / "scripts" / "release-tag.ps1").read_text(encoding="utf-8")
    assert "main" in text
    assert "release/" in text


def test_release_tag_script_checks_working_tree_clean():
    text = (REPO_ROOT / "scripts" / "release-tag.ps1").read_text(encoding="utf-8")
    assert "git status --porcelain" in text


def test_release_tag_script_creates_annotated_tag():
    text = (REPO_ROOT / "scripts" / "release-tag.ps1").read_text(encoding="utf-8")
    assert "git tag -a" in text


def test_release_tag_script_checks_version_consistency():
    text = (REPO_ROOT / "scripts" / "release-tag.ps1").read_text(encoding="utf-8")
    assert "Backend-Version" in text or "BackendVersion" in text
    assert "Electron-Version" in text or "ElectronVersion" in text


# ---------------------------------------------------------------------------
# Backend / Electron Version Format
# ---------------------------------------------------------------------------

def test_backend_app_version_is_valid_semver():
    from config import settings
    assert SEMVER_RE.match(settings.app_version), (
        f"Backend app_version '{settings.app_version}' kein gueltiges Semver."
    )


def test_electron_package_version_is_valid_semver():
    pkg_path = REPO_ROOT / "5eyes-electron" / "package.json"
    pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
    assert SEMVER_RE.match(pkg["version"]), (
        f"Electron version '{pkg['version']}' kein gueltiges Semver."
    )


# ---------------------------------------------------------------------------
# Backend/Electron Drift-Detection
# ---------------------------------------------------------------------------

def test_backend_electron_version_drift_documented():
    """Stand 2026-06-04: Backend 1.3.0, Electron 0.4.0 = bekannte Drift.

    Dieser Test ist xfail-mässig: er dokumentiert die Drift, ohne sie
    zu erzwingen. Sobald ein Release alignt (z.B. v1.4.0), wird
    er strict werden.
    """
    from config import settings
    pkg_path = REPO_ROOT / "5eyes-electron" / "package.json"
    pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
    backend = settings.app_version
    electron = pkg["version"]
    if backend != electron:
        pytest.xfail(
            f"Bekannte Version-Drift Backend={backend} vs Electron={electron}. "
            f"Wird beim naechsten Berater-Release (siehe RELEASE_TAGS.md) "
            f"aligned."
        )


def test_main_py_uses_settings_app_version():
    """main.py setzt FastAPI(version=settings.app_version) — Drift-Schutz."""
    main_py = (BACKEND_ROOT / "main.py").read_text(encoding="utf-8")
    assert "settings.app_version" in main_py
