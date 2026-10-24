"""GOAL-RECURRING-EDITOR-CONTRACT-001 -- Pflichttest 3 (Runde 38 Red-Test).

Kreuzt alle unterstuetzten wiederkehrenden Frequenzen
(jaehrlich/halbjaehrlich/quartalsweise/monatlich, siehe
``services/cashflow_timeline.SUPPORTED_FREQUENCIES`` minus ``einmalig``)
mit den Randwerten von ``target_amount_rappen`` (0, -1, 1, sehr gross)
gegen den echten Domain-Validator ``services/goal_semantics.validate_goal_model_input``.

Zweck: den aktuellen Annahme/Ablehnungs-Rand praezise dokumentieren. Faelle,
die schon korrekt sind, bleiben gruene Regressionstests. Nur Faelle, die vom
dokumentierten Vertrag abweichen, werden mit
``@pytest.mark.xfail(strict=True, ...)`` markiert.

Befund (siehe docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md,
Finding GOAL-RECURRING-EDITOR-CONTRACT-001):

* 0 und -1 werden fuer alle vier Frequenzen korrekt als "positiver Zielbetrag
  fehlt" abgelehnt -- unabhaengig von der Frequenz, da die Betragspruefung in
  ``validate_goal_model_input`` vor jeder frequenzspezifischen Logik greift.
* 1 (kleinster positiver Rappen-Betrag) wird fuer alle vier Frequenzen korrekt
  akzeptiert.
* Ein sehr grosser Betrag (deutlich jenseits des 64-Bit-Integer-Bereichs, in
  dem SQLite seine INTEGER-Spalten speichert -- ``target_amount_rappen`` ist
  in ``models/wealth.py`` und ``models/review.py`` als ``Column(Integer)``
  deklariert) wird AKTUELL klaglos akzeptiert. ``_strict_int`` setzt fuer
  Geschwister-Felder in derselben Funktion (``weight_bps``,
  ``success_probability_min_x100``, ``probability_pct``) explizit ein
  ``maximum``, fuer ``target_amount_rappen`` fehlt diese Deckelung jedoch
  komplett -- ein Bruch mit dem im Modul-Docstring postulierten
  "fail-closed"-Vertrag und mit der SQLite-Persistenzgrenze. Dieses
  Unterfall wird daher xfail(strict=True) markiert, fuer alle vier Frequenzen
  identisch (die Betragspruefung ist frequenzunabhaengig).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy.orm import configure_mappers  # noqa: E402

from database import Base  # noqa: E402, F401
from models import (  # noqa: E402, F401
    allocation,
    clients,
    mandates,
    profiling,
    review,
    snapshots,
    users,
    wealth,
)

configure_mappers()

from services.goal_semantics import GoalInputError, validate_goal_model_input  # noqa: E402

# Die vier wiederkehrenden Frequenzen aus
# services/cashflow_timeline.SUPPORTED_FREQUENCIES, abzueglich "einmalig"
# (das fuer wiederkehrende Ziele explizit verboten ist). ASCII-Schreibweisen
# wie im Formular/Legacy-Datensatz ueblich.
RECURRING_FREQUENCIES = ["jaehrlich", "halbjaehrlich", "quartalsweise", "monatlich"]

# 64-Bit-signed-Integer-Obergrenze, wie sie SQLite fuer eine INTEGER-Spalte
# verwendet (target_amount_rappen ist Column(Integer)).
SQLITE_INT64_MAX = 9_223_372_036_854_775_807
VERY_LARGE_AMOUNT_RAPPEN = SQLITE_INT64_MAX * 1_000  # weit jenseits der Spaltenkapazitaet


def _make_recurring_goal(
    *,
    frequency: str,
    target_amount_rappen: int,
    goal_type: str = "wiederkehrende_ausgabe",
) -> dict:
    """Minimal gueltiges wiederkehrendes Ziel, nur target_amount_rappen variiert."""
    return dict(
        label="Test",
        goal_type=goal_type,
        goal_family="cashflow",
        rank=1,
        weight_bps=None,
        success_probability_min_x100=None,
        probability_pct=None,
        horizon_years=None,
        hardness="primaer",
        goal_scope="beratungsvermoegen",
        value_mode="nominal",
        is_ongoing=1,
        start_date="2024-01-01",
        target_date=None,
        target_amount_rappen=target_amount_rappen,
        target_wealth_rappen=None,
        target_return_bps=None,
        frequency=frequency,
        pension_pillar=None,
    )


# ============================================================================
# Bereits korrekt: target_amount_rappen <= 0 wird fuer jede Frequenz abgelehnt
# ============================================================================


@pytest.mark.parametrize("frequency", RECURRING_FREQUENCIES)
@pytest.mark.parametrize("amount", [0, -1])
def test_non_positive_amount_rejected_for_every_frequency(frequency: str, amount: int) -> None:
    goal = _make_recurring_goal(frequency=frequency, target_amount_rappen=amount)
    with pytest.raises(GoalInputError, match="positiver Zielbetrag fehlt"):
        validate_goal_model_input(goal)


# ============================================================================
# Bereits korrekt: kleinster positiver Betrag (1 Rappen) wird akzeptiert
# ============================================================================


@pytest.mark.parametrize("frequency", RECURRING_FREQUENCIES)
def test_minimal_positive_amount_accepted_for_every_frequency(frequency: str) -> None:
    goal = _make_recurring_goal(frequency=frequency, target_amount_rappen=1)
    validate_goal_model_input(goal)  # darf nicht raisen


# ============================================================================
# RED: sehr grosser Betrag (jenseits der SQLite-INTEGER-Spaltenkapazitaet)
# wird aktuell ohne Obergrenze akzeptiert -- Bruch mit dem fail-closed-Vertrag
# ============================================================================


@pytest.mark.parametrize("frequency", RECURRING_FREQUENCIES)
@pytest.mark.xfail(
    strict=True,
    reason=(
        "GOAL-RECURRING-EDITOR-CONTRACT-001 -- round 38 red test, see "
        "docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md"
    ),
)
def test_absurdly_large_amount_should_be_rejected_but_is_not(frequency: str) -> None:
    """target_amount_rappen hat -- anders als weight_bps/probability-Felder in
    derselben Funktion -- keine obere Schranke. Ein Betrag, der die
    SQLite-INTEGER-Spaltenkapazitaet um den Faktor 1000 uebersteigt, sollte
    vom fail-closed-Validator abgelehnt werden, wird aber aktuell klaglos
    akzeptiert."""
    goal = _make_recurring_goal(
        frequency=frequency, target_amount_rappen=VERY_LARGE_AMOUNT_RAPPEN
    )
    with pytest.raises(GoalInputError):
        validate_goal_model_input(goal)
