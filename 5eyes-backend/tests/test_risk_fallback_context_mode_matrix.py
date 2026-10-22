"""RISK-FALLBACK-CONTEXT-001 (Rest): Codex-Reproducer, als regulaerer Test.

Ein erzwungener Hausmatrix-Fallback muss die GESAMTE Auswahl-Herkunft
ueberschreiben. Vorher wertete ``_build_allocation_model_basis``
``has_stochastic_basis`` vor ``active_method`` aus: ein Fallback, der noch den
Context des verworfenen Solver-Laufs trug, war gleichzeitig
``fallback_house_matrix`` und ``stochastic_decision_v2``.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.optimizer.objective_contract import ObjectiveContractV1
from services.portfolio_engine_model_basis import _build_allocation_model_basis


def _failed_solver_result():
    context = SimpleNamespace(
        n_paths=100,
        horizon_years=10,
        tax_regime=None,
        dividend_yield_bps_per_bucket=None,
        scenario_weights=[1.0] * 100,
        objective_contract=ObjectiveContractV1(
            objective_mode="goal_shortfall",
            goal_weighting_mode="hardness",
        ),
    )
    return SimpleNamespace(context=context, method="SLSQP", seed=7, n_paths=100)


def _basis(optimizer_mode: str, forced: str | None):
    return _build_allocation_model_basis(
        optimizer_mode=optimizer_mode,
        optimizer_result=_failed_solver_result(),
        allocation=None,
        monte_carlo={"horizon_years": 10},
        simulation_prefs={},
        mandate=SimpleNamespace(jurisdiction="CH"),
        cma=None,
        forced_active_method=forced,
    )["optimization"]


@pytest.mark.parametrize("optimizer_mode", ["stochastic", "shadow_stochastic"])
def test_stochastic_risk_fallback_does_not_claim_stochastic_selection_basis(
    optimizer_mode: str,
) -> None:
    basis = _basis(optimizer_mode, "fallback_house_matrix")
    assert basis["active_method"] == "fallback_house_matrix"
    assert basis["basis_id"] == "house_matrix_fallback_v1", basis
    assert basis["purpose"] == "controlled_fallback", basis
    assert basis["portfolio_dynamics"] == "policy_matrix", basis
    assert basis["liability_basis"] == "policy_only", basis
    assert basis["importance_sampling"] is False, basis
    assert "resampling" not in basis
    # Audit-Spur des verworfenen Laufs bleibt erhalten.
    assert basis["seed"] == 7
    assert basis["n_paths"] == 100


def test_unforced_stochastic_run_keeps_stochastic_basis() -> None:
    """Positivkontrolle: ohne Fallback bleibt die stochastische Herkunft."""
    basis = _basis("stochastic", None)
    assert basis["basis_id"] == "stochastic_decision_v2"
    assert basis["portfolio_dynamics"] == "annual_constant_weight"
    assert basis["importance_sampling"] is True
