"""Bugfix 2026-05-09 — FE-Contract-Tests fuer defensive IST-Grafik-Render.

Vor dem Fix returnte updateProjectionChartsFromSimulation early wenn
simulationPayload(result) null war. Folge: nach Mandant-Wechsel zeigte
charts.ist und charts.aaCurrent veraltete Daten vom vorigen Klienten.

Der Fix entfernt das early-return; die deterministischen Current-Pfade
werden immer aus result-Cashflows + advisory_wealth gebaut. Nur das
target_mix-Chart (charts.opt) braucht weiterhin ein simulation-Payload
und faellt sonst auf einen Placeholder.
"""
from pathlib import Path


HTML_PATH = Path(__file__).resolve().parents[2] / "5eyes-electron" / "frontend" / "5eyes_v2.html"


def _function_block() -> str:
    html = HTML_PATH.read_text(encoding="utf-8")
    start = html.find("function updateProjectionChartsFromSimulation(result)")
    assert start >= 0, "updateProjectionChartsFromSimulation nicht gefunden"
    rest = html[start:]
    end = rest.find("\nfunction upgradeCurrentAaChartWithMonteCarlo")
    if end < 0:
        end = len(rest)
    return rest[:end]


def test_no_early_return_when_simulation_missing():
    """Das alte 'if(!sim)return;' Pattern ist die Bug-Quelle und darf nicht
    mehr im ersten Block der Funktion stehen."""
    body = _function_block()
    # Erste 5 Zeilen nach var sim=...
    head = body[:body.find("\n}", 0) if body.find("\n}", 0) > 0 else 800][:800]
    assert "if(!sim)return;" not in head, (
        "Regression: updateProjectionChartsFromSimulation hat wieder den "
        "early-return ohne sim — Charts wuerden alte Mandant-Daten zeigen."
    )


def test_horizon_falls_back_to_projectionHorizonYears():
    body = _function_block()
    assert "projectionHorizonYears(result,null)" in body


def test_labels_built_from_projectionYearLabels():
    body = _function_block()
    assert "projectionYearLabels(result,horizon,sim&&sim.year_labels)" in body


def test_target_series_only_when_simulation_present():
    body = _function_block()
    assert "var targetSeries=sim?simulationSeriesK(sim.target_mix_series_rappen):[]" in body


def test_target_chart_placeholder_when_no_simulation():
    body = _function_block()
    assert "Strategie ausstehend" in body
    # placeholder = labels.map(function(){return null;})
    assert "labels.map(function(){return null;})" in body


def test_current_charts_always_updated_with_deterministic_series():
    body = _function_block()
    # advisoryBaselineProjection und totalBaselineProjection werden gebaut
    # OHNE Pruefung auf sim
    pos_advisory = body.find("var advisoryBaselineProjection=buildCurrentBaselineProjection(result,horizon,labels)")
    pos_total = body.find("var totalBaselineProjection=buildCurrentWealthProjection('total',horizon,labels)")
    assert pos_advisory >= 0
    assert pos_total >= 0


def test_charts_ist_assignment_unchanged():
    body = _function_block()
    assert "charts.ist.data.datasets[0].data=totalCurrentSeries" in body


def test_charts_aaCurrent_assignment_unchanged():
    body = _function_block()
    assert "charts.aaCurrent.data.datasets[0].data=advisoryCurrentSeries" in body
