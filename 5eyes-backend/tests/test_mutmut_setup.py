"""Sprint U-106 (2026-06-05): Drift-Schutz fuer Mutation-Testing-Setup.

Verifiziert dass mutmut.cfg + docs/MUTATION_TESTING.md vorhanden sind,
die Pflicht-Sektionen erwaehnen und mutmut NICHT versehentlich zur
requirements.txt hinzugefuegt wurde (User-Konvention: opt-in).
"""
from __future__ import annotations

from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
MUTMUT_CFG = BACKEND_ROOT / "mutmut.cfg"
MUTATION_DOC = REPO_ROOT / "docs" / "MUTATION_TESTING.md"
REQUIREMENTS = BACKEND_ROOT / "requirements.txt"
GITIGNORE = REPO_ROOT / ".gitignore"


# ---------------------------------------------------------------------------
# mutmut.cfg
# ---------------------------------------------------------------------------

def test_mutmut_cfg_exists():
    assert MUTMUT_CFG.exists()


def test_mutmut_cfg_has_mutmut_section():
    text = MUTMUT_CFG.read_text(encoding="utf-8")
    assert "[mutmut]" in text


def test_mutmut_cfg_targets_services_and_routers():
    text = MUTMUT_CFG.read_text(encoding="utf-8")
    assert "paths_to_mutate" in text
    assert "services/" in text
    assert "routers/" in text


def test_mutmut_cfg_uses_pytest_runner():
    text = MUTMUT_CFG.read_text(encoding="utf-8")
    assert "runner=" in text
    assert "pytest" in text


def test_mutmut_cfg_has_setup_instructions():
    """Erklaerung im Comment, was Berater/Engineer machen muss."""
    text = MUTMUT_CFG.read_text(encoding="utf-8")
    assert "pip install mutmut" in text


# ---------------------------------------------------------------------------
# docs/MUTATION_TESTING.md
# ---------------------------------------------------------------------------

def test_mutation_doc_exists():
    assert MUTATION_DOC.exists()


def test_mutation_doc_explains_what_it_is():
    text = MUTATION_DOC.read_text(encoding="utf-8")
    assert "Mutation-Testing" in text
    assert "Surviving" in text or "survived" in text


def test_mutation_doc_documents_setup():
    text = MUTATION_DOC.read_text(encoding="utf-8")
    assert "pip install mutmut" in text
    assert "opt-in" in text.lower()


def test_mutation_doc_lists_recommended_modules():
    """Modul-Tabelle: welche Module sind erstes Audit-Ziel?"""
    text = MUTATION_DOC.read_text(encoding="utf-8")
    assert "risk_metrics_kpi.py" in text
    assert "recommendation_run_cleanup.py" in text
    assert "ns_calibration_2024.py" in text


def test_mutation_doc_explains_status_codes():
    """killed/survived/timeout-Bedeutungen."""
    text = MUTATION_DOC.read_text(encoding="utf-8")
    for status in ("killed", "survived", "timeout"):
        assert status in text


def test_mutation_doc_documents_what_not_in_scope():
    text = MUTATION_DOC.read_text(encoding="utf-8")
    assert "NICHT in Scope" in text or "Bewusst NICHT" in text
    # mutmut sollte NICHT zu requirements.txt gehoeren
    assert "requirements.txt" in text


def test_mutation_doc_links_to_related_roadmap_points():
    """Komplementaere QA-Strategien (#107 hypothesis, #105 coverage)."""
    text = MUTATION_DOC.read_text(encoding="utf-8")
    assert "#107" in text
    assert "#105" in text


# ---------------------------------------------------------------------------
# Konventions-Check: mutmut NICHT in requirements.txt
# ---------------------------------------------------------------------------

def test_mutmut_not_in_requirements_txt():
    """User-Konvention: KEINE neuen Dependencies ohne explizite Auth."""
    text = REQUIREMENTS.read_text(encoding="utf-8")
    assert "mutmut" not in text.lower()


def test_gitignore_excludes_mutmut_cache():
    """Cache-Files muessen ignoriert werden damit kein Mutmut-Output committed wird."""
    text = GITIGNORE.read_text(encoding="utf-8")
    assert ".mutmut-cache" in text
