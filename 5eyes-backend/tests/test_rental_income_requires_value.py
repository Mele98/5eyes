"""Mieteinnahme erfordert Immobilienwert > 0 (Audit-Frage 2026-06-25).

Sonst entstünde Einkommen ohne Substanz: eine Liegenschaft mit Wert 0 aber
property_rental_income_rappen > 0 (Dateneingabe-Fehler) erzeugte sonst eine
Mieteinnahme im IST-Cashflow, während Gesamt-/Beratungsvermögen die Liegenschaft
mit 0 führen.
"""
from __future__ import annotations

from types import SimpleNamespace

from services.wealth_cashflows import derive_wealth_cashflows


def _immo(value_rappen, rent_rappen, **kw):
    base = dict(
        id="p1", client_id="c1", position_type="Immobilien", label="Wohnung",
        currency="CHF", is_active=1, deleted_at=None,
        current_value_rappen=value_rappen, property_rental_income_rappen=rent_rappen,
        property_rental_inflation_linked=0,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _rental(cfs):
    return [c for c in cfs if c.origin_position_id == "p1" and "Miet" in c.label]


def test_rental_income_with_value_is_derived():
    cfs = derive_wealth_cashflows([_immo(10_000_000, 300_000)])
    rent = _rental(cfs)
    assert len(rent) == 1
    assert rent[0].amount_rappen == 300_000
    assert rent[0].cashflow_type == "Income"


def test_no_rental_income_when_value_zero():
    # Wert 0 + Miete > 0 → KEINE Mieteinnahme (Einkommen ohne Substanz vermieden).
    cfs = derive_wealth_cashflows([_immo(0, 300_000)])
    assert _rental(cfs) == []


def test_no_rental_income_when_value_negative():
    cfs = derive_wealth_cashflows([_immo(-100, 300_000)])
    assert _rental(cfs) == []


def test_rental_income_carries_origin_assignment():
    # Herkunfts-Topf wird durchgereicht, damit die UI sichtbar machen kann, dass
    # ein Mietertrag aus 'Anderem Vermögen' stammt (nicht im Beratungsvermögen).
    cfs = derive_wealth_cashflows([_immo(10_000_000, 300_000, assignment="Anderes Vermögen")])
    rent = _rental(cfs)
    assert len(rent) == 1
    assert rent[0].origin_assignment == "Anderes Vermögen"
    assert "origin_assignment" in rent[0].to_dict()


def test_origin_assignment_none_when_unset():
    cfs = derive_wealth_cashflows([_immo(10_000_000, 300_000)])
    assert _rental(cfs)[0].origin_assignment is None
