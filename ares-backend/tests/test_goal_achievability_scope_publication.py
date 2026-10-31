"""GOAL-ACHIEVABILITY-ATTRIBUTION-001 -- Publikationskanaele.

Vertragspunkte 4, 6 und 8 des Audits
(docs/audits/2026-09-28-goal-funding-priority-and-achievability-attribution-audit.md):
Plan-Solvenz genau einmal und klar beschriftet, je Ziel "Zielerreichung nach
Prioritaet", gemeinsame Failure-Events als EIN Konflikt, Altzeilen ohne Scope
ohne individuelle Ampel -- in Meldungen, Anlagestrategie-PDF und Classic UI.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

MONOLITH = BACKEND_ROOT.parent / "ares-desktop" / "frontend" / "ares.html"


def _goal_row(goal_id, label, probability, status, *, hardness="hart", event=None, rank=1):
    return {
        "goal_id": goal_id, "label": label, "target_kind": "cashflow_in_year",
        "probability": probability, "tau": 0.8, "status": status,
        "hardness": hardness, "evaluation_scope": "priority_funded",
        "funding_policy_version": "rank_cumulative_scope_v1",
        "funding_rank": rank, "failure_event_id": event,
        # Engine v10 (GOAL-FAILURE-EVENT-MODE-COLLAPSE-001): ein gemeinsamer
        # Engpass verlangt die VOLLE Fehlschlagsmasse auf dem Ereignis.
        "failure_event_share": 1.0 if event else None,
        "failure_event_distribution": (
            [{"event_id": event, "weighted_mass": 1.0, "share": 1.0}] if event else []
        ),
    }


def _plan_row(probability=0.31):
    return {
        "goal_id": None, "label": "Plan-Solvenz (alle Ziele gemeinsam)",
        "target_kind": "joint_plan", "probability": probability, "tau": 0.8,
        "status": "nicht_erreichbar", "hardness": None,
        "evaluation_scope": "joint_plan", "goal_ids": ["a", "b"],
        "failure_event_id": "liquiditaetsengpass-jahr-2",
    }


# ---------------------------------------------------------------------------
# Meldungen: ein gemeinsamer Engpass ist EINE Konfliktmeldung
# ---------------------------------------------------------------------------


def _allocation(limiting_factor="gemeinsamer_engpass"):
    return {"limiting_factor": limiting_factor, "optimization_status": "converged"}


def test_messages_report_one_shared_bottleneck_not_two_conflicts():
    # Codes als Literale (nicht importiert), damit der Test auf einem Stand
    # ohne den neuen Code am VERHALTEN scheitert, nicht am Import.
    from services.allocation_messages import classify_messages

    CONFLICT_GOAL_INCOMPATIBLE = "CONFLICT_GOAL_INCOMPATIBLE"
    CONFLICT_SHARED_BOTTLENECK = "CONFLICT_SHARED_BOTTLENECK"

    rows = [
        _goal_row("a", "Hauskauf", 0.2, "nicht_erreichbar", event="liquiditaetsengpass-jahr-2"),
        _goal_row("b", "Weltreise", 0.1, "nicht_erreichbar", hardness="primär",
                  event="liquiditaetsengpass-jahr-2", rank=2),
        _plan_row(),
    ]
    messages = classify_messages(_allocation(), rows, "converged", None, None)
    codes = [m["code"] for m in messages]
    assert codes == [CONFLICT_SHARED_BOTTLENECK]
    assert CONFLICT_GOAL_INCOMPATIBLE not in codes
    assert "Hauskauf" in messages[0]["body_advisor"]
    assert "Weltreise" in messages[0]["body_advisor"]
    assert "Planjahr 2" in messages[0]["body_advisor"]


def test_messages_keep_two_conflicts_for_independent_causes():
    from services.allocation_messages import CONFLICT_GOAL_INCOMPATIBLE, classify_messages

    rows = [
        _goal_row("a", "Hauskauf", 0.2, "nicht_erreichbar", event="liquiditaetsengpass-jahr-2"),
        _goal_row("b", "Vermoegen", 0.1, "nicht_erreichbar", event="zielschwelle-b", rank=2),
    ]
    messages = classify_messages(_allocation("zielkonflikt"), rows, "converged", None, None)
    assert [m["code"] for m in messages] == [CONFLICT_GOAL_INCOMPATIBLE]


def test_plan_row_never_counts_as_a_goal_conflict():
    from services.risk_matrix import classify_limiting_factor

    verdict = classify_limiting_factor(
        allocation_bps={"liquidity": 1000}, risky_fraction=5000,
        max_risky_fraction=6000, min_liquidity_bps=500, bands={},
        achievability=[
            _goal_row("a", "Hauskauf", 0.2, "nicht_erreichbar", event="zielschwelle-a"),
            _plan_row(),
        ],
        optimization_status="converged",
    )
    assert verdict != "zielkonflikt"


# ---------------------------------------------------------------------------
# Anlagestrategie-PDF
# ---------------------------------------------------------------------------


def _cell_text(cell) -> str:
    if hasattr(cell, "getPlainText"):
        return cell.getPlainText()
    return str(cell)


def test_pdf_table_labels_the_priority_scope_and_omits_the_plan_row():
    from services.pdf.components.goal_achievability import make_goal_achievability_table

    table = make_goal_achievability_table([
        _goal_row("a", "Hauskauf", 0.9, "erreichbar"),
        _goal_row("b", "Weltreise", 0.4, "nicht_erreichbar", rank=2),
        _plan_row(),
    ])
    data = table._cellvalues
    assert [_cell_text(c) for c in data[0]] == [
        "Ziel", "Typ", "Härtegrad", "Erfolgs-Wkt. (nach Priorität)", "Status",
    ]
    labels = [_cell_text(row[0]) for row in data[1:]]
    assert labels == ["Hauskauf", "Weltreise"]
    assert not any("Plan-Solvenz" in label for label in labels)


def test_pdf_plan_solvency_line_appears_once_with_label():
    from services.pdf.components.goal_achievability import make_plan_solvency_line

    paragraph = make_plan_solvency_line([
        _goal_row("a", "Hauskauf", 0.9, "erreichbar"), _plan_row(0.31),
    ])
    text = paragraph.getPlainText()
    assert text.count("Plan-Solvenz (alle Ziele gemeinsam)") == 1
    assert "31%" in text
    # Ohne Planzeile (Altbewertung) wird kein Wert erfunden.
    assert make_plan_solvency_line([_goal_row("a", "X", 0.9, "erreichbar")]).getPlainText() == ""


def test_pdf_legacy_rows_get_no_traffic_light():
    from services.pdf.components.goal_achievability import make_goal_achievability_table

    legacy = {"goal_id": "x", "label": "Alt", "probability": 0.2,
              "status": "nicht_erreichbar", "hardness": "hart"}
    table = make_goal_achievability_table([legacy])
    status_cell = _cell_text(table._cellvalues[1][4])
    assert "Altbewertung" in status_cell
    assert "nicht erreichbar" not in status_cell


def test_limiting_factor_label_exists_for_shared_bottleneck():
    from services.pdf.components.goal_achievability import LIMITING_FACTOR_LABELS

    assert "gemeinsamer_engpass" in LIMITING_FACTOR_LABELS


# ---------------------------------------------------------------------------
# Classic UI (Monolith)
# ---------------------------------------------------------------------------


def _monolith() -> str:
    return MONOLITH.read_text(encoding="utf-8")


def _function_body(source: str, name: str) -> str:
    match = re.search(r"function " + re.escape(name) + r"\([^)]*\)\{", source)
    assert match, name
    depth, index = 0, match.end() - 1
    for index in range(match.end() - 1, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                break
    return source[match.start(): index + 1]


def test_monolith_goal_list_excludes_the_joint_plan_row():
    body = _function_body(_monolith(), "allocationAchievability")
    assert "joint_plan" in body
    assert "filter" in body


def test_monolith_shows_plan_solvency_once_with_label():
    source = _monolith()
    assert "Plan-Solvenz (alle Ziele gemeinsam)" in source
    for name in ("renderOptimizerAchievability", "renderReviewGoalAchievability"):
        body = _function_body(source, name)
        assert body.count("planSolvencyHtml(allocationPlanSolvency(result))") == 1, name


def test_monolith_labels_individual_values_as_priority_funded():
    source = _monolith()
    # UX-1 (Befund 8): einheitliche Primaerkennzahl "Erfolgswahrscheinlichkeit",
    # weiterhin ausdruecklich als priorisierte (zielindividuelle) Bewertung.
    assert "Erfolgs-Wkt. (nach Priorit&auml;t)</th>" in source
    assert '<div class="rv-cockpit-kicker">Erfolgswahrscheinlichkeit nach Priorit&auml;t</div>' in source
    assert "var PRIORITY_FUNDED_LABEL='Erfolgswahrscheinlichkeit nach Priorit\\u00e4t';" in source
    # Die alte, scopelose Spaltenueberschrift "P" ist weg.
    table = source[source.index('id="opt-achievability-table"'):]
    table = table[: table.index("</thead>")]
    assert "<th>P</th>" not in table


def test_monolith_quarantines_legacy_rows_and_knows_shared_bottleneck():
    source = _monolith()
    assert "function goalAchievabilityIsLegacy(" in source
    for name in ("renderOptimizerAchievability", "renderReviewGoalAchievability"):
        assert "goalAchievabilityIsLegacy(row)" in _function_body(source, name), name
    assert "gemeinsamer_engpass:{label:" in _function_body(source, "limitingFactorMeta")
    assert "gemeinsamer_engpass" in _function_body(source, "rvBuildAllocationStory")
