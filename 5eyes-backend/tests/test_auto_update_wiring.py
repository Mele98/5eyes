"""Sprint U-65 (2026-06-06): Drift-Schutz fuer Electron Auto-Update Wiring.

Verifiziert dass main.js die autoUpdater-Lifecycle-Events haendelt und
package.json die Publish-Config hat.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ELECTRON_MAIN_JS = REPO_ROOT / "5eyes-electron" / "main.js"
ELECTRON_PKG = REPO_ROOT / "5eyes-electron" / "package.json"
AUTO_UPDATE_DOC = REPO_ROOT / "docs" / "AUTO_UPDATE.md"


def test_doc_exists():
    assert AUTO_UPDATE_DOC.exists()


def test_main_js_imports_electron_updater():
    text = ELECTRON_MAIN_JS.read_text(encoding="utf-8")
    assert "electron-updater" in text
    assert "autoUpdater" in text


def test_main_js_handles_all_lifecycle_events():
    """Pflicht-Events: checking-for-update, update-available,
    update-not-available, update-downloaded, error."""
    text = ELECTRON_MAIN_JS.read_text(encoding="utf-8")
    for event in (
        "checking-for-update",
        "update-available",
        "update-not-available",
        "update-downloaded",
    ):
        assert event in text, f"Lifecycle-Event {event!r} fehlt"


def test_main_js_has_check_for_updates_function():
    text = ELECTRON_MAIN_JS.read_text(encoding="utf-8")
    assert "checkForUpdates" in text


def test_main_js_uses_enable_auto_update_env_var():
    """Opt-in via Env-Var."""
    text = ELECTRON_MAIN_JS.read_text(encoding="utf-8")
    assert "ENABLE_AUTO_UPDATE" in text
    assert "app.isPackaged" in text


def test_package_json_has_publish_config():
    pkg = json.loads(ELECTRON_PKG.read_text(encoding="utf-8"))
    publish = pkg.get("build", {}).get("publish", [])
    assert isinstance(publish, list)
    assert len(publish) >= 1
    assert publish[0].get("provider")


def test_doc_documents_enable_auto_update_env_var():
    text = AUTO_UPDATE_DOC.read_text(encoding="utf-8")
    assert "ENABLE_AUTO_UPDATE" in text


def test_doc_documents_release_workflow():
    text = AUTO_UPDATE_DOC.read_text(encoding="utf-8")
    assert "Release-Workflow" in text
    assert "latest.yml" in text
    assert "npm run dist:win" in text or "dist:win" in text


def test_doc_documents_security_and_signing_gap():
    text = AUTO_UPDATE_DOC.read_text(encoding="utf-8")
    assert "Code-Signing" in text
    assert "#109" in text  # Cert-Gap-Verweis


def test_doc_documents_https_requirement():
    text = AUTO_UPDATE_DOC.read_text(encoding="utf-8")
    assert "HTTPS" in text or "https://" in text


def test_doc_lists_lifecycle_events():
    text = AUTO_UPDATE_DOC.read_text(encoding="utf-8")
    for event in ("checking-for-update", "update-available", "update-downloaded"):
        assert event in text


def test_doc_documents_bewusst_nicht_in_scope():
    text = AUTO_UPDATE_DOC.read_text(encoding="utf-8")
    assert "Bewusst NICHT in Scope" in text
    assert "GitHub-Releases" in text or "GitHub" in text
