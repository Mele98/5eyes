"""Uebernommen 2026-10-18 aus dem Codex-Audit-Reproducer
``docs/audits/reproducers/test_2026_10_18_resampling_drawdown_validation_adversarial.py``
(Branch codex/asset-allocation-stochastic-core) als regulaerer Produkttest;
strict-xfail entfernt, Assertions unveraendert. Gruen ab Engine
``saa_resampled_v7``.

Adversarial contracts for the resampling/drawdown stack at PR #631.

Reviewed immutable product head:

    0ed08b5482a2fabd6ca4e10da355f6b7530a5ef1

Normal execution records two strict expected failures without making the
documentation branch red.  The certification execution

    pytest -q --runxfail \
      docs/audits/reproducers/test_2026_10_18_resampling_drawdown_validation_adversarial.py

must fail on the reviewed head and may turn green only when both statistical
contracts are closed.  This file is audit evidence, not product code.
"""
from __future__ import annotations

import ast
import inspect
import textwrap

import numpy as np
import pytest


def test_antithetic_validation_paths_must_be_bootstrapped_as_pairs():
    """Antithetic partners are one sampling unit, not two iid observations.

    ``build_scenario_paths(..., antithetic=True)`` stores base paths in the
    first half and their partners in the second half.  The production
    bootstrap currently samples individual row indices.  This deterministic
    counterexample duplicates each cluster effect across the two partner
    rows: individual-row resampling reports p=0.0374, whereas the correct
    pair/block bootstrap reports p=0.0873.

    Duplicate effects are intentional: nonlinear portfolio-loss differences
    of antithetic return paths need not be negatively correlated.  The test
    isolates the sampling-unit error without depending on solver convergence.
    """
    from services.optimizer.resampling import paired_bootstrap_improvement

    pair_effects = np.random.default_rng(2).normal(0.14, 1.0, 100)
    path_effects = np.concatenate([pair_effects, pair_effects])

    def loss_pair(indices):
        sample = path_effects if indices is None else path_effects[indices]
        return float(np.mean(sample)), 0.0

    current = paired_bootstrap_improvement(
        loss_pair,
        n_paths=200,
        n_bootstrap=400,
        alpha=0.05,
        seed=11,
    )

    # Reference inference: resample the 100 independent antithetic blocks and
    # keep both members of every selected pair together.  In this construction
    # their block mean is exactly ``pair_effects``.
    rng = np.random.default_rng(11)
    block_replicates = np.array([
        np.mean(pair_effects[rng.integers(0, 100, size=100)])
        for _ in range(400)
    ])
    block_p = (1 + np.count_nonzero(block_replicates <= 0.0)) / 401

    assert block_p > 0.05
    assert current["p_value"] >= 0.05
    assert current["significant"] is False


def _validation_argument_names(function) -> dict[str, str | None]:
    """Return validation keyword names for relevant calls in ``function``."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
    targets = {"certify_resampled_candidates", "_significance_vs_house_anchor"}
    found: dict[str, str | None] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        called = (
            node.func.id
            if isinstance(node.func, ast.Name)
            else node.func.attr
            if isinstance(node.func, ast.Attribute)
            else None
        )
        if called not in targets:
            continue
        keyword = next((kw for kw in node.keywords if kw.arg == "validation"), None)
        found[called] = keyword.value.id if keyword and isinstance(keyword.value, ast.Name) else None
    return found


def test_drawdown_challenger_selection_must_not_consume_test_holdout():
    """Candidate selection and final significance require separate cubes.

    The reviewed solver gives one ``validation`` object first to
    ``certify_resampled_candidates``.  That function selects the best
    non-anchor candidate by validated drawdown.  The solver then gives the
    same object to ``_significance_vs_house_anchor``.  A winner selected on a
    sample cannot be tested on that sample as if it were an untouched holdout.
    """
    from services.optimizer import solver as solver_module

    names = _validation_argument_names(solver_module._run_resampled_solver)
    assert set(names) == {
        "certify_resampled_candidates",
        "_significance_vs_house_anchor",
    }
    assert names["certify_resampled_candidates"] != names["_significance_vs_house_anchor"]
