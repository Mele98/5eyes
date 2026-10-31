"""#AA-5 (2026-06-12): annualisierte MC-Rendite ist time-weighted (TWR).

Vor dem Fix: `_annualized_return_bps(start, end_over_horizon)` = money-weighted
(end/start enthaelt alle Ein-/Auszahlungen). Eine Einzahlung vor einem guten
Jahr hob die ausgewiesene "CAGR" kuenstlich — die Kennzahl mass also nicht die
Strategie-Performance, sondern das Cashflow-Timing.

Nach dem Fix: geometrische Verkettung der jaehrlichen MARKT-Wachstumsfaktoren
(vor Cashflow) -> `target_annualized_return_p50_bps` ist unabhaengig vom
Cashflow-Timing, solange der Cashflow gleich investiert wird (Rebalancing).

User-Entscheid 2026-06-12: TWR (Strategie-Performance, benchmark-vergleichbar).
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
    _twr_annualized_bps,
)
from models.allocation import CapitalMarketAssumption


def _cma_equity(return_bps: int, vol_bps: int) -> CapitalMarketAssumption:
    return CapitalMarketAssumption(
        id="cma-aa5", assumption_set_name="AA5", version=1, valid_from="2026-01-01", is_current=1,
        bonds_chf_ig_return_bps=0, bonds_chf_ig_vol_bps=0,
        bonds_fx_hedged_return_bps=0, bonds_fx_hedged_vol_bps=0,
        equity_ch_return_bps=return_bps, equity_ch_vol_bps=vol_bps,
        equity_intl_return_bps=return_bps, equity_intl_vol_bps=vol_bps,
        real_estate_ch_return_bps=0, real_estate_ch_vol_bps=0,
        alternatives_gold_return_bps=0, alternatives_gold_vol_bps=0,
        liquidity_return_bps=0, liquidity_vol_bps=0,
        correlation_matrix_json="", sub_asset_class_assumptions_json="",
        created_by="t", created_at="2026-01-01T00:00:00.000Z", updated_at="2026-01-01T00:00:00.000Z",
    )


def _run(cashflow, cma):
    adv = PortfolioSummary(
        amounts_rappen={k: (100_000_00 if k == "equities" else 0) for k in BUCKET_FIELDS},
        total_rappen=100_000_00,
    )
    return _run_allocation_monte_carlo(
        advisory_summary=adv,
        cashflow_projection_series_rappen=cashflow,
        goal_inflation_series_bps=[0] * len(cashflow),
        targets={k: (10000 if k == "equities" else 0) for k in BUCKET_FIELDS},
        minimums={k: 0 for k in BUCKET_FIELDS},
        maximums={k: 10000 for k in BUCKET_FIELDS},
        cma=cma, goals=[],
        advisory_wealth_rappen=adv.total_rappen, total_wealth_rappen=adv.total_rappen,
        policy=None, mandate_id="m-aa5-seed",
        # calendar-Rebalance -> Einzahlung wird in Aktien investiert (gleiche Strategie)
        simulation_prefs={"transactionCostBps": 0, "rebalanceMode": "calendar"},
        start_year=2026, target_total_rappen=adv.total_rappen,
    )


@pytest.fixture(autouse=True)
def _fixed_sims(monkeypatch):
    monkeypatch.setattr(pe, "_monte_carlo_simulations", lambda prefs: 600)


def test_twr_is_cashflow_timing_neutral():
    """Identischer Seed; nur ein grosser Jahr-1-Cashflow variiert. Da er gleich
    investiert wird (Rebalancing), ist die TWR-Median-Rendite IDENTISCH —
    unter money-weighted haette die Einzahlung sie verzerrt."""
    cma = _cma_equity(return_bps=500, vol_bps=1500)
    no_cf = _run([0, 0, 0, 0, 0], cma)
    big_deposit = _run([200_000_00, 0, 0, 0, 0], cma)  # 2x Startwert in Jahr 1
    assert (no_cf["target_annualized_return_p50_bps"]
            == big_deposit["target_annualized_return_p50_bps"])


def test_twr_positive_for_positive_drift():
    """Sanity: positive Markt-Drift -> positive Median-TWR."""
    res = _run([0, 0, 0, 0, 0], _cma_equity(return_bps=500, vol_bps=1000))
    assert res["target_annualized_return_p50_bps"] > 0


# --- Unit-Tests des TWR-Helpers ---

def test_twr_helper_no_growth():
    assert _twr_annualized_bps(1.0, 10) == 0


def test_twr_helper_doubling_over_10y():
    # 2^(1/10)-1 = 7.177%
    assert 700 <= _twr_annualized_bps(2.0, 10) <= 730


def test_twr_helper_collapsed_path_is_total_loss():
    """Eingebrochener Pfad (Produkt <= 0) -> -100% (analog #AA-6 Floor)."""
    assert _twr_annualized_bps(0.0, 5) == -10000


def test_twr_helper_zero_years():
    assert _twr_annualized_bps(1.5, 0) == 0
