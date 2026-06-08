from pathlib import Path


HTML_PATH = (
    Path(__file__).resolve().parents[2]
    / "5eyes-electron"
    / "frontend"
    / "5eyes_v2.html"
)


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def _function_block(html: str, name: str, next_name: str) -> str:
    start = html.index(f"function {name}")
    end = html.index(f"function {next_name}", start)
    return html[start:end]


def test_goal_save_has_explicit_success_failure_contract():
    html = _html()
    block = _function_block(html, "goalSaveErrorText", "refreshGoalsUI")

    assert "async function saveGoal(options)" in block
    assert "return true;" in block
    assert "return false;" in block
    assert "goalSaveErrorText(e)" in block


def test_combined_save_stops_when_goal_post_failed():
    html = _html()

    assert "var goalSaved=await saveGoal({deferRefresh:true});" in html
    assert "if(goalSaved!==true||goalModal.classList.contains('open'))" in html


def test_ist_projection_uses_persisted_cashflow_projection_not_goals():
    html = _html()
    block = _function_block(
        html,
        "buildCurrentWealthProjection",
        "buildAllocationPendingSummaryHtml",
    )

    assert "currentCashflowProjectionComponentSeries(" in block
    assert "currentGoals" not in block
    assert "goal" not in block.lower()


def test_ist_chart_is_continuous_and_has_deterministic_edge_padding():
    html = _html()
    presentation = _function_block(
        html,
        "normalizeProjectionChartsPresentation",
        "resetCurrentProjectionCharts",
    )
    domain = _function_block(
        html,
        "projectionAxisDomain",
        "syncAaProjectionAxisScales",
    )

    assert "charts.ist.data.datasets[0].stepped=false" in presentation
    assert "charts.ist.data.datasets[0].stepped='after'" not in presentation
    assert "projectionAxisDomain(projectionChartValues(charts.ist),0.25)" in domain
    assert "yScale.min=domain.min" in domain
    assert "yScale.max=domain.max" in domain

