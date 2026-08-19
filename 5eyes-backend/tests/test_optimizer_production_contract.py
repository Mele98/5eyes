"""P0 production contracts for the stochastic asset-allocation path.

These tests deliberately exercise ``generate_target_allocation``.  Unit tests
for the solver are not sufficient here: the production orchestrator must pass
the exact mandate-specific sub-allocation plan, effective bounds and weighted
risky fractions into the solver, and it must publish analytics for the
allocation that is actually persisted.

The numerical optimizer is replaced with deterministic doubles where its
mathematics is not the subject of the test.  Every double still builds the real
``OptimizerContext`` from the received production kwargs, so context wiring and
the final activation validation remain real.
"""
from __future__ import annotations

import copy
import hashlib
import inspect
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Query

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for path in (BACKEND_ROOT, TESTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from main import app  # noqa: E402,F401 - registers all ORM models
from models.allocation import (  # noqa: E402
    BuildingBlock,
    CapitalMarketAssumption,
    OptimizerPolicy,
    OptimizerRun,
    TargetAllocation,
)
from models.mandates import Mandate  # noqa: E402
from models.profiling import RiskAssessment  # noqa: E402
from models.wealth import Cashflow, Goal, WealthInflow, WealthPosition  # noqa: E402
import services.optimizer.objective as objective_module  # noqa: E402
import services.optimizer.solver as solver_module  # noqa: E402
import services.portfolio_engine as pe  # noqa: E402
from schemas.allocation import TargetAllocationResponse  # noqa: E402
from services.optimizer.constraints import OptimizerInputError  # noqa: E402
from services.optimizer.solver import (  # noqa: E402
    OptimizerResult,
    build_optimizer_context,
)
from services.optimizer.scenario_engine import scenario_inputs_from_cma  # noqa: E402
from services.portfolio_engine_house_matrix import (  # noqa: E402
    _canonicalize_sub_allocation_mix,
    _materialize_sub_allocation_plan,
)
from test_optimizer_shadow_mode import (  # noqa: E402
    _seed_realistic_mandate,
    session_factory,  # noqa: F401 - pytest fixture re-export
)


BUCKETS = ("equities", "bonds", "real_estate", "alternatives", "liquidity")
INTEGRITY_ERROR_PATTERN = (
    r"Persistiert|Allocation-Context|Context-Hash|Entscheidungsartefakt|Integrit"
)


@pytest.fixture(autouse=True)
def _fast_non_optimizer_layers(monkeypatch):
    """Keep production orchestration real while avoiding a second large MC."""
    monkeypatch.setattr(pe, "_OPTIMIZER_N_PATHS_DEFAULT", 48)
    monkeypatch.setattr(
        pe,
        "_run_allocation_monte_carlo",
        lambda **_kwargs: {"goal_summaries": [], "current_goal_summaries": []},
    )


def _seed_clean_mandate(session_factory, suffix: str):
    """Reuse the realistic strategy-ready fixture, but remove goals/cashflows.

    The resulting mandate has a real portfolio, CMA, policy, House Matrix and
    complete risk assessment.  Removing goal/reserve tilts gives the tests a
    crisp allocation oracle without weakening the production path under test.
    """
    advisor_id, client_id, mandate_id, assessment_id, _goal_id = (
        _seed_realistic_mandate(session_factory, suffix=suffix)
    )
    with session_factory() as session:
        for goal in session.query(Goal).filter(Goal.mandate_id == mandate_id).all():
            goal.is_active = 0
        for cashflow in session.query(Cashflow).filter(
            Cashflow.client_id == client_id
        ).all():
            cashflow.is_active = 0
        session.commit()
    return advisor_id, client_id, mandate_id, assessment_id


def _preferences(*, max_illiquid: str | None = None, pe_only: bool = False) -> dict:
    limits = {}
    if max_illiquid is not None:
        limits["maxIlliquid"] = max_illiquid
    asset_classes = {
        "equitiesGeo": "Global",
        "altsGold": not pe_only,
        "altsPe": True,
    }
    return {
        "policy": {},
        "tilts": {},
        "product": {},
        "geo": {},
        "assetClasses": asset_classes,
        "limits": limits,
        "simulation": {"monteCarloRuns": 50},
        "bands": {
            "equities": {"min_bps": 4400, "target_bps": 5000, "max_bps": 5600},
            "bonds": {"min_bps": 2600, "target_bps": 3000, "max_bps": 3600},
            "real_estate": {"min_bps": 300, "target_bps": 500, "max_bps": 1000},
            "alternatives": {"min_bps": 500, "target_bps": 1000, "max_bps": 1000},
            "liquidity": {"min_bps": 200, "target_bps": 500, "max_bps": 1000},
        },
    }


def _invalid_real_estate_preferences() -> dict:
    """Per-bucket valid and sums to 100%, but conflicts with global RE cap."""
    prefs = _preferences()
    prefs["bands"] = {
        "equities": {"min_bps": 3000, "target_bps": 3500, "max_bps": 5000},
        "bonds": {"min_bps": 2500, "target_bps": 3000, "max_bps": 4500},
        "real_estate": {"min_bps": 2500, "target_bps": 2500, "max_bps": 3000},
        "alternatives": {"min_bps": 0, "target_bps": 500, "max_bps": 1000},
        "liquidity": {"min_bps": 200, "target_bps": 500, "max_bps": 1000},
    }
    return prefs


def _weights(target_allocation: TargetAllocation) -> dict[str, int]:
    return {
        "equities": int(target_allocation.target_equities_bps),
        "bonds": int(target_allocation.target_bonds_bps),
        "real_estate": int(target_allocation.target_real_estate_bps),
        "alternatives": int(target_allocation.target_alternatives_bps),
        "liquidity": int(target_allocation.target_liquidity_bps),
    }


def _band_pairs(target_allocation: TargetAllocation) -> dict[str, tuple[int, int]]:
    return {
        "equities": (
            int(target_allocation.band_equities_min_bps),
            int(target_allocation.band_equities_max_bps),
        ),
        "bonds": (
            int(target_allocation.band_bonds_min_bps),
            int(target_allocation.band_bonds_max_bps),
        ),
        "real_estate": (
            int(target_allocation.band_real_estate_min_bps),
            int(target_allocation.band_real_estate_max_bps),
        ),
        "alternatives": (
            int(target_allocation.band_alternatives_min_bps),
            int(target_allocation.band_alternatives_max_bps),
        ),
        "liquidity": (
            int(target_allocation.band_liquidity_min_bps),
            int(target_allocation.band_liquidity_max_bps),
        ),
    }


def _canonical_rows(rows) -> list[tuple[str, str, int]]:
    canonical = _canonicalize_sub_allocation_mix([dict(row) for row in rows or []])
    return [
        (
            str(row.get("asset_class") or ""),
            str(row.get("sub_asset_class") or ""),
            int(row.get("target_weight_bps") or 0),
        )
        for row in canonical
    ]


def _weighted_rows(rows) -> list[tuple[str, str, int]]:
    """Comparable materialized rows without non-contract rationale metadata."""
    return [
        (
            str(row.get("asset_class") or ""),
            str(row.get("sub_asset_class") or ""),
            int(row.get("target_weight_bps") or 0),
        )
        for row in rows or []
    ]


def _sub_weight(rows, label: str) -> int:
    return sum(
        int(row.get("target_weight_bps") or 0)
        for row in rows or []
        if str(row.get("sub_asset_class") or "") == label
    )


def _generate(session_factory, mandate_id: str, advisor_id: str, preferences: dict):
    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        result = pe.generate_target_allocation(
            session,
            mandate,
            advisor_id,
            preferences=preferences,
        )
        session.commit()
        return result


def _reload_payload(session, allocation: TargetAllocation):
    mandate = session.query(Mandate).filter(
        Mandate.id == allocation.mandate_id
    ).one()
    policy = session.query(OptimizerPolicy).filter(
        OptimizerPolicy.id == allocation.policy_id
    ).one()
    cma = session.query(CapitalMarketAssumption).filter(
        CapitalMarketAssumption.id == allocation.capital_market_assumptions_id
    ).one()
    assessment = session.query(RiskAssessment).filter(
        RiskAssessment.id == allocation.based_on_assessment_id
    ).one()
    return pe.build_target_payload_from_allocation(
        session,
        mandate,
        allocation,
        policy,
        cma,
        assessment,
        preferences=None,
    )


def _context_from_solver_kwargs(kwargs: dict):
    accepted = inspect.signature(build_optimizer_context).parameters
    context_kwargs = {key: value for key, value in kwargs.items() if key in accepted}
    return build_optimizer_context(**context_kwargs)


def _install_solver_double(
    monkeypatch,
    *,
    weights_bps: dict[str, int],
    status: str = "converged",
    method: str = "stochastic",
    goal_achievability: tuple[dict, ...] = (),
    stress_evaluations: dict | None = None,
):
    calls: list[dict] = []

    def _fake_run_solver(**kwargs):
        context = kwargs.get("optimizer_context") or _context_from_solver_kwargs(kwargs)
        calls.append(
            {
                "kwargs": kwargs,
                "sub_allocations": copy.deepcopy(kwargs.get("sub_allocations")),
                "effective_bounds_bps": copy.deepcopy(
                    kwargs.get("effective_bounds_bps")
                ),
                "risky_fraction_per_bucket": copy.deepcopy(
                    kwargs.get("risky_fraction_per_bucket")
                ),
                "candidate_weights_bps": dict(weights_bps),
                "context": context,
            }
        )
        return OptimizerResult(
            weights_bps=dict(weights_bps),
            objective_value=1.25,
            iterations=2,
            seed=int(context.seed),
            status=status,
            method=method,
            reasoning=[f"forced {status} production-contract result"],
            n_paths=int(context.n_paths),
            n_starts_attempted=1,
            stress_evaluations=stress_evaluations,
            goal_achievability=goal_achievability,
            context=context,
        )

    monkeypatch.setattr(solver_module, "run_solver", _fake_run_solver)
    return calls


def test_productive_solver_receives_exact_effective_inputs_and_materializes_exactly(
    session_factory,
    monkeypatch,
):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _client_id, mandate_id, _assessment_id = _seed_clean_mandate(
        session_factory, "prod-contract-inputs"
    )
    expected_weights = {
        "equities": 5000,
        "bonds": 3000,
        "real_estate": 500,
        "alternatives": 1000,
        "liquidity": 500,
    }
    calls = _install_solver_double(
        monkeypatch,
        weights_bps=expected_weights,
    )

    result = _generate(
        session_factory,
        mandate_id,
        advisor_id,
        _preferences(),
    )

    assert len(calls) == 1
    call = calls[0]
    assert call["sub_allocations"], "Produktiver Solver erhielt keinen Sub-Mix"
    assert call["effective_bounds_bps"] == {
        "equities": (4400, 5600),
        "bonds": (2600, 3600),
        "real_estate": (300, 1000),
        "alternatives": (500, 1000),
        "liquidity": (200, 1000),
    }
    assert list(call["context"].sub_allocations) == call["sub_allocations"]
    assert call["context"] is call["kwargs"]["optimizer_context"]
    assert call["context"].risky_fraction_per_bucket == call[
        "risky_fraction_per_bucket"
    ]

    target_allocation = result["target_allocation"]
    assert _weights(target_allocation) == expected_weights
    assert _band_pairs(target_allocation) == call["effective_bounds_bps"]
    assert target_allocation.optimization_method == "stochastic"
    assert target_allocation.optimization_status == "converged"

    final_sub_allocations = result["sub_allocations"]
    assert sum(int(row["target_weight_bps"]) for row in final_sub_allocations) == 10000
    for bucket, target_bps in expected_weights.items():
        assert sum(
            int(row["target_weight_bps"])
            for row in final_sub_allocations
            if pe._bucket_key(row.get("asset_class")) == bucket
        ) == target_bps
    assert _weighted_rows(final_sub_allocations) == _weighted_rows(
        _materialize_sub_allocation_plan(
            call["sub_allocations"],
            expected_weights,
        )
    )
    context_market = scenario_inputs_from_cma(
        call["kwargs"]["cma"],
        sub_allocations=call["sub_allocations"],
    )
    final_market = scenario_inputs_from_cma(
        call["kwargs"]["cma"],
        sub_allocations=final_sub_allocations,
    )
    assert np.array_equal(final_market.mu_bps, context_market.mu_bps)
    assert np.array_equal(final_market.sigma_bps, context_market.sigma_bps)

    final_risky = result["asset_class_risky_weights_bps"]
    for bucket in BUCKETS:
        assert call["risky_fraction_per_bucket"][bucket] == pytest.approx(
            int(final_risky[bucket]) / 10000.0,
            abs=1e-12,
        )


def test_converged_stochastic_enforces_maxilliquid_in_context_and_output(
    session_factory,
    monkeypatch,
):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _client_id, mandate_id, _assessment_id = _seed_clean_mandate(
        session_factory, "prod-contract-illiquid"
    )
    expected_weights = {
        "equities": 5000,
        "bonds": 3000,
        "real_estate": 500,
        "alternatives": 1000,
        "liquidity": 500,
    }
    calls = _install_solver_double(monkeypatch, weights_bps=expected_weights)

    result = _generate(
        session_factory,
        mandate_id,
        advisor_id,
        _preferences(max_illiquid="1"),
    )

    assert len(calls) == 1
    context_plan = calls[0]["sub_allocations"]
    # Context rows are bucket-relative: PE may occupy at most 10% of a bucket
    # whose hard upper bound is 10% of the total portfolio.
    assert _sub_weight(context_plan, "Private Equity") == 1000
    assert _sub_weight(context_plan, "Gold / Rohstoffe") == 9000
    assert _weighted_rows(result["sub_allocations"]) == _weighted_rows(
        _materialize_sub_allocation_plan(context_plan, expected_weights)
    )
    assert _sub_weight(result["sub_allocations"], "Private Equity") == 100
    assert _sub_weight(result["sub_allocations"], "Gold / Rohstoffe") == 900
    assert _weights(result["target_allocation"]) == expected_weights


def test_zero_weight_bucket_keeps_canonical_model_for_reload_and_sensitivity(
    session_factory,
    monkeypatch,
):
    """A dormant bucket remains modelled for later counterfactual allocations."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _client_id, mandate_id, _assessment_id, goal_id = (
        _seed_realistic_mandate(
            session_factory,
            suffix="prod-contract-zero-bucket",
        )
    )
    preferences = _preferences()
    preferences["bands"]["alternatives"]["min_bps"] = 0
    final_weights = {
        "equities": 5000,
        "bonds": 3500,
        "real_estate": 500,
        "alternatives": 0,
        "liquidity": 1000,
    }
    calls = _install_solver_double(
        monkeypatch,
        weights_bps=final_weights,
    )

    generated = _generate(
        session_factory,
        mandate_id,
        advisor_id,
        preferences,
    )

    assert len(calls) == 1
    generation_call = calls[0]
    generation_plan = generation_call["sub_allocations"]
    assert _sub_weight(generation_plan, "Gold / Rohstoffe") > 0
    assert _sub_weight(generation_plan, "Private Equity") > 0
    assert _weights(generated["target_allocation"]) == final_weights, {
        "status": generated["target_allocation"].optimization_status,
        "candidate_violations": solver_module.evaluate_weights(
            generation_call["context"], final_weights
        ).constraint_violations,
        "effective_bounds": generation_call["effective_bounds_bps"],
    }

    with session_factory() as session:
        allocation = session.query(TargetAllocation).filter(
            TargetAllocation.id == generated["target_allocation"].id
        ).one()
        persisted_rows = json.loads(allocation.sub_allocations_json)
        persisted_constraints = json.loads(allocation.effective_constraints_json)
        dormant_alternatives = [
            row for row in persisted_rows
            if pe._bucket_key(row.get("asset_class")) == "alternatives"
        ]
        assert dormant_alternatives, (
            "The zero-weight Alternatives bucket lost its canonical sub-model"
        )
        assert sum(
            int(row.get("target_weight_bps") or 0)
            for row in dormant_alternatives
        ) == 0
        assert sum(
            int(row.get("within_bucket_weight_bps") or 0)
            for row in dormant_alternatives
        ) == 10000
        assert _canonical_rows(persisted_rows) == _canonical_rows(generation_plan)
        assert persisted_constraints["risky_fraction_per_bucket_bps"][
            "alternatives"
        ] == int(round(
            generation_call["risky_fraction_per_bucket"]["alternatives"]
            * 10000
        ))

        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        sensitivity = pe.evaluate_goal_sensitivity(
            session,
            mandate,
            advisor_id,
            goal_id,
            target_delta_pct=10,
        )

    assert sensitivity["status_baseline"] == "converged"
    assert sensitivity["status_new"] == "converged"
    assert len(calls) == 3
    for sensitivity_call in calls[1:]:
        sensitivity_rows = sensitivity_call["sub_allocations"]
        assert _canonical_rows(sensitivity_rows) == _canonical_rows(
            generation_plan
        )
        assert sensitivity_call["effective_bounds_bps"] == generation_call[
            "effective_bounds_bps"
        ]
        for bucket in BUCKETS:
            assert sensitivity_call["risky_fraction_per_bucket"][
                bucket
            ] == pytest.approx(
                generation_call["risky_fraction_per_bucket"][bucket],
                abs=1e-12,
            )
        sensitivity_market = scenario_inputs_from_cma(
            sensitivity_call["kwargs"]["cma"],
            sub_allocations=sensitivity_rows,
        )
        generation_market = scenario_inputs_from_cma(
            generation_call["kwargs"]["cma"],
            sub_allocations=generation_plan,
        )
        assert np.array_equal(sensitivity_market.mu_bps, generation_market.mu_bps)
        assert np.array_equal(
            sensitivity_market.sigma_bps,
            generation_market.sigma_bps,
        )


def test_reload_uses_persisted_decision_artifacts_and_verifies_context_hash(
    session_factory,
    monkeypatch,
):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _client_id, mandate_id, _assessment_id = _seed_clean_mandate(
        session_factory, "prod-contract-reload"
    )
    expected_weights = {
        "equities": 5000,
        "bonds": 3000,
        "real_estate": 500,
        "alternatives": 1000,
        "liquidity": 500,
    }
    _install_solver_double(monkeypatch, weights_bps=expected_weights)
    generated = _generate(
        session_factory,
        mandate_id,
        advisor_id,
        _preferences(max_illiquid="1"),
    )
    allocation_id = generated["target_allocation"].id
    expected_rows = _weighted_rows(generated["sub_allocations"])

    # If reload attempts to reconstruct from current preferences/reference
    # data, fail loudly. A new stochastic allocation must own its exact rows.
    monkeypatch.setattr(
        pe,
        "_build_sub_allocations",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("historic sub-allocation was rebuilt")
        ),
    )

    with session_factory() as session:
        allocation = session.query(TargetAllocation).filter(
            TargetAllocation.id == allocation_id
        ).one()
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        policy = session.query(OptimizerPolicy).filter(
            OptimizerPolicy.id == allocation.policy_id
        ).one()
        cma = session.query(CapitalMarketAssumption).filter(
            CapitalMarketAssumption.id == allocation.capital_market_assumptions_id
        ).one()
        assessment = session.query(RiskAssessment).filter(
            RiskAssessment.id == allocation.based_on_assessment_id
        ).one()

        assert allocation.sub_allocations_json
        assert allocation.effective_constraints_json
        assert len(str(allocation.allocation_context_hash)) == 64
        reloaded = pe.build_target_payload_from_allocation(
            session,
            mandate,
            allocation,
            policy,
            cma,
            assessment,
            preferences=None,
        )

    assert _weighted_rows(reloaded["sub_allocations"]) == expected_rows
    assert _weights(reloaded["target_allocation"]) == expected_weights


def test_generate_and_reload_label_decision_and_implementation_model_bases(
    session_factory,
    monkeypatch,
):
    """Goal probabilities must identify which of the two model views produced them."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _client_id, mandate_id, _assessment_id, _goal_id = (
        _seed_realistic_mandate(
            session_factory,
            suffix="prod-contract-model-basis",
        )
    )
    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        mandate.tax_jurisdiction = "CH-ZH"
        session.commit()
    preferences = _preferences()
    preferences["simulation"].update({
        "rebalanceMode": "calendar",
        "transactionCostBps": 23,
    })
    _install_solver_double(
        monkeypatch,
        weights_bps={
            "equities": 5000,
            "bonds": 3000,
            "real_estate": 500,
            "alternatives": 1000,
            "liquidity": 500,
        },
    )
    generated = _generate(
        session_factory,
        mandate_id,
        advisor_id,
        preferences,
    )

    with session_factory() as session:
        allocation = session.query(TargetAllocation).filter(
            TargetAllocation.id == generated["target_allocation"].id
        ).one()
        reloaded = _reload_payload(session, allocation)

    for payload in (generated, reloaded):
        basis = payload["model_basis"]
        assert set(basis) == {"optimization", "reporting"}
        optimization = basis["optimization"]
        reporting = basis["reporting"]

        assert optimization["basis_id"] == "stochastic_decision_v2"
        assert optimization["purpose"] == "allocation_selection"
        assert optimization["portfolio_dynamics"] == "annual_constant_weight"
        assert optimization["liquidity_yield"] == "cma_total_return"
        assert optimization["transaction_cost_bps"] == 0
        assert optimization["return_moment_mapping"] == (
            "arithmetic_mean_and_volatility_preserved_v2"
        )
        assert optimization["tail_model"] == (
            "bounded_cornish_fisher_moment_calibrated_v2"
        )
        assert optimization["tail_calibration"] == (
            "bounded_cornish_fisher_gauss_hermite_v2"
        )
        assert optimization["foundation_model_version"] == (
            "external_foundation_v2"
        )
        assert optimization["external_property_goal_basis"] == (
            "inflation_zero_real_plus_exact_liability_and_pledged_transfer_v2"
        )

        assert reporting["basis_id"] == "implementation_projection_v2"
        assert reporting["purpose"] == "post_selection_projection"
        assert reporting["portfolio_dynamics"] == "calendar"
        assert reporting["transaction_cost_bps"] == 23
        assert reporting["liquidity_yield"] == (
            "zero_bucket_plus_position_interest_cashflow"
        )
        assert reporting["return_moment_mapping"] == (
            "arithmetic_mean_and_volatility_preserved_v2"
        )
        assert reporting["tail_model"] == "lognormal_arithmetic_moments_v2"
        assert reporting["tail_calibration"] == "not_applicable"
        assert reporting["foundation_model_version"] == "external_foundation_v2"
        assert reporting["total_scope_goal_basis"] == (
            "exact_total_projection_path_v2"
        )
        assert reporting["direct_real_estate_return_basis"] == (
            "position_price_appreciation_plus_explicit_rent_v2"
        )

        for model_view in (optimization, reporting):
            assert model_view["real_estate_return_basis"] == (
                "listed_real_estate_total_return_including_distributions_v1"
            )
            assert model_view["indirect_amortization_treatment"] == (
                "pledged_asset_transfer_v1"
            )
            assert model_view["direct_real_estate_scope"] == (
                "external_total_wealth"
            )
            assert model_view["external_rent_treatment"] == "cashflow_only"
        assert reporting.get("real_estate_income_basis") != (
            "cma_appreciation_plus_explicit_position_rent"
        )

        assert payload["goal_achievability_basis_id"] == optimization["basis_id"]
        assert payload["goal_analysis_basis_id"] == reporting["basis_id"]

    assert generated["model_basis"]["reporting"] == reloaded["model_basis"][
        "reporting"
    ]
    generated_optimization = generated["model_basis"]["optimization"]
    reloaded_optimization = reloaded["model_basis"]["optimization"]
    assert generated_optimization["n_paths"]
    assert generated_optimization["horizon_years"]
    assert generated_optimization["importance_sampling"] is True
    assert generated_optimization["tax_basis"].startswith("median_rate_")
    assert generated_optimization == reloaded_optimization


def test_reload_verifies_real_v1_context_hash_and_preserves_v1_basis(
    session_factory,
    monkeypatch,
):
    """The v2 deploy must not invalidate a fully hashed v1 decision artifact."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _client_id, mandate_id, _assessment_id = _seed_clean_mandate(
        session_factory,
        "prod-contract-v1-context-compat",
    )
    _install_solver_double(
        monkeypatch,
        weights_bps={
            "equities": 5000,
            "bonds": 3000,
            "real_estate": 500,
            "alternatives": 1000,
            "liquidity": 500,
        },
    )
    generated = _generate(
        session_factory,
        mandate_id,
        advisor_id,
        _preferences(),
    )

    with session_factory() as session:
        allocation = session.query(TargetAllocation).filter(
            TargetAllocation.id == generated["target_allocation"].id
        ).one()
        stored_rows = json.loads(allocation.sub_allocations_json)
        constraints_v1 = json.loads(allocation.effective_constraints_json)
        constraints_v1["engine_version"] = "stochastic_core_v1"

        basis_v1 = dict(constraints_v1["optimization_model_basis"])
        basis_v1["basis_id"] = "stochastic_decision_v1"
        basis_v1["tail_model"] = "cornish_fisher_cma_moments"
        for v2_only_field in (
            "return_moment_mapping",
            "tail_calibration",
            "foundation_model_version",
            "external_property_goal_basis",
            "indirect_amortization_treatment",
        ):
            basis_v1.pop(v2_only_field, None)
        constraints_v1["optimization_model_basis"] = basis_v1

        targets = _weights(allocation)
        v1_context_payload = {
            "engine_version": "stochastic_core_v1",
            "policy_id": str(allocation.policy_id),
            "cma_id": str(allocation.capital_market_assumptions_id),
            "assessment_id": str(allocation.based_on_assessment_id),
            "input_snapshot_hash": str(allocation.input_snapshot_hash),
            "preferences_json": allocation.preferences_json,
            "targets_bps": targets,
            "sub_allocations": stored_rows,
            "effective_constraints": constraints_v1,
            "optimization_seed": allocation.optimization_seed,
        }
        allocation.effective_constraints_json = json.dumps(
            constraints_v1,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        allocation.allocation_context_hash = hashlib.sha256(
            json.dumps(
                v1_context_payload,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()
        session.commit()

        reloaded = _reload_payload(session, allocation)

    assert reloaded["model_basis"]["optimization"] == basis_v1
    assert reloaded["goal_achievability_basis_id"] == "stochastic_decision_v1"
    assert reloaded["model_basis"]["reporting"]["basis_id"] == (
        "implementation_projection_v2"
    )


def test_advisory_direct_real_estate_fails_closed_before_solver(
    session_factory,
    monkeypatch,
):
    """Legacy/raw invalid data must not become a listed-RE optimizer bucket."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, client_id, mandate_id, _assessment_id = _seed_clean_mandate(
        session_factory,
        "prod-contract-advisory-direct-property",
    )
    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        session.add(WealthPosition(
            id=f"pos-invalid-advisory-property-{mandate_id}",
            client_id=client_id,
            label="Unzulässige Beratungs-Liegenschaft",
            position_type="Immobilien",
            assignment="Beratungsvermögen",
            current_value_rappen=1_000_000_00,
            currency="CHF",
            property_rental_income_rappen=30_000_00,
            property_rental_inflation_linked=0,
            asset_expected_return_bps=150,
            is_active=1,
            created_at=mandate.created_at,
            updated_at=mandate.updated_at,
        ))
        session.commit()

    calls = _install_solver_double(
        monkeypatch,
        weights_bps={
            "equities": 5000,
            "bonds": 3000,
            "real_estate": 500,
            "alternatives": 1000,
            "liquidity": 500,
        },
    )

    with pytest.raises(
        OptimizerInputError,
        match=r"Direktimmobilien.*Anderes Vermögen",
    ):
        _generate(session_factory, mandate_id, advisor_id, _preferences())

    assert calls == [], "Preflight must fail before run_solver and House fallback"
    with session_factory() as session:
        assert session.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mandate_id
        ).count() == 0
        assert session.query(OptimizerRun).filter(
            OptimizerRun.mandate_id == mandate_id
        ).count() == 0


def test_external_direct_property_rent_remains_reporting_and_solver_cashflow(
    session_factory,
):
    """External rent is funding; the external principal is not a solver asset."""
    advisor_id, client_id, mandate_id, _assessment_id = _seed_clean_mandate(
        session_factory,
        "prod-contract-external-property-rent",
    )
    annual_rent_rappen = 30_000_00
    position_id = f"pos-external-property-{mandate_id}"

    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        mandate.tax_estimate_in_cashflow_enabled = 0
        _policy, cma = pe.ensure_runtime_reference_data(session, advisor_id)
        baseline = pe._load_allocation_inputs(session, mandate, {}, cma=cma)
        session.add(WealthPosition(
            id=position_id,
            client_id=client_id,
            label="Externe Renditeliegenschaft",
            position_type="Immobilien",
            assignment="Anderes Vermögen",
            current_value_rappen=1_000_000_00,
            currency="CHF",
            property_rental_income_rappen=annual_rent_rappen,
            property_rental_inflation_linked=0,
            asset_expected_return_bps=150,
            is_active=1,
            created_at=mandate.created_at,
            updated_at=mandate.updated_at,
        ))
        session.flush()
        with_property = pe._load_allocation_inputs(session, mandate, {}, cma=cma)

    reporting_delta = [
        int(current) - int(original)
        for current, original in zip(
            with_property["cashflow_projection_series_rappen"],
            baseline["cashflow_projection_series_rappen"],
        )
    ]
    solver_delta = [
        int(current) - int(original)
        for current, original in zip(
            with_property["optimizer_cashflow_projection_series_rappen"],
            baseline["optimizer_cashflow_projection_series_rappen"],
        )
    ]

    assert reporting_delta and set(reporting_delta) == {annual_rent_rappen}
    assert solver_delta == reporting_delta
    assert with_property["advisory_wealth_rappen"] == baseline[
        "advisory_wealth_rappen"
    ]
    assert with_property["total_wealth_rappen"] == (
        baseline["total_wealth_rappen"] + 1_000_000_00
    )
    derived_rent = next(
        cashflow
        for cashflow in with_property["cashflows"]
        if getattr(cashflow, "origin_position_id", None) == position_id
    )
    assert str(derived_rent.id).startswith("derived:rental_income:")
    assert derived_rent.origin_assignment == "Anderes Vermögen"
    assert derived_rent.amount_rappen == annual_rent_rappen


def test_external_reserve_tax_remains_in_solver_cashflow_after_advisory_carve_out(
    session_factory,
    monkeypatch,
):
    """Only tax on the actually invested advisory pool is solver-dynamic.

    The reserve carved out before the SAA is economically external to the
    solver, just like ``Anderes Vermoegen``.  Both slices therefore have to
    remain in the solver cashflow while reporting still carries tax on total
    wealth.
    """
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, client_id, mandate_id, _assessment_id, _goal_id = (
        _seed_realistic_mandate(
            session_factory,
            suffix="prod-contract-reserve-tax-scope",
        )
    )
    external_reserve_rappen = 100_000_00
    preferences = _preferences()

    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        session.add(WealthPosition(
            id=f"pos-external-tax-{mandate_id}",
            client_id=client_id,
            label="Externes Vermoegen fuer Reserve-Steuervertrag",
            position_type="Depot",
            assignment="Anderes Vermögen",
            current_value_rappen=500_000_00,
            currency="CHF",
            alloc_liquidity_bps=10000,
            is_active=1,
            created_at=mandate.created_at,
            updated_at=mandate.updated_at,
        ))
        mandate.tax_jurisdiction = "CH"
        mandate.tax_overrides_json = None
        mandate.tax_estimate_in_cashflow_enabled = 0
        _policy, cma = pe.ensure_runtime_reference_data(session, advisor_id)
        session.flush()
        without_tax = pe._load_allocation_inputs(
            session,
            mandate,
            preferences["simulation"],
            cma=cma,
        )
        assert without_tax["advisory_wealth_rappen"] == 500_000_00
        assert without_tax["total_wealth_rappen"] == 1_000_000_00
        mandate.tax_estimate_in_cashflow_enabled = 1
        session.commit()

    # Isolate the accounting edge from reserve-sizing policy: the production
    # path still performs the real investable-base calculation and tax rebase.
    monkeypatch.setattr(
        pe,
        "_apply_goal_and_reserve_tilts",
        lambda **_kwargs: (external_reserve_rappen, external_reserve_rappen),
    )
    calls = _install_solver_double(
        monkeypatch,
        weights_bps={
            "equities": 5000,
            "bonds": 3000,
            "real_estate": 500,
            "alternatives": 1000,
            "liquidity": 500,
        },
    )

    generated = _generate(
        session_factory,
        mandate_id,
        advisor_id,
        preferences,
    )

    assert len(calls) == 1
    solver_kwargs = calls[0]["kwargs"]
    assert generated["external_reserve_rappen"] == external_reserve_rappen
    assert generated["investable_advisory_wealth_rappen"] == 400_000_00
    assert solver_kwargs["advisory_wealth_rappen"] == 400_000_00

    reporting_delta = [
        int(with_tax) - int(no_tax)
        for with_tax, no_tax in zip(
            generated["cashflow_projection_series_rappen"],
            without_tax["cashflow_projection_series_rappen"],
        )
    ]
    solver_delta = [
        int(with_tax) - int(no_tax)
        for with_tax, no_tax in zip(
            solver_kwargs["cashflow_series_rappen"],
            without_tax["optimizer_cashflow_projection_series_rappen"],
        )
    ]

    # CH default wealth-tax estimate is 40 bps: reporting sees 1.0m total;
    # the solver dynamically replaces only 400k investable advisory wealth.
    # Tax on 100k carved-out reserve + 500k Other Wealth therefore remains.
    assert reporting_delta and set(reporting_delta) == {-400_000}
    assert solver_delta == [-240_000] * len(reporting_delta)


def test_target_allocation_response_exposes_optimizer_audit_fields():
    required_fields = {
        "optimization_method",
        "optimization_status",
        "optimization_seed",
        "optimization_iterations",
        "optimization_objective_value_milli",
    }

    assert required_fields <= set(TargetAllocationResponse.model_fields)


@pytest.mark.parametrize(
    ("optimizer_mode", "optimizer_result", "allocation", "expected_basis_id"),
    [
        pytest.param(
            "stochastic",
            SimpleNamespace(
                context=None,
                method="fallback_house_matrix",
                seed=0,
                n_paths=0,
            ),
            None,
            "house_matrix_fallback_v1",
            id="no-context-fallback",
        ),
        pytest.param(
            "house_matrix",
            None,
            SimpleNamespace(
                optimization_method=None,
                optimization_seed=None,
                shadow_optimization_json=None,
            ),
            "house_matrix_policy_v1",
            id="legacy-house-matrix",
        ),
        pytest.param(
            "stochastic",
            None,
            SimpleNamespace(
                optimization_method="stochastic",
                optimization_seed=17,
                shadow_optimization_json=None,
            ),
            "stochastic_legacy_unverified_v0",
            id="legacy-stochastic-without-context-snapshot",
        ),
        pytest.param(
            "house_matrix",
            None,
            SimpleNamespace(
                optimization_method=None,
                optimization_seed=None,
                shadow_optimization_json="{}",
            ),
            "stochastic_shadow_legacy_unverified_v0",
            id="legacy-shadow-without-context-snapshot",
        ),
    ],
)
def test_basis_without_stochastic_context_does_not_claim_stochastic_decision(
    optimizer_mode,
    optimizer_result,
    allocation,
    expected_basis_id,
):
    basis = pe._build_allocation_model_basis(
        optimizer_mode=optimizer_mode,
        optimizer_result=optimizer_result,
        allocation=allocation,
        monte_carlo={},
        simulation_prefs={},
        mandate=SimpleNamespace(tax_estimate_in_cashflow_enabled=0),
    )

    assert basis["optimization"]["basis_id"] == expected_basis_id


def test_model_basis_does_not_claim_ineffective_tax_regime():
    from services.tax.regimes.de import DETaxRegime

    context = SimpleNamespace(
        n_paths=48,
        horizon_years=10,
        scenario_weights=None,
        tax_regime=DETaxRegime(),
        dividend_yield_bps_per_bucket=None,
    )
    basis = pe._build_allocation_model_basis(
        optimizer_mode="stochastic",
        optimizer_result=SimpleNamespace(
            context=context,
            method="stochastic",
            seed=17,
            n_paths=48,
        ),
        allocation=None,
        monte_carlo={},
        simulation_prefs={},
        mandate=SimpleNamespace(tax_estimate_in_cashflow_enabled=0),
    )

    assert basis["optimization"]["tax_basis"] == "none_effective_DETaxRegime"


def test_reload_rejects_tampered_persisted_suballocation(
    session_factory,
    monkeypatch,
):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _client_id, mandate_id, _assessment_id = _seed_clean_mandate(
        session_factory, "prod-contract-tamper"
    )
    _install_solver_double(
        monkeypatch,
        weights_bps={
            "equities": 5000,
            "bonds": 3000,
            "real_estate": 500,
            "alternatives": 1000,
            "liquidity": 500,
        },
    )
    generated = _generate(
        session_factory, mandate_id, advisor_id, _preferences()
    )

    with session_factory() as session:
        allocation = session.query(TargetAllocation).filter(
            TargetAllocation.id == generated["target_allocation"].id
        ).one()
        rows = json.loads(allocation.sub_allocations_json)
        rows[0]["target_weight_bps"] = int(rows[0]["target_weight_bps"]) + 1
        allocation.sub_allocations_json = json.dumps(rows)
        session.commit()

        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        policy = session.query(OptimizerPolicy).filter(
            OptimizerPolicy.id == allocation.policy_id
        ).one()
        cma = session.query(CapitalMarketAssumption).filter(
            CapitalMarketAssumption.id == allocation.capital_market_assumptions_id
        ).one()
        assessment = session.query(RiskAssessment).filter(
            RiskAssessment.id == allocation.based_on_assessment_id
        ).one()

        with pytest.raises(ValueError, match=INTEGRITY_ERROR_PATTERN):
            pe.build_target_payload_from_allocation(
                session,
                mandate,
                allocation,
                policy,
                cma,
                assessment,
                preferences=None,
            )


def test_reload_rejects_partial_artifact_state_with_null_hash(
    session_factory,
    monkeypatch,
):
    """A new allocation may never silently downgrade itself to legacy mode."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _client_id, mandate_id, _assessment_id = _seed_clean_mandate(
        session_factory, "prod-contract-partial-artifact"
    )
    _install_solver_double(
        monkeypatch,
        weights_bps={
            "equities": 5000,
            "bonds": 3000,
            "real_estate": 500,
            "alternatives": 1000,
            "liquidity": 500,
        },
    )
    generated = _generate(
        session_factory, mandate_id, advisor_id, _preferences()
    )

    with session_factory() as session:
        allocation = session.query(TargetAllocation).filter(
            TargetAllocation.id == generated["target_allocation"].id
        ).one()
        assert allocation.sub_allocations_json
        assert allocation.effective_constraints_json
        assert allocation.allocation_context_hash
        allocation.allocation_context_hash = None
        session.commit()

        with pytest.raises(ValueError, match=INTEGRITY_ERROR_PATTERN):
            _reload_payload(session, allocation)


def test_reload_allows_genuine_legacy_state_without_any_context_artifact(
    session_factory,
    monkeypatch,
):
    """All-null artifact columns remain the explicit pre-context legacy state."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _client_id, mandate_id, _assessment_id = _seed_clean_mandate(
        session_factory, "prod-contract-genuine-legacy"
    )
    _install_solver_double(
        monkeypatch,
        weights_bps={
            "equities": 5000,
            "bonds": 3000,
            "real_estate": 500,
            "alternatives": 1000,
            "liquidity": 500,
        },
    )
    generated = _generate(
        session_factory, mandate_id, advisor_id, _preferences()
    )

    with session_factory() as session:
        allocation = session.query(TargetAllocation).filter(
            TargetAllocation.id == generated["target_allocation"].id
        ).one()
        # Alembic backfills the explicit discriminator with 0 for genuine
        # rows from before immutable decision artefacts existed.
        allocation.context_artifacts_required = 0
        allocation.sub_allocations_json = None
        allocation.effective_constraints_json = None
        allocation.allocation_context_hash = None
        session.commit()

        reloaded = _reload_payload(session, allocation)

    assert _weights(reloaded["target_allocation"]) == {
        "equities": 5000,
        "bonds": 3000,
        "real_estate": 500,
        "alternatives": 1000,
        "liquidity": 500,
    }
    assert sum(
        int(row["target_weight_bps"])
        for row in reloaded["sub_allocations"]
    ) == 10000


def test_reload_rejects_modern_allocation_with_all_context_artifacts_removed(
    session_factory,
    monkeypatch,
):
    """Deleting all three payloads cannot disguise a modern row as legacy."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _client_id, mandate_id, _assessment_id = _seed_clean_mandate(
        session_factory, "prod-contract-modern-all-null"
    )
    _install_solver_double(
        monkeypatch,
        weights_bps={
            "equities": 5000,
            "bonds": 3000,
            "real_estate": 500,
            "alternatives": 1000,
            "liquidity": 500,
        },
    )
    generated = _generate(
        session_factory, mandate_id, advisor_id, _preferences()
    )

    with session_factory() as session:
        allocation = session.query(TargetAllocation).filter(
            TargetAllocation.id == generated["target_allocation"].id
        ).one()
        assert allocation.context_artifacts_required == 1
        allocation.sub_allocations_json = None
        allocation.effective_constraints_json = None
        allocation.allocation_context_hash = None
        session.commit()

        with pytest.raises(ValueError, match="Context.*fehlt|Artefakte"):
            _reload_payload(session, allocation)


def test_reload_hash_rejects_intra_bucket_tamper_with_unchanged_sums(
    session_factory,
    monkeypatch,
):
    """Exercise SHA verification, not the cheaper bucket-sum validation."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _client_id, mandate_id, _assessment_id = _seed_clean_mandate(
        session_factory, "prod-contract-hash-specific"
    )
    _install_solver_double(
        monkeypatch,
        weights_bps={
            "equities": 5000,
            "bonds": 3000,
            "real_estate": 500,
            "alternatives": 1000,
            "liquidity": 500,
        },
    )
    generated = _generate(
        session_factory, mandate_id, advisor_id, _preferences()
    )

    with session_factory() as session:
        allocation = session.query(TargetAllocation).filter(
            TargetAllocation.id == generated["target_allocation"].id
        ).one()
        rows = json.loads(allocation.sub_allocations_json)
        alternatives = [
            row for row in rows
            if pe._bucket_key(row.get("asset_class")) == "alternatives"
        ]
        assert len(alternatives) >= 2
        donor = next(
            row for row in alternatives
            if int(row.get("target_weight_bps") or 0) > 0
        )
        receiver = next(row for row in alternatives if row is not donor)
        original_bucket_total = sum(
            int(row.get("target_weight_bps") or 0) for row in alternatives
        )
        donor["target_weight_bps"] = int(donor["target_weight_bps"]) - 1
        receiver["target_weight_bps"] = int(receiver["target_weight_bps"]) + 1
        assert sum(
            int(row.get("target_weight_bps") or 0) for row in alternatives
        ) == original_bucket_total
        assert sum(int(row.get("target_weight_bps") or 0) for row in rows) == 10000
        allocation.sub_allocations_json = json.dumps(
            rows,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        session.commit()

        with pytest.raises(ValueError, match="Context-Hash"):
            _reload_payload(session, allocation)


def test_sensitivity_rejects_context_hash_tamper_before_solver(
    session_factory,
    monkeypatch,
):
    """Sensitivity may consume only a verified persisted decision context."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _client_id, mandate_id, _assessment_id, goal_id = (
        _seed_realistic_mandate(
            session_factory,
            suffix="prod-contract-sensitivity-hash",
        )
    )
    calls = _install_solver_double(
        monkeypatch,
        weights_bps={
            "equities": 5000,
            "bonds": 3000,
            "real_estate": 500,
            "alternatives": 1000,
            "liquidity": 500,
        },
    )
    generated = _generate(
        session_factory, mandate_id, advisor_id, _preferences()
    )
    assert len(calls) == 1

    with session_factory() as session:
        allocation = session.query(TargetAllocation).filter(
            TargetAllocation.id == generated["target_allocation"].id
        ).one()
        stored_hash = allocation.allocation_context_hash
        rows = json.loads(allocation.sub_allocations_json)
        alternatives = [
            row for row in rows
            if pe._bucket_key(row.get("asset_class")) == "alternatives"
        ]
        assert len(alternatives) >= 2
        donor = next(
            row for row in alternatives
            if int(row.get("target_weight_bps") or 0) > 0
        )
        receiver = next(row for row in alternatives if row is not donor)
        original_bucket_total = sum(
            int(row.get("target_weight_bps") or 0) for row in alternatives
        )
        donor["target_weight_bps"] = int(donor["target_weight_bps"]) - 1
        receiver["target_weight_bps"] = int(
            receiver.get("target_weight_bps") or 0
        ) + 1
        assert sum(
            int(row.get("target_weight_bps") or 0) for row in alternatives
        ) == original_bucket_total
        assert sum(int(row.get("target_weight_bps") or 0) for row in rows) == 10000
        allocation.sub_allocations_json = json.dumps(
            rows,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        session.commit()
        assert allocation.allocation_context_hash == stored_hash

        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        with pytest.raises(ValueError, match=r"Integrit|Context-Hash"):
            pe.evaluate_goal_sensitivity(
                session,
                mandate,
                advisor_id,
                goal_id,
                target_delta_pct=10,
            )

    assert len(calls) == 1, "Sensitivity reached run_solver before integrity gate"


@pytest.mark.parametrize(
    "field_name",
    [
        "band_equities_max_bps",
        "risk_budget_bps_at_generation",
        "risky_fraction_bps_at_generation",
        "optimization_method",
        "optimization_status",
    ],
)
def test_reload_rejects_typed_context_field_that_disagrees_with_hashed_constraints(
    session_factory,
    monkeypatch,
    field_name,
):
    """Typed query fields and hashed JSON must never become two truths."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    suffix = field_name.replace("_bps_at_generation", "").replace("_", "-")
    advisor_id, _client_id, mandate_id, _assessment_id = _seed_clean_mandate(
        session_factory, f"prod-contract-typed-{suffix}"
    )
    _install_solver_double(
        monkeypatch,
        weights_bps={
            "equities": 5000,
            "bonds": 3000,
            "real_estate": 500,
            "alternatives": 1000,
            "liquidity": 500,
        },
    )
    generated = _generate(
        session_factory, mandate_id, advisor_id, _preferences()
    )

    with session_factory() as session:
        allocation = session.query(TargetAllocation).filter(
            TargetAllocation.id == generated["target_allocation"].id
        ).one()
        original = getattr(allocation, field_name)
        assert original is not None
        if isinstance(original, int):
            setattr(allocation, field_name, int(original) + 1)
        else:
            setattr(allocation, field_name, "tampered_context_value")
        session.commit()

        with pytest.raises(ValueError, match=INTEGRITY_ERROR_PATTERN):
            _reload_payload(session, allocation)


def test_solver_exception_uses_audited_exact_house_fallback(
    session_factory,
    monkeypatch,
):
    advisor_id, _client_id, mandate_id, _assessment_id = _seed_clean_mandate(
        session_factory, "prod-contract-exception"
    )
    prefs = _preferences()

    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")
    house_result = _generate(session_factory, mandate_id, advisor_id, prefs)
    expected_house_weights = _weights(house_result["target_allocation"])
    crashing_calls = []

    def _crashing_solver(**kwargs):
        crashing_calls.append(kwargs)
        raise solver_module.SolverTechnicalError(
            "forced production solver crash"
        )

    monkeypatch.setattr(solver_module, "run_solver", _crashing_solver)
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    fallback = _generate(session_factory, mandate_id, advisor_id, prefs)
    target_allocation = fallback["target_allocation"]

    assert _weights(target_allocation) == expected_house_weights
    assert len(crashing_calls) == 1
    assert _weighted_rows(fallback["sub_allocations"]) == _weighted_rows(
        _materialize_sub_allocation_plan(
            crashing_calls[0]["sub_allocations"], expected_house_weights
        )
    )
    assert target_allocation.optimization_method == "fallback_house_matrix"
    assert target_allocation.optimization_status == "fallback_house_matrix"
    assert target_allocation.optimization_seed is not None
    assert fallback["goal_achievability"] == []
    # The retained single context lets fallback analytics be recomputed on the
    # active House weights instead of being empty or describing the rejected
    # solver candidate.
    assert isinstance(fallback["stress_evaluations"], dict)
    assert fallback["stress_evaluations"]

    with session_factory() as session:
        run = session.query(OptimizerRun).filter(
            OptimizerRun.target_allocation_id == target_allocation.id
        ).one()
        assert run.method == "fallback_house_matrix"
        assert run.status == "fallback_house_matrix"
        assert json.loads(run.weights_bps_json) == expected_house_weights
        assert "SolverTechnicalError" in (run.reasoning_json or "")


@pytest.mark.parametrize(
    "preferences",
    [
        pytest.param(_invalid_real_estate_preferences(), id="manual-re-min-over-global-cap"),
        pytest.param(
            _preferences(max_illiquid="1", pe_only=True),
            id="pe-only-minimum-over-illiquidity-cap",
        ),
    ],
)
def test_hard_domain_errors_are_not_converted_to_house_fallback(
    session_factory,
    monkeypatch,
    preferences,
):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _client_id, mandate_id, _assessment_id = _seed_clean_mandate(
        session_factory, f"prod-contract-domain-{preferences['bands']['real_estate']['target_bps']}"
    )

    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        with pytest.raises(ValueError):
            pe.generate_target_allocation(
                session,
                mandate,
                advisor_id,
                preferences=preferences,
            )
        session.rollback()

    with session_factory() as session:
        assert session.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mandate_id
        ).count() == 0
        assert session.query(OptimizerRun).filter(
            OptimizerRun.mandate_id == mandate_id
        ).count() == 0


def test_fallback_analytics_are_recomputed_for_active_house_weights(
    session_factory,
    monkeypatch,
):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _client_id, mandate_id, _assessment_id = _seed_clean_mandate(
        session_factory, "prod-contract-fallback-analytics"
    )
    candidate_analytics = ({
        "goal_id": "discarded-candidate-only",
        "label": "Discarded candidate",
        "probability": 0.01,
        "tau": 0.99,
        "status": "nicht_erreichbar",
        "hardness": "hart",
    },)
    calls = _install_solver_double(
        monkeypatch,
        weights_bps={
            "equities": 4400,
            "bonds": 3600,
            "real_estate": 500,
            "alternatives": 500,
            "liquidity": 1000,
        },
        status="fallback_house_matrix",
        method="fallback_house_matrix",
        goal_achievability=candidate_analytics,
        stress_evaluations={"discarded_candidate": {"marker": True}},
    )
    active_analytics = [{
        "goal_id": "active-house-fallback",
        "label": "Active fallback",
        "probability": 1.0,
        "tau": 0.0,
        "status": "erreichbar",
        "hardness": "primaer",
    }]

    def _active_penalty(*_args, **_kwargs):
        return 0.0, list(active_analytics)

    monkeypatch.setattr(objective_module, "chance_constraint_penalty", _active_penalty)

    result = _generate(
        session_factory,
        mandate_id,
        advisor_id,
        _preferences(),
    )

    assert len(calls) == 1
    target_allocation = result["target_allocation"]
    assert target_allocation.optimization_method == "fallback_house_matrix"
    assert result["goal_achievability"] == active_analytics
    assert all(
        row.get("goal_id") != "discarded-candidate-only"
        for row in result["goal_achievability"]
    )
    assert result["stress_evaluations"] != {
        "discarded_candidate": {"marker": True}
    }

    with session_factory() as session:
        run = session.query(OptimizerRun).filter(
            OptimizerRun.target_allocation_id == target_allocation.id
        ).one()
        assert json.loads(run.weights_bps_json) == _weights(target_allocation)
        assert json.loads(target_allocation.goal_achievability_json) == active_analytics


def test_invalid_converged_candidate_is_rejected_before_materialization(
    session_factory,
    monkeypatch,
):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _client_id, mandate_id, _assessment_id = _seed_clean_mandate(
        session_factory, "prod-contract-invalid-candidate"
    )
    calls = _install_solver_double(
        monkeypatch,
        weights_bps={
            "equities": 6000,  # manual maximum is 5600
            "bonds": 2000,
            "real_estate": 500,
            "alternatives": 1000,
            "liquidity": 500,
        },
    )

    result = _generate(
        session_factory,
        mandate_id,
        advisor_id,
        _preferences(),
    )

    assert len(calls) == 1
    target_allocation = result["target_allocation"]
    assert target_allocation.optimization_method == "fallback_house_matrix"
    assert target_allocation.optimization_status == "fallback_house_matrix"
    assert _weights(target_allocation) != calls[0]["candidate_weights_bps"]
    assert _weights(target_allocation)["equities"] <= 5600

    with session_factory() as session:
        run = session.query(OptimizerRun).filter(
            OptimizerRun.target_allocation_id == target_allocation.id
        ).one()
        # This list describes only the effective House allocation and is empty
        # because that active fallback is feasible. Rejected-candidate details
        # remain explicitly scoped in the decision envelope.
        assert json.loads(run.constraint_violations_json or "[]") == []
        assert "Abschlussvalidierung" in (run.reasoning_json or "")
        rejection_audit = json.loads(run.robustification_json)
        assert rejection_audit["final_reason"] == "activation_validation_failed"
        assert rejection_audit["effective_allocation_feasible"] is True
        assert rejection_audit["rejected_weights_bps"] == calls[0][
            "candidate_weights_bps"
        ]
        assert any(
            "activation_validation" in item
            for item in rejection_audit[
                "rejected_candidate_constraint_violations"
            ]
        )


@pytest.mark.parametrize(
    ("field", "changed_value"),
    [
        ("weight_bps", 1234),
        ("pension_pillar", "AHV"),
    ],
)
def test_reload_fails_closed_when_solver_relevant_goal_input_drifts(
    session_factory,
    monkeypatch,
    field,
    changed_value,
):
    """Reload must not publish persisted targets with a live goal analysis."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _client_id, mandate_id, _assessment_id, goal_id = (
        _seed_realistic_mandate(
            session_factory,
            suffix=f"prod-contract-stale-{field}",
        )
    )
    _install_solver_double(
        monkeypatch,
        weights_bps={
            "equities": 5000,
            "bonds": 3000,
            "real_estate": 500,
            "alternatives": 1000,
            "liquidity": 500,
        },
    )
    generated = _generate(
        session_factory,
        mandate_id,
        advisor_id,
        _preferences(),
    )

    with session_factory() as session:
        goal = session.query(Goal).filter(Goal.id == goal_id).one()
        setattr(goal, field, changed_value)
        session.commit()

    with session_factory() as session:
        allocation = session.query(TargetAllocation).filter(
            TargetAllocation.id == generated["target_allocation"].id
        ).one()
        with pytest.raises(ValueError, match="veraltet|neu berechnen"):
            _reload_payload(session, allocation)


def test_current_payload_route_maps_goal_drift_to_http_409(
    session_factory,
    monkeypatch,
):
    """The public route exposes stale strategy state as a domain conflict."""
    from models.users import User
    from routers.allocation import get_current_allocation_payload

    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _client_id, mandate_id, _assessment_id, goal_id = (
        _seed_realistic_mandate(
            session_factory,
            suffix="prod-contract-stale-route",
        )
    )
    _install_solver_double(
        monkeypatch,
        weights_bps={
            "equities": 5000,
            "bonds": 3000,
            "real_estate": 500,
            "alternatives": 1000,
            "liquidity": 500,
        },
    )
    _generate(session_factory, mandate_id, advisor_id, _preferences())

    with session_factory() as session:
        goal = session.query(Goal).filter(Goal.id == goal_id).one()
        goal.weight_bps = int(goal.weight_bps or 0) + 1
        session.commit()

        advisor = session.query(User).filter(User.id == advisor_id).one()
        with pytest.raises(HTTPException) as exc_info:
            get_current_allocation_payload(
                mandate_id=mandate_id,
                db=session,
                current_user=advisor,
            )

    assert exc_info.value.status_code == 409
    assert "veraltet" in str(exc_info.value.detail)


def test_reload_fails_closed_when_wealth_inflow_query_fails(
    session_factory,
    monkeypatch,
):
    """A DB/schema failure must never masquerade as an empty inflow set."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _client_id, mandate_id, _assessment_id = _seed_clean_mandate(
        session_factory,
        "prod-contract-inflow-query-failure",
    )
    _install_solver_double(
        monkeypatch,
        weights_bps={
            "equities": 5000,
            "bonds": 3000,
            "real_estate": 500,
            "alternatives": 1000,
            "liquidity": 500,
        },
    )
    generated = _generate(
        session_factory,
        mandate_id,
        advisor_id,
        _preferences(),
    )

    original_all = Query.all

    def _fail_wealth_inflow_query(query):
        descriptions = query.column_descriptions
        if descriptions and descriptions[0].get("entity") is WealthInflow:
            raise RuntimeError("wealth inflow query unavailable")
        return original_all(query)

    monkeypatch.setattr(Query, "all", _fail_wealth_inflow_query)

    with session_factory() as session:
        allocation = session.query(TargetAllocation).filter(
            TargetAllocation.id == generated["target_allocation"].id
        ).one()
        with pytest.raises(RuntimeError, match="wealth inflow query unavailable"):
            _reload_payload(session, allocation)


def test_reload_fails_closed_when_referenced_cma_is_missing(
    session_factory,
    monkeypatch,
):
    """A current CMA may never impersonate a missing generation snapshot."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _client_id, mandate_id, _assessment_id = _seed_clean_mandate(
        session_factory,
        "prod-contract-missing-cma",
    )
    _install_solver_double(
        monkeypatch,
        weights_bps={
            "equities": 5000,
            "bonds": 3000,
            "real_estate": 500,
            "alternatives": 1000,
            "liquidity": 500,
        },
    )
    generated = _generate(
        session_factory,
        mandate_id,
        advisor_id,
        _preferences(),
    )

    with session_factory() as session:
        allocation = session.query(TargetAllocation).filter(
            TargetAllocation.id == generated["target_allocation"].id
        ).one()
        cma = session.query(CapitalMarketAssumption).filter(
            CapitalMarketAssumption.id
            == allocation.capital_market_assumptions_id
        ).one()
        session.delete(cma)
        session.commit()

    with session_factory() as session:
        allocation = session.query(TargetAllocation).filter(
            TargetAllocation.id == generated["target_allocation"].id
        ).one()
        mandate = session.query(Mandate).filter(
            Mandate.id == allocation.mandate_id
        ).one()
        policy = session.query(OptimizerPolicy).filter(
            OptimizerPolicy.id == allocation.policy_id
        ).one()
        assessment = session.query(RiskAssessment).filter(
            RiskAssessment.id == allocation.based_on_assessment_id
        ).one()
        with pytest.raises(ValueError, match="referenzierte CMA.*nicht mehr"):
            pe.build_target_payload_from_allocation(
                session,
                mandate,
                allocation,
                policy,
                SimpleNamespace(id="current-replacement-cma"),
                assessment,
                preferences=None,
            )


def test_reload_accepts_unchanged_historical_v3_projection_anchor(
    session_factory,
    monkeypatch,
):
    """An unchanged v3 allocation remains readable after v4 activation."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _client_id, mandate_id, _assessment_id = _seed_clean_mandate(
        session_factory,
        "prod-contract-historical-v3",
    )
    _install_solver_double(
        monkeypatch,
        weights_bps={
            "equities": 5000,
            "bonds": 3000,
            "real_estate": 500,
            "alternatives": 1000,
            "liquidity": 500,
        },
    )
    generated = _generate(
        session_factory,
        mandate_id,
        advisor_id,
        _preferences(),
    )

    original_hash = pe._compute_input_snapshot_hash
    observed_v3_hashes: list[str] = []

    def _capture_v3_hash(**kwargs):
        result = original_hash(**kwargs)
        if kwargs.get("snapshot_version") == "strategy_inputs_v3_projection_context":
            observed_v3_hashes.append(result)
        return result

    monkeypatch.setattr(pe, "_compute_input_snapshot_hash", _capture_v3_hash)
    with session_factory() as session:
        allocation = session.query(TargetAllocation).filter(
            TargetAllocation.id == generated["target_allocation"].id
        ).one()
        _reload_payload(session, allocation)
        assert observed_v3_hashes

        allocation.input_snapshot_hash = observed_v3_hashes[-1]
        stored_sub_allocations = json.loads(allocation.sub_allocations_json)
        stored_constraints = json.loads(allocation.effective_constraints_json)
        historical_context_payload = {
            "engine_version": str(stored_constraints["engine_version"]),
            "policy_id": str(allocation.policy_id),
            "cma_id": str(allocation.capital_market_assumptions_id),
            "assessment_id": str(allocation.based_on_assessment_id),
            "input_snapshot_hash": str(allocation.input_snapshot_hash),
            "preferences_json": allocation.preferences_json,
            "targets_bps": _weights(allocation),
            "sub_allocations": stored_sub_allocations,
            "effective_constraints": stored_constraints,
            "optimization_seed": allocation.optimization_seed,
        }
        allocation.allocation_context_hash = hashlib.sha256(
            json.dumps(
                historical_context_payload,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()
        session.commit()
        reloaded = _reload_payload(session, allocation)

    assert reloaded["target_allocation"].id == generated["target_allocation"].id
