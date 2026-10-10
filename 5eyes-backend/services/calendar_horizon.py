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


def recurring_outflow_window(
    *,
    start_date: date | None,
    target_date: date | None,
    is_ongoing: bool,
    fallback_horizon_years: int | None,
    horizon_years: int,
    as_of: date | None = None,
) -> tuple[int, int]:
    """Kanonisches Outflow-Fenster eines wiederkehrenden Ziels.

    Returns ``(first_year_index, duration_years)`` -- 1-based, ungeklammert
    im Startindex (ein Start jenseits des Horizonts liefert duration=0).
    Die belasteten Jahre sind damit
    ``first_year_index .. first_year_index + duration_years - 1``.

    GOAL-RECURRENCE-SCHEDULE-001 (2026-10-10): Solver und Reporting-MC
    leiteten dieses Fenster vorher UNABHAENGIG voneinander ab und kamen zu
    verschiedenen Kalenderjahren:

    - Der Solver (services/optimizer/goal_liabilities.py) ankert auf
      ``start_date`` und zaehlt Jahrestage (``calendar_years_until``).
    - Der Reporting-MC (services/portfolio_engine_mc_simulation.py) ankerte
      via ``_goal_projection_years`` auf ``target_date`` und rechnete mit
      Tageszaehlung/Aufrundung (``(delta_days + 364) // 365``) -- also mit
      invertierter Anker-PRIORITAET *und* anderer Rundung.

    Beide Abweichungen hoben sich bei der Gesamtsumme oft auf, verorteten
    den Outflow aber in anderen Jahren. Fuer eine Pensionsausgabe ist der
    ``start_date``-Anker der fachlich richtige: die Rente beginnt bei
    Pensionierung, nicht am Ende der Rentenlaufzeit. Diese Funktion ist
    jetzt die EINZIGE Herleitung; sie reproduziert bewusst exakt die
    bisherige Solver-Semantik, damit die Optimizer-Seite unveraendert
    bleibt und nur der abweichende Reporting-Pfad korrigiert wird.
    """
    anchor = start_date or target_date
    if anchor is not None:
        first_year_index = max(1, calendar_years_until(anchor, as_of=as_of))
    else:
        first_year_index = max(1, int(fallback_horizon_years or 1))

    horizon = int(horizon_years)
    if first_year_index > horizon:
        return first_year_index, 0

    remaining_in_horizon = horizon - first_year_index + 1
    if start_date is not None and target_date is not None and target_date >= start_date:
        full_years = int(target_date.year) - int(start_date.year) + 1
        return first_year_index, max(0, min(full_years, remaining_in_horizon))
    if is_ongoing:
        return first_year_index, max(1, remaining_in_horizon)
    return first_year_index, 1
