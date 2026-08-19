"""Strict mandate-bound and immutable optimizer-context regression tests."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from scipy.optimize import OptimizeResult

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.optimizer.constraints import (  # noqa: E402
    OptimizerInputError,
    bands_from_effective_bounds_bps,
    build_bounds,
    build_constraint_set,
    is_feasible,
)
from services.optimizer.scenario_engine import BUCKET_ORDER  # noqa: E402
import services.optimizer.solver as solver_module  # noqa: E402
from services.optimizer.solver import build_optimizer_context, run_solver  # noqa: E402


def _cma(**overrides):
    values = {
        "id": "cma-effective-context",
        "bonds_chf_ig_return_bps": 220,
        "bonds_chf_ig_vol_bps": 350,
        "bonds_fx_hedged_return_bps": 240,
        "bonds_fx_hedged_vol_bps": 430,
        "equity_ch_return_bps": 620,
        "equity_ch_vol_bps": 1450,
        "equity_intl_return_bps": 700,
        "equity_intl_vol_bps": 1600,
        "real_estate_ch_return_bps": 450,
        "real_estate_ch_vol_bps": 820,
        "alternatives_gold_return_bps": 300,
        "alternatives_gold_vol_bps": 1200,
        "liquidity_return_bps": 80,
        "liquidity_vol_bps": 20,
        "correlation_matrix_json": "",
        "sub_asset_class_assumptions_json": "",
        "equities_skewness_bps": 0,
        "equities_excess_kurt_bps": 0,
        "bonds_skewness_bps": 0,
        "bonds_excess_kurt_bps": 0,
        "real_estate_skewness_bps": 0,
        "real_estate_excess_kurt_bps": 0,
        "alternatives_skewness_bps": 0,
        "alternatives_excess_kurt_bps": 0,
        "liquidity_skewness_bps": 0,
        "liquidity_excess_kurt_bps": 0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _house_matrix(**overrides):
    values = {
        "profile_name": "Test",
        "equity_min_bps": 1000,
        "equity_max_bps": 7000,
        "equity_target_bps": 3000,
        "bonds_min_bps": 1000,
        "bonds_max_bps": 8000,
        "bonds_target_bps": 5000,
        "real_estate_min_bps": 0,
        "real_estate_max_bps": 2000,
        "real_estate_target_bps": 500,
        "alt_min_bps": 0,
        "alt_max_bps": 1000,
        "alt_target_bps": 500,
        "liq_min_bps": 200,
        "liq_max_bps": 4000,
        "liq_target_bps": 1000,
        "max_risky_fraction_bps": 10000,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _effective_bounds(**overrides):
    bounds = {
        "equities": (1000, 2000),
        "bonds": (4000, 7000),
        "real_estate": (0, 1000),
        "alternatives": (0, 500),
        "liquidity": (1000, 3000),
    }
    bounds.update(overrides)
    return bounds


def _context_kwargs(**overrides):
    values = {
        "cma": _cma(),
        "goals": [],
        "house_matrix_row": _house_matrix(),
        "score_x10": 100,
        "advisory_wealth_rappen": 1_000_000_00,
        "cashflow_series_rappen": [0, 0],
        "horizon_years": 2,
        "n_paths": 40,
        "seed": 1234,
    }
    values.update(overrides)
    return values


def test_strict_effective_bounds_are_used_instead_of_house_matrix():
    context = build_optimizer_context(
        **_context_kwargs(effective_bounds_bps=_effective_bounds())
    )

    assert context.bounds == [
        (0.10, 0.20),
        (0.40, 0.70),
        (0.0, 0.10),
        (0.0, 0.05),
        (0.10, 0.30),
    ]
    assert context.bounds_collapse_warnings == ()


@pytest.mark.parametrize(
    "override, message_fragment",
    [
        ({"real_estate": (0, 4000)}, "real_estate maximum"),
        ({"alternatives": (0, 3000)}, "alternatives maximum"),
        ({"liquidity": (0, 3000)}, "liquidity minimum"),
    ],
)
def test_strict_bounds_reject_non_final_global_guardrails(
    override,
    message_fragment,
):
    with pytest.raises(OptimizerInputError, match=message_fragment):
        bands_from_effective_bounds_bps(_effective_bounds(**override))


@pytest.mark.parametrize(
    "bounds, message_fragment",
    [
        (
            {key: value for key, value in _effective_bounds().items() if key != "bonds"},
            "missing",
        ),
        (_effective_bounds(equities=(1000.0, 2000)), "integer basis points"),
        (_effective_bounds(equities=(-1, 2000)), "0..10000"),
        (_effective_bounds(equities=(3000, 2000)), "min_bps > max_bps"),
        (_effective_bounds(real_estate=(2500, 3000)), "real_estate maximum"),
        (_effective_bounds(alternatives=(1500, 2000)), "alternatives maximum"),
        (_effective_bounds(liquidity=(0, 100)), "liquidity minimum"),
        (
            {
                "equities": (0, 1000),
                "bonds": (0, 6000),
                "real_estate": (0, 1000),
                "alternatives": (0, 500),
                "liquidity": (200, 1000),
            },
            "sum-to-10000",
        ),
        (
            {
                "equities": (5000, 6000),
                "bonds": (4000, 5000),
                "real_estate": (1000, 1500),
                "alternatives": (500, 1000),
                "liquidity": (200, 1000),
            },
            "sum-to-10000",
        ),
    ],
)
def test_strict_effective_bounds_reject_invalid_domain(bounds, message_fragment):
    with pytest.raises(OptimizerInputError, match=message_fragment):
        bands_from_effective_bounds_bps(bounds)


def test_legacy_house_matrix_path_keeps_existing_clamp_behavior():
    context = build_optimizer_context(
        **_context_kwargs(
            house_matrix_row=_house_matrix(
                real_estate_min_bps=2500,
                real_estate_max_bps=3000,
            )
        )
    )

    re_index = BUCKET_ORDER.index("real_estate")
    assert context.bounds[re_index] == (0.20, 0.20)
    assert context.bounds_collapse_warnings


def test_feasibility_rejects_non_finite_or_wrong_shape_weights():
    bands = bands_from_effective_bounds_bps(_effective_bounds())
    bounds, constraints = build_constraint_set(bands, score_x10=100)

    non_finite = np.array([0.2, 0.6, 0.05, np.nan, 0.15])
    feasible, reasons = is_feasible(
        non_finite,
        bounds=bounds,
        constraints=constraints,
    )
    assert feasible is False
    assert any("NaN" in item for item in reasons)

    wrong_shape = np.array([0.2, 0.6, 0.05, 0.15])
    feasible, reasons = is_feasible(
        wrong_shape,
        bounds=bounds,
        constraints=constraints,
    )
    assert feasible is False
    assert any("shape invalid" in item for item in reasons)


def test_context_snapshots_exact_sub_allocations_and_risky_fractions():
    sub_allocations = [
        {
            "asset_class": "Aktien",
            "sub_asset_class": "Aktien Schweiz",
            "target_weight_bps": 700,
            "rationale": "home",
        },
        {
            "asset_class": "Aktien",
            "sub_asset_class": "Aktien Global",
            "target_weight_bps": 300,
            "rationale": "global",
        },
    ]
    risky_fractions = {
        "equities": 0.91,
        "bonds": 0.17,
        "real_estate": 0.44,
        "alternatives": 0.63,
        "liquidity": 0.0,
    }
    context = build_optimizer_context(
        **_context_kwargs(
            effective_bounds_bps=_effective_bounds(),
            sub_allocations=sub_allocations,
            risky_fraction_per_bucket=risky_fractions,
            max_risky_fraction_bps=5000,
        )
    )

    assert isinstance(context.sub_allocations, tuple)
    assert list(context.sub_allocations) == sub_allocations
    assert context.risky_fraction_per_bucket == risky_fractions

    # Caller mutations after context construction must not rewrite the run.
    sub_allocations[0]["target_weight_bps"] = 9999
    risky_fractions["equities"] = 0.01
    assert context.sub_allocations[0]["target_weight_bps"] == 700
    assert context.risky_fraction_per_bucket["equities"] == 0.91

    weights = np.array([0.20, 0.60, 0.05, 0.05, 0.10])
    risky_constraint = next(
        item for item in context.scipy_constraints if item["type"] == "ineq"
    )
    exact_risky_use = 0.50 - (
        0.20 * 0.91
        + 0.60 * 0.17
        + 0.05 * 0.44
        + 0.05 * 0.63
        + 0.10 * 0.0
    )
    assert risky_constraint["fun"](weights) == pytest.approx(exact_risky_use)


def test_run_solver_result_carries_the_actual_context():
    sub_allocations = [
        {
            "asset_class": "Alternative",
            "sub_asset_class": "Gold / Rohstoffe",
            "target_weight_bps": 500,
        }
    ]
    result = run_solver(
        **_context_kwargs(
            effective_bounds_bps=_effective_bounds(),
            sub_allocations=sub_allocations,
        ),
        max_iter=4,
    )

    assert result.context is not None
    assert result.context.bounds[BUCKET_ORDER.index("equities")] == (0.10, 0.20)
    assert list(result.context.sub_allocations) == sub_allocations


def test_fallback_result_also_carries_the_actual_context(monkeypatch):
    def _failed_result(*_args, **_kwargs):
        return OptimizeResult(
            x=np.full(len(BUCKET_ORDER), np.nan),
            fun=float("inf"),
            success=False,
            status=99,
            message="forced failure",
            nit=0,
        )

    monkeypatch.setattr(solver_module, "_solve_single_start", _failed_result)
    monkeypatch.setattr(solver_module, "_solve_via_genetic_algorithm", _failed_result)

    result = run_solver(
        **_context_kwargs(effective_bounds_bps=_effective_bounds()),
        max_iter=1,
    )

    assert result.status == "fallback_house_matrix"
    assert result.context is not None
    assert result.context.bounds[BUCKET_ORDER.index("bonds")] == (0.40, 0.70)


def test_post_round_constraint_violation_cannot_remain_converged(monkeypatch):
    feasible_continuous = np.array([0.20, 0.60, 0.05, 0.05, 0.10])

    def _successful_result(*_args, **_kwargs):
        return OptimizeResult(
            x=feasible_continuous.copy(),
            fun=0.0,
            success=True,
            status=0,
            message="forced success",
            nit=1,
        )

    monkeypatch.setattr(solver_module, "_solve_single_start", _successful_result)
    monkeypatch.setattr(
        solver_module,
        "_weights_to_bps_dict",
        lambda _weights: {
            "equities": 2001,
            "bonds": 5999,
            "real_estate": 500,
            "alternatives": 500,
            "liquidity": 1000,
        },
    )

    result = run_solver(
        **_context_kwargs(effective_bounds_bps=_effective_bounds()),
        max_iter=1,
    )

    assert result.status == "diverged_infeasible"
    assert any("equities above max" in item for item in result.constraint_violations)
    assert result.context is not None
