"""GOAL-FUNDING-PRIORITY-001 (Kontrollrunde 37) -- Gewichtungsmodus vs. Rang.

STATUS 2026-10-25: ueberholt durch Owner-Entscheid 9a (priorisiertes Goal
Funding nach RANG, Entscheidungsprotokoll 2026-10-11 in
docs/planning/2026-10-04-goal-engine-time-lifecycle-scheduler-validation-unification.md)
und dessen Umsetzung (Prioritaets-Scopes S_r = {h | rank(h) <= r} in
``goals_to_liabilities``, direkter Replay ab Engine v10). Der fruehere rote
Test verlangte, dass der GEWICHTUNGSMODUS (``OPTIMIZER_GOAL_WEIGHTING=
hardness``) die Finanzierungsreihenfolge repariert, und setzte dafuer
gleichzeitig voraus, dass das harte Ziel im Standardmodus bei P=0 bleibt --
ein Vertrag, den der Owner-Entscheid gerade nicht vorsieht: die Reihenfolge
kommt aus dem Rang, nicht aus dem Gewichtungsmodus. Der Test unten prueft den
gueltigen Vertrag auf dem Produktionspfad: das harte Rang-1-Ziel ist in BEIDEN
Modi gegen den Abfluss des Rang-5-Ziels geschuetzt, mit identischem Ergebnis.

Urspruenglicher Befund (zur Einordnung):

Audit finding: the optimizer has no goal-funding priority mechanism — every
spending goal's outflow is subtracted unconditionally from the shared wealth
path (services.optimizer.goal_liabilities.aggregate_liability_path) before
any goal's achievability is evaluated. The opt-in hardness-weighting mode
(OPTIMIZER_GOAL_WEIGHTING=hardness) does NOT repair this: it only rescales
the shortfall contribution inside the primary MSE objective
(services.optimizer.objective.shortfall_objective via
_effective_hardness_weight), while the chance-constraint penalty
(services.optimizer.objective.chance_constraint_penalty) never reads
OPTIMIZER_GOAL_WEIGHTING at all and operates on the exact same wealth path
in both modes. So a hard goal that is starved by an opportunistic goal's
outflow stays at 0% achievability, with the identical chance-penalty value,
in both equal and hardness weighting modes.

Scenario (same two-goal setup as the sibling repro task
round47-funding-priority-repro1, built independently from scratch here):
  initial wealth CHF 100, return factor 1.0 (no growth)
  Goal A: Vermoegensziel, Hart, rank 1, target CHF 90, due year 2
  Goal B: Einmalige_Ausgabe, Opportunistisch, rank 5, amount CHF 20, due year 1

See docs/audits/2026-09-28-goal-funding-priority-and-achievability-attribution-audit.md.
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

from sqlalchemy.orm import configure_mappers

from database import Base  # noqa: F401
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, tenant, users, wealth,
)

configure_mappers()

from services.optimizer.goal_liabilities import (
    GoalLiability,
    aggregate_liability_path,
    goal_to_liability,
    goals_to_liabilities,
)
from services.optimizer.objective import chance_constraint_penalty
from services.optimizer.scenario_engine import simulate_wealth_paths

HORIZON_YEARS = 2
INITIAL_WEALTH_RAPPEN = 100_00  # CHF 100
N_PATHS = 50


def _goal_a_vermoegensziel_hart() -> SimpleNamespace:
    """Hard wealth goal, rank 1, target CHF 90 due year 2."""
    return SimpleNamespace(
        id="goal-a-hart",
        label="Vermoegensziel Hart",
        goal_type="Vermoegensziel",
        target_wealth_rappen=90_00,  # CHF 90
        target_amount_rappen=None,
        target_return_bps=None,
        horizon_years=HORIZON_YEARS,
        target_date=None,
        start_date=None,
        is_ongoing=0,
        frequency=None,
        hardness="Hart",
        rank=1,
        weight_bps=None,
        value_mode="nominal",
        goal_scope="Beratungsvermoegen",
        pension_pillar=None,
        probability_pct=None,
        success_probability_min_x100=None,
    )


def _goal_b_einmalige_ausgabe_opportunistisch() -> SimpleNamespace:
    """Opportunistic one-off spending goal, rank 5, amount CHF 20 due year 1."""
    return SimpleNamespace(
        id="goal-b-opportunistisch",
        label="Einmalige Ausgabe Opportunistisch",
        goal_type="Einmalige_Ausgabe",
        target_wealth_rappen=None,
        target_amount_rappen=20_00,  # CHF 20
        target_return_bps=None,
        horizon_years=1,
        target_date=None,
        start_date=None,
        is_ongoing=0,
        frequency=None,
        hardness="Opportunistisch",
        rank=5,
        weight_bps=None,
        value_mode="nominal",
        goal_scope="Beratungsvermoegen",
        pension_pillar=None,
        probability_pct=None,
        success_probability_min_x100=None,
    )


def _build_liabilities() -> tuple[GoalLiability, GoalLiability]:
    goal_a = goal_to_liability(_goal_a_vermoegensziel_hart(), horizon_years=HORIZON_YEARS)
    goal_b = goal_to_liability(
        _goal_b_einmalige_ausgabe_opportunistisch(), horizon_years=HORIZON_YEARS
    )
    assert goal_a.target_kind == "wealth_at_t"
    assert goal_a.target_year_index == 2
    assert goal_a.target_amount_rappen == 90_00
    assert goal_b.target_kind == "cashflow_in_year"
    assert goal_b.liability_path_rappen == [20_00, 0]
    return goal_a, goal_b


def _run_scenario() -> tuple[float, float, list[dict]]:
    """Builds the shared wealth path via real production functions and
    returns (goal_a_probability, goal_a_chance_penalty, achievability_rows).

    Uses the exact same unconditional-subtraction call path the audit
    describes: aggregate_liability_path() sums ALL goal outflows (hard and
    opportunistic alike) BEFORE any per-goal evaluation happens, and that
    aggregate is what simulate_wealth_paths() subtracts from the shared
    wealth path.
    """
    goal_a, goal_b = _build_liabilities()
    liabilities = [goal_a, goal_b]

    liability_path = aggregate_liability_path(liabilities, horizon_years=HORIZON_YEARS)
    assert liability_path == [20_00, 0]

    # return factor 1.0 == no growth, no volatility: weight everything on a
    # single bucket so the dot-product is exactly 1.0 every year/path.
    weights = np.array([0.0, 0.0, 0.0, 0.0, 1.0])
    return_paths = np.ones((N_PATHS, HORIZON_YEARS, 5), dtype=np.float64)

    wealth_paths = simulate_wealth_paths(
        initial_wealth_rappen=INITIAL_WEALTH_RAPPEN,
        weights=weights,
        return_paths=return_paths,
        cashflow_series_rappen=[0, 0],
        liability_path_rappen=liability_path,
    )
    # Sanity: deterministic path, opportunistic Goal B's outflow is taken
    # unconditionally before Goal A (due a year later) is ever evaluated.
    assert np.all(wealth_paths[:, 1] == 80_00)  # 100 - 20 (Goal B outflow)
    assert np.all(wealth_paths[:, 2] == 80_00)  # no growth, no further outflow

    penalty, rows = chance_constraint_penalty(
        wealth_paths,
        liabilities,
        initial_value_rappen=INITIAL_WEALTH_RAPPEN,
    )
    goal_a_row = next(row for row in rows if row["goal_id"] == "goal-a-hart")
    return float(goal_a_row["probability"]), float(penalty), rows


def _run_production_scenario() -> tuple[float, float, list[dict]]:
    """Wie ``_run_scenario``, aber mit der Produktions-Zusammenstellung
    ``goals_to_liabilities`` (Prioritaets-Scopes je Rang), so wie der Solver
    die Ziele erhaelt."""
    liabilities = goals_to_liabilities(
        [_goal_a_vermoegensziel_hart(), _goal_b_einmalige_ausgabe_opportunistisch()],
        horizon_years=HORIZON_YEARS,
    )
    liability_path = aggregate_liability_path(liabilities, horizon_years=HORIZON_YEARS)
    assert liability_path == [20_00, 0]
    weights = np.array([0.0, 0.0, 0.0, 0.0, 1.0])
    return_paths = np.ones((N_PATHS, HORIZON_YEARS, 5), dtype=np.float64)
    wealth_paths = simulate_wealth_paths(
        initial_wealth_rappen=INITIAL_WEALTH_RAPPEN,
        weights=weights,
        return_paths=return_paths,
        cashflow_series_rappen=[0, 0],
        liability_path_rappen=liability_path,
    )
    # Der gemeinsame Pfad bleibt der Gesamtplan (100 - 20 = 80) ...
    assert np.all(wealth_paths[:, 2] == 80_00)
    penalty, rows = chance_constraint_penalty(
        wealth_paths,
        liabilities,
        initial_value_rappen=INITIAL_WEALTH_RAPPEN,
    )
    goal_a_row = next(row for row in rows if row["goal_id"] == "goal-a-hart")
    return float(goal_a_row["probability"]), float(penalty), rows


def test_bare_per_goal_build_without_priority_scope_shows_the_starved_joint_path(monkeypatch):
    """Positivkontrolle des Mechanismus: OHNE Prioritaets-Scope (einzeln
    gebaute Liabilities, nicht der Produktionspfad) wird Ziel A auf dem
    gemeinsamen Pfad (80 < 90) bewertet -- P=0 und positive Strafe, in
    beiden Modi gleich."""
    penalties = []
    for mode in (None, "hardness"):
        if mode is None:
            monkeypatch.delenv("OPTIMIZER_GOAL_WEIGHTING", raising=False)
        else:
            monkeypatch.setenv("OPTIMIZER_GOAL_WEIGHTING", mode)
        probability, penalty, _rows = _run_scenario()
        assert probability == pytest.approx(0.0)
        assert penalty > 0.0
        penalties.append(penalty)
    assert penalties[0] == pytest.approx(penalties[1])


def test_rank_priority_protects_hard_goal_in_both_weighting_modes(monkeypatch):
    """Owner-Entscheid 9a: das Rang-1-Ziel wird auf dem Pfad bewertet, von
    dem nur Abfluesse mit Rang <= 1 abgezogen sind (100 >= 90). Der
    Gewichtungsmodus aendert daran nichts -- beide Modi liefern dieselbe
    Wahrscheinlichkeit und dieselbe Strafe."""
    monkeypatch.delenv("OPTIMIZER_GOAL_WEIGHTING", raising=False)
    probability_equal, penalty_equal, _ = _run_production_scenario()

    monkeypatch.setenv("OPTIMIZER_GOAL_WEIGHTING", "hardness")
    probability_hardness, penalty_hardness, _ = _run_production_scenario()

    assert probability_equal == pytest.approx(1.0)
    assert probability_hardness == pytest.approx(1.0)
    assert penalty_equal == pytest.approx(penalty_hardness)
    assert penalty_equal == pytest.approx(0.0)
