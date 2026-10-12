"""Red test for GOAL-PAST-DATE-LIFECYCLE-001 (round 38), Pflichttest 1.

See docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md.

`_resolve_target_year_index()` in services/optimizer/goal_liabilities.py does
`years = max(1, calendar_years_until(anchor))` and never threads an explicit
lifecycle decision. `calendar_years_until()` returns 0 for any target_date
on or before the valuation date (today, yesterday, an exact past anniversary),
so all of these collapse to `target_year_index == 1` -- byte-identical to a
goal that is genuinely due in exactly one year. There is no field on
`GoalLiability` (see its dataclass definition) that distinguishes a past/
overdue/due-today goal from a normal future one.

This test documents the required contract (`GOAL-PAST-DATE-LIFECYCLE-001`,
Reparaturvertrag item 1: "Ein Goal besitzt einen typisierten Lifecycle") by
asserting that genuinely past-dated and today-dated one-off/wealth goals are
NOT silently indistinguishable from a true "due in exactly one year" goal.
It currently fails because no such lifecycle marker exists.
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

from sqlalchemy.orm import configure_mappers
from database import Base
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
configure_mappers()

from services.optimizer.goal_liabilities import goal_to_liability


def _make_goal(*, goal_type: str, target_date: str, goal_id: str = "g1"):
    return SimpleNamespace(
        id=goal_id,
        label="Lifecycle-Boundary",
        goal_type=goal_type,
        target_amount_rappen=100_00 if goal_type == "Einmalige_Ausgabe" else None,
        target_wealth_rappen=500_000_00 if goal_type == "Vermoegensziel" else None,
        target_return_bps=None,
        horizon_years=10,
        target_date=target_date,
        start_date=None,
        is_ongoing=0,
        frequency=None,
        hardness="Primaer",
        rank=2,
        weight_bps=None,
        value_mode="nominal",
        goal_scope="Beratungsvermoegen",
        pension_pillar=None,
    )


#: Zustaende, die ein vergangenes oder heute faelliges Ziel von einem echten
#: Zukunftsziel UNTERSCHEIDEN. ``planned`` gehoert ausdruecklich nicht dazu.
_PAST_OR_DUE_STATES = frozenset({
    "overdue",
    "due",
    "fulfilled",
    "cancelled",
    "accepted_as_due_now",
    "historical_unknown",
    "inactive",
})


def _has_lifecycle_marker(liab) -> bool:
    """Unterscheidet dieses Ziel sich nachweislich von einem Zukunftsziel?

    GESCHAERFT am 2026-10-11 (ADR-3 Etappe 1). Vorher genuegte ein
    BELIEBIGES nicht-``None`` ``lifecycle_status``:

        if lifecycle_status is not None:
            return True

    Seit jede Liability einen typisierten Zustand traegt -- auch
    ``planned`` -- waere dieser Test damit trivial gruen geworden, ohne dass
    ein vergangenes Ziel von einem Jahr-eins-Ziel zu unterscheiden ist.
    Genau das ist die Aussage, die hier geprueft werden soll.

    Der Helfer verlangt deshalb einen Zustand aus ``_PAST_OR_DUE_STATES``
    (oder, als Rueckfall fuer Kanaele ohne typisiertes Feld, einen
    sprechenden Hinweistext).
    """
    lifecycle_status = getattr(liab, "lifecycle_status", None)
    if lifecycle_status in _PAST_OR_DUE_STATES:
        return True
    if lifecycle_status == "planned":
        # Ausdruecklich KEIN Marker: ein vergangenes Ziel, das als
        # "planned" ausgewiesen wird, ist der Befund, nicht sein Fix.
        return False
    note = (liab.evaluation_note or "") if hasattr(liab, "evaluation_note") else ""
    return any(
        marker in note.lower()
        for marker in ("past", "overdue", "ueberfaellig", "vergangen", "faellig heute")
    )


@pytest.mark.parametrize("goal_type", ["Einmalige_Ausgabe", "Vermoegensziel"])
@pytest.mark.parametrize(
    "label,offset_days",
    [
        pytest.param("yesterday", -1),
        pytest.param("today", 0),
        ("tomorrow", 1),
        pytest.param("one_year_past_anniversary", -365),
    ],
)
def test_past_present_future_boundary_needs_explicit_lifecycle(goal_type, label, offset_days):
    today = date.today()
    target = today + timedelta(days=offset_days)
    goal = _make_goal(goal_type=goal_type, target_date=target.isoformat())

    liab = goal_to_liability(goal, horizon_years=10)

    if offset_days > 0:
        # Genuinely future (tomorrow): a real "due in ~1 year" goal. Not the
        # focus of this test, but pinned so the matrix stays self-documenting.
        assert liab.target_year_index == 1
        return

    # gestern / heute / vor einem Jahr: alle faellig oder ueberfaellig, keines
    # "in genau einem Jahr faellig".
    #
    # Die frueher hier gepinnte Erwartung ``target_year_index == 1`` hielt den
    # ``max(1, calendar_years_until(...))``-Clamp als Ist-Zustand fest. Seit
    # ADR-2/ADR-3 gilt sie nicht mehr einheitlich: ein Ziel im laufenden
    # Kalenderjahr (gestern/heute) liegt in Bucket 1, ein Ziel im Vorjahr
    # bekommt den Ausserhalb-Sentinel ``horizon_years + 1``, damit kein
    # negativer Index entsteht (siehe
    # tests/test_goal_liability_target_year_index_never_wraps.py).
    #
    # Der Index ist hier ohnehin nicht die Aussage -- entscheidend ist, dass
    # das Ziel als vergangen/faellig ERKENNBAR ist.
    assert liab.target_year_index >= 1, liab.target_year_index
    assert _has_lifecycle_marker(liab), (
        f"{label}: GOAL-PAST-DATE-LIFECYCLE-001 — a past/overdue/due-today goal "
        f"must expose an explicit lifecycle marker distinguishing it from a goal "
        f"genuinely due in one year. No such marker exists today, so this goal "
        f"is silently reactivated as a normal future year-1 liability."
    )
