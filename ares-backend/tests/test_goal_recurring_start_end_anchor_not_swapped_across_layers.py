"""Red test for GOAL-CALENDAR-HORIZON-PARITY-001 (round 38), Pflichttest 6.

See docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md
(this path does not exist in this worktree's git history -- confirmed via
Glob/git log --all; derived directly from reading
services/optimizer/goal_liabilities.py and
services/portfolio_engine_payload.py, and from empirically running both
before writing assertions).

For a recurring (``Wiederkehrende_Ausgabe``/``Pensionsausgabe``) goal with
BOTH ``start_date`` and ``target_date`` set -- the ordinary case, since a
finite recurring expense has both a start and an end -- two independent
production modules each resolve a single-year "anchor index" for the goal,
but from opposite ends of the window:

- ``goal_liabilities._resolve_target_year_index()`` (optimizer consumer):
  ``anchor = start_date or target_date`` -- prefers START first.
- ``portfolio_engine_payload._goal_projection_years()`` (reserve/MC
  consumer): ``anchor = target_date or (start_date if recurring else
  None)`` -- prefers TARGET first.

Whenever ``start_date`` and ``target_date`` are not equidistant from today
(i.e. the stream has any real duration at all), these two formulas resolve
to different "years from today" distances for the SAME goal -- not a small
rounding difference, but a divergence that grows with the stream's length.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
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

from services.calendar_horizon import calendar_years_until  # noqa: E402
from services.optimizer.goal_liabilities import goal_to_liability  # noqa: E402
from services.portfolio_engine_payload import _goal_projection_years  # noqa: E402


def _make_recurring_goal(
    *, start_date: date | None, target_date: date | None
) -> SimpleNamespace:
    """Mock-Goal as SimpleNamespace -- same pattern as
    tests/test_optimizer_goal_liabilities.py::_make_goal. ``_goal_projection_years``
    additionally needs ``goal_type`` resolvable via ``_norm_text`` (plain
    string compare), which the literal "Wiederkehrende_Ausgabe" satisfies.
    """
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
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "GOAL-CALENDAR-HORIZON-PARITY-001 -- round 38 red test, see "
        "docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md"
    ),
)
def test_optimizer_and_reserve_mc_resolve_the_same_anchor_year_for_recurring_goal():
    """A 5-year recurring stream starting 2 years out: the optimizer
    consumer anchors on start_date (-> 2 years from today) while the
    reserve/MC consumer anchors on target_date (-> 7 years from today) for
    the exact same goal record. Empirically verified against current
    develop: 2 != 7.
    """
    today = date.today()
    start_date = today + timedelta(days=365 * 2)
    target_date = start_date + timedelta(days=365 * 5)

    goal = _make_recurring_goal(start_date=start_date, target_date=target_date)

    optimizer_anchor_years = goal_to_liability(goal, horizon_years=20).target_year_index
    reserve_mc_anchor_years = _goal_projection_years(goal)

    assert optimizer_anchor_years == reserve_mc_anchor_years, (
        "optimizer consumer anchored on start_date and resolved "
        f"{optimizer_anchor_years} years from today, but the reserve/MC "
        f"consumer anchored on target_date and resolved "
        f"{reserve_mc_anchor_years} years from today -- same goal, "
        "same window, incompatible anchors"
    )


def test_single_point_in_time_goal_has_no_anchor_ambiguity():
    """Positivkontrolle: fallen start_date und target_date zusammen, kann die
    ANKER-WAHL nicht mehr ins Gewicht fallen -- beide Konsumenten leiten ihr
    Ergebnis zwangslaeufig aus demselben Datum ab. Damit ist der Befund auf
    echte Mehrjahres-Fenster eingegrenzt und nicht auf einen generell
    kaputten Anker-Mechanismus.

    UMGESTELLT am 2026-10-11 (ADR-2): dieser Test verglich vorher die beiden
    Rueckgabewerte direkt auf Gleichheit. Das geht nicht mehr, weil sie
    seither verschiedene GROESSEN sind, und zwar beide richtig:

    * ``target_year_index`` ist ein KALENDERJAHR-Bucket (ADR-2) -- dieselbe
      Achse, auf der Cashflow-, Inflations- und Steuerserie liegen und auf
      der der Liability-Pfad vom Vermoegen abgezogen wird.
    * ``_goal_projection_years`` ist ein JAHRESTAG-Horizont (ADR-1a) --
      "wie viele Jahresschritte bis zum Ziel".

    Bucket-Ursprung und Horizont-Formel sind zwei verschiedene Achsen; die
    Spec fuehrt sie als eine. Der Test prueft deshalb jetzt, dass jeder
    Konsument sein Ergebnis aus DEMSELBEN Datum herleitet -- das ist die
    Aussage "keine Anker-Ambiguitaet" -- statt zwei verschieden skalierte
    Zahlen gleichzusetzen.
    """
    today = date.today()
    same_date = today + timedelta(days=365 * 3)

    goal = _make_recurring_goal(start_date=same_date, target_date=same_date)

    optimizer_anchor_years = goal_to_liability(goal, horizon_years=20).target_year_index
    reserve_mc_anchor_years = _goal_projection_years(goal)

    # Optimizer: Kalenderjahr-Bucket von same_date (1-based).
    assert optimizer_anchor_years == same_date.year - today.year + 1
    # Reserve/MC: Jahrestag-Horizont bis same_date.
    assert reserve_mc_anchor_years == calendar_years_until(same_date)

    # Beide aus demselben Datum -- die Anker-Wahl (start_date vs. target_date)
    # ist hier wirkungslos, denn es gibt nur ein Datum. Gegenprobe: dasselbe
    # Ziel nur mit start_date bzw. nur mit target_date liefert jeweils
    # unveraenderte Werte.
    only_start = _make_recurring_goal(start_date=same_date, target_date=None)
    only_target = _make_recurring_goal(start_date=None, target_date=same_date)
    assert (
        goal_to_liability(only_start, horizon_years=20).target_year_index
        == optimizer_anchor_years
    )
    assert _goal_projection_years(only_target) == reserve_mc_anchor_years
