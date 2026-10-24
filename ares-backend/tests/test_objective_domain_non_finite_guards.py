"""OPTIMIZER-OBJECTIVE-DOMAIN-001 (Residual): nicht-endliche Zielfunktionswerte.

OPTIMIZER-OBJECTIVE-DOMAIN-FAIL-CLOSED-001 hatte die EINGAENGE der Schaetzer
geprueft (Likelihood-Gewichte, Wachstumsfaktoren) und den Wert nach dem
Rounding in ``run_solver``. Offen blieben (Codex-Reproducer 2026-10-14,
``test_2026_10_14_objective_domain_residual_adversarial.py``):

1. Die SCHAETZER selbst akzeptierten ``nan``/``inf`` in den WERTEN -- gueltige
   Gewichte "reinigen" keine ungueltigen Werte.
2. Endliche, strikt positive Faktoren koennen trotzdem ueberlaufen
   (``cumprod``, Summe, Quadrat) -- jeder Ausgang von ``primary_objective``
   konnte ``inf``/``nan`` liefern.
3. Die Solver-Closure (``_objective_from_inputs``/``_objective_from_array``)
   gab einen nicht endlichen Wert ungeprueft an SLSQP, und
   ``evaluate_weights`` publizierte ihn als ``objective_value``. Der Check
   nach dem Rounding kam fuer SLSQP zu spaet.

Fail-closed heisst hier: ``ObjectiveDomainError`` mit stabilem Reason-Code
(``ValueError``-Unterklasse, ausserhalb der Fallback-Allowlist der
Produktionsgrenze) -- nie ein Wert, der als Optimierungsergebnis weiterlaeuft.
Endliche Faelle sind unveraendert (nur Pruefungen, keine Rechenaenderung).
"""
from __future__ import annotations

import inspect
import sys
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.optimizer import solver  # noqa: E402
from services.optimizer.objective_variants import (  # noqa: E402
    OBJECTIVE_CVAR_RETURN,
    OBJECTIVE_GOAL_SHORTFALL,
    OBJECTIVE_MAX_DRAWDOWN,
    OBJECTIVE_MAX_RETURN,
    OBJECTIVE_MIN_VOLATILITY,
    ObjectiveDomainError,
    primary_objective,
    weighted_lower_tail_mean,
    weighted_mean,
    weighted_std,
)


# -- Codex-Reproducer (uebernommen ohne xfail) --------------------------------


def test_weighted_estimators_reject_non_finite_values_not_only_weights() -> None:
    """Estimator values are domain inputs too; valid weights do not sanitize them."""
    violations: list[str] = []
    cases = (
        ("mean_nan", weighted_mean, np.array([0.0, np.nan])),
        ("mean_inf", weighted_mean, np.array([0.0, np.inf])),
        ("std_nan", weighted_std, np.array([0.0, np.nan])),
        ("std_inf", weighted_std, np.array([0.0, np.inf])),
    )
    for label, estimator, values in cases:
        try:
            estimator(values, np.ones(values.shape[0], dtype=np.float64))
        except ObjectiveDomainError:
            continue
        violations.append(label)

    assert not violations, f"non-finite estimator values accepted: {violations}"


def test_every_primary_objective_exit_is_finite_or_raises_domain_error() -> None:
    """Finite positive factors can still overflow every factor-based metric."""
    cases = (
        ("goal_shortfall_nan", OBJECTIVE_GOAL_SHORTFALL, float("nan"), None),
        (
            "min_volatility_overflow",
            OBJECTIVE_MIN_VOLATILITY,
            0.0,
            np.array([[np.finfo(np.float64).max], [1.0]]),
        ),
        (
            "max_drawdown_cumprod_overflow",
            OBJECTIVE_MAX_DRAWDOWN,
            0.0,
            np.array([[1e308, 1e308], [1.0, 1.0]]),
        ),
        (
            "max_return_weighted_sum_overflow",
            OBJECTIVE_MAX_RETURN,
            0.0,
            np.array([[np.finfo(np.float64).max], [np.finfo(np.float64).max]]),
        ),
    )
    violations: list[tuple[str, float]] = []
    with np.errstate(all="ignore"):
        for label, mode, goal_value, factors in cases:
            try:
                value = primary_objective(
                    mode,
                    goal_shortfall_value=goal_value,
                    portfolio_return_factors=factors,
                )
            except ObjectiveDomainError:
                continue
            if not np.isfinite(value):
                violations.append((label, value))

    assert not violations, f"non-finite primary objectives escaped: {violations}"


def test_solver_rejects_non_finite_objective_before_each_candidate_return() -> None:
    """A final post-round check is too late for SLSQP and public evaluation."""
    candidate_source = inspect.getsource(solver._objective_from_array)
    evaluation_source = inspect.getsource(solver.evaluate_weights)

    finite_guard_tokens = ("isfinite", "require_finite_objective")
    assert any(token in candidate_source for token in finite_guard_tokens), (
        "_objective_from_array can return NaN/Inf to SLSQP; only run_solver's "
        "post-round result is checked"
    )
    assert any(token in evaluation_source for token in finite_guard_tokens), (
        "evaluate_weights can publish a NaN/Inf objective"
    )


# -- Verhaltensnachweise (nicht nur Quelltext-Token) --------------------------


@pytest.mark.parametrize(
    "estimator",
    [weighted_mean, weighted_std, weighted_lower_tail_mean],
)
@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf])
@pytest.mark.parametrize("with_weights", [True, False])
def test_estimators_reject_non_finite_values_with_reason_code(estimator, bad, with_weights):
    values = np.array([0.01, bad, 0.03])
    weights = np.ones(3) if with_weights else None
    with pytest.raises(ObjectiveDomainError) as exc:
        estimator(values, weights)
    assert exc.value.reason_code == "objective_values_not_finite"


def test_estimator_overflow_of_finite_values_is_rejected():
    big = np.finfo(np.float64).max
    with np.errstate(all="ignore"):
        with pytest.raises(ObjectiveDomainError) as exc:
            weighted_mean(np.array([big, big]), None)
    assert exc.value.reason_code == "objective_estimate_not_finite"


@pytest.mark.parametrize(
    "mode",
    [OBJECTIVE_MIN_VOLATILITY, OBJECTIVE_MAX_DRAWDOWN, OBJECTIVE_MAX_RETURN],
)
def test_primary_objective_overflow_carries_reason_code(mode):
    big = np.finfo(np.float64).max
    factors = {
        OBJECTIVE_MIN_VOLATILITY: np.array([[big], [1.0]]),
        OBJECTIVE_MAX_DRAWDOWN: np.array([[1e308, 1e308], [1.0, 1.0]]),
        OBJECTIVE_MAX_RETURN: np.array([[big], [big]]),
    }[mode]
    with np.errstate(all="ignore"):
        with pytest.raises(ObjectiveDomainError) as exc:
            primary_objective(
                mode, goal_shortfall_value=0.0, portfolio_return_factors=factors,
            )
    assert exc.value.reason_code in {
        "objective_values_not_finite",
        "objective_estimate_not_finite",
        "objective_value_not_finite",
    }


@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf])
def test_goal_shortfall_non_finite_value_is_rejected(bad):
    with pytest.raises(ObjectiveDomainError) as exc:
        primary_objective(
            OBJECTIVE_GOAL_SHORTFALL,
            goal_shortfall_value=bad,
            portfolio_return_factors=None,
        )
    assert exc.value.reason_code == "objective_value_not_finite"


@pytest.mark.parametrize(
    "mode",
    [
        OBJECTIVE_CVAR_RETURN,
        OBJECTIVE_MAX_DRAWDOWN,
        OBJECTIVE_MIN_VOLATILITY,
        OBJECTIVE_MAX_RETURN,
    ],
)
def test_finite_primary_objectives_are_unchanged(mode):
    """Bitidentitaet endlicher Faelle: Wert gleich der Referenzrechnung."""
    rng = np.random.default_rng(11)
    factors = 1.0 + rng.normal(0.04, 0.10, size=(40, 6))
    weights = rng.uniform(0.5, 1.5, size=40)
    value = primary_objective(
        mode, goal_shortfall_value=0.0, portfolio_return_factors=factors,
        weights=weights,
    )
    w = weights / weights.sum()
    if mode == OBJECTIVE_MAX_RETURN:
        ann = np.exp(np.mean(np.log(factors), axis=1)) - 1.0
        expected = -float(np.sum(ann * w))
    elif mode == OBJECTIVE_MIN_VOLATILITY:
        flat = (factors - 1.0).reshape(-1)
        fw = np.repeat(weights, factors.shape[1])
        fw = fw / fw.sum()
        mean = float(np.sum(flat * fw))
        dev = flat - mean
        expected = float(np.sqrt(max(0.0, np.sum(fw * dev * dev))))
    elif mode == OBJECTIVE_MAX_DRAWDOWN:
        index = np.concatenate([np.ones((40, 1)), np.cumprod(factors, axis=1)], axis=1)
        peak = np.maximum.accumulate(index, axis=1)
        dd = ((peak - index) / np.where(peak > 0.0, peak, 1.0)).max(axis=1)
        expected = float(np.sum(dd * w))
    else:
        assert np.isfinite(value)
        return
    assert value == expected


# -- Solver-Closure und evaluate_weights --------------------------------------


def _cma():
    return SimpleNamespace(
        id="cma-nonfinite",
        bonds_chf_ig_return_bps=220, bonds_chf_ig_vol_bps=350,
        bonds_fx_hedged_return_bps=220, bonds_fx_hedged_vol_bps=430,
        equity_ch_return_bps=620, equity_ch_vol_bps=1450,
        equity_intl_return_bps=700, equity_intl_vol_bps=1600,
        real_estate_ch_return_bps=450, real_estate_ch_vol_bps=820,
        alternatives_gold_return_bps=300, alternatives_gold_vol_bps=1200,
        liquidity_return_bps=80, liquidity_vol_bps=20,
        correlation_matrix_json="",
        equities_skewness_bps=-3000, equities_excess_kurt_bps=15000,
        bonds_skewness_bps=0, bonds_excess_kurt_bps=0,
        real_estate_skewness_bps=0, real_estate_excess_kurt_bps=0,
        alternatives_skewness_bps=0, alternatives_excess_kurt_bps=0,
        liquidity_skewness_bps=0, liquidity_excess_kurt_bps=0,
    )


def _house_matrix():
    return SimpleNamespace(
        profile_name="Wachstumsorientiert",
        equity_min_bps=4500, equity_max_bps=7000, equity_target_bps=6000,
        bonds_min_bps=2000, bonds_max_bps=4500, bonds_target_bps=3000,
        real_estate_min_bps=0, real_estate_max_bps=1500, real_estate_target_bps=500,
        alt_min_bps=0, alt_max_bps=1000, alt_target_bps=300,
        liq_min_bps=200, liq_max_bps=2000, liq_target_bps=200,
        max_risky_fraction_bps=7500,
    )


def _pension_goal():
    today = date.today()
    return SimpleNamespace(
        id="goal-pension-nonfinite", label="Pension",
        goal_type="Pensionsausgabe",
        target_amount_rappen=24_000_00,
        target_wealth_rappen=None, target_return_bps=None,
        horizon_years=None,
        start_date=(today + timedelta(days=365 * 5)).isoformat(),
        target_date=(today + timedelta(days=365 * 25)).isoformat(),
        is_ongoing=0, frequency="jährlich",
        hardness="Hart", rank=1, weight_bps=5000,
        value_mode="real",
    )


def _solver_kwargs():
    return dict(
        cma=_cma(), goals=[_pension_goal()], house_matrix_row=_house_matrix(),
        score_x10=70, advisory_wealth_rappen=500_000_00,
        cashflow_series_rappen=[20_000_00] * 10,
        horizon_years=10, n_paths=200, seed=4242,
    )


_HOUSE_WEIGHTS = {
    "equities": 6000, "bonds": 3000, "real_estate": 500,
    "alternatives": 300, "liquidity": 200,
}


@pytest.fixture
def nan_objective(monkeypatch):
    """Simuliert einen Defekt weiter innen: die Zielfunktion wird ``nan``."""
    monkeypatch.setattr(
        solver, "combined_objective_two_phase", lambda *a, **k: float("nan"),
    )


def test_objective_from_array_raises_instead_of_returning_nan(nan_objective):
    ctx = solver.build_optimizer_context(**_solver_kwargs())
    w = solver._weights_bps_to_array(_HOUSE_WEIGHTS)
    with pytest.raises(ObjectiveDomainError) as exc:
        solver._objective_from_array(ctx, w)
    assert exc.value.reason_code == "objective_value_not_finite"


def test_evaluate_weights_never_publishes_non_finite_objective(nan_objective):
    ctx = solver.build_optimizer_context(**_solver_kwargs())
    with pytest.raises(ObjectiveDomainError) as exc:
        solver.evaluate_weights(ctx, dict(_HOUSE_WEIGHTS))
    assert exc.value.reason_code == "objective_value_not_finite"


def test_run_solver_fails_closed_before_slsqp_sees_non_finite(nan_objective, monkeypatch):
    """Kein Ergebnis (weder konvergiert noch House-Fallback) aus ``nan``.

    Gruen allein durch den Post-Round-Check waere der falsche Grund: SLSQP
    haette ``nan`` dann schon gesehen. Darum darf kein SLSQP-Start und kein
    GA-Fallback ueberhaupt laufen.
    """
    def _must_not_run(*_a, **_k):
        raise AssertionError("SLSQP/GA lief mit nicht endlicher Zielfunktion")

    monkeypatch.setattr(solver, "_solve_single_start", _must_not_run)
    monkeypatch.setattr(solver, "_solve_via_genetic_algorithm", _must_not_run)
    with pytest.raises(ObjectiveDomainError) as exc:
        solver.run_solver(**_solver_kwargs())
    assert exc.value.reason_code == "objective_value_not_finite"
    assert not isinstance(exc.value, solver.SolverTechnicalError)


def test_finite_evaluate_weights_unchanged():
    ctx = solver.build_optimizer_context(**_solver_kwargs())
    w = solver._weights_bps_to_array(_HOUSE_WEIGHTS)
    ev = solver.evaluate_weights(ctx, dict(_HOUSE_WEIGHTS))
    assert np.isfinite(ev.objective_value)
    assert ev.objective_value == solver._objective_from_array(ctx, w)
