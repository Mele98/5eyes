"""Uebernommen 2026-10-18 aus dem Codex-Audit-Reproducer
``docs/audits/reproducers/test_2026_10_18_resampling_estimand_and_pvalue_adversarial.py``
(Branch codex/asset-allocation-stochastic-core) als regulaerer Produkttest;
strict-xfail entfernt, Assertions unveraendert. Gruen ab Engine
``saa_resampled_v7``.

Adversarial contracts for residual resampling inference risks at 570cc71.

Normal execution records two strict expected failures.  Certification:

    pytest -q --runxfail \
      docs/audits/reproducers/test_2026_10_18_resampling_estimand_and_pvalue_adversarial.py

must pass only after failed bags no longer create an undisclosed
success-conditioned estimand and bootstrap tail fractions are either named
honestly or supplied with a calibrated p-value contract.  This file is audit
evidence; it does not modify product code.
"""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest


def test_half_failed_bags_must_not_publish_success_conditioned_optimizer_mean(
    monkeypatch: pytest.MonkeyPatch,
):
    """Exactly 50% successful bags currently pass as a normal estimate.

    The two successful bags are averaged and their standard error is divided
    by ``sqrt(n_success)``; the two failures disappear from the estimand.  If
    convergence is related to difficult scenarios or portfolio regions, this
    is survivor selection, not an unconditional resampled-efficiency
    estimate.  Until a missingness/estimand policy is implemented, any failed
    bag must fail closed rather than publish an optimizer mean as if all bags
    were exchangeable observations.
    """
    from services.optimizer import solver as solver_module
    from services.optimizer.resampling import ResamplingConfig

    success_weights = [
        np.array([0.20, 0.30, 0.20, 0.10, 0.20], dtype=np.float64),
        np.array([0.80, 0.10, 0.05, 0.03, 0.02], dtype=np.float64),
    ]
    selections = iter([
        solver_module._CubeSelection(
            weights=success_weights[0], objective=1.0, total_iters=1,
            n_starts=1, attempt_summaries=[], used_ga_fallback=False,
            accepted_feasible_non_success=False,
            robustification_derisked=False,
        ),
        solver_module._CubeSelection(
            weights=success_weights[1], objective=1.0, total_iters=1,
            n_starts=1, attempt_summaries=[], used_ga_fallback=False,
            accepted_feasible_non_success=False,
            robustification_derisked=False,
        ),
        solver_module._CubeSelection(
            weights=None, objective=float("inf"), total_iters=1,
            n_starts=1, attempt_summaries=[], used_ga_fallback=False,
            accepted_feasible_non_success=False,
            robustification_derisked=False,
        ),
        solver_module._CubeSelection(
            weights=None, objective=float("inf"), total_iters=1,
            n_starts=1, attempt_summaries=[], used_ga_fallback=False,
            accepted_feasible_non_success=False,
            robustification_derisked=False,
        ),
    ])

    context = SimpleNamespace(
        scenario_inputs=object(),
        n_paths=20,
        seed=7,
        scenario_weights=None,
        bounds=[(0.0, 1.0)] * 5,
    )

    monkeypatch.setattr(solver_module, "bag_seeds", lambda _seed, _n: [1, 2, 3, 4])
    monkeypatch.setattr(solver_module, "_bag_context", lambda ctx, **_kw: ctx)
    monkeypatch.setattr(solver_module, "_select_cube_candidate", lambda *_a, **_kw: next(selections))
    monkeypatch.setattr(solver_module, "_weights_to_bps_dict", lambda *_a, **_kw: {})
    monkeypatch.setattr(solver_module, "_project_onto_feasible_set", lambda weights, _ctx: weights)
    monkeypatch.setattr(
        solver_module,
        "_rounded_bps_with_repair",
        lambda *_a, **_kw: {
            "equities": 5000,
            "bonds": 2000,
            "real_estate": 1250,
            "alternatives": 650,
            "liquidity": 1100,
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
    monkeypatch.setattr(solver_module, "_trusted_weights_bps_to_array", lambda _bps: np.zeros(5))
    monkeypatch.setattr(
        solver_module,
        "_finalize_solver_result",
        lambda *_a, resampling_payload=None, **_kw: SimpleNamespace(
            status="optimizer",
            resampling=resampling_payload,
        ),
    )

    # Harness-Ergaenzung bei der Uebernahme (2026-10-18): auf dem
    # Review-Head wurde der Fallback-Zweig nie erreicht, deshalb fehlte sein
    # Mock. Der echte Fallback braucht einen vollstaendigen OptimizerContext
    # (Vermoegenssimulation); hier zaehlt nur, DASS fail-closed wird und mit
    # welchem Payload. Die Assertions unten sind unveraendert.
    monkeypatch.setattr(
        solver_module,
        "_house_midpoint_fallback_result",
        lambda _ctx, _sel, *, extra_reasoning=None, resampling_payload=None: (
            SimpleNamespace(
                status="fallback_house_matrix",
                resampling=resampling_payload,
            )
        ),
    )

    result = solver_module._run_resampled_solver(
        context,
        config=ResamplingConfig(n_bags=4, bag_n_paths=20),
        house_anchor_bps=None,
        max_iter=1,
        ftol=1e-6,
        advisory_wealth_rappen=1,
        cashflow_series_rappen=[],
    )

    assert result.resampling["n_bags_succeeded"] == 2
    assert result.resampling["decision"] == "fallback_house_matrix"
    assert "mean_weights_bps" not in result.resampling


def test_bootstrap_tail_fraction_must_not_be_unqualified_p_value():
    """A raw bootstrap sign fraction needs honest naming or calibration.

    The implementation resamples around the observed empirical distribution
    and reports ``(1 + count(delta <= 0)) / (B + 1)`` as ``p_value``.  A
    customer- or model-governance-facing p-value additionally needs an
    explicit null hypothesis, calibration method and sampling unit.  A raw
    stability/tail fraction is acceptable when named as such.
    """
    from services.optimizer.resampling import paired_bootstrap_improvement

    effects = np.linspace(0.01, 0.20, 40)

    def loss_pair(indices):
        sample = effects if indices is None else effects[indices]
        return float(np.mean(sample)), 0.0

    result = paired_bootstrap_improvement(
        loss_pair,
        n_paths=len(effects),
        n_bootstrap=100,
        alpha=0.05,
        seed=19,
    )

    if result.get("p_value") is not None:
        assert result.get("null_hypothesis")
        assert result.get("p_value_calibration")
        assert result.get("sampling_unit")
    else:
        assert result.get("bootstrap_tail_fraction") is not None
