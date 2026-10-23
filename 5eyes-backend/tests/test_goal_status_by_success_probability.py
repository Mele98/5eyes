"""GOAL-STATUS-BY-SUCCESS-001: Ziel-Status und Cockpit-Kachel folgen der
Erfolgswahrscheinlichkeit (Ampel 70/45, #654), nicht dem Mischwert
``achievement_score``.

Backend: ``_merge_goal_analysis_with_monte_carlo`` leitete ``status`` aus
``summary["score"]`` (alpha * Erfolgsquote + (1 - alpha) * Deckungsgrad) ab.
Ein Ziel mit 30 % Erfolgswahrscheinlichkeit und hohem Median-Deckungsgrad
hiess "On Track", obwohl die Ampel derselben Zeile "kritisch" zeigt.

CIO-Entscheid zu #667 (EINE Quelle): kanonisch ist die priorisierte,
vom Optimizer publizierte Erfolgswahrscheinlichkeit (``goal_achievability``,
``priority_funded``) -- dieselbe Quelle wie der Bericht. Nur ohne
Optimizer-Evidenz faellt alles auf ``success_rate_pct`` der Simulation zurueck
("Schaetzung aus Simulation").

Monolith: Kachel ``sr-goal-score`` mittelte ``achievement_score``.
"""
import json
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from services import advisory_report
from services.goal_success_status import (
    goal_items_weighted_success_bps,
    goal_status_from_success_pct,
)
from services.portfolio_engine_payload import _merge_goal_analysis_with_monte_carlo

HTML_PATH = Path(__file__).resolve().parents[2] / "5eyes-electron" / "frontend" / "5eyes_v2.html"


def _merge(score: int, success: int, achievability=None) -> dict:
    item = {"goal_id": "g1", "label": "Ziel", "achievement_score": 50, "status": "Pruefen", "weight_bps": 100}
    mc = {"goal_summaries": [{"goal_id": "g1", "score": score, "success_rate_pct": success}]}
    return _merge_goal_analysis_with_monte_carlo([item], mc, achievability=achievability)[0]


def _row(goal_id, probability, scope="priority_funded", rank=1):
    return {"goal_id": goal_id, "probability": probability, "evaluation_scope": scope, "funding_rank": rank}


@pytest.mark.parametrize(
    "pct,expected",
    [(100, "On Track"), (70, "On Track"), (69, "Pruefen"), (45, "Pruefen"), (44, "Gefaehrdet"), (0, "Gefaehrdet"), (None, "Gefaehrdet")],
)
def test_status_thresholds_70_45(pct, expected):
    assert goal_status_from_success_pct(pct) == expected


def test_high_mixed_score_but_low_success_is_at_risk():
    merged = _merge(score=82, success=30)
    assert merged["status"] == "Gefaehrdet"
    assert merged["path_success_rate_pct"] == 30
    # Der Mischwert bleibt als eigenes Feld erhalten, traegt aber keinen Status.
    assert merged["achievement_score"] == 82


def test_low_mixed_score_but_high_success_is_on_track():
    merged = _merge(score=40, success=75)
    assert merged["status"] == "On Track"


def test_tight_success_is_review():
    assert _merge(score=90, success=60)["status"] == "Pruefen"


def test_optimizer_evidence_is_canonical_over_simulation():
    merged = _merge(score=90, success=85, achievability=[_row("g1", 0.30)])
    assert merged["success_probability"] == pytest.approx(0.30)
    assert merged["success_probability_pct"] == 30
    assert merged["success_probability_source"] == "optimizer"
    assert merged["status"] == "Gefaehrdet"
    # Simulationswert bleibt fuer den SOLL/IST-Vergleich (gleiche Basis) erhalten.
    assert merged["path_success_rate_pct"] == 85


def test_simulation_is_fallback_only_without_optimizer_evidence():
    merged = _merge(score=90, success=60, achievability=None)
    assert merged["success_probability_source"] == "simulation"
    assert merged["success_probability_pct"] == 60
    assert merged["status"] == "Pruefen"


@pytest.mark.parametrize("scope", ["joint_plan", ""])
def test_plan_solvency_and_legacy_rows_are_not_goal_evidence(scope):
    merged = _merge(score=10, success=75, achievability=[_row("g1", 0.10, scope=scope)])
    assert merged["success_probability_source"] == "simulation"
    assert merged["status"] == "On Track"


def test_optimizer_evidence_without_simulation_summary_still_sets_status():
    item = {"goal_id": "g1", "label": "Ziel", "achievement_score": 95, "status": "On Track"}
    merged = _merge_goal_analysis_with_monte_carlo([item], None, achievability=[_row("g1", 0.2)])[0]
    assert merged["status"] == "Gefaehrdet"
    assert merged["success_probability_source"] == "optimizer"


def test_status_words_stay_backend_contract():
    # Statuswoerter unveraendert (GoalAnalysisResponse.status, Monolith-Mapping).
    assert {goal_status_from_success_pct(p) for p in (0, 50, 90)} == {"On Track", "Pruefen", "Gefaehrdet"}


def test_foundation_example_uses_same_weighted_success():
    items = [
        {"success_probability": 0.4, "success_weight_bps": 3000, "achievement_score": 99},
        {"success_probability": 0.8, "success_weight_bps": 1000, "achievement_score": 1},
        {"achievement_score": 50},  # ohne Wert: zaehlt nicht
    ]
    assert goal_items_weighted_success_bps(items) == 5000
    src = (Path(__file__).resolve().parents[1] / "services" / "foundation_example.py").read_text(encoding="utf-8")
    assert "goal_items_weighted_success_bps(goal_analysis)" in src
    assert 'item.get("achievement_score")' not in src


# --------------------------------------------------------------------------
# Monolith: Kachel sr-goal-score
# --------------------------------------------------------------------------

def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def _function_source(html: str, name: str) -> str:
    match = re.search(r"function " + re.escape(name) + r"\(", html)
    assert match, name
    i = html.index("{", match.end())
    depth, j = 1, i + 1
    while depth:
        if html[j] == "{":
            depth += 1
        elif html[j] == "}":
            depth -= 1
        j += 1
    return html[match.start():j]


def _run_js(goals: list, extra: str = "") -> dict:
    html = _html()
    names = (
        "fmtNumber", "goalSuccessPct", "goalSuccessIsEstimate", "goalSuccessAmpel",
        "goalSuccessSummary", "goalSuccessTileText", "goalSuccessSubText",
    )
    script = (
        "var GOAL_SUCCESS_ESTIMATE_HINT='Schaetzung aus Simulation';\n"
        + "\n".join(_function_source(html, n) for n in names)
        + "\nvar r=goalSuccessSummary(" + json.dumps(goals) + ");"
        + "r.tile=goalSuccessTileText(r);r.sub=goalSuccessSubText(r);" + extra
        + "process.stdout.write(JSON.stringify(r));"
    )
    out = subprocess.run(["node", "-e", script], capture_output=True, timeout=10, check=False)
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")
    return json.loads(out.stdout.decode("utf-8"))


def test_tile_value_is_weighted_success_probability_not_mixed_score():
    goals = [
        {"success_weight_bps": 3000, "achievement_score": 95, "success_probability": 0.4,
         "success_probability_pct": 40, "success_probability_source": "optimizer"},
        {"success_weight_bps": 1000, "achievement_score": 10, "success_probability": 0.8,
         "success_probability_pct": 80, "success_probability_source": "optimizer"},
    ]
    s = _run_js(goals)
    # (3000*40 + 1000*80) / 4000 = 50 -- der Mischwert ergaebe 74.
    assert s["weighted"] == 50 and s["weightedBps"] == 5000
    assert s["critical"] == 1 and s["tight"] == 0 and s["good"] == 1
    assert s["ampel"]["label"] == "knapp"
    assert s["estimated"] == 0 and "Simulation" not in s["sub"]


def test_tile_without_any_value_shows_no_number():
    s = _run_js([{"weight_bps": 1000, "achievement_score": 80}])
    assert s["weighted"] is None and s["scored"] == 0 and s["tile"] == "—"


def test_simulation_fallback_is_marked_as_estimate():
    s = _run_js([{"weight_bps": 0, "path_success_rate_pct": 44}])
    assert s["ampel"]["label"] == "kritisch" and s["estimated"] == 1
    assert "Schaetzung aus Simulation" in s["sub"]
    s = _run_js([{"success_probability_pct": 70, "success_probability_source": "simulation"}])
    assert s["ampel"]["label"] == "gut" and s["estimated"] == 1
    assert "var GOAL_SUCCESS_ESTIMATE_HINT='Sch\\u00e4tzung aus Simulation';" in _html()


REPORT_CASES = [
    # (Optimizer-Wahrscheinlichkeiten, Goal.weight_bps)
    ([0.3127, 0.8891, 0.555], [3000, 0, 1250]),
    ([0.455, 0.7049], [0, 0]),
    ([0.1, 0.92, 0.6666, 0.4449], [5000, 2500, 1250, 625]),
]


@pytest.mark.parametrize("probabilities,weights", REPORT_CASES)
def test_tile_and_report_show_the_same_value(monkeypatch, probabilities, weights):
    """CIO-Entscheid #667: bei vorhandener Optimizer-Evidenz zeigen Cockpit-
    Kachel und Bericht (Sektion 11 / Key-Metric) denselben Wert."""
    ids = [f"g{i}" for i in range(len(probabilities))]
    rows = [_row(gid, p, rank=i + 1) for i, (gid, p) in enumerate(zip(ids, probabilities))]
    goals = [SimpleNamespace(id=gid, weight_bps=w) for gid, w in zip(ids, weights)]
    achievability = rows + [{"evaluation_scope": "joint_plan", "probability": 0.05, "goal_ids": ids}]
    ta = SimpleNamespace(goal_achievability_json=json.dumps(achievability))
    monkeypatch.setattr(advisory_report, "_allocation_projection_hidden", lambda db, m: False)
    monkeypatch.setattr(advisory_report, "_cached_current_ta", lambda db, m: ta)
    monkeypatch.setattr(advisory_report, "_cached_active_goals", lambda db, m: goals)
    report_bps = advisory_report._compute_goal_achievement_score_bps(None, None)
    assert report_bps is not None

    # goal_analysis wie aus _build_goal_analysis: weight_bps (Engine-Gewicht)
    # weicht absichtlich ab; massgebend ist success_weight_bps (= Goal.weight_bps).
    items = [
        {"goal_id": gid, "label": gid, "achievement_score": 99, "weight_bps": 7777, "success_weight_bps": w}
        for gid, w in zip(ids, weights)
    ]
    mc = {"goal_summaries": [{"goal_id": gid, "score": 99, "success_rate_pct": 99} for gid in ids]}
    merged = _merge_goal_analysis_with_monte_carlo(items, mc, achievability=achievability)
    assert all(m["success_probability_source"] == "optimizer" for m in merged)

    js = _run_js(merged, extra="r.reportTile=fmtNumber(" + str(report_bps) + "/100,0)+'\\u00a0%';")
    assert js["weightedBps"] == report_bps
    assert goal_items_weighted_success_bps(merged) == report_bps
    assert js["tile"] == js["reportTile"]


def test_goals_tab_shows_current_allocation_success_not_db_score_and_draft_removed():
    html = _html()
    goal_list = _function_source(html, "renderGoalList")
    assert "goal.achievement_score" not in goal_list
    assert "goalSuccessFromCurrentAllocation(goal.id)" in goal_list
    lookup = _function_source(html, "goalSuccessFromCurrentAllocation")
    assert "strategyState.dirty" in lookup
    assert "function buildAnlagestrategieDocHtmlV2Draft(" not in html
    # kein erfundener Default-Score mehr beim lokalen Ziel-Upsert
    assert "existingGoal.achievement_score:50" not in html


def test_cockpit_renderers_no_longer_use_mixed_score_for_tile_or_status():
    html = _html()
    for name in ("renderStrategySummary", "renderSrApiSummary", "buildAnlagestrategieDocHtml"):
        src = _function_source(html, name)
        assert "achievement_score" not in src, name
    for name in ("renderStrategySummary", "renderSrApiSummary"):
        assert "goalSuccessSummary(" in _function_source(html, name), name
    # Ueberschreibender Wrapper der Prioritaetenliste
    wrapper = html[html.index("renderStrategySummary=function(){"):]
    wrapper = wrapper[: wrapper.index("sr-allocation-bars")]
    assert "achievement_score" not in wrapper
    assert "'Im Blick'" not in html and "'Im Plan'" not in html
    tile = html[html.index('id="sr-goal-score"') - 400: html.index('id="sr-goal-score"')]
    assert "Erfolgs-Wkt. gesamt" in tile
