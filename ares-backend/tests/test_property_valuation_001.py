"""PROPERTY-VALUATION-001 (Audit 2026-09-14, User-Entscheid 2026-09-16:
"Vollen Fixvertrag umsetzen"):

`valuation_date` war ein freier String, der gleichzeitig als Bewertungs-
stichtag UND als valid_from der abgeleiteten Cashflows (Miete, Hypothekarzins,
Tilgung) diente. Ein syntaktisch ungueltiges Datum wurde klaglos akzeptiert;
ein zukuenftig datierter Wert liess den Immobilien-Principal ab Jahr 0 in der
Bilanz stehen (_build_external_foundation_projection zaehlt jede aktive
Position unconditional), waehrend die abgeleitete Miete erst ab diesem
zukuenftigen Datum begann -- widerspruechliche Wirtschaftlichkeit derselben
Position (Audit-Repro). Zusaetzlich fehlte `currency` komplett in
WealthPositionUpdate, `property_usage` war dort (anders als in Create) kein
Literal, und `property_rental_inflation_linked` akzeptierte jeden Int-Wert.

Dieses Modul deckt die vollstaendig umgesetzten Teile ab. Bewusst NICHT
umgesetzt (siehe PR-Beschreibung, eigene Owner-Decision): separates
Mietvertrags-/Eigennutzungs-Gueltigkeitsdatum, Eigentumsanteil, Bewertungs-
quelle/-evidenz, versionierte Freshness-Policy, effective_from/until-
Statusverlauf.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from schemas.wealth import WealthPositionCreate, WealthPositionUpdate
from services.wealth_cashflows import derive_wealth_cashflows


def _valid_property(**overrides):
    base = dict(
        label="Renditeliegenschaft",
        position_type="Immobilien",
        assignment="Anderes Vermögen",
        current_value_rappen=1_000_000_00,
        property_usage="Renditeobjekt",
        property_rental_income_rappen=24_000_00,
    )
    base.update(overrides)
    return base


# ============================================================================
# Schema-Validierung
# ============================================================================


def test_create_rejects_malformed_valuation_date():
    """Audit-Repro: "2099-not-a-date" wurde bislang klaglos akzeptiert."""
    with pytest.raises(ValidationError):
        WealthPositionCreate(**_valid_property(valuation_date="2099-not-a-date"))


def test_create_accepts_well_formed_valuation_date_and_none():
    WealthPositionCreate(**_valid_property(valuation_date="2027-06-30"))
    WealthPositionCreate(**_valid_property(valuation_date=None))


def test_create_rejects_out_of_range_rental_inflation_linked_flag():
    """Audit-Repro: 999 als property_rental_inflation_linked wirkte spaeter
    truthy, obwohl es kein gueltiges 0/1-Flag ist."""
    with pytest.raises(ValidationError):
        WealthPositionCreate(**_valid_property(property_rental_inflation_linked=999))


def test_update_rejects_malformed_valuation_date():
    with pytest.raises(ValidationError):
        WealthPositionUpdate(valuation_date="2099-not-a-date")


def test_update_accepts_well_formed_valuation_date():
    WealthPositionUpdate(valuation_date="2030-01-01")


def test_update_accepts_currency():
    """PROPERTY-VALUATION-001 Punkt 6: currency fehlte bisher komplett in
    WealthPositionUpdate und wurde von Pydantic still verworfen."""
    upd = WealthPositionUpdate(currency="EUR")
    assert upd.currency == "EUR"


def test_update_rejects_invalid_property_usage_literal():
    """An WealthPositionCreate angeglichen (dort schon Literal-gehaertet)."""
    with pytest.raises(ValidationError):
        WealthPositionUpdate(property_usage="submarine")


def test_update_accepts_valid_property_usage_literal():
    WealthPositionUpdate(property_usage="Ferienimmobilie")


def test_update_rejects_out_of_range_rental_inflation_linked_flag():
    with pytest.raises(ValidationError):
        WealthPositionUpdate(property_rental_inflation_linked=999)


# ============================================================================
# derive_wealth_cashflows(): valuation_date wirkt nicht mehr als
# Cashflow-Startdatum (Audit-Repro, Kernfund)
# ============================================================================


class _Pos:
    def __init__(self, **kw):
        defaults = dict(
            deleted_at=None, is_active=1, position_type="Immobilien",
            id="prop-1", client_id="c-1", label="Ferienhaus",
            currency="CHF", valuation_date=None, current_value_rappen=0,
            assignment="Anderes Vermögen", property_rental_income_rappen=0,
            property_rental_inflation_linked=0,
        )
        defaults.update(kw)
        for k, v in defaults.items():
            setattr(self, k, v)


def test_future_valuation_date_no_longer_delays_derived_rental_income():
    """Audit-Repro: eine Immobilie mit zukuenftigem valuation_date liess die
    abgeleitete Miete vorher erst ab diesem Datum beginnen (valid_from=
    valuation_date), waehrend der Principal in _build_external_foundation_
    projection() unconditional ab Jahr 0 zaehlt. Jetzt hat der abgeleitete
    Cashflow keine kuenstliche Startbeschraenkung mehr -- konsistent mit der
    Bilanzwirkung ab Jahr 0."""
    pos = _Pos(
        current_value_rappen=1_000_000_00,
        property_rental_income_rappen=20_000_00,
        valuation_date="2099-01-01",
    )
    flows = derive_wealth_cashflows([pos])
    rent = next(f for f in flows if f.id.startswith("derived:rental_income:"))
    assert rent.valid_from is None


def test_mortgage_flows_also_no_longer_gated_by_valuation_date():
    """Dieselbe Korrektur gilt fuer Hypothekarzins/Tilgung -- valuation_date
    beschreibt einen Bewertungsstichtag, keine Zins-/Tilgungsstart-Semantik."""
    pos = _Pos(
        position_type="Hypothek",
        assignment="Verbindlichkeit",
        current_value_rappen=600_000_00,
        valuation_date="2099-01-01",
        mortgage_interest_rate_bps=150,
        mortgage_amortization_rappen=10_000_00,
        mortgage_amortization_type="Direkt",
    )
    flows = derive_wealth_cashflows([pos])
    interest = next(f for f in flows if f.id.startswith("derived:mortgage_interest:"))
    amortization = next(f for f in flows if f.id.startswith("derived:mortgage_amortization:"))
    assert interest.valid_from is None
    assert amortization.valid_from is None
