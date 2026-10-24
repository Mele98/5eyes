"""GOAL-FAILURE-DISTRIBUTION-REPORT-001: die volle Ursachenverteilung
(``failure_event_distribution``, Engine v10 / PR #659) erreicht Advisory-
Payload und -PDF.

Vertrag:
* Zielzeile mit Verteilung -> ``failure_event_distribution`` (typisiert,
  ``share_bps``, ohne interne ``weighted_mass``) + kompakte
  ``failure_cause_summary`` je Ereignisart;
* Altbestand ohne Verteilung / Altbewertung / nicht deutbare Verteilung ->
  ``None`` -> PDF zeigt keinen Ursachenblock;
* Projection-Gate ``blocked`` -> beides ``None`` (wie die uebrigen
  Projektionen), Positivkontrolle auf derselben Fixture;
* keine Kausalformulierung im kundensichtbaren Text.
"""
from __future__ import annotations

import json
import uuid

import pytest
from reportlab.platypus import Paragraph, Table

from models.mandates import Mandate
from models.wealth import Goal
from services.advisory_report import compute_advisory_report
from services.goal_failure_causes import (
    normalize_failure_event_distribution,
    summarize_failure_causes,
)
from tests.test_advisory_report import (
    _NOW,
    _make_ta_with_goals,
    _seed_minimal_mandate,
    session_factory,  # noqa: F401 - pytest fixture re-export
)

_DISTRIBUTION = [
    {"event_id": "liquiditaetsengpass-jahr-7", "weighted_mass": 31.0, "share": 0.5},
    {"event_id": "zielschwelle-G", "weighted_mass": 18.6, "share": 0.3},
    {"event_id": "liquiditaetsengpass-jahr-9", "weighted_mass": 12.4, "share": 0.2},
]


def _row(goal_id: str, **extra) -> dict:
    row = {
        "goal_id": goal_id, "label": "Hauskauf", "probability": 0.62,
        "status": "knapp", "hardness": "Hart",
        "evaluation_scope": "priority_funded", "funding_rank": 1,
        "failure_event_id": "liquiditaetsengpass-jahr-7",
        "failure_event_share": 0.5,
    }
    row.update(extra)
    return row


def _add_goal(s, mandate, client, goal_id: str) -> None:
    s.add(Goal(
        id=goal_id, mandate_id=mandate.id, client_id=client.id,
        goal_family="Vermoegen", goal_type="Vermoegensziel",
        label="Hauskauf", rank=1, weight_bps=6000,
        goal_scope="Beratungsvermögen", value_mode="real",
        target_wealth_rappen=500_000_00, frequency="einmalig",
        target_date="2032-06-01", is_ongoing=0, hardness="Hart",
        is_active=1, created_at=_NOW, updated_at=_NOW,
    ))


def _goal_payload(session_factory, row_factory) -> dict:
    with session_factory() as s:
        mandate, client, advisor = _seed_minimal_mandate(s)
        goal_id = str(uuid.uuid4())
        _add_goal(s, mandate, client, goal_id)
        _make_ta_with_goals(
            s, mandate_id=mandate.id, advisor_id=advisor.id,
            goal_achievability_json=json.dumps([row_factory(goal_id)]),
        )
        s.commit()
        report = compute_advisory_report(s, mandate, advisor=advisor)
    return report["goal_based_investing"]


def _texts(flowables) -> str:
    parts: list[str] = []

    def _walk(node):
        if isinstance(node, Paragraph):
            parts.append(node.getPlainText())
        elif isinstance(node, Table):
            for row in node._cellvalues:
                for cell in row:
                    _walk(cell)
        elif isinstance(node, (list, tuple)):
            for child in node:
                _walk(child)

    _walk(list(flowables))
    return " ".join(parts)


def _pdf_goal_text(gbi: dict) -> str:
    from services.pdf.documents.advisory_report import (
        _build_goals_flowables,
        make_advisory_styles,
    )

    return _texts(_build_goals_flowables(gbi, make_advisory_styles()))


# ---------------------------------------------------------------------------
# Payload
# ---------------------------------------------------------------------------


def test_payload_passes_full_distribution_and_compact_summary(session_factory):
    gbi = _goal_payload(
        session_factory,
        lambda gid: _row(gid, failure_event_distribution=_DISTRIBUTION),
    )
    goal = gbi["goals"][0]
    assert goal["failure_event_distribution"] == [
        {"event_id": "liquiditaetsengpass-jahr-7", "kind": "liquiditaetsengpass",
         "plan_year": 7, "share_bps": 5000},
        {"event_id": "zielschwelle-G", "kind": "zielschwelle",
         "plan_year": None, "share_bps": 3000},
        {"event_id": "liquiditaetsengpass-jahr-9", "kind": "liquiditaetsengpass",
         "plan_year": 9, "share_bps": 2000},
    ]
    summary = goal["failure_cause_summary"]
    assert [(g["kind"], g["share_bps"]) for g in summary] == [
        ("liquiditaetsengpass", 7000), ("zielschwelle", 3000),
    ]
    assert summary[0]["first_plan_year"] == 7
    assert summary[0]["last_plan_year"] == 9
    assert "zwischen dem 7. und 9. Planjahr" in summary[0]["label"]
    # Modus bleibt wie bisher erhalten.
    assert goal["failure_event_id"] == "liquiditaetsengpass-jahr-7"


def test_legacy_row_without_distribution_publishes_nothing(session_factory):
    gbi = _goal_payload(session_factory, _row)
    goal = gbi["goals"][0]
    assert goal["failure_event_distribution"] is None
    assert goal["failure_cause_summary"] is None
    assert "Verfehlte Verläufe" not in _pdf_goal_text(gbi)


def test_legacy_scope_row_never_shows_distribution(session_factory):
    gbi = _goal_payload(
        session_factory,
        lambda gid: _row(
            gid, evaluation_scope=None, failure_event_distribution=_DISTRIBUTION,
        ),
    )
    assert gbi["goals"][0]["failure_cause_summary"] is None


def test_goal_without_failed_paths_has_empty_distribution_and_no_pdf_block(
    session_factory,
):
    gbi = _goal_payload(
        session_factory,
        lambda gid: _row(gid, failure_event_distribution=[],
                         failure_event_id=None, failure_event_share=None),
    )
    goal = gbi["goals"][0]
    assert goal["failure_event_distribution"] == []
    assert goal["failure_cause_summary"] == []
    assert "Verfehlte Verläufe" not in _pdf_goal_text(gbi)


@pytest.mark.parametrize("bad", [
    [{"event_id": "liquiditaetsengpass-jahr-3", "share": 0.6}],  # Teilmasse
    [{"event_id": "irgendwas", "share": 1.0}],  # unbekannte Ereignisart
    [{"event_id": "liquiditaetsengpass-jahr-3", "share": "x"}],
    [{"event_id": "liquiditaetsengpass-jahr-3", "share": float("nan")}],
    [{"event_id": "liquiditaetsengpass-jahr-0", "share": 1.0}],
    ["liquiditaetsengpass-jahr-3"],
    "liquiditaetsengpass-jahr-3",
])
def test_uninterpretable_distribution_is_fail_closed(bad):
    row = {"failure_event_distribution": bad}
    assert normalize_failure_event_distribution(row) is None
    assert summarize_failure_causes(None) is None


def test_return_goal_label():
    dist = normalize_failure_event_distribution(
        {"failure_event_distribution": [{"event_id": "renditeziel-R", "share": 1.0}]}
    )
    assert summarize_failure_causes(dist)[0]["label"] == "Zielrendite nicht erreicht"


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


def test_pdf_renders_compact_customer_text_without_causal_claims(session_factory):
    gbi = _goal_payload(
        session_factory,
        lambda gid: _row(gid, failure_event_distribution=_DISTRIBUTION),
    )
    text = _pdf_goal_text(gbi)
    assert "Verfehlte Verläufe nach erstem Ereignis" in text
    assert (
        "Hauskauf: In den simulierten Verläufen, in denen das Ziel verfehlt wird, "
        "tritt zuerst ein: Liquiditätsengpass – verfügbares Vermögen zwischen "
        "dem 7. und 9. Planjahr aufgebraucht (70 %)" in text
    ), text
    assert "Zielbetrag zum Fälligkeitszeitpunkt nicht vollständig erreicht (30 %)" in text
    lowered = text.lower()
    for causal in ("weil ", "verursacht", "aufgrund", "wegen "):
        assert causal not in lowered, causal


# Projection-Gate stale/blocked: siehe
# tests/test_report_projection_gate_blocked.py::test_failure_distribution_visible_then_hidden_when_blocked
