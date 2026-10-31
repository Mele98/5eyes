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


def test_ns_params_do_not_override_fixed_bond_returns():
    """NS-BOND-SLEEVE-COLLAPSE-001: die Kurve setzt KEIN Niveau mehr.

    Dieser Test hiess einmal ``test_ns_params_override_fixed_bond_returns``
    und verlangte ``bonds_return == curve.yield_at(5)``. Er pinnte damit den
    Befund als Vertrag: die NS-Kurve ist eine Swap-/Staatskurve ohne
    Kreditaufschlag, die CMA-Bond-Returns sind Basis-plus-Spread. Das
    Ersetzen vernichtete den Aufschlag -- hier konkret 225 bps (= avg(200,
    250)) zu 366 bps hochgezogen, im Produktions-Default mit der CHF-Swap-
    Kalibrierung umgekehrt 228 bps auf 50 bps heruntergezogen -- und
    kollabierte zusaetzlich alle Bond-Sleeves auf denselben Wert.

    Neuer Vertrag: die Kurve traegt nur die Termstruktur bei, und die ist
    ohne Laufzeitpraeferenz exakt null. Der Bond-Return bleibt deshalb der
    CMA-Wert.
    """
    from services.optimizer.scenario_engine import scenario_inputs_from_cma
    from services.rates.nelson_siegel import NelsonSiegelCurve

    inputs = scenario_inputs_from_cma(_CMANelsonSiegel())
    bonds_return = inputs.mu_bps[1]

    # _avg_or_zero([200, 250]) = 225 -- unveraendert gegenueber dem Lauf ohne NS.
    assert bonds_return == 225.0

    # Gegenprobe: der Kurvenwert ist ein voellig anderer Betrag. Genau diese
    # Differenz wurde vorher als Bond-Return ausgewiesen.
    curve = NelsonSiegelCurve(beta0_bps=400, beta1_bps=-150, beta2_bps=50, lambda_=0.6)
    assert round(curve.yield_at(5.0)) != 225, (
        "Fixture-Kurve muss sich vom CMA-Wert unterscheiden, sonst prueft "
        "dieser Test nichts"
    )


def test_ns_tilt_applies_when_a_maturity_is_given():
    """Die Kurve wirkt additiv, sobald eine Laufzeit abseits der Referenz gilt.

    Gegenstueck zum Test darueber: ohne Laufzeit null Wirkung, mit Laufzeit
    genau die Termstruktur-Differenz -- und zwar auf den CMA-Wert addiert,
    nicht an seine Stelle gesetzt.
    """
    from services.optimizer.scenario_engine import _compute_bonds_duration_tilt_bps
    from services.portfolio_engine_cma import _apply_cma_market_adjustments

    cma = _CMANelsonSiegel()
    tilt = _compute_bonds_duration_tilt_bps(cma, maturity_years=10.0)
    assert tilt is not None and tilt != 0.0

    adjusted = _apply_cma_market_adjustments(
        {
            "equities": 700, "bonds": 225, "real_estate": 330,
            "alternatives": 300, "liquidity": 80,
        },
        cma,
        bonds_maturity_years=10.0,
    )
    assert adjusted["bonds"] == int(round(225 + tilt))


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


def test_complete_ns_with_zero_lambda_fails_closed():
    """Eine vollstaendige, ungueltige NS-Gruppe ist kein Fixed-CMA-Fallback."""
    from services.optimizer.constraints import OptimizerInputError
    from services.optimizer.scenario_engine import scenario_inputs_from_cma

    class _CMAZeroLambda(_CMAFixedBonds):
        bonds_ns_beta0_bps = 400
        bonds_ns_beta1_bps = -150
        bonds_ns_beta2_bps = 50
        bonds_ns_lambda_x100 = 0

    with pytest.raises(OptimizerInputError, match="bonds_ns_lambda_x100"):
        scenario_inputs_from_cma(_CMAZeroLambda())


@pytest.mark.parametrize(
    "field_name, invalid_value",
    [
        ("bonds_ns_beta0_bps", float("nan")),
        ("bonds_ns_beta1_bps", float("inf")),
        ("bonds_ns_beta2_bps", float("-inf")),
        ("bonds_ns_lambda_x100", float("nan")),
    ],
)
def test_complete_ns_with_non_finite_raw_value_fails_closed(
    field_name,
    invalid_value,
):
    """Auch direkt aus einer korrupten DB gelesene Werte duerfen nicht downgraden."""
    from services.optimizer.constraints import OptimizerInputError
    from services.optimizer.scenario_engine import scenario_inputs_from_cma

    cma = _CMANelsonSiegel()
    setattr(cma, field_name, invalid_value)

    with pytest.raises(OptimizerInputError, match=field_name):
        scenario_inputs_from_cma(cma)


def test_no_bucket_is_changed_by_an_active_ns_curve_without_a_maturity():
    """Eine aktive Kurve ohne Laufzeitpraeferenz aendert KEINEN Bucket.

    Vorher verlangte dieser Test ausdruecklich, dass sich Bonds aendern
    (``mu_bps[1] != mu_bps[1]``) -- das war die Erwartung aus dem
    Overwrite-Zeitalter. Jetzt gilt: ohne Laufzeit ist der Termstruktur-Tilt
    null, also bleibt auch der Obligationen-Bucket gleich.

    Die Risikopraemien-Felder (real_estate/alternatives) sind in dieser
    Fixture nicht gesetzt; waeren sie es, wuerden sie ihre Buckets weiter
    ueberschreiben -- ein eigener, hier nicht beruehrter Befund.
    """
    from services.optimizer.scenario_engine import scenario_inputs_from_cma

    inputs_no_ns = scenario_inputs_from_cma(_CMAFixedBonds())
    inputs_with_ns = scenario_inputs_from_cma(_CMANelsonSiegel())

    # Indices: equities=0, bonds=1, real_estate=2, alternatives=3, liquidity=4
    np.testing.assert_array_equal(inputs_no_ns.mu_bps, inputs_with_ns.mu_bps)


def test_vols_unchanged_by_ns_phase2():
    """Phase 2 modifiziert NUR mu_bps (Returns), nicht sigma_bps (Vols).
    Vol-Modellierung ueber NS-Forward-Curve ist Phase 3."""
    from services.optimizer.scenario_engine import scenario_inputs_from_cma

    inputs_no_ns = scenario_inputs_from_cma(_CMAFixedBonds())
    inputs_with_ns = scenario_inputs_from_cma(_CMANelsonSiegel())
    np.testing.assert_array_equal(inputs_no_ns.sigma_bps, inputs_with_ns.sigma_bps)
