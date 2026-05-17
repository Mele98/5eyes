"""Sprint 6 Phase 2: scenario_inputs_from_cma nutzt Nelson-Siegel-Curve
fuer Bond-Returns wenn alle 4 NS-Params in CMA gesetzt sind.
"""
from __future__ import annotations

import numpy as np
import pytest


class _CMAFixedBonds:
    """CMA mit fixen Bond-Werten (alte Variante)."""
    id = "fixed-bonds"
    bonds_chf_ig_return_bps = 200
    bonds_fx_hedged_return_bps = 250
    bonds_chf_ig_vol_bps = 400
    bonds_fx_hedged_vol_bps = 500
    bonds_hy_return_bps = None
    bonds_hy_vol_bps = None
    equity_ch_return_bps = 600
    equity_ch_vol_bps = 1500
    equity_intl_return_bps = 700
    equity_intl_vol_bps = 1700
    equity_em_return_bps = None
    equity_em_vol_bps = None
    real_estate_ch_return_bps = 400
    real_estate_ch_vol_bps = 800
    alternatives_gold_return_bps = 300
    alternatives_gold_vol_bps = 1200
    liquidity_return_bps = 50
    liquidity_vol_bps = 50
    correlation_matrix_json = ""
    # Sprint 6 Phase 2: keine NS-Params → Fallback auf fix-Werte
    bonds_ns_beta0_bps = None
    bonds_ns_beta1_bps = None
    bonds_ns_beta2_bps = None
    bonds_ns_lambda_x100 = None


class _CMANelsonSiegel(_CMAFixedBonds):
    """CMA mit Nelson-Siegel-Params (neue Variante)."""
    id = "ns-bonds"
    # NS-Curve: beta0=400, beta1=-150, beta2=50, lambda=0.6
    # y(5) = 400 + (-150) * (1-exp(-3))/3 + 50 * ((1-exp(-3))/3 - exp(-3))
    bonds_ns_beta0_bps = 400
    bonds_ns_beta1_bps = -150
    bonds_ns_beta2_bps = 50
    bonds_ns_lambda_x100 = 60  # = 0.6


def test_no_ns_params_uses_fixed_bond_returns():
    """CMA ohne NS-Params → bonds_return = avg(bonds_chf_ig, bonds_fx_hedged)."""
    from services.optimizer.scenario_engine import scenario_inputs_from_cma

    inputs = scenario_inputs_from_cma(_CMAFixedBonds())
    # bonds in BUCKET_ORDER ist Index 1
    bonds_return = inputs.mu_bps[1]
    # _avg_or_zero([200, 250]) = 225
    assert bonds_return == 225.0


def test_ns_params_override_fixed_bond_returns():
    """CMA mit NS-Params → bonds_return = curve.yield_at(5)."""
    from services.optimizer.scenario_engine import scenario_inputs_from_cma
    from services.rates.nelson_siegel import NelsonSiegelCurve

    cma = _CMANelsonSiegel()
    inputs = scenario_inputs_from_cma(cma)

    # Erwarteter Wert: gleicher wie wenn ich direkt rechne
    curve = NelsonSiegelCurve(beta0_bps=400, beta1_bps=-150, beta2_bps=50, lambda_=0.6)
    expected_yield_5y = curve.yield_at(5.0)

    bonds_return = inputs.mu_bps[1]
    assert abs(bonds_return - expected_yield_5y) < 0.01


def test_ns_params_value_realistic_5y_yield():
    """Sanity: ein realistisches 5J-Yield ist im Bereich 200-400 bps."""
    from services.optimizer.scenario_engine import scenario_inputs_from_cma

    inputs = scenario_inputs_from_cma(_CMANelsonSiegel())
    bonds_return = inputs.mu_bps[1]
    assert 100 < bonds_return < 500, f"5J-Yield {bonds_return:.1f} bps unrealistisch"


def test_partial_ns_params_fall_back_to_fixed():
    """Wenn nur 3 von 4 NS-Params gesetzt sind → Fallback auf fix-Werte."""
    from services.optimizer.scenario_engine import scenario_inputs_from_cma

    class _CMAPartial(_CMAFixedBonds):
        bonds_ns_beta0_bps = 400
        bonds_ns_beta1_bps = -150
        bonds_ns_beta2_bps = 50
        bonds_ns_lambda_x100 = None  # FEHLT

    inputs = scenario_inputs_from_cma(_CMAPartial())
    # Fallback: avg(200, 250) = 225
    assert inputs.mu_bps[1] == 225.0


def test_zero_lambda_falls_back_to_fixed():
    """lambda = 0 → ungueltig, Fallback auf fix-Werte."""
    from services.optimizer.scenario_engine import scenario_inputs_from_cma

    class _CMAZeroLambda(_CMAFixedBonds):
        bonds_ns_beta0_bps = 400
        bonds_ns_beta1_bps = -150
        bonds_ns_beta2_bps = 50
        bonds_ns_lambda_x100 = 0

    inputs = scenario_inputs_from_cma(_CMAZeroLambda())
    assert inputs.mu_bps[1] == 225.0


def test_other_buckets_unchanged_by_ns():
    """Equities, RE, Alternatives, Liquidity bleiben unveraendert."""
    from services.optimizer.scenario_engine import scenario_inputs_from_cma

    inputs_no_ns = scenario_inputs_from_cma(_CMAFixedBonds())
    inputs_with_ns = scenario_inputs_from_cma(_CMANelsonSiegel())

    # Indices: equities=0, bonds=1, real_estate=2, alternatives=3, liquidity=4
    for i in (0, 2, 3, 4):
        assert inputs_no_ns.mu_bps[i] == inputs_with_ns.mu_bps[i]
    # bonds (1) ist anders
    assert inputs_no_ns.mu_bps[1] != inputs_with_ns.mu_bps[1]


def test_vols_unchanged_by_ns_phase2():
    """Phase 2 modifiziert NUR mu_bps (Returns), nicht sigma_bps (Vols).
    Vol-Modellierung ueber NS-Forward-Curve ist Phase 3."""
    from services.optimizer.scenario_engine import scenario_inputs_from_cma

    inputs_no_ns = scenario_inputs_from_cma(_CMAFixedBonds())
    inputs_with_ns = scenario_inputs_from_cma(_CMANelsonSiegel())
    np.testing.assert_array_equal(inputs_no_ns.sigma_bps, inputs_with_ns.sigma_bps)
