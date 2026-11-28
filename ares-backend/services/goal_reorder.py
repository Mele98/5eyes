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


GOAL_ORDER_CHANGED_DETAIL = (
    "Die Ziel-Reihenfolge wurde zwischenzeitlich geaendert. Bitte neu laden "
    "und erneut sortieren."
)


def acquire_goal_order_write_lock(db) -> None:
    """N-868-2: Schreibsperre VOR dem Lesen der Ziele nehmen.

    Ohne Sperre konnte ein paralleler Reorder zwischen Lesen (inkl.
    ``expected_goal_ids``-Pruefung) und Schreiben committen: der eigene
    Stand war dann veraltet, das Schreiben lief in ``ux_goals_rank_active``
    (500) oder ueberschrieb die fremde Reihenfolge trotz CAS.

    * SQLite (Desktop): ``BEGIN IMMEDIATE`` holt die datenbankweite
      Schreibsperre sofort; ein zweiter Reorder wartet (``busy_timeout``)
      und liest danach den committeten Stand. pysqlite beginnt die
      Transaktion sonst erst beim ersten DML -- nach dem Lesen. Laeuft auf
      der Verbindung bereits eine Transaktion, bleibt sie unangetastet (der
      IntegrityError-Fallback im Router faengt den Restfall ab).
    * PostgreSQL: Zeilensperre per ``SELECT ... FOR UPDATE`` auf die Ziele
      des Mandats, gesetzt im Router-Query (``with_for_update``).
    """
    connection = db.connection()
    if connection.dialect.name != "sqlite":
        return
    raw = connection.connection.dbapi_connection
    if not raw.in_transaction:
        raw.execute("BEGIN IMMEDIATE")


# H-868-D1: PostgreSQL-SQLSTATEs eines Sperrkonflikts zwischen zwei
# Reorders (deadlock_detected, lock_not_available/lock_timeout,
# serialization_failure). Der Client laedt neu und sortiert erneut (409).
_GOAL_ORDER_LOCK_CONFLICT_SQLSTATES = frozenset({"40P01", "55P03", "40001"})


def is_goal_order_lock_conflict(exc: BaseException) -> bool:
    """True fuer einen Sperrkonflikt (PG-Deadlock/Lock-Timeout, SQLite
    "database is locked") beim Reorder."""
    orig = getattr(exc, "orig", exc)
    sqlstate = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    if sqlstate in _GOAL_ORDER_LOCK_CONFLICT_SQLSTATES:
        return True
    return "database is locked" in str(orig).lower()


def is_goal_rank_unique_violation(exc: BaseException) -> bool:
    """True fuer die Verletzung von ``ux_goals_rank_active`` (SQLite nennt
    die Spalten, PostgreSQL den Indexnamen)."""
    text = str(getattr(exc, "orig", exc))
    return "ux_goals_rank_active" in text or "goals.mandate_id, goals.rank" in text
