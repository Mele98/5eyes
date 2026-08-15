"""Strict optimizer-core input and retained-context contracts."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from scipy.optimize import OptimizeResult

from services.optimizer.constraints import OptimizerInputError
import services.optimizer.solver as solver_module
from services.optimizer.solver import (
    _weights_bps_to_array,
    build_optimizer_context,
    run_solver,
)


BUCKETS = ("equities", "bonds", "real_estate", "alternatives", "liquidity")


def _cma(**overrides):
    values = {
        "id": "strict-core-cma",
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


def _house():
    return SimpleNamespace(
        profile_name="Strict Core",
        equity_min_bps=1000,
        equity_max_bps=7000,
        equity_target_bps=3000,
        bonds_min_bps=1000,
        bonds_max_bps=8000,
        bonds_target_bps=5000,
        real_estate_min_bps=0,
        real_estate_max_bps=2000,
        real_estate_target_bps=500,
        alt_min_bps=0,
        alt_max_bps=1000,
        alt_target_bps=500,
        liq_min_bps=200,
        liq_max_bps=4000,
        liq_target_bps=1000,
        max_risky_fraction_bps=10000,
    )


def _effective_bounds(**overrides):
    values = {
        "equities": (1000, 2000),
        "bonds": (4000, 7000),
        "real_estate": (0, 1000),
        "alternatives": (0, 500),
        "liquidity": (1000, 3000),
    }
    values.update(overrides)
    return values


def _context_kwargs(**overrides):
    values = {
        "cma": _cma(),
        "goals": [],
        "house_matrix_row": _house(),
        "score_x10": 100,
        "advisory_wealth_rappen": 100_000_000,
        "cashflow_series_rappen": [0, 0],
        "effective_bounds_bps": _effective_bounds(),
        "horizon_years": 2,
        "n_paths": 20,
        "seed": 99,
    }
    values.update(overrides)
    return values


def _valid_weights_bps():
    return {
        "equities": 2000,
        "bonds": 6000,
        "real_estate": 500,
        "alternatives": 500,
        "liquidity": 1000,
    }


def _valid_risky_map():
    return {
        "equities": 1.0,
        "bonds": 0.2,
        "real_estate": 0.5,
        "alternatives": 0.5,
        "liquidity": 0.0,
    }


def test_external_bps_conversion_requires_exact_10000_sum():
    invalid = _valid_weights_bps()
    invalid["bonds"] -= 1

    with pytest.raises(OptimizerInputError, match="sum exactly to 10000"):
        _weights_bps_to_array(invalid)


def test_external_bps_conversion_requires_exact_bucket_schema():
    invalid = _valid_weights_bps()
    invalid["equity_ch"] = invalid.pop("equities")

    with pytest.raises(OptimizerInputError, match="exactly the optimizer buckets"):
        _weights_bps_to_array(invalid)


@pytest.mark.parametrize(
    "mutator, message_fragment",
    [
        (lambda value: value.pop("bonds"), "missing"),
        (lambda value: value.__setitem__("equities", float("nan")), "finite"),
        (lambda value: value.__setitem__("equities", -0.01), "within 0..1"),
        (lambda value: value.__setitem__("equities", 1.01), "within 0..1"),
    ],
)
def test_exact_risky_map_is_complete_finite_and_bounded_before_scenarios(
    monkeypatch,
    mutator,
    message_fragment,
):
    risky = _valid_risky_map()
    mutator(risky)
    scenario_called = False

    def _unexpected_scenario(*_args, **_kwargs):
        nonlocal scenario_called
        scenario_called = True
        raise AssertionError("scenario generation must not run")

    monkeypatch.setattr(solver_module, "scenario_inputs_from_cma", _unexpected_scenario)
    with pytest.raises(OptimizerInputError, match=message_fragment):
        build_optimizer_context(
            **_context_kwargs(
                risky_fraction_per_bucket=risky,
                max_risky_fraction_bps=7000,
            )
        )
    assert scenario_called is False


def test_structurally_infeasible_risk_cap_fails_before_scenarios(monkeypatch):
    scenario_called = False

    def _unexpected_scenario(*_args, **_kwargs):
        nonlocal scenario_called
        scenario_called = True
        raise AssertionError("scenario generation must not run")

    monkeypatch.setattr(solver_module, "scenario_inputs_from_cma", _unexpected_scenario)
    forced_risky_bounds = {
        "equities": (8000, 8000),
        "bonds": (1000, 1000),
        "real_estate": (0, 0),
        "alternatives": (0, 0),
        "liquidity": (1000, 1000),
    }

    with pytest.raises(OptimizerInputError, match="minimum achievable"):
        build_optimizer_context(
            **_context_kwargs(
                effective_bounds_bps=forced_risky_bounds,
                risky_fraction_per_bucket=_valid_risky_map(),
                max_risky_fraction_bps=5000,
            )
        )
    assert scenario_called is False


def test_context_owns_markowitz_inputs_and_supplied_solve_never_rereads_cma(
    monkeypatch,
):
    context = build_optimizer_context(**_context_kwargs())
    assert context.scenario_mu_bps is not None
    assert context.scenario_cov_bps2 is not None
    assert context.scenario_mu_bps.shape == (5,)
    assert context.scenario_cov_bps2.shape == (5, 5)
    assert context.scenario_mu_bps.flags.writeable is False
    assert context.scenario_cov_bps2.flags.writeable is False

    captured: dict[str, np.ndarray] = {}
    feasible = np.array([0.20, 0.60, 0.05, 0.05, 0.10])

    def _initials(
        _bounds,
        _score_x10,
        *,
        mu_bps=None,
        cov_bps=None,
        risky_fraction_per_bucket=None,
    ):
        captured["mu"] = np.asarray(mu_bps).copy()
        captured["cov"] = np.asarray(cov_bps).copy()
        return [feasible.copy()]

    def _success(*_args, **_kwargs):
        return OptimizeResult(
            x=feasible.copy(),
            fun=0.0,
            success=True,
            status=0,
            message="test",
            nit=1,
        )

    monkeypatch.setattr(solver_module, "build_initial_guesses", _initials)
    monkeypatch.setattr(solver_module, "_solve_single_start", _success)
    monkeypatch.setattr(
        solver_module,
        "scenario_inputs_from_cma",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("supplied context must be the sole scenario/CMA source")
        ),
    )

    result = run_solver(
        **_context_kwargs(cma=SimpleNamespace(id="poisoned-cma")),
        optimizer_context=context,
        max_iter=1,
    )

    assert result.context is context
    np.testing.assert_array_equal(captured["mu"], context.scenario_mu_bps)
    np.testing.assert_array_equal(captured["cov"], context.scenario_cov_bps2)
