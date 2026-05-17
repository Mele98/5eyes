"""Sprint 8 Phase 2: scenario_engine + Risikopraemien-Integration."""
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
    equity_kgv_current_x10 = None
    equity_kgv_fair_x10 = None
    equity_kgv_alpha_x100 = None
    # Sprint 8: default None
    real_estate_risk_premium_bps = None
    alternatives_risk_premium_bps = None


def test_no_premium_re_alts_use_fixed_returns():
    """CMA ohne Premium → RE/Alts nutzen fixe Werte."""
    from services.optimizer.scenario_engine import scenario_inputs_from_cma

    inputs = scenario_inputs_from_cma(_BaseCMA())
    # real_estate=2, alternatives=3
    assert inputs.mu_bps[2] == 400  # real_estate_ch_return
    assert inputs.mu_bps[3] == 300  # alternatives_gold_return


def test_premium_without_ns_falls_back():
    """Premium gesetzt ABER kein NS → Fallback auf fixe Werte (kein risk_free)."""
    from services.optimizer.scenario_engine import scenario_inputs_from_cma

    class _CMAPremiumNoNs(_BaseCMA):
        real_estate_risk_premium_bps = 200
        alternatives_risk_premium_bps = 300

    inputs = scenario_inputs_from_cma(_CMAPremiumNoNs())
    assert inputs.mu_bps[2] == 400  # unveraendert
    assert inputs.mu_bps[3] == 300


def test_premium_with_ns_active_re_return():
    """Premium + NS → re_return = NS.short_rate + premium."""
    from services.optimizer.scenario_engine import scenario_inputs_from_cma

    class _CMAFull(_BaseCMA):
        bonds_ns_beta0_bps = 400
        bonds_ns_beta1_bps = -100  # short_rate = 400 - 100 = 300
        bonds_ns_beta2_bps = 50
        bonds_ns_lambda_x100 = 60
        real_estate_risk_premium_bps = 200

    inputs = scenario_inputs_from_cma(_CMAFull())
    # short_rate = 300, premium = 200 → re_return = 500
    assert inputs.mu_bps[2] == 500


def test_premium_with_ns_active_alternatives_return():
    """Analog fuer Alternatives."""
    from services.optimizer.scenario_engine import scenario_inputs_from_cma

    class _CMAFull(_BaseCMA):
        bonds_ns_beta0_bps = 400
        bonds_ns_beta1_bps = -100  # short_rate = 300
        bonds_ns_beta2_bps = 50
        bonds_ns_lambda_x100 = 60
        alternatives_risk_premium_bps = 350

    inputs = scenario_inputs_from_cma(_CMAFull())
    # short_rate = 300, premium = 350 → alt_return = 650
    assert inputs.mu_bps[3] == 650


def test_zinsanstieg_erhoeht_re_return():
    """Bei Zinsanstieg (hoehere NS-Curve): RE-Return steigt mit."""
    from services.optimizer.scenario_engine import scenario_inputs_from_cma

    class _CMALowRates(_BaseCMA):
        bonds_ns_beta0_bps = 200  # niedrige Long-Rate
        bonds_ns_beta1_bps = -100  # short = 100
        bonds_ns_beta2_bps = 0
        bonds_ns_lambda_x100 = 60
        real_estate_risk_premium_bps = 200

    class _CMAHighRates(_BaseCMA):
        bonds_ns_beta0_bps = 600  # hohe Long-Rate
        bonds_ns_beta1_bps = -200  # short = 400
        bonds_ns_beta2_bps = 0
        bonds_ns_lambda_x100 = 60
        real_estate_risk_premium_bps = 200

    inputs_low = scenario_inputs_from_cma(_CMALowRates())
    inputs_high = scenario_inputs_from_cma(_CMAHighRates())
    # low: 100 + 200 = 300, high: 400 + 200 = 600
    assert inputs_low.mu_bps[2] == 300
    assert inputs_high.mu_bps[2] == 600
    assert inputs_high.mu_bps[2] > inputs_low.mu_bps[2]


def test_only_re_premium_set_alts_fixed():
    """Wenn nur RE-Premium gesetzt, alts bleibt fix."""
    from services.optimizer.scenario_engine import scenario_inputs_from_cma

    class _CMAReOnly(_BaseCMA):
        bonds_ns_beta0_bps = 400
        bonds_ns_beta1_bps = -100
        bonds_ns_beta2_bps = 0
        bonds_ns_lambda_x100 = 60
        real_estate_risk_premium_bps = 200
        # alts kein Premium

    inputs = scenario_inputs_from_cma(_CMAReOnly())
    assert inputs.mu_bps[2] == 500  # re via Premium
    assert inputs.mu_bps[3] == 300  # alts fix


def test_other_buckets_unchanged_by_premium():
    """Equities, Bonds, Liquidity bleiben unveraendert."""
    from services.optimizer.scenario_engine import scenario_inputs_from_cma

    class _CMAFull(_BaseCMA):
        bonds_ns_beta0_bps = 400
        bonds_ns_beta1_bps = -100
        bonds_ns_beta2_bps = 50
        bonds_ns_lambda_x100 = 60
        real_estate_risk_premium_bps = 200
        alternatives_risk_premium_bps = 300

    base = scenario_inputs_from_cma(_BaseCMA())
    with_premium = scenario_inputs_from_cma(_CMAFull())
    # equities (0), liquidity (4) unveraendert
    assert base.mu_bps[0] == with_premium.mu_bps[0]
    assert base.mu_bps[4] == with_premium.mu_bps[4]
    # bonds (1) ist anders weil NS aktiv, aber Premium ist NICHT Ursache
    # → testen wir nicht hier
    # RE und Alts sind anders
    assert base.mu_bps[2] != with_premium.mu_bps[2]
    assert base.mu_bps[3] != with_premium.mu_bps[3]
