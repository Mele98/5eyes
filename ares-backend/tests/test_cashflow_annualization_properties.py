"""2026-06-14 (Roadmap #62): Eigenschafts-/Invarianten-Tests der Cashflow-
Annualisierung (services.cashflow_timeline.contribution_for_year).

Deterministische Kombinationen (kein Zufall) über Frequenz × Zeitfenster, die die
fachlichen Invarianten pinnen — das Herz der Cashflow-Korrektheit (Basis für
Saldo, Verzehr-Projektion und Engine).
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.cashflow_timeline import contribution_for_year

YEAR = 2030
AMT = 1_000_00  # CHF 1'000


def _c(**kw):
    base = dict(amount_rappen=AMT, frequency="jährlich", nature="wiederkehrend",
                valid_from=None, valid_until=None, year=YEAR)
    base.update(kw)
    return contribution_for_year(**base)


@pytest.mark.parametrize("freq,expected_occ", [
    ("monatlich", 12), ("quartalsweise", 4), ("halbjährlich", 2), ("jährlich", 1),
])
def test_full_year_window_annualizes_correctly(freq, expected_occ):
    got = _c(frequency=freq, valid_from=f"{YEAR}-01-01", valid_until=f"{YEAR}-12-31")
    assert got == AMT * expected_occ, (freq, got)


@pytest.mark.parametrize("freq", ["monatlich", "quartalsweise", "halbjährlich", "jährlich"])
def test_zero_amount_yields_zero(freq):
    assert _c(amount_rappen=0, frequency=freq, valid_from=f"{YEAR}-01-01") == 0


@pytest.mark.parametrize("freq", ["monatlich", "quartalsweise", "halbjährlich", "jährlich"])
def test_window_entirely_before_year_yields_zero(freq):
    assert _c(frequency=freq, valid_from=f"{YEAR-5}-01-01", valid_until=f"{YEAR-1}-12-31") == 0


@pytest.mark.parametrize("freq", ["monatlich", "quartalsweise", "halbjährlich", "jährlich"])
def test_window_entirely_after_year_yields_zero(freq):
    assert _c(frequency=freq, valid_from=f"{YEAR+1}-01-01") == 0


def test_valid_until_is_inclusive_on_jan_first():
    """Fach-Konvention (verifiziert): valid_until=YEAR-01-01 zahlt im YEAR noch
    eine volle Jahres-Occurrence (Anker 1. Jan)."""
    got = _c(frequency="jährlich", valid_from=f"{YEAR-10}-01-01", valid_until=f"{YEAR}-01-01")
    assert got == AMT


def test_valid_until_prior_year_end_excludes_year():
    assert _c(frequency="jährlich", valid_from=f"{YEAR-10}-01-01", valid_until=f"{YEAR-1}-12-31") == 0


@pytest.mark.parametrize("freq", ["monatlich", "quartalsweise", "halbjährlich", "jährlich"])
def test_never_negative(freq):
    assert _c(frequency=freq, valid_from=f"{YEAR}-01-01") >= 0


@pytest.mark.parametrize("freq,full", [
    ("monatlich", 12), ("quartalsweise", 4), ("halbjährlich", 2),
])
def test_partial_year_not_more_than_full_year(freq, full):
    """Monotonie: ein im Jahr später startender Flow hat <= Occurrences als ganzjährig."""
    full_year = _c(frequency=freq, valid_from=f"{YEAR}-01-01", valid_until=f"{YEAR}-12-31")
    mid_year = _c(frequency=freq, valid_from=f"{YEAR}-07-01", valid_until=f"{YEAR}-12-31")
    assert 0 <= mid_year <= full_year == AMT * full


def test_einmalig_in_year_counts_once_else_zero():
    in_year = _c(frequency="einmalig", nature="einmalig",
                 valid_from=f"{YEAR}-06-30", valid_until=f"{YEAR}-06-30")
    out_year = _c(frequency="einmalig", nature="einmalig",
                  valid_from=f"{YEAR-2}-06-30", valid_until=f"{YEAR-2}-06-30")
    assert in_year == AMT
    assert out_year == 0


def test_inflation_factor_scales_linearly():
    base = _c(frequency="jährlich", valid_from=f"{YEAR}-01-01")
    inflated = contribution_for_year(amount_rappen=AMT, frequency="jährlich",
                                     nature="wiederkehrend", valid_from=f"{YEAR}-01-01",
                                     valid_until=None, year=YEAR, inflation_factor=1.10)
    assert base == AMT
    assert inflated == round(AMT * 1.10)
