"""Pflichttest 6 (GOAL-RECURRENCE-SCHEDULE-001).

Audit: docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md

services.optimizer.goal_liabilities._build_recurring_outflow() (the scheduler
behind Wiederkehrende_Ausgabe / Pensionsausgabe) assigns the FULL annualized
amount to every calendar-year *label* touched by [start_date, target_date] --
``duration`` is computed as ``target_date.year - start_date.year + 1``, a count
of distinct year labels, not of elapsed time. services.cashflow_timeline's
``contribution_for_year`` (the canonical enumerator, already pinned by
property tests in tests/test_cashflow_annualization_properties.py) instead
walks the real occurrence dates inside the window per calendar year.

For an identical (frequency, start, end/ongoing, amount) contract the two
schedulers should describe the same per-period occurrence series. They
currently do not: whenever a contract starts or ends off a year boundary (or
spans very little real time while still touching several year labels), goal
liabilities over- or under-counts relative to the real occurrence enumerator.

This file builds several equivalent contracts, runs each one through BOTH
schedulers and asserts parity. All assertions are expected to fail today;
see the ``xfail`` marker below.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy.orm import configure_mappers
from database import Base
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
configure_mappers()

from services.optimizer.goal_liabilities import goal_to_liability
from services.cashflow_timeline import contribution_for_year


pytestmark = pytest.mark.xfail(
    strict=True,
    reason=(
        "GOAL-RECURRENCE-SCHEDULE-001 -- round 38 red test, see "
        "docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md"
    ),
)


AMOUNT = 1_000_00  # CHF 1'000 pro Periode (vor Annualisierung)
FREQUENCIES = ["monatlich", "quartalsweise", "halbjährlich", "jährlich"]


def _make_recurring_goal(
    *,
    goal_type: str = "Wiederkehrende_Ausgabe",
    amount_rappen: int,
    frequency: str,
    start_date: str,
    target_date: str | None = None,
    is_ongoing: int = 0,
):
    """Mock-Goal (SimpleNamespace, kein DB-Objekt noetig) -- nominal, unconditional."""
    return SimpleNamespace(
        id="parity-goal",
        label="Parity",
        goal_type=goal_type,
        target_amount_rappen=amount_rappen,
        target_wealth_rappen=None,
        target_return_bps=None,
        horizon_years=None,
        target_date=target_date,
        start_date=start_date,
        is_ongoing=is_ongoing,
        frequency=frequency,
        hardness="Primaer",
        rank=2,
        weight_bps=None,
        value_mode="nominal",
        goal_scope="Beratungsvermoegen",
        pension_pillar=None,
    )


def _goal_liability_bucket_series(goal, *, horizon_years: int) -> tuple[int, list[int]]:
    """target_year_index + liability_path_rappen aus goal_liabilities' Scheduler."""
    liab = goal_to_liability(goal, horizon_years=horizon_years)
    return liab.target_year_index, liab.liability_path_rappen


def _cashflow_timeline_series(
    *,
    amount_rappen: int,
    frequency: str,
    start_date: date,
    end_date: date | None,
    calendar_years: list[int],
) -> list[int]:
    """Reale per-Kalenderjahr Occurrence-Betraege ueber den kanonischen Enumerator."""
    return [
        contribution_for_year(
            amount_rappen=amount_rappen,
            frequency=frequency,
            nature="wiederkehrend",
            valid_from=start_date.isoformat(),
            valid_until=end_date.isoformat() if end_date else None,
            year=year,
        )
        for year in calendar_years
    ]


def _assert_parity(
    *,
    goal_type: str,
    frequency: str,
    start: date,
    end: date | None,
    is_ongoing: int,
    horizon_years: int,
) -> None:
    goal = _make_recurring_goal(
        goal_type=goal_type,
        amount_rappen=AMOUNT,
        frequency=frequency,
        start_date=start.isoformat(),
        target_date=end.isoformat() if end else None,
        is_ongoing=is_ongoing,
    )
    target_year_index, path = _goal_liability_bucket_series(goal, horizon_years=horizon_years)
    n_buckets = max(0, horizon_years - target_year_index + 1)
    calendar_years = [start.year + offset for offset in range(n_buckets)]
    goal_series = [path[target_year_index - 1 + offset] for offset in range(n_buckets)]
    real_series = _cashflow_timeline_series(
        amount_rappen=AMOUNT,
        frequency=frequency,
        start_date=start,
        end_date=end,
        calendar_years=calendar_years,
    )
    assert goal_series == real_series, (
        f"{goal_type}/{frequency} ab {start.isoformat()} bis "
        f"{end.isoformat() if end else 'laufend'}: goal_liabilities "
        f"(Kalenderjahr-Label-Zaehlung) = {goal_series} != cashflow_timeline "
        f"(reale Occurrence-Enumeration) = {real_series}"
    )


# ============================================================================
# Szenario A: offenes (is_ongoing) Goal mit unterjaehrigem Start.
#
# jaehrlich wird bewusst ausgelassen: bei einem reinen "1x/Jahr, egal welcher
# Monat" Rhythmus faellt in JEDEM Jahr genau eine Occurrence an (so lange
# Start <= Jahresende), weshalb unterjaehriger Start hier zufaellig KEINE
# Divergenz erzeugt -- Szenario B deckt jaehrlich stattdessen ueber eine
# Label-straddle Konstellation ab, die auch fuer jaehrlich garantiert divergiert.
# ============================================================================


def _mid_year_ongoing_start() -> date:
    """Start sicher unterjaehrig (nicht 1. Jan / 31. Dez), robust gegen 'heute'."""
    today = date.today()
    candidate = date(today.year + 2, 9, 15)
    return candidate


@pytest.mark.parametrize("frequency", ["monatlich", "quartalsweise", "halbjährlich"])
def test_ongoing_recurring_goal_parity_vs_cashflow_timeline(frequency):
    """Offenes Wiederkehrende_Ausgabe-Goal: Start-Jahr ist unterjaehrig/partiell
    bei cashflow_timeline, aber goal_liabilities schreibt den vollen
    annualisierten Betrag in jedes Jahr der Laufzeit (inkl. Start-Jahr)."""
    start = _mid_year_ongoing_start()
    _assert_parity(
        goal_type="Wiederkehrende_Ausgabe",
        frequency=frequency,
        start=start,
        end=None,
        is_ongoing=1,
        horizon_years=12,
    )


# ============================================================================
# Szenario B: kurzes Fenster, das drei Kalenderjahr-Labels "beruehrt"
# (Juli Jahr N -> Mitte Januar Jahr N+2), real aber nur ~19 Monate dauert.
# goal_liabilities zaehlt "target_date.year - start_date.year + 1" = 3 Label-
# Jahre und schreibt den vollen Jahresbetrag in alle drei; cashflow_timeline
# enumeriert die tatsaechlichen Occurrences und liefert ein deutlich anderes,
# realistisches Muster (inkl. einem ggf. leeren letzten Jahr).
# ============================================================================


def _straddle_window() -> tuple[date, date]:
    today = date.today()
    start = date(today.year + 3, 7, 1)
    end = date(today.year + 5, 1, 15)
    return start, end


@pytest.mark.parametrize("frequency", FREQUENCIES)
def test_label_straddling_window_parity_vs_cashflow_timeline(frequency):
    """Kurzlebiges Fenster, das 3 Kalenderjahr-Labels beruehrt: goal_liabilities
    ueberzaehlt (3x voller Jahresbetrag), cashflow_timeline enumeriert real."""
    start, end = _straddle_window()
    _assert_parity(
        goal_type="Wiederkehrende_Ausgabe",
        frequency=frequency,
        start=start,
        end=end,
        is_ongoing=0,
        horizon_years=10,
    )


def test_pensionsausgabe_shares_the_same_divergence():
    """Pensionsausgabe durchlaeuft denselben Builder (_build_recurring_outflow)
    wie Wiederkehrende_Ausgabe -- die Divergenz ist nicht auf einen Goal-Typ
    beschraenkt."""
    start, end = _straddle_window()
    _assert_parity(
        goal_type="Pensionsausgabe",
        frequency="monatlich",
        start=start,
        end=end,
        is_ongoing=0,
        horizon_years=10,
    )
