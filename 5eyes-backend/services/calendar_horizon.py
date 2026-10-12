"""Canonical calendar-year horizon arithmetic.

Optimizer years are annual liability/simulation buckets, so their boundary is
the calendar anniversary of the valuation date, not a fixed 365-day span.
"""

from __future__ import annotations

from datetime import date


def add_calendar_years(value: date, years: int) -> date:
    """Shift a date by whole calendar years.

    February 29 maps to February 28 when the destination year is not a leap
    year. This is the same convention used for goal-sensitivity date shifts.
    """

    destination_year = int(value.year) + int(years)
    try:
        return value.replace(year=destination_year)
    except ValueError:
        if value.month == 2 and value.day == 29:
            return value.replace(year=destination_year, day=28)
        raise


def calendar_years_until(
    target_date: date,
    *,
    as_of: date | None = None,
) -> int:
    """Return the number of annual buckets needed to include ``target_date``.

    An exact N-year anniversary maps to N; the following calendar day maps to
    N+1. Dates on or before the valuation date require zero future buckets.
    Callers that model a mandatory first year may apply ``max(1, result)``.
    """

    valuation_date = as_of or date.today()
    if target_date <= valuation_date:
        return 0

    candidate_years = max(0, int(target_date.year) - int(valuation_date.year))
    anniversary = add_calendar_years(valuation_date, candidate_years)
    if target_date > anniversary:
        candidate_years += 1
    return candidate_years


# GOAL-RECURRENCE-SCHEDULE-001 / ADR-2c (2026-10-11): recurring_outflow_window
# ist ersatzlos ENTFERNT. Sie lieferte (erster Jahrestag-Bucket, Dauer in
# Kalenderjahr-Labels) und war damit in BEIDEN Komponenten die Konvention, die
# ADR-2 beseitigt: der Startindex lag auf der Jahrestag-Achse (waehrend
# Cashflow-, Inflations- und Steuerserie Kalenderjahre benutzen), und die Dauer
# zaehlte beruehrte Jahres-Labels statt Faelligkeiten.
#
# Ersatz fuer beide Aufrufer (services/optimizer/goal_liabilities.py und
# services/portfolio_engine_mc_simulation.py):
#   services/cashflow_timeline.py::recurring_occurrence_series()
# Sie liefert direkt die Betraege pro Kalenderjahr-Bucket; "Dauer in Jahren"
# existiert als Begriff nicht mehr, weil ein Teiljahr ein Bucket ist, aber
# nicht ein Jahresbetrag.
