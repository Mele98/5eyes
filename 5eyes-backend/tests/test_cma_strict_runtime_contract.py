"""Strict CMA ingestion contracts shared by reporting and the optimizer.

An absent optional JSON payload keeps the documented default assumptions.
Once a payload is present, however, it is model input: malformed/non-finite
content must fail closed instead of silently selecting another model.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import pytest
from pydantic import ValidationError

from schemas.allocation import CapitalMarketAssumptionCreate


def _identity() -> list[list[float]]:
    return [[1.0 if i == j else 0.0 for j in range(5)] for i in range(5)]


def _cma(**overrides):
    values = {
        "equity_ch_return_bps": 500,
        "equity_intl_return_bps": 500,
        "equity_ch_vol_bps": 1200,
        "equity_intl_vol_bps": 1200,
        "bonds_chf_ig_return_bps": 200,
        "bonds_fx_hedged_return_bps": 200,
        "bonds_chf_ig_vol_bps": 400,
        "bonds_fx_hedged_vol_bps": 400,
        "real_estate_ch_return_bps": 350,
        "real_estate_ch_vol_bps": 700,
        "alternatives_gold_return_bps": 120,
        "alternatives_gold_vol_bps": 950,
        "liquidity_return_bps": 80,
        "liquidity_vol_bps": 20,
        "correlation_matrix_json": "",
        "sub_asset_class_assumptions_json": "",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _non_psd_correlation() -> list[list[float]]:
    matrix = _identity()
    matrix[0][1] = matrix[1][0] = 0.9
    matrix[0][2] = matrix[2][0] = 0.9
    matrix[1][2] = matrix[2][1] = -0.9
    return matrix


def test_schema_rejects_non_psd_correlation_matrix():
    with pytest.raises(ValidationError, match="positiv semidefinit"):
        CapitalMarketAssumptionCreate(
            valid_from="2026-01-01",
            correlation_matrix_json=json.dumps(_non_psd_correlation()),
        )


def test_schema_rejects_non_finite_correlation_value():
    matrix = _identity()
    matrix[0][1] = matrix[1][0] = float("nan")
    with pytest.raises(ValidationError, match="non-finite|endlich"):
        CapitalMarketAssumptionCreate(
            valid_from="2026-01-01",
            correlation_matrix_json=json.dumps(matrix),
        )


def test_runtime_correlation_parser_rejects_malformed_json():
    from services.cma_validation import CMAValidationError
    from services.portfolio_engine_cma import _build_cholesky_from_cma

    with pytest.raises(CMAValidationError, match="valid JSON"):
        _build_cholesky_from_cma(_cma(correlation_matrix_json="{broken"))


def test_runtime_correlation_parser_rejects_non_psd_matrix():
    from services.cma_validation import CMAValidationError
    from services.portfolio_engine_cma import _build_cholesky_from_cma

    with pytest.raises(CMAValidationError, match="positiv semidefinit"):
        _build_cholesky_from_cma(
            _cma(correlation_matrix_json=json.dumps(_non_psd_correlation()))
        )


def test_optimizer_wraps_invalid_correlation_as_domain_error():
    from services.optimizer.constraints import OptimizerInputError
    from services.optimizer.scenario_engine import scenario_inputs_from_cma

    with pytest.raises(OptimizerInputError, match="correlation_matrix_json"):
        scenario_inputs_from_cma(_cma(correlation_matrix_json="{broken"))


def test_optimizer_does_not_replace_non_psd_correlation_with_identity():
    from services.optimizer.constraints import OptimizerInputError
    from services.optimizer.scenario_engine import scenario_inputs_from_cma

    with pytest.raises(OptimizerInputError, match="positiv semidefinit"):
        scenario_inputs_from_cma(
            _cma(correlation_matrix_json=json.dumps(_non_psd_correlation()))
        )


@pytest.mark.parametrize(
    "advanced_fields, error_fragment",
    [
        (
            {
                "bonds_ns_beta0_bps": 400,
                "bonds_ns_beta1_bps": -150,
                "bonds_ns_beta2_bps": 50,
                "bonds_ns_lambda_x100": 0,
            },
            "bonds_ns_lambda_x100",
        ),
        (
            {
                "bonds_ns_beta0_bps": -10_000,
                "bonds_ns_beta1_bps": 0,
                "bonds_ns_beta2_bps": 0,
                "bonds_ns_lambda_x100": 60,
            },
            "bonds_ns_short_rate_bps",
        ),
        (
            {
                "equity_kgv_current_x10": 0,
                "equity_kgv_fair_x10": 170,
                "equity_kgv_alpha_x100": 15,
            },
            "equity_kgv_current_x10",
        ),
        (
            {
                "equity_kgv_current_x10": 220,
                "equity_kgv_fair_x10": 170,
                "equity_kgv_alpha_x100": 101,
            },
            "equity_kgv_alpha_x100",
        ),
        (
            {
                "equity_kgv_current_x10": True,
                "equity_kgv_fair_x10": 170,
                "equity_kgv_alpha_x100": 15,
            },
            "numerisch skaliert",
        ),
    ],
)
def test_schema_rejects_complete_invalid_advanced_cma_group(
    advanced_fields,
    error_fragment,
):
    with pytest.raises(ValidationError, match=error_fragment):
        CapitalMarketAssumptionCreate(
            valid_from="2026-01-01",
            **advanced_fields,
        )


def test_schema_keeps_partial_advanced_cma_groups_inactive():
    model = CapitalMarketAssumptionCreate(
        valid_from="2026-01-01",
        bonds_ns_beta0_bps=400,
        bonds_ns_lambda_x100=0,
        equity_kgv_current_x10=0,
        equity_kgv_fair_x10=170,
    )
    assert model.bonds_ns_lambda_x100 == 0
    assert model.equity_kgv_current_x10 == 0


@pytest.mark.parametrize("alpha_x100", [0, 100])
def test_schema_accepts_inclusive_kgv_alpha_scaled_boundaries(alpha_x100):
    model = CapitalMarketAssumptionCreate(
        valid_from="2026-01-01",
        equity_kgv_current_x10=220,
        equity_kgv_fair_x10=170,
        equity_kgv_alpha_x100=alpha_x100,
    )
    assert model.equity_kgv_alpha_x100 == alpha_x100


def test_raw_runtime_rejects_complete_invalid_ns_as_cma_domain_error():
    from services.cma_validation import CMAValidationError
    from services.optimizer.scenario_engine import (
        _compute_bonds_return_from_nelson_siegel,
    )

    with pytest.raises(CMAValidationError, match="bonds_ns_lambda_x100"):
        _compute_bonds_return_from_nelson_siegel(
            _cma(
                bonds_ns_beta0_bps=400,
                bonds_ns_beta1_bps=-150,
                bonds_ns_beta2_bps=50,
                bonds_ns_lambda_x100=0,
            )
        )


def test_raw_runtime_rejects_complete_invalid_kgv_as_cma_domain_error():
    from services.cma_validation import CMAValidationError
    from services.optimizer.scenario_engine import _compute_equity_kgv_adjustment

    with pytest.raises(CMAValidationError, match="equity_kgv_alpha_x100"):
        _compute_equity_kgv_adjustment(
            _cma(
                equity_kgv_current_x10=220,
                equity_kgv_fair_x10=170,
                equity_kgv_alpha_x100=float("nan"),
            )
        )


@pytest.mark.parametrize(
    "advanced_fields, error_fragment",
    [
        (
            {
                "bonds_ns_beta0_bps": 400,
                "bonds_ns_beta1_bps": -150,
                "bonds_ns_beta2_bps": 50,
                "bonds_ns_lambda_x100": 0,
            },
            "bonds_ns_lambda_x100",
        ),
        (
            {
                "equity_kgv_current_x10": 220,
                "equity_kgv_fair_x10": 170,
                "equity_kgv_alpha_x100": 101,
            },
            "equity_kgv_alpha_x100",
        ),
    ],
)
def test_reporting_runtime_does_not_replace_invalid_advanced_cma_with_fixed(
    advanced_fields,
    error_fragment,
):
    from services.cma_validation import CMAValidationError
    from services.portfolio_engine_cma import _asset_class_expected_metrics

    with pytest.raises(CMAValidationError, match=error_fragment):
        _asset_class_expected_metrics(_cma(**advanced_fields))


def test_positive_semidefinite_singular_correlation_is_used_not_replaced():
    from services.portfolio_engine_cma import _build_cholesky_from_cma

    singular_psd = [[1.0] * 5 for _ in range(5)]
    factor = np.asarray(
        _build_cholesky_from_cma(
            _cma(correlation_matrix_json=json.dumps(singular_psd))
        )
    )
    np.testing.assert_allclose(factor @ factor.T, singular_psd, atol=1e-10)


def test_absent_correlation_uses_same_canonical_default_in_both_engines():
    from services.optimizer.scenario_engine import (
        build_default_correlation_matrix,
        scenario_inputs_from_cma,
    )
    from services.portfolio_engine_cma import _build_cholesky_from_cma

    expected = build_default_correlation_matrix()
    reporting_factor = np.asarray(_build_cholesky_from_cma(_cma()))
    optimizer_factor = scenario_inputs_from_cma(_cma()).cholesky
    np.testing.assert_allclose(
        reporting_factor @ reporting_factor.T,
        expected,
        atol=1e-12,
    )
    np.testing.assert_allclose(
        optimizer_factor @ optimizer_factor.T,
        expected,
        atol=1e-12,
    )


@pytest.mark.parametrize(
    "payload, error_fragment",
    [
        ("{broken", "valid JSON"),
        (json.dumps([]), "JSON object"),
        (
            json.dumps({"Aktien Schweiz": {"expected_return_bps": -10_000}}),
            "greater than -100%",
        ),
        (
            json.dumps({"Aktien Schweiz": {"expected_volatility_bps": -1}}),
            "non-negative",
        ),
        (
            json.dumps({"Aktien Schweiz": {"expected_volatility_bps": float("nan")}}),
            "finite",
        ),
        (
            json.dumps({"Aktien Schweiz": {"expected_return_bps": True}}),
            "integer",
        ),
        (
            json.dumps({"Aktien Schweiz": {"expected_retrun_bps": 650}}),
            "unknown fields",
        ),
    ],
)
def test_schema_rejects_invalid_sub_cma_payload(payload, error_fragment):
    with pytest.raises(ValidationError, match=error_fragment):
        CapitalMarketAssumptionCreate(
            valid_from="2026-01-01",
            sub_asset_class_assumptions_json=payload,
        )


def test_sub_cma_explicit_zero_is_preserved_instead_of_defaulted():
    from services.portfolio_engine_cma import _sub_asset_class_assumption_map

    assumptions = _sub_asset_class_assumption_map(
        _cma(
            sub_asset_class_assumptions_json=json.dumps(
                {
                    "Aktien Schweiz": {
                        "asset_class": "Aktien",
                        "expected_return_bps": 0,
                        "expected_volatility_bps": 0,
                    }
                }
            )
        )
    )
    assert assumptions["Aktien Schweiz"]["expected_return_bps"] == 0
    assert assumptions["Aktien Schweiz"]["expected_volatility_bps"] == 0


def test_schema_accepts_complete_jurisdiction_specific_sub_cma_label():
    model = CapitalMarketAssumptionCreate(
        valid_from="2026-01-01",
        sub_asset_class_assumptions_json=json.dumps({
            "Aktien Deutschland": {
                "asset_class": "Aktien",
                "expected_return_bps": 650,
                "expected_volatility_bps": 1500,
            },
        }),
    )
    assert "Aktien Deutschland" in model.sub_asset_class_assumptions_json


def test_runtime_rejects_configured_sub_cma_label_outside_active_universe():
    from services.portfolio_engine_cma import _validate_sub_cma_universe

    cma = _cma(
        sub_asset_class_assumptions_json=json.dumps({
            "Aktien Schwiez": {
                "asset_class": "Aktien",
                "expected_return_bps": 650,
                "expected_volatility_bps": 1450,
            },
        })
    )
    with pytest.raises(ValueError, match="not referenced.*Aktien Schwiez"):
        _validate_sub_cma_universe(cma, {"Aktien Schweiz"})


def test_historical_partial_known_sub_cma_inherits_only_missing_fields():
    """Existing partial admin rows remain usable without treating 0 as absent."""
    from services.portfolio_engine_cma import _sub_asset_class_assumption_map

    assumptions = _sub_asset_class_assumption_map(
        _cma(
            sub_asset_class_assumptions_json=json.dumps(
                {"Aktien Schweiz": {"expected_return_bps": 650}}
            )
        )
    )
    assert assumptions["Aktien Schweiz"] == {
        "asset_class": "Aktien",
        "expected_return_bps": 650,
        "expected_volatility_bps": 1450,
    }


def test_runtime_sub_cma_malformed_json_is_domain_error_even_without_sleeves():
    from services.cma_validation import CMAValidationError
    from services.portfolio_engine_cma import _weighted_bucket_metrics

    with pytest.raises(CMAValidationError, match="valid JSON"):
        _weighted_bucket_metrics(
            _cma(sub_asset_class_assumptions_json="{broken"),
            sub_allocations=None,
        )


def test_optimizer_wraps_invalid_sub_cma_as_domain_error():
    from services.optimizer.constraints import OptimizerInputError
    from services.optimizer.scenario_engine import scenario_inputs_from_cma

    with pytest.raises(OptimizerInputError, match="sub_asset_class_assumptions_json"):
        scenario_inputs_from_cma(
            _cma(sub_asset_class_assumptions_json="{broken"),
            sub_allocations=[
                {
                    "asset_class": "Aktien",
                    "sub_asset_class": "Aktien Schweiz",
                    "target_weight_bps": 10_000,
                }
            ],
        )


def test_expected_metrics_keep_negative_net_return_signed():
    from services.portfolio_engine_cma import _expected_metrics

    cma = _cma(
        equity_ch_return_bps=-100,
        equity_intl_return_bps=-100,
        liquidity_return_bps=0,
    )
    metrics = _expected_metrics(
        {
            "equities": 10_000,
            "bonds": 0,
            "real_estate": 0,
            "alternatives": 0,
            "liquidity": 0,
        },
        cma,
        products=[{"target_weight_bps": 10_000, "ter_bps": 50}],
    )
    assert metrics["expected_return_gross_bps"] == -100
    assert metrics["expected_return_bps"] == -150
    assert metrics["risk_free_bps"] == 0
    assert metrics["sharpe_ratio_x100"] < 0
