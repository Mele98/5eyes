"""Bugfix 2026-05-08 — FE-Contract-Tests fuer Risk-Gating bei AA-Navigation.

Vor dem Fix blockierte ensureStrategyReadyRiskForMandate die
Asset-Allocation-Navigation, sobald der UI-DOM keine .qopt.sel-Klassen
trug — auch wenn das Backend ein vollstaendiges Risikoprofil hatte.

Der Fix dreht die Reihenfolge um: Backend wird als Source-of-Truth
befragt, BEVOR UI-State gegen-geprueft wird.

Diese Tests verifizieren statisch im FE-Code, dass die neue Reihenfolge
implementiert ist.
"""
from pathlib import Path
import re


HTML_PATH = Path(__file__).resolve().parents[2] / "5eyes-electron" / "frontend" / "5eyes_v2.html"


def _ensure_function_block() -> str:
    """Extrahiert den Body von ensureStrategyReadyRiskForMandate."""
    html = HTML_PATH.read_text(encoding="utf-8")
    start = html.find("async function ensureStrategyReadyRiskForMandate")
    assert start >= 0, "ensureStrategyReadyRiskForMandate nicht gefunden"
    # Bis zum naechsten 'async function' oder 'function ' am Zeilenanfang
    rest = html[start:]
    # Body geht bis zur naechsten Top-Level Funktion
    end = rest.find("\nasync function goFromRiskProfileToAllocation")
    if end < 0:
        end = len(rest)
    return rest[:end]


def test_backend_first_resolution_is_called_before_ui_issues():
    """resolveStrategyRiskForMandate muss VOR collectRiskAssessmentUiIssues
    aufgerufen werden (Backend = Source of Truth)."""
    body = _ensure_function_block()
    pos_resolve = body.find("resolveStrategyRiskForMandate(requestedMandateId)")
    pos_uiissues = body.find("collectRiskAssessmentUiIssues()")
    assert pos_resolve >= 0
    assert pos_uiissues >= 0
    assert pos_resolve < pos_uiissues, (
        "Bugfix-Regression: resolveStrategyRiskForMandate muss vor "
        "collectRiskAssessmentUiIssues aufgerufen werden."
    )


def test_resolved_risk_short_circuits_ui_check():
    """Wenn resolution.risk gesetzt ist, wird sofort returned — kein UI-Check."""
    body = _ensure_function_block()
    assert "if(resolution && resolution.risk){" in body
    assert "return resolution;" in body


def test_dirty_ui_still_saves_first():
    """Bestehende Semantik: dirty UI -> saveRiskProfile() vor Backend-Check."""
    body = _ensure_function_block()
    assert "if(riskAssessmentUiDirty){" in body
    pos_dirty = body.find("if(riskAssessmentUiDirty){")
    pos_resolve = body.find("resolveStrategyRiskForMandate(requestedMandateId)")
    assert pos_dirty < pos_resolve


def test_demo_mandate_blocked_first():
    """Demo / leerer Mandant blockiert sofort, vor allem anderen."""
    body = _ensure_function_block()
    pos_demo = body.find("isDemoMandateId(requestedMandateId)")
    pos_dirty = body.find("riskAssessmentUiDirty")
    assert pos_demo >= 0 and pos_dirty >= 0
    assert pos_demo < pos_dirty


def test_fallback_save_when_ui_complete_but_backend_empty():
    """Wenn Backend leer aber UI vollstaendig: saveRiskProfile als Fallback,
    danach Backend nochmal befragen.
    """
    body = _ensure_function_block()
    assert "savedFallback=" in body or "savedFallback =" in body
    # Nach savedFallback soll resolveStrategyRiskForMandate erneut aufgerufen werden
    pos_fallback = body.find("savedFallback")
    pos_second_resolve = body.find(
        "resolveStrategyRiskForMandate(requestedMandateId)",
        pos_fallback,
    )
    assert pos_second_resolve > pos_fallback, (
        "Nach Fallback-Save muss Backend erneut befragt werden"
    )


def test_old_buggy_pattern_no_longer_present():
    """Das alte Pattern 'else { ... uiIssues = ... loadCurrentRiskAssessment ...
    uiIssues = ... return null }' war die Bug-Quelle. Stelle sicher, dass es
    nicht mehr da ist.
    """
    body = _ensure_function_block()
    # Der alte Pfad hatte ein "}else{" direkt nach dem dirty-Block.
    # Im neuen Code gibt es das nicht mehr — nur sequentielle if-Statements.
    # Heuristik: das Pattern "loadCurrentRiskAssessment(requestedMandateId,true)"
    # innerhalb von ensureStrategyReadyRiskForMandate war Teil des alten Bugs
    # (forciert UI-Hydrate trotz Backend-Existenz). Sollte raus sein.
    assert "loadCurrentRiskAssessment(requestedMandateId,true)" not in body, (
        "loadCurrentRiskAssessment im Gating-Pfad ist Teil des alten Bug-"
        "Patterns; Backend-First sollte das ueberfluessig machen."
    )


def test_message_propagation_uses_backend_message_when_available():
    """Wenn Backend eine spezifische Message liefert (z.B. 'unvollstaendig'),
    soll diese vor dem generischen UI-Hint bevorzugt werden.
    """
    body = _ensure_function_block()
    assert "(resolution && resolution.message)" in body


def test_point_scoring_willingness_questions_have_no_default_selection():
    html = HTML_PATH.read_text(encoding="utf-8")
    for question_key in ("q9", "q10", "q11"):
        selected = re.findall(rf'<div class="qopt sel" onclick="sq\(this,\'{question_key}\'\)"', html)
        assert selected == [], f"{question_key} darf keine Default-Auswahl haben"


def test_frontend_strategy_gate_requires_current_questionnaire_contract():
    html = HTML_PATH.read_text(encoding="utf-8")
    assert "riskAssessmentHasCurrentSchemaMarkers" in html
    assert "var required={1:true,2:true,3:true,4:true,5:true,6:true,7:true,8:true,9:true,10:true,11:true}" in html
    assert "Bitte alle bewerteten Fragen anklicken" in html
