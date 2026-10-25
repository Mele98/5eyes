"""Paritaet Fragebogen Desktop-Frontend <-> Server: Punkte und Scores (O-2).

Die echten Funktionen aus dem Monolithen laufen in Node gegen einen minimalen
DOM-Ersatz, die Optionstexte stammen aus derselben HTML-Quelle:

* Property-Test (vollstaendige Enumeration aller 240'000 zulaessigen
  Antwortkombinationen der bewerteten Fragen): Die Punkte, die der Server aus
  den gewaehlten Antworten ableitet, sind identisch zu den Punkten, die
  ``buildRiskAssessmentPayloadFromUI`` sendet; Faehigkeits-, Bereitschafts-
  und Final-Score des Servers sind identisch zur Frontend-Vorschau.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.risk_scoring import compute_scores
from tests.monolith_risk_js import DOM, NODE, monolith_js, run_node
from tests.risk_fixture_helpers import monolith_risk_questionnaire

pytestmark = pytest.mark.skipif(NODE is None, reason="node nicht verfuegbar")


@pytest.fixture(scope="module")
def questionnaire() -> dict:
    return monolith_risk_questionnaire()


# ── Property-Test Punkte und Scores ─────────────────────────────────────────────

_RANGES = {"income": 5, "oblig": 5, "wealth": 5, "savings": 5, "horizon": 6, "goal": 4, "pref": 4, "behav": 4}


def _frontend_payloads(questionnaire) -> dict:
    o = questionnaire["options"]
    script = monolith_js() + DOM + f"""
var O = {json.dumps(o)};
var SOURCES = {json.dumps(questionnaire["sources"])};
var SOURCE_VARIANTS = [[], [SOURCES[0]], SOURCES.slice()];
var rf = [fakeSection(O['rf-income']), fakeSection([]), fakeSection(O['rf-oblig']),
          fakeSection(O['rf-wealth']), fakeSection(O['rf-savings']), fakeSection(O['rf-horizon'])];
var rb = [fakeSection(O['q9']), fakeSection(O['q10']), fakeSection(O['q11'])];
var STATE = null;
function collectRiskAssessmentUiState(){{ return STATE; }}
var labels = [], labelIds = new Map();
function lid(t){{ if(!labelIds.has(t)){{ labelIds.set(t, labels.length); labels.push(t); }} return labelIds.get(t); }}
var rows = [], n = 0;
var R = {json.dumps(list(_RANGES.values()))};
for (var a=0;a<R[0];a++) for (var b=0;b<R[1];b++) for (var c=0;c<R[2];c++) for (var d=0;d<R[3];d++)
for (var e=0;e<R[4];e++) for (var f=0;f<R[5];f++) for (var g=0;g<R[6];g++) for (var h=0;h<R[7];h++) {{
  STATE = {{ rfSections: rf, rbSections: rb, incomeIdx: a, obligIdx: b, wealthIdx: c, savingsIdx: d,
            horizonIdx: e, goalIdx: f, prefIdx: g, behavIdx: h,
            knowledgeServices: (n % 2 ? {{Anlageberatung: {{known: 1, informed: 0}}}} : {{}}),
            knowledgeInstruments: {{}}, incomeSources: SOURCE_VARIANTS[n % 3] }};
  var r = buildRiskAssessmentPayloadFromUI(); n++;
  var p = r.payload;
  rows.push([[a,b,c,d,e,f,g,h], p.q_income_points, p.q_obligations_points, p.q_savings_points,
    p.q_wealth_points, lid(p.investment_horizon_label), p.investment_horizon_years,
    p.q_investment_goal_points, p.q_risk_preference_points, p.q_risk_behavior_points,
    lid(p.knowledge_services_json), lid(p.knowledge_instruments_json),
    p.answers.map(function(x){{ return [x.question_number, lid(x.answer_label), x.answer_points]; }}),
    r.capScore, r.willScore, r.finalScore]);
}}
process.stdout.write(JSON.stringify({{labels: labels, rows: rows}}));
"""
    return json.loads(run_node(script))


def test_server_derived_points_and_scores_equal_frontend_for_all_combinations(questionnaire):
    from services.risk_questionnaire_integrity import validate_standard_submission

    data = _frontend_payloads(questionnaire)
    labels, rows = data["labels"], data["rows"]
    expected_count = 1
    for size in _RANGES.values():
        expected_count *= size
    assert len(rows) == expected_count == 240_000
    seen = set()
    failures = []
    for row in rows:
        (idx, inc, obl, sav, wea, hl, hy, goal, pref, beh, ks, ki, answers, cap, will, final) = row
        seen.add(tuple(idx))
        body = SimpleNamespace(
            q_income_points=inc, q_obligations_points=obl, q_savings_points=sav, q_wealth_points=wea,
            investment_horizon_label=labels[hl], investment_horizon_years=hy,
            q_investment_goal_points=goal, q_risk_preference_points=pref, q_risk_behavior_points=beh,
            knowledge_services_json=labels[ks], knowledge_instruments_json=labels[ki],
            answers=[{"question_number": q, "answer_label": labels[l], "answer_points": p} for q, l, p in answers],
        )
        try:
            derived = validate_standard_submission(body)
        except ValueError as exc:  # pragma: no cover - Befund
            failures.append((idx, str(exc)))
            continue
        scores = compute_scores(**derived, investment_horizon_label=labels[hl])
        got = (scores.risk_capacity_score_x10, scores.risk_willingness_score_x10, scores.final_score_x10)
        if got != (cap, will, final):
            failures.append((idx, {"server": got, "frontend": (cap, will, final)}))
        if len(failures) > 20:
            break
    assert not failures, failures[:20]
    assert len(seen) == 240_000


def test_server_option_catalog_matches_monolith_source(questionnaire):
    from services import risk_questionnaire_integrity as rqi

    o, p = questionnaire["options"], questionnaire["points"]
    assert list(rqi.STANDARD_OPTIONS[3]) == o["rf-income"]
    assert list(rqi.STANDARD_OPTIONS[5]) == o["rf-oblig"]
    assert list(rqi.STANDARD_OPTIONS[6]) == o["rf-wealth"]
    assert list(rqi.STANDARD_OPTIONS[7]) == o["rf-savings"]
    assert [list(rqi.STANDARD_OPTIONS[q]) for q in (9, 10, 11)] == [o["q9"], o["q10"], o["q11"]]
    assert list(rqi.HORIZON_OPTIONS) == o["rf-horizon"]
    assert list(rqi.INCOME_SOURCE_OPTIONS) == questionnaire["sources"]
    assert list(rqi.STANDARD_POINTS[3]) == p["RISK_INCOME_POINTS"]
    assert list(rqi.STANDARD_POINTS[5]) == p["RISK_OBLIGATIONS_POINTS"]
    assert list(rqi.STANDARD_POINTS[6]) == p["RISK_WEALTH_POINTS"]
    assert list(rqi.STANDARD_POINTS[7]) == p["RISK_SAVINGS_POINTS"]
