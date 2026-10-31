"""Uebernommen 2026-10-18 aus dem Codex-Audit-Reproducer
``docs/audits/reproducers/test_2026_10_18_house_prior_v6_adversarial.py``
(Branch codex/asset-allocation-stochastic-core) als regulaerer Produkttest;
strict-xfail entfernt, Assertions unveraendert. Gruen ab Engine
``saa_resampled_v7``.

Adversarial contracts for HOUSE-PRIOR-001 at feature head f725c3b.

Normal execution records four strict expected failures.  Certification:

    pytest -q --runxfail \
      docs/audits/reproducers/test_2026_10_18_house_prior_v6_adversarial.py

must pass only after the house prior has a positive-definite policy distance,
the canonical result binds the objective that selected it, and validation
failure is fail-closed.  This file is audit evidence, not product code.
"""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest


def test_distinct_feasible_weights_must_not_have_zero_house_prior_distance():
    """A PSD covariance can leave the claimed weight prior with a nullspace.

    The production context validates shape and finiteness, not strict positive
    definiteness.  With perfectly correlated equal-volatility sleeves, every
    fully-invested redistribution has zero tracking error because its weight
    delta sums to zero.  The documented claims "strongly convex", "unique
    minimum" and "Gaussian prior on weights" therefore do not hold.  A true
    policy anchor needs a positive-definite weight-space ridge/metric, or the
    feature must be described narrowly as a risk-space tracking-error prior.
    """
    from services.optimizer.house_prior import (
        house_prior_penalty,
        tracking_error_bps,
    )

    house = np.array([0.40, 0.30, 0.10, 0.10, 0.10], dtype=np.float64)
    candidate = np.array([0.50, 0.20, 0.10, 0.10, 0.10], dtype=np.float64)
    covariance_bps2 = np.ones((5, 5), dtype=np.float64) * 10_000.0

    assert not np.array_equal(candidate, house)
    assert house_prior_penalty(candidate, house, covariance_bps2) > 0.0
    assert tracking_error_bps(candidate, house, covariance_bps2) > 0.0


def test_house_prior_validation_failure_must_publish_anchor_not_candidate(
    monkeypatch: pytest.MonkeyPatch,
):
    """The safety net is unavailable when validation construction fails.

    The current feature returns ``decision=house_prior`` and publishes the
    candidate with reason ``no_validation_cube``.  Missing certification must
    instead block or conservatively publish the projected house anchor.
    """
    from services.optimizer import solver as solver_module
    from services.optimizer.resampling import ResamplingConfig

    anchor = {
        "equities": 4000,
        "bonds": 3000,
        "real_estate": 1000,
        "alternatives": 1000,
        "liquidity": 1000,
    }
    candidate = {
        "equities": 5000,
        "bonds": 2000,
        "real_estate": 1000,
        "alternatives": 1000,
        "liquidity": 1000,
    }
    context = SimpleNamespace(
        house_prior_weights=np.array(list(anchor.values()), dtype=np.float64) / 10_000.0,
        house_prior_kappa=300.0,
        scenario_cov_bps2=np.eye(5, dtype=np.float64) * 10_000.0,
    )
    monkeypatch.setattr(solver_module, "_build_validation_context", lambda _ctx: None)

    block = solver_module._house_prior_disclosure(
        context,
        candidate_bps=candidate,
        house_anchor_bps=anchor,
        anchor_projected_bps=anchor,
        config=ResamplingConfig(n_bootstrap=20, significance_test=True),
    )

    assert block["reason"] == "no_validation_cube"
    assert block["final_bps"] == anchor
    assert block["decision"] != "house_prior"


def test_canonical_result_context_must_bind_the_objective_used_for_selection(
    monkeypatch: pytest.MonkeyPatch,
):
    """The feature optimizes the prior context but finalizes the caller context.

    Consequently ``result.objective_value`` reproduces the old external
    objective, not ``G + preference + house_prior`` that selected the bags.
    Keeping the old context object is useful for compatibility, but it cannot
    remain the sole canonical decision objective.  Persist either the actual
    prior context/contract or explicit decision-objective components and hash.
    """
    from services.optimizer import solver as solver_module
    from services.optimizer.resampling import ResamplingConfig

    anchor = {
        "equities": 4000,
        "bonds": 3000,
        "real_estate": 1000,
        "alternatives": 1000,
        "liquidity": 1000,
    }
    candidate = {
        "equities": 4500,
        "bonds": 2500,
        "real_estate": 1000,
        "alternatives": 1000,
        "liquidity": 1000,
    }
    caller = SimpleNamespace(
        scenario_inputs=object(),
        n_paths=20,
        seed=7,
        scenario_weights=None,
        bounds=[(0.0, 1.0)] * 5,
        house_prior_weights=None,
    )
    prior = SimpleNamespace(**vars(caller))
    prior.house_prior_weights = np.array(list(anchor.values()), dtype=np.float64) / 10_000.0
    prior.house_prior_kappa = 300.0

    selection = solver_module._CubeSelection(
        weights=np.array(list(candidate.values()), dtype=np.float64) / 10_000.0,
        objective=1.0,
        total_iters=1,
        n_starts=1,
        attempt_summaries=[],
        used_ga_fallback=False,
        accepted_feasible_non_success=False,
        robustification_derisked=False,
    )
    captured = {}

    monkeypatch.setattr(
        solver_module,
        "objective_contract_of",
        lambda _ctx: SimpleNamespace(objective_mode="goal_shortfall"),
    )
    monkeypatch.setattr(solver_module, "_project_house_anchor", lambda *_a, **_kw: (anchor, None))
    monkeypatch.setattr(solver_module, "_with_house_prior", lambda *_a, **_kw: prior)
    monkeypatch.setattr(solver_module, "bag_seeds", lambda *_a, **_kw: [1, 2])
    monkeypatch.setattr(solver_module, "_bag_context", lambda ctx, **_kw: ctx)
    monkeypatch.setattr(solver_module, "_select_cube_candidate", lambda *_a, **_kw: selection)
    monkeypatch.setattr(solver_module, "_weights_to_bps_dict", lambda *_a, **_kw: candidate)
    monkeypatch.setattr(solver_module, "_project_onto_feasible_set", lambda weights, _ctx: weights)
    monkeypatch.setattr(solver_module, "_rounded_bps_with_repair", lambda *_a, **_kw: candidate)
    monkeypatch.setattr(
        solver_module,
        "_house_prior_disclosure",
        lambda *_a, **_kw: {
            "decision": "house_prior",
            "reason": "audit",
            "final_bps": candidate,
        },
    )
    monkeypatch.setattr(solver_module, "_trusted_weights_bps_to_array", lambda _bps: np.zeros(5))

    def finalize(context, *_args, resampling_payload=None, **_kwargs):
        captured["context"] = context
        return SimpleNamespace(context=context, resampling=resampling_payload)

    monkeypatch.setattr(solver_module, "_finalize_solver_result", finalize)

    result = solver_module._run_resampled_solver(
        caller,
        config=ResamplingConfig(n_bags=2, bag_n_paths=20),
        house_anchor_bps=anchor,
        max_iter=1,
        ftol=1e-6,
        advisory_wealth_rappen=1,
        cashflow_series_rappen=[],
    )

    assert captured["context"] is prior
    assert result.context.house_prior_weights is not None


def test_house_prior_disclosure_tail_fraction_needs_calibrated_pvalue_contract():
    """The v6 disclosure repeats the unqualified bootstrap p-value claim."""
    from services.optimizer.house_prior import paired_bootstrap_disclosure

    effects = np.linspace(0.01, 0.20, 40)

    def loss_pair(indices):
        sample = effects if indices is None else effects[indices]
        return float(np.mean(sample)), 0.0

    result = paired_bootstrap_disclosure(
        loss_pair,
        n_paths=len(effects),
        n_bootstrap=100,
        alpha=0.05,
        seed=23,
    )

    for key in ("p_value_better", "p_value_worse"):
        if result.get(key) is not None:
            assert result.get("null_hypothesis")
            assert result.get("p_value_calibration")
            assert result.get("sampling_unit")
