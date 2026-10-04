"""Red test for ZERO-CONSTRAINT-SEMANTICS-001 (round 46) -- defense-in-depth
variant inside ``_run_stochastic_optimizer_pass``'s activation-validation
boundary (services/portfolio_engine_optimizer_integration.py, around line 456).

    cap = int(getattr(house_matrix, "max_risky_fraction_bps", 10000) or 10000)

When ``house_matrix.max_risky_fraction_bps`` is explicitly ``0`` (the House
policy that the risky-asset fraction must be fully excluded), the
``0 or 10000`` idiom silently substitutes "no limit" (10000bps) instead of
the correct 0bps cap, because ``0`` is falsy in Python.

This branch is only reached when ``result.context is None`` -- i.e. the
"test double" scenario the surrounding production code explicitly
anticipates in its own comment ("this also protects against future solver
implementations and test doubles"). This test supplies exactly such a
double: a converged solver result with ``context=None`` and an explicit
``risky_fraction_per_bucket`` so the ``elif rf_per_bucket is not None:``
defense-in-depth path runs instead of the ``evaluate_weights`` path.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import services.optimizer.solver as solver_module
import services.portfolio_engine as pe
from services.portfolio_engine_optimizer_integration import (
    _run_stochastic_optimizer_pass,
)


BUCKETS = ("equities", "bonds", "real_estate", "alternatives", "liquidity")
HOUSE_TARGETS = {
    "equities": 4000,
    "bonds": 3000,
    "real_estate": 1000,
    "alternatives": 500,
    "liquidity": 1500,
}
# 100%-equities candidate. Under a max_risky_fraction_bps=0 House policy
# ("risky assets fully excluded") this must be rejected outright.
RISKY_CANDIDATE = {
    "equities": 10_000,
    "bonds": 0,
    "real_estate": 0,
    "alternatives": 0,
    "liquidity": 0,
}


@pytest.mark.xfail(
    strict=True,
    reason=(
        "ZERO-CONSTRAINT-SEMANTICS-001 -- round 46 red test, see audit "
        "2026-10-04-house-matrix-policy-constraint-and-retirement-basis-"
        "integrity-audit.md (not committed in this repo)"
    ),
)
def test_zero_max_risky_fraction_bps_rejects_fully_risky_candidate(monkeypatch):
    """house_matrix.max_risky_fraction_bps=0 must mean 'no risky exposure
    allowed', not be treated as an unset/no-limit sentinel."""
    monkeypatch.setattr(pe, "_OPTIMIZER_N_PATHS_DEFAULT", 8)
    monkeypatch.setattr(
        solver_module,
        "build_optimizer_context",
        lambda **_kwargs: SimpleNamespace(seed=42, n_paths=8),
    )
    # Converged solver result whose ``context`` is None -- the production
    # code's own documented "test double" scenario -- so activation
    # validation must fall back to the rf_per_bucket risky-fraction
    # defense-in-depth check (line ~456) instead of evaluate_weights().
    solver_result = SimpleNamespace(
        weights_bps=dict(RISKY_CANDIDATE),
        objective_value=1.0,
        iterations=1,
        seed=42,
        status="converged",
        method="stochastic",
        constraint_violations=[],
        reasoning=[],
        n_paths=8,
        n_starts_attempted=1,
        robustification={},
        context=None,
    )
    monkeypatch.setattr(solver_module, "run_solver", lambda **_kwargs: solver_result)

    reasoning: list[str] = []
    result = _run_stochastic_optimizer_pass(
        optimizer_mode="stochastic",
        apply_targets=True,
        cma=SimpleNamespace(id="zero-risky-cap-cma"),
        goals=[],
        house_matrix=SimpleNamespace(max_risky_fraction_bps=0),
        assessment=SimpleNamespace(
            final_score_x10=50, final_profile="Ausgewogen", is_overridden=0
        ),
        advisory_wealth_rappen=100_000_00,
        cashflow_projection_series_rappen=[0] * 10,
        inflation_series_bps=[100] * 10,
        targets=dict(HOUSE_TARGETS),
        minimums={bucket: 0 for bucket in BUCKETS},
        maximums={bucket: 10_000 for bucket in BUCKETS},
        reasoning=reasoning,
        risky_fraction_per_bucket={bucket: 1.0 for bucket in BUCKETS},
        effective_bounds_bps=None,
    )

    assert result.status == "fallback_house_matrix", (
        "max_risky_fraction_bps=0 must reject any risky exposure; the "
        "'getattr(...) or 10000' idiom silently treats explicit 0 as "
        "unset (no limit) instead, letting a 100%-equities candidate "
        "stay 'converged'."
    )
    assert result.weights_bps == HOUSE_TARGETS
    assert any(
        violation.startswith("activation_validation:risky_fraction:")
        for violation in result.constraint_violations
    )
