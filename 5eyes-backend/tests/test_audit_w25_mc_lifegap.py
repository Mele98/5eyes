"""W2.5 - Monte-Carlo Lebensluecke darf ins Negative gehen.

Vor diesem Fix: target_p10/p50/p90 wurden via max(0, ...) auf 0 geclampt, weil
_apply_cashflow_to_bucket_values den Deficit-Remainder zurueckgab aber ignoriert
wurde. Damit zeigte die MC-Simulation eine Lebensluecke nicht im negativen
Bereich, obwohl der deterministische Pfad (_simulate_bucket_path) sie korrekt
via accumulated_deficit traegt.

Fix: in _run_allocation_monte_carlo wird pro Simulation current_deficit und
target_deficit getrackt und beim Bilden der jaehrlichen Totals subtrahiert.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy.orm import configure_mappers
from database import Base
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
configure_mappers()

import services.portfolio_engine as pe
from models.allocation import CapitalMarketAssumption
from services.portfolio_engine import (
    BUCKET_FIELDS,
    PortfolioSummary,
    _run_allocation_monte_carlo,
)


def _zero_return_cma() -> CapitalMarketAssumption:
    """CMA ohne Returns/Volatilitaet - rein deterministisch fuer Reproduzierbarkeit."""
    return CapitalMarketAssumption(
        id="cma-zero",
        assumption_set_name="ZeroReturn",
        version=1,
        valid_from="2026-01-01",
        is_current=1,
        bonds_chf_ig_return_bps=0,
        bonds_chf_ig_vol_bps=0,
        bonds_fx_hedged_return_bps=0,
        bonds_fx_hedged_vol_bps=0,
        equity_ch_return_bps=0,
        equity_ch_vol_bps=0,
        equity_intl_return_bps=0,
        equity_intl_vol_bps=0,
        real_estate_ch_return_bps=0,
        real_estate_ch_vol_bps=0,
        alternatives_gold_return_bps=0,
        alternatives_gold_vol_bps=0,
        liquidity_return_bps=0,
        liquidity_vol_bps=0,
        correlation_matrix_json="",
        sub_asset_class_assumptions_json="",
        created_by="test",
        created_at="2026-01-01T00:00:00.000Z",
        updated_at="2026-01-01T00:00:00.000Z",
    )


def _flat_targets():
    return {key: 10000 if key == "liquidity" else 0 for key in BUCKET_FIELDS}


def _flat_minmax():
    return {key: 0 for key in BUCKET_FIELDS}


def test_w25_mc_target_path_goes_negative_when_cashflow_outpaces_wealth(monkeypatch):
    """Wenn Lebenshaltungsausgaben das Vermoegen aufzehren, muss target_p50
    in spaeteren Jahren negativ werden (= akkumulierte Lebensluecke)."""
    monkeypatch.setattr(pe, "_monte_carlo_simulations", lambda prefs: 50)

    # Start: 100'000 Rappen Liquiditaet (= 1'000 CHF)
    advisory_summary = PortfolioSummary(
        amounts_rappen={key: (100_000 if key == "liquidity" else 0) for key in BUCKET_FIELDS},
        total_rappen=100_000,
    )
    # Jaehrlich -200'000 Rappen Outflow -> nach Jahr 1 ist Vermoegen weg, ab Jahr 2 ist es Lebensluecke.
    cashflow_series = [-200_000] * 5

    result = _run_allocation_monte_carlo(
        advisory_summary=advisory_summary,
        cashflow_projection_series_rappen=cashflow_series,
        goal_inflation_series_bps=[0] * 5,
        targets=_flat_targets(),
        minimums=_flat_minmax(),
        maximums=_flat_minmax(),
        cma=_zero_return_cma(),
        goals=[],
        advisory_wealth_rappen=100_000,
        total_wealth_rappen=100_000,
        policy=None,
        mandate_id="mandate-test-w25",
        simulation_prefs={"transactionCostBps": 0, "rebalanceMode": "bands"},
        start_year=2026,
        target_total_rappen=100_000,
    )

    # Year 0: start = +100'000
    assert result["target_p50_series_rappen"][0] == 100_000
    # Year 1: 100'000 - 200'000 = -100'000 (alles aufgezehrt + 100'000 deficit)
    # Toleranz wegen float/rebalance Rundung in der Schleife
    assert result["target_p50_series_rappen"][1] == pytest.approx(-100_000, abs=2_000)
    # Year 5: -100'000 - 4 * 200'000 = -900'000 (Lebensluecke akkumuliert)
    assert result["target_p50_series_rappen"][5] == pytest.approx(-900_000, abs=10_000)
    # Monoton fallend
    assert result["target_p50_series_rappen"][5] < result["target_p50_series_rappen"][1]


def test_w25_mc_current_path_goes_negative_too(monkeypatch):
    """Auch der current-Pfad (heutige Allokation) muss ins Negative gehen koennen."""
    monkeypatch.setattr(pe, "_monte_carlo_simulations", lambda prefs: 50)

    advisory_summary = PortfolioSummary(
        amounts_rappen={key: (50_000 if key == "liquidity" else 0) for key in BUCKET_FIELDS},
        total_rappen=50_000,
    )
    cashflow_series = [-100_000] * 3

    result = _run_allocation_monte_carlo(
        advisory_summary=advisory_summary,
        cashflow_projection_series_rappen=cashflow_series,
        goal_inflation_series_bps=[0] * 3,
        targets=_flat_targets(),
        minimums=_flat_minmax(),
        maximums=_flat_minmax(),
        cma=_zero_return_cma(),
        goals=[],
        advisory_wealth_rappen=50_000,
        total_wealth_rappen=50_000,
        policy=None,
        mandate_id="mandate-test-w25-current",
        simulation_prefs={"transactionCostBps": 0, "rebalanceMode": "bands"},
        start_year=2026,
        target_total_rappen=50_000,
    )

    # Year 1: 50'000 - 100'000 = -50'000
    assert result["current_p50_series_rappen"][1] == pytest.approx(-50_000, abs=2_000)
    # Year 3: -50'000 - 2 * 100'000 = -250'000
    assert result["current_p50_series_rappen"][3] == pytest.approx(-250_000, abs=5_000)
    # monoton fallend (Lebensluecke akkumuliert)
    assert result["current_p50_series_rappen"][3] < result["current_p50_series_rappen"][1]


def test_w25_mc_no_negative_when_cashflow_within_wealth(monkeypatch):
    """Wenn Cashflow das Vermoegen NICHT aufzehrt, bleibt der Pfad positiv."""
    monkeypatch.setattr(pe, "_monte_carlo_simulations", lambda prefs: 30)

    advisory_summary = PortfolioSummary(
        amounts_rappen={key: (1_000_000 if key == "liquidity" else 0) for key in BUCKET_FIELDS},
        total_rappen=1_000_000,
    )
    cashflow_series = [-50_000] * 3  # gut innerhalb 1M

    result = _run_allocation_monte_carlo(
        advisory_summary=advisory_summary,
        cashflow_projection_series_rappen=cashflow_series,
        goal_inflation_series_bps=[0] * 3,
        targets=_flat_targets(),
        minimums=_flat_minmax(),
        maximums=_flat_minmax(),
        cma=_zero_return_cma(),
        goals=[],
        advisory_wealth_rappen=1_000_000,
        total_wealth_rappen=1_000_000,
        policy=None,
        mandate_id="mandate-test-w25-positive",
        simulation_prefs={"transactionCostBps": 0, "rebalanceMode": "bands"},
        start_year=2026,
        target_total_rappen=1_000_000,
    )

    for value in result["target_p50_series_rappen"]:
        assert value >= 0, f"target_p50 should stay non-negative when cashflow fits within wealth, got {value}"


def test_w25_mc_p10_more_negative_than_p90_when_volatility_added(monkeypatch):
    """Mit Volatilitaet sollte p10 staerker negativ sein als p90 (mehr verteilt)."""
    monkeypatch.setattr(pe, "_monte_carlo_simulations", lambda prefs: 200)

    advisory_summary = PortfolioSummary(
        amounts_rappen={key: (100_000 if key == "equities" else 0) for key in BUCKET_FIELDS},
        total_rappen=100_000,
    )
    cashflow_series = [-150_000] * 4  # zehrt staendig

    cma = _zero_return_cma()
    cma.equity_ch_return_bps = 500
    cma.equity_ch_vol_bps = 1500
    cma.equity_intl_return_bps = 500
    cma.equity_intl_vol_bps = 1500

    targets = {key: 10000 if key == "equities" else 0 for key in BUCKET_FIELDS}

    result = _run_allocation_monte_carlo(
        advisory_summary=advisory_summary,
        cashflow_projection_series_rappen=cashflow_series,
        goal_inflation_series_bps=[0] * 4,
        targets=targets,
        minimums=_flat_minmax(),
        maximums=_flat_minmax(),
        cma=cma,
        goals=[],
        advisory_wealth_rappen=100_000,
        total_wealth_rappen=100_000,
        policy=None,
        mandate_id="mandate-test-w25-vol",
        simulation_prefs={"transactionCostBps": 0, "rebalanceMode": "bands"},
        start_year=2026,
        target_total_rappen=100_000,
    )

    p10_final = result["target_p10_series_rappen"][-1]
    p90_final = result["target_p90_series_rappen"][-1]
    # p10 = schlechtes Szenario, p90 = gutes -> p10 muss <= p90 sein
    assert p10_final <= p90_final
    # beide sind im negativen Bereich (Lebensluecke dominiert)
    assert p10_final < 0
