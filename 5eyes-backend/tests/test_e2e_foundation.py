"""Sprint U-55 (2026-06-06): Drift-Schutz fuer E2E-Testing Foundation-Doku."""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC = REPO_ROOT / "docs" / "E2E_TESTING.md"
REPORTING_PKG = REPO_ROOT / "5eyes-electron" / "frontend" / "reporting" / "package.json"


def _read() -> str:
    return DOC.read_text(encoding="utf-8")


def test_doc_exists():
    assert DOC.exists()


def test_documents_why_e2e():
    text = _read()
    assert "vitest" in text
    assert "End-to-End" in text or "Berater-End-to-End-Flow" in text


def test_documents_playwright_over_cypress():
    text = _read()
    assert "Playwright" in text
    assert "Cypress" in text  # explizit verglichen


def test_playwright_not_in_package_json():
    pkg = json.loads(REPORTING_PKG.read_text(encoding="utf-8"))
    for deps in (pkg.get("dependencies", {}), pkg.get("devDependencies", {})):
        assert "@playwright/test" not in deps
        assert "playwright" not in deps


def test_documents_5_smoke_tests():
    text = _read()
    # Smoke-Test-Themen
    assert "Sub-App Boot" in text or "Boot" in text
    assert "Sidebar-Click" in text or "Sidebar" in text
    assert "Token" in text
    assert "Client-Portal" in text  # U-36


def test_documents_ci_integration_concept():
    text = _read()
    assert ".github/workflows/e2e.yml" in text
    assert "playwright test" in text


def test_documents_foundation_example_test_seed():
    text = _read()
    assert "foundation-example" in text


def test_documents_cost_discipline_no_chromatic():
    """ADR-005 CHF-0 verbietet Chromatic."""
    text = _read()
    assert "Chromatic" in text
    assert "ADR-005" in text


def test_documents_bewusst_nicht_in_scope():
    text = _read()
    assert "Bewusst NICHT" in text
    assert "package.json" in text


def test_documents_test_struktur():
    text = _read()
    assert "playwright.config.ts" in text
    assert "specs/" in text


def test_links_to_other_qa_strategies():
    text = _read()
    assert "#106" in text or "Mutation" in text
    assert "#107" in text or "Property" in text


def test_documents_electron_main_process_as_followup():
    text = _read()
    assert "electron-playwright" in text or "Electron-Main-Process" in text
