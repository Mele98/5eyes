"""F23 - Total-Vermoegen-Pfade in Monte Carlo.

Vor dem Fix: _run_allocation_monte_carlo lieferte nur advisory-Pfade
(current/target_p10/p50/p90). Total-Vermoegen-Pfade existierten nur
deterministisch in _build_simulation_payload (Z8-W2 Phase 2).

Fix: total_summary + total_liabilities_rappen werden durchgereicht;
parallel zu advisory werden total_current/target_*_series berechnet:
- IST traegt Liabilities als initial deficit (Z8-W2 Phase 2 konsistent)
- SOLL hat Liabilities bereits beim Start abgezogen
- Beide nutzen die selben CMA-Returns wie advisory (Markt-Return)
- Lebensluecke laeuft via accumulated_deficit (W2.5 konsistent)

Wenn total_summary fehlt -> alle 6 Listen leer (default-safe).
"""
from __future__ import annotations

import sys
from pathlib import Path

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
    return CapitalMarketAssumption(
        id="cma-zero-f23",
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


def _common_kwargs(*, advisory, total=None, liabilities=0, cashflow=None):
    return dict(
        advisory_summary=advisory,
        cashflow_projection_series_rappen=cashflow if cashflow is not None else [0, 0, 0],
        goal_inflation_series_bps=[0] * (len(cashflow) if cashflow is not None else 3),
        targets=_flat_targets(),
        minimums=_flat_minmax(),
        maximums=_flat_minmax(),
        cma=_zero_return_cma(),
        goals=[],
        advisory_wealth_rappen=advisory.total_rappen,
        total_wealth_rappen=total.total_rappen if total is not None else advisory.total_rappen,
        policy=None,
        mandate_id="mandate-f23",
        simulation_prefs={"transactionCostBps": 0, "rebalanceMode": "bands"},
        start_year=2026,
        target_total_rappen=advisory.total_rappen,
        total_summary=total,
        total_liabilities_rappen=liabilities,
    )


def test_f23_no_total_summary_returns_empty_total_series(monkeypatch):
    """Default ohne total_summary -> alle 6 total_* Listen leer."""
    monkeypatch.setattr(pe, "_monte_carlo_simulations", lambda prefs: 30)

    advisory = PortfolioSummary(
        amounts_rappen={key: (100_000 if key == "liquidity" else 0) for key in BUCKET_FIELDS},
        total_rappen=100_000,
    )
    result = _run_allocation_monte_carlo(**_common_kwargs(advisory=advisory))

    for key in (
        "total_current_p10_series_rappen",
        "total_current_p50_series_rappen",
        "total_current_p90_series_rappen",
        "total_target_p10_series_rappen",
        "total_target_p50_series_rappen",
        "total_target_p90_series_rappen",
    ):
        assert result[key] == [], f"{key} muss leer sein wenn total_summary fehlt"


def test_f23_total_current_starts_at_total_minus_liabilities(monkeypatch):
    """total_current[0] = sum(total_summary.amounts) - liabilities (= Reinvermoegen)."""
    monkeypatch.setattr(pe, "_monte_carlo_simulations", lambda prefs: 30)

    advisory = PortfolioSummary(
        amounts_rappen={key: (300_000 if key == "liquidity" else 0) for key in BUCKET_FIELDS},
        total_rappen=300_000,
    )
    total = PortfolioSummary(
        amounts_rappen={
            "liquidity": 300_000,
            "equities": 200_000,
            "real_estate": 1_000_000,
            "bonds": 0,
            "alternatives": 0,
        },
        total_rappen=1_500_000,
    )
    liabilities = 800_000  # Hypothek auf real_estate

    result = _run_allocation_monte_carlo(**_common_kwargs(
        advisory=advisory, total=total, liabilities=liabilities,
    ))

    # Year 0: 1.5M Vermoegen - 800k Hypothek = 700k Reinvermoegen
    assert result["total_current_p50_series_rappen"][0] == 700_000


def test_f23_total_target_starts_at_total_minus_liabilities_and_redistributed(monkeypatch):
    """total_target[0] = (sum - liabilities) Wert in target-Verteilung umgeschichtet."""
    monkeypatch.setattr(pe, "_monte_carlo_simulations", lambda prefs: 30)

    advisory = PortfolioSummary(
        amounts_rappen={key: (300_000 if key == "liquidity" else 0) for key in BUCKET_FIELDS},
        total_rappen=300_000,
    )
    total = PortfolioSummary(
        amounts_rappen={
            "liquidity": 300_000,
            "real_estate": 1_000_000,
            "equities": 0,
            "bonds": 0,
            "alternatives": 0,
        },
        total_rappen=1_300_000,
    )
    liabilities = 500_000

    result = _run_allocation_monte_carlo(**_common_kwargs(
        advisory=advisory, total=total, liabilities=liabilities,
    ))

    # SOLL = (1.3M - 500k) = 800k, alles in liquidity (targets={liquidity:10000bps})
    assert result["total_target_p50_series_rappen"][0] == 800_000


def test_f23_total_paths_go_negative_with_excessive_outflow(monkeypatch):
    """Bei aufzehrendem Cashflow muessen Total-Pfade auch ins Negative gehen."""
    monkeypatch.setattr(pe, "_monte_carlo_simulations", lambda prefs: 50)

    advisory = PortfolioSummary(
        amounts_rappen={key: (50_000 if key == "liquidity" else 0) for key in BUCKET_FIELDS},
        total_rappen=50_000,
    )
    total = PortfolioSummary(
        amounts_rappen={key: (100_000 if key == "liquidity" else 0) for key in BUCKET_FIELDS},
        total_rappen=100_000,
    )
    cashflow = [-200_000] * 3

    result = _run_allocation_monte_carlo(**_common_kwargs(
        advisory=advisory, total=total, liabilities=0, cashflow=cashflow,
    ))

    # Year 1: 100k - 200k = -100k
    assert result["total_target_p50_series_rappen"][1] == pytest.approx(-100_000, abs=2_000)
    # Year 3: -100k - 2*200k = -500k
    assert result["total_target_p50_series_rappen"][3] == pytest.approx(-500_000, abs=10_000)


def test_f23_total_paths_match_advisory_when_no_extra_assets(monkeypatch):
    """Wenn total == advisory + 0 liabilities, sollten total und advisory gleich sein."""
    monkeypatch.setattr(pe, "_monte_carlo_simulations", lambda prefs: 30)

    advisory = PortfolioSummary(
        amounts_rappen={key: (200_000 if key == "liquidity" else 0) for key in BUCKET_FIELDS},
        total_rappen=200_000,
    )
    # Total identisch zu advisory (kein extra Vermoegen ausserhalb Beratung)
    total = PortfolioSummary(
        amounts_rappen={key: (200_000 if key == "liquidity" else 0) for key in BUCKET_FIELDS},
        total_rappen=200_000,
    )

    result = _run_allocation_monte_carlo(**_common_kwargs(
        advisory=advisory, total=total, liabilities=0, cashflow=[0] * 3,
    ))

    # P50 muss bei beiden uebereinstimmen weil identische Inputs
    assert result["current_p50_series_rappen"] == result["total_current_p50_series_rappen"]
    assert result["target_p50_series_rappen"] == result["total_target_p50_series_rappen"]


def test_f23_total_paths_have_same_length_as_advisory(monkeypatch):
    """Series-Laengen muessen alle gleich sein (year_labels Konsistenz)."""
    monkeypatch.setattr(pe, "_monte_carlo_simulations", lambda prefs: 20)

    advisory = PortfolioSummary(
        amounts_rappen={key: (100_000 if key == "liquidity" else 0) for key in BUCKET_FIELDS},
        total_rappen=100_000,
    )
    total = PortfolioSummary(
        amounts_rappen={key: (200_000 if key == "liquidity" else 0) for key in BUCKET_FIELDS},
        total_rappen=200_000,
    )
    cashflow = [0] * 7  # 7-Jahres-Horizont

    result = _run_allocation_monte_carlo(**_common_kwargs(
        advisory=advisory, total=total, liabilities=0, cashflow=cashflow,
    ))

    expected_len = len(result["target_p50_series_rappen"])  # 8 = horizon + 1
    assert len(result["total_current_p10_series_rappen"]) == expected_len
    assert len(result["total_current_p50_series_rappen"]) == expected_len
    assert len(result["total_current_p90_series_rappen"]) == expected_len
    assert len(result["total_target_p10_series_rappen"]) == expected_len
    assert len(result["total_target_p50_series_rappen"]) == expected_len
    assert len(result["total_target_p90_series_rappen"]) == expected_len


def test_f23_total_p10_below_p90_with_volatility(monkeypatch):
    """Mit Volatilitaet: total_p10 <= total_p50 <= total_p90."""
    monkeypatch.setattr(pe, "_monte_carlo_simulations", lambda prefs: 200)

    advisory = PortfolioSummary(
        amounts_rappen={key: (100_000 if key == "equities" else 0) for key in BUCKET_FIELDS},
        total_rappen=100_000,
    )
    total = PortfolioSummary(
        amounts_rappen={key: (300_000 if key == "equities" else 0) for key in BUCKET_FIELDS},
        total_rappen=300_000,
    )
    cma = _zero_return_cma()
    cma.equity_ch_return_bps = 500
    cma.equity_ch_vol_bps = 1500
    cma.equity_intl_return_bps = 500
    cma.equity_intl_vol_bps = 1500

    targets = {key: 10000 if key == "equities" else 0 for key in BUCKET_FIELDS}
    kwargs = _common_kwargs(advisory=advisory, total=total)
    kwargs["cma"] = cma
    kwargs["targets"] = targets
    kwargs["target_total_rappen"] = 100_000

    result = _run_allocation_monte_carlo(**kwargs)

    # p10 <= p50 <= p90 fuer das letzte Jahr im total-Pfad
    p10 = result["total_target_p10_series_rappen"][-1]
    p50 = result["total_target_p50_series_rappen"][-1]
    p90 = result["total_target_p90_series_rappen"][-1]
    assert p10 <= p50 <= p90, f"Order broken: p10={p10}, p50={p50}, p90={p90}"
