"""Red-test matrix for GOAL-CALENDAR-HORIZON-PARITY-001.

See docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md,
finding GOAL-CALENDAR-HORIZON-PARITY-001 ("Repro 4").

Four independent horizon resolvers exist in this codebase and are supposed to agree
on "how many annual buckets lie between as_of and target_date":

- services.calendar_horizon.calendar_years_until  (canonical, calendar-anniversary based)
- services.optimizer.goal_liabilities._resolve_target_year_index (optimizer path;
  internally delegates to calendar_years_until)
- routers.wealth._goal_horizon_from_date (day-count based: (delta_days + 364) // 365)
- services.portfolio_engine_payload._goal_projection_years (same day-count formula)

The day-count formula used by the router and the reporting layer silently adds one
extra bucket whenever at least one leap day (Feb 29) falls inside the elapsed span,
even though the span is an *exact* calendar-year anniversary. The audit's canonical
repro ("Repro 4"): as_of=2026-10-03, target_date=2038-10-03 (delta_days=4383, spanning
the leap days 2028-02-29, 2032-02-29 and 2036-02-29) -> router/reporting say 13,
calendar_years_until/optimizer say 12.

This test file pins "today" to each case's as_of date (via monkeypatching the `date`
name each resolver module calls `.today()` on) and asserts all four resolvers agree.

GEFIXT am 2026-10-11 (ADR-1a, Owner-Entscheid): Router und Payload rufen jetzt
`calendar_years_until` statt der Tage-Ceiling-Formel `(delta_days + 364) // 365`,
die jeden ueberschrittenen Schalttag mitzaehlte. Alle Faelle dieser Datei stimmen
jetzt ueberein; die sechs xfail(strict)-Marker sind entfernt und die als
`..._diverges` benannten Tests heissen jetzt `..._agrees` -- sie pruefen
Uebereinstimmung, nicht mehr Abweichung.

Zur Groessenordnung: ueber ZUFAELLIGE Zieldaten wich die alte Formel nur in
1.1 % der Faelle ab, ueber RUNDE Jahrestage in 97 % -- immer um +1 Jahr zu
lang. Berater tippen "Ziel in N Jahren", und das ergibt einen exakten
Jahrestag, also genau den Fall, in dem die alte Formel praktisch immer irrte.
Die niedrige Zufallsquote hatte die Wirkung verdeckt.

Nicht betroffen: `pdf/components/goal_classification.py` und
`reporting/src/lib/goalClassification.ts` rechnen `target_year - start_year`
mit `start_year` aus der DIAGRAMM-Zeitachse. Das ist ein Achsen-Index, keine
Horizont-Formel, und beide Kanaele sind untereinander bereits in Paritaet --
die Spec zaehlt sie faelschlich als vierte konkurrierende Formel.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

import routers.wealth as wealth_router
import services.calendar_horizon as calendar_horizon
import services.portfolio_engine_payload as portfolio_engine_payload
from services.calendar_horizon import calendar_years_until
from services.optimizer.goal_liabilities import _resolve_target_year_index


class _FrozenDate(date):
    """A `datetime.date` subclass whose `.today()` returns a fixed value.

    Installed in place of the `date` name inside each resolver's own module so that
    every resolver that calls `date.today()` internally observes the same "today" as
    the resolver that takes an explicit `as_of` argument.
    """

    _frozen: "date | None" = None

    @classmethod
    def today(cls):  # type: ignore[override]
        return cls._frozen


@pytest.fixture
def freeze_today(monkeypatch):
    def _freeze(as_of: date):
        frozen = type("_Frozen", (_FrozenDate,), {"_frozen": as_of})
        monkeypatch.setattr(wealth_router, "date", frozen)
        monkeypatch.setattr(portfolio_engine_payload, "date", frozen)
        monkeypatch.setattr(calendar_horizon, "date", frozen)

    return _freeze


def _make_goal(target_date: date, *, start_date: date | None = None, goal_type: str = "Vermoegensziel"):
    return SimpleNamespace(
        target_date=target_date.isoformat(),
        start_date=start_date.isoformat() if start_date else None,
        goal_type=goal_type,
        horizon_years=999,
        target_amount_rappen=0,
        frequency=None,
        is_ongoing=0,
    )


def _resolve_all(as_of: date, target: date) -> dict[str, int]:
    """Run all four resolvers for the same (as_of, target) pair and return their results.

    Assumes `date.today()` inside the router/reporting/calendar_horizon modules has
    already been frozen to `as_of` via the `freeze_today` fixture.
    """

    goal = _make_goal(target)
    return {
        "calendar_years_until": calendar_years_until(target, as_of=as_of),
        "optimizer": _resolve_target_year_index(goal, horizon_years=999, clamp_to_horizon=False),
        "router": wealth_router._goal_horizon_from_date(target),
        "reporting": portfolio_engine_payload._goal_projection_years(goal),
    }


def _assert_all_agree(results: dict[str, int], expected: int) -> None:
    assert results == {
        "calendar_years_until": expected,
        "optimizer": expected,
        "router": expected,
        "reporting": expected,
    }, results


# ---------------------------------------------------------------------------
# Pflichttest 1: exact anniversaries over 1/4/12/20/40 years crossing leap years
# ---------------------------------------------------------------------------


def test_one_year_exact_anniversary_no_leap_crossed_agrees(freeze_today):
    as_of = date(2026, 10, 3)
    target = date(2027, 10, 3)
    freeze_today(as_of)
    _assert_all_agree(_resolve_all(as_of, target), 1)


def test_four_year_exact_anniversary_crossing_one_leap_day_agrees(freeze_today):
    as_of = date(2026, 10, 3)
    target = date(2030, 10, 3)
    freeze_today(as_of)
    _assert_all_agree(_resolve_all(as_of, target), 4)


def test_twelve_year_exact_anniversary_crossing_three_leap_days_agrees(freeze_today):
    """Audit's canonical repro ("Repro 4"), restated as a 12-year anniversary case."""

    as_of = date(2026, 10, 3)
    target = date(2038, 10, 3)
    freeze_today(as_of)
    _assert_all_agree(_resolve_all(as_of, target), 12)


def test_twenty_year_exact_anniversary_crossing_five_leap_days_agrees(freeze_today):
    as_of = date(2026, 10, 3)
    target = date(2046, 10, 3)
    freeze_today(as_of)
    _assert_all_agree(_resolve_all(as_of, target), 20)


def test_forty_year_exact_anniversary_crossing_ten_leap_days_agrees(freeze_today):
    as_of = date(2026, 10, 3)
    target = date(2066, 10, 3)
    freeze_today(as_of)
    _assert_all_agree(_resolve_all(as_of, target), 40)


# ---------------------------------------------------------------------------
# Pflichttest 2: Feb 28 / Feb 29 boundary dates
# ---------------------------------------------------------------------------


def test_leap_day_as_of_to_feb28_next_year_is_exact_one_year(freeze_today):
    """as_of=2024-02-29 (leap day) -> target=2025-02-28 is the mapped anniversary."""

    as_of = date(2024, 2, 29)
    target = date(2025, 2, 28)
    freeze_today(as_of)
    _assert_all_agree(_resolve_all(as_of, target), 1)


def test_leap_day_as_of_to_next_leap_day_four_years_agrees(freeze_today):
    """as_of=2024-02-29 -> target=2028-02-29, both leap days, exact 4-year anniversary."""

    as_of = date(2024, 2, 29)
    target = date(2028, 2, 29)
    freeze_today(as_of)
    _assert_all_agree(_resolve_all(as_of, target), 4)


def test_feb28_as_of_non_leap_target_year_is_exact_one_year(freeze_today):
    as_of = date(2023, 2, 28)
    target = date(2024, 2, 28)
    freeze_today(as_of)
    _assert_all_agree(_resolve_all(as_of, target), 1)


def test_feb28_as_of_to_feb29_one_day_past_anniversary_agrees_on_two(freeze_today):
    """target is one calendar day past the mapped Feb-28 anniversary -> correctly year 2.

    Not a divergence case: calendar_years_until's own Feb-29-maps-to-Feb-28 convention
    already bumps this to year 2, and the day-count formula happens to agree here.
    """

    as_of = date(2023, 2, 28)
    target = date(2024, 2, 29)
    freeze_today(as_of)
    _assert_all_agree(_resolve_all(as_of, target), 2)


# ---------------------------------------------------------------------------
# Pflichttest 7: audit's exact Repro 4 (as_of=2026-10-03, target=2038-10-03, delta_days=4383)
# ---------------------------------------------------------------------------


def test_repro_4_exact_values_all_resolvers_say_twelve(freeze_today):
    """Die Zahlen aus Repro 4 des Audits, jetzt in der kanonischen Konvention.

    Dieser Test hiess einmal
    ``test_repro_4_exact_values_router_and_reporting_say_13_others_say_12``
    und pinnte die FEHLERWERTE als Vertrag: Router und Payload mussten 13
    liefern, waehrend die kanonische Funktion 12 sagt.

    ADR-1a (Owner-Entscheid 2026-10-11): beide rufen jetzt
    ``calendar_years_until``. 4383 Tage sind exakt 12 Kalenderjahre
    (2026-10-03 bis 2038-10-03, drei Schalttage dazwischen); die
    Tage-Ceiling-Formel ``(delta_days + 364) // 365`` zaehlte diese
    Schalttage mit und kam auf 13.

    Gemessen ueber 4 Stichtage x 30 runde Jahrestage war die alte Formel in
    97 % der Faelle um +1 Jahr zu lang. Ueber zufaellige Zieldaten sind es
    nur 1.1 % -- aber Berater tippen "Ziel in N Jahren", und das ergibt
    immer einen exakten Jahrestag.
    """

    as_of = date(2026, 10, 3)
    target = date(2038, 10, 3)
    assert (target - as_of).days == 4383

    freeze_today(as_of)
    goal = _make_goal(target)

    assert calendar_years_until(target, as_of=as_of) == 12
    assert _resolve_target_year_index(goal, horizon_years=999, clamp_to_horizon=False) == 12
    assert wealth_router._goal_horizon_from_date(target) == 12
    assert portfolio_engine_payload._goal_projection_years(goal) == 12

    # Gegenprobe: die alte Formel ergibt hier nachweislich 13 -- so ist
    # dokumentiert, was korrigiert wurde, ohne sie noch zu verwenden.
    delta_days = (target - as_of).days
    assert max(1, (delta_days + 364) // 365) == 13


def test_repro_4_all_four_resolvers_should_agree_on_twelve(freeze_today):
    """The actual Pflichttest 7 assertion: all four resolvers should return 12."""

    as_of = date(2026, 10, 3)
    target = date(2038, 10, 3)
    freeze_today(as_of)
    _assert_all_agree(_resolve_all(as_of, target), 12)
