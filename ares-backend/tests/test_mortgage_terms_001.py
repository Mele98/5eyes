"""MORTGAGE-TERMS-001 (Audit 2026-09-14, User-Entscheid 2026-09-16):

`mortgage_interest_rate_bps` und `mortgage_maturity_date` besassen keine
Eingabevalidierung. Konkret reproduziert vom Audit: ein negativer Zinssatz
(-999999 bps) wurde vom Schedule (mortgage_interest_schedule) weiterhin
verwendet, waehrend der abgeleitete Basis-Cashflow (derive_wealth_cashflows)
ihn als Betrag<=0 komplett verwarf -- zwei inkonsistente Interpretationen
desselben gespeicherten Werts. Ein Laufzeit-String wie "2027-not-a-date"
wurde von _year_of() als Jahr 2027 interpretiert statt abgelehnt.

Fachentscheid (User, 2026-09-16): negative Hypothekarzinsen werden
abgelehnt (in CH praktisch nie real); `liquidity_interest_rate_bps`
(Bank-/Sparkonti) bleibt bewusst UNVERAENDERT und weiterhin negativ
zulaessig -- dort real und wichtig (siehe fix-negativzins-2026-07-13).
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


def _valid_mortgage(**overrides):
    base = dict(
        label="Hypothek Eigenheim",
        position_type="Hypothek",
        assignment="Verbindlichkeit",
        current_value_rappen=78_000_000,
        mortgage_bank="UBS",
        mortgage_type="Festhypothek",
        mortgage_interest_rate_bps=100,
        mortgage_maturity_date="2030-12-31",
    )
    base.update(overrides)
    return base


def test_create_rejects_negative_mortgage_interest_rate():
    """Audit-Repro: -999999 bps wurde bislang klaglos akzeptiert."""
    with pytest.raises(ValidationError):
        WealthPositionCreate(**_valid_mortgage(mortgage_interest_rate_bps=-999_999))


def test_create_rejects_small_negative_mortgage_interest_rate():
    """Auch ein fachlich plausibel wirkender kleiner negativer Satz (-10 bps)
    muss abgelehnt werden -- nicht nur der extreme Tippfehlerfall."""
    with pytest.raises(ValidationError):
        WealthPositionCreate(**_valid_mortgage(mortgage_interest_rate_bps=-10))


def test_create_accepts_zero_and_plausible_positive_mortgage_interest_rate():
    for rate in (0, 1, 100, 500, 10_000):
        WealthPositionCreate(**_valid_mortgage(mortgage_interest_rate_bps=rate))


def test_create_rejects_excessive_mortgage_interest_rate():
    with pytest.raises(ValidationError):
        WealthPositionCreate(**_valid_mortgage(mortgage_interest_rate_bps=10_001))


def test_create_rejects_malformed_mortgage_maturity_date():
    """Audit-Repro: "2027-not-a-date" wurde von _year_of() als Jahr 2027
    interpretiert statt als ungueltig abgelehnt."""
    with pytest.raises(ValidationError):
        WealthPositionCreate(**_valid_mortgage(mortgage_maturity_date="2027-not-a-date"))


def test_create_rejects_syntactically_impossible_mortgage_maturity_date():
    with pytest.raises(ValidationError):
        WealthPositionCreate(**_valid_mortgage(mortgage_maturity_date="2027-99-99"))


def test_create_accepts_well_formed_mortgage_maturity_date_and_none():
    WealthPositionCreate(**_valid_mortgage(mortgage_maturity_date="2035-06-30"))
    WealthPositionCreate(**_valid_mortgage(mortgage_maturity_date=None))


def test_update_rejects_negative_mortgage_interest_rate():
    with pytest.raises(ValidationError):
        WealthPositionUpdate(mortgage_interest_rate_bps=-999_999)


def test_update_rejects_malformed_mortgage_maturity_date():
    with pytest.raises(ValidationError):
        WealthPositionUpdate(mortgage_maturity_date="2099-not-a-date")


def test_update_accepts_well_formed_mortgage_maturity_date():
    WealthPositionUpdate(mortgage_maturity_date="2040-01-01")


def test_liquidity_interest_rate_still_allows_negative_values():
    """Regressionsschutz: die Negativzins-Faehigkeit fuer Bank-/Sparkonti
    (liquidity_interest_rate_bps) ist von diesem Fix explizit NICHT
    betroffen und bleibt unveraendert negativ zulaessig."""
    WealthPositionCreate(
        label="Sparkonto",
        position_type="Liquidität",
        assignment="Anderes Vermögen",
        current_value_rappen=100_000_00,
        liquidity_interest_rate_bps=-75,
    )
    WealthPositionUpdate(liquidity_interest_rate_bps=-75)
