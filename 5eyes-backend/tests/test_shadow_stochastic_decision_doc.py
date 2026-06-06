"""Sprint U-101 (2026-06-06): Drift-Schutz fuer shadow_stochastic-Decision-Doc."""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC = REPO_ROOT / "docs" / "decisions" / "SHADOW_STOCHASTIC_DEFAULT.md"


def _read() -> str:
    return DOC.read_text(encoding="utf-8")


def test_doc_exists():
    assert DOC.exists()


def test_documents_3_optimizer_modes():
    text = _read()
    for mode in ("house_matrix", "shadow_stochastic", "stochastic"):
        assert mode in text


def test_documents_3_decision_options():
    text = _read()
    assert "Option A" in text
    assert "Option B" in text
    assert "Option C" in text


def test_each_option_has_pro_and_contra():
    text = _read()
    assert text.count("**Pro:**") >= 3
    assert text.count("**Contra:**") >= 3


def test_documents_recommended_triggers():
    text = _read()
    assert "Recommended-Trigger" in text


def test_documents_engineering_recommendation():
    text = _read()
    assert "Empfehlung" in text
    assert "Option A" in text or "Status Quo" in text


def test_documents_user_questions_to_decide():
    text = _read()
    assert "Was der User entscheiden muss" in text
    assert "?" in text


def test_documents_activation_steps():
    text = _read()
    assert "config.py" in text
    assert "1-Monat-Probelauf" in text or "Probelauf" in text


def test_documents_what_we_dont_know():
    """Ehrlich: Wissens-Luecken explizit gelistet."""
    text = _read()
    assert "Was wir NICHT wissen" in text


def test_documents_shadow_comparison_endpoint():
    text = _read()
    assert "shadow-comparison-aggregate" in text


def test_links_to_relevant_memory():
    text = _read()
    assert "project_5eyes_optimizer" in text


def test_documents_bewusst_nicht_in_scope():
    text = _read()
    assert "Bewusst NICHT" in text
    assert "Konkrete Implementation" in text or "Implementation" in text


def test_links_to_adrs():
    text = _read()
    assert "ADR-001" in text
    assert "ADR-003" in text
