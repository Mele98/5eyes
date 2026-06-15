"""2026-06-14 (Roadmap #31, Schritt A): Amortisations-/Zins-Schedule-Funktion.

Fachlogik-Entscheid des Users:
  • direkte Amortisation baut Schuld ab (Zins sinkt), indirekte nicht;
  • Zinssatz aktuell bis Ablauf (Fix) bzw. 5 J (SARON), danach 3%.
Reine Funktion — getestet bevor sie in die Projektion integriert wird (Schritt B).
"""
from __future__ import annotations
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from types import SimpleNamespace
from services.wealth_cashflows import mortgage_interest_schedule as sched
from services.wealth_cashflows import mortgage_interest_adjustment_series as adj_series


def _hyp(**kw):
    base = dict(position_type="Hypothek", is_active=1, deleted_at=None,
                current_value_rappen=500_000_00, mortgage_interest_rate_bps=150,
                mortgage_amortization_rappen=0, mortgage_amortization_type=None,
                mortgage_type="Festhypothek", mortgage_maturity_date=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_adjustment_series_direct_amortization():
    # 500k @1.5% direkt 100k/J -> Zins 7500/6000/4500/3000 -> adj = base - s
    pos = _hyp(mortgage_amortization_rappen=100_000_00, mortgage_amortization_type="Direkt")
    assert adj_series([pos], 4, 2026) == [0, 150_000, 300_000, 450_000]


def test_adjustment_series_indirect_is_zero():
    pos = _hyp(mortgage_amortization_rappen=100_000_00, mortgage_amortization_type="Indirekt")
    assert adj_series([pos], 4, 2026) == [0, 0, 0, 0]


def test_adjustment_series_refi_cutover_is_negative():
    # Fix 1% bis 2027, danach 3% -> Zins steigt -> adj negativ ab Cutover.
    pos = _hyp(current_value_rappen=1_000_000_00, mortgage_interest_rate_bps=100,
               mortgage_maturity_date="2027-12-31")
    # s = [10000,10000,30000,30000]*100 -> [1000000,1000000,3000000,3000000]; base=1000000
    assert adj_series([pos], 4, 2026) == [0, 0, -2_000_000, -2_000_000]


def test_adjustment_series_ignores_non_mortgage_and_inactive():
    depot = _hyp(position_type="Depot", mortgage_amortization_rappen=100_000_00,
                 mortgage_amortization_type="Direkt")
    inactive = _hyp(is_active=0, mortgage_amortization_rappen=100_000_00,
                    mortgage_amortization_type="Direkt")
    assert adj_series([depot, inactive], 4, 2026) == [0, 0, 0, 0]


def test_indirect_constant_interest_no_decay():
    # 500'000 @ 1.5% = 7'500/Jahr, indirekt -> konstant.
    s = sched(debt_rappen=500_000_00, rate_bps=150, amortization_rappen=10_000_00,
              amortization_type="Indirekt", mortgage_type="Festhypothek",
              maturity_date=None, horizon_years=4, start_year=2026)
    assert s == [750_000, 750_000, 750_000, 750_000]


def test_direct_amortization_reduces_interest_each_year():
    # 500'000 @ 1.5%, direkte Amort 100'000/Jahr -> Schuld 500/400/300/200k.
    s = sched(debt_rappen=500_000_00, rate_bps=150, amortization_rappen=100_000_00,
              amortization_type="Direkt", mortgage_type="Festhypothek",
              maturity_date=None, horizon_years=4, start_year=2026)
    assert s == [750_000, 600_000, 450_000, 300_000]  # 1.5% von 500/400/300/200k


def test_direct_amortization_floors_at_zero():
    s = sched(debt_rappen=200_000_00, rate_bps=200, amortization_rappen=100_000_00,
              amortization_type="direkt", mortgage_type="Fest",
              maturity_date=None, horizon_years=4, start_year=2026)
    # Schuld 200/100/0/0 -> Zins 4000/2000/0/0
    assert s == [400_000, 200_000, 0, 0]


def test_fix_rate_cutover_at_maturity_to_3pct():
    # Fix 1.0% bis 2028, danach 3.0%. Schuld konstant (indirekt).
    s = sched(debt_rappen=1_000_000_00, rate_bps=100, amortization_rappen=0,
              amortization_type="Indirekt", mortgage_type="Festhypothek",
              maturity_date="2028-06-30", horizon_years=5, start_year=2026)
    # 2026,2027,2028 @1% = 10'000; 2029,2030 @3% = 30'000
    assert s == [1_000_000, 1_000_000, 1_000_000, 3_000_000, 3_000_000]


def test_saron_cutover_after_five_years_to_3pct():
    # SARON 0.8% für 5 Jahre, danach 3%.
    s = sched(debt_rappen=1_000_000_00, rate_bps=80, amortization_rappen=0,
              amortization_type="Indirekt", mortgage_type="SARON-Hypothek",
              maturity_date=None, horizon_years=7, start_year=2026)
    assert s == [800_000, 800_000, 800_000, 800_000, 800_000, 3_000_000, 3_000_000]


def test_fix_without_maturity_keeps_current_rate():
    s = sched(debt_rappen=500_000_00, rate_bps=120, amortization_rappen=0,
              amortization_type=None, mortgage_type="Festhypothek",
              maturity_date=None, horizon_years=3, start_year=2026)
    assert s == [600_000, 600_000, 600_000]


def test_direct_amort_and_saron_cutover_combined():
    # Direkt 50k/J, SARON 1% 5J dann 3%. Schuld 500/450/400/350/300/250/200k.
    s = sched(debt_rappen=500_000_00, rate_bps=100, amortization_rappen=50_000_00,
              amortization_type="Direkt", mortgage_type="SARON",
              maturity_date=None, horizon_years=7, start_year=2026)
    # Jahre 0-4 @1%: 5000,4500,4000,3500,3000 ; Jahre 5-6 @3%: 3%*250k=7500, 3%*200k=6000
    assert s == [500_000, 450_000, 400_000, 350_000, 300_000, 750_000, 600_000]


def test_zero_horizon_returns_empty():
    assert sched(debt_rappen=500_000_00, rate_bps=150, horizon_years=0, start_year=2026) == []


def test_negative_debt_is_abs():
    s = sched(debt_rappen=-500_000_00, rate_bps=200, amortization_rappen=0,
              amortization_type="Indirekt", mortgage_type="Fest",
              maturity_date=None, horizon_years=2, start_year=2026)
    assert s == [1_000_000, 1_000_000]
