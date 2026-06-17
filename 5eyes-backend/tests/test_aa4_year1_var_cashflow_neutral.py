"""#AA-4 (2026-06-12): 1-Jahres-VaR/CVaR/Loss-Prob cashflow-bereinigt.

Vor dem Fix floss der Jahr-1-Cashflow in die Jahr-1-Rendite ein
(`_return_bps(target_start, target_by_year[1])` — target_by_year[1] = Wert NACH
Cashflow). Eine Einzahlung liess das Portfolio dadurch "sicherer" erscheinen
(VaR/Loss-Prob zu niedrig), eine Entnahme "riskanter". VaR misst aber
MARKT-Risiko, nicht den Effekt von Ein-/Auszahlungen.

Nach dem Fix wird der Marktwert nach Wachstum, aber VOR Cashflow als Basis
genutzt -> die 1-Jahres-Risikomasse sind unabhaengig vom Jahr-1-Cashflow.

Verifikation: identischer Seed (mandate_id) -> identische Markt-Pfade. Nur der
Jahr-1-Cashflow variiert. Erwartung: target_var_95_1y / cvar / loss_prob
IDENTISCH zwischen Null-Cashflow und grosser Einzahlung.
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
)
from models.allocation import CapitalMarketAssumption


def _equity_risk_cma() -> CapitalMarketAssumption:
    """CMA mit echter Aktien-Volatilitaet (20%), sonst flach -> Markt-Risiko."""
    return CapitalMarketAssumption(
        id="cma-aa4", assumption_set_name="EquityRisk", version=1,
        valid_from="2026-01-01", is_current=1,
        bonds_chf_ig_return_bps=0, bonds_chf_ig_vol_bps=0,
        bonds_fx_hedged_return_bps=0, bonds_fx_hedged_vol_bps=0,
        equity_ch_return_bps=0, equity_ch_vol_bps=2000,
        equity_intl_return_bps=0, equity_intl_vol_bps=2000,
        real_estate_ch_return_bps=0, real_estate_ch_vol_bps=0,
        alternatives_gold_return_bps=0, alternatives_gold_vol_bps=0,
        liquidity_return_bps=0, liquidity_vol_bps=0,
        correlation_matrix_json="", sub_asset_class_assumptions_json="",
        created_by="test", created_at="2026-01-01T00:00:00.000Z",
        updated_at="2026-01-01T00:00:00.000Z",
    )


def _kwargs(cashflow):
    advisory = PortfolioSummary(
        amounts_rappen={key: (100_000_00 if key == "equities" else 0) for key in BUCKET_FIELDS},
        total_rappen=100_000_00,
    )
    return dict(
        advisory_summary=advisory,
        cashflow_projection_series_rappen=cashflow,
        goal_inflation_series_bps=[0] * len(cashflow),
        targets={key: (10000 if key == "equities" else 0) for key in BUCKET_FIELDS},
        minimums={key: 0 for key in BUCKET_FIELDS},
        maximums={key: 10000 for key in BUCKET_FIELDS},
        cma=_equity_risk_cma(),
        goals=[],
        advisory_wealth_rappen=advisory.total_rappen,
        total_wealth_rappen=advisory.total_rappen,
        policy=None,
        mandate_id="mandate-aa4-fixed-seed",
        simulation_prefs={"transactionCostBps": 0, "rebalanceMode": "none"},
        start_year=2026,
        target_total_rappen=advisory.total_rappen,
    )


@pytest.fixture(autouse=True)
def _fixed_sims(monkeypatch):
    monkeypatch.setattr(pe, "_monte_carlo_simulations", lambda prefs: 500)


def test_year1_risk_metrics_independent_of_year1_cashflow():
    """Identischer Seed, nur Jahr-1-Cashflow variiert -> 1J-Risikomasse gleich."""
    no_cf = _run_allocation_monte_carlo(**_kwargs([0, 0, 0]))
    # Grosse Jahr-1-Einzahlung (50% des Startwerts): wuerde vor dem Fix den
    # VaR/Loss-Prob kuenstlich senken.
    big_deposit = _run_allocation_monte_carlo(**_kwargs([50_000_00, 0, 0]))

    assert no_cf["target_var_95_1y_bps"] == big_deposit["target_var_95_1y_bps"]
    assert no_cf["target_cvar_95_1y_bps"] == big_deposit["target_cvar_95_1y_bps"]
    assert no_cf["target_loss_probability_1y_pct"] == big_deposit["target_loss_probability_1y_pct"]


def test_year1_loss_probability_is_meaningful():
    """Sanity: bei 20% Aktien-Vol und 0% Drift liegt die 1J-Loss-Prob nahe 50%
    (symmetrische Markt-Renditen) — also klar > 0, sonst misst der Test nichts."""
    res = _run_allocation_monte_carlo(**_kwargs([0, 0, 0]))
    assert res["target_loss_probability_1y_pct"] > 10
    assert res["target_var_95_1y_bps"] > 0
