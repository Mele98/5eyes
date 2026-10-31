"""RESAMPLING-SUCCESS-SURVIVOR-BIAS-001, Restvertrag (Engine v14).

Befund (Codex-Review 2026-10-19 zu #649): bei 36/40 erfolgreichen Bags mit
identischen Gewichten meldete ``missingness_sensitivity_bps = f * 2 *
std(Erfolge)`` 0 bp, obwohl die vier fehlenden Outcomes vollstaendig
unbeobachtet sind. Allein die [0,1]-Bandbreiten erlauben beim Aktiengewicht
600 bp.

Vertrag ab v14:

* Schranke = identifizierter Bereich auf Bandbreiten + Simplex
  (``f * max(m - lo', hi' - m)``), scharf, ohne Verteilungsannahme.
* Schaetzgroesse explizit (``estimand``): Mittel ueber alle Bags nur bei
  vollstaendigem Lauf, sonst ``conditional_on_solver_success``.
* Mindestquote 90 % bleibt; zusaetzlich fail-closed, wenn die Schranke in
  einem Bucket das Praezisionsziel (100 bps) uebersteigt
  (``reason = missingness_bound_exceeds_budget``), kein Mittel publiziert.
"""
from __future__ import annotations

import itertools
from types import SimpleNamespace

import numpy as np
import pytest

from services.optimizer import resampling as rs
from services.optimizer import solver as solver_module
from services.optimizer.resampling import ResamplingConfig, resampling_model_basis
from services.optimizer.scenario_engine import BUCKET_ORDER


# ---------------------------------------------------------------------------
# Codex-Reproducer (docs/audits/reproducers/
# test_2026_10_19_pr649_resampling_missingness_adversarial.py), wortgleich
# ohne xfail.
# ---------------------------------------------------------------------------


def test_missing_bags_cannot_have_zero_uncertainty_when_successes_are_identical(
    monkeypatch: pytest.MonkeyPatch,
):
    """A zero conditional dispersion says nothing about failed optimizations.

    Thirty-six successful bags all return the same allocation; four bags have
    no candidate.  The published mean is therefore conditional on success.
    With no model for the failures, a valid conservative per-bucket bound is
    at least the feasible-set worst case.  For bounds [0, 1], failure share f
    and conditional mean m this is ``f * max(m, 1-m)``.  Falling back instead
    of publishing the mean is also valid.
    """
    from services.optimizer import solver as solver_module
    from services.optimizer.resampling import ResamplingConfig

    n_bags, n_success = 40, 36
    weights = np.array([0.40, 0.30, 0.10, 0.10, 0.10], dtype=np.float64)
    selections = iter([
        solver_module._CubeSelection(
            weights=(weights if i < n_success else None),
            objective=(1.0 if i < n_success else float("inf")),
            total_iters=1,
            n_starts=1,
            attempt_summaries=[],
            used_ga_fallback=False,
            accepted_feasible_non_success=False,
            robustification_derisked=False,
        )
        for i in range(n_bags)
    ])
    context = SimpleNamespace(
        scenario_inputs=object(),
        n_paths=20,
        seed=7,
        scenario_weights=None,
        bounds=[(0.0, 1.0)] * 5,
    )

    monkeypatch.setattr(solver_module, "bag_seeds", lambda _s, n: list(range(n)))
    monkeypatch.setattr(solver_module, "_bag_context", lambda ctx, **_kw: ctx)
    monkeypatch.setattr(
        solver_module,
        "_select_cube_candidate",
        lambda *_a, **_kw: next(selections),
    )
    monkeypatch.setattr(solver_module, "_weights_to_bps_dict", lambda *_a, **_kw: {})
    monkeypatch.setattr(solver_module, "_project_onto_feasible_set", lambda w, _c: w)
    monkeypatch.setattr(
        solver_module,
        "_rounded_bps_with_repair",
        lambda *_a, **_kw: {
            "equities": 4000,
            "bonds": 3000,
            "real_estate": 1000,
            "alternatives": 1000,
            "liquidity": 1000,
        },
    )
    monkeypatch.setattr(
        solver_module,
        "objective_contract_of",
        lambda _ctx: SimpleNamespace(objective_mode="goal_shortfall"),
    )
    monkeypatch.setattr(
        solver_module,
        "_significance_vs_house_anchor",
        lambda *_a, **_kw: {"decision": "unavailable", "reason": "audit"},
    )
    monkeypatch.setattr(
        solver_module,
        "_trusted_weights_bps_to_array",
        lambda _bps: np.zeros(5),
    )
    monkeypatch.setattr(
        solver_module,
        "_finalize_solver_result",
        lambda *_a, resampling_payload=None, **_kw: SimpleNamespace(
            status="optimizer",
            resampling=resampling_payload,
        ),
    )
    monkeypatch.setattr(
        solver_module,
        "_house_midpoint_fallback_result",
        lambda _ctx, _selection, *, extra_reasoning=None, resampling_payload=None: (
            SimpleNamespace(
                status="fallback_house_matrix",
                resampling=resampling_payload,
                reasoning=extra_reasoning,
            )
        ),
    )

    result = solver_module._run_resampled_solver(
        context,
        config=ResamplingConfig(n_bags=n_bags, bag_n_paths=20),
        house_anchor_bps=None,
        max_iter=1,
        ftol=1e-6,
        advisory_wealth_rappen=1,
        cashflow_series_rappen=[],
    )
    payload = result.resampling
    assert payload["n_bags_succeeded"] == n_success

    # A conservative fallback is acceptable.  If the conditional mean is
    # published, its failure uncertainty must cover the feasible-set worst
    # case instead of collapsing with the successful-bag variance.
    if "mean_weights_bps" in payload:
        failure_share = (n_bags - n_success) / n_bags
        for bucket, mean_bps in payload["mean_weights_bps"].items():
            mean = float(mean_bps) / 10_000.0
            minimum_bound_bps = failure_share * max(mean, 1.0 - mean) * 10_000.0
            assert payload["missingness_sensitivity_bps"][bucket] >= minimum_bound_bps


# ---------------------------------------------------------------------------
# Harness: _run_resampled_solver mit vorgegebenen Bag-Ergebnissen
# ---------------------------------------------------------------------------

SCORE7_BOUNDS = [(0.60, 0.75), (0.10, 0.25), (0.05, 0.20), (0.03, 0.10), (0.02, 0.02)]
UNIT_BOUNDS = [(0.0, 1.0)] * 5


def _run(monkeypatch, bag_results, *, bounds):
    """``bag_results``: Liste von Gewichtsvektoren bzw. ``None`` (Ausfall)."""
    n_bags = len(bag_results)
    selections = iter([
        solver_module._CubeSelection(
            weights=(None if w is None else np.asarray(w, dtype=np.float64)),
            objective=(float("inf") if w is None else 1.0),
            total_iters=1, n_starts=1, attempt_summaries=[],
            used_ga_fallback=False, accepted_feasible_non_success=False,
            robustification_derisked=False,
        )
        for w in bag_results
    ])
    context = SimpleNamespace(
        scenario_inputs=object(), n_paths=20, seed=7, scenario_weights=None,
        bounds=list(bounds),
    )
    monkeypatch.setattr(solver_module, "bag_seeds", lambda _s, n: list(range(n)))
    monkeypatch.setattr(solver_module, "_bag_context", lambda ctx, **_kw: ctx)
    monkeypatch.setattr(
        solver_module, "_select_cube_candidate", lambda *_a, **_kw: next(selections),
    )
    monkeypatch.setattr(solver_module, "_weights_to_bps_dict", lambda *_a, **_kw: {})
    monkeypatch.setattr(solver_module, "_project_onto_feasible_set", lambda w, _c: w)
    monkeypatch.setattr(
        solver_module, "_rounded_bps_with_repair",
        lambda w, _c: {b: int(round(float(w[i]) * 10000)) for i, b in enumerate(BUCKET_ORDER)},
    )
    monkeypatch.setattr(
        solver_module, "objective_contract_of",
        lambda _ctx: SimpleNamespace(objective_mode="goal_shortfall"),
    )
    monkeypatch.setattr(
        solver_module, "_significance_vs_house_anchor",
        lambda *_a, **_kw: {"decision": "unavailable", "reason": "test"},
    )
    monkeypatch.setattr(solver_module, "_trusted_weights_bps_to_array", lambda _b: np.zeros(5))
    monkeypatch.setattr(
        solver_module, "_finalize_solver_result",
        lambda *_a, resampling_payload=None, extra_reasoning=None, **_kw: SimpleNamespace(
            status="optimizer", resampling=resampling_payload, reasoning=extra_reasoning,
        ),
    )
    monkeypatch.setattr(
        solver_module, "_house_midpoint_fallback_result",
        lambda _c, _s, *, extra_reasoning=None, resampling_payload=None: SimpleNamespace(
            status="fallback_house_matrix", resampling=resampling_payload,
            reasoning=extra_reasoning,
        ),
    )
    return solver_module._run_resampled_solver(
        context,
        config=ResamplingConfig(n_bags=n_bags, bag_n_paths=20),
        house_anchor_bps=None, max_iter=1, ftol=1e-6,
        advisory_wealth_rappen=1, cashflow_series_rappen=[],
    )


def _vertices(bounds) -> np.ndarray:
    """Unabhaengiges Orakel: Ecken von Box und Simplex durch Aufzaehlung.

    Jede Ecke hat hoechstens eine Koordinate strikt zwischen ihren Grenzen;
    alle anderen liegen auf lo oder hi.
    """
    arr = np.asarray(bounds, dtype=np.float64)
    n = arr.shape[0]
    found = []
    for free in range(n):
        others = [j for j in range(n) if j != free]
        for choice in itertools.product((0, 1), repeat=n - 1):
            w = np.empty(n)
            for j, c in zip(others, choice):
                w[j] = arr[j, c]
            w[free] = 1.0 - w[others].sum()
            if arr[free, 0] - 1e-12 <= w[free] <= arr[free, 1] + 1e-12:
                found.append(w)
    return np.unique(np.round(np.array(found), 12), axis=0)


def _random_bounds(rng) -> list[tuple[float, float]]:
    while True:
        lo = rng.uniform(0.0, 0.25, size=5)
        hi = np.minimum(lo + rng.uniform(0.0, 0.6, size=5), 1.0)
        if lo.sum() <= 1.0 <= hi.sum():
            return list(zip(lo.tolist(), hi.tolist()))


def _random_feasible_point(rng, vertices) -> np.ndarray:
    lam = rng.dirichlet(np.ones(len(vertices)))
    return lam @ vertices


# ---------------------------------------------------------------------------
# Pflichtregressionen
# ---------------------------------------------------------------------------


def test_complete_run_has_zero_bound_and_all_bag_estimand(monkeypatch):
    w = [0.40, 0.30, 0.10, 0.10, 0.10]
    payload = _run(monkeypatch, [w] * 40, bounds=UNIT_BOUNDS).resampling
    assert payload["estimand"] == rs.ESTIMAND_ALL_BAGS
    assert all(v == 0.0 for v in payload["missingness_sensitivity_bps"].values())
    assert all(v == 0.0 for v in payload["conditional_bag_mean_standard_error_bps"].values())
    assert payload["mean_weights_bps"]["equities"] == 4000.0
    # Bereich des Mittels ueber alle Bags kollabiert auf den Punkt.
    assert payload["all_bags_mean_bounds_bps"]["equities"] == [4000.0, 4000.0]


def test_36_of_40_identical_successes_fail_closed_on_unit_bands(monkeypatch):
    w = [0.40, 0.30, 0.10, 0.10, 0.10]
    result = _run(monkeypatch, [w] * 36 + [None] * 4, bounds=UNIT_BOUNDS)
    payload = result.resampling
    assert result.status == "fallback_house_matrix"
    assert payload["decision"] == "fallback_house_matrix"
    assert payload["reason"] == "missingness_bound_exceeds_budget"
    assert "mean_weights_bps" not in payload
    assert "final_weights_bps" not in payload
    # f * max(m, 1 - m) = 0.1 * 0.6 = 600 bps (vorher: 0 bps).
    assert payload["missingness_sensitivity_bps"]["equities"] == pytest.approx(600.0, abs=0.011)
    assert payload["missingness_sensitivity_bps"]["equities"] >= 600.0
    assert any("Praezisionsziel" in line for line in result.reasoning)


def test_minimum_quota_stays_first_gate_even_with_zero_width_bands(monkeypatch):
    """Bandbreiten der Breite 0: Schranke 0, die Quote blockiert trotzdem."""
    w = [0.40, 0.30, 0.10, 0.10, 0.10]
    fixed = [(x, x) for x in w]
    payload = _run(monkeypatch, [w] * 35 + [None] * 5, bounds=fixed).resampling
    assert payload["reason"] == "insufficient_successful_bags"
    assert "mean_weights_bps" not in payload


def test_39_of_40_on_house_bands_publishes_conditional_mean_with_covering_bound(monkeypatch):
    """Enge Erfolgsstreuung, adversarial fehlender Bag: die Schranke deckt
    jede zulaessige Allokation des fehlenden Bags (Ecken-Orakel)."""
    w = np.array([0.68, 0.16, 0.08, 0.06, 0.02])
    result = _run(monkeypatch, [w] * 39 + [None], bounds=SCORE7_BOUNDS)
    payload = result.resampling
    assert payload["estimand"] == rs.ESTIMAND_CONDITIONAL_ON_SUCCESS
    assert "mean_weights_bps" in payload
    assert all(v == 0.0 for v in payload["conditional_bag_mean_standard_error_bps"].values())
    mean = np.array([payload["mean_weights_bps"][b] for b in BUCKET_ORDER]) / 10000.0
    for v in _vertices(SCORE7_BOUNDS):
        all_bags_mean = (39 * mean + v) / 40.0
        for i, bucket in enumerate(BUCKET_ORDER):
            shift_bps = abs(all_bags_mean[i] - mean[i]) * 10000.0
            assert shift_bps <= payload["missingness_sensitivity_bps"][bucket] + 1e-9
            lo, hi = payload["all_bags_mean_bounds_bps"][bucket]
            assert lo - 1e-9 <= all_bags_mean[i] * 10000.0 <= hi + 1e-9
    # Scharf: Aktien 0.025 * max(0.68 - 0.60, 0.75 - 0.68) = 20 bps.
    assert payload["missingness_sensitivity_bps"]["equities"] == pytest.approx(20.0, abs=0.011)
    assert any("bedingt auf Solver-Erfolg" in line for line in result.reasoning)


def test_bound_is_sharp_against_vertex_oracle_property():
    """Property (200 Faelle, fester Seed): Schranke und Bereich == Extrema
    ueber alle Ecken (unabhaengiges Orakel), also weder zu eng noch zu weit."""
    rng = np.random.default_rng(20261024)
    for _ in range(200):
        bounds = _random_bounds(rng)
        vertices = _vertices(bounds)
        mean = _random_feasible_point(rng, vertices)
        n_bags = 40
        n_ok = int(rng.integers(30, 41))
        f = (n_bags - n_ok) / n_bags
        out = rs.missingness_identified_set(mean, bounds, n_bags=n_bags, n_succeeded=n_ok)
        all_bags = (1.0 - f) * mean + f * vertices
        oracle_bound = np.max(np.abs(all_bags - mean), axis=0)
        np.testing.assert_allclose(out["bound"], oracle_bound, atol=1e-12)
        np.testing.assert_allclose(out["lower"], all_bags.min(axis=0), atol=1e-12)
        np.testing.assert_allclose(out["upper"], all_bags.max(axis=0), atol=1e-12)
        # Abdeckung fuer beliebige zulaessige fehlende Outcomes (nicht nur Ecken).
        for _k in range(5):
            missing = np.array([
                _random_feasible_point(rng, vertices) for _m in range(n_bags - n_ok)
            ]).reshape(-1, 5)
            full = (n_ok * mean + missing.sum(axis=0)) / n_bags
            assert np.all(np.abs(full - mean) <= out["bound"] + 1e-12)


def test_bound_metamorphic_relations():
    rng = np.random.default_rng(7)
    mean = np.array([0.40, 0.30, 0.10, 0.10, 0.10])
    wide = rs.missingness_identified_set(mean, UNIT_BOUNDS, n_bags=40, n_succeeded=38)["bound"]
    narrow_bounds = [(0.30, 0.50), (0.20, 0.40), (0.05, 0.15), (0.05, 0.15), (0.05, 0.15)]
    narrow = rs.missingness_identified_set(
        mean, narrow_bounds, n_bags=40, n_succeeded=38,
    )["bound"]
    # Engere Bandbreiten engen nur ein, nie aus.
    assert np.all(narrow <= wide + 1e-15)
    # Mehr Ausfall -> nie kleinere Schranke.
    previous = np.zeros(5)
    for n_ok in range(40, 29, -1):
        b = rs.missingness_identified_set(
            mean, UNIT_BOUNDS, n_bags=40, n_succeeded=n_ok,
        )["bound"]
        assert np.all(b >= previous - 1e-15)
        previous = b
    # Permutation der Buckets permutiert die Schranke.
    perm = rng.permutation(5)
    permuted = rs.missingness_identified_set(
        mean[perm], [narrow_bounds[i] for i in perm], n_bags=40, n_succeeded=38,
    )["bound"]
    np.testing.assert_allclose(permuted, narrow[perm], atol=1e-15)
    # Unabhaengig von der Streuung der Erfolge (die Erfolge bestimmen nur m).
    assert rs.missingness_identified_set(
        mean, UNIT_BOUNDS, n_bags=40, n_succeeded=36,
    )["bound"][0] == pytest.approx(0.1 * 0.6)


def test_bound_rounding_never_tightens():
    assert rs.ceil_bps(0.0060000001) >= 60.000001
    assert rs.ceil_bps(0.06) >= 600.0
    assert rs.floor_bps(0.06) <= 600.0
    assert rs.ceil_bps(0.0) == 0.0


def test_identified_set_rejects_invalid_counts():
    with pytest.raises(ValueError):
        rs.missingness_identified_set(np.zeros(5), UNIT_BOUNDS, n_bags=40, n_succeeded=41)
    with pytest.raises(ValueError):
        rs.missingness_identified_set(np.zeros(4), UNIT_BOUNDS, n_bags=40, n_succeeded=40)


def test_model_basis_binds_estimand_bound_method_and_fallback_reason(monkeypatch):
    w = np.array([0.68, 0.16, 0.08, 0.06, 0.02])
    published = _run(monkeypatch, [w] * 39 + [None], bounds=SCORE7_BOUNDS).resampling
    basis = resampling_model_basis(published)
    assert basis["estimand"] == rs.ESTIMAND_CONDITIONAL_ON_SUCCESS
    assert basis["missingness_bound_method"] == rs.MISSINGNESS_BOUND_METHOD
    assert basis["missingness_bound_budget_bps"] == rs.MISSINGNESS_BOUND_BUDGET_BPS
    assert basis["all_bags_mean_bounds_bps"] == published["all_bags_mean_bounds_bps"]
    failed = _run(monkeypatch, [list(w)] * 36 + [None] * 4, bounds=UNIT_BOUNDS).resampling
    assert resampling_model_basis(failed)["reason"] == "missingness_bound_exceeds_budget"


def test_identical_inputs_give_identical_payload(monkeypatch):
    w = np.array([0.68, 0.16, 0.08, 0.06, 0.02])
    a = _run(monkeypatch, [w] * 39 + [None], bounds=SCORE7_BOUNDS).resampling
    b = _run(monkeypatch, [w] * 39 + [None], bounds=SCORE7_BOUNDS).resampling
    for payload in (a, b):
        payload.pop("elapsed_ms")
        for bag in payload["bags"]:
            bag.pop("elapsed_ms")
    assert a == b
