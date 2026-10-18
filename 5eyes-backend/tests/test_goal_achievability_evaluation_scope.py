"""GOAL-ACHIEVABILITY-ATTRIBUTION-001 -- typisierter Evaluation-Scope.

Audit: docs/audits/2026-09-28-goal-funding-priority-and-achievability-attribution-audit.md
(Finding ``GOAL-ACHIEVABILITY-ATTRIBUTION-001``, verbindlicher Reparaturvertrag
Punkte 1-6 und Pflicht-Negativtests 1-6).

Owner-Entscheid (2026-10-14):

* Jede publizierte Zielzeile traegt einen diskriminierten ``evaluation_scope``.
  - ``priority_funded``: Funding-Ledger nach Rang. Auf jedem Pfad werden die
    Ziele in kanonischer Rangfolge finanziert (Rang 1 zuerst); ein Ziel gilt
    auf einem Pfad als erreicht, wenn es NACH allen hoeher priorisierten
    Zielen voll finanziert ist. Gleichrangige Ziele teilen sich einen Scope
    (sie werden gemeinsam finanziert, keine erfundene Reihenfolge); die Haerte
    wirkt nur ueber Gewicht und Chance-Penalty, nie ueber die
    Finanzierungsreihenfolge (GOAL-FUNDING-PRIORITY-001: Rang ist die einzige
    Funding-Prioritaet).
  - ``joint_plan``: Plan-Solvenz -- alle Ziele gemeinsam auf dem tatsaechlich
    simulierten Pfad. Genau EINE Zeile, nie pro Ziel wiederholt.
* Gemeinsame Failure-Events werden typisiert (``failure_event_id``) und in der
  Konfliktklassifikation dedupliziert.
* Die Chance-Constraint-/Objective-Mathematik bleibt unveraendert.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.optimizer.goal_liabilities import goals_to_liabilities
from services.optimizer.objective import chance_constraint_penalty
from services.optimizer.scenario_engine import N_BUCKETS, simulate_wealth_paths
from services.risk_matrix import classify_limiting_factor


def _goal(
    *,
    goal_id: str,
    goal_type: str,
    hardness: str,
    rank: int,
    target_wealth_rappen: int | None = None,
    target_amount_rappen: int | None = None,
    horizon_years: int = 1,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=goal_id,
        label=goal_id,
        goal_type=goal_type,
        target_amount_rappen=target_amount_rappen,
        target_wealth_rappen=target_wealth_rappen,
        target_return_bps=None,
        horizon_years=horizon_years,
        target_date=None,
        start_date=None,
        is_ongoing=0,
        frequency=None,
        hardness=hardness,
        rank=rank,
        weight_bps=None,
        value_mode="nominal",
        goal_scope="Beratungsvermoegen",
        pension_pillar=None,
    )


def _simulate(
    initial_wealth_rappen: int,
    liability_path_rappen: list[int],
    *,
    horizon_years: int,
    growth: float = 1.0,
    n_paths: int = 1,
) -> np.ndarray:
    weights = np.full(N_BUCKETS, 1.0 / N_BUCKETS, dtype=np.float64)
    return_paths = np.full((n_paths, horizon_years, N_BUCKETS), growth, dtype=np.float64)
    return simulate_wealth_paths(
        initial_wealth_rappen=initial_wealth_rappen,
        weights=weights,
        return_paths=return_paths,
        cashflow_series_rappen=[0] * horizon_years,
        liability_path_rappen=liability_path_rappen,
    )


def _audit_repro():
    """Audit-Repro: CHF 100, gleichzeitig CHF 90 (Rang 1, hart) und CHF 20
    (Rang 2, opportunistisch) im Jahr 1."""
    hard = _goal(
        goal_id="hart-90", goal_type="Einmalige_Ausgabe", hardness="Hart",
        rank=1, target_amount_rappen=90,
    )
    opp = _goal(
        goal_id="opp-20", goal_type="Einmalige_Ausgabe", hardness="Opportunistisch",
        rank=2, target_amount_rappen=20,
    )
    liabilities = goals_to_liabilities([hard, opp], horizon_years=1)
    wealth = _simulate(100, liabilities[0].joint_liability_path_rappen, horizon_years=1)
    np.testing.assert_allclose(wealth, [[100.0, -10.0]])
    return liabilities, wealth


def _publish(wealth, liabilities, initial, **kwargs):
    from services.optimizer.goal_attribution import publish_goal_achievability

    return publish_goal_achievability(
        wealth, liabilities, initial,
        weights=kwargs.pop("weights", None),
        annualized_return_bps_per_path=kwargs.pop("annualized_return_bps_per_path", None),
        validation_seed=kwargs.pop("validation_seed", None),
    )


def _split(rows):
    from services.optimizer.goal_attribution import split_goal_achievability

    return split_goal_achievability(rows)


# ---------------------------------------------------------------------------
# Pflichttest 1: zwei simultane Ausgaben unterschiedlicher Groesse/Prioritaet
# ---------------------------------------------------------------------------


def test_simultaneous_goals_get_priority_funded_individual_evidence():
    liabilities, wealth = _audit_repro()
    rows = _publish(wealth, liabilities, 100)
    goal_rows, plan_row = _split(rows)

    by_id = {row["goal_id"]: row for row in goal_rows}
    assert set(by_id) == {"hart-90", "opp-20"}
    assert all(row["evaluation_scope"] == "priority_funded" for row in goal_rows)
    # Rang 1 wird zuerst finanziert: 100 - 90 = 10 >= 0 -> erreicht.
    assert by_id["hart-90"]["probability"] == pytest.approx(1.0)
    # Rang 2 erst danach: 10 - 20 < 0 -> nicht finanziert.
    assert by_id["opp-20"]["probability"] == pytest.approx(0.0)
    assert by_id["hart-90"]["probability"] != by_id["opp-20"]["probability"]
    assert by_id["hart-90"]["funding_rank"] == 1
    assert by_id["opp-20"]["funding_rank"] == 2

    # Die gemeinsame Plan-Solvenz ist 0: auf dem simulierten Pfad werden
    # nicht alle Ziele gemeinsam finanziert.
    assert plan_row is not None
    assert plan_row["evaluation_scope"] == "joint_plan"
    assert plan_row["goal_id"] is None
    assert plan_row["probability"] == pytest.approx(0.0)
    assert plan_row["label"] == "Plan-Solvenz (alle Ziele gemeinsam)"
    assert sorted(plan_row["goal_ids"]) == ["hart-90", "opp-20"]


def test_exactly_one_joint_plan_row_and_no_joint_value_on_goal_rows():
    """Pflichttest 5 / Vertragspunkt 4: der Joint-Wert existiert genau einmal."""
    liabilities, wealth = _audit_repro()
    rows = _publish(wealth, liabilities, 100)
    plan_rows = [row for row in rows if row.get("evaluation_scope") == "joint_plan"]
    assert len(plan_rows) == 1
    goal_rows = [row for row in rows if row.get("evaluation_scope") != "joint_plan"]
    assert len(goal_rows) == 2
    for row in goal_rows:
        assert row["evaluation_scope"] == "priority_funded"
        assert row["funding_policy_version"]
        assert not any(key.startswith("joint") for key in row), row


def test_every_published_row_has_a_scope():
    """Vertragspunkt 2: ``probability`` ohne Scope ist unzulaessig."""
    liabilities, wealth = _audit_repro()
    for row in _publish(wealth, liabilities, 100):
        assert row.get("evaluation_scope") in {"priority_funded", "joint_plan"}


# ---------------------------------------------------------------------------
# Pflichttest 2: ein gemeinsames Failure-Event ist EIN Konflikt
# ---------------------------------------------------------------------------


def _conflict_kwargs(rows):
    return dict(
        allocation_bps={"liquidity": 1000},
        risky_fraction=5000,
        max_risky_fraction=6000,
        min_liquidity_bps=500,
        bands={},
        achievability=rows,
        optimization_status="converged",
    )


def test_shared_liquidity_bottleneck_is_one_failure_event():
    """CHF 100, Rang 1 hart CHF 110 und Rang 2 primaer CHF 20 im selben Jahr:
    beide Ziele scheitern am SELBEN Engpass (Jahr 1)."""
    a = _goal(goal_id="a-110", goal_type="Einmalige_Ausgabe", hardness="Hart",
              rank=1, target_amount_rappen=110)
    b = _goal(goal_id="b-20", goal_type="Einmalige_Ausgabe", hardness="Primaer",
              rank=2, target_amount_rappen=20)
    liabilities = goals_to_liabilities([a, b], horizon_years=1)
    wealth = _simulate(100, liabilities[0].joint_liability_path_rappen, horizon_years=1)
    goal_rows, _plan = _split(_publish(wealth, liabilities, 100))
    by_id = {row["goal_id"]: row for row in goal_rows}
    assert by_id["a-110"]["status"] == "nicht_erreichbar"
    assert by_id["b-20"]["status"] == "nicht_erreichbar"
    assert by_id["a-110"]["failure_event_id"] == by_id["b-20"]["failure_event_id"]
    assert by_id["a-110"]["failure_event_id"] == "liquiditaetsengpass-jahr-1"

    verdict = classify_limiting_factor(**_conflict_kwargs(goal_rows))
    assert verdict == "gemeinsamer_engpass"


def test_independent_failures_remain_two_conflicts():
    """Rang 1: Vermoegensschwelle CHF 200 in Jahr 2 (verfehlt ohne Insolvenz),
    Rang 2: Ausgabe CHF 150 in Jahr 1 (Insolvenz Jahr 1) -- zwei Ursachen."""
    wealth_goal = _goal(goal_id="w-200", goal_type="Vermoegensziel", hardness="Hart",
                        rank=1, target_wealth_rappen=200, horizon_years=2)
    spend = _goal(goal_id="s-150", goal_type="Einmalige_Ausgabe", hardness="Primaer",
                  rank=2, target_amount_rappen=150, horizon_years=1)
    liabilities = goals_to_liabilities([wealth_goal, spend], horizon_years=2)
    wealth = _simulate(100, liabilities[0].joint_liability_path_rappen, horizon_years=2)
    goal_rows, _plan = _split(_publish(wealth, liabilities, 100))
    by_id = {row["goal_id"]: row for row in goal_rows}
    assert by_id["w-200"]["status"] == "nicht_erreichbar"
    assert by_id["s-150"]["status"] == "nicht_erreichbar"
    assert by_id["w-200"]["failure_event_id"] != by_id["s-150"]["failure_event_id"]
    assert classify_limiting_factor(**_conflict_kwargs(goal_rows)) == "zielkonflikt"


# ---------------------------------------------------------------------------
# Pflichttest 4: Reihenfolge/Labels aendern Mathematik und Event-ID nicht
# ---------------------------------------------------------------------------


def test_input_order_does_not_change_rows_or_event_ids():
    rng = np.random.default_rng(20261014)
    a = _goal(goal_id="a", goal_type="Einmalige_Ausgabe", hardness="Hart",
              rank=1, target_amount_rappen=60, horizon_years=2)
    b = _goal(goal_id="b", goal_type="Einmalige_Ausgabe", hardness="Primaer",
              rank=2, target_amount_rappen=40, horizon_years=1)
    c = _goal(goal_id="c", goal_type="Vermoegensziel", hardness="Opportunistisch",
              rank=3, target_wealth_rappen=30, horizon_years=3)
    horizon = 3
    forward = goals_to_liabilities([a, b, c], horizon_years=horizon)
    backward = goals_to_liabilities([c, b, a], horizon_years=horizon)
    factors = rng.lognormal(mean=0.02, sigma=0.25, size=(400, horizon, N_BUCKETS))
    weights = np.full(N_BUCKETS, 1.0 / N_BUCKETS, dtype=np.float64)
    wealth = simulate_wealth_paths(
        initial_wealth_rappen=100,
        weights=weights,
        return_paths=factors,
        cashflow_series_rappen=[0] * horizon,
        liability_path_rappen=forward[0].joint_liability_path_rappen,
    )
    rows_f = {r["goal_id"]: r for r in _publish(wealth, forward, 100)}
    rows_b = {r["goal_id"]: r for r in _publish(wealth, backward, 100)}
    assert rows_f.keys() == rows_b.keys()
    for key in rows_f:
        for field_name in ("probability", "status", "failure_event_id", "evaluation_scope"):
            assert rows_f[key].get(field_name) == rows_b[key].get(field_name), (key, field_name)


def test_single_goal_priority_funded_equals_plan_solvency():
    only = _goal(goal_id="only", goal_type="Einmalige_Ausgabe", hardness="Hart",
                 rank=1, target_amount_rappen=90)
    liabilities = goals_to_liabilities([only], horizon_years=1)
    rng = np.random.default_rng(7)
    factors = rng.lognormal(mean=0.0, sigma=0.2, size=(300, 1, N_BUCKETS))
    weights = np.full(N_BUCKETS, 1.0 / N_BUCKETS, dtype=np.float64)
    wealth = simulate_wealth_paths(
        initial_wealth_rappen=100, weights=weights, return_paths=factors,
        cashflow_series_rappen=[0], liability_path_rappen=[90],
    )
    goal_rows, plan_row = _split(_publish(wealth, liabilities, 100))
    assert len(goal_rows) == 1
    assert goal_rows[0]["probability"] == pytest.approx(plan_row["probability"])


def test_importance_weights_are_used_for_both_scopes():
    liabilities, _ = _audit_repro()
    # Zwei Pfade: einer mit Wachstum (alles finanzierbar), einer ohne.
    wealth = np.array([[100.0, 40.0], [100.0, -10.0]])
    weights = np.array([3.0, 1.0])
    goal_rows, plan_row = _split(_publish(wealth, liabilities, 100, weights=weights))
    assert plan_row["probability"] == pytest.approx(0.75)
    by_id = {row["goal_id"]: row for row in goal_rows}
    assert by_id["opp-20"]["probability"] == pytest.approx(0.75)
    assert by_id["hart-90"]["probability"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Objective-Mathematik bleibt unveraendert
# ---------------------------------------------------------------------------


def test_chance_penalty_still_uses_the_joint_path():
    """Die Chance-Penalty (Ziel-Untergrenze im SLSQP-Objective) ist bewusst
    unveraendert: sie bewertet weiterhin den gemeinsamen Pfad. Ihre Zeilen
    sind als interne Sicht getaggt und werden nicht publiziert."""
    liabilities, wealth = _audit_repro()
    penalty, rows = chance_constraint_penalty(wealth, liabilities, 100)
    by_id = {row["goal_id"]: row for row in rows}
    assert by_id["hart-90"]["probability"] == pytest.approx(0.0)
    assert penalty > 0.0
    assert all(row["evaluation_scope"] == "joint_path_chance_penalty" for row in rows)


# ---------------------------------------------------------------------------
# Pflichttest 6: Legacy-Zeilen ohne Scope
# ---------------------------------------------------------------------------


def test_legacy_rows_without_scope_are_quarantined_on_read():
    legacy = [
        {"goal_id": "x", "label": "X", "probability": 0.4, "status": "nicht_erreichbar",
         "hardness": "hart"},
    ]
    goal_rows, plan_row = _split(legacy)
    assert plan_row is None
    assert goal_rows[0]["evaluation_scope"] == "legacy_aggregate_unknown"
    # Der Leser veraendert die Eingabe nicht.
    assert "evaluation_scope" not in legacy[0]


def test_split_returns_goal_rows_in_canonical_rank_order():
    liabilities, wealth = _audit_repro()
    rows = _publish(wealth, liabilities[::-1], 100)
    goal_rows, _ = _split(rows)
    assert [row["goal_id"] for row in goal_rows] == ["hart-90", "opp-20"]


# ---------------------------------------------------------------------------
# Produktionspfad: run_solver publiziert den typisierten Vertrag
# ---------------------------------------------------------------------------


def _solver_goals():
    from datetime import date, timedelta

    today = date.today()
    pension = SimpleNamespace(
        id="goal-pension", label="Pension", goal_type="Pensionsausgabe",
        target_amount_rappen=24_000_00, target_wealth_rappen=None,
        target_return_bps=None, horizon_years=None,
        start_date=(today + timedelta(days=365 * 5)).isoformat(),
        target_date=(today + timedelta(days=365 * 25)).isoformat(),
        is_ongoing=0, frequency="jährlich", hardness="Hart", rank=1,
        weight_bps=5000, value_mode="real",
    )
    house = SimpleNamespace(
        id="goal-house", label="Hauskauf", goal_type="Einmalige_Ausgabe",
        target_amount_rappen=180_000_00, target_wealth_rappen=None,
        target_return_bps=None, horizon_years=3, start_date=None,
        target_date=(today + timedelta(days=365 * 3)).isoformat(),
        is_ongoing=0, frequency=None, hardness="Opportunistisch", rank=2,
        weight_bps=None, value_mode="nominal",
    )
    return [pension, house]


def test_run_solver_publishes_priority_funded_rows_and_one_plan_row():
    TESTS_ROOT = Path(__file__).resolve().parent
    if str(TESTS_ROOT) not in sys.path:
        sys.path.insert(0, str(TESTS_ROOT))
    from test_optimizer_context import _cma, _house_matrix
    from services.optimizer.solver import run_solver

    result = run_solver(
        cma=_cma(), goals=_solver_goals(), house_matrix_row=_house_matrix(),
        score_x10=70, advisory_wealth_rappen=500_000_00,
        cashflow_series_rappen=[20_000_00] * 10, horizon_years=10,
        n_paths=400, seed=20261014,
    )
    rows = list(result.goal_achievability)
    plan_rows = [r for r in rows if r.get("evaluation_scope") == "joint_plan"]
    goal_rows = [r for r in rows if r.get("evaluation_scope") != "joint_plan"]
    assert len(plan_rows) == 1, rows
    assert {r["goal_id"] for r in goal_rows} == {"goal-pension", "goal-house"}
    assert all(r["evaluation_scope"] == "priority_funded" for r in goal_rows)
    # Rang 1 kann nach Prioritaet nie schlechter dastehen als der Gesamtplan.
    by_id = {r["goal_id"]: r for r in goal_rows}
    assert by_id["goal-pension"]["probability"] >= plan_rows[0]["probability"] - 1e-12
    # Validierungsanker auch auf der Planzeile.
    if result.validation_seed is not None:
        assert plan_rows[0]["validation_seed"] == result.validation_seed


def _simultaneous_solver_goals():
    """Audit-Repro im Produktionspfad: CHF 500'000, im selben Jahr 3 eine
    harte Ausgabe Rang 1 (CHF 350'000) und eine opportunistische Rang 2
    (CHF 350'000). Gemeinsam selten finanzierbar, Rang 1 allein praktisch
    immer."""
    from datetime import date, timedelta

    due = (date.today() + timedelta(days=365 * 3)).isoformat()

    def _spend(goal_id, label, hardness, rank):
        return SimpleNamespace(
            id=goal_id, label=label, goal_type="Einmalige_Ausgabe",
            target_amount_rappen=350_000_00, target_wealth_rappen=None,
            target_return_bps=None, horizon_years=3, start_date=None,
            target_date=due, is_ongoing=0, frequency=None,
            hardness=hardness, rank=rank, weight_bps=None, value_mode="nominal",
        )

    return [
        _spend("goal-hard", "Hauskauf", "Hart", 1),
        _spend("goal-opp", "Ferienwohnung", "Opportunistisch", 2),
    ]


def test_run_solver_rank_one_goal_is_not_dragged_down_by_a_lower_priority_goal():
    """Reproducer GOAL-ACHIEVABILITY-ATTRIBUTION-001 im Produktionspfad.

    Vorher publizierte ``run_solver`` fuer BEIDE Ziele den gemeinsamen
    Planwert (hier rund 20 %): das harte Rang-1-Ziel wurde wegen des
    opportunistischen Rang-2-Ziels als unerreichbar ausgewiesen."""
    TESTS_ROOT = Path(__file__).resolve().parent
    if str(TESTS_ROOT) not in sys.path:
        sys.path.insert(0, str(TESTS_ROOT))
    from test_optimizer_context import _cma, _house_matrix
    from services.optimizer.solver import run_solver

    result = run_solver(
        cma=_cma(), goals=_simultaneous_solver_goals(),
        house_matrix_row=_house_matrix(), score_x10=70,
        advisory_wealth_rappen=500_000_00, cashflow_series_rappen=[0] * 5,
        horizon_years=5, n_paths=400, seed=20261016,
    )
    rows = list(result.goal_achievability)
    by_id = {r.get("goal_id"): r for r in rows if r.get("goal_id")}
    hard, opp = by_id["goal-hard"], by_id["goal-opp"]
    # Kern: Rang 1 wird zuerst finanziert und ist praktisch immer erreicht.
    assert hard["probability"] >= 0.95, hard
    assert hard["status"] == "erreichbar", hard
    # Rang 2 bekommt, was nach Rang 1 uebrig bleibt -- meist zu wenig.
    assert opp["probability"] <= 0.5, opp
    assert opp["status"] == "nicht_erreichbar", opp
    # Der gemeinsame Wert steht genau einmal, als Plan-Solvenz. Fuer das
    # tiefst priorisierte Ziel umfasst der Rang-Scope alle Ziele -- dort sind
    # Zielzeile und Plan-Solvenz per Konstruktion gleich.
    plan_rows = [r for r in rows if r.get("evaluation_scope") == "joint_plan"]
    assert len(plan_rows) == 1, rows
    assert plan_rows[0]["probability"] == pytest.approx(opp["probability"])
    assert hard["probability"] - plan_rows[0]["probability"] >= 0.5
    assert hard["evaluation_scope"] == opp["evaluation_scope"] == "priority_funded"
