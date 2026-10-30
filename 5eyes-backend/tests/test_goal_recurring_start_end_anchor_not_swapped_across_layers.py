"""GOAL-CALENDAR-HORIZON-PARITY-001 (round 38), Pflichttest 6 -- Start-/Endanker.

Befund: fuer einen Strom mit Start- UND Enddatum loesten zwei Schichten ihren
Anker von entgegengesetzten Enden auf:

- Solver (``goal_liabilities._resolve_target_year_index``): ``start_date`` zuerst;
- Reserve / deterministische Zielanalyse (``portfolio_engine_payload.
  _goal_projection_years``): ``target_date`` zuerst.

Eine Rente ab in 2 Jahren mit Ende in 7 Jahren galt der Reserve damit als
"in 7 Jahren faellig" (Reserve 50 %), dem Solver als "beginnt in 2 Jahren".

GESCHLOSSEN 2026-10-25: beide Schichten ankern auf dem BEGINN. Die beiden
Rueckgabewerte sind verschiedene Groessen (Solver: Kalenderjahr-Bucket nach
ADR-2; Reserve: verstrichene Jahre nach ADR-1a) und unterscheiden sich um 0
oder 1 -- verglichen wird deshalb, dass beide aus DEMSELBEN Datum entstehen.
Der fruehere Reproducer setzte beide Groessen gleich; das haette auch nach
dem Fix nie gehalten.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy.orm import configure_mappers  # noqa: E402
from database import Base  # noqa: E402,F401
from models import (  # noqa: E402,F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
configure_mappers()

from services.calendar_horizon import add_calendar_years, calendar_years_until  # noqa: E402
from services.optimizer.goal_liabilities import goal_to_liability  # noqa: E402
from services.portfolio_engine import _goal_reserve_for_goal  # noqa: E402
from services.portfolio_engine_payload import _goal_projection_years  # noqa: E402
from services.valuation_clock import bound_valuation_date  # noqa: E402

VALUATION = date(2026, 10, 25)


def _make_recurring_goal(*, start_date: date | None, target_date: date | None) -> SimpleNamespace:
    return SimpleNamespace(
        id="g-anchor-swap",
        label="Anchor-Swap Recurring Goal",
        goal_type="Wiederkehrende_Ausgabe",
        target_amount_rappen=100 * 100,
        target_wealth_rappen=None,
        target_return_bps=None,
        horizon_years=None,
        target_date=target_date.isoformat() if target_date else None,
        start_date=start_date.isoformat() if start_date else None,
        is_ongoing=0,
        frequency="jaehrlich",
        hardness="Primaer",
        rank=1,
        weight_bps=None,
        value_mode="nominal",
        goal_scope="Beratungsvermoegen",
        pension_pillar=None,
        probability_pct=None,
    )


def test_optimizer_and_reserve_mc_resolve_the_same_anchor_year_for_recurring_goal():
    """5-jaehriger Strom, Beginn in 2 Jahren: beide Schichten leiten aus dem
    BEGINN ab (vorher Solver 3 Buckets, Reserve 7 Jahre)."""
    start = add_calendar_years(VALUATION, 2)
    end = add_calendar_years(start, 5)
    goal = _make_recurring_goal(start_date=start, target_date=end)

    with bound_valuation_date(VALUATION):
        optimizer_bucket = goal_to_liability(goal, horizon_years=20).target_year_index
        reserve_years = _goal_projection_years(goal)
        assert reserve_years == calendar_years_until(start)

    assert optimizer_bucket == start.year - VALUATION.year + 1
    assert reserve_years == 2
    assert optimizer_bucket - reserve_years in (0, 1)


def test_reserve_reacts_to_the_stream_start_not_its_end():
    """Wirkung: Beginn in 2 Jahren (<= 3) -> volle Reserve, unabhaengig davon,
    dass der Strom erst in 7 Jahren endet (vorher: 50 %)."""
    start = add_calendar_years(VALUATION, 2)
    goal = _make_recurring_goal(start_date=start, target_date=add_calendar_years(start, 5))
    with bound_valuation_date(VALUATION):
        assert _goal_reserve_for_goal(goal) == 100 * 100


def test_single_point_in_time_goal_has_no_anchor_ambiguity():
    """Positivkontrolle: fallen Beginn und Ende zusammen, ist die Ankerwahl
    wirkungslos -- nur Beginn bzw. nur Ende liefern dieselben Werte."""
    same = add_calendar_years(VALUATION, 3)
    with bound_valuation_date(VALUATION):
        both = _make_recurring_goal(start_date=same, target_date=same)
        only_start = _make_recurring_goal(start_date=same, target_date=None)
        only_target = _make_recurring_goal(start_date=None, target_date=same)
        bucket = goal_to_liability(both, horizon_years=20).target_year_index
        years = _goal_projection_years(both)
        assert bucket == same.year - VALUATION.year + 1
        assert years == calendar_years_until(same)
        assert goal_to_liability(only_start, horizon_years=20).target_year_index == bucket
        assert _goal_projection_years(only_target) == years
