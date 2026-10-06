"""CMA-TAIL-ACTIVATION-GOVERNANCE-001 (Kontrollrunde 50, P2).

Finding
-------
The stochastic optimizer (services/optimizer/scenario_engine.py) ALWAYS runs
each bucket's CMA moments through the Cornish-Fisher tail transform --
``_log_parameters_for_inputs`` calls
``arithmetic_moments_to_log_parameters(..., use_cornish_fisher=True)``
unconditionally, for every bucket, regardless of any preference.

The general-purpose reporting Monte Carlo engine
(``_run_allocation_monte_carlo`` in services/portfolio_engine_mc_simulation.py)
only does the same when a ``tailRisk``/``cornishFisher`` simulation
preference is explicitly set to True. The gate is ``_simulation_use_tail_risk``,
which defaults to False when the preference is absent:

    def _simulation_use_tail_risk(simulation_prefs: dict | None) -> bool:
        if not simulation_prefs:
            return False
        raw = simulation_prefs.get("tailRisk") or simulation_prefs.get("cornishFisher")
        ...

Both pipelines compute each bucket's (mu, sigma) from the SAME single
source of truth (``services.portfolio_engine._weighted_bucket_metrics``) and
read the SAME per-bucket skew/kurtosis fields off the SAME CMA row. The only
difference is the ``use_cornish_fisher`` flag each pipeline passes into the
shared ``arithmetic_moments_to_log_parameters`` calibration. With nonzero
skew/kurtosis, that flag changes the resulting log-location/log-scale pair
non-trivially (see services/return_moments.py:
``_tail_log_parameters_cached`` recalibrates the lognormal scale via
Gauss-Hermite quadrature when the flag is True; with it False the tail
moments are simply discarded).

Net effect: for the identical CMA, with no explicit tail-risk preference
set, the optimizer's candidate selection / goal-probability math bakes the
tail moments in while the customer-facing reporting projection silently
falls back to a plain lognormal -- two different "success probability"
models from the same inputs, with no reconciliation and no UI warning
(see 5eyes-electron/frontend/5eyes_v2.html, which renders a bare
``tail_model`` string with no control to align the two).

This test builds a real optimizer scenario-path run AND a real reporting
Monte Carlo run from the identical CMA (same nonzero equities skew/kurt),
with default/absent simulation preferences, and asserts both apply the SAME
tail-model treatment. It currently fails for exactly the documented reason.

See docs/audits/2026-10-05-cma-correlation-tail-moment-and-runtime-parity-integrity-audit.md.
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest
from sqlalchemy.orm import configure_mappers

from database import Base  # noqa: F401
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)

configure_mappers()

import services.portfolio_engine as pe
from services.portfolio_engine import (
    BUCKET_FIELDS,
    PortfolioSummary,
    _run_allocation_monte_carlo,
    _weighted_bucket_metrics,
)
from services.portfolio_engine_mc_simulation import _simulation_use_tail_risk
from services.optimizer.scenario_engine import (
    build_scenario_paths,
    scenario_inputs_from_cma,
)
from services.return_moments import arithmetic_moments_to_log_parameters
from models.allocation import CapitalMarketAssumption


# Nonzero, monotonic-safe tail moments on the equities bucket (same magnitude
# as the established skew=-0.4/excess_kurt=1.5 pair already used elsewhere in
# this suite, e.g. tests/test_optimizer_scenario_engine.py).
_EQUITIES_SKEW_BPS = -4000
_EQUITIES_EXCESS_KURT_BPS = 15000


def _cma_with_tail_moments() -> CapitalMarketAssumption:
    """ONE CMA row, fed into BOTH the stochastic optimizer and the reporting MC."""
    return CapitalMarketAssumption(
        id="cma-tailgov-001", assumption_set_name="TailGov", version=1,
        valid_from="2026-01-01", is_current=1,
        bonds_chf_ig_return_bps=220, bonds_chf_ig_vol_bps=350,
        bonds_fx_hedged_return_bps=220, bonds_fx_hedged_vol_bps=430,
        equity_ch_return_bps=620, equity_ch_vol_bps=1450,
        equity_intl_return_bps=700, equity_intl_vol_bps=1600,
        real_estate_ch_return_bps=450, real_estate_ch_vol_bps=820,
        alternatives_gold_return_bps=300, alternatives_gold_vol_bps=1200,
        liquidity_return_bps=80, liquidity_vol_bps=20,
        correlation_matrix_json="", sub_asset_class_assumptions_json="",
        equities_skewness_bps=_EQUITIES_SKEW_BPS,
        equities_excess_kurt_bps=_EQUITIES_EXCESS_KURT_BPS,
        bonds_skewness_bps=0, bonds_excess_kurt_bps=0,
        real_estate_skewness_bps=0, real_estate_excess_kurt_bps=0,
        alternatives_skewness_bps=0, alternatives_excess_kurt_bps=0,
        liquidity_skewness_bps=0, liquidity_excess_kurt_bps=0,
        created_by="test", created_at="2026-01-01T00:00:00.000Z",
        updated_at="2026-01-01T00:00:00.000Z",
    )


@pytest.fixture(autouse=True)
def _fixed_sims(monkeypatch):
    monkeypatch.setattr(pe, "_monte_carlo_simulations", lambda prefs: 500)


def _reporting_kwargs(cma: CapitalMarketAssumption, simulation_prefs: dict | None) -> dict:
    horizon = [0] * 8  # no cashflows, keep the run minimal
    advisory = PortfolioSummary(
        amounts_rappen={key: (100_000_00 if key == "equities" else 0) for key in BUCKET_FIELDS},
        total_rappen=100_000_00,
    )
    return dict(
        advisory_summary=advisory,
        cashflow_projection_series_rappen=horizon,
        goal_inflation_series_bps=[0] * len(horizon),
        targets={key: (10000 if key == "equities" else 0) for key in BUCKET_FIELDS},
        minimums={key: 0 for key in BUCKET_FIELDS},
        maximums={key: 10000 for key in BUCKET_FIELDS},
        cma=cma,
        goals=[],
        advisory_wealth_rappen=advisory.total_rappen,
        total_wealth_rappen=advisory.total_rappen,
        policy=None,
        mandate_id="mandate-tailgov-001",
        simulation_prefs=simulation_prefs,
        start_year=2026,
        target_total_rappen=advisory.total_rappen,
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "CMA-TAIL-ACTIVATION-GOVERNANCE-001 — round 53 red test, see audit "
        "docs/audits/2026-10-05-cma-correlation-tail-moment-and-runtime-parity-integrity-audit.md"
    ),
)
def test_reporting_mc_applies_same_tail_model_as_optimizer_by_default():
    cma = _cma_with_tail_moments()

    # No explicit tailRisk/cornishFisher preference anywhere -- the realistic
    # "customer never touched this switch" default (the admin/preferences UI
    # does not even expose one, see 5eyes_v2.html).
    default_prefs = {"transactionCostBps": 0, "rebalanceMode": "none"}
    assert "tailRisk" not in default_prefs and "cornishFisher" not in default_prefs

    # --- Build the real optimizer scenario-path run -------------------------
    # scenario_inputs_from_cma() reads skew/kurt off the SAME CMA row and the
    # SAME _weighted_bucket_metrics() mu/sigma that the reporting engine uses.
    scenario_inputs = scenario_inputs_from_cma(cma)
    optimizer_paths = build_scenario_paths(
        scenario_inputs, horizon_years=5, n_paths=256, seed=11, antithetic=False,
    )
    assert optimizer_paths.shape[0] == 256  # sanity: the optimizer run actually ran

    # --- Build the real reporting Monte Carlo run ---------------------------
    reporting_result = _run_allocation_monte_carlo(**_reporting_kwargs(cma, default_prefs))
    assert reporting_result["current_p50_series_rappen"]  # sanity: the reporting run actually ran

    # --- Same single source of truth for (mu, sigma) on both sides ----------
    bucket_returns_bps, bucket_vols_bps = _weighted_bucket_metrics(cma, None)
    mu = bucket_returns_bps["equities"] / 10_000.0
    sigma = bucket_vols_bps["equities"] / 10_000.0
    skew = _EQUITIES_SKEW_BPS / 10_000.0
    kurt = _EQUITIES_EXCESS_KURT_BPS / 10_000.0

    # What the optimizer unconditionally does for this bucket
    # (services/optimizer/scenario_engine.py:_log_parameters_for_inputs).
    optimizer_log_params = arithmetic_moments_to_log_parameters(
        mu, sigma, skew=skew, excess_kurtosis=kurt, use_cornish_fisher=True,
    )

    # What the reporting engine actually does for this bucket, gated by the
    # SAME default/absent preferences used to build reporting_result above
    # (services/portfolio_engine_mc_simulation.py:_run_allocation_monte_carlo).
    reporting_uses_cf = _simulation_use_tail_risk(default_prefs)
    reporting_log_params = arithmetic_moments_to_log_parameters(
        mu, sigma, skew=skew, excess_kurtosis=kurt, use_cornish_fisher=reporting_uses_cf,
    )

    # THE CLAIM: with no explicit tail-risk preference, reporting should
    # treat the CMA's tail moments the same way the optimizer always does.
    assert reporting_uses_cf is True, (
        "_simulation_use_tail_risk() must default to True to match the "
        "optimizer's unconditional Cornish-Fisher application for a CMA "
        f"with nonzero skew/kurt -- it returned {reporting_uses_cf!r} for "
        "default/absent simulation preferences"
    )
    assert reporting_log_params == optimizer_log_params, (
        "reporting and optimizer must calibrate the SAME log-return "
        "parameters from the SAME CMA tail moments by default; got "
        f"reporting={reporting_log_params} vs optimizer={optimizer_log_params} "
        "-- the same CMA produces two different success-probability models"
    )
