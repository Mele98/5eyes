"""User-Fachentscheid 2026-06-17: Liquidität wertet in der PROJEKTION NICHT auf
(Cash = 0%, sofern nicht anders gesetzt). Selbst wenn die CMA eine Liquiditäts-
rendite trägt (risk-free/Sharpe), muss ein 100%-Liquiditäts-Portfolio ohne
Cashflows als HORIZONTALE Linie projizieren — kein Phantom-Wachstum.

Tatsächliche Konto-Zinsen kommen ausschliesslich über den abgeleiteten
Zinsertrag-Cashflow rein (kein Doppelzählen).
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
from services.portfolio_engine import BUCKET_FIELDS, PortfolioSummary, _run_allocation_monte_carlo
from models.allocation import CapitalMarketAssumption


def _cma_with_liquidity_return() -> CapitalMarketAssumption:
    # Liquidität trägt in der CMA 0.8% (risk-free) UND Vola — die Projektion muss sie
    # trotzdem flach halten.
    return CapitalMarketAssumption(
        id="cma-liqflat", assumption_set_name="LiqFlat", version=1,
        valid_from="2026-01-01", is_current=1,
        bonds_chf_ig_return_bps=0, bonds_chf_ig_vol_bps=0,
        bonds_fx_hedged_return_bps=0, bonds_fx_hedged_vol_bps=0,
        equity_ch_return_bps=0, equity_ch_vol_bps=0,
        equity_intl_return_bps=0, equity_intl_vol_bps=0,
        real_estate_ch_return_bps=0, real_estate_ch_vol_bps=0,
        alternatives_gold_return_bps=0, alternatives_gold_vol_bps=0,
        liquidity_return_bps=80, liquidity_vol_bps=15,
        correlation_matrix_json="", sub_asset_class_assumptions_json="",
        created_by="test", created_at="2026-01-01T00:00:00.000Z",
        updated_at="2026-01-01T00:00:00.000Z",
    )


def _kwargs():
    horizon = [0] * 10  # 10 Jahre, KEINE Cashflows
    advisory = PortfolioSummary(
        amounts_rappen={key: (100_000_00 if key == "liquidity" else 0) for key in BUCKET_FIELDS},
        total_rappen=100_000_00,
    )
    return dict(
        advisory_summary=advisory,
        cashflow_projection_series_rappen=horizon,
        goal_inflation_series_bps=[0] * len(horizon),
        targets={key: (10000 if key == "liquidity" else 0) for key in BUCKET_FIELDS},
        minimums={key: 0 for key in BUCKET_FIELDS},
        maximums={key: 10000 for key in BUCKET_FIELDS},
        cma=_cma_with_liquidity_return(),
        goals=[],
        advisory_wealth_rappen=advisory.total_rappen,
        total_wealth_rappen=advisory.total_rappen,
        policy=None,
        mandate_id="mandate-liqflat",
        simulation_prefs={"transactionCostBps": 0, "rebalanceMode": "none"},
        start_year=2026,
        target_total_rappen=advisory.total_rappen,
    )


@pytest.fixture(autouse=True)
def _fixed_sims(monkeypatch):
    monkeypatch.setattr(pe, "_monte_carlo_simulations", lambda prefs: 300)


def test_pure_liquidity_projection_is_flat():
    mc = _run_allocation_monte_carlo(**_kwargs())
    start = 100_000_00
    p50 = mc["current_p50_series_rappen"]
    p10 = mc["current_p10_series_rappen"]
    p90 = mc["current_p90_series_rappen"]
    assert p50, "leere Serie"
    # Median exakt flach (mu=0, sigma=0 -> growth=1.0 jedes Jahr).
    assert all(v == start for v in p50), f"Liquidität waechst trotz 0%: {p50}"
    # Auch kein Streuband auf Cash (Vola 0): P10 == P90 == Start am Ende.
    assert p10[-1] == start and p90[-1] == start, f"P10/P90: {p10[-1]} / {p90[-1]}"
