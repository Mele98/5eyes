"""Sprint U-88 (2026-06-06): Drift-Schutz fuer Service-Worker Foundation-Doku."""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC = REPO_ROOT / "docs" / "OFFLINE_MODE.md"
REPORTING_PKG = REPO_ROOT / "5eyes-electron" / "frontend" / "reporting" / "package.json"


def _read() -> str:
    return DOC.read_text(encoding="utf-8")


def test_doc_exists():
    assert DOC.exists()


def test_documents_use_case():
    text = _read()
    assert "Berater" in text
    assert "Beratungsgespraech" in text or "Mobile" in text


def test_documents_network_first_strategy():
    text = _read()
    assert "Network-First" in text
    assert "NetworkFirst" in text


def test_documents_cache_ttl():
    text = _read()
    assert "1 Stunde" in text or "3600" in text


def test_documents_vite_plugin_pwa():
    text = _read()
    assert "vite-plugin-pwa" in text


def test_vite_plugin_pwa_not_in_package_json():
    """User-Konvention: KEINE neue Dep ohne Auth."""
    pkg = json.loads(REPORTING_PKG.read_text(encoding="utf-8"))
    dev_deps = pkg.get("devDependencies", {})
    deps = pkg.get("dependencies", {})
    assert "vite-plugin-pwa" not in dev_deps
    assert "vite-plugin-pwa" not in deps


def test_documents_bearer_token_security():
    text = _read()
    assert "Bearer-Token" in text or "Token" in text
    assert "sessionStorage" in text


def test_documents_cache_invalidation_at_logout():
    text = _read()
    assert "caches.delete" in text or "Cache-Invalidation" in text


def test_documents_no_push_notifications_adr_003():
    """ADR-003 verbietet Markt-Timing-Alarme."""
    text = _read()
    assert "Push-Notifications" in text or "ADR-003" in text


def test_documents_bewusst_nicht_in_scope():
    text = _read()
    assert "Bewusst NICHT" in text
    assert "package.json" in text


def test_links_to_handoff_module():
    text = _read()
    assert "handoff.ts" in text


def test_documents_offline_status_indicator_aria_live():
    """Offline-Status muss a11y-compatible sein (U-90 Folge)."""
    text = _read()
    assert "aria-live" in text or "role=\"status\"" in text or "role='status'" in text
