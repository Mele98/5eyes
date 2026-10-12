"""Red test for GOAL-RECURRENCE-SCHEDULE-001 (round 38), Pflichttest 2.

See docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md
(this path does not exist in this worktree's git history -- confirmed via
Glob/git log --all; derived directly from reading
services/optimizer/goal_liabilities.py and from empirically running
goal_to_liability() for every combination below before writing assertions).

``_build_recurring_outflow()`` books one YEAR-sized bucket per element of
``_outflow_duration_years()``, and that duration is computed as the plain
calendar-year LABEL difference ``target_date.year - start_date.year + 1``
(``goal_liabilities.py::_outflow_duration_years``), not the number of
calendar years the stream actually, elapsed-time-wise, overlaps. Frequency
(monatlich/quartalsweise/halbjaehrlich/jaehrlich) only scales the per-year
annualized amount (``_annualize_amount_rappen``); it does not change the
duration-counting bug, so the same bucket-count defect appears identically
-- just scaled -- at every frequency.

This matrix pins down, for each of the four supported frequencies, both:

- two window shapes where the calendar-label formula is CORRECT today
  (same-year window; an exact N-year span landing on Dec 31) -- plain
  passing positive-control tests, not xfail;
- two window shapes where it overcounts by exactly one bucket (a 1-day
  cross-year straddle; an exact N-year span landing on Jan 1 of year N+1)
  -- xfail(strict) red tests.

Every expected total/bucket-count below was verified by directly executing
``goal_to_liability()`` against current `develop` before writing the
assertions (not hand-derived in the abstract).
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy.orm import configure_mappers  # noqa: E402
from database import Base  # noqa: E402,F401
from models import (  # noqa: E402,F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
configure_mappers()

from services.optimizer.goal_liabilities import goal_to_liability  # noqa: E402

CHF = 100  # 1 CHF == 100 Rappen
ANNUAL_AMOUNT_RAPPEN = 100 * CHF  # CHF100 (per-frequency-period amount)

FREQUENCIES = ["jaehrlich", "monatlich", "quartalsweise", "halbjaehrlich"]
_ANNUALIZATION_MULTIPLIER = {
    "jaehrlich": 1,
    "monatlich": 12,
    "quartalsweise": 4,
    "halbjaehrlich": 2,
}


def _make_goal(*, frequency: str, start_date: str, target_date: str) -> SimpleNamespace:
    """Mock-Goal as SimpleNamespace -- same pattern as
    tests/test_optimizer_goal_liabilities.py::_make_goal and the sibling
    round-38 test_goal_liability_dec31_jan1_single_occurrence.py."""
    return SimpleNamespace(
        id="g-freq-window",
        label="Frequency/Window Matrix Goal",
        goal_type="Wiederkehrende_Ausgabe",
        target_amount_rappen=ANNUAL_AMOUNT_RAPPEN,
        target_wealth_rappen=None,
        target_return_bps=None,
        horizon_years=None,
        target_date=target_date,
        start_date=start_date,
        is_ongoing=0,
        frequency=frequency,
        hardness="Primaer",
        rank=1,
        weight_bps=None,
        value_mode="nominal",
        goal_scope="Beratungsvermoegen",
        pension_pillar=None,
    )


def _annual_total(frequency: str) -> int:
    """Ein voller Jahresbetrag = Periodenbetrag x Faelligkeiten pro Jahr.

    ANNUAL_AMOUNT_RAPPEN ist trotz des Namens der PERIODENbetrag (CHF pro
    Monat bei monatlich) -- so wird goal.target_amount_rappen ueberall in
    diesem Projekt interpretiert.
    """
    return ANNUAL_AMOUNT_RAPPEN * _ANNUALIZATION_MULTIPLIER[frequency]


# Faelligkeiten im Fenster 2027-03-01..2027-09-01 (Anker 1. Maerz):
# monatlich Mrz-Sep = 7, quartalsweise Mrz/Jun/Sep = 3, halbjaehrlich
# Mrz/Sep = 2, jaehrlich Mrz = 1. Explizit ausgeschrieben, weil es genau
# NICHT die Annualisierungs-Multiplikatoren sind -- das war der Fehler.
_MAR_TO_SEP_OCCURRENCES = {
    "monatlich": 7,
    "quartalsweise": 3,
    "halbjaehrlich": 2,
    "jaehrlich": 1,
}


@pytest.mark.parametrize("frequency", FREQUENCIES)
def test_same_year_window_books_one_bucket_with_only_the_due_instalments(frequency):
    """Start und Ziel im selben Kalenderjahr: EIN Bucket, aber nur die
    tatsaechlich faelligen Raten.

    Dieser Test war als "positive control (already correct today)"
    deklariert und verlangte den vollen Jahresbetrag. Das Fenster
    1.3.-1.9.2027 ist aber ein halbes Jahr, nicht eines: monatlich sind es
    sieben Raten, nicht zwoelf. Die Label-Formel traf hier nur die
    BUCKET-ZAHL zufaellig richtig -- der Betrag war um fuenf Raten zu hoch.
    Korrigiert mit ADR-2 (Owner-Entscheid 2026-10-11).
    """
    goal = _make_goal(frequency=frequency, start_date="2027-03-01", target_date="2027-09-01")
    liab = goal_to_liability(goal, horizon_years=10)

    nonzero_buckets = [amount for amount in liab.liability_path_rappen if amount]
    assert len(nonzero_buckets) == 1
    expected = _MAR_TO_SEP_OCCURRENCES[frequency] * ANNUAL_AMOUNT_RAPPEN
    assert liab.target_amount_rappen == expected


@pytest.mark.parametrize("frequency", FREQUENCIES)
def test_exact_two_year_span_ending_dec31_books_exactly_two_buckets(frequency):
    """Echte Positivkontrolle: start=2027-01-01, target=2028-12-31.

    Zwei VOLLE Kalenderjahre, auf beiden Seiten an der Jahresgrenze
    ausgerichtet -- hier stimmen Label-Zaehlung und Occurrence-Zaehlung
    tatsaechlich ueberein, und zwar nicht zufaellig: ein Fenster, das am
    1.1. beginnt und am 31.12. endet, enthaelt pro Jahr genau einen vollen
    Frequenz-Zyklus. Das ist der Grund, warum der Fehler lange unentdeckt
    blieb -- Testdaten werden gern so gewaehlt."""
    goal = _make_goal(frequency=frequency, start_date="2027-01-01", target_date="2028-12-31")
    liab = goal_to_liability(goal, horizon_years=10)

    nonzero_buckets = [amount for amount in liab.liability_path_rappen if amount]
    assert len(nonzero_buckets) == 2
    assert liab.target_amount_rappen == 2 * _annual_total(frequency)


@pytest.mark.parametrize("frequency", FREQUENCIES)
def test_one_day_cross_year_straddle_books_one_bucket_not_two(frequency):
    """start=2027-12-31, target=2028-01-01 -- ein Kalendertag, also genau
    EINE Faelligkeit (31.12.2027).

    Die Label-Formel zaehlte zwei Jahres-Labels (2027, 2028) und buchte in
    jedes den vollen Jahresbetrag. Der Test prueft jetzt beides: einen
    Bucket UND den Betrag einer einzigen Rate. Die Betrags-Assertion
    verlangte vorher ``_annual_total(frequency)`` und war damit nur fuer
    'jaehrlich' richtig -- dort ist eine Rate zufaellig der Jahresbetrag.
    """
    goal = _make_goal(frequency=frequency, start_date="2027-12-31", target_date="2028-01-01")
    liab = goal_to_liability(goal, horizon_years=10)

    nonzero_buckets = [amount for amount in liab.liability_path_rappen if amount]
    assert len(nonzero_buckets) == 1, (
        f"expected a single occurrence bucket, got {len(nonzero_buckets)} "
        f"({nonzero_buckets}) -- Dec31/Jan1 boundary double-booked at {frequency}"
    )
    assert liab.target_amount_rappen == ANNUAL_AMOUNT_RAPPEN


@pytest.mark.parametrize("frequency", FREQUENCIES)
def test_exact_two_year_span_landing_on_jan1_books_three_buckets_but_one_extra_instalment(
    frequency,
):
    """start=2027-01-01, target=2029-01-01 -- DREI Buckets, 2 Jahre + 1 Rate.

    Dieser Test verlangte zwei Buckets und genau zwei Jahresbetraege. Beides
    ist falsch, und zwar aus demselben Grund: ``valid_until`` ist INKLUSIV
    (ADR-2a, bestaetigt; etablierte Projekt-Konvention fuer Cashflows). Die
    Rate am 1.1.2029 ist also faellig und faellt ins Kalenderjahr 2029 --
    es gibt drei belastete Buckets.

    Der Befund an dieser Konstellation ist nicht die Bucket-ZAHL, sondern
    der BETRAG: die Label-Formel buchte in das dritte Bucket einen vollen
    Jahresbetrag, obwohl dort nur eine einzige Rate faellig ist. Bei
    monatlich sind das 25 Raten statt 36 -- 44 % zu viel.
    """
    goal = _make_goal(frequency=frequency, start_date="2027-01-01", target_date="2029-01-01")
    liab = goal_to_liability(goal, horizon_years=10)

    nonzero_buckets = [amount for amount in liab.liability_path_rappen if amount]
    assert len(nonzero_buckets) == 3, (
        f"expected three occurrence buckets (inclusive endpoint), got "
        f"{len(nonzero_buckets)} ({nonzero_buckets}) at {frequency}"
    )
    assert liab.target_amount_rappen == 2 * _annual_total(frequency) + ANNUAL_AMOUNT_RAPPEN
    # Das dritte Bucket traegt genau EINE Rate, keinen Jahresbetrag.
    assert nonzero_buckets[-1] == ANNUAL_AMOUNT_RAPPEN
