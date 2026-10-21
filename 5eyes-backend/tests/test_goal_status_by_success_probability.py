"""GOAL-STATUS-BY-SUCCESS-001: Ziel-Status und Cockpit-Kachel folgen der
Erfolgswahrscheinlichkeit (Ampel 70/45, #654), nicht dem Mischwert
``achievement_score``.

Backend: ``_merge_goal_analysis_with_monte_carlo`` leitete ``status`` aus
``summary["score"]`` (alpha * Erfolgsquote + (1 - alpha) * Deckungsgrad) ab.
Ein Ziel mit 30 % Erfolgswahrscheinlichkeit und hohem Median-Deckungsgrad
hiess "On Track", obwohl die Ampel derselben Zeile "kritisch" zeigt.

Monolith: Kachel ``sr-goal-score`` mittelte ``achievement_score``.
"""
import json
import re
import subprocess
from pathlib import Path

import pytest

from services.goal_success_status import goal_status_from_success_pct
from services.portfolio_engine_payload import _merge_goal_analysis_with_monte_carlo

HTML_PATH = Path(__file__).resolve().parents[2] / "5eyes-electron" / "frontend" / "5eyes_v2.html"


def _merge(score: int, success: int) -> dict:
    item = {"goal_id": "g1", "label": "Ziel", "achievement_score": 50, "status": "Pruefen", "weight_bps": 100}
    mc = {"goal_summaries": [{"goal_id": "g1", "score": score, "success_rate_pct": success}]}
    return _merge_goal_analysis_with_monte_carlo([item], mc)[0]


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


def test_status_words_stay_backend_contract():
    # Statuswoerter unveraendert (GoalAnalysisResponse.status, Monolith-Mapping).
    assert {goal_status_from_success_pct(p) for p in (0, 50, 90)} == {"On Track", "Pruefen", "Gefaehrdet"}


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


def _run_summary(goals: list) -> dict:
    html = _html()
    script = (
        _function_source(html, "goalSuccessPct")
        + "\n" + _function_source(html, "goalSuccessAmpel")
        + "\n" + _function_source(html, "goalSuccessSummary")
        + "\nprocess.stdout.write(JSON.stringify(goalSuccessSummary(" + json.dumps(goals) + ")));"
    )
    out = subprocess.run(["node", "-e", script], capture_output=True, timeout=10, check=False)
    assert out.returncode == 0, out.stderr.decode("utf-8", "replace")
    return json.loads(out.stdout.decode("utf-8"))


def test_tile_value_is_weighted_success_probability_not_mixed_score():
    goals = [
        {"weight_bps": 3000, "achievement_score": 95, "path_success_rate_pct": 40},
        {"weight_bps": 1000, "achievement_score": 10, "path_success_rate_pct": 80},
    ]
    s = _run_summary(goals)
    # (3000*40 + 1000*80) / 4000 = 50 -- der Mischwert ergaebe 74.
    assert s["weighted"] == 50
    assert s["critical"] == 1 and s["tight"] == 0 and s["good"] == 1
    assert s["ampel"]["label"] == "knapp"


def test_tile_without_simulation_shows_no_number():
    s = _run_summary([{"weight_bps": 1000, "achievement_score": 80}])
    assert s["weighted"] is None and s["scored"] == 0


def test_ampel_labels_match_654():
    s = _run_summary([{"weight_bps": 0, "path_success_rate_pct": 70}])
    assert s["ampel"]["label"] == "gut"
    s = _run_summary([{"weight_bps": 0, "path_success_rate_pct": 44}])
    assert s["ampel"]["label"] == "kritisch"


def test_cockpit_renderers_no_longer_use_mixed_score_for_tile_or_status():
    html = _html()
    for name in ("renderStrategySummary", "renderSrApiSummary"):
        src = _function_source(html, name)
        assert "goalSuccessSummary(" in src, name
        assert "achievement_score" not in src, name
    # Ueberschreibender Wrapper der Prioritaetenliste
    wrapper = html[html.index("renderStrategySummary=function(){"):]
    wrapper = wrapper[: wrapper.index("sr-allocation-bars")]
    assert "achievement_score" not in wrapper
    assert "'Im Blick'" not in html and "'Im Plan'" not in html
    tile = html[html.index('id="sr-goal-score"') - 400: html.index('id="sr-goal-score"')]
    assert "Erfolgs-Wkt. gesamt" in tile
