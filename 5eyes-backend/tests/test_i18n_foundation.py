"""Sprint U-89 (2026-06-06): Drift-Schutz fuer i18n-Foundation-Doku."""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC = REPO_ROOT / "docs" / "I18N.md"
REPORTING_PKG = REPO_ROOT / "5eyes-electron" / "frontend" / "reporting" / "package.json"


def _read() -> str:
    return DOC.read_text(encoding="utf-8")


def test_doc_exists():
    assert DOC.exists()


def test_documents_use_cases():
    text = _read()
    assert "Kunde" in text
    assert "FINMA" in text


def test_documents_react_i18next():
    text = _read()
    assert "react-i18next" in text


def test_documents_5_stage_language_detection_cascade():
    """URL-Param + localStorage + Mandate.advisory_language + navigator + fallback."""
    text = _read()
    assert "localStorage" in text
    assert "Mandate.advisory_language" in text
    assert "navigator.language" in text
    assert "Fallback" in text or "fallback" in text


def test_documents_translation_files_structure():
    text = _read()
    assert "locales/" in text
    assert "common.json" in text


def test_i18next_not_in_package_json():
    """User-Konvention: KEINE neue Dep ohne Auth."""
    pkg = json.loads(REPORTING_PKG.read_text(encoding="utf-8"))
    for deps in (pkg.get("dependencies", {}), pkg.get("devDependencies", {})):
        for name in deps:
            assert "i18next" not in name.lower(), f"i18next-Dep gefunden: {name}"


def test_branding_disziplin_drittmarken_genannt():
    text = _read()
    assert "Drittmarken" in text


def test_branding_disziplin_garantie_sprache_genannt():
    text = _read()
    assert "Garantie-Sprache" in text
    assert "guaranteed" in text or "secured" in text


def test_documents_backend_integration():
    text = _read()
    assert "Mandate.advisory_language" in text
    assert "Aggregator" in text


def test_documents_language_selector_pattern():
    text = _read()
    assert "LanguageSelector" in text
    assert "ThemeToggle" in text  # gleiches Pattern wie U-50


def test_documents_bewusst_nicht_in_scope():
    text = _read()
    assert "Bewusst NICHT" in text
    assert "RTL" in text or "Currency-Format" in text


def test_documents_follow_up_sprints():
    text = _read()
    assert "FR/IT" in text or "FR" in text  # weitere Sprachen
    assert "Anwalts-Review" in text  # legal review fuer FIDLEG


def test_links_to_adr_004_editorial():
    text = _read()
    assert "ADR-004" in text


def test_documents_no_rtl_support_today():
    text = _read()
    assert "RTL" in text  # explizit als out-of-scope
