"""
Tests für services/cashflow_timeline.py
Abdeckung: contribution_for_year(), totals_for_year(), _add_months()
"""
from datetime import date
from types import SimpleNamespace

import pytest

from services.cashflow_timeline import (
    contribution_for_year,
    totals_for_year,
    net_cashflow_series,
    _add_months,
    normalize_frequency,
)


# ── _add_months ────────────────────────────────────────────────────────────────

def test_add_months_normal():
    assert _add_months(date(2026, 1, 15), 1) == date(2026, 2, 15)
    assert _add_months(date(2026, 1, 15), 3) == date(2026, 4, 15)
    assert _add_months(date(2026, 1, 15), 12) == date(2027, 1, 15)


def test_add_months_end_of_month_clamp():
    """31. Januar + 1 Monat → 28./29. Februar (kein Überlauf)."""
    result = _add_months(date(2026, 1, 31), 1)
    assert result == date(2026, 2, 28)


def test_add_months_leap_year():
    """31. Januar 2028 + 1 Monat → 29. Februar 2028 (Schaltjahr)."""
    result = _add_months(date(2028, 1, 31), 1)
    assert result == date(2028, 2, 29)


# ── contribution_for_year: Einmalig ───────────────────────────────────────────

def test_einmalig_richtiges_jahr():
    assert contribution_for_year(
        amount_rappen=100_000_00,
        frequency="einmalig",
        nature="einmalig",
        valid_from="2026-06-15",
        valid_until="2026-06-15",
        year=2026,
    ) == 100_000_00


def test_einmalig_falsches_jahr():
    assert contribution_for_year(
        amount_rappen=100_000_00,
        frequency="einmalig",
        nature="einmalig",
        valid_from="2025-06-15",
        valid_until="2025-06-15",
        year=2026,
    ) == 0


def test_einmalig_kein_betrag():
    assert contribution_for_year(
        amount_rappen=0,
        frequency="einmalig",
        nature="einmalig",
        valid_from="2026-01-01",
        valid_until=None,
        year=2026,
    ) == 0


# ── contribution_for_year: Jährlich ──────────────────────────────────────────

def test_jaehrlich_ganzes_jahr():
    result = contribution_for_year(
        amount_rappen=12_000_00,
        frequency="jährlich",
        nature="wiederkehrend",
        valid_from=None,
        valid_until=None,
        year=2026,
    )
    assert result == 12_000_00  # 1× pro Jahr


def test_jaehrlich_start_im_jahr():
    """Start am 1. Juli → zählt genau 1× im selben Jahr."""
    result = contribution_for_year(
        amount_rappen=12_000_00,
        frequency="jährlich",
        nature="wiederkehrend",
        valid_from="2026-07-01",
        valid_until=None,
        year=2026,
    )
    assert result == 12_000_00


def test_jaehrlich_bereits_abgelaufen():
    """Enddatum vor dem Zieljahr → 0."""
    result = contribution_for_year(
        amount_rappen=12_000_00,
        frequency="jährlich",
        nature="wiederkehrend",
        valid_from="2020-01-01",
        valid_until="2025-12-31",
        year=2026,
    )
    assert result == 0


def test_jaehrlich_noch_nicht_gestartet():
    """Startdatum nach dem Zieljahr → 0."""
    result = contribution_for_year(
        amount_rappen=12_000_00,
        frequency="jährlich",
        nature="wiederkehrend",
        valid_from="2027-01-01",
        valid_until=None,
        year=2026,
    )
    assert result == 0


# ── contribution_for_year: Monatlich ─────────────────────────────────────────

def test_monatlich_ganzes_jahr():
    result = contribution_for_year(
        amount_rappen=1_000_00,
        frequency="monatlich",
        nature="wiederkehrend",
        valid_from=None,
        valid_until=None,
        year=2026,
    )
    assert result == 12 * 1_000_00


def test_monatlich_ab_juli():
    """Start 1. Juli → 6 Monate (Jul–Dez)."""
    result = contribution_for_year(
        amount_rappen=1_000_00,
        frequency="monatlich",
        nature="wiederkehrend",
        valid_from="2026-07-01",
        valid_until=None,
        year=2026,
    )
    assert result == 6 * 1_000_00


def test_monatlich_bis_juni():
    """Ende 30. Juni → 6 Monate (Jan–Jun)."""
    result = contribution_for_year(
        amount_rappen=1_000_00,
        frequency="monatlich",
        nature="wiederkehrend",
        valid_from=None,
        valid_until="2026-06-30",
        year=2026,
    )
    assert result == 6 * 1_000_00


# ── contribution_for_year: Quartalsweise ─────────────────────────────────────

def test_quartalsweise_ganzes_jahr():
    result = contribution_for_year(
        amount_rappen=5_000_00,
        frequency="quartalsweise",
        nature="wiederkehrend",
        valid_from=None,
        valid_until=None,
        year=2026,
    )
    assert result == 4 * 5_000_00


# ── contribution_for_year: Halbjährlich ──────────────────────────────────────

def test_halbjaehrlich_ganzes_jahr():
    result = contribution_for_year(
        amount_rappen=10_000_00,
        frequency="halbjährlich",
        nature="wiederkehrend",
        valid_from=None,
        valid_until=None,
        year=2026,
    )
    assert result == 2 * 10_000_00


# ── contribution_for_year: Grenzfälle ────────────────────────────────────────

def test_end_vor_start_ergibt_null():
    result = contribution_for_year(
        amount_rappen=1_000_00,
        frequency="monatlich",
        nature="wiederkehrend",
        valid_from="2026-06-01",
        valid_until="2026-01-01",
        year=2026,
    )
    assert result == 0


def test_start_31_januar_monatlich_kein_doppelzaehlen():
    """Start 31.01 → Feb=28, Mar=28 (clamped), zählt korrekt ohne Doppeleintrag."""
    result = contribution_for_year(
        amount_rappen=1_000_00,
        frequency="monatlich",
        nature="wiederkehrend",
        valid_from="2026-01-31",
        valid_until=None,
        year=2026,
    )
    assert result == 12 * 1_000_00


# ── totals_for_year ───────────────────────────────────────────────────────────

def _make_cf(cashflow_type, amount_rappen, frequency="jährlich", nature="wiederkehrend",
             valid_from=None, valid_until=None):
    return SimpleNamespace(
        cashflow_type=cashflow_type,
        amount_rappen=amount_rappen,
        frequency=frequency,
        nature=nature,
        valid_from=valid_from,
        valid_until=valid_until,
    )


def test_totals_nur_income():
    cfs = [_make_cf("Income", 100_000_00)]
    result = totals_for_year(cfs, year=2026)
    assert result["income_rappen"] == 100_000_00
    assert result["expense_rappen"] == 0
    assert result["net_rappen"] == 100_000_00


def test_totals_nur_expense():
    """Expense geht in expense_rappen, NICHT in income_rappen."""
    cfs = [_make_cf("Expense", 50_000_00)]
    result = totals_for_year(cfs, year=2026)
    assert result["income_rappen"] == 0
    assert result["expense_rappen"] == 50_000_00
    assert result["net_rappen"] == -50_000_00


def test_totals_income_und_expense():
    cfs = [
        _make_cf("Income", 120_000_00),
        _make_cf("Expense", 80_000_00),
    ]
    result = totals_for_year(cfs, year=2026)
    assert result["income_rappen"] == 120_000_00
    assert result["expense_rappen"] == 80_000_00
    assert result["net_rappen"] == 40_000_00


def test_totals_segmentiert_wiederkehrend_und_einmalig():
    cfs = [
        _make_cf("Income", 120_000_00, frequency="jährlich", nature="wiederkehrend"),
        _make_cf("Income", 50_000_00, frequency="einmalig", nature="einmalig", valid_from="2026-06-30"),
        _make_cf("Expense", 80_000_00, frequency="jährlich", nature="wiederkehrend"),
        _make_cf("Expense", 10_000_00, frequency="einmalig", nature="einmalig", valid_from="2026-09-30"),
    ]
    result = totals_for_year(cfs, year=2026)
    assert result["recurring_income_rappen"] == 120_000_00
    assert result["capital_inflow_rappen"] == 50_000_00
    assert result["recurring_expense_rappen"] == 80_000_00
    assert result["capital_outflow_rappen"] == 10_000_00
    assert result["income_rappen"] == 170_000_00
    assert result["expense_rappen"] == 90_000_00
    assert result["net_rappen"] == 80_000_00


def test_totals_mehrere_cashflows_gleiches_jahr():
    cfs = [
        _make_cf("Income", 10_000_00, frequency="monatlich"),   # 12 × = 120_000_00
        _make_cf("Expense", 5_000_00, frequency="quartalsweise"),  # 4 × = 20_000_00
    ]
    result = totals_for_year(cfs, year=2026)
    assert result["income_rappen"] == 12 * 10_000_00
    assert result["expense_rappen"] == 4 * 5_000_00
    assert result["net_rappen"] == result["income_rappen"] - result["expense_rappen"]


def test_totals_leere_liste():
    result = totals_for_year([], year=2026)
    assert result["income_rappen"] == 0
    assert result["expense_rappen"] == 0
    assert result["net_rappen"] == 0


def test_totals_cashflow_ausserhalb_des_jahres():
    cfs = [_make_cf("Income", 100_000_00, valid_from="2025-01-01", valid_until="2025-12-31")]
    result = totals_for_year(cfs, year=2026)
    assert result["income_rappen"] == 0
    assert result["net_rappen"] == 0


def test_net_cashflow_series_respects_one_off_and_recurring_events():
    cfs = [
        _make_cf("Expense", 9_300_000, frequency="jährlich", valid_from="2026-01-01", valid_until="2029-12-31"),
        _make_cf("Income", 5_000_000, frequency="einmalig", nature="einmalig", valid_from="2028-01-01", valid_until="2028-01-01"),
        _make_cf("Income", 10_000_000, frequency="einmalig", nature="einmalig", valid_from="2029-01-01", valid_until="2029-01-01"),
    ]

    assert net_cashflow_series(cfs, years=4, start_year=2026) == [
        -9_300_000,
        -9_300_000,
        -4_300_000,
        700_000,
    ]
