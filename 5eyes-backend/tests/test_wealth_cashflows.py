"""2026-06-14: Vermögensgetriebene Cashflows — Ableitungs-Mathematik.

Hypothekarzins = Schuld * Satz; Amortisation, Miet- und Zinserträge aus den
jeweiligen Vermögensfeldern. Reine Wertsteigerung wird NICHT abgeleitet.
"""
from __future__ import annotations
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.wealth_cashflows import derive_wealth_cashflows


def _pos(**kw):
    base = dict(id="p1", client_id="c1", label="X", position_type="Depot",
                current_value_rappen=0, currency="CHF", valuation_date="2026-01-01",
                is_active=1, deleted_at=None,
                mortgage_interest_rate_bps=None, mortgage_amortization_rappen=0,
                property_rental_income_rappen=0, liquidity_interest_rate_bps=None)
    base.update(kw)
    return SimpleNamespace(**base)


def _by_label(rows):
    return {r.label: r for r in rows}


def test_mortgage_interest_and_amortization():
    # CHF 500'000 Schuld @ 1.5% -> CHF 7'500 Zins/Jahr; Amortisation CHF 10'000.
    pos = _pos(id="h1", label="Hypothek EFH", position_type="Hypothek",
               current_value_rappen=500_000_00, mortgage_interest_rate_bps=150,
               mortgage_amortization_rappen=10_000_00)
    rows = derive_wealth_cashflows([pos])
    by = _by_label(rows)
    assert by["Hypothekarzins: Hypothek EFH"].cashflow_type == "Expense"
    assert by["Hypothekarzins: Hypothek EFH"].amount_rappen == 750_000  # CHF 7'500
    assert by["Hypothekarzins: Hypothek EFH"].origin_position_id == "h1"
    assert by["Hypothekarzins: Hypothek EFH"].is_derived == 1
    assert by["Amortisation: Hypothek EFH"].amount_rappen == 10_000_00
    assert by["Amortisation: Hypothek EFH"].cashflow_type == "Expense"


def test_mortgage_negative_value_is_abs():
    # Falls Schuld als negativer Wert gespeichert ist, trotzdem positiver Zins.
    pos = _pos(id="h2", position_type="Hypothek", label="H",
               current_value_rappen=-500_000_00, mortgage_interest_rate_bps=200)
    rows = derive_wealth_cashflows([pos])
    assert rows[0].amount_rappen == 1_000_000  # CHF 10'000, positiv


def test_rental_income():
    pos = _pos(id="i1", position_type="Immobilien", label="Renditeobjekt",
               property_rental_income_rappen=24_000_00)
    rows = derive_wealth_cashflows([pos])
    assert len(rows) == 1
    assert rows[0].cashflow_type == "Income"
    assert rows[0].amount_rappen == 24_000_00
    assert rows[0].label == "Mieteinnahmen: Renditeobjekt"


def test_liquidity_interest():
    # CHF 100'000 @ 0.8% -> CHF 800 Zinsertrag.
    pos = _pos(id="l1", position_type="Liquidität", label="Sparkonto",
               current_value_rappen=100_000_00, liquidity_interest_rate_bps=80)
    rows = derive_wealth_cashflows([pos])
    assert rows[0].cashflow_type == "Income"
    assert rows[0].amount_rappen == 800_00
    assert rows[0].label == "Zinsertrag: Sparkonto"


def test_zero_rate_or_amount_yields_nothing():
    assert derive_wealth_cashflows([_pos(position_type="Hypothek", current_value_rappen=0, mortgage_interest_rate_bps=150)]) == []
    assert derive_wealth_cashflows([_pos(position_type="Hypothek", current_value_rappen=500_000_00, mortgage_interest_rate_bps=0)]) == []
    assert derive_wealth_cashflows([_pos(position_type="Immobilien", property_rental_income_rappen=0)]) == []


def test_depot_appreciation_not_derived():
    # Depot/Alternative: keine Cashflow-Ableitung (Wertsteigerung != Cashflow).
    assert derive_wealth_cashflows([_pos(position_type="Depot", current_value_rappen=1_000_000_00)]) == []
    assert derive_wealth_cashflows([_pos(position_type="Alternative", current_value_rappen=1_000_000_00,
                                         asset_expected_return_bps=500)]) == []


def test_inactive_and_deleted_skipped():
    active = _pos(id="a", position_type="Immobilien", property_rental_income_rappen=12_000_00)
    inactive = _pos(id="b", position_type="Immobilien", property_rental_income_rappen=12_000_00, is_active=0)
    deleted = _pos(id="c", position_type="Immobilien", property_rental_income_rappen=12_000_00, deleted_at="2026-01-01")
    rows = derive_wealth_cashflows([active, inactive, deleted])
    assert len(rows) == 1
    assert rows[0].origin_position_id == "a"


def test_derived_objects_compatible_with_totals_for_year():
    """Die abgeleiteten Objekte müssen von cashflow_timeline summierbar sein."""
    from services.cashflow_timeline import totals_for_year
    pos = _pos(id="h1", position_type="Hypothek", label="H",
               current_value_rappen=500_000_00, mortgage_interest_rate_bps=150,
               property_rental_income_rappen=0)
    rows = derive_wealth_cashflows([pos])
    totals = totals_for_year(rows, 2026)
    assert totals["recurring_expense_rappen"] == 750_000
    assert totals["recurring_income_rappen"] == 0
