"""#84 (2026-06-18): Miete teuerungsindexiert.

Ist property_rental_inflation_linked=1 auf einer Immobilien-Position gesetzt, traegt
der abgeleitete Mietertrag-Cashflow is_inflation_linked=1 -> er waechst in der
Projektion mit der Teuerung (cashflow_timeline respektiert is_inflation_linked).
Ohne Flag bleibt der Mietertrag nominal flach.
"""
from types import SimpleNamespace

from services.wealth_cashflows import derive_wealth_cashflows


def _immobilie(**over):
    base = dict(
        id="pos-re-1", client_id="c1", position_type="Immobilien",
        label="Mehrfamilienhaus", currency="CHF",
        current_value_rappen=120_000_000,
        property_rental_income_rappen=4_800_000,   # 48'000 CHF/Jahr
        property_rental_inflation_linked=0,
        is_active=1, deleted_at=None, valuation_date=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _rental(cfs):
    return next((c for c in cfs if str(c.label).startswith("Mieteinnahmen")), None)


def test_rental_inflation_linked_when_flag_set():
    cfs = derive_wealth_cashflows([_immobilie(property_rental_inflation_linked=1)])
    r = _rental(cfs)
    assert r is not None, "Mietertrag-Cashflow fehlt"
    assert int(r.is_inflation_linked) == 1
    assert int(r.amount_rappen) == 4_800_000


def test_rental_flat_when_flag_not_set():
    cfs = derive_wealth_cashflows([_immobilie(property_rental_inflation_linked=0)])
    r = _rental(cfs)
    assert r is not None
    assert int(r.is_inflation_linked) == 0


def test_rental_flag_missing_attribute_defaults_to_flat():
    # Robustheit: aeltere Positionsobjekte ohne das Attribut -> nominal flach.
    pos = _immobilie()
    delattr(pos, "property_rental_inflation_linked")
    r = _rental(derive_wealth_cashflows([pos]))
    assert r is not None and int(r.is_inflation_linked) == 0
