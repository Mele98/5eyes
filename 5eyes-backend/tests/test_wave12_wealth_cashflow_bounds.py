"""2026-07-25 (Generalaudit, Wave 12 -- WealthPosition/Cashflow-CRUD-Fork).

Reine Pydantic-Schema-Unit-Tests, keine DB noetig:
- WealthPositionCreate/-Update: current_value_rappen/property_rental_income_
  rappen/mortgage_amortization_rappen hatten keinen Bounds-Check -- ein
  Tippfehler (zusaetzliche Nullen) haette unbemerkt die SAA-/MC-Basis-
  Aggregation eines Mandats verzerrt.
- CashflowCreate/-Update: ein unerkannter frequency-Wert fiel bisher NICHT
  am API-Rand auf, sondern erst tief in annual_amount_for_year() als
  stiller Fallback auf 12 Monate/jaehrlich (Faktor-12-Fehler bei z.B.
  tatsaechlich monatlichem Cashflow).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from schemas.wealth import CashflowCreate, CashflowUpdate, WealthPositionCreate, WealthPositionUpdate


def _valid_position_kwargs(**over):
    base = dict(
        label="Test",
        position_type="Depot",
        alloc_equities_bps=10000,
    )
    base.update(over)
    return base


def _valid_cashflow_kwargs(**over):
    base = dict(cashflow_type="Income", label="Lohn", amount_rappen=100_000)
    base.update(over)
    return base


# ── WealthPosition rappen bounds ────────────────────────────────────────────

def test_wealth_position_rejects_negative_current_value():
    with pytest.raises(ValidationError):
        WealthPositionCreate(**_valid_position_kwargs(current_value_rappen=-1))


def test_wealth_position_rejects_absurdly_high_current_value():
    with pytest.raises(ValidationError):
        WealthPositionCreate(**_valid_position_kwargs(current_value_rappen=10**15))


def test_wealth_position_accepts_plausible_high_net_worth_value():
    pos = WealthPositionCreate(**_valid_position_kwargs(current_value_rappen=50_000_000_00))
    assert pos.current_value_rappen == 50_000_000_00


def test_wealth_position_rejects_negative_rental_income():
    with pytest.raises(ValidationError):
        WealthPositionCreate(
            label="Haus", position_type="Immobilien",
            property_rental_income_rappen=-100,
        )


def test_direct_real_estate_create_requires_other_wealth_scope():
    """Direktimmobilien are a fixed total-wealth foundation, not SAA assets."""
    with pytest.raises(
        ValidationError,
        match=r"Direktimmobilien.*Anderes Vermögen",
    ):
        WealthPositionCreate(
            label="Renditeliegenschaft",
            position_type="Immobilien",
            assignment="Beratungsvermögen",
            current_value_rappen=1_000_000_00,
            property_rental_income_rappen=30_000_00,
        )


def test_direct_real_estate_create_accepts_external_total_wealth_scope():
    position = WealthPositionCreate(
        label="Renditeliegenschaft",
        position_type="Immobilien",
        assignment="Anderes Vermögen",
        current_value_rappen=1_000_000_00,
        property_rental_income_rappen=30_000_00,
    )

    assert position.assignment == "Anderes Vermögen"


@pytest.mark.parametrize("invalid_return", [True, -10_000, -20_000])
def test_direct_real_estate_rejects_invalid_price_return(invalid_return):
    with pytest.raises(ValidationError):
        WealthPositionCreate(
            label="Renditeliegenschaft",
            position_type="Immobilien",
            assignment="Anderes Vermögen",
            current_value_rappen=1_000_000_00,
            asset_expected_return_bps=invalid_return,
        )


def test_non_depot_position_rejects_depot_allocation_fields():
    with pytest.raises(ValidationError, match=r"alloc_\*-Felder"):
        WealthPositionCreate(
            label="Renditeliegenschaft",
            position_type="Immobilien",
            assignment="Anderes Vermögen",
            current_value_rappen=1_000_000_00,
            alloc_equities_bps=10_000,
        )


def test_positive_mortgage_amortization_requires_explicit_mode():
    with pytest.raises(ValidationError, match="Amortisation.*Typ"):
        WealthPositionCreate(
            label="Hypo",
            position_type="Hypothek",
            assignment="Verbindlichkeit",
            mortgage_amortization_rappen=10_000_00,
        )


def test_wealth_position_rejects_negative_mortgage_amortization():
    with pytest.raises(ValidationError):
        WealthPositionCreate(
            label="Hypo", position_type="Hypothek", assignment="Verbindlichkeit",
            mortgage_amortization_rappen=-1,
        )


def test_wealth_position_update_rejects_absurd_current_value():
    with pytest.raises(ValidationError):
        WealthPositionUpdate(current_value_rappen=10**15)


def test_wealth_position_update_allows_omitted_current_value():
    upd = WealthPositionUpdate(label="Renamed")
    assert upd.current_value_rappen is None


# ── Cashflow frequency validation ───────────────────────────────────────────

def test_cashflow_rejects_unrecognized_frequency():
    with pytest.raises(ValidationError):
        CashflowCreate(**_valid_cashflow_kwargs(frequency="monatlic"))


def test_cashflow_accepts_canonical_german_frequency():
    cf = CashflowCreate(**_valid_cashflow_kwargs(frequency="monatlich"))
    assert cf.frequency == "monatlich"


def test_cashflow_accepts_english_alias_frequency():
    cf = CashflowCreate(**_valid_cashflow_kwargs(frequency="monthly"))
    assert cf.frequency == "monthly"


def test_cashflow_accepts_einmalig_frequency():
    cf = CashflowCreate(**_valid_cashflow_kwargs(frequency="einmalig"))
    assert cf.frequency == "einmalig"


def test_cashflow_default_frequency_is_valid():
    cf = CashflowCreate(**_valid_cashflow_kwargs())
    assert cf.frequency == "jährlich"


def test_cashflow_update_rejects_unrecognized_frequency():
    with pytest.raises(ValidationError):
        CashflowUpdate(frequency="wochentlich-typo")


def test_cashflow_update_allows_omitted_frequency():
    upd = CashflowUpdate(label="Renamed")
    assert upd.frequency is None
