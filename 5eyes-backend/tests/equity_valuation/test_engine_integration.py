"""Sprint 7 Phase 2: scenario_inputs_from_cma + KGV-MR-Adjustment."""
from __future__ import annotations

import numpy as np
import pytest


class _BaseCMA:
    id = "base"
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
    bonds_ns_beta0_bps = None
    bonds_ns_beta1_bps = None
    bonds_ns_beta2_bps = None
    bonds_ns_lambda_x100 = None
    # KGV-Params default None
    equity_kgv_current_x10 = None
    equity_kgv_fair_x10 = None
    equity_kgv_alpha_x100 = None


def test_no_kgv_params_equity_return_unchanged():
    """CMA ohne KGV-Params → equity-Return = avg(equity_ch, equity_intl)."""
    from services.optimizer.scenario_engine import scenario_inputs_from_cma

    inputs = scenario_inputs_from_cma(_BaseCMA())
    # equities-Index = 0
    expected = (600 + 700) / 2
    assert inputs.mu_bps[0] == expected


def test_kgv_overvaluation_reduces_equity_return():
    """KGV-Current 22 > KGV-Fair 17 → equity-Return wird gesenkt."""
    from services.optimizer.scenario_engine import scenario_inputs_from_cma

    class _CMAOvervalued(_BaseCMA):
        equity_kgv_current_x10 = 220  # 22.0
        equity_kgv_fair_x10 = 170     # 17.0
        equity_kgv_alpha_x100 = 15    # 0.15

    inputs = scenario_inputs_from_cma(_CMAOvervalued())
    base_equity = (600 + 700) / 2  # 650
    assert inputs.mu_bps[0] < base_equity, "Equity-Return sollte gesenkt sein"


def test_kgv_undervaluation_increases_equity_return():
    """KGV-Current 13 < KGV-Fair 17 → equity-Return wird erhoeht."""
    from services.optimizer.scenario_engine import scenario_inputs_from_cma

    class _CMAUndervalued(_BaseCMA):
        equity_kgv_current_x10 = 130
        equity_kgv_fair_x10 = 170
        equity_kgv_alpha_x100 = 15

    inputs = scenario_inputs_from_cma(_CMAUndervalued())
    base_equity = (600 + 700) / 2  # 650
    assert inputs.mu_bps[0] > base_equity, "Equity-Return sollte erhoeht sein"


def test_kgv_at_fair_value_no_adjustment():
    """KGV-Current = KGV-Fair → kein Adjustment, equity-Return unveraendert."""
    from services.optimizer.scenario_engine import scenario_inputs_from_cma

    class _CMAFair(_BaseCMA):
        equity_kgv_current_x10 = 170
        equity_kgv_fair_x10 = 170
        equity_kgv_alpha_x100 = 15

    inputs = scenario_inputs_from_cma(_CMAFair())
    base_equity = (600 + 700) / 2  # 650
    assert inputs.mu_bps[0] == base_equity


def test_partial_kgv_params_no_adjustment():
    """Wenn nur 2 von 3 KGV-Params gesetzt → kein Adjustment."""
    from services.optimizer.scenario_engine import scenario_inputs_from_cma

    class _CMAPartial(_BaseCMA):
        equity_kgv_current_x10 = 220
        equity_kgv_fair_x10 = 170
        equity_kgv_alpha_x100 = None  # FEHLT

    inputs = scenario_inputs_from_cma(_CMAPartial())
    base_equity = (600 + 700) / 2
    assert inputs.mu_bps[0] == base_equity


def test_kgv_invalid_params_no_adjustment():
    """KGV-Current=0 ist invalid → defensive Fallback auf 0 Adjustment."""
    from services.optimizer.scenario_engine import scenario_inputs_from_cma

    class _CMAInvalid(_BaseCMA):
        equity_kgv_current_x10 = 0  # invalid
        equity_kgv_fair_x10 = 170
        equity_kgv_alpha_x100 = 15

    inputs = scenario_inputs_from_cma(_CMAInvalid())
    base_equity = (600 + 700) / 2
    assert inputs.mu_bps[0] == base_equity


def test_kgv_only_affects_equities_bucket():
    """Andere Buckets (bonds, RE, alt, liq) bleiben unveraendert."""
    from services.optimizer.scenario_engine import scenario_inputs_from_cma

    class _CMAOvervalued(_BaseCMA):
        equity_kgv_current_x10 = 220
        equity_kgv_fair_x10 = 170
        equity_kgv_alpha_x100 = 15

    base = scenario_inputs_from_cma(_BaseCMA())
    with_kgv = scenario_inputs_from_cma(_CMAOvervalued())
    # Buckets: equities=0, bonds=1, real_estate=2, alternatives=3, liquidity=4
    for i in (1, 2, 3, 4):
        assert base.mu_bps[i] == with_kgv.mu_bps[i]
    # equities (0) ist anders
    assert base.mu_bps[0] != with_kgv.mu_bps[0]


def test_kgv_with_ns_bonds_both_active():
    """Sprint 6 (NS-Bonds) + Sprint 7 (KGV-MR) gleichzeitig aktiv."""
    from services.optimizer.scenario_engine import scenario_inputs_from_cma

    class _CMACombined(_BaseCMA):
        # NS-Curve
        bonds_ns_beta0_bps = 400
        bonds_ns_beta1_bps = -150
        bonds_ns_beta2_bps = 50
        bonds_ns_lambda_x100 = 60
        # KGV-MR
        equity_kgv_current_x10 = 220
        equity_kgv_fair_x10 = 170
        equity_kgv_alpha_x100 = 15

    inputs = scenario_inputs_from_cma(_CMACombined())
    # Bonds Return ist NS-basiert (anders als 225)
    assert inputs.mu_bps[1] != 225.0
    # Equity ist KGV-MR-adjusted (anders als 650)
    assert inputs.mu_bps[0] != 650.0
