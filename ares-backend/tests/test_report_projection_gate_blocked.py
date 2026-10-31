"""MC-CONTEXT-001 (Codex-Closure-Review PR #652): ``blocked`` sperrt ALLE
Projektionskanaele des Reports, nicht nur die Live-Monte-Carlo-Kurve.

Befund (docs/audits/2026-10-20-report-projection-gate-pr652-closure-review.md,
Codex-Branch): Fehlt ein eindeutig aktuelles RiskAssessment, meldete die
MC-Sektion korrekt ``blocked`` und leere Quantile, waehrend derselbe Bericht
Key-Metrics (Risikoquote, Vola, Rendite, MaxDD, VaR) und alle fuenf
Stress-Szenarien der unverifizierbaren Allokation numerisch publizierte.
Ursache: ``_allocation_projection_hidden`` verglich nur mit ``STATUS_STALE``
statt den kanonischen Gate-Vertrag (stale UND blocked) zu verwenden.

Vertrag:
* ein einmal berechneter Gate-Entscheid; ``stale``, ``blocked`` und jeder
  unbekannte Status (auch eine Gate-Ausnahme) blenden fail-closed aus;
* ausgeblendet werden kanalgleich: Zielwahrscheinlichkeiten/Plan-Solvenz,
  Key-Metrics, MC-Pfade, Stress-Replay, Benchmark-Attribution, Soll-Werte der
  Sektionen 7-10/13, Advisory-PDF; das Strategie-PDF bleibt fail-closed (409);
* der Berater sieht "Kein aktuelles Risikoprofil – Projektionen ausgeblendet";
* IST-/Bestandswerte bleiben sichtbar und sind im ``projection_gate``-Payload
  typisiert von den Projektionskanaelen getrennt;
* aktueller Kontext: alles numerisch befuellt (Positivkontrolle).

Der erste Test ist der Codex-Reproducer
``docs/audits/reproducers/test_2026_10_20_pr652_projection_gate_blocked_adversarial.py``
ohne ``xfail``.
"""
from __future__ import annotations

import pytest

from models.allocation import OptimizerPolicy
from models.mandates import Mandate
from models.profiling import RiskAssessment
from services.advisory_report import compute_advisory_report
import services.portfolio_engine as pe
from services.report_projection_gate import (
    HINT_NO_ASSESSMENT,
    ProjectionGate,
)
from services.report_projection_redaction import numeric_projection_leaks
from tests.test_report_mc_allocation_staleness import (
    _generate,
    _replace_current_assessment,
    _seed_mandate,
    advisor_user,  # noqa: F401 - pytest fixture re-export
    session_factory,  # noqa: F401 - pytest fixture re-export
)


@pytest.fixture()
def house_matrix(monkeypatch):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")


def _drop_current_assessment(session_factory, mandate_id: str) -> None:
    """Referenzierte Zeile bleibt, aber kein eindeutig aktuelles Profil."""
    with session_factory() as session:
        current = (
            session.query(RiskAssessment)
            .filter(
                RiskAssessment.mandate_id == mandate_id,
                RiskAssessment.is_current == 1,
            )
            .one()
        )
        current.is_current = 0
        session.commit()


def _report(session_factory, mandate_id: str) -> dict:
    with session_factory() as session:
        return compute_advisory_report(session, session.get(Mandate, mandate_id))


def _assert_all_projections_hidden(report: dict, *, status: str) -> None:
    gate = report["projection_gate"]
    assert gate["status"] == status
    assert gate["projections_hidden"] is True
    assert gate["hidden_channels"], gate

    gbi = report["goal_based_investing"]
    mc = gbi["monte_carlo_paths"]
    assert mc["data_pending"] is True
    assert mc["projection_status"] == status
    assert mc["p50"] == []
    assert gbi["target_allocation_stale"] is True
    assert gbi["plan_solvency"] is None
    # MC-CONTEXT-001 (Codex-Closure-Review PR #663): nicht verfuegbar ist
    # None, nie eine gemessene Erfolgswahrscheinlichkeit von 0 %.
    assert gbi["goal_achievement_score_bps"] is None
    for goal in gbi["goals"]:
        assert goal["probability_bps"] is None
        assert goal["status"] == "data_pending"
        # GOAL-FAILURE-DISTRIBUTION-REPORT-001
        assert goal["failure_event_distribution"] is None
        assert goal["failure_cause_summary"] is None

    key_metrics = report["ausgangslage"]["key_metrics"]
    assert all(value is None for value in key_metrics.values()), key_metrics

    stress = report["stress_replay"]
    assert stress["data_pending"] is True
    assert stress["scenarios"] == []
    assert stress["weights_bps"] == {}

    pa = report["performance_attribution"]
    assert pa["buckets"] == []
    assert pa["error"]

    for section in ("asset_allocation", "risikowaehrungen", "branchen"):
        payload = report[section]
        assert payload["soll_ausgeblendet"] is True, section
        assert payload["soll_bps"] is None, section
        assert payload["drift_bps"] is None, section
        for item in payload["items"]:
            assert item["soll_bps"] is None, (section, item)
            assert item["drift_bps"] is None, (section, item)

    bb = report["building_blocks"]
    assert bb["target_allocation_stale"] is True
    assert all(b["target_bps"] is None for b in bb["blocks"])
    assert bb["constraints"] == []

    checks = {c["pruefpunkt"]: c for c in report["erkenntnisse"]["checks"]}
    assert checks["Asset Allocation"]["bewertung"] == "nicht_beurteilbar"
    assert checks["Zielkompatibilität"]["bewertung"] == "nicht_beurteilbar"

    # MC-CONTEXT-001 (PR #663): die Risikoquote der Allokation ist kein
    # Assessmentwert; das Profil bleibt sichtbar, das Risikobudget nicht.
    rp = report["risikoprofilierung"]
    assert rp["risky_fraction_bps"] is None
    for channel in (
        "goal_based_investing.goal_achievement_score_bps",
        "risikoprofilierung.risky_fraction_bps",
    ):
        assert channel in gate["hidden_channels"], channel
    # Zentrale Publikationsgrenze: kein Manifest-Feld bleibt numerisch.
    assert numeric_projection_leaks(report) == []


# ---------------------------------------------------------------------------
# Codex-Reproducer (ohne xfail)
# ---------------------------------------------------------------------------


@pytest.mark.timeout(120)
def test_blocked_projection_gate_suppresses_all_allocation_projections(
    session_factory,  # noqa: F811
    advisor_user,  # noqa: F811
    monkeypatch,
):
    """One report must not mix a blocked MC verdict with numeric projections."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")
    mandate_id = _seed_mandate(session_factory, advisor_user.id)
    _generate(session_factory, mandate_id, advisor_user.id)

    # Preserve the referenced assessment row but remove a unique current
    # assessment.  The allocation is now unverifiable, not merely changed.
    with session_factory() as session:
        current = (
            session.query(RiskAssessment)
            .filter(
                RiskAssessment.mandate_id == mandate_id,
                RiskAssessment.is_current == 1,
            )
            .one()
        )
        current.is_current = 0
        session.commit()

    with session_factory() as session:
        report = compute_advisory_report(
            session,
            session.get(Mandate, mandate_id),
        )

    goals = report["goal_based_investing"]
    mc = goals["monte_carlo_paths"]
    assert mc["data_pending"] is True
    assert mc["projection_status"] == "blocked"

    leaked = {
        "goal_probabilities": [
            row.get("probability_bps")
            for row in goals.get("goals", [])
            if row.get("probability_bps") is not None
        ],
        "key_metrics": {
            key: value
            for key, value in report["ausgangslage"]["key_metrics"].items()
            if value is not None
        },
        "stress_scenarios": report["stress_replay"].get("scenarios") or [],
    }
    assert not any(leaked.values()), (
        "projection gate is blocked, but other report sections still publish "
        f"the unverifiable allocation: {leaked}"
    )


# ---------------------------------------------------------------------------
# Pflichtregressionen
# ---------------------------------------------------------------------------


@pytest.mark.timeout(180)
def test_current_context_publishes_every_channel_then_blocked_hides_all(
    session_factory, advisor_user, house_matrix  # noqa: F811
):
    """Positivkontrolle + Kanalgleichheit auf derselben Fixture: erst sind
    alle Kanaele befuellt (sonst waere das Ausblenden unten trivial gruen),
    nach Wegfall des aktuellen Risikoprofils sind alle gemeinsam leer."""
    mid = _seed_mandate(session_factory, advisor_user.id)
    _generate(session_factory, mid, advisor_user.id)

    fresh = _report(session_factory, mid)
    gate = fresh["projection_gate"]
    assert gate["status"] == "current"
    assert gate["projections_hidden"] is False
    assert gate["hinweis"] is None
    assert gate["hidden_channels"] == []
    assert fresh["goal_based_investing"]["monte_carlo_paths"]["data_pending"] is False
    assert fresh["ausgangslage"]["key_metrics"]["risky_fraction_bps"] is not None
    # PR #663 Positivkontrolle: aktueller Kontext publiziert das Risikobudget
    # (Score-Positivkontrolle mit bewerteten Zielen:
    # tests/test_report_projection_redaction.py).
    assert isinstance(fresh["risikoprofilierung"]["risky_fraction_bps"], int)
    assert fresh["stress_replay"]["scenarios"], fresh["stress_replay"]
    assert any(
        b["target_bps"] for b in fresh["building_blocks"]["blocks"]
    )
    assert fresh["asset_allocation"]["soll_ausgeblendet"] is False
    fresh_wealth = fresh["ausgangslage"]["wealth_summary"]

    _drop_current_assessment(session_factory, mid)
    report = _report(session_factory, mid)
    _assert_all_projections_hidden(report, status="blocked")

    # Berater-Hinweis: einheitlich in Gate, MC, Stress, Sektion 11 und den
    # Soll-Sektionen -- nicht die irrefuehrende "frueheres Risikoprofil"-Form.
    assert report["projection_gate"]["hinweis"] == HINT_NO_ASSESSMENT
    assert report["projection_gate"]["reason_code"] == "no_assessment"
    assert HINT_NO_ASSESSMENT in report["goal_based_investing"]["staleness_hinweis"]
    assert HINT_NO_ASSESSMENT in report["goal_based_investing"]["monte_carlo_paths"]["note"]
    assert HINT_NO_ASSESSMENT in report["stress_replay"]["note"]
    for section in ("asset_allocation", "risikowaehrungen", "branchen", "building_blocks"):
        hinweis = report[section]["staleness_hinweis"]
        assert HINT_NO_ASSESSMENT in hinweis, (section, hinweis)
        assert "frueheren" not in hinweis, (section, hinweis)

    # IST-Historie / Bestand bleibt sichtbar und ist typisiert getrennt.
    assert report["ausgangslage"]["wealth_summary"] == fresh_wealth
    assert "ausgangslage.wealth_summary" in report["projection_gate"]["historical_ist_channels"]
    assert "ausgangslage.key_metrics" in report["projection_gate"]["hidden_channels"]


@pytest.mark.timeout(180)
def test_stale_assessment_hides_every_channel_with_same_gate(
    session_factory, advisor_user, house_matrix  # noqa: F811
):
    mid = _seed_mandate(session_factory, advisor_user.id)
    _generate(session_factory, mid, advisor_user.id)
    _replace_current_assessment(session_factory, mid, advisor_user.id)

    report = _report(session_factory, mid)
    _assert_all_projections_hidden(report, status="stale")
    assert report["projection_gate"]["reason_code"] == "assessment"
    assert "Projektionen ausgeblendet" in report["projection_gate"]["hinweis"]


@pytest.mark.timeout(180)
def test_policy_not_current_blocks_soll_sections_although_depot_check_is_fresh(
    session_factory, advisor_user, house_matrix  # noqa: F811
):
    """Der Depot-Check kennt ``policy_not_current`` nicht (er meldet die
    Allokation als frisch). Der Report-Gate muss trotzdem auch die
    Soll-Sektionen 7-10/13 ausblenden -- EIN Entscheid fuer alle Kanaele."""
    mid = _seed_mandate(session_factory, advisor_user.id)
    allocation = _generate(session_factory, mid, advisor_user.id)
    with session_factory() as s:
        policy = s.get(OptimizerPolicy, allocation.policy_id)
        policy.is_current = 0
        s.commit()

    with session_factory() as s:
        from services.depot_check import compute_depot_check

        dc = compute_depot_check(s, s.get(Mandate, mid))
    assert dc["target_allocation_stale"] is False  # Voraussetzung des Tests

    report = _report(session_factory, mid)
    _assert_all_projections_hidden(report, status="blocked")
    assert report["projection_gate"]["reason_code"] == "policy_not_current"


@pytest.mark.timeout(120)
def test_gate_exception_is_fail_closed(
    session_factory, advisor_user, house_matrix, monkeypatch  # noqa: F811
):
    mid = _seed_mandate(session_factory, advisor_user.id)
    _generate(session_factory, mid, advisor_user.id)

    import services.report_projection_gate as rpg

    def _boom(*_args, **_kwargs):
        raise RuntimeError("gate kaputt")

    monkeypatch.setattr(rpg, "resolve_report_projection_gate", _boom)
    report = _report(session_factory, mid)
    _assert_all_projections_hidden(report, status="blocked")
    assert report["projection_gate"]["reason_code"] == "gate_error"


def test_unknown_gate_status_is_fail_closed():
    for status in ("stale", "blocked", "future_status", ""):
        assert ProjectionGate(status, "", "").is_hidden is True, status
    assert ProjectionGate("current", "", "").is_hidden is False
    assert ProjectionGate("no_allocation", "no_allocation", "").is_hidden is False
    assert ProjectionGate("blocked", "no_assessment", "x").hint == HINT_NO_ASSESSMENT


def test_projection_gate_cannot_be_hidden_by_report_configuration():
    from services.advisory_report import PROTECTED_REPORT_SECTIONS

    assert "projection_gate" in PROTECTED_REPORT_SECTIONS


# ---------------------------------------------------------------------------
# PDFs
# ---------------------------------------------------------------------------


@pytest.mark.timeout(180)
def test_advisory_pdf_shows_hint_and_no_projection_when_blocked(
    session_factory, advisor_user, house_matrix  # noqa: F811
):
    from reportlab.graphics.shapes import Drawing
    from reportlab.platypus import Paragraph

    from services.pdf.documents.advisory_report import (
        _build_ausgangslage_flowables,
        _build_goals_flowables,
        _build_stress_replay_flowables,
        make_advisory_styles,
    )

    mid = _seed_mandate(session_factory, advisor_user.id)
    _generate(session_factory, mid, advisor_user.id)
    _drop_current_assessment(session_factory, mid)
    report = _report(session_factory, mid)
    styles = make_advisory_styles()

    from reportlab.platypus import Table

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

    ausgangslage = _build_ausgangslage_flowables(
        report["ausgangslage"], styles,
        projection_gate=report["projection_gate"],
    )
    assert HINT_NO_ASSESSMENT in _texts(ausgangslage)

    goals = _build_goals_flowables(report["goal_based_investing"], styles)
    assert not any(isinstance(f, Drawing) for f in goals)
    assert HINT_NO_ASSESSMENT in _texts(goals)

    stress = _build_stress_replay_flowables(report["stress_replay"], styles)
    assert HINT_NO_ASSESSMENT in _texts(stress)


@pytest.mark.timeout(120)
def test_strategy_pdf_is_fail_closed_when_blocked(
    session_factory, advisor_user, house_matrix  # noqa: F811
):
    """Das Strategie-PDF projiziert dieselbe Allokation (MC/Zielanalyse) und
    muss bei ``blocked`` ebenfalls verweigern (Route -> 409)."""
    from routers.pdf_reports import _build_anlagestrategie_data

    mid = _seed_mandate(session_factory, advisor_user.id)
    _generate(session_factory, mid, advisor_user.id)
    _drop_current_assessment(session_factory, mid)
    with session_factory() as s:
        with pytest.raises(ValueError, match="Risikoprofil"):
            _build_anlagestrategie_data(s.get(Mandate, mid), s)


@pytest.mark.timeout(180)
def test_failure_distribution_visible_then_hidden_when_blocked(
    session_factory, advisor_user, house_matrix  # noqa: F811
):
    """GOAL-FAILURE-DISTRIBUTION-REPORT-001: die Ursachenverteilung ist ein
    Projektionskanal. Positivkontrolle (current: sichtbar) und ``blocked``
    (ausgeblendet, auch im PDF) auf derselben Fixture."""
    import json

    from models.allocation import TargetAllocation
    from reportlab.platypus import Paragraph

    from services.pdf.documents.advisory_report import (
        _build_goals_flowables,
        make_advisory_styles,
    )

    mid = _seed_mandate(session_factory, advisor_user.id)
    _generate(session_factory, mid, advisor_user.id)
    with session_factory() as session:
        ta = (
            session.query(TargetAllocation)
            .filter(TargetAllocation.mandate_id == mid, TargetAllocation.is_current == 1)
            .one()
        )
        ta.goal_achievability_json = json.dumps([{
            "goal_id": "g-fd", "label": "Hauskauf", "probability": 0.6,
            "status": "knapp", "hardness": "Hart",
            "evaluation_scope": "priority_funded", "funding_rank": 1,
            "failure_event_id": "liquiditaetsengpass-jahr-4",
            "failure_event_share": 0.75,
            "failure_event_distribution": [
                {"event_id": "liquiditaetsengpass-jahr-4", "weighted_mass": 3.0, "share": 0.75},
                {"event_id": "zielschwelle-g-fd", "weighted_mass": 1.0, "share": 0.25},
            ],
        }])
        session.commit()

    def _pdf_text(gbi: dict) -> str:
        return " ".join(
            f.getPlainText()
            for f in _build_goals_flowables(gbi, make_advisory_styles())
            if isinstance(f, Paragraph)
        )

    fresh = _report(session_factory, mid)
    assert fresh["projection_gate"]["status"] == "current"
    goal = next(g for g in fresh["goal_based_investing"]["goals"] if g["goal_id"] == "g-fd")
    assert [g["share_bps"] for g in goal["failure_cause_summary"]] == [7500, 2500]
    assert "Verfehlte Verläufe" in _pdf_text(fresh["goal_based_investing"])
    assert (
        "goal_based_investing.goals.failure_cause_summary"
        not in fresh["projection_gate"]["hidden_channels"]
    )

    _drop_current_assessment(session_factory, mid)
    report = _report(session_factory, mid)
    _assert_all_projections_hidden(report, status="blocked")
    assert (
        "goal_based_investing.goals.failure_cause_summary"
        in report["projection_gate"]["hidden_channels"]
    )
    assert "Verfehlte Verläufe" not in _pdf_text(report["goal_based_investing"])
