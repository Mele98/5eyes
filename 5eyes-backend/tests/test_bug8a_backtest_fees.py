"""Bug-#8a (2026-06-07): Backtest mit jaehrlichen Gebuehren (TER + Berater).

User-Befund: 'sonst kann man nie den Benchmark schlagen da dieser keine
Fees ausweist'. Backtest-Engine bisher brutto only — die SOLL-Strategie
und der Vergleichsindex liefen beide kostenlos. Berater sah deshalb
'Strategie underperformed Benchmark', obwohl der Index gar nicht
investierbar war.

Fix: `compound_wealth_path`, `_build_path_views`, `run_strategy_backtest`
und der Router-Endpoint akzeptieren jetzt `strategy_fee_bps` und
`benchmark_fee_bps` (jaehrlich, in bps). Die Returns werden geometrisch
abgezogen:  r_net = (1 + r_gross) * (1 - fee/10000) - 1.

Bei `strategy_fee_bps > 0` enthaelt das SOLL-View zusaetzlich einen
`gross`-Block (Brutto-Pfad ohne Fees), damit Berater Brutto vs. Netto
direkt vergleichen kann.

Tests decken die Engine-Mathematik + Backwards-Compat + Edge-Cases ab.
"""
from __future__ import annotations

import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import math

import pytest

from services.backtest_strategy import compound_wealth_path


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _equity_only_weights() -> dict[str, int]:
    return {
        "equities": 10000,
        "bonds": 0,
        "real_estate": 0,
        "alternatives": 0,
        "liquidity": 0,
    }


def _flat_10pct_years(n: int) -> list[tuple[int, dict[str, int]]]:
    """n Jahre mit jeweils +10% Aktienrendite (alle anderen 0)."""
    return [
        (2000 + i, {"equities": 1000, "bonds": 0, "real_estate": 0, "alternatives": 0, "liquidity": 0})
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Engine-Math
# ---------------------------------------------------------------------------


def test_compound_wealth_path_ohne_fee_unverhaendert():
    """fee_bps_per_year=0 muss das alte Verhalten exakt reproduzieren."""
    path_gross = compound_wealth_path(
        100_000_00,
        _equity_only_weights(),
        _flat_10pct_years(5),
        rebalance=True,
        fee_bps_per_year=0,
    )
    final = path_gross["wealth_path_rappen"][-1][1]
    expected = round(100_000_00 * (1.10 ** 5))
    assert abs(final - expected) <= 5
    assert path_gross["fee_bps_per_year"] == 0


def test_compound_wealth_path_mit_100bps_fee_zieht_geometrisch_ab():
    """1% Fee p.a. reduziert den Endwert um (1-0.01)^n vs. brutto."""
    n = 10
    years = _flat_10pct_years(n)
    init = 100_000_00

    gross = compound_wealth_path(init, _equity_only_weights(), years, rebalance=True, fee_bps_per_year=0)
    net = compound_wealth_path(init, _equity_only_weights(), years, rebalance=True, fee_bps_per_year=100)

    gross_final = gross["wealth_path_rappen"][-1][1]
    net_final = net["wealth_path_rappen"][-1][1]

    # Brutto: 100 * 1.10^10 = 259'374.25
    # Netto-Faktor pro Jahr = 1.10 * 0.99 = 1.089
    expected_gross = round(init * (1.10 ** n))
    expected_net = round(init * ((1.10 * 0.99) ** n))

    assert abs(gross_final - expected_gross) <= 10
    assert abs(net_final - expected_net) <= 10
    # Netto ist kleiner als Brutto
    assert net_final < gross_final
    # Audit-Feld korrekt
    assert net["fee_bps_per_year"] == 100


def test_fee_clamp_negative_wird_zu_null():
    """Negative Fee = 0 (kein Boost durch User-Trickserei)."""
    init = 100_000_00
    years = _flat_10pct_years(3)
    no_fee = compound_wealth_path(init, _equity_only_weights(), years, rebalance=True, fee_bps_per_year=0)
    neg_fee = compound_wealth_path(init, _equity_only_weights(), years, rebalance=True, fee_bps_per_year=-500)
    assert no_fee["wealth_path_rappen"][-1][1] == neg_fee["wealth_path_rappen"][-1][1]
    assert neg_fee["fee_bps_per_year"] == 0


def test_fee_clamp_ueber_10000bps_wird_zu_10000():
    """fee >= 100% kappt den Faktor auf 0 — der Pfad geht auf 0."""
    init = 100_000_00
    years = _flat_10pct_years(2)
    extreme = compound_wealth_path(init, _equity_only_weights(), years, rebalance=True, fee_bps_per_year=99999)
    # fee_factor = 0 -> alle new_values = 0 nach Jahr 1
    assert extreme["wealth_path_rappen"][-1][1] == 0
    assert extreme["fee_bps_per_year"] == 10000


def test_fee_wirkt_auch_im_no_rebal_pfad():
    init = 100_000_00
    years = _flat_10pct_years(5)
    gross = compound_wealth_path(init, _equity_only_weights(), years, rebalance=False, fee_bps_per_year=0)
    net = compound_wealth_path(init, _equity_only_weights(), years, rebalance=False, fee_bps_per_year=200)
    assert net["wealth_path_rappen"][-1][1] < gross["wealth_path_rappen"][-1][1]


def test_annual_returns_bps_spiegeln_netto():
    """Bei +10% Brutto - 1% Fee => Netto-Rendite ca. (1.10*0.99-1) = 8.9% = 890 bps."""
    init = 100_000_00
    years = _flat_10pct_years(3)
    net = compound_wealth_path(init, _equity_only_weights(), years, rebalance=True, fee_bps_per_year=100)
    for ret_bps in net["annual_returns_bps"]:
        assert 880 <= ret_bps <= 895


# ---------------------------------------------------------------------------
# Build-Path-Views: bei strategy_fee > 0 muss ein 'gross'-Block dazukommen
# ---------------------------------------------------------------------------


def test_build_path_views_kein_gross_wenn_fee_null():
    from services.backtest_strategy import _build_path_views

    view = _build_path_views(
        100_000_00,
        _equity_only_weights(),
        _flat_10pct_years(3),
        risk_free_bps=50,
        fee_bps_per_year=0,
    )
    assert view["fee_bps_per_year"] == 0
    assert "gross" not in view


def test_build_path_views_liefert_gross_bei_fee():
    from services.backtest_strategy import _build_path_views

    view = _build_path_views(
        100_000_00,
        _equity_only_weights(),
        _flat_10pct_years(5),
        risk_free_bps=50,
        fee_bps_per_year=150,
    )
    assert view["fee_bps_per_year"] == 150
    assert "gross" in view
    gross_final = view["gross"]["rebalanced"]["wealth_path_rappen"][-1][1]
    net_final = view["rebalanced"]["wealth_path_rappen"][-1][1]
    assert gross_final > net_final


# ---------------------------------------------------------------------------
# Router-Endpoint: nimmt Fee-Query-Params an + propagiert
# ---------------------------------------------------------------------------


def test_router_signature_akzeptiert_fee_params():
    """Drift-Wache fuer die Endpoint-Signatur: Fee-Params muessen
    als optionale Query-Params verfuegbar sein."""
    import inspect
    from routers.allocation import get_strategy_backtest
    sig = inspect.signature(get_strategy_backtest)
    assert "strategy_fee_bps" in sig.parameters
    assert "benchmark_fee_bps" in sig.parameters
    # Default ist None (Backwards-Compat).
    assert sig.parameters["strategy_fee_bps"].default is None
    assert sig.parameters["benchmark_fee_bps"].default is None


def test_run_strategy_backtest_signature_akzeptiert_fee_params():
    import inspect
    from services.backtest_strategy import run_strategy_backtest
    sig = inspect.signature(run_strategy_backtest)
    assert "strategy_fee_bps" in sig.parameters
    assert "benchmark_fee_bps" in sig.parameters
    assert sig.parameters["strategy_fee_bps"].default is None
    assert sig.parameters["benchmark_fee_bps"].default is None
