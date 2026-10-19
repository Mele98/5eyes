"""GOAL-REACHABILITY-CERTIFICATE-001 (CIO-Entscheid 2026-10-19, Codex-Befund
zu PR #650: docs/audits/2026-10-19-maximize-goal-hardness-pr650-current-
review.md, Abschnitt 4).

Befund: ein endlicher Screen-Miss (``not_found_reachable_in_screen_set``)
stufte ein hartes Ziel aus Stufe 1 herab, obwohl eine zulaessige 50/50-
Innenallokation es auf allen 200 Pfaden erfuellt.

Entscheid: die Herabstufung (Wunschziel-Gewicht 0.2 + W0-Deckel) bleibt als
Mechanismus, greift aber NUR bei ZERTIFIZIERTER Unerreichbarkeit: eine echte
Optimierung "maximiere die geglaettete Erfolgswahrscheinlichkeit dieses
Ziels ueber die zulaessige Menge" (gleiche Bandbreiten/Restriktionen/
Risikobudget, Multi-Start inkl. aller Screen-Kandidaten und des Zentrums der
zulaessigen Menge), ausgewertet auf dem eigenen Screening-Wuerfel; demoted
nur, wenn die obere Wilson-Grenze (Kish-ESS) des besten gefundenen Punktes
< tau/2 liegt.
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

from services.optimizer import goal_reachability as reachability  # noqa: E402
from services.optimizer import objective as objective_module  # noqa: E402
from services.optimizer import solver as solver_module  # noqa: E402
from services.optimizer.goal_liabilities import GoalLiability  # noqa: E402
from services.optimizer.objective_contract import ObjectiveContractV1  # noqa: E402


def _hard_wealth_goal(target: int = 1_000):
    return GoalLiability(
        goal_id="hard-goal",
        label="Hard goal",
        goal_type="Vermögensziel",
        target_kind="wealth_at_t",
        target_amount_rappen=target,
        target_year_index=1,
        liability_path_rappen=[0],
        hardness_key="hart",
        weight_bps=10_000,
        success_probability_min_x100=8_000,
    )


# ---------------------------------------------------------------------------
# 1. Codex-Reproducer (docs/audits/reproducers/
#    test_2026_10_19_pr650_goal_hierarchy_adversarial.py), unveraendert
#    uebernommen, nur ohne xfail-Marker.
# ---------------------------------------------------------------------------


def test_finite_screen_miss_must_not_demote_feasible_hard_goal_from_stage1(
    monkeypatch: pytest.MonkeyPatch,
):
    """The inspected endpoints fail while a feasible interior allocation wins."""
    goal = _hard_wealth_goal()
    context = SimpleNamespace(
        liabilities=[goal],
        horizon_years=1,
        n_paths=200,
        advisory_wealth_rappen=100,
        objective_contract=ObjectiveContractV1(
            objective_mode="goal_shortfall",
            goal_weighting_mode="hardness",
        ),
    )

    monkeypatch.setattr(
        reachability,
        "candidate_allocations",
        lambda _context: [np.array([0.0, 1.0]), np.array([1.0, 0.0])],
    )
    monkeypatch.setattr(
        reachability,
        "_build_screening_context",
        lambda _context: (context, 123, "screen-cube"),
    )
    monkeypatch.setattr(
        solver_module,
        "_simulate_context_wealth",
        lambda _context, w: np.full((200, 2), float(w[0])),
    )
    monkeypatch.setattr(
        solver_module,
        "_annualized_twr_bps_per_path",
        lambda _context, _w: np.zeros(200),
    )

    def success_only_at_diversified_interior(wealth, *_args, **_kwargs):
        succeeds = abs(float(wealth[0, 0]) - 0.5) < 1e-12
        return np.full(wealth.shape[0], succeeds, dtype=bool)

    monkeypatch.setattr(
        objective_module,
        "_goal_probability_core",
        success_only_at_diversified_interior,
    )

    interior = solver_module._simulate_context_wealth(context, np.array([0.5, 0.5]))
    assert np.all(objective_module._goal_probability_core(interior, goal, 100))

    screen = reachability.goal_reachability_screen(context)
    assert screen["goals"][0]["status"] == "not_found_reachable_in_screen_set"
    assert screen["penalty_exempt_goal_ids"] == []

    context.goal_reachability = screen
    assert solver_module._stage1_liabilities(context) == [goal]
    # Und aus dem RICHTIGEN Grund: das Zertifikat hat den Innenpunkt
    # gefunden (Zentrum der zulaessigen Menge), nicht etwa "kein Zertifikat".
    row = screen["goals"][0]
    assert row["certificate"]["status"] == "reachable"
    assert row["certificate"]["max_probability"] == pytest.approx(1.0)
    assert row["certificate"]["best_bps"] == [5000, 5000]
    assert screen["demoted_goal_ids"] == []


# ---------------------------------------------------------------------------
# 2. Echte Optimierung: Innenpunkt, der weder Kandidat noch Zentrum ist
# ---------------------------------------------------------------------------

_W_STAR = np.array([0.45, 0.30, 0.15, 0.06, 0.04])


def _bump_context(monkeypatch, *, target: float, candidates=None, n_paths=400):
    """5-Bucket-Simplex, Vermoegen = 1000 * (1 - 4 ||w - w*||^2) + Rauschen.

    Erfolg (W >= Ziel) nur in einer Kugel um den Innenpunkt w*; die Ecken
    (Kandidaten) und das Zentrum (0.2, ...) verfehlen. Nur eine echte
    Optimierung ueber die zulaessige Menge findet die Kugel.
    """
    goal = _hard_wealth_goal(target=int(target))
    noise = np.random.default_rng(7).normal(0.0, 5.0, size=n_paths)
    context = SimpleNamespace(
        liabilities=[goal],
        horizon_years=1,
        n_paths=n_paths,
        advisory_wealth_rappen=100,
        bounds=[(0.0, 1.0)] * 5,
        scipy_constraints=[
            {"type": "eq", "fun": lambda w: float(np.sum(w) - 1.0)},
        ],
        scenario_weights=None,
        objective_contract=ObjectiveContractV1(
            objective_mode="goal_shortfall", goal_weighting_mode="hardness",
        ),
    )
    if candidates is None:
        candidates = [np.eye(5)[i] for i in range(5)]
    monkeypatch.setattr(
        reachability, "candidate_allocations", lambda _c: [np.array(c) for c in candidates],
    )
    monkeypatch.setattr(
        reachability, "_build_screening_context", lambda _c: (context, 321, "bump-cube"),
    )

    def wealth(_context, w):
        value = 1000.0 * (1.0 - 4.0 * float(np.sum((np.asarray(w) - _W_STAR) ** 2)))
        return np.column_stack([np.full(n_paths, 100.0), value + noise])

    monkeypatch.setattr(solver_module, "_simulate_context_wealth", wealth)
    monkeypatch.setattr(
        solver_module, "_annualized_twr_bps_per_path", lambda _c, _w: np.zeros(n_paths),
    )
    return context, goal


def _exact_probability(context, goal, w):
    wealth = solver_module._simulate_context_wealth(context, np.asarray(w))
    return float(np.mean(objective_module._goal_probability_core(wealth, goal, 100)))


def test_certificate_finds_an_interior_optimum_that_neither_screen_nor_center_contains(
    monkeypatch,
):
    context, goal = _bump_context(monkeypatch, target=960.0)
    # Gegenprobe der Konstruktion: Ecken und Zentrum verfehlen, w* trifft.
    assert all(_exact_probability(context, goal, np.eye(5)[i]) == 0.0 for i in range(5))
    assert _exact_probability(context, goal, np.full(5, 0.2)) == 0.0
    assert _exact_probability(context, goal, _W_STAR) > 0.99

    screen = reachability.goal_reachability_screen(context)
    row = screen["goals"][0]
    assert row["status"] == "not_found_reachable_in_screen_set"  # der Screen allein
    certificate = row["certificate"]
    assert certificate["status"] == "reachable"
    assert certificate["max_upper_bound"] >= 0.5 * row["tau"]
    assert certificate["n_local_solves"] >= 1
    assert screen["demoted_goal_ids"] == []
    context.goal_reachability = screen
    assert solver_module._stage1_liabilities(context) == [goal]


@pytest.mark.parametrize("variant", ["reversed", "extra_start", "fewer_starts", "rounded"])
def test_candidate_order_extra_or_removed_starts_do_not_change_the_protection_class(
    monkeypatch, variant,
):
    """Codex-Pflichtregression: Kandidatenreihenfolge, zusaetzliche/entfernte
    Startpunkte und Rundung aendern nie die Schutzklasse desselben Ziels."""
    base = [np.eye(5)[i] for i in range(5)]
    candidates = {
        "reversed": base[::-1],
        "extra_start": base + [np.array([0.1, 0.1, 0.6, 0.1, 0.1])],
        "fewer_starts": base[:3],
        "rounded": [np.round(c * 0.9995 + 0.0001, 4) for c in base],
    }[variant]
    context, goal = _bump_context(monkeypatch, target=960.0, candidates=candidates)
    screen = reachability.goal_reachability_screen(context)
    assert screen["demoted_goal_ids"] == []
    context.goal_reachability = screen
    assert solver_module._stage1_liabilities(context) == [goal]


def test_truly_unreachable_goal_is_certified_and_demoted(monkeypatch):
    """Positivkontrolle: Ziel ueber dem globalen Maximum (1000 + Rauschen)."""
    context, goal = _bump_context(monkeypatch, target=5_000.0)
    screen = reachability.goal_reachability_screen(context)
    row = screen["goals"][0]
    certificate = row["certificate"]
    assert certificate["status"] == "certified_unreachable_on_screen_cube"
    assert certificate["max_upper_bound"] < 0.5 * row["tau"]
    assert certificate["n_eff"] == pytest.approx(400.0)
    assert certificate["screening_cube_hash"] == "bump-cube"
    assert certificate["n_starts"] == 6  # 5 Kandidaten + Zentrum
    assert screen["demoted_goal_ids"] == ["hard-goal"]
    assert screen["certified_unreachable_goal_ids"] == ["hard-goal"]
    context.goal_reachability = screen
    assert solver_module._stage1_liabilities(context) == []


def test_certificate_uses_kish_ess_under_scenario_weights(monkeypatch):
    """Obere Wilson-Grenze mit Kish-ESS: ungleiche Gewichte -> kleinere ESS
    -> breitere Grenze."""
    context, _goal = _bump_context(monkeypatch, target=5_000.0)
    weights = np.ones(400)
    weights[:200] = 3.0
    context.scenario_weights = weights
    screen = reachability.goal_reachability_screen(context)
    n_eff = screen["goals"][0]["certificate"]["n_eff"]
    expected = float(np.sum(weights)) ** 2 / float(np.sum(weights ** 2))
    assert n_eff == pytest.approx(expected)
    assert n_eff < 400.0


def test_without_feasible_set_a_screen_miss_is_never_demoted(monkeypatch):
    """Fail-safe: ohne Bandbreiten kein Zertifikat -> keine Herabstufung."""
    context, goal = _bump_context(monkeypatch, target=5_000.0)
    del context.bounds
    screen = reachability.goal_reachability_screen(context)
    assert screen["goals"][0]["certificate"]["status"] == "certificate_unavailable"
    assert screen["demoted_goal_ids"] == []
    context.goal_reachability = screen
    assert solver_module._stage1_liabilities(context) == [goal]


def test_not_found_status_alone_does_not_demote():
    """``not_found_reachable_goal_ids`` ist reine Offenlegung: nur
    ``demoted_goal_ids`` (zertifiziert) steuert die Stufe 1."""
    goal = _hard_wealth_goal()
    context = SimpleNamespace(
        liabilities=[goal], horizon_years=1,
        goal_reachability={
            "not_found_reachable_goal_ids": ["hard-goal"],
            "unreachable_goal_ids": ["hard-goal"],
            "demoted_goal_ids": [],
        },
    )
    assert solver_module._stage1_liabilities(context) == [goal]
    assert solver_module._demoted_goal_ids(context) == frozenset()


def test_policy_versions_are_bound_in_the_objective_contract():
    from services.optimizer.objective import DEMOTED_GOAL_POLICY_VERSION
    from services.optimizer.objective_contract import resolve_objective_contract

    evidence = resolve_objective_contract().as_evidence()
    assert evidence["goal_reachability_policy"] == reachability.GOAL_REACHABILITY_SCREEN_VERSION
    assert "certif" in reachability.GOAL_REACHABILITY_SCREEN_VERSION
    assert evidence["goal_demotion_policy"] == DEMOTED_GOAL_POLICY_VERSION
    assert DEMOTED_GOAL_POLICY_VERSION.startswith("certified_unreachable_")
    assert solver_module.OPTIMIZER_ENGINE_VERSION == "saa_resampled_v9_reach"
