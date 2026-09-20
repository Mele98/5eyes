"""Kontrollrunde 2026-09-21 (Override-Begruendungs-Audit, dritter Fund
derselben Runde nach SUITABILITY-OVERRIDE-REASON-001 und der Heuristik-
Haertung in services/override_reason_quality.py).

_build_risikoprofilierung (Sektion 12 des Advisory-Reports, gespeist von
der aktuellen RiskAssessment) las override_reason bisher ohne jede
Qualitaetspruefung -- derselbe Massstab wie beim Schreiben (schemas/
profiling.py) und beim Live-Engine-Lauf (services.risk_assessment_
semantics.validate_risk_assessment_model_input) wurde hier nie
angewendet. Ein Altbestand-Override (vor Sprint U-28/U-29) oder ein
Override, dessen RiskAssessment nie wieder einen Live-Engine-Lauf
durchlaeuft, zeigte den rohen Text unmarkiert -- selbst wenn er leer
oder eine generische Floskel ist.

Fix: neues Feld override_reason_quality_issue (str|None) im
_build_risikoprofilierung-Ergebnis, nicht-blockierend (analog zur
Allokations-Staleness-Warnung in Sektion 7/8).
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import services.advisory_report as ar  # noqa: E402
from services.advisory_report import _build_risikoprofilierung  # noqa: E402


def _ra(**overrides) -> SimpleNamespace:
    base = dict(
        id="ra-001",
        final_score_x10=50,
        final_profile="Ausgewogen",
        risk_capacity_score_x10=50,
        risk_willingness_score_x10=50,
        is_overridden=0,
        override_score_x10=None,
        override_profile=None,
        override_reason=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _patch_ra(monkeypatch, ra) -> None:
    monkeypatch.setattr(ar, "_cached_current_ra_is_current", lambda db, mandate: ra)
    monkeypatch.setattr(ar, "_cached_current_ta", lambda db, mandate: None)


def test_no_risk_assessment_yields_none_issue(monkeypatch):
    monkeypatch.setattr(ar, "_cached_current_ra_is_current", lambda db, mandate: None)
    result = _build_risikoprofilierung(MagicMock(), MagicMock())
    assert result["override_reason_quality_issue"] is None


def test_not_overridden_no_quality_issue(monkeypatch):
    _patch_ra(monkeypatch, _ra())
    result = _build_risikoprofilierung(MagicMock(), MagicMock())
    assert result["is_overridden"] is False
    assert result["override_reason_quality_issue"] is None


def test_overridden_with_valid_reason_no_issue(monkeypatch):
    ra = _ra(
        is_overridden=1, override_score_x10=70, override_profile="Wachstumsorientiert",
        override_reason=(
            "Kunde hat umfangreiche Erfahrung und wuenscht bewusst "
            "mehr Risiko im Portfolio."
        ),
    )
    _patch_ra(monkeypatch, ra)
    result = _build_risikoprofilierung(MagicMock(), MagicMock())
    assert result["is_overridden"] is True
    assert result["override_reason_quality_issue"] is None


def test_overridden_with_missing_reason_flags_issue(monkeypatch):
    ra = _ra(
        is_overridden=1, override_score_x10=70, override_profile="Wachstumsorientiert",
        override_reason=None,
    )
    _patch_ra(monkeypatch, ra)
    result = _build_risikoprofilierung(MagicMock(), MagicMock())
    assert result["override_reason_quality_issue"] is not None
    assert "Pflicht" in result["override_reason_quality_issue"]


def test_overridden_with_generic_phrase_flags_issue(monkeypatch):
    ra = _ra(
        is_overridden=1, override_score_x10=70, override_profile="Wachstumsorientiert",
        override_reason="kundenwunsch!!!!!!!!!!!!",
    )
    _patch_ra(monkeypatch, ra)
    result = _build_risikoprofilierung(MagicMock(), MagicMock())
    assert result["override_reason_quality_issue"] is not None
    assert "generische Floskel" in result["override_reason_quality_issue"]


# ---------------------------------------------------------------------------
# PDF-Renderer (services/pdf/documents/advisory_report.py)
# ---------------------------------------------------------------------------

def test_pdf_flowables_render_compliance_hint_for_bad_override():
    from services.pdf.documents.advisory_report import _build_risikoprofil_flowables
    from services.pdf.components.advisory_palette import make_advisory_styles

    rp = {
        "risky_fraction_bps": 4000,
        "risk_capacity_score_x10": 50,
        "risk_willingness_score_x10": 50,
        "final_score_x10": 50,
        "final_profile": "Ausgewogen",
        "display_score_x10": 70,
        "display_profile": "Wachstumsorientiert",
        "is_overridden": True,
        "override_reason": "kundenwunsch!!!!!!!!!!!!",
        "override_reason_quality_issue": (
            "override_reason 'kundenwunsch!!!!!!!!!!!!' ist eine generische "
            "Floskel."
        ),
        "questions": [],
    }
    flowables = _build_risikoprofil_flowables(rp, make_advisory_styles())
    texts = [getattr(f, "text", "") for f in flowables]
    assert any("Compliance-Hinweis" in t for t in texts)
    assert any("generische" in t for t in texts)


def test_pdf_flowables_no_compliance_hint_when_reason_valid():
    from services.pdf.documents.advisory_report import _build_risikoprofil_flowables
    from services.pdf.components.advisory_palette import make_advisory_styles

    rp = {
        "risky_fraction_bps": 4000,
        "risk_capacity_score_x10": 50,
        "risk_willingness_score_x10": 50,
        "final_score_x10": 50,
        "final_profile": "Ausgewogen",
        "display_score_x10": 70,
        "display_profile": "Wachstumsorientiert",
        "is_overridden": True,
        "override_reason": "Kunde hat umfangreiche Erfahrung und wuenscht bewusst mehr Risiko.",
        "override_reason_quality_issue": None,
        "questions": [],
    }
    flowables = _build_risikoprofil_flowables(rp, make_advisory_styles())
    texts = [getattr(f, "text", "") for f in flowables]
    assert not any("Compliance-Hinweis" in t for t in texts)


def test_pdf_flowables_backward_compatible_without_new_key():
    """Alte payloads ohne override_reason_quality_issue-Key duerfen nicht
    crashen (z.B. Test-Fixtures aus frueheren Sprints)."""
    from services.pdf.documents.advisory_report import _build_risikoprofil_flowables
    from services.pdf.components.advisory_palette import make_advisory_styles

    rp = {
        "risky_fraction_bps": 4000,
        "risk_capacity_score_x10": 50,
        "risk_willingness_score_x10": 50,
        "final_score_x10": 50,
        "final_profile": "Ausgewogen",
        "display_score_x10": 70,
        "display_profile": "Wachstumsorientiert",
        "is_overridden": True,
        "override_reason": "Kunde wuenscht offensiveres Profil als Score impliziert.",
        "questions": [],
    }
    flowables = _build_risikoprofil_flowables(rp, make_advisory_styles())
    texts = [getattr(f, "text", "") for f in flowables]
    assert not any("Compliance-Hinweis" in t for t in texts)
