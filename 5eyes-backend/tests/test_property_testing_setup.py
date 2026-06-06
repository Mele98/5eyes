"""Sprint U-107 (2026-06-05): Drift-Schutz fuer Property-Based-Testing-Setup.

Verifiziert dass docs/PROPERTY_BASED_TESTING.md + tests/property/-Struktur
+ Beispiel-Property-Test vorhanden sind, und dass hypothesis NICHT
versehentlich zur requirements.txt hinzugefuegt wurde.
"""
from __future__ import annotations

from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
PROPERTY_DOC = REPO_ROOT / "docs" / "PROPERTY_BASED_TESTING.md"
PROPERTY_DIR = BACKEND_ROOT / "tests" / "property"
PROPERTY_INIT = PROPERTY_DIR / "__init__.py"
EXAMPLE_TEST = PROPERTY_DIR / "test_risk_metrics_kpi_properties.py"
REQUIREMENTS = BACKEND_ROOT / "requirements.txt"
GITIGNORE = REPO_ROOT / ".gitignore"


# ---------------------------------------------------------------------------
# Verzeichnis + Init
# ---------------------------------------------------------------------------

def test_property_dir_exists():
    assert PROPERTY_DIR.is_dir()


def test_property_dir_has_init():
    """Pytest braucht __init__.py um Property-Tests als Package zu erkennen."""
    assert PROPERTY_INIT.exists()


# ---------------------------------------------------------------------------
# docs/PROPERTY_BASED_TESTING.md
# ---------------------------------------------------------------------------

def test_property_doc_exists():
    assert PROPERTY_DOC.exists()


def test_property_doc_explains_what_it_is():
    text = PROPERTY_DOC.read_text(encoding="utf-8")
    assert "Property-Based-Testing" in text
    assert "hypothesis" in text


def test_property_doc_documents_opt_in_setup():
    text = PROPERTY_DOC.read_text(encoding="utf-8")
    assert "pip install hypothesis" in text
    assert "opt-in" in text.lower()


def test_property_doc_documents_skip_pattern():
    """importorskip-Pattern erklaeren damit CI ohne hypothesis gruen bleibt."""
    text = PROPERTY_DOC.read_text(encoding="utf-8")
    assert "skip" in text.lower()


def test_property_doc_lists_recommended_modules():
    text = PROPERTY_DOC.read_text(encoding="utf-8")
    # Mindestens 4 der 6 empfohlenen Module
    candidates = [
        "risk_metrics_kpi.py",
        "nelson_siegel.py",
        "ns_calibration_2024.py",
        "override_reason_quality.py",
        "recommendation_run_cleanup.py",
        "liquidity_cascade_audit.py",
    ]
    found = sum(1 for c in candidates if c in text)
    assert found >= 4, f"Nur {found} Module gelistet, mind. 4 erwartet"


def test_property_doc_links_to_mutation_testing():
    """Cross-Referenz auf komplementaere QA-Strategie."""
    text = PROPERTY_DOC.read_text(encoding="utf-8")
    assert "MUTATION_TESTING.md" in text


def test_property_doc_documents_what_not_in_scope():
    text = PROPERTY_DOC.read_text(encoding="utf-8")
    assert "NICHT in Scope" in text or "Bewusst NICHT" in text
    assert "requirements.txt" in text


# ---------------------------------------------------------------------------
# Beispiel Property-Test
# ---------------------------------------------------------------------------

def test_example_property_test_file_exists():
    assert EXAMPLE_TEST.exists()


def test_example_uses_importorskip_for_hypothesis():
    """Wenn hypothesis nicht da ist, muss der Test SKIPPED werden,
    nicht ImportError werfen."""
    text = EXAMPLE_TEST.read_text(encoding="utf-8")
    assert "importorskip" in text
    assert "hypothesis" in text


def test_example_tests_risk_metrics_kpi():
    """Beispiel testet U-96-Modul (Sortino/Calmar/Information-Ratio)."""
    text = EXAMPLE_TEST.read_text(encoding="utf-8")
    assert "compute_sortino_ratio_x100" in text
    assert "compute_calmar_ratio_x100" in text
    assert "compute_information_ratio_x100" in text


def test_example_has_at_least_3_properties():
    """3+ @given-decorated Properties pro Beispiel-Datei."""
    text = EXAMPLE_TEST.read_text(encoding="utf-8")
    assert text.count("@given(") >= 3


def test_example_test_collection_does_not_fail_without_hypothesis():
    """Wenn hypothesis fehlt, collection ist erfolgreich (skipped),
    nicht ImportError. Hier indirekt verifiziert: importorskip wird
    benutzt (siehe test_example_uses_importorskip_for_hypothesis)."""
    text = EXAMPLE_TEST.read_text(encoding="utf-8")
    # Modul-Ebenen-Skip-Pattern verhindert Collection-Error
    assert "hypothesis = pytest.importorskip" in text


# ---------------------------------------------------------------------------
# Konventions-Check: hypothesis NICHT in requirements.txt
# ---------------------------------------------------------------------------

def test_hypothesis_not_in_requirements_txt():
    """User-Konvention: KEINE neuen Dependencies ohne explizite Auth."""
    text = REQUIREMENTS.read_text(encoding="utf-8")
    assert "hypothesis" not in text.lower()


def test_gitignore_excludes_hypothesis_cache():
    """Damit Counter-Examples nicht versehentlich committet werden."""
    text = GITIGNORE.read_text(encoding="utf-8")
    assert ".hypothesis" in text
