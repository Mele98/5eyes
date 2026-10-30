"""Atomare Ziel-Reihenfolge (GOAL-RANK-HARDNESS-ROUNDTRIP-001, ADR-10c).

``rank`` ist die kanonische Prioritaet eines Ziels (Owner-Entscheid 10a): aus
ihm leiten sich das Default-Gewicht (``goal_liabilities._weight_bps``), der
Prioritaets-Scope der Finanzierung und das Hauptziel ab. Eine neue
Reihenfolge wird deshalb nie aus Einzel-Updates zusammengesetzt, sondern als
vollstaendige Permutation aller aktiven Ziele eines Mandats geschrieben:

* jede aktive Ziel-ID genau einmal, keine fremde oder doppelte ID;
* Raenge danach lueckenlos und eindeutig ``1..n`` in der uebergebenen Folge;
* optional ``expected_goal_ids``: die Reihenfolge, die der Client zuletzt
  gesehen hat. Weicht der Serverstand davon ab (paralleler Reorder oder
  Edit), wird abgelehnt statt einen fremden Stand zu ueberschreiben (CAS).

Die Haerte (``hardness``) bleibt unberuehrt -- Rang und Haerte sind getrennte
Felder.
"""
from __future__ import annotations

from typing import Iterable, Sequence


class GoalOrderError(ValueError):
    """Die uebergebene Reihenfolge ist keine gueltige Permutation."""


class GoalOrderConflictError(ValueError):
    """Der Serverstand weicht von der erwarteten Reihenfolge ab."""


def _matches_server_order(goals: Iterable, expected_goal_ids: Sequence[str]) -> bool:
    """True, wenn die erwartete Folge zum Serverstand passt.

    Passt heisst: dieselben Ziele, und die Raenge entlang der erwarteten Folge
    fallen nie. Gleichrangige Altdaten (doppelter Rang) erlauben jede
    Reihenfolge untereinander -- der Client kennt dafuer keine eindeutige
    Folge, und ein Fehlalarm wuerde das Aufraeumen genau solcher Daten
    blockieren.
    """
    rank_by_id = {str(goal.id): int(goal.rank or 0) for goal in goals}
    expected = [str(goal_id) for goal_id in expected_goal_ids]
    if len(set(expected)) != len(expected) or set(expected) != set(rank_by_id):
        return False
    ranks = [rank_by_id[goal_id] for goal_id in expected]
    return all(a <= b for a, b in zip(ranks, ranks[1:]))


def resolve_goal_order(
    goals: Sequence,
    goal_ids: Sequence[str],
    expected_goal_ids: Sequence[str] | None = None,
) -> dict[str, int]:
    """Validiert die Permutation und liefert ``{goal_id: neuer_rang}``."""
    active_ids = [str(goal.id) for goal in goals]
    requested = [str(goal_id) for goal_id in goal_ids]
    if len(set(requested)) != len(requested):
        raise GoalOrderError("Die Reihenfolge enthaelt eine Ziel-ID mehrfach.")
    if set(requested) != set(active_ids):
        missing = sorted(set(active_ids) - set(requested))
        unknown = sorted(set(requested) - set(active_ids))
        raise GoalOrderError(
            "Die Reihenfolge muss jedes aktive Ziel genau einmal enthalten"
            + (f"; fehlend: {', '.join(missing)}" if missing else "")
            + (f"; unbekannt: {', '.join(unknown)}" if unknown else "")
            + "."
        )
    if expected_goal_ids is not None and not _matches_server_order(goals, expected_goal_ids):
        raise GoalOrderConflictError(
            "Die Ziel-Reihenfolge wurde inzwischen geaendert. Bitte neu "
            "laden und erneut sortieren."
        )
    return {goal_id: index + 1 for index, goal_id in enumerate(requested)}
