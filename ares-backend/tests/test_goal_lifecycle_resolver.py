"""ADR-3 Etappe 1: der Lifecycle-Resolver.

GOAL-PAST-DATE-LIFECYCLE-001. Prueft ``services/goal_lifecycle.py`` isoliert
-- ohne DB, ohne Solver -- damit die Zustandslogik eigenstaendig belegt ist,
bevor sie in ``goal_to_liability()`` und in das fail-closed Gate einzieht.

Owner-Entscheide: 3a bestaetigt (sechs Zustaende, append-only auditiert),
3b **Variante 3** (fail-closed), 3c bestaetigt (Begruendung + Actor +
Zeitstempel fuer Terminal-Zustaende).
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.goal_lifecycle import (  # noqa: E402
    ACCEPTED_AS_DUE_NOW,
    CANCELLED,
    DUE,
    FULFILLED,
    HISTORICAL_UNKNOWN,
    INACTIVE,
    OVERDUE,
    PLANNED,
    GoalLifecycleError,
    is_economically_null,
    requires_advisor_resolution,
    resolve_lifecycle_state,
)

AS_OF = date(2026, 10, 11)


def _goal(**kw) -> SimpleNamespace:
    base = {
        "id": "lifecycle-goal",
        "goal_type": "Einmalige_Ausgabe",
        "target_date": None,
        "start_date": None,
        "is_ongoing": 0,
        "is_active": 1,
        "is_included": 1,
    }
    base.update(kw)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# Abgeleitete Zeit-Zustaende
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "offset_days,expected",
    [
        (1, PLANNED),
        (365, PLANNED),
        (0, DUE),
        (-1, OVERDUE),
        (-365, OVERDUE),
        (-3650, OVERDUE),
    ],
)
def test_time_state_is_derived_from_the_target_date(offset_days, expected):
    """Gestern/heute/morgen muessen unterscheidbar sein.

    Genau das war der Befund: ``max(1, calendar_years_until(...))`` machte
    aus jedem vergangenen Datum ein "Jahr 1 ab jetzt", wodurch ein
    ueberfaelliges Ziel von einem echten Jahr-1-Ziel nicht zu
    unterscheiden war.
    """
    goal = _goal(target_date=(AS_OF + timedelta(days=offset_days)).isoformat())
    assert resolve_lifecycle_state(goal, as_of=AS_OF) == expected


def test_derived_state_follows_the_valuation_date_not_the_wall_clock():
    """``as_of`` steuert das Ergebnis -- Vorbereitung fuer ADR-1b."""
    goal = _goal(target_date="2026-10-11")

    assert resolve_lifecycle_state(goal, as_of=date(2026, 10, 10)) == PLANNED
    assert resolve_lifecycle_state(goal, as_of=date(2026, 10, 11)) == DUE
    assert resolve_lifecycle_state(goal, as_of=date(2026, 10, 12)) == OVERDUE


def test_goal_without_any_date_is_planned_not_overdue():
    """Kein Anker heisst nicht ueberfaellig -- es heisst unbestimmt.

    Ein Ziel ohne Datum als ``overdue`` zu fuehren wuerde die Berechnung
    fuer Altbestaende fail-closed blockieren, ohne dass irgendetwas
    tatsaechlich verfallen ist.
    """
    assert resolve_lifecycle_state(_goal(), as_of=AS_OF) == PLANNED


# ---------------------------------------------------------------------------
# Wiederkehrende Stroeme: das ENDE entscheidet, nicht der Beginn
# ---------------------------------------------------------------------------


def test_running_stream_that_started_in_the_past_is_not_overdue():
    """Eine laufende Rente ist nicht ueberfaellig, nur weil sie begonnen hat."""
    goal = _goal(
        goal_type="Pensionsausgabe",
        start_date="2020-01-01",
        target_date="2040-12-31",
        is_ongoing=0,
    )
    assert resolve_lifecycle_state(goal, as_of=AS_OF) == PLANNED


def test_fully_elapsed_stream_is_overdue():
    goal = _goal(
        goal_type="Wiederkehrende_Ausgabe",
        start_date="2018-01-01",
        target_date="2021-12-31",
    )
    assert resolve_lifecycle_state(goal, as_of=AS_OF) == OVERDUE


def test_open_ended_stream_without_end_date_is_never_overdue():
    """``is_ongoing`` ohne Enddatum laeuft per Definition weiter."""
    goal = _goal(
        goal_type="Pensionsausgabe",
        start_date="2015-01-01",
        target_date=None,
        is_ongoing=1,
    )
    assert resolve_lifecycle_state(goal, as_of=AS_OF) == PLANNED


# ---------------------------------------------------------------------------
# Gespeicherte Entscheidungen gewinnen
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "decision",
    [FULFILLED, CANCELLED, ACCEPTED_AS_DUE_NOW, HISTORICAL_UNKNOWN],
)
def test_stored_decision_wins_over_the_date(decision):
    """Ein erfuelltes Ziel bleibt erfuellt, auch wenn sein Datum vergangen ist.

    Deshalb wird die Entscheidung VOR dem Datum geprueft -- sonst kippte
    jedes geklaerte Altziel beim naechsten Lauf wieder auf ``overdue``
    und blockierte die Berechnung erneut.
    """
    goal = _goal(target_date="2020-01-01", lifecycle_decision=decision)
    assert resolve_lifecycle_state(goal, as_of=AS_OF) == decision


def test_unknown_stored_decision_fails_closed():
    """Ein unbekannter persistierter Zustand wird nicht stillschweigend
    als ``planned`` gelesen -- das waere eine erfundene Freigabe."""
    goal = _goal(target_date="2030-01-01", lifecycle_decision="irgendwas")
    with pytest.raises(GoalLifecycleError):
        resolve_lifecycle_state(goal, as_of=AS_OF)


def test_empty_stored_decision_falls_back_to_derivation():
    """Leerstring/None ist "nicht entschieden", nicht "ungueltig"."""
    for empty in (None, "", "   "):
        goal = _goal(target_date="2030-01-01", lifecycle_decision=empty)
        assert resolve_lifecycle_state(goal, as_of=AS_OF) == PLANNED


# ---------------------------------------------------------------------------
# is_active / is_included
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("field", ["is_active", "is_included"])
def test_excluded_goal_is_inactive_not_cancelled(field):
    """``is_active=0`` sagt NICHT, ob erfuellt oder storniert.

    Diese Unterscheidung zu erfinden waere eine Behauptung ueber einen
    Kundensachverhalt, den niemand erfasst hat. Der Zustand heisst deshalb
    ``inactive``: wirtschaftlich null, aber ohne Aussage warum.
    """
    goal = _goal(target_date="2030-01-01", **{field: 0})
    state = resolve_lifecycle_state(goal, as_of=AS_OF)
    assert state == INACTIVE
    assert state not in (CANCELLED, FULFILLED)


def test_stored_decision_still_wins_over_inactive():
    goal = _goal(target_date="2030-01-01", is_active=0, lifecycle_decision=FULFILLED)
    assert resolve_lifecycle_state(goal, as_of=AS_OF) == FULFILLED


def test_missing_is_included_defaults_to_included():
    """Alt-Zeilen ohne das Feld duerfen nicht als ausgeschlossen gelten."""
    goal = _goal(target_date="2030-01-01")
    del goal.is_included
    assert resolve_lifecycle_state(goal, as_of=AS_OF) == PLANNED


# ---------------------------------------------------------------------------
# Praedikate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "state,expected",
    [
        (PLANNED, False),
        (DUE, False),
        (OVERDUE, False),
        (ACCEPTED_AS_DUE_NOW, False),
        (FULFILLED, True),
        (CANCELLED, True),
        (HISTORICAL_UNKNOWN, True),
        (INACTIVE, True),
    ],
)
def test_economically_null_states(state, expected):
    """``overdue`` ist NICHT wirtschaftlich null.

    Das ist bewusst: ein ueberfaelliges Ziel wird nicht weggerechnet,
    sondern blockiert die Berechnung (ADR-3b Variante 3). Es auf null zu
    setzen waere die stille Variante, die der Audit kritisiert -- nur in
    die andere Richtung.
    """
    assert is_economically_null(state) is expected


@pytest.mark.parametrize(
    "state,expected",
    [
        (OVERDUE, True),
        (PLANNED, False),
        (DUE, False),
        (ACCEPTED_AS_DUE_NOW, False),
        (FULFILLED, False),
        (CANCELLED, False),
        (HISTORICAL_UNKNOWN, False),
        (INACTIVE, False),
    ],
)
def test_requires_advisor_resolution(state, expected):
    assert requires_advisor_resolution(state) is expected


def test_accepted_as_due_now_resolves_the_block():
    """ADR-3b Variante 1: der Berater uebernimmt den Betrag als t0-Bedarf.

    Danach darf gerechnet werden, und das Ziel traegt weiter eine
    Verbindlichkeit -- es ist geklaert, nicht erledigt.
    """
    goal = _goal(target_date="2020-01-01", lifecycle_decision=ACCEPTED_AS_DUE_NOW)
    state = resolve_lifecycle_state(goal, as_of=AS_OF)

    assert state == ACCEPTED_AS_DUE_NOW
    assert requires_advisor_resolution(state) is False
    assert is_economically_null(state) is False


def test_rescheduling_resolves_the_block_without_its_own_state():
    """ADR-3b Variante 2 braucht keinen eigenen Zustand.

    Der Berater setzt ein neues Zieldatum; der abgeleitete Zustand wird
    dadurch von selbst wieder ``planned``. Ein zusaetzlicher Zustand
    waere eine Dublette, die veralten koennte.
    """
    overdue = _goal(target_date="2020-01-01")
    assert requires_advisor_resolution(
        resolve_lifecycle_state(overdue, as_of=AS_OF)
    ) is True

    rescheduled = _goal(target_date="2031-06-01")
    assert resolve_lifecycle_state(rescheduled, as_of=AS_OF) == PLANNED
    assert requires_advisor_resolution(
        resolve_lifecycle_state(rescheduled, as_of=AS_OF)
    ) is False
