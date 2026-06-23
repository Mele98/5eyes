"""Datenbasis-Guard für die Asset-Allocation (User-Anweisung 2026-06-23).

Regel:
- Beratungsvermögen > 0                         → Allocation erlaubt.
- Beratungsvermögen == 0 ABER Cashflows erfasst  → erlaubt (Vermögensaufbau, "Strategie vor Geldfluss").
- Weder Vermögen NOCH Cashflows (gar keine Daten) → ValueError → Endpoint 409.

Hintergrund: Ohne Datenbasis zeigte die SOLL-%-Torte ein Vermögen vor, das es nicht gibt
(Asset-Allocation = %-Ableitung aus Risikoprofil, unabhängig von echten Assets) — unseriös.
"""
from __future__ import annotations

import pytest

from services.portfolio_engine import _assert_allocation_has_basis


def _call(wealth=0, inc=0, exp=0, cap_in=0, cap_out=0):
    _assert_allocation_has_basis(wealth, inc, exp, cap_in, cap_out)


def test_with_wealth_is_allowed():
    _call(wealth=1_000_000)  # kein raise


def test_no_wealth_no_cashflows_blocks():
    with pytest.raises(ValueError, match="Keine Vermögensbasis"):
        _call(wealth=0)


def test_negative_wealth_no_cashflows_blocks():
    with pytest.raises(ValueError, match="Keine Vermögensbasis"):
        _call(wealth=-5_000)


def test_no_wealth_but_recurring_income_is_allowed():
    # Vermögensaufbau via Sparquote: 0 Vermögen, aber Einkommen erfasst → erlaubt.
    _call(wealth=0, inc=120_000_00)


def test_no_wealth_but_recurring_expense_is_allowed():
    # Cashflows erfasst (auch reine Ausgaben = Modellierung vorhanden) → erlaubt.
    _call(wealth=0, exp=36_000_00)


def test_no_wealth_but_capital_inflow_is_allowed():
    _call(wealth=0, cap_in=250_000_00)
