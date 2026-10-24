"""WISH-GOAL-SOFT-TRADEOFF-001 (CIO-Entscheid, Option B, Engine ``saa_resampled_v15``).

Befund (Reproducer ``test_2026_10_18_objective_normalization_adversarial.py``,
Teil "Lexikographie"): Code, Docstrings und Objective-Vertrag nannten den
Varianzterm "Prioritaet 2" bzw. "Tiebreak" -- als ordne er nur Allokationen,
die auf den Zielen gleichauf liegen. Der Skalar ``L(w) + C(w) + kappa w'Sigma w``
tauscht aber ein Wunschziel gegen Varianz: 1 % Fehlbetrag auf jedem Pfad
(0.0001 + Chance-Strafe) ist billiger als 20 % Volatilitaet (0.04).

CIO-Entscheid: Wunschziele BLEIBEN weiche Terme; die Bezeichnung wird
ehrlich (Policy ``wish_goal_soft_tradeoff_v1``, Vertragsfelder
``risk_term_*`` statt ``tiebreak_*``, ObjectiveContractV4). Harte und
primaere Ziele schuetzt die Stufe-1-Nebenbedingung in jedem Modus
(tests/test_goal_hierarchy_all_objectives.py).

Dieser Test haelt das dokumentierte Verhalten fest: ein Wunschziel DARF gegen
Varianz bzw. Haus-Prior getauscht werden, ein hartes Ziel NICHT. Der
Reproducer-Teil "Lexikographie" ist damit nach CIO-Entscheid ueberholt (seine
Assertion verlangt das Gegenteil des entschiedenen Verhaltens).
"""
from __future__ import annotations

import copy
import json
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import services.optimizer.objective as objective_module  # noqa: E402
import services.optimizer.solver as solver_module  # noqa: E402
from services.optimizer.goal_liabilities import GoalLiability  # noqa: E402
from services.optimizer.objective_contract import (  # noqa: E402
    ObjectiveContractError,
    ObjectiveContractV3,
    ObjectiveContractV4,
    resolve_objective_contract,
    verify_objective_contract_evidence,
)
from test_maximize_goal_and_hardness import (  # noqa: E402
    HOUSE_ANCHOR,
    _goal_context,
    _w,
)

V3_HISTORY = json.loads(
    (BACKEND_ROOT / "tests" / "fixtures" / "objective_contract_v3_history.json")
    .read_text(encoding="utf-8")
)["entries"]


@pytest.fixture(autouse=True)
def _default_modes(monkeypatch):
    monkeypatch.delenv("OPTIMIZER_GOAL_WEIGHTING", raising=False)
    monkeypatch.delenv("OPTIMIZER_OBJECTIVE", raising=False)


def _goal(*, target: int, hardness: str) -> GoalLiability:
    return GoalLiability(
        goal_id="goal", label="Goal", goal_type="Vermögensziel",
        target_kind="wealth_at_t", target_amount_rappen=target,
        target_year_index=1, liability_path_rappen=[], hardness_key=hardness,
        weight_bps=10_000, success_probability_min_x100=8_000,
    )


# ---------------------------------------------------------------------------
# 1. Skalar: Wunschziel gegen Varianz tauschbar (dokumentiertes Verhalten)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("goal_weighting_mode", ["equal", "hardness"])
def test_wish_goal_is_traded_against_variance_in_the_scalar(goal_weighting_mode):
    """Reproducer-Zahlen ("Lexikographie"): A erreicht das Wunschziel auf
    jedem Pfad bei 20 % Volatilitaet, B verfehlt es um 1 % bei Volatilitaet 0.
    Nach ``wish_goal_soft_tradeoff_v1`` gewinnt B -- gewollt."""
    n_paths = 2_000
    goal = _goal(target=100, hardness="opportunistisch")
    reaches = np.column_stack([np.full(n_paths, 100.0), np.full(n_paths, 100.0)])
    misses = np.column_stack([np.full(n_paths, 100.0), np.full(n_paths, 99.0)])
    common = {
        "initial_wealth_rappen": 100, "horizon_years": 1,
        "objective_mode": "goal_shortfall", "goal_weighting_mode": goal_weighting_mode,
    }
    reaches_loss = objective_module.combined_objective_two_phase(
        [goal], reaches, portfolio_variance=0.20**2, **common,
    )
    misses_loss = objective_module.combined_objective_two_phase(
        [goal], misses, portfolio_variance=0.0, **common,
    )
    assert misses_loss < reaches_loss
    # Die Terme stehen in EINER Summe (kein Gleichstandsentscheid).
    goal_level, risk_term = objective_module.two_phase_objective_parts(
        [goal], reaches, portfolio_variance=0.20**2, **common,
    )
    assert risk_term == pytest.approx(objective_module.RISK_TERM_VARIANCE_WEIGHT * 0.04)
    assert reaches_loss == pytest.approx(goal_level + risk_term, rel=1e-15)


def test_wish_goals_are_not_stage_one_hard_goals_are():
    """Stufe 1 umfasst nur harte/primaere Ziele; Wunschziele sind weich."""
    n_cols = 2
    assert not objective_module.is_protected_goal(
        _goal(target=100, hardness="opportunistisch"), n_wealth_columns=n_cols,
    )
    for hardness in ("hart", "primaer"):
        assert objective_module.is_protected_goal(
            _goal(target=100, hardness=hardness), n_wealth_columns=n_cols,
        )


# ---------------------------------------------------------------------------
# 2. Solver: dasselbe Ziel, nur der Haertegrad verschieden
# ---------------------------------------------------------------------------


def _strong_prior_selection(hardness: str):
    """Absichtlich extremer Haus-Prior (kappa = 1e6): ohne Schutz waere das
    Ergebnis praktisch die Hausquote, auf Kosten des Ziels."""
    context = _goal_context(hardness)
    strong = replace(context, house_prior_weights=_w(HOUSE_ANCHOR), house_prior_kappa=1e6)
    selection = solver_module._select_cube_candidate(strong, max_iter=50, ftol=1e-6)
    return strong, selection


def _goal_level(context, w) -> float:
    """Zielebene des EINEN Ziels (Fehlbetrag + Chance-Strafe), unabhaengig
    vom Haertegrad mit Gewicht 1 nachgerechnet (Mass fuer die Erosion)."""
    _f, wealth, annualized, scope = solver_module._evaluation_inputs(context, w)
    goal = replace(context.liabilities[0], hardness_key="primaer")
    return objective_module.protected_goal_level(
        [goal], wealth,
        initial_wealth_rappen=context.advisory_wealth_rappen,
        horizon_years=context.horizon_years,
        weights=context.scenario_weights,
        annualized_return_bps_per_path=annualized,
        goal_weighting_mode="equal",
        scope_wealth=scope,
    )[0]


def test_wish_goal_may_be_traded_against_the_prior_hard_goal_may_not():
    hard_context, hard = _strong_prior_selection("Hart")
    wish_context, wish = _strong_prior_selection("Opportunistisch")

    # Hart: Stufe-1-Schranke gehalten.
    audit = hard.goal_protection
    assert audit is not None
    assert audit["final_level"] <= audit["bound"] * (1.0 + 1e-9)

    # Wunsch: keine Schranke; der Prior zieht auf die Hausquote ...
    assert wish.goal_protection is None
    house = _w(HOUSE_ANCHOR)
    assert np.max(np.abs(wish.weights - house)) < 5e-3
    # ... und das Ziel erodiert dabei messbar gegenueber der Allokation, die
    # derselbe Lauf fuer das harte Ziel findet (gleiche Szenarien, gleiches
    # Ziel, nur der Haertegrad verschieden).
    assert _goal_level(wish_context, wish.weights) > _goal_level(wish_context, hard.weights)


# ---------------------------------------------------------------------------
# 3. Objective-Vertrag V4
# ---------------------------------------------------------------------------


def test_runs_resolve_contract_v4_with_wish_goal_policy():
    contract = resolve_objective_contract()
    assert type(contract) is ObjectiveContractV4
    evidence = contract.as_evidence()
    assert evidence["objective_contract_version"] == "objective-contract-v4"
    assert evidence["wish_goal_policy"] == "wish_goal_soft_tradeoff_v1"
    assert evidence["risk_term_policy"] == "portfolio_variance_one_year_v1"
    assert evidence["risk_term_weight"] == objective_module.RISK_TERM_VARIANCE_WEIGHT
    assert evidence["goal_hierarchy_scope"] == "all_objectives"
    assert not any("tiebreak" in key for key in evidence)
    assert len(evidence) == 29
    result = verify_objective_contract_evidence(evidence)
    assert (result["status"], result["schema"]) == ("verified", "v4_policy_25")


def test_v4_hash_differs_from_the_last_v3_and_v3_still_replays():
    develop_v3 = V3_HISTORY[0]["evidence"]
    result = verify_objective_contract_evidence(copy.deepcopy(develop_v3))
    assert (result["status"], result["schema"]) == ("verified", "v3_policy_24")
    assert develop_v3["goal_hierarchy_scope"] == "goal_shortfall_mode_only"
    current = resolve_objective_contract()
    assert current.contract_hash != develop_v3["objective_contract_hash"]


def test_v4_rejects_the_old_tiebreak_fields():
    with pytest.raises(ObjectiveContractError):
        ObjectiveContractV4(
            objective_mode="goal_shortfall", goal_weighting_mode="hardness",
            tiebreak_policy="portfolio_variance_one_year_v1",
        )
    with pytest.raises(ObjectiveContractError):
        ObjectiveContractV3(
            objective_mode="goal_shortfall", goal_weighting_mode="hardness",
            wish_goal_policy="wish_goal_soft_tradeoff_v1",
        )
    with pytest.raises(ObjectiveContractError):
        ObjectiveContractV4(
            objective_mode="goal_shortfall", goal_weighting_mode="hardness",
            wish_goal_policy="lexicographic_wish_before_variance",
        )


def test_module_documentation_names_the_policy_not_a_priority_two():
    doc = objective_module.__doc__ or ""
    assert "wish_goal_soft_tradeoff_v1" in doc
    assert "Priorität 2" not in doc and "Prioritaet 2" not in doc
    for function in (
        objective_module.combined_objective_two_phase,
        objective_module.two_phase_objective_parts,
    ):
        assert "Tiebreak" not in (function.__doc__ or "")
