"""Fail-closed contracts at the stochastic/House-Matrix boundary."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

import services.optimizer.solver as solver_module
import services.portfolio_engine as pe
from services.cma_validation import CMAValidationError
from services.optimizer.constraints import OptimizerInputError
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


def _invoke_optimizer_boundary(monkeypatch, raised: BaseException):
    context = SimpleNamespace(seed=42, n_paths=8)
    monkeypatch.setattr(pe, "_OPTIMIZER_N_PATHS_DEFAULT", 8)
    monkeypatch.setattr(
        solver_module,
        "build_optimizer_context",
        lambda **_kwargs: context,
    )

    def _raise_from_solver(**_kwargs):
        raise raised

    monkeypatch.setattr(solver_module, "run_solver", _raise_from_solver)
    reasoning: list[str] = []
    result = _run_stochastic_optimizer_pass(
        optimizer_mode="stochastic",
        apply_targets=True,
        cma=SimpleNamespace(id="strict-boundary-cma"),
        goals=[],
        house_matrix=SimpleNamespace(max_risky_fraction_bps=10_000),
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
        risky_fraction_per_bucket={bucket: 0.5 for bucket in BUCKETS},
        effective_bounds_bps={bucket: (0, 10_000) for bucket in BUCKETS},
    )
    return result, context, reasoning


@pytest.mark.parametrize(
    "raised",
    [
        pytest.param(
            CMAValidationError("invalid CMA"),
            id="cma-domain-error",
        ),
        pytest.param(ValueError("bad model state"), id="value-error"),
        pytest.param(
            OptimizerInputError("bad optimizer input"),
            id="optimizer-input-error",
        ),
        pytest.param(RuntimeError("programming defect"), id="runtime-programming-error"),
    ],
)
def test_nontechnical_solver_errors_are_not_converted_to_house_fallback(
    monkeypatch,
    raised,
):
    with pytest.raises(type(raised), match=str(raised)):
        _invoke_optimizer_boundary(monkeypatch, raised)


@pytest.mark.parametrize(
    "raised",
    [
        pytest.param(
            lambda: solver_module.SolverTechnicalError("solver backend unavailable"),
            id="explicit-solver-technical-error",
        ),
        pytest.param(
            lambda: FloatingPointError("non-finite numerical iterate"),
            id="floating-point-error",
        ),
        pytest.param(
            lambda: np.linalg.LinAlgError("factorization failed"),
            id="linear-algebra-error",
        ),
    ],
)
def test_only_explicit_numerical_solver_errors_use_audited_house_fallback(
    monkeypatch,
    raised,
):
    error = raised()
    result, context, reasoning = _invoke_optimizer_boundary(monkeypatch, error)

    assert result.status == "fallback_house_matrix"
    assert result.method == "fallback_house_matrix"
    assert result.weights_bps == HOUSE_TARGETS
    assert result.context is context
    assert result.constraint_violations == [f"solver_exception:{type(error).__name__}"]
    assert reasoning and type(error).__name__ in reasoning[-1]


@pytest.mark.parametrize(
    "raised",
    [
        pytest.param(RuntimeError("objective defect"), id="runtime-error"),
        pytest.param(ValueError("invalid domain state"), id="value-error"),
        pytest.param(
            CMAValidationError("invalid CMA in objective"),
            id="cma-validation-error",
        ),
    ],
)
def test_slsqp_wrapper_propagates_nontechnical_exceptions(monkeypatch, raised):
    def _raise_from_minimize(*_args, **_kwargs):
        raise raised

    monkeypatch.setattr(solver_module, "minimize", _raise_from_minimize)

    with pytest.raises(type(raised), match=str(raised)):
        solver_module._solve_single_start(
            lambda _weights: 0.0,
            np.full(5, 0.2),
            [(0.0, 1.0)] * 5,
            [],
        )


def test_nonconverged_candidate_recheck_does_not_hide_objective_error():
    result = solver_module.OptimizeResult(
        x=np.full(5, 0.2),
        fun=1.0,
        success=False,
        status=9,
        message="iteration limit reached",
        nit=1,
    )

    def _raise_from_objective(_weights):
        raise RuntimeError("candidate recheck defect")

    with pytest.raises(RuntimeError, match="candidate recheck defect"):
        solver_module._finite_feasible_candidate(
            result,
            _raise_from_objective,
            [(0.0, 1.0)] * 5,
            [],
        )


def test_robustification_does_not_hide_objective_error():
    selected = np.array([0.50, 0.20, 0.10, 0.05, 0.15])

    def _raise_from_objective(_weights):
        raise RuntimeError("robustification defect")

    with pytest.raises(RuntimeError, match="robustification defect"):
        solver_module._derisk_candidate_near_best(
            selected,
            objective_fn=_raise_from_objective,
            objective_value=1.0,
            bounds=[(0.0, 1.0)] * 5,
            constraints=[],
            risky_fraction_per_bucket={
                "equities": 1.0,
                "bonds": 0.25,
                "real_estate": 0.5,
                "alternatives": 0.5,
                "liquidity": 0.0,
            },
        )


def _invoke_activation_evaluation_boundary(monkeypatch, raised: BaseException):
    context = SimpleNamespace(seed=42, n_paths=8)
    monkeypatch.setattr(pe, "_OPTIMIZER_N_PATHS_DEFAULT", 8)
    monkeypatch.setattr(
        solver_module,
        "build_optimizer_context",
        lambda **_kwargs: context,
    )
    solver_result = SimpleNamespace(
        weights_bps=dict(HOUSE_TARGETS),
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
        context=context,
    )
    monkeypatch.setattr(
        solver_module,
        "run_solver",
        lambda **_kwargs: solver_result,
    )

    def _raise_from_evaluation(*_args, **_kwargs):
        raise raised

    monkeypatch.setattr(solver_module, "evaluate_weights", _raise_from_evaluation)
    reasoning: list[str] = []
    result = _run_stochastic_optimizer_pass(
        optimizer_mode="stochastic",
        apply_targets=True,
        cma=SimpleNamespace(id="activation-boundary-cma"),
        goals=[],
        house_matrix=SimpleNamespace(max_risky_fraction_bps=10_000),
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
        risky_fraction_per_bucket={bucket: 0.5 for bucket in BUCKETS},
        effective_bounds_bps={bucket: (0, 10_000) for bucket in BUCKETS},
    )
    return result


@pytest.mark.parametrize(
    "raised",
    [
        pytest.param(RuntimeError("activation defect"), id="runtime-error"),
        pytest.param(ValueError("invalid activation state"), id="value-error"),
        pytest.param(
            CMAValidationError("invalid CMA during activation"),
            id="cma-validation-error",
        ),
    ],
)
def test_activation_evaluation_propagates_nontechnical_exceptions(
    monkeypatch,
    raised,
):
    with pytest.raises(type(raised), match=str(raised)):
        _invoke_activation_evaluation_boundary(monkeypatch, raised)


@pytest.mark.parametrize(
    "raised",
    [
        pytest.param(
            lambda: solver_module.SolverTechnicalError("evaluation unavailable"),
            id="explicit-solver-technical-error",
        ),
        pytest.param(
            lambda: FloatingPointError("non-finite activation evaluation"),
            id="floating-point-error",
        ),
        pytest.param(
            lambda: np.linalg.LinAlgError("activation factorization failed"),
            id="linear-algebra-error",
        ),
    ],
)
def test_activation_evaluation_technical_errors_use_audited_house_fallback(
    monkeypatch,
    raised,
):
    error = raised()
    result = _invoke_activation_evaluation_boundary(monkeypatch, error)

    assert result.status == "fallback_house_matrix"
    assert result.method == "fallback_house_matrix"
    assert result.weights_bps == HOUSE_TARGETS
    assert result.constraint_violations == [
        f"activation_validation:activation_evaluation_error:{type(error).__name__}"
    ]


class _CompleteCMA:
    id = "strict-cache-cma"
    jurisdiction = "CH"
    correlation_matrix_json = ""
    sub_asset_class_assumptions_json = ""
    equity_ch_return_bps = 600
    equity_intl_return_bps = 650
    bonds_chf_ig_return_bps = 200
    bonds_fx_hedged_return_bps = 220
    real_estate_ch_return_bps = 400
    alternatives_gold_return_bps = 150
    liquidity_return_bps = 50
    equity_ch_vol_bps = 1500
    equity_intl_vol_bps = 1600
    bonds_chf_ig_vol_bps = 400
    bonds_fx_hedged_vol_bps = 450
    real_estate_ch_vol_bps = 800
    alternatives_gold_vol_bps = 1200
    liquidity_vol_bps = 20


class _WideHouseMatrix:
    equities_min_bps = 0
    equities_target_bps = 4000
    equities_max_bps = 10_000
    bonds_min_bps = 0
    bonds_target_bps = 3000
    bonds_max_bps = 10_000
    real_estate_min_bps = 0
    real_estate_target_bps = 1000
    real_estate_max_bps = 10_000
    alternatives_min_bps = 0
    alternatives_target_bps = 500
    alternatives_max_bps = 10_000
    liquidity_min_bps = 0
    liquidity_target_bps = 1500
    liquidity_max_bps = 10_000


def test_non_json_suballocation_cannot_alias_plain_cma_scenario_cache_key():
    rows = [
        {
            "asset_class": "Aktien",
            "sub_asset_class": "Aktien Schweiz",
            "within_bucket_weight_bps": 10_000,
            "opaque_runtime_value": object(),
        },
        {
            "asset_class": "Obligationen",
            "sub_asset_class": "Obligationen CHF IG",
            "within_bucket_weight_bps": 10_000,
        },
        {
            "asset_class": "Immobilien",
            "sub_asset_class": "Immobilien Schweiz",
            "within_bucket_weight_bps": 10_000,
        },
        {
            "asset_class": "Alternative",
            "sub_asset_class": "Gold / Rohstoffe",
            "within_bucket_weight_bps": 10_000,
        },
        {
            "asset_class": "Liquiditaet",
            "sub_asset_class": "Geldmarktfonds",
            "within_bucket_weight_bps": 10_000,
        },
    ]

    with pytest.raises(
        OptimizerInputError,
        match="strictly JSON serializable.*scenario-cache identity",
    ):
        solver_module.build_optimizer_context(
            cma=_CompleteCMA(),
            goals=[],
            house_matrix_row=_WideHouseMatrix(),
            score_x10=50,
            advisory_wealth_rappen=100_000_00,
            cashflow_series_rappen=[0] * 2,
            sub_allocations=rows,
            horizon_years=2,
            n_paths=4,
            seed=42,
        )


def test_production_boundary_does_not_silently_disable_incomplete_mortality(
    monkeypatch,
):
    monkeypatch.setattr(pe, "_OPTIMIZER_N_PATHS_DEFAULT", 4)
    mandate = SimpleNamespace(
        use_mortality_simulation=1,
        client_birth_year=1965,
        client_sex=None,
        jurisdiction="CH",
        tax_jurisdiction=None,
        tax_overrides_json=None,
        opened_at="2026-01-01",
        retirement_year=None,
    )
    house = _WideHouseMatrix()
    house.max_risky_fraction_bps = 10_000

    with pytest.raises(OptimizerInputError, match="requires client_birth_year"):
        _run_stochastic_optimizer_pass(
            optimizer_mode="stochastic",
            apply_targets=True,
            cma=_CompleteCMA(),
            goals=[],
            house_matrix=house,
            assessment=SimpleNamespace(
            final_score_x10=50, final_profile="Ausgewogen", is_overridden=0
        ),
            advisory_wealth_rappen=100_000_00,
            cashflow_projection_series_rappen=[0] * 2,
            inflation_series_bps=[100] * 2,
            targets=dict(HOUSE_TARGETS),
            minimums={bucket: 0 for bucket in BUCKETS},
            maximums={bucket: 10_000 for bucket in BUCKETS},
            reasoning=[],
            risky_fraction_per_bucket={bucket: 0.5 for bucket in BUCKETS},
            effective_bounds_bps={
                "equities": (0, 10_000),
                "bonds": (0, 10_000),
                "real_estate": (0, 2_000),
                "alternatives": (0, 1_000),
                "liquidity": (200, 10_000),
            },
            mandate=mandate,
        )


def test_production_boundary_rejects_activated_mortality_outside_ch(
    monkeypatch,
):
    monkeypatch.setattr(pe, "_OPTIMIZER_N_PATHS_DEFAULT", 4)
    mandate = SimpleNamespace(
        use_mortality_simulation=1,
        client_birth_year=1965,
        client_sex="M",
        jurisdiction="DE",
        tax_estimate_in_cashflow_enabled=0,
        tax_jurisdiction=None,
        tax_overrides_json=None,
        opened_at="2026-01-01",
        retirement_year=None,
    )
    house = _WideHouseMatrix()
    house.max_risky_fraction_bps = 10_000

    with pytest.raises(OptimizerInputError, match="requires jurisdiction CH"):
        _run_stochastic_optimizer_pass(
            optimizer_mode="stochastic",
            apply_targets=True,
            cma=_CompleteCMA(),
            goals=[],
            house_matrix=house,
            assessment=SimpleNamespace(
            final_score_x10=50, final_profile="Ausgewogen", is_overridden=0
        ),
            advisory_wealth_rappen=100_000_00,
            cashflow_projection_series_rappen=[0] * 2,
            inflation_series_bps=[100] * 2,
            targets=dict(HOUSE_TARGETS),
            minimums={bucket: 0 for bucket in BUCKETS},
            maximums={bucket: 10_000 for bucket in BUCKETS},
            reasoning=[],
            risky_fraction_per_bucket={bucket: 0.5 for bucket in BUCKETS},
            effective_bounds_bps={bucket: (0, 10_000) for bucket in BUCKETS},
            mandate=mandate,
        )


def test_tax_cashflow_activation_requires_jurisdiction_even_at_zero_wealth():
    from services.wealth_cashflows import derive_tax_cashflow

    mandate = SimpleNamespace(
        id="tax-zero-wealth",
        client_id="client",
        base_currency="CHF",
        tax_estimate_in_cashflow_enabled=1,
        tax_jurisdiction=None,
        tax_overrides_json=None,
        opened_at="2026-01-01",
        client_birth_year=None,
        retirement_year=None,
    )

    with pytest.raises(OptimizerInputError, match="Steuerbasis"):
        derive_tax_cashflow(mandate, 0)
