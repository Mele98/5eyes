"""P5b / N-925-03: M-3-Anzeige aus dem kanonischen Zielkennzahl-Payload.

Wuerfel-Hash, Pfadzahl und Rundung im Payload; Seed Pflicht; Status aus
Untergrenze und tau neu berechnet (nie aus der Zeile kopiert)."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from core.goal_metric_contract import (
    ESS_ABSOLUTE_FLOOR_X100,
    ESS_FRACTION_FLOOR_PPM,
    PPM_ROUNDING_POLICY,
    TAU_UNREACHABLE_PPM,
    GoalMetricUncertified,
    build_goal_metric_payload,
    canonical_goal_rows,
    goal_status_from_metric,
)

CUBE = "c" * 64


def _row(**over):
    row = {"goal_id": "g1", "evaluation_scope": "priority_funded", "probability": 0.91,
           "lower_confidence_bound": 0.78, "tau": 0.80, "effective_sample_size": 2000.0,
           "validation_seed": 4711, "status": "erreichbar", "outside_simulation_horizon": False}
    row.update(over)
    return row


def _ta(rows, *, seed=4711, cube=CUBE, n_paths=2000):
    goal = SimpleNamespace(id="g1", label="Haus", rank=1, hardness="Primär", target_amount_rappen=100_000_00,
                           target_wealth_rappen=0, target_date="2035-01-01", is_active=1, is_included=1,
                           deleted_at=None)
    mandate = SimpleNamespace(base_currency="CHF", goals=[goal])
    run = SimpleNamespace(validation_seed=seed, validation_cube_hash=cube, validation_n_paths=n_paths)
    ta = SimpleNamespace(id="ta1", goal_achievability_json=json.dumps(rows), optimization_run=run, mandate=mandate)
    return ta, goal, mandate


def test_status_constants_equal_the_certification_chain():
    from services.optimizer.certification import ESS_ABSOLUTE_FLOOR, ESS_FRACTION_FLOOR
    from services.optimizer.objective import TAU_UNREACHABLE

    assert ESS_ABSOLUTE_FLOOR_X100 == round(ESS_ABSOLUTE_FLOOR * 100)
    assert ESS_FRACTION_FLOOR_PPM == round(ESS_FRACTION_FLOOR * 1_000_000)
    assert TAU_UNREACHABLE_PPM == round(TAU_UNREACHABLE * 1_000_000)


def test_status_is_recomputed_from_lower_bound_and_tau_not_copied():
    """Zeile sagt «erreichbar», Untergrenze 0.78 < tau 0.80 -> knapp."""
    ta, goal, mandate = _ta([_row()])
    payload = build_goal_metric_payload([goal], mandate=mandate, target_allocation=ta)
    entry = payload["goals"][0]
    assert entry["status"] == "knapp"
    assert payload["validation"] == {"seed": 4711, "cube_hash": CUBE, "n_paths": 2000}
    assert payload["rounding_policy"] == PPM_ROUNDING_POLICY
    shown = canonical_goal_rows([_row()], ta)[0]
    assert shown["status"] == "knapp" and shown["goal_metric_payload_hash"] == payload["goal_metric_payload_hash"]


def test_status_chain_matches_the_optimizer_rule():
    import numpy as np

    from services.optimizer.objective import certify_success_indicator

    for successes, n in ((1990, 2000), (1700, 2000), (900, 2000), (25, 40)):
        per_path = np.array([1] * successes + [0] * (n - successes), dtype=float)
        est = certify_success_indicator(per_path, tau=0.80, weights_arr=None, weight_sum=None, validation_seed=1)
        ppm = lambda v: int(round(v * 1_000_000))  # noqa: E731
        assert goal_status_from_metric(
            probability_ppm=ppm(est["probability"]), lower_bound_ppm=ppm(est["lower_confidence_bound"]),
            tau_ppm=800_000, ess_x100=int(round(est["effective_sample_size"] * 100)), n_paths=n,
            outside_horizon=False) == est["status"]


@pytest.mark.parametrize("change", [
    {"row": {"validation_seed": None}},
    {"row": {"validation_seed": 1}},          # weicht vom Lauf ab
    {"ta": {"cube": None}},
    {"ta": {"n_paths": 0}},
])
def test_seed_cube_and_path_count_are_mandatory(change):
    ta, goal, mandate = _ta([_row(**change.get("row", {}))], **change.get("ta", {}))
    with pytest.raises(GoalMetricUncertified):
        build_goal_metric_payload([goal], mandate=mandate, target_allocation=ta)
    # P5c / N-930-01: ohne M-3 "nicht bewertbar" (fail-closed), nie der gespeicherte Status.
    assert canonical_goal_rows([_row(**change.get("row", {}))], ta)[0]["status"] == "nicht_bewertbar"


def test_cube_hash_and_path_count_change_the_payload_hash():
    ta1, goal, mandate = _ta([_row()])
    ta2, _g, _m = _ta([_row()], cube="d" * 64)
    ta3, _g, _m = _ta([_row()], n_paths=4000)
    hashes = {build_goal_metric_payload([goal], mandate=mandate, target_allocation=t)["goal_metric_payload_hash"]
              for t in (ta1, ta2, ta3)}
    assert len(hashes) == 3


def test_display_from_payload_in_app_payload_and_report():
    """N-925-03: App-Payload (``_stored_goal_achievability``) und Bericht
    (``split_goal_achievability`` ueber ``_goal_rows``) zeigen den Payload-
    Status, nicht die gespeicherte Zeile."""
    from services.portfolio_engine_payload import _stored_goal_achievability

    ta, _goal, _mandate = _ta([_row()])
    ta.effective_constraints_json = None
    rows = _stored_goal_achievability(ta)
    assert rows[0]["status"] == "knapp" and rows[0]["goal_metric_payload_hash"]


def test_payload_goal_revision_ignores_timestamp_touch_but_not_material_change():
    """N-925-08 (Querschnitt): eine reine Beruehrung des Ziels (updated_at)
    laesst den M-3-Hash und damit den Entscheid FRESH; eine fachliche
    Aenderung nicht."""
    ta, goal, mandate = _ta([_row()])
    goal.updated_at = "2026-11-01"
    before = build_goal_metric_payload([goal], mandate=mandate, target_allocation=ta)["goal_metric_payload_hash"]
    goal.updated_at = "2026-11-21T10:00:00"
    assert build_goal_metric_payload([goal], mandate=mandate, target_allocation=ta)["goal_metric_payload_hash"] == before
    goal.target_date = "2036-01-01"
    assert build_goal_metric_payload([goal], mandate=mandate, target_allocation=ta)["goal_metric_payload_hash"] != before
