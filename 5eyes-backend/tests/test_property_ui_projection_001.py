"""PROPERTY-UI-PROJECTION-001 (Audit 2026-09-14, User-Entscheid 2026-09-16:
"UI auf Backend-Serie umstellen"):

Die sichtbare "IST"-Vermoegenskurve (buildCurrentWealthProjection ->
wealthProjectionInputs) nettete Hypothekenschuld bisher EINMALIG bei t=0
gegen den Immobilien-Sockel und liess die Schuld danach nie wieder sinken
(direkte Amortisation) bzw. baute nie ein Gegen-Asset auf (indirekte
Amortisation). Die zugehoerige Tilgungszahlung wurde aber sehr wohl als
Cashflow-Abfluss verrechnet -- eine bilanziell neutrale Zahlung wirkte im
Chart dadurch wie echter Vermoegensverzehr (Audit-Repro: 300k -> 200k trotz
bilanzieller Neutralitaet).

Fix: mortgageLiabilityAndPledgedSeriesRappen() spiegelt dieselbe, jahres-
abhaengige Formel wie Backend services/portfolio_engine.py::
_build_external_foundation_projection() (direkt: linear sinkend bis 0;
indirekt: Pledged-Asset waechst unbegrenzt mit der Zahlung, siehe
MORTGAGE-INDIRECT-AMORTIZATION-001). buildBaselineProjectionFromComponent-
Series() nutzt diese Serien jetzt pro Jahr statt eines einmaligen
statischen Netto-Sockels, wenn sie mitgegeben werden.

Diese Datei deckt nur die statisch pruefbaren Vertragsteile ab (kein Node
in der Backend-CI-Job verfuegbar, siehe .github/workflows/test.yml --
Node/npm/vitest laeuft nur im separaten "Frontend Reporting Tests"-Job).
Die tatsaechliche Laufzeit-Arithmetik wurde manuell mit Node verifiziert
(direkte Amortisation: [300000,300000] statt vorher [300000,200000];
indirekte Amortisation mit realistischer Immobilien-Deckung: flach bei
600000 ueber 4 Jahre) -- siehe PR-Beschreibung fuer die Reproduktionswerte.
"""
from __future__ import annotations

from pathlib import Path


HTML_PATH = (
    Path(__file__).resolve().parents[2]
    / "5eyes-electron"
    / "frontend"
    / "5eyes_v2.html"
)


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def _function_block(html: str, name: str, next_marker: str) -> str:
    start = html.find(f"function {name}(")
    assert start >= 0, f"{name} nicht gefunden"
    end = html.find(next_marker, start)
    assert end > start, f"{next_marker} nach {name} nicht gefunden"
    return html[start:end]


def test_mortgage_liability_and_pledged_series_function_exists():
    html = _html()
    assert "function mortgageLiabilityAndPledgedSeriesRappen(positions,years){" in html


def test_mortgage_series_function_handles_direct_and_indirect_distinctly():
    """Direkte Amortisation muss die Liability linear reduzieren; indirekte
    darf die Liability NICHT reduzieren, sondern muss stattdessen das
    Pledged-Asset aufbauen -- dieselbe Unterscheidung wie
    services/wealth_cashflows._is_direct_amortization()."""
    body = _function_block(
        html=_html(),
        name="mortgageLiabilityAndPledgedSeriesRappen",
        next_marker="function wealthProjectionInputs(",
    )
    assert "isIndirect" in body and "isDirect" in body
    # "indirekt" muss VOR "direkt" geprueft werden (Substring-Falle).
    assert body.index("isIndirect=") < body.index("isDirect=")
    assert "debt-amortization*year" in body.replace(" ", "")
    assert "amortization*year" in body.replace(" ", "")


def test_wealth_projection_inputs_computes_mortgage_series_not_static_netting():
    """Regressionsschutz: die alte einmalige Nettung
    'sockelRappen=Math.max(0,sockelGrossRappen-liabilitiesRappen)' ohne
    Jahresbezug darf nicht mehr die einzige Berechnung sein -- die Funktion
    muss jetzt mortgageLiabilityAndPledgedSeriesRappen() aufrufen."""
    body = _function_block(
        html=_html(),
        name="wealthProjectionInputs",
        next_marker="function cashflowProjectionComponents(",
    )
    assert "mortgageLiabilityAndPledgedSeriesRappen(" in body
    assert "mortgageLiabilityYearSeriesRappen" in body
    assert "mortgagePledgedYearSeriesRappen" in body


def test_build_baseline_projection_uses_year_indexed_mortgage_series_when_available():
    body = _function_block(
        html=_html(),
        name="buildBaselineProjectionFromComponentSeries",
        next_marker="// Setzt einen Verzehr-Marker",
    )
    assert "hasMortgageSeries" in body
    assert "mortgageLiabilityYearSeriesRappen" in body
    assert "mortgagePledgedYearSeriesRappen" in body
    # Backward-Compat: ohne die neuen Serien (z.B. Advisory-Scope-Aufrufer)
    # muss der alte statische Pfad unveraendert erreichbar bleiben.
    normalized = body.replace(" ", "")
    assert "sockelOpts&&sockelOpts.sockelRappen" in normalized


def test_build_current_wealth_projection_passes_years_to_inputs():
    """wealthProjectionInputs() braucht den Horizont, um die Serien fuer
    genug Jahre zu berechnen -- vorher wurde scope ohne years aufgerufen."""
    html = _html()
    start = html.find("function buildCurrentWealthProjection(scope,preferredYears,preferredLabels){")
    assert start >= 0
    end = html.find("\nfunction buildAllocationPendingSummaryHtml", start)
    body = html[start:end]
    assert "wealthProjectionInputs(scope,years)" in body
    assert "sockelGrossRappen:inputs.sockelGrossRappen" in body
