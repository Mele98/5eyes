"""MC-CONTEXT-001 / GOAL-PUBLICATION-001 (Codex-Closure-Review PR #663):
zentrale Publikationsgrenze fuer skalare Projektionsfelder.

Vertrag:
* bei jedem ausgeblendeten Gate-Status (``stale``, ``blocked``,
  ``gate_error`` -> blocked, unbekannt) ist kein Manifest-Feld numerisch;
* ``current`` und ``no_allocation`` lassen den Payload unveraendert;
* jedes Manifest-Feld ist in ``projection_gate.hidden_channels`` deklariert;
* Advisory-PDF: bei ausgeblendetem Gate weder grosse ``0 %``-KPI noch alte
  Risikoquote, stattdessen der gemeinsame Hinweis.
"""
from __future__ import annotations

import copy

import pytest

from models.mandates import Mandate
import services.portfolio_engine as pe
from services.advisory_report import _PROJECTION_CHANNELS, compute_advisory_report
from services.report_projection_gate import (
    STATUS_BLOCKED,
    STATUS_CURRENT,
    STATUS_NO_ALLOCATION,
    STATUS_STALE,
    ProjectionGate,
    gate_error,
)
from services.report_projection_redaction import (
    SCALAR_PROJECTION_FIELDS,
    numeric_projection_leaks,
    redact_projection_channels,
)
from tests.test_report_mc_allocation_staleness import (
    _generate,
    _replace_current_assessment,
    _seed_mandate,
    advisor_user,  # noqa: F401 - pytest fixture re-export
    session_factory,  # noqa: F401 - pytest fixture re-export
)


def _numeric_payload() -> dict:
    return {
        "ausgangslage": {
            "key_metrics": {
                "risky_fraction_bps": 5380,
                "zielerreichung_bps": 7100,
                "exp_vol_bps": 820,
            },
            "wealth_summary": {"total_rappen": 123_00},
        },
        "goal_based_investing": {
            "goal_achievement_score_bps": 7100,
            "goals": [
                {"goal_id": "g1", "probability_bps": 6500, "target_amount_rappen": 5},
                {"goal_id": "g2", "probability_bps": 0, "target_amount_rappen": 7},
            ],
            "plan_solvency": {"probability_bps": 6000, "label": "x"},
        },
        "risikoprofilierung": {
            "risky_fraction_bps": 5380,
            "final_score_x10": 55,
        },
    }


@pytest.mark.parametrize(
    "gate",
    [
        ProjectionGate(STATUS_STALE, "assessment", ""),
        ProjectionGate(STATUS_BLOCKED, "no_assessment", ""),
        ProjectionGate(STATUS_BLOCKED, "policy_not_current", ""),
        gate_error(),
        ProjectionGate("future_status", "", ""),
    ],
    ids=["stale", "blocked", "policy_not_current", "gate_error", "unknown"],
)
def test_hidden_gate_leaves_no_numeric_projection_field(gate):
    payload = _numeric_payload()
    assert numeric_projection_leaks(payload)  # Positivkontrolle
    redacted = redact_projection_channels(payload, gate)
    assert numeric_projection_leaks(redacted) == []
    assert redacted["goal_based_investing"]["goal_achievement_score_bps"] is None
    assert redacted["risikoprofilierung"]["risky_fraction_bps"] is None
    assert all(
        g["probability_bps"] is None for g in redacted["goal_based_investing"]["goals"]
    )
    # IST-/Assessment-/Stammdaten bleiben unveraendert.
    assert redacted["ausgangslage"]["wealth_summary"] == {"total_rappen": 123_00}
    assert redacted["risikoprofilierung"]["final_score_x10"] == 55
    assert [g["target_amount_rappen"] for g in redacted["goal_based_investing"]["goals"]] == [5, 7]


@pytest.mark.parametrize("status", [STATUS_CURRENT, STATUS_NO_ALLOCATION])
def test_publishable_gate_keeps_payload_unchanged(status):
    payload = _numeric_payload()
    before = copy.deepcopy(payload)
    assert redact_projection_channels(payload, ProjectionGate(status, "", "")) == before


def test_redactor_tolerates_hidden_or_empty_sections():
    payload = {"goal_based_investing": {"goals": None}, "risikoprofilierung": {}}
    redact_projection_channels(payload, ProjectionGate(STATUS_STALE, "", ""))
    assert payload == {"goal_based_investing": {"goals": None}, "risikoprofilierung": {}}


def test_every_manifest_field_is_a_declared_hidden_channel():
    assert set(SCALAR_PROJECTION_FIELDS) <= set(_PROJECTION_CHANNELS)
    assert "goal_based_investing.goal_achievement_score_bps" in _PROJECTION_CHANNELS
    assert "risikoprofilierung.risky_fraction_bps" in _PROJECTION_CHANNELS


# ---------------------------------------------------------------------------
# Aggregator end-to-end
# ---------------------------------------------------------------------------


def _attach_goal_evaluation(session_factory, mandate_id: str) -> None:
    """Bewertete Zielzeile an die aktuelle Allokation haengen, damit der
    aggregierte Score im aktuellen Kontext numerisch ist (Positivkontrolle)."""
    import json

    from models.allocation import TargetAllocation

    with session_factory() as session:
        ta = (
            session.query(TargetAllocation)
            .filter(
                TargetAllocation.mandate_id == mandate_id,
                TargetAllocation.is_current == 1,
            )
            .one()
        )
        ta.goal_achievability_json = json.dumps([{
            "goal_id": "g-red", "label": "Hauskauf", "probability": 0.6,
            "status": "knapp", "hardness": "Hart",
            "evaluation_scope": "priority_funded", "funding_rank": 1,
        }])
        session.commit()


def _report(session_factory, mandate_id: str) -> dict:
    with session_factory() as session:
        return compute_advisory_report(session, session.get(Mandate, mandate_id))


@pytest.mark.timeout(180)
def test_current_publishes_score_then_policy_not_current_hides_it(
    session_factory, advisor_user, monkeypatch  # noqa: F811
):
    from models.allocation import OptimizerPolicy

    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")
    mid = _seed_mandate(session_factory, advisor_user.id)
    allocation = _generate(session_factory, mid, advisor_user.id)
    _attach_goal_evaluation(session_factory, mid)

    fresh = _report(session_factory, mid)
    assert fresh["projection_gate"]["status"] == STATUS_CURRENT
    assert fresh["goal_based_investing"]["goal_achievement_score_bps"] == 6000
    assert fresh["ausgangslage"]["key_metrics"]["zielerreichung_bps"] == 6000
    assert fresh["risikoprofilierung"]["risky_fraction_bps"] == int(
        allocation.risky_fraction_bps
    )

    with session_factory() as session:
        session.get(OptimizerPolicy, allocation.policy_id).is_current = 0
        session.commit()

    report = _report(session_factory, mid)
    assert report["projection_gate"]["status"] == STATUS_BLOCKED
    assert report["goal_based_investing"]["goal_achievement_score_bps"] is None
    assert report["risikoprofilierung"]["risky_fraction_bps"] is None
    # Assessmentdaten bleiben sichtbar.
    assert report["risikoprofilierung"]["final_score_x10"] == (
        fresh["risikoprofilierung"]["final_score_x10"]
    )
    assert numeric_projection_leaks(report) == []


# ---------------------------------------------------------------------------
# Advisory-PDF
# ---------------------------------------------------------------------------


def _texts(flowables) -> str:
    from reportlab.platypus import Paragraph, Table

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


@pytest.mark.timeout(180)
def test_advisory_pdf_hides_zero_kpi_and_old_risk_budget_when_stale(
    session_factory, advisor_user, monkeypatch  # noqa: F811
):
    from services.pdf.documents.advisory_report import (
        _build_goals_flowables,
        _build_risikoprofil_flowables,
        make_advisory_styles,
    )
    from services.pdf.components.swiss_numbers import format_bps_as_pct

    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")
    mid = _seed_mandate(session_factory, advisor_user.id)
    allocation = _generate(session_factory, mid, advisor_user.id)
    _attach_goal_evaluation(session_factory, mid)
    old_risky_text = format_bps_as_pct(int(allocation.risky_fraction_bps))
    styles = make_advisory_styles()

    fresh = _report(session_factory, mid)
    fresh_rp = _texts(_build_risikoprofil_flowables(
        fresh["risikoprofilierung"], styles,
        projection_gate=fresh["projection_gate"],
    ))
    assert old_risky_text in fresh_rp  # Positivkontrolle
    assert "ERFOLGSWAHRSCHEINLICHKEIT GESAMT" in _texts(
        _build_goals_flowables(fresh["goal_based_investing"], styles)
    )

    _replace_current_assessment(session_factory, mid, advisor_user.id)
    report = _report(session_factory, mid)
    gate = report["projection_gate"]
    assert gate["projections_hidden"] is True

    rp_text = _texts(_build_risikoprofil_flowables(
        report["risikoprofilierung"], styles, projection_gate=gate,
    ))
    assert old_risky_text not in rp_text
    assert gate["hinweis"] in rp_text

    goals_text = _texts(
        _build_goals_flowables(report["goal_based_investing"], styles)
    )
    assert "ERFOLGSWAHRSCHEINLICHKEIT GESAMT" not in goals_text
