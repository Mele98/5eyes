"""GOAL-ATTRIBUTION-CASHFLOW-INVERSION-001, GOAL-OPTIMIZATION-PUBLICATION-
SCOPE-SPLIT-001, GOAL-FAILURE-EVENT-MODE-COLLAPSE-001 (Engine v10).

Uebernommen aus dem Codex-Audit-Reproducer
``docs/audits/reproducers/test_2026_10_18_goal_attribution_priority_adversarial.py``
(Branch ``codex/asset-allocation-stochastic-core``) -- als regulaere Tests,
ohne xfail. Zahlen und Asserts sind unveraendert. Angepasst ist einzig die
EINGABE: der alte Vertrag bekam nur den aggregierten gemeinsamen Pfad und
konnte den Scope nur rueckwaerts rekonstruieren. Codex fordert ausdruecklich
"niemals nur einen aggregierten Wealth-Pfad", sondern den eingefrorenen
Simulationskontext; die Tests uebergeben ihn daher als ``replay`` /
``scope_wealth`` (``services.optimizer.priority_scope``).
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

from services.optimizer.priority_scope import (  # noqa: E402
    PriorityScopeUnavailableError,
    PriorityScopeWealth,
    ScopeReplayInputs,
)
from services.optimizer.scenario_engine import N_BUCKETS  # noqa: E402


def _wealth_goal_with_scopes(*, n_paths: int):
    from services.optimizer.goal_liabilities import GoalLiability

    return GoalLiability(
        goal_id="protected-wealth",
        label="Protected wealth",
        goal_type="Vermögensziel",
        target_kind="wealth_at_t",
        target_amount_rappen=300,
        target_year_index=2,
        liability_path_rappen=[0, 0],
        hardness_key="hart",
        rank=1,
        priority_scope_liability_path_rappen=[0, 0],
        joint_liability_path_rappen=[80, 0],
        success_probability_min_x100=5_000,
    )


def _replay_inputs(*, n_paths: int = 400) -> ScopeReplayInputs:
    return ScopeReplayInputs(
        initial_wealth_rappen=100,
        weights=np.full(N_BUCKETS, 1.0 / N_BUCKETS),
        return_paths=np.ones((n_paths, 2, N_BUCKETS)),
        cashflow_series_rappen=(0, 100),
        joint_liability_path_rappen=(80, 0),
    )


def _cashflow_replay(*, n_paths: int = 400):
    from services.optimizer.scenario_engine import simulate_wealth_paths

    weights = np.full(N_BUCKETS, 1.0 / N_BUCKETS)
    returns = np.ones((n_paths, 2, N_BUCKETS))
    common = {
        "initial_wealth_rappen": 100,
        "weights": weights,
        "return_paths": returns,
        "cashflow_series_rappen": [0, 100],
    }
    joint = simulate_wealth_paths(**common, liability_path_rappen=[80, 0])
    protected = simulate_wealth_paths(**common, liability_path_rappen=[0, 0])
    return joint, protected


def test_priority_path_reconstruction_must_equal_direct_common_random_number_replay():
    """Cashflows are additive and must never be reverse-engineered as returns.

    Joint replay:      100 -> 20 -> 120
    protected replay:  100 -> 100 -> 200   (v8 reconstruction: 600)
    """
    from services.optimizer.objective import _priority_protected_wealth_paths

    joint, expected = _cashflow_replay()
    np.testing.assert_allclose(joint[0], [100.0, 20.0, 120.0])
    np.testing.assert_allclose(expected[0], [100.0, 100.0, 200.0])
    reconstructed, was_reconstructed = _priority_protected_wealth_paths(
        joint,
        _wealth_goal_with_scopes(n_paths=joint.shape[0]),
        replay=_replay_inputs(n_paths=joint.shape[0]),
    )

    assert was_reconstructed is True
    np.testing.assert_allclose(reconstructed, expected, rtol=0.0, atol=1e-12)


def test_priority_publication_must_use_replay_exact_wealth():
    """The reconstruction error must not flip customer goal achievability."""
    from services.optimizer.goal_attribution import publish_goal_achievability
    from services.optimizer.objective import _goal_probability_core

    joint, expected = _cashflow_replay()
    goal = _wealth_goal_with_scopes(n_paths=joint.shape[0])
    correct_probability = float(np.mean(_goal_probability_core(expected, goal, 100)))
    published = publish_goal_achievability(
        joint, [goal], 100,
        scope_wealth=PriorityScopeWealth(
            joint=joint, liabilities=[goal], replay=_replay_inputs(),
        ),
    )
    goal_row = next(row for row in published if row.get("goal_id") == goal.goal_id)

    assert correct_probability == 0.0
    assert goal_row["probability"] == correct_probability
    assert goal_row["status"] == "nicht_erreichbar"


def test_priority_publication_without_replay_context_fails_closed():
    """Kein Replay-Kontext -> keine Zahl (statt Rueckwaertsrekonstruktion)."""
    from services.optimizer.goal_attribution import publish_goal_achievability

    joint, _expected = _cashflow_replay()
    goal = _wealth_goal_with_scopes(n_paths=joint.shape[0])
    with pytest.raises(PriorityScopeUnavailableError):
        publish_goal_achievability(joint, [goal], 100)


def test_priority_publication_rejects_joint_path_from_another_context():
    """Der gemeinsame Pfad ist an den Replay-Kontext gebunden."""
    from services.optimizer.goal_attribution import publish_goal_achievability

    joint, _expected = _cashflow_replay()
    goal = _wealth_goal_with_scopes(n_paths=joint.shape[0])
    tampered = joint.copy()
    tampered[:, 2] += 1.0
    with pytest.raises(PriorityScopeUnavailableError):
        publish_goal_achievability(
            tampered, [goal], 100,
            scope_wealth=PriorityScopeWealth(
                joint=tampered, liabilities=[goal], replay=_replay_inputs(),
            ),
        )


def _goal(*, goal_id: str, amount: int, rank: int, hardness: str):
    return SimpleNamespace(
        id=goal_id,
        label=goal_id,
        goal_type="Einmalige_Ausgabe",
        target_amount_rappen=amount,
        target_wealth_rappen=None,
        target_return_bps=None,
        horizon_years=1,
        target_date=None,
        start_date=None,
        is_ongoing=0,
        frequency=None,
        hardness=hardness,
        rank=rank,
        weight_bps=None,
        value_mode="nominal",
        goal_scope="Beratungsvermögen",
        pension_pillar=None,
    )


def test_lower_priority_goal_must_not_trigger_higher_priority_goal_constraint():
    """Per-goal optimization and publication must share funding semantics.

    CHF 100 fully funds the rank-1 CHF 90 goal, but not that goal plus the
    rank-2 CHF 20 goal. The joint path ends at CHF -10. Publication AND the
    per-goal chance-penalty row must both say rank 1 succeeds.
    """
    from services.optimizer.goal_attribution import publish_goal_achievability
    from services.optimizer.goal_liabilities import goals_to_liabilities
    from services.optimizer.objective import chance_constraint_penalty

    liabilities = goals_to_liabilities(
        [
            _goal(goal_id="hard-90", amount=90, rank=1, hardness="Hart"),
            _goal(goal_id="opp-20", amount=20, rank=2, hardness="Opportunistisch"),
        ],
        horizon_years=1,
    )
    joint_wealth = np.tile(np.array([[100.0, -10.0]]), (400, 1))
    replay = ScopeReplayInputs(
        initial_wealth_rappen=100,
        weights=np.full(N_BUCKETS, 1.0 / N_BUCKETS),
        return_paths=np.ones((400, 1, N_BUCKETS)),
        cashflow_series_rappen=(0,),
        joint_liability_path_rappen=(110,),
    )
    scopes = PriorityScopeWealth(joint=joint_wealth, liabilities=liabilities, replay=replay)
    published = publish_goal_achievability(
        joint_wealth, liabilities, 100, scope_wealth=scopes,
    )
    _penalty, internal = chance_constraint_penalty(
        joint_wealth, liabilities, 100, scope_wealth=scopes,
    )
    public_hard = next(row for row in published if row.get("goal_id") == "hard-90")
    internal_hard = next(row for row in internal if row.get("goal_id") == "hard-90")

    assert public_hard["probability"] == 1.0
    assert internal_hard["probability"] == public_hard["probability"]
    # Ein Replay je eindeutigem abweichendem Rang (Rang 2 = gemeinsamer Pfad).
    assert scopes.replay_count == 1


def test_dominant_shared_event_must_not_erase_material_independent_failures():
    """A 60% common event does not make the other 40% cease to exist."""
    from services.risk_matrix import classify_limiting_factor

    rows = [
        {
            "goal_id": "a",
            "status": "nicht_erreichbar",
            "hardness": "hart",
            "evaluation_scope": "priority_funded",
            "failure_event_id": "liquiditaetsengpass-jahr-1",
            "failure_event_share": 0.6,
        },
        {
            "goal_id": "b",
            "status": "nicht_erreichbar",
            "hardness": "primaer",
            "evaluation_scope": "priority_funded",
            "failure_event_id": "liquiditaetsengpass-jahr-1",
            "failure_event_share": 0.6,
        },
    ]
    verdict = classify_limiting_factor(
        allocation_bps={"liquidity": 1000},
        risky_fraction=5000,
        max_risky_fraction=6000,
        min_liquidity_bps=500,
        bands={},
        achievability=rows,
        optimization_status="converged",
    )

    assert verdict == "zielkonflikt"


# ---------------------------------------------------------------------------
# Zusaetzliche Pflichtregressionen (Codex-Review Abschnitt 8)
# ---------------------------------------------------------------------------


def test_full_mass_shared_event_is_one_bottleneck_and_distribution_is_persisted():
    """100 % gemeinsames Ereignis -> gemeinsamer_engpass; Verteilung je Zeile."""
    from services.allocation_messages import _single_shared_failure_event
    from services.risk_matrix import classify_limiting_factor

    rows = [
        {
            "goal_id": goal_id, "status": "nicht_erreichbar", "hardness": "hart",
            "evaluation_scope": "priority_funded",
            "failure_event_id": "liquiditaetsengpass-jahr-1",
            "failure_event_share": 1.0,
            "failure_event_distribution": [
                {"event_id": "liquiditaetsengpass-jahr-1", "weighted_mass": 7.0, "share": 1.0},
            ],
        }
        for goal_id in ("a", "b")
    ]
    verdict = classify_limiting_factor(
        allocation_bps={"liquidity": 1000}, risky_fraction=5000,
        max_risky_fraction=6000, min_liquidity_bps=500, bands={},
        achievability=rows, optimization_status="converged",
    )
    assert verdict == "gemeinsamer_engpass"
    assert _single_shared_failure_event(rows) == "liquiditaetsengpass-jahr-1"
    mixed = [dict(rows[0]), dict(rows[1])]
    mixed[1]["failure_event_distribution"] = [
        {"event_id": "liquiditaetsengpass-jahr-1", "weighted_mass": 6.0, "share": 0.6},
        {"event_id": "zielschwelle-b", "weighted_mass": 4.0, "share": 0.4},
    ]
    assert _single_shared_failure_event(mixed) is None


def test_publication_persists_full_cause_distribution_deterministically():
    """60 % Liquiditaetsengpass Jahr 1, 40 % eigene Zielschwelle."""
    from services.optimizer.goal_attribution import publish_goal_achievability
    from services.optimizer.goal_liabilities import GoalLiability

    goal = GoalLiability(
        goal_id="w", label="w", goal_type="Vermögensziel",
        target_kind="wealth_at_t", target_amount_rappen=150,
        target_year_index=2, liability_path_rappen=[0, 0], hardness_key="hart",
    )
    # 6 Pfade negativ in Jahr 1, 4 Pfade positiv aber unter 150, 10 erreicht.
    wealth = np.vstack([
        np.tile([100.0, -5.0, -5.0], (6, 1)),
        np.tile([100.0, 50.0, 100.0], (4, 1)),
        np.tile([100.0, 120.0, 200.0], (10, 1)),
    ])
    row = publish_goal_achievability(wealth, [goal], 100)[0]
    assert row["failure_event_distribution"] == [
        {"event_id": "liquiditaetsengpass-jahr-1", "weighted_mass": 6.0, "share": 0.6},
        {"event_id": "zielschwelle-w", "weighted_mass": 4.0, "share": 0.4},
    ]
    assert row["failure_event_id"] == "liquiditaetsengpass-jahr-1"
    assert row["failure_event_share"] == 0.6


def _replay_case(*, death_index=None, tax_regime=None, tax_free_negative=False):
    from services.optimizer.goal_liabilities import goals_to_liabilities

    rng = np.random.default_rng(7)
    n_paths, horizon = 64, 4
    returns = 1.0 + rng.normal(0.03, 0.15, size=(n_paths, horizon, N_BUCKETS))
    goals = [
        _goal(goal_id="r1", amount=40, rank=1, hardness="Hart"),
        _goal(goal_id="r2", amount=70, rank=2, hardness="Primär"),
        _goal(goal_id="r3", amount=90, rank=3, hardness="Opportunistisch"),
    ]
    for index, goal in enumerate(goals):
        goal.horizon_years = index + 1
    liabilities = goals_to_liabilities(goals, horizon_years=horizon)
    joint_path = [sum(l.liability_path_rappen[t] for l in liabilities) for t in range(horizon)]
    replay = ScopeReplayInputs(
        initial_wealth_rappen=100,
        weights=np.full(N_BUCKETS, 1.0 / N_BUCKETS),
        return_paths=returns,
        cashflow_series_rappen=(-30, 50, -20, 60) if not tax_free_negative else (-300, 400, -20, 60),
        joint_liability_path_rappen=tuple(joint_path),
        death_year_index_per_path=death_index,
        tax_regime=tax_regime,
    )
    return liabilities, replay, joint_path


@pytest.mark.parametrize("variant", ["plain", "mortality", "negative_then_positive", "tax"])
def test_every_unique_rank_is_replayed_exactly_like_a_direct_simulation(variant):
    """Replay-Paritaet gegen direkte ``simulate_wealth_paths``-Aufrufe.

    Cashflows vor/nach der Scope-Divergenz, negatives Vermoegen (W2.5),
    pfadweise Todesmaske und pfadabhaengige Vermoegenssteuer.
    """
    from services.optimizer.scenario_engine import simulate_wealth_paths

    death = None
    tax = None
    if variant == "mortality":
        death = np.array([1, 2, 3, 4] * 16, dtype=np.int32)
    if variant == "tax":
        from services.tax.regimes.generic import GenericFlatRateRegime

        tax = GenericFlatRateRegime(wealth_tax_bps_pa=80.0, dividend_tax_bps=3000.0)
    liabilities, replay, joint_path = _replay_case(
        death_index=death, tax_regime=tax,
        tax_free_negative=variant == "negative_then_positive",
    )
    joint = replay.simulate(joint_path)
    scopes = PriorityScopeWealth(joint=joint, liabilities=liabilities, replay=replay)
    for liab in liabilities:
        direct = simulate_wealth_paths(
            initial_wealth_rappen=100,
            weights=replay.weights,
            return_paths=replay.return_paths,
            cashflow_series_rappen=list(replay.cashflow_series_rappen),
            liability_path_rappen=liab.priority_scope_liability_path_rappen,
            death_year_index_per_path=death,
            tax_regime=tax,
        )
        np.testing.assert_array_equal(scopes.for_goal(liab), direct)
    # Drei Raenge, der hoechste ist der gemeinsame Pfad: genau zwei Replays.
    assert scopes.replay_count == 2
    if variant == "negative_then_positive":
        assert (joint < 0).any()


def test_equal_rank_goals_share_exactly_one_scope_replay():
    from services.optimizer.goal_liabilities import goals_to_liabilities

    goals = [
        _goal(goal_id="a", amount=30, rank=1, hardness="Hart"),
        _goal(goal_id="b", amount=30, rank=1, hardness="Primär"),
        _goal(goal_id="c", amount=30, rank=2, hardness="Opportunistisch"),
    ]
    liabilities = goals_to_liabilities(goals, horizon_years=1)
    replay = ScopeReplayInputs(
        initial_wealth_rappen=100,
        weights=np.full(N_BUCKETS, 1.0 / N_BUCKETS),
        return_paths=np.ones((8, 1, N_BUCKETS)),
        cashflow_series_rappen=(0,),
        joint_liability_path_rappen=(90,),
    )
    scopes = PriorityScopeWealth(
        joint=replay.simulate([90]), liabilities=liabilities, replay=replay,
    )
    a, b = scopes.for_goal(liabilities[0]), scopes.for_goal(liabilities[1])
    assert a is b
    np.testing.assert_allclose(a[0], [100.0, 40.0])
    assert scopes.replay_count == 1


def test_out_of_scope_reserve_release_leaves_with_its_goal():
    """Die Reserve-Freigabe eines Rang-2-Ziels gehoert nicht in den Rang-1-Scope.

    Start 100, Rang-2-Abfluss 50 in Jahr 1, davon 30 aus der externen Reserve
    freigegeben (Cashflow +30). Rang-1-Scope: weder Abfluss noch Freigabe ->
    100; nicht 130.
    """
    from services.optimizer.goal_liabilities import goals_to_liabilities

    goals = [
        _goal(goal_id="r1", amount=10, rank=1, hardness="Hart"),
        _goal(goal_id="r2", amount=50, rank=2, hardness="Primär"),
    ]
    goals[0].horizon_years = 2
    liabilities = goals_to_liabilities(goals, horizon_years=2)
    replay = ScopeReplayInputs(
        initial_wealth_rappen=100,
        weights=np.full(N_BUCKETS, 1.0 / N_BUCKETS),
        return_paths=np.ones((4, 2, N_BUCKETS)),
        cashflow_series_rappen=(30, 0),
        joint_liability_path_rappen=(50, 10),
        goal_reserve_release_series_rappen=(("r2", (30, 0)),),
    )
    scopes = PriorityScopeWealth(
        joint=replay.simulate([50, 10]), liabilities=liabilities, replay=replay,
    )
    np.testing.assert_allclose(scopes.joint[0], [100.0, 80.0, 70.0])
    np.testing.assert_allclose(scopes.for_goal(liabilities[0])[0], [100.0, 100.0, 90.0])


def test_goal_release_series_from_ledger_groups_goal_tranches_only():
    from services.optimizer.priority_scope import goal_release_series_from_ledger
    from services.reserve_funding_ledger import ReserveRelease

    ledger = SimpleNamespace(releases=(
        ReserveRelease(0, "goal:b", "goal", "b", 5),
        ReserveRelease(2, "goal:a", "goal", "a", 7),
        ReserveRelease(0, "cashflow_deficit:near_term", "cashflow_deficit", "near_term", 9),
        ReserveRelease(2, "goal:a", "goal", "a", 1),
    ))
    assert goal_release_series_from_ledger(ledger, 3) == (
        ("a", (0, 0, 8)),
        ("b", (5, 0, 0)),
    )


def test_objective_contract_binds_the_priority_scope_policy():
    """ObjectiveContractV2 nennt den Scope der Zielterme (Codex Pflicht 14)."""
    from services.optimizer.objective_contract import resolve_objective_contract
    from services.optimizer.priority_scope import PRIORITY_SCOPE_POLICY_VERSION
    from services.optimizer.solver import OPTIMIZER_ENGINE_VERSION

    evidence = resolve_objective_contract().as_evidence()
    assert evidence["goal_evaluation_scope"] == "priority_funded"
    assert evidence["goal_scope_replay_policy"] == PRIORITY_SCOPE_POLICY_VERSION
    assert OPTIMIZER_ENGINE_VERSION == "saa_resampled_v10"
