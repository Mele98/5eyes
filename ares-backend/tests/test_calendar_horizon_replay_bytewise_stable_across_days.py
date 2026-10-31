"""GOAL-CALENDAR-HORIZON-PARITY-001 (round 38) / ADR-1b -- Replay-Stabilitaet.

Befund: ``goal_liabilities.goal_to_liability()`` las den Bewertungsstichtag aus
der Wanduhr. Derselbe gespeicherte Datensatz lieferte bei einem Replay an einem
anderen Kalendertag andere Buckets -- seit ADR-2 (Kalenderjahr-Buckets) nicht
mehr taeglich, aber am Jahreswechsel weiterhin (Stichtag 31.12. -> Bucket 2,
1.1. -> Bucket 1, Zieldatum 2027-10-05).

GESCHLOSSEN 2026-10-25 (ADR-1b): der Stichtag ist an den Lauf gebunden
(``services/valuation_clock.py``). Ein Lauf bindet ihn beim Ausloesen und
persistiert ihn an der Soll-Allokation; Replays binden den GESPEICHERTEN
Stichtag (``binds_allocation_valuation_date``) oder reichen ihn explizit als
``as_of`` durch. Die Wanduhr bewegt das Ergebnis dann nicht mehr. Ein anderer
Stichtag ist ein ausdruecklicher Counterfactual-Lauf und darf (soll) ein anderes
Ergebnis liefern -- Positivkontrolle unten.

Die Wanduhr wird ueber ``services.valuation_clock.date`` gepinnt: das ist seit
ADR-1b die EINZIGE Lesestelle der Engine.
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

from sqlalchemy.orm import configure_mappers  # noqa: E402
from database import Base  # noqa: E402,F401
from models import (  # noqa: E402,F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
configure_mappers()

import services.calendar_horizon as calendar_horizon  # noqa: E402
import services.valuation_clock as valuation_clock  # noqa: E402
from services.optimizer.goal_liabilities import goal_to_liability, goals_to_liabilities  # noqa: E402
from services.valuation_clock import (  # noqa: E402
    binds_allocation_valuation_date,
    bound_valuation_date,
)

DAY_ONE = date(2026, 10, 4)
DAY_TWO = date(2026, 10, 5)
TARGET_DATE = date(2027, 10, 5)
NEW_YEARS_EVE = date(2026, 12, 31)
NEW_YEAR = date(2027, 1, 1)


class _PinnedToday(date):
    """`date` subclass whose `.today()` returns whatever `pinned` is set to."""

    pinned: date = DAY_ONE

    @classmethod
    def today(cls):
        return cls.pinned


@pytest.fixture()
def wall_clock(monkeypatch):
    """Pinnt die Wanduhr an der einzigen Engine-Lesestelle."""
    monkeypatch.setattr(valuation_clock, "date", _PinnedToday)
    _PinnedToday.pinned = DAY_ONE
    yield _PinnedToday


def _make_wealth_goal() -> SimpleNamespace:
    return SimpleNamespace(
        id="g-replay-stability",
        label="Vermoegensziel Replay Stability",
        goal_type="Vermoegensziel",
        target_amount_rappen=None,
        target_wealth_rappen=100_00,
        target_return_bps=None,
        horizon_years=None,
        target_date=TARGET_DATE.isoformat(),
        start_date=None,
        is_ongoing=0,
        frequency=None,
        hardness="Primaer",
        rank=1,
        weight_bps=None,
        value_mode="nominal",
        goal_scope="Beratungsvermoegen",
        pension_pillar=None,
        probability_pct=None,
        success_probability_min_x100=None,
    )


def test_calendar_years_until_is_stable_when_as_of_is_explicit(wall_clock):
    """Positivkontrolle: mit explizitem `as_of` haengt das Ergebnis nur davon ab."""
    wall_clock.pinned = DAY_ONE
    first = calendar_horizon.calendar_years_until(TARGET_DATE, as_of=DAY_ONE)
    wall_clock.pinned = DAY_TWO
    second = calendar_horizon.calendar_years_until(TARGET_DATE, as_of=DAY_ONE)
    assert first == second == 2


def test_goal_to_liability_replay_is_stable_within_a_calendar_year(wall_clock):
    """Zwei aufeinanderfolgende Kalendertage liefern denselben Bucket (ADR-2)."""
    goal = _make_wealth_goal()
    wall_clock.pinned = DAY_ONE
    day_one = goal_to_liability(goal, horizon_years=10)
    wall_clock.pinned = DAY_TWO
    day_two = goal_to_liability(goal, horizon_years=10)
    assert day_one.target_year_index == day_two.target_year_index
    assert day_one.liability_path_rappen == day_two.liability_path_rappen


def test_bound_valuation_date_makes_replay_stable_across_the_year_boundary(wall_clock):
    """Der Lauf am 31.12. wird am 1.1. mit SEINEM Stichtag nachgerechnet:
    gleicher Bucket, gleicher Pfad -- obwohl die Wanduhr das Jahr gewechselt
    hat. Vorher: Bucket 2 -> 1."""
    goal = _make_wealth_goal()

    wall_clock.pinned = NEW_YEARS_EVE
    with bound_valuation_date(NEW_YEARS_EVE):
        original = goal_to_liability(goal, horizon_years=10)

    wall_clock.pinned = NEW_YEAR
    with bound_valuation_date(NEW_YEARS_EVE):
        replay_bound = goal_to_liability(goal, horizon_years=10)
    replay_explicit = goal_to_liability(goal, horizon_years=10, as_of=NEW_YEARS_EVE)
    replay_batch = goals_to_liabilities([goal], horizon_years=10, as_of=NEW_YEARS_EVE)[0]

    assert original.target_year_index == 2
    for replay in (replay_bound, replay_explicit, replay_batch):
        assert replay.target_year_index == original.target_year_index
        assert replay.liability_path_rappen == original.liability_path_rappen
        assert replay.lifecycle_status == original.lifecycle_status


def test_allocation_replay_binds_the_stored_valuation_date(wall_clock):
    """Der Replay-Dekorator bindet den an der Allokation gespeicherten
    Stichtag fuer den ganzen Rebuild -- unabhaengig von der Wanduhr."""
    goal = _make_wealth_goal()

    @binds_allocation_valuation_date
    def rebuild(db, allocation):
        return valuation_clock.valuation_date(), goal_to_liability(goal, horizon_years=10)

    wall_clock.pinned = NEW_YEAR
    stored = SimpleNamespace(valuation_date=NEW_YEARS_EVE.isoformat())
    bound, liability = rebuild(None, allocation=stored)
    assert bound == NEW_YEARS_EVE
    assert liability.target_year_index == 2

    # Bestand ohne Stichtag: bisheriges Verhalten (Wanduhr).
    legacy_bound, legacy_liability = rebuild(None, SimpleNamespace(valuation_date=None))
    assert legacy_bound == NEW_YEAR
    assert legacy_liability.target_year_index == 1


def test_different_valuation_date_is_an_explicit_counterfactual(wall_clock):
    """Positivkontrolle: ein ANDERER gebundener Stichtag aendert den Bucket
    sichtbar -- die Bindung friert nicht die Wirtschaftlichkeit ein, sie
    macht den Stichtag zur ausdruecklichen Eingabe."""
    goal = _make_wealth_goal()
    before = goal_to_liability(goal, horizon_years=10, as_of=NEW_YEARS_EVE)
    after = goal_to_liability(goal, horizon_years=10, as_of=NEW_YEAR)
    assert (before.target_year_index, after.target_year_index) == (2, 1)
