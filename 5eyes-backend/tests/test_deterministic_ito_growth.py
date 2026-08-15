"""Regression: der deterministische Hauptpfad nutzt dieselbe momentenkalibrierte
geometrische Wachstumskonvention wie die Monte-Carlo-Simulation, damit die
Hauptlinie zum MC-Median (p50) konvergiert.

Vorher (2026-06-17 davor): _build_simulation_payload uebergab vols_by_asset NICHT
-> deterministischer Pfad = (1+r)^t (kein Vol-Drag) -> Hauptlinie lag ueber dem
MC-Median-Faecher. Fix: vols_by_asset wird an die Hauptpfade uebergeben.
"""
import math

from services.portfolio_engine import _simulate_bucket_path


def _run(vols):
    return _simulate_bucket_path(
        start_values={"equities": 1_000_000},
        returns_by_asset={"equities": 500},          # 5% p.a.
        vols_by_asset=vols,
        cashflow_series_rappen=[0] * 10,             # keine Cashflows -> reines Wachstum
        targets={},
        minimums={},
        maximums={},
        start_year=2026,
        rebalance_mode="none",
        transaction_cost_bps=0,
    )[0]


def test_ito_geometric_growth_when_vols_present():
    series = _run({"equities": 2000})               # sigma = 20%
    variance_ln = math.log1p((0.20 / 1.05) ** 2)
    expected = round(
        1_000_000 * math.exp((math.log1p(0.05) - 0.5 * variance_ln) * 10)
    )
    # +-1 Rappen pro Jahr Rundungstoleranz.
    assert abs(series[-1] - expected) <= 12


def test_arithmetic_growth_when_no_vols():
    series = _run(None)
    expected = round(1_000_000 * (1.05 ** 10))
    assert abs(series[-1] - expected) <= 12


def test_vol_drag_makes_main_path_lower_than_arithmetic():
    """Der momententreue Vol-Drag MUSS den Hauptpfad unter die naive
    (1+r)-Linie druecken — sonst liegt die Linie wieder ueber dem MC-Median."""
    with_vols = _run({"equities": 2000})[-1]
    without_vols = _run(None)[-1]
    assert with_vols < without_vols


def test_zero_vol_bucket_stays_on_arithmetic_path():
    """Liquiditaet (sigma=0) darf durch die Itô-Konvention NICHT veraendert werden:
    bei r=0 bleibt sie exakt flach (Leart-IST-Regression)."""
    flat = _simulate_bucket_path(
        start_values={"liquidity": 500_000},
        returns_by_asset={"liquidity": 0},
        vols_by_asset={"liquidity": 0},
        cashflow_series_rappen=[0] * 10,
        targets={}, minimums={}, maximums={},
        start_year=2026, rebalance_mode="none", transaction_cost_bps=0,
    )[0]
    assert all(v == 500_000 for v in flat)           # absolut flach, keine Steigung
