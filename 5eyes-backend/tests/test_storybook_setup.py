"""Sprint U-86 (2026-06-06): Drift-Schutz fuer Storybook-Setup-Doku."""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
STORYBOOK_DOC = REPO_ROOT / "docs" / "STORYBOOK.md"
REPORTING_PKG = REPO_ROOT / "5eyes-electron" / "frontend" / "reporting" / "package.json"


def _read() -> str:
    return STORYBOOK_DOC.read_text(encoding="utf-8")


def test_storybook_doc_exists():
    assert STORYBOOK_DOC.exists()


def test_documents_opt_in_setup():
    text = _read()
    assert "opt-in" in text.lower()
    assert "storybook@latest init" in text


def test_branding_disziplin_mentioned():
    text = _read()
    assert "Drittmarken" in text
    assert "Garantie-Sprache" in text


def test_recommends_initial_stories():
    text = _read()
    for c in ("AmpelPill", "Sidebar", "ThemeToggle", "ErrorBoundary"):
        assert c in text


def test_documents_bewusst_nicht_in_scope():
    text = _read()
    assert "Bewusst NICHT in Scope" in text
    assert "package.json" in text  # nicht als Dep


def test_storybook_not_in_package_json():
    """User-Konvention: KEINE neue Dep ohne Auth."""
    pkg = REPORTING_PKG.read_text(encoding="utf-8")
    assert "@storybook" not in pkg


def test_links_to_design_system():
    text = _read()
    assert "DESIGN_SYSTEM.md" in text


def test_links_to_related_sprints():
    text = _read()
    assert "U-50" in text or "#50" in text
    assert "U-90" in text or "#90" in text


def test_documents_axe_storybook_for_a11y():
    text = _read()
    assert "axe-storybook" in text


def test_documents_cost_discipline():
    """ADR-005 CHF-0-Hard-Constraint."""
    text = _read()
    assert "Chromatic" in text  # kostenpflichtig dokumentiert
    assert "CHF" in text or "ADR-005" in text
