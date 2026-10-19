"""Statistische Vertraege der Engine ``saa_resampled_v7``.

Schliesst die Codex-Befunde vom 2026-10-18 (Reviews
``2026-10-18-resampled-efficiency-and-drawdown-validation-review.md`` und
``2026-10-18-house-prior-v6-pr640-current-review.md``):

* RESAMPLING-ANTITHETIC-BOOTSTRAP-001 -- Bootstrap ueber unabhaengige
  Stichprobeneinheiten (antithetische Paare), nicht ueber Zeilen.
* RESAMPLING-PVALUE-SEMANTICS-001 -- ``p_value`` ist ein nullzentrierter
  einseitiger p-Wert mit Nullhypothese; der rohe Vorzeichenanteil heisst
  ``bootstrap_tail_fraction``. Groesse unter H0 simuliert.
* DRAWDOWN-HOLDOUT-REUSE-001 -- Auswahl-Wuerfel und finaler Holdout getrennt;
  Challenger vor dem finalen Test eingefroren.
* RESAMPLING-SUCCESS-SURVIVOR-BIAS-001 -- Mindestquote 90 % erfolgreicher
  Bags, darunter fail-closed.
* HOUSE-PRIOR-PSD-NULLSPACE-001 -- Ridge-Metrik ``Sigma + eps I``.
* HOUSE-PRIOR-DECISION-OBJECTIVE-IDENTITY-001 -- das Ergebnis traegt den
  Prior-Context, unter dem selektiert wurde.
* OPTIMIZER-POST-SELECTION-CERTIFICATION-001 -- ohne Validierungswuerfel
  fail-closed auf die Hausquote (Prior und Varianten).

Die unveraenderten Codex-Reproducer liegen in ``test_stat_contract_*.py``.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _path in (BACKEND_ROOT, TESTS_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from services.optimizer import house_prior as hp  # noqa: E402
from services.optimizer import resampling as rs  # noqa: E402
from services.optimizer import solver as solver_module  # noqa: E402
from services.optimizer.objective_variants import (  # noqa: E402
    OBJECTIVE_GOAL_SHORTFALL,
    OBJECTIVE_MAX_DRAWDOWN,
)
from services.optimizer.scenario_engine import (  # noqa: E402
    N_BUCKETS,
    ScenarioInputs,
    build_scenario_paths,
    sampling_unit_ids,
)
from services.optimizer.solver import (  # noqa: E402
    VALIDATION_SEED_OFFSET,
    build_optimizer_context,
    evaluate_weights,
    run_solver,
)

from test_optimizer_context import _cma, _house_matrix, _pension_goal  # noqa: E402

SEED = 20261018
HORIZON = 10


def _kwargs(**overrides) -> dict:
    base = dict(
        cma=_cma(),
        goals=[_pension_goal()],
        house_matrix_row=_house_matrix(),
        score_x10=70,
        advisory_wealth_rappen=500_000_00,
        cashflow_series_rappen=[20_000_00] * HORIZON,
        horizon_years=HORIZON,
        n_paths=400,
        seed=SEED,
    )
    base.update(overrides)
    return base


SMALL = rs.ResamplingConfig(n_bags=4, bag_n_paths=200, n_bootstrap=60)


def _identity_inputs() -> ScenarioInputs:
    return ScenarioInputs(
        mu_bps=np.full(N_BUCKETS, 500, dtype=np.float64),
        sigma_bps=np.full(N_BUCKETS, 1000, dtype=np.float64),
        skew_bps=np.zeros(N_BUCKETS, dtype=np.float64),
        excess_kurt_bps=np.zeros(N_BUCKETS, dtype=np.float64),
        cholesky=np.eye(N_BUCKETS),
    )


# ---------------------------------------------------------------------------
# RESAMPLING-ANTITHETIC-BOOTSTRAP-001: Stichprobeneinheit
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n_paths", [10, 11])
def test_sampling_unit_ids_describe_the_antithetic_layout(n_paths):
    """Partner (i, i + ceil(n/2)) stammen aus derselben Ziehung Z: ohne
    Schiefe/Kurtosis ist log r_i + log r_partner fuer alle Paare gleich.
    Ungerade Pfadzahl: der letzte Basispfad ist eine Einzel-Einheit."""
    paths = build_scenario_paths(
        _identity_inputs(), horizon_years=3, n_paths=n_paths, seed=5, antithetic=True,
    )
    ids = sampling_unit_ids(n_paths, antithetic=True)
    half = (n_paths + 1) // 2
    counts = np.bincount(ids)
    assert counts.size == half
    expected = [2] * (n_paths // 2) + ([1] if n_paths % 2 else [])
    assert counts.tolist() == expected
    logs = np.log(paths)
    reference = logs[0] + logs[half]
    for unit in range(n_paths // 2):
        a, b = np.flatnonzero(ids == unit)
        assert b == a + half
        np.testing.assert_allclose(logs[a] + logs[b], reference, atol=1e-12)
    np.testing.assert_array_equal(
        sampling_unit_ids(n_paths, antithetic=False), np.arange(n_paths),
    )


@pytest.mark.parametrize("n_paths", [12, 13])
def test_unit_bootstrap_draws_partners_together_and_equally_often(n_paths):
    ids = sampling_unit_ids(n_paths, antithetic=True)
    drawn: list[np.ndarray] = []

    def statistic(idx):
        if idx is not None:
            drawn.append(np.asarray(idx))
        return 0.0

    _full, _reps, meta = rs.unit_block_bootstrap(
        statistic, n_paths=n_paths, n_bootstrap=40, seed=3,
    )
    assert meta["sampling_unit"] == "antithetic_pair"
    assert meta["n_independent_units"] == (n_paths + 1) // 2
    for idx in drawn:
        counts = np.bincount(idx, minlength=n_paths)
        for unit in np.unique(ids):
            members = np.flatnonzero(ids == unit)
            assert len(set(counts[members].tolist())) == 1
        # m = ceil(n/2) Einheiten je Replikation: gerade n -> exakt n Pfade,
        # ungerade n -> 2(m - k) + k Pfade (k = Ziehungen der Einzel-Einheit).
        if n_paths % 2 == 0:
            assert counts.sum() == n_paths
        else:
            half = (n_paths + 1) // 2
            singles = int(counts[half - 1])
            assert counts.sum() == 2 * (half - singles) + singles


def test_single_path_units_reproduce_the_legacy_row_bootstrap_stream():
    """Unabhaengige Pfade: Einzelpfad-Einheiten == bisheriger Zeilen-Bootstrap
    (gleicher RNG-Strom, gleiche Replikationen)."""
    effects = np.random.default_rng(7).normal(0.0, 1.0, 40)

    def statistic(idx):
        return float(np.mean(effects if idx is None else effects[idx]))

    _full, reps, meta = rs.unit_block_bootstrap(
        statistic, n_paths=40, n_bootstrap=50, seed=9,
        sampling_unit_ids=np.arange(40), sampling_unit="path",
    )
    rng = np.random.default_rng(9)
    legacy = [float(np.mean(effects[rng.integers(0, 40, size=40)])) for _ in range(50)]
    np.testing.assert_allclose(reps, legacy, rtol=0, atol=0)
    assert meta["n_independent_units"] == 40


def _codex_counterexample():
    pair_effects = np.random.default_rng(2).normal(0.14, 1.0, 100)
    path_effects = np.concatenate([pair_effects, pair_effects])

    def loss_pair(indices):
        sample = path_effects if indices is None else path_effects[indices]
        return float(np.mean(sample)), 0.0

    return loss_pair


def test_codex_counterexample_numbers_before_and_after():
    """Deterministischer Gegenfall aus dem Review, Zahlen gepinnt:

    * vorher (Zeilen-Bootstrap): Vorzeichenanteil 0.0374 -> 'signifikant',
    * nachher (Paar-Bootstrap): Vorzeichenanteil 0.0873, p (nullzentriert)
      0.0723 -> nicht signifikant.
    """
    loss_pair = _codex_counterexample()
    kwargs = dict(n_paths=200, n_bootstrap=400, alpha=0.05, seed=11)
    rows = rs.paired_bootstrap_improvement(
        loss_pair, sampling_unit_ids=np.arange(200), sampling_unit="path", **kwargs,
    )
    pairs = rs.paired_bootstrap_improvement(loss_pair, **kwargs)
    assert rows["bootstrap_tail_fraction"] == pytest.approx(15 / 401)
    assert rows["significant"] is True  # der Defekt, wenn man Zeilen zieht
    assert pairs["sampling_unit"] == "antithetic_pair"
    assert pairs["n_independent_units"] == 100
    assert pairs["bootstrap_tail_fraction"] == pytest.approx(35 / 401)
    assert pairs["p_value"] == pytest.approx(29 / 401)
    assert pairs["significant"] is False
    assert pairs["improvement_lower_bound"] < 0.0


# ---------------------------------------------------------------------------
# RESAMPLING-PVALUE-SEMANTICS-001: Kalibrierung und Benennung
# ---------------------------------------------------------------------------


def _size_under_h0(*, pairs: bool, n_datasets: int = 1000) -> float:
    """Ablehnungsrate bei wahrem Delta = 0, perfekt positiv korrelierte
    Partner (der Grenzfall des Reviews), 100 Einheiten, B = 199."""
    rng = np.random.default_rng(20261018)
    rejections = 0
    for k in range(n_datasets):
        unit_effects = rng.normal(0.0, 1.0, 100)
        path_effects = np.concatenate([unit_effects, unit_effects])

        def loss_pair(idx, data=path_effects):
            sample = data if idx is None else data[idx]
            return float(np.mean(sample)), 0.0

        stats = rs.paired_bootstrap_improvement(
            loss_pair,
            n_paths=200,
            n_bootstrap=199,
            alpha=0.05,
            seed=1000 + k,
            sampling_unit_ids=None if pairs else np.arange(200),
            sampling_unit=None if pairs else "path",
        )
        rejections += int(stats["significant"])
    return rejections / n_datasets


def test_null_centered_pair_bootstrap_holds_nominal_size_under_h0():
    """Groesse <= alpha + 3 MC-Standardfehler (1000 Datensaetze: se 0.0069;
    gemessen 0.060, in einem Kontrolllauf mit 3000 Datensaetzen 0.049).
    Der Zeilen-Bootstrap derselben Daten ist deutlich antikonservativ
    (gemessen 0.124; theoretisch 1 - Phi(1.645 / sqrt(2)) = 0.122)."""
    alpha, n = 0.05, 1000
    se = np.sqrt(alpha * (1 - alpha) / n)
    size_pairs = _size_under_h0(pairs=True, n_datasets=n)
    size_rows = _size_under_h0(pairs=False, n_datasets=n)
    assert size_pairs <= alpha + 3 * se, size_pairs
    assert size_rows > alpha + 3 * se, size_rows


def test_pvalue_tail_fraction_and_bound_are_separate_named_quantities():
    effects = np.linspace(-0.05, 0.20, 40)

    def loss_pair(idx):
        sample = effects if idx is None else effects[idx]
        return float(np.mean(sample)), 0.0

    out = rs.paired_bootstrap_improvement(
        loss_pair, n_paths=40, n_bootstrap=200, alpha=0.05, seed=4,
    )
    assert out["null_hypothesis"] == rs.NULL_HYPOTHESIS_NOT_BETTER
    assert out["p_value_calibration"] == rs.P_VALUE_CALIBRATION
    assert out["bootstrap_method"] == rs.BOOTSTRAP_METHOD_VERSION
    assert out["test"] == rs.SIGNIFICANCE_TEST_VERSION
    assert len(out["sampling_unit_hash"]) == 64
    # Duale Grenze: signifikant <=> untere Basic-Grenze > 0 (klarer Fall).
    assert out["significant"] is True and out["improvement_lower_bound"] > 0.0
    assert out["p_value"] != out["bootstrap_tail_fraction"] or out["p_value"] == pytest.approx(1 / 201)


def test_house_prior_disclosure_uses_pairs_and_calibrated_two_sided_contract():
    loss_pair = _codex_counterexample()

    def flipped(idx):
        house, final = loss_pair(idx)
        return -house, final  # Delta = -effects: Ergebnis schlechter

    out = hp.paired_bootstrap_disclosure(
        flipped, n_paths=200, n_bootstrap=400, alpha=0.05, seed=11,
    )
    assert out["sampling_unit"] == "antithetic_pair"
    assert out["null_hypothesis"]["p_value_worse"] == rs.NULL_HYPOTHESIS_NOT_WORSE
    assert out["p_value_worse"] == pytest.approx(29 / 401)
    # Mit Paaren NICHT signifikant schlechter (Zeilen haetten 'schlechter' gemeldet).
    assert out["significantly_worse"] is False
    assert out["improvement_lower_bound"] < out["improvement"] < out["improvement_upper_bound"]


# ---------------------------------------------------------------------------
# RESAMPLING-SUCCESS-SURVIVOR-BIAS-001
# ---------------------------------------------------------------------------


def _run_with_successes(monkeypatch, n_bags: int, n_success: int):
    weights = np.array([0.40, 0.30, 0.10, 0.10, 0.10], dtype=np.float64)
    selections = iter([
        solver_module._CubeSelection(
            weights=(weights if i < n_success else None),
            objective=(1.0 if i < n_success else float("inf")),
            total_iters=1, n_starts=1, attempt_summaries=[],
            used_ga_fallback=False, accepted_feasible_non_success=False,
            robustification_derisked=False,
        )
        for i in range(n_bags)
    ])
    context = SimpleNamespace(
        scenario_inputs=object(), n_paths=20, seed=7, scenario_weights=None,
        bounds=[(0.0, 1.0)] * 5,
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
        lambda *_a, **_kw: {"equities": 4000, "bonds": 3000, "real_estate": 1000,
                            "alternatives": 1000, "liquidity": 1000},
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
        lambda *_a, resampling_payload=None, **_kw: SimpleNamespace(
            status="optimizer", resampling=resampling_payload,
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
        config=rs.ResamplingConfig(n_bags=n_bags, bag_n_paths=20),
        house_anchor_bps=None, max_iter=1, ftol=1e-6,
        advisory_wealth_rappen=1, cashflow_series_rappen=[],
    )


@pytest.mark.parametrize(
    "n_success, publishes_mean",
    [(40, True), (39, True), (36, True), (35, False), (30, False), (20, False), (19, False)],
)
def test_survivor_threshold_outcomes_for_40_bags(monkeypatch, n_success, publishes_mean):
    result = _run_with_successes(monkeypatch, 40, n_success)
    payload = result.resampling
    assert payload["n_bags_succeeded"] == n_success
    assert payload["min_successful_bag_share"] == pytest.approx(0.9)
    if publishes_mean:
        assert "mean_weights_bps" in payload
        assert "conditional_bag_mean_standard_error_bps" in payload
        assert "standard_error_bps" not in payload
        sensitivity = payload["missingness_sensitivity_bps"]
        if n_success == 40:
            assert all(value == 0.0 for value in sensitivity.values())
    else:
        assert result.status == "fallback_house_matrix"
        assert payload["decision"] == "fallback_house_matrix"
        assert payload["reason"] == "insufficient_successful_bags"
        assert "mean_weights_bps" not in payload


def test_missingness_sensitivity_is_share_times_two_bag_sigmas():
    """f * 2 * sigma_bag: mit 39/40 und einer Bag-Streuung s je Bucket."""
    f = 1 / 40
    sigma_bps = 450.0
    assert round(f * rs.MISSINGNESS_STRESS_SIGMAS * sigma_bps, 2) == 22.5
    assert rs.MIN_SUCCESSFUL_BAG_SHARE * 40 == pytest.approx(36)


# ---------------------------------------------------------------------------
# DRAWDOWN-HOLDOUT-REUSE-001: Rollen der Wuerfel
# ---------------------------------------------------------------------------


def test_selection_and_final_cubes_are_distinct_and_content_seeded():
    context = build_optimizer_context(**_kwargs())
    final = solver_module._build_validation_context(context)
    selection = solver_module._build_selection_validation_context(context)
    assert final[1] == SEED + VALIDATION_SEED_OFFSET
    assert selection[1] == rs._domain_seed("saa-validation-selection-v1", SEED)
    assert selection[1] != final[1]
    assert selection[2] != final[2]
    assert not np.allclose(selection[0].return_paths, final[0].return_paths)
    # deterministisch
    again = solver_module._build_selection_validation_context(context)
    assert again[1] == selection[1] and again[2] == selection[2]
    with pytest.raises(ValueError):
        solver_module._build_validation_context(context, role="unknown")


@pytest.fixture(scope="module")
def drawdown_runs():
    """Drei max_drawdown-Laeufe: Basis, gestoerter Final-Holdout, gestoerter
    Auswahl-Wuerfel (Seed der jeweiligen Rolle um 1 verschoben)."""
    mp = pytest.MonkeyPatch()
    mp.setenv("OPTIMIZER_OBJECTIVE", OBJECTIVE_MAX_DRAWDOWN)
    real = solver_module._validation_seed_for_role
    runs = {}
    try:
        runs["base"] = run_solver(**_kwargs(), resampling=SMALL)
        for role in (solver_module.CUBE_ROLE_FINAL, solver_module.CUBE_ROLE_SELECTION):
            mp.setattr(
                solver_module, "_validation_seed_for_role",
                lambda seed, r, _role=role: real(seed, r) + (1 if r == _role else 0),
            )
            runs[role] = run_solver(**_kwargs(), resampling=SMALL)
            mp.setattr(solver_module, "_validation_seed_for_role", real)
    finally:
        mp.undo()
    return runs


def _dd(result):
    return result.drawdown_certification, result.resampling["significance"]


def test_drawdown_rerank_runs_on_selection_cube_and_test_on_final(drawdown_runs):
    result = drawdown_runs["base"]
    audit, significance = _dd(result)
    assert audit["certified"] is True
    assert audit["cube_role"] == "selection" and audit["selection_free"] is False
    assert significance["cube_role"] == solver_module.CUBE_ROLE_FINAL
    assert audit["validation_cube_hash"] != significance["validation_cube_hash"]
    assert significance["selection_cube_hash"] == audit["validation_cube_hash"]
    # Zielerreichung und Test auf DEMSELBEN finalen Holdout.
    assert result.validation_cube_hash == significance["validation_cube_hash"]
    assert result.validation_seed == SEED + VALIDATION_SEED_OFFSET


def test_changing_the_final_holdout_never_changes_the_frozen_challenger(drawdown_runs):
    base_audit, base_sig = _dd(drawdown_runs["base"])
    moved_audit, moved_sig = _dd(drawdown_runs[solver_module.CUBE_ROLE_FINAL])
    assert moved_audit == base_audit  # Auswahl unberuehrt
    assert moved_sig["candidate_bps"] == base_sig["candidate_bps"]
    assert moved_sig["validation_cube_hash"] != base_sig["validation_cube_hash"]


def test_changing_the_selection_cube_never_changes_the_final_identity(drawdown_runs):
    base = drawdown_runs["base"]
    moved = drawdown_runs[solver_module.CUBE_ROLE_SELECTION]
    _base_audit, base_sig = _dd(base)
    moved_audit, moved_sig = _dd(moved)
    assert moved_audit["validation_cube_hash"] != _base_audit["validation_cube_hash"]
    assert moved_sig["validation_cube_hash"] == base_sig["validation_cube_hash"]
    assert moved.validation_cube_hash == base.validation_cube_hash


def test_single_cube_rerank_also_uses_the_selection_cube(monkeypatch):
    monkeypatch.setenv("OPTIMIZER_OBJECTIVE", OBJECTIVE_MAX_DRAWDOWN)
    result = run_solver(**_kwargs(), resampling=rs.SINGLE_CUBE)
    if result.status == "fallback_house_matrix":
        pytest.skip("Solver-Fallback; keine Finalisten.")
    audit = result.drawdown_certification
    assert audit["cube_role"] == "selection"
    assert audit["validation_seed"] == rs._domain_seed("saa-validation-selection-v1", SEED)
    assert result.validation_seed == SEED + VALIDATION_SEED_OFFSET
    assert result.validation_cube_hash != audit["validation_cube_hash"]


# ---------------------------------------------------------------------------
# HOUSE-PRIOR-PSD-NULLSPACE-001
# ---------------------------------------------------------------------------


def test_ridge_metric_has_eigenvalue_floor_for_singular_and_near_singular_psd():
    singular = np.ones((5, 5)) * 10_000.0
    near = singular + np.diag([1e-9, 0, 0, 0, 0])
    for cov in (singular, near):
        audit = hp.prior_metric_audit(cov)
        assert audit["min_eigenvalue_bps2"] >= hp.HOUSE_PRIOR_RIDGE_BPS2 - 1e-6
        assert audit["condition_number"] is not None


def test_distinct_weights_with_zero_covariance_te_still_have_positive_distance():
    cov = np.ones((5, 5)) * 10_000.0
    house = np.array([0.40, 0.30, 0.10, 0.10, 0.10])
    other = np.array([0.30, 0.40, 0.10, 0.10, 0.10])
    delta = other - house
    assert float(delta @ cov @ delta) == pytest.approx(0.0, abs=1e-12)
    expected_te = np.sqrt(hp.HOUSE_PRIOR_RIDGE_BPS2 / 1e8 * float(delta @ delta)) * 1e4
    assert hp.tracking_error_bps(other, house, cov) == pytest.approx(expected_te)
    assert hp.house_prior_penalty(other, house, cov) == pytest.approx(
        hp.HOUSE_PRIOR_KAPPA * hp.HOUSE_PRIOR_RIDGE_BPS2 / 1e8 * float(delta @ delta)
    )


def test_ridge_changes_typical_asset_class_moves_only_marginally():
    """Ausserhalb des Nullraums: Ridge-Anteil an der TE-Varianz einer
    10-pp-Umschichtung Aktien <-> Obligationen < 2 %, Obligationen <->
    Liquiditaet < 5 % (Produktions-CMA des Testmandats)."""
    context = build_optimizer_context(**_kwargs())
    cov = context.scenario_cov_bps2
    house = np.array([0.60, 0.30, 0.05, 0.03, 0.02])
    order = solver_module.BUCKET_ORDER
    for src, dst, limit in (("equities", "bonds", 0.02), ("bonds", "liquidity", 0.05)):
        move = np.zeros(5)
        move[order.index(src)], move[order.index(dst)] = -0.10, 0.10
        pure = float(move @ np.asarray(cov) @ move) / 1e8
        ridge = hp.HOUSE_PRIOR_RIDGE_BPS2 / 1e8 * float(move @ move)
        assert ridge / pure < limit, (src, dst, ridge / pure)
        assert hp.house_prior_penalty(house + move, house, cov) == pytest.approx(
            hp.HOUSE_PRIOR_KAPPA * (pure + ridge)
        )


def test_prior_penalty_is_continuous_under_bps_rounding():
    cov = np.ones((5, 5)) * 10_000.0
    house = np.array([0.40, 0.30, 0.10, 0.10, 0.10])
    w = np.array([0.452341, 0.247659, 0.10, 0.10, 0.10])
    rounded = np.round(w * 10_000) / 10_000
    gap = abs(hp.house_prior_penalty(w, house, cov) - hp.house_prior_penalty(rounded, house, cov))
    assert gap < 1e-6


# ---------------------------------------------------------------------------
# OPTIMIZER-POST-SELECTION-CERTIFICATION-001: fail-closed (Varianten)
# ---------------------------------------------------------------------------


def test_variant_significance_without_validation_cube_keeps_house_matrix(monkeypatch):
    context = build_optimizer_context(**_kwargs())
    anchor, _reason = solver_module._project_house_anchor(
        context, solver_module._resolve_house_anchor_bps(None, _house_matrix()),
    )
    candidate = dict(anchor)
    candidate["equities"] += 100
    candidate["bonds"] -= 100
    monkeypatch.setattr(solver_module, "_build_validation_context", lambda _ctx: None)
    block = solver_module._significance_vs_house_anchor(
        context, candidate_bps=candidate, house_anchor_bps=anchor,
        config=rs.ResamplingConfig(n_bootstrap=20),
    )
    assert block["decision"] == "house_matrix"
    assert block["reason"] == "no_validation_cube"


# ---------------------------------------------------------------------------
# HOUSE-PRIOR-DECISION-OBJECTIVE-IDENTITY-001: End-to-End
# ---------------------------------------------------------------------------


def test_result_context_and_objective_are_the_prior_decision_objective(monkeypatch):
    monkeypatch.setenv("OPTIMIZER_OBJECTIVE", OBJECTIVE_GOAL_SHORTFALL)
    result = run_solver(**_kwargs(), resampling=SMALL)
    assert result.resampling["engine_version"] == "saa_resampled_v7"
    prior = result.resampling.get("house_prior")
    assert prior is not None
    assert result.context.house_prior_weights is not None
    evaluation = evaluate_weights(result.context, result.weights_bps)
    assert evaluation.objective_value == pytest.approx(result.objective_value, rel=1e-12)
    assert prior["prior_metric"]["ridge_bps2"] == hp.HOUSE_PRIOR_RIDGE_BPS2
    if prior.get("disclosure"):
        assert prior["cube_role"] == solver_module.CUBE_ROLE_FINAL
        assert prior["disclosure"]["sampling_unit"] == "antithetic_pair"
