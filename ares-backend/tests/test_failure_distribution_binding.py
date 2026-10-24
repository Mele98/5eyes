"""GOAL-ACHIEVABILITY-ATTRIBUTION-001 -- semantische Bindung der
Ursachenverteilung an ihre Zielzeile.

Closure-Review PR #671 (Codex-Gate
``test_2026_10_23_pr671_failure_distribution_binding_adversarial.py``, hier
ohne xfail uebernommen): eine syntaktisch gueltige Verteilung wird nur
publiziert, wenn ihre zielspezifischen Ereignisse zur eigenen ``goal_id``
gehoeren und primaeres Ereignis/Anteil/Wahrscheinlichkeit ihr nicht
widersprechen. Sonst: nichts publizieren (fail-closed), Status
``integrity_mismatch``.

Die dauerhafte Snapshot-Bindung (Run/Goal-Set/Hash) ist NICHT Gegenstand
dieses Tests und bleibt offen.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


def _backend_root() -> Path:
    """Backend per Struktur finden (Verzeichnis mit ``main.py`` + ``services``)."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "main.py").is_file() and (parent / "services").is_dir():
            return parent
    raise RuntimeError("Backend-Verzeichnis nicht gefunden")


_BACKEND = _backend_root()
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from services.advisory_report import _failure_cause_fields  # noqa: E402
from services.goal_failure_causes import (  # noqa: E402
    is_bound_to_goal_row,
    normalize_failure_event_distribution,
)


def _row(**changes) -> dict:
    row = {
        "goal_id": "goal-a",
        "probability": 0.4,
        "evaluation_scope": "priority_funded",
        "funding_rank": 1,
        "failure_event_id": "liquiditaetsengpass-jahr-3",
        "failure_event_share": 1.0,
        "failure_event_distribution": [
            {"event_id": "liquiditaetsengpass-jahr-3", "share": 1.0},
        ],
    }
    row.update(changes)
    return row


# ---------------------------------------------------------------------------
# Codex-Gate PR #671 (ohne xfail)
# ---------------------------------------------------------------------------

def test_failure_distribution_rejects_threshold_event_from_another_goal() -> None:
    """A goal-specific threshold event must match the row's own goal_id."""
    published = _failure_cause_fields(
        _row(
            failure_event_id="zielschwelle-goal-b",
            failure_event_distribution=[
                {"event_id": "zielschwelle-goal-b", "share": 1.0},
            ],
        )
    )
    assert published["failure_event_distribution"] is None, published
    assert published["failure_cause_summary"] is None, published


def test_failure_distribution_rejects_primary_event_share_contradiction() -> None:
    """The mode and its share cannot contradict the full distribution."""
    published = _failure_cause_fields(
        _row(
            failure_event_id="liquiditaetsengpass-jahr-3",
            failure_event_share=0.9,
            failure_event_distribution=[
                {"event_id": "zielschwelle-goal-a", "share": 1.0},
            ],
        )
    )
    assert published["failure_event_distribution"] is None, published
    assert published["failure_cause_summary"] is None, published


# ---------------------------------------------------------------------------
# Positivkontrollen: engine-konforme Zeilen bleiben sichtbar
# ---------------------------------------------------------------------------

def test_bound_row_is_published_with_row_consistent_status() -> None:
    published = _failure_cause_fields(_row(
        failure_event_id="liquiditaetsengpass-jahr-3",
        failure_event_share=0.75,
        failure_event_distribution=[
            {"event_id": "liquiditaetsengpass-jahr-3", "share": 0.75},
            {"event_id": "zielschwelle-goal-a", "share": 0.25},
        ],
    ))
    assert [e["event_id"] for e in published["failure_event_distribution"]] == [
        "liquiditaetsengpass-jahr-3", "zielschwelle-goal-a",
    ]
    assert published["failure_cause_summary"]
    assert published["failure_evidence_status"] == "row_consistent"
    assert "failure_event_id" not in published  # primaeres Ereignis unveraendert


def test_return_goal_with_own_event_is_published() -> None:
    published = _failure_cause_fields(_row(
        target_kind="return_rate",
        failure_event_id="renditeziel-goal-a",
        failure_event_distribution=[{"event_id": "renditeziel-goal-a", "share": 1.0}],
    ))
    assert published["failure_cause_summary"][0]["kind"] == "renditeziel"


def test_tie_uses_engine_order_earlier_year_first() -> None:
    published = _failure_cause_fields(_row(
        failure_event_id="liquiditaetsengpass-jahr-2",
        failure_event_share=0.5,
        failure_event_distribution=[
            {"event_id": "liquiditaetsengpass-jahr-2", "share": 0.5},
            {"event_id": "zielschwelle-goal-a", "share": 0.5},
        ],
    ))
    assert published["failure_event_distribution"] is not None


def test_goal_without_failed_paths_stays_empty() -> None:
    published = _failure_cause_fields(_row(
        probability=1.0, failure_event_id=None, failure_event_share=None,
        failure_event_distribution=[],
    ))
    assert published["failure_event_distribution"] == []
    assert published["failure_evidence_status"] == "row_consistent"


# ---------------------------------------------------------------------------
# Negativvertraege
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "changes",
    [
        # fremdes Renditeziel
        {"failure_event_id": "renditeziel-goal-b",
         "failure_event_distribution": [{"event_id": "renditeziel-goal-b", "share": 1.0}]},
        # nacktes Plan-Ereignis ohne goal_id in einer Zielzeile
        {"failure_event_id": "zielschwelle",
         "failure_event_distribution": [{"event_id": "zielschwelle", "share": 1.0}]},
        # Art passt nicht zur target_kind
        {"target_kind": "wealth", "failure_event_id": "renditeziel-goal-a",
         "failure_event_distribution": [{"event_id": "renditeziel-goal-a", "share": 1.0}]},
        # primaeres Ereignis ist nicht der Modus
        {"failure_event_id": "zielschwelle-goal-a", "failure_event_share": 0.25,
         "failure_event_distribution": [
             {"event_id": "liquiditaetsengpass-jahr-3", "share": 0.75},
             {"event_id": "zielschwelle-goal-a", "share": 0.25}]},
        # Modus richtig, Anteil falsch (> 1 bp)
        {"failure_event_share": 0.74,
         "failure_event_distribution": [
             {"event_id": "liquiditaetsengpass-jahr-3", "share": 0.75},
             {"event_id": "zielschwelle-goal-a", "share": 0.25}]},
        # Tie-Break gegen die Engine-Reihenfolge
        {"failure_event_id": "zielschwelle-goal-a", "failure_event_share": 0.5,
         "failure_event_distribution": [
             {"event_id": "liquiditaetsengpass-jahr-2", "share": 0.5},
             {"event_id": "zielschwelle-goal-a", "share": 0.5}]},
        # fehlender primaerer Anteil
        {"failure_event_share": None},
        # doppelte Event-ID
        {"failure_event_share": 0.5, "failure_event_distribution": [
            {"event_id": "liquiditaetsengpass-jahr-3", "share": 0.5},
            {"event_id": "liquiditaetsengpass-jahr-3", "share": 0.5}]},
        # 100 % Wahrscheinlichkeit mit Failure-Evidence
        {"probability": 1.0},
        # leere Verteilung, aber primaeres Ereignis behauptet
        {"failure_event_distribution": []},
        # leere Verteilung trotz Wahrscheinlichkeit < 100 %
        {"failure_event_id": None, "failure_event_share": None,
         "failure_event_distribution": []},
        # fehlende goal_id
        {"goal_id": None},
    ],
    ids=[
        "foreign-return-goal", "bare-plan-event", "kind-vs-target-kind",
        "primary-not-mode", "primary-share-drift", "tie-break-drift",
        "primary-share-missing", "duplicate-event", "probability-one-with-failure",
        "empty-with-primary", "empty-below-one", "no-goal-id",
    ],
)
def test_unbound_or_contradictory_row_is_not_published(changes) -> None:
    published = _failure_cause_fields(_row(**changes))
    assert published["failure_event_distribution"] is None, published
    assert published["failure_cause_summary"] is None, published
    assert published["failure_evidence_status"] == "integrity_mismatch", published
    assert published["failure_event_id"] is None, published


def test_outside_horizon_row_without_distribution_is_not_a_contradiction() -> None:
    row = _row(
        probability=0.0, outside_simulation_horizon=True,
        failure_event_id=None, failure_event_share=None, failure_event_distribution=[],
    )
    assert is_bound_to_goal_row(row, normalize_failure_event_distribution(row))


def test_legacy_row_keeps_primary_event_without_distribution() -> None:
    row = _row()
    row.pop("failure_event_distribution")
    published = _failure_cause_fields(row)
    assert published["failure_event_distribution"] is None
    assert published["failure_evidence_status"] == "unavailable"
    assert "failure_event_id" not in published


# ---------------------------------------------------------------------------
# Positivkontrolle gegen echte Engine-Ausgabe (kein Orakel-Nachbau)
# ---------------------------------------------------------------------------

def _engine_goal(goal_id: str, *, wealth_target: bool):
    from types import SimpleNamespace

    return SimpleNamespace(
        id=goal_id, label=goal_id,
        goal_type="Vermögensziel" if wealth_target else "Einmalige_Ausgabe",
        target_amount_rappen=None if wealth_target else 90,
        target_wealth_rappen=140 if wealth_target else None,
        target_return_bps=None, horizon_years=3, target_date=None,
        start_date=None, is_ongoing=0, frequency=None, hardness="Hart",
        rank=1, weight_bps=None, value_mode="nominal",
        goal_scope="Beratungsvermögen", pension_pillar=None,
    )


@pytest.mark.parametrize(
    ("mean", "sd"), [(60.0, 80.0), (140.0, 40.0)], ids=["mit-liquiditaet", "nur-zielschwelle"],
)
def test_engine_published_rows_pass_binding_after_json_roundtrip(mean, sd) -> None:
    import json

    import numpy as np

    from services.optimizer.goal_attribution import publish_goal_achievability
    from services.optimizer.goal_liabilities import goals_to_liabilities

    liabilities = goals_to_liabilities(
        [_engine_goal("goal-x", wealth_target=mean > 100)], horizon_years=3,
    )
    rng = np.random.default_rng(7)
    wealth = np.column_stack(
        [np.full(400, 100.0)] + [rng.normal(mean, sd, 400) for _ in range(3)]
    )
    if mean > 100:
        wealth = np.abs(wealth)  # keine Insolvenz -> nur eigenes Zielereignis
    rows = json.loads(json.dumps(publish_goal_achievability(wealth, liabilities, 100)))
    goal_row = next(r for r in rows if r.get("goal_id") == "goal-x")
    assert goal_row["failure_event_distribution"], goal_row  # Positivkontrolle nicht leer
    published = _failure_cause_fields(goal_row)
    assert published["failure_evidence_status"] == "row_consistent", published
    assert published["failure_cause_summary"]
    if mean > 100:
        assert {e["kind"] for e in published["failure_event_distribution"]} == {"zielschwelle"}
