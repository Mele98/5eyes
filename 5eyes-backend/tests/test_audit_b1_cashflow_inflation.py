"""B1 - Inflation auf Cashflows.

Cashflows mit is_inflation_linked=1 werden im Jahr t (relativ zu start_year)
mit dem kumulierten Inflations-Faktor multipliziert. Cashflows mit
is_inflation_linked=0 bleiben nominal (User-Eingabe ist End-Wert im Eingabe-Jahr).

CH-Defaults (vom Aufrufer durchgereicht):
- AHV/Lohn/Miete: is_inflation_linked=1 (Mischindex/LIK/OR 269a)
- Bonus/Erbschaft/Hypothek-Zinsen: is_inflation_linked=0

Wissenschaftlich: User gibt den heute-Wert ein (real). Modell rechnet nominal
in Future-Rappen, indem im Jahr t das amount mit Pi(1+inflation_i) multipliziert
wird.
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.cashflow_timeline import (
    contribution_for_year,
    net_cashflow_series,
    recurring_net_cashflow_series,
    totals_for_year,
)


class _CF:
    """Kleiner Mock fuer Cashflow-Objekt (ohne ORM)."""

    def __init__(
        self,
        *,
        amount_rappen,
        cashflow_type="Income",
        frequency="jährlich",
        nature="wiederkehrend",
        valid_from=None,
        valid_until=None,
        is_inflation_linked=0,
    ):
        self.amount_rappen = amount_rappen
        self.cashflow_type = cashflow_type
        self.frequency = frequency
        self.nature = nature
        self.valid_from = valid_from
        self.valid_until = valid_until
        self.is_inflation_linked = is_inflation_linked


# ============================================================================
# B1.1 - contribution_for_year nimmt inflation_factor
# ============================================================================

def test_b1_contribution_no_inflation_factor_default_unchanged():
    """Default inflation_factor=1.0 -> verhalten unveraendert."""
    amount = contribution_for_year(
        amount_rappen=10_000_00,
        frequency="jährlich",
        nature="wiederkehrend",
        valid_from=None,
        valid_until=None,
        year=2026,
    )
    assert amount == 10_000_00


def test_b1_contribution_inflation_factor_2pct_one_year():
    """inflation_factor=1.02 -> amount * 1.02."""
    amount = contribution_for_year(
        amount_rappen=10_000_00,
        frequency="jährlich",
        nature="wiederkehrend",
        valid_from=None,
        valid_until=None,
        year=2026,
        inflation_factor=1.02,
    )
    assert amount == 10_200_00  # 10_000_00 * 1.02 = 10_200_00


def test_b1_contribution_monthly_with_inflation_factor():
    """Monatliche Miete 3000 CHF mit Faktor 1.05 -> 12 * 3000 * 1.05 = 37800 CHF/Jahr."""
    amount = contribution_for_year(
        amount_rappen=3_000_00,
        frequency="monatlich",
        nature="wiederkehrend",
        valid_from="2026-01-01",
        valid_until=None,
        year=2026,
        inflation_factor=1.05,
    )
    assert amount == 37_800_00  # 12 * 3000 * 1.05


# ============================================================================
# B1.2 - totals_for_year reagiert auf is_inflation_linked
# ============================================================================

def test_b1_totals_inflation_linked_uses_inflation_series():
    """Ein inflation-linked Cashflow im Jahr 2 (start 2026, Ziel 2028)
    wird mit (1+i_2026)*(1+i_2027) multipliziert."""
    miete = _CF(
        amount_rappen=3_000_00,
        cashflow_type="Expense",
        frequency="monatlich",
        is_inflation_linked=1,
        valid_from="2026-01-01",
    )
    inflation_series_bps = [200, 200, 200]  # 2% pro Jahr
    # Jahr 2026 (offset 0): faktor 1.0  -> 36'000
    # Jahr 2027 (offset 1): faktor 1.02 -> 36'720
    # Jahr 2028 (offset 2): faktor 1.0404 -> 37'454.4
    t0 = totals_for_year([miete], 2026, inflation_series_bps=inflation_series_bps, start_year=2026)
    assert t0["recurring_expense_rappen"] == 36_000_00

    t1 = totals_for_year([miete], 2027, inflation_series_bps=inflation_series_bps, start_year=2026)
    assert t1["recurring_expense_rappen"] == 36_720_00

    t2 = totals_for_year([miete], 2028, inflation_series_bps=inflation_series_bps, start_year=2026)
    # 36'000 * 1.02 * 1.02 = 37454.4 -> 37_454_40 Rappen (tolerance: round)
    assert abs(t2["recurring_expense_rappen"] - 37_454_40) <= 100


def test_b1_totals_not_inflation_linked_stays_nominal():
    """Bonus mit is_inflation_linked=0 bleibt im Future-Jahr nominal."""
    bonus = _CF(
        amount_rappen=20_000_00,
        cashflow_type="Income",
        frequency="einmalig",
        nature="einmalig",
        is_inflation_linked=0,
        valid_from="2030-01-01",
    )
    inflation_series_bps = [200] * 10
    t = totals_for_year([bonus], 2030, inflation_series_bps=inflation_series_bps, start_year=2026)
    assert t["capital_inflow_rappen"] == 20_000_00


def test_b1_totals_no_inflation_series_passed_no_change():
    """Backwards-compat: wenn keine inflation_series_bps uebergeben,
    bleibt das Verhalten exakt wie vorher (kein Inflations-Adjust)."""
    miete = _CF(
        amount_rappen=3_000_00,
        cashflow_type="Expense",
        frequency="monatlich",
        is_inflation_linked=1,
        valid_from="2026-01-01",
    )
    # Kein inflation_series_bps -> 12 * 3000 ohne inflation
    t = totals_for_year([miete], 2030)
    assert t["recurring_expense_rappen"] == 36_000_00


# ============================================================================
# B1.3 - net_cashflow_series und recurring_net_cashflow_series
# ============================================================================

def test_b1_recurring_series_inflates_year_by_year():
    """Lohn 100k inflation-linked, 2% p.a. -> Series waechst geometrisch."""
    lohn = _CF(
        amount_rappen=100_000_00,
        cashflow_type="Income",
        frequency="jährlich",
        is_inflation_linked=1,
        valid_from="2026-01-01",
    )
    series = recurring_net_cashflow_series(
        [lohn], years=4, start_year=2026,
        inflation_series_bps=[200, 200, 200, 200],
    )
    assert len(series) == 4
    assert series[0] == 100_000_00
    assert series[1] == 102_000_00
    # 100_000 * 1.02 * 1.02 = 104_040
    assert abs(series[2] - 104_040_00) <= 100
    # 100_000 * 1.02^3 = 106120.8
    assert abs(series[3] - 106_120_80) <= 100


def test_b1_net_series_mixed_cashflows():
    """Lohn (linked) + Bonus (nicht linked) ueber 3 Jahre."""
    lohn = _CF(
        amount_rappen=100_000_00,
        cashflow_type="Income",
        frequency="jährlich",
        is_inflation_linked=1,
    )
    bonus_2027 = _CF(
        amount_rappen=20_000_00,
        cashflow_type="Income",
        frequency="einmalig",
        nature="einmalig",
        is_inflation_linked=0,
        valid_from="2027-01-01",
    )
    series = net_cashflow_series(
        [lohn, bonus_2027], years=3, start_year=2026,
        inflation_series_bps=[200, 200, 200],
    )
    # 2026: 100k Lohn (kein Inflation, t=0)
    assert series[0] == 100_000_00
    # 2027: 102k Lohn (Inflation 1J) + 20k Bonus nominal
    assert series[1] == 102_000_00 + 20_000_00


# ============================================================================
# B1.4 - End-to-End: Backend-Aufrufer reichen inflation series weiter
# ============================================================================

def test_b1_inflation_factor_is_compound():
    """Im Jahr 5 ist faktor = (1+i_0)*(1+i_1)*(1+i_2)*(1+i_3)*(1+i_4)."""
    lohn = _CF(
        amount_rappen=100_000_00,
        cashflow_type="Income",
        frequency="jährlich",
        is_inflation_linked=1,
        valid_from="2026-01-01",
    )
    series = recurring_net_cashflow_series(
        [lohn], years=6, start_year=2026,
        inflation_series_bps=[100, 200, 300, 100, 100, 100],
    )
    # year 0 (2026): 1.00
    # year 1 (2027): 1.01
    # year 2 (2028): 1.01 * 1.02 = 1.0302
    # year 3 (2029): 1.0302 * 1.03 = 1.061106
    # year 4 (2030): 1.061106 * 1.01 = 1.0717...
    expected_factor_year_3 = 1.01 * 1.02 * 1.03
    assert abs(series[3] - int(round(100_000_00 * expected_factor_year_3))) <= 200
