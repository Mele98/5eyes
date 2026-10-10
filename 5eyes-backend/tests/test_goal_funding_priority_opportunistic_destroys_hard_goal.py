"""Red test fuer GOAL-FUNDING-PRIORITY-001 (Kontrollrunde 37 Audit).

Audit: docs/audits/2026-09-28-goal-funding-priority-and-achievability-attribution-audit.md

Befund: der Optimizer hat keinen Goal-Funding-Priority-Mechanismus. Jeder
Goal-Liability-Pfad wird in `aggregate_liability_path()`
(services/optimizer/goal_liabilities.py) kommutativ in EINEN gemeinsamen
Outflow-Pfad summiert -- unabhaengig von Rank/Haertegrad. Dieser gemeinsame
Pfad wird in `simulate_wealth_paths()` (services/optimizer/scenario_engine.py)
unconditional vom Wealth abgezogen, BEVOR irgendein einzelnes Goal bewertet
wird (`goal_probability_per_path()` / `chance_constraint_penalty()` in
services/optimizer/objective.py). Dadurch kann ein opportunistisches
(niedrigste Prioritaet) Einmal-Ausgabe-Goal die Erreichbarkeit eines harten
Goals von 100% auf 0% drehen und dessen volle Chance-Constraint-Penalty
ausloesen -- obwohl das harte Goal strikt vorrangig finanziert werden sollte.

Deterministischer Repro (aus dem Audit, hier mit den production-Funktionen
nachgebaut und lokal verifiziert -- siehe Kommentare fuer die exakt
gemessenen Werte):

    initial wealth = 100, Return-Faktor = 1.0 (kein Wachstum), horizon = 2 Jahre
    Goal A: Vermoegensziel, hardness=Hart, rank=1, target=90, faellig Jahr 2
    Goal B: Einmalige_Ausgabe, hardness=Opportunistisch, rank=5, amount=20,
            faellig Jahr 1

    Ohne Goal B: wealth-Pfad = [100, 100, 100] -> Goal A Probability = 1.0
    Mit Goal B:  wealth-Pfad = [100,  80,  80] -> Goal A Probability = 0.0
                 Goal B Probability = 1.0 (die opportunistische Ausgabe wird
                 voll bedient, WAEHREND das harte Goal komplett ausfaellt)
                 Chance-Constraint-Penalty fuer Goal A = 640'000.0
                 (lambda=1e6, tau=0.8, shortfall=tau-prob=0.8 -> 1e6*0.8^2)

Verifiziert: das Ergebnis ist IDENTISCH mit und ohne
OPTIMIZER_GOAL_WEIGHTING=hardness -- der Opt-in-Haertegrad-Modus skaliert nur
den bereits gemeinsamen Shortfall in der primaeren Zielfunktion
(_effective_hardness_weight in objective.py), er wird in
goal_probability_per_path()/chance_constraint_penalty() gar nicht
referenziert. Er behebt also nicht, dass Goal B's Outflow ueberhaupt erst in
den gemeinsamen Wealth-Pfad gelangt, bevor Goal A bewertet wird.

Call-Path, der hier direkt gegen Production-Code getestet wird:
    goals_to_liabilities()      (services/optimizer/goal_liabilities.py)
    aggregate_liability_path()  (services/optimizer/goal_liabilities.py)
    simulate_wealth_paths()     (services/optimizer/scenario_engine.py)
    goal_probability_per_path() (services/optimizer/objective.py)
    chance_constraint_penalty() (services/optimizer/objective.py)
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
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)

configure_mappers()

from services.optimizer.goal_liabilities import (
    aggregate_liability_path,
    goals_to_liabilities,
)
from services.optimizer.objective import (
    chance_constraint_penalty,
    goal_probability_per_path,
)
from services.optimizer.scenario_engine import N_BUCKETS, simulate_wealth_paths


# ============================================================================
# Mock-Goal-Konstruktion (gleiches Pattern wie tests/test_optimizer_goal_liabilities.py)
# ============================================================================


def _make_goal(
    *,
    goal_id: str,
    label: str,
    goal_type: str,
    hardness: str,
    rank: int,
    target_wealth_rappen: int | None = None,
    target_amount_rappen: int | None = None,
    horizon_years: int | None = None,
) -> SimpleNamespace:
    """Mock-Goal als SimpleNamespace (kein DB-Objekt noetig).

    horizon_years wird hier direkt als Zieljahr-Anker genutzt (kein
    target_date/start_date gesetzt), konsistent zu
    services.optimizer.goal_liabilities._resolve_target_year_index: ohne
    target_date faellt die Funktion auf `goal.horizon_years` zurueck.
    """
    return SimpleNamespace(
        id=goal_id,
        label=label,
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


HORIZON_YEARS = 2
INITIAL_WEALTH_RAPPEN = 100


def _hard_wealth_goal() -> SimpleNamespace:
    """Goal A: hartes Vermoegensziel, rank=1, target=90, faellig Jahr 2."""
    return _make_goal(
        goal_id="goal-a-hart",
        label="Vermoegensziel Hart",
        goal_type="Vermoegensziel",
        hardness="Hart",
        rank=1,
        target_wealth_rappen=90,
        horizon_years=HORIZON_YEARS,
    )


def _opportunistic_one_off_expense() -> SimpleNamespace:
    """Goal B: opportunistische Einmal-Ausgabe, rank=5, amount=20, faellig Jahr 1."""
    return _make_goal(
        goal_id="goal-b-opportunistisch",
        label="Einmalige Ausgabe Opportunistisch",
        goal_type="Einmalige_Ausgabe",
        hardness="Opportunistisch",
        rank=5,
        target_amount_rappen=20,
        horizon_years=1,
    )


#: OPTIMIZER-POST-SELECTION-CERTIFICATION-001 (2026-10-10): dieser Test
#: simulierte EINEN deterministischen Pfad. Die Zertifizierung ist seither
#: schaetzer-bewusst (untere Wilson-Konfidenzgrenze, ESS-Schwelle), und ein
#: einzelner Pfad ist dafuer keine verwertbare Stichprobe -- selbst ein
#: strukturelles p=1.0 ergibt dort eine Untergrenze von nur ~0.27.
#:
#: Der Pfad wird deshalb auf eine aussagefaehige Stichprobe vervielfacht.
#: Weil ALLE Pfade identisch sind, bleibt die Wahrscheinlichkeit exakt 0.0
#: bzw. 1.0 -- die Aussage des Tests (Prioritaetsschutz) ist unveraendert,
#: nur die Stichprobengroesse passt jetzt zur Zertifizierungsregel. Die im
#: Audit dokumentierten Strafwerte gelten damit wieder exakt.
DETERMINISTIC_PATH_REPLICAS = 2000


def _simulate_wealth(liability_path_rappen: list[int]) -> np.ndarray:
    """Simuliert einen deterministischen Pfad mit Return-Faktor 1.0 (kein
    Wachstum), vervielfacht auf DETERMINISTIC_PATH_REPLICAS identische Pfade.

    weights/return_paths sind hier irrelevant fuer den Wert (jeder Bucket hat
    Faktor 1.0), nur die Shapes muessen zur production API passen.
    """
    weights = np.full(N_BUCKETS, 1.0 / N_BUCKETS, dtype=np.float64)
    return_paths = np.ones(
        (DETERMINISTIC_PATH_REPLICAS, HORIZON_YEARS, N_BUCKETS), dtype=np.float64,
    )
    cashflow_series_rappen = [0] * HORIZON_YEARS
    return simulate_wealth_paths(
        initial_wealth_rappen=INITIAL_WEALTH_RAPPEN,
        weights=weights,
        return_paths=return_paths,
        cashflow_series_rappen=cashflow_series_rappen,
        liability_path_rappen=liability_path_rappen,
    )


def test_opportunistic_one_off_expense_destroys_hard_goal_achievability(monkeypatch):
    """Documents GOAL-FUNDING-PRIORITY-001: adding a lowest-rank opportunistic
    one-off expense (Goal B) must NOT be able to drag a rank-1 HARD goal's
    (Goal A) achievability from 100% down to 0%. Today it does, because
    aggregate_liability_path() sums every goal's outflow into one shared
    wealth path with no regard for rank/hardness, and that shared path is
    what every goal (hard or not) is evaluated against.

    Verified to reproduce identically whether or not
    OPTIMIZER_GOAL_WEIGHTING=hardness is set -- that opt-in mode only
    rescales the shortfall inside the primary SLSQP objective
    (_effective_hardness_weight in objective.py); it is never consulted by
    goal_probability_per_path() or chance_constraint_penalty(), so it cannot
    reorder funding priority.
    """
    monkeypatch.setenv("OPTIMIZER_GOAL_WEIGHTING", "hardness")

    goal_a = _hard_wealth_goal()
    goal_b = _opportunistic_one_off_expense()

    # --- Baseline: Goal A alone is fully achievable. ---
    liabilities_without_b = goals_to_liabilities([goal_a], horizon_years=HORIZON_YEARS)
    agg_without_b = aggregate_liability_path(liabilities_without_b, HORIZON_YEARS)
    assert agg_without_b == [0, 0]

    wealth_without_b = _simulate_wealth(agg_without_b)
    # np.unique prueft zusaetzlich, dass alle vervielfachten Pfade wirklich
    # identisch sind (siehe DETERMINISTIC_PATH_REPLICAS).
    np.testing.assert_allclose(np.unique(wealth_without_b, axis=0), [[100.0, 100.0, 100.0]])

    prob_a_without_b = float(
        goal_probability_per_path(
            wealth_without_b, liabilities_without_b[0], initial_value_rappen=INITIAL_WEALTH_RAPPEN
        ).mean()
    )
    assert prob_a_without_b == pytest.approx(1.0)

    # --- Adding the opportunistic Goal B shares the SAME aggregated wealth path. ---
    liabilities_with_b = goals_to_liabilities([goal_a, goal_b], horizon_years=HORIZON_YEARS)
    agg_with_b = aggregate_liability_path(liabilities_with_b, HORIZON_YEARS)
    assert agg_with_b == [20, 0]  # Goal B's outflow enters the SHARED path unconditionally

    wealth_with_b = _simulate_wealth(agg_with_b)
    np.testing.assert_allclose(np.unique(wealth_with_b, axis=0), [[100.0, 80.0, 80.0]])

    goal_a_liability_with_b = liabilities_with_b[0]
    goal_b_liability_with_b = liabilities_with_b[1]

    prob_a_with_b = float(
        goal_probability_per_path(
            wealth_with_b, goal_a_liability_with_b, initial_value_rappen=INITIAL_WEALTH_RAPPEN
        ).mean()
    )
    prob_b_with_b = float(
        goal_probability_per_path(
            wealth_with_b, goal_b_liability_with_b, initial_value_rappen=INITIAL_WEALTH_RAPPEN
        ).mean()
    )

    # The opportunistic, rank-5 Goal B is fully funded...
    assert prob_b_with_b == pytest.approx(1.0)

    # ...while the hard, rank-1 Goal A's achievability collapsed from 100% to 0%,
    # purely because it shares an unprioritized aggregated wealth path with a
    # lower-priority goal. Verified penalty matches the audit's documented
    # value exactly: lambda_chance(1e6) * (tau(0.8) - probability(0.0))^2.
    penalty, rows = chance_constraint_penalty(
        wealth_with_b, liabilities_with_b, initial_value_rappen=INITIAL_WEALTH_RAPPEN
    )
    assert penalty == pytest.approx(640_000.0)
    assert rows[0]["goal_id"] == "goal-a-hart"
    assert rows[0]["status"] == "nicht_erreichbar"

    # This is the actual bug assertion: a lower-priority goal must never be
    # able to make a hard goal's achievability WORSE than it was without it.
    # Today it goes from 1.0 straight to 0.0 -- this fails, documenting
    # GOAL-FUNDING-PRIORITY-001.
    assert prob_a_with_b >= prob_a_without_b


def test_positive_control_hard_goal_alone_is_fully_achievable():
    """Harness/control: WITHOUT the competing opportunistic Goal B, the hard
    Goal A (same construction as above) is fully achievable (probability
    1.0, status 'erreichbar'). This proves the production call path
    (goals_to_liabilities -> aggregate_liability_path -> simulate_wealth_paths
    -> goal_probability_per_path / chance_constraint_penalty) and the test
    harness work correctly on their own -- the failure in
    test_opportunistic_one_off_expense_destroys_hard_goal_achievability is
    not a setup artifact.
    """
    goal_a = _hard_wealth_goal()

    liabilities = goals_to_liabilities([goal_a], horizon_years=HORIZON_YEARS)
    aggregated = aggregate_liability_path(liabilities, HORIZON_YEARS)
    assert aggregated == [0, 0]

    wealth_paths = _simulate_wealth(aggregated)
    np.testing.assert_allclose(np.unique(wealth_paths, axis=0), [[100.0, 100.0, 100.0]])

    probability = float(
        goal_probability_per_path(
            wealth_paths, liabilities[0], initial_value_rappen=INITIAL_WEALTH_RAPPEN
        ).mean()
    )
    assert probability == pytest.approx(1.0)

    penalty, rows = chance_constraint_penalty(
        wealth_paths, liabilities, initial_value_rappen=INITIAL_WEALTH_RAPPEN
    )
    assert penalty == pytest.approx(0.0)
    assert rows[0]["status"] == "erreichbar"
