"""Regression (2026-06-17): Die Cashflow-Liste muss beim Client-Load SOFORT
gerendert werden — vor der langsameren Risiko-/Strategie-Hydration.

Vorher wurde refreshCashflowsUI erst NACH `await loadCurrentRiskAssessment` und
`await loadCurrentAllocationResult` (und hinter deren stale-guard) aufgerufen ->
beim App-Start blieb "Wird geladen …" in den Cashflow-Listen stehen, bis die
gesamte Strategie-Hydration fertig war (oder der guard die Anzeige ganz verhinderte).
"""
from pathlib import Path

HTML_PATH = Path(__file__).resolve().parents[2] / "5eyes-electron" / "frontend" / "5eyes_v2.html"


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def test_cashflows_render_before_risk_hydration():
    html = _html()
    early = html.find("refreshCashflowsUI(c.id);")
    risk_await = html.find("await loadCurrentRiskAssessment(")
    assert early != -1, "Frueher refreshCashflowsUI(c.id)-Aufruf fehlt"
    assert risk_await != -1, "loadCurrentRiskAssessment-Await nicht gefunden"
    assert early < risk_await, (
        "Cashflow-Liste wird erst NACH der Risiko-Hydration gerendert — "
        "beim App-Start bleibt 'Wird geladen …' stehen."
    )


def test_early_render_marker_present():
    assert "Cashflow-Liste SOFORT rendern" in _html()


def test_no_duplicate_late_cashflow_call_after_preferences():
    """Der frueher vorhandene Doppel-Aufruf direkt nach syncAllocationPreferences()
    ist entfernt (sonst doppelter 4-fach-Fetch pro Client-Load)."""
    html = _html()
    anchor = "syncAllocationPreferences();"
    idx = html.find(anchor)
    assert idx != -1
    window = html[idx:idx + 200]
    assert "refreshCashflowsUI(c.id);" not in window
