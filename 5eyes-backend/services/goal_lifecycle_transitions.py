"""Lifecycle-Transitionen schreiben (ADR-3a/3c).

Owner-Entscheide vom 2026-10-11:
* 3a -- Transitionen append-only auditiert (Actor, Zeitstempel, Grund).
* 3c -- kein Ziel wechselt in einen Terminal-Zustand ohne Begruendungstext,
  Zeitstempel und Actor. Pflichtfeld, nicht optional.

Zwei Schreibvorgaenge pro Transition, bewusst:

1. ``goal_lifecycle_transitions`` -- traegt den GRUND. Append-only: ein
   Eintrag wird nie veraendert und nie geloescht, eine Korrektur ist ein
   neuer Eintrag.
2. ``services/audit.py::log()`` -- die manipulationssichere Spur
   (hash-verkettet ueber ``sequence`` + ``previous_hash``). Sie hat kein
   Begruendungsfeld, deshalb braucht es beide: die eine Tabelle sagt
   WARUM, die andere beweist, dass der Eintrag nicht nachtraeglich
   veraendert wurde.

Beides laeuft in der TRANSAKTION DES AUFRUFERS. Diese Funktion committet
nicht -- sonst koennte eine Transition bestehen bleiben, waehrend die
Zustandsaenderung am Ziel zurueckgerollt wird, und das Protokoll wuerde
etwas behaupten, das nie passiert ist.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from database import new_uuid
from models.allocation import TargetAllocation
from models.wealth import Goal, GoalLifecycleTransition
from services import audit
from services.goal_lifecycle import (
    DECIDED_STATES,
    GoalLifecycleError,
    resolve_lifecycle_state,
)

#: ADR-3c gilt fuer die Terminal-Zustaende. ``accepted_as_due_now`` ist
#: zwar kein Terminal-Zustand (das Ziel traegt weiter eine
#: Verbindlichkeit), verlangt aber dieselbe Nachweispflicht -- es ist eine
#: Beraterentscheidung mit wirtschaftlicher Folge.
_MIN_REASON_CHARS = 3


def record_lifecycle_decision(
    db: Session,
    goal: Goal,
    *,
    to_state: str,
    reason: str,
    actor_user_id: str,
    actor_user_name: str,
    as_of: date | None = None,
    ip_address: str | None = None,
) -> GoalLifecycleTransition:
    """Setzt den Lifecycle-Entscheid und protokolliert ihn append-only.

    Wirft ``GoalLifecycleError``, wenn der Zielzustand kein
    Entscheidungs-Zustand ist oder die Begruendung fehlt -- fail-closed,
    weil ein Terminal-Zustand ohne Nachweis genau die Luecke ist, die
    ADR-3c schliesst.

    Gibt den geschriebenen Transitions-Eintrag zurueck, damit der Aufrufer
    ihn in seine Antwort aufnehmen kann, ohne erneut zu lesen.
    """
    state = str(to_state or "").strip()
    if state not in DECIDED_STATES:
        raise GoalLifecycleError(
            f"{state!r} ist kein Entscheidungs-Zustand. Zulaessig sind "
            f"{sorted(DECIDED_STATES)}. Die Zeit-Zustaende (planned, due, "
            "overdue) entstehen aus dem Zieldatum und werden nicht gesetzt."
        )

    cleaned_reason = str(reason or "").strip()
    if len(cleaned_reason) < _MIN_REASON_CHARS:
        raise GoalLifecycleError(
            f"Lifecycle-Wechsel nach '{state}' verlangt eine Begruendung "
            f"(mindestens {_MIN_REASON_CHARS} Zeichen). ADR-3c: kein "
            "Terminal-Zustand ohne Nachweis."
        )

    actor = str(actor_user_id or "").strip()
    if not actor:
        raise GoalLifecycleError(
            f"Lifecycle-Wechsel nach '{state}' verlangt einen Actor."
        )

    # Der Ausgangszustand wird VOR der Aenderung aufgeloest, damit das
    # Protokoll den tatsaechlichen Uebergang traegt und nicht zweimal den
    # Zielzustand.
    from_state = resolve_lifecycle_state(goal, as_of=as_of)
    created_at = (
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    )

    transition = GoalLifecycleTransition(
        id=new_uuid(),
        goal_id=str(goal.id),
        mandate_id=str(goal.mandate_id),
        client_id=str(goal.client_id),
        from_state=from_state,
        to_state=state,
        reason=cleaned_reason,
        actor_user_id=actor,
        created_at=created_at,
    )
    db.add(transition)

    goal.lifecycle_decision = state
    goal.updated_at = created_at

    # Hash-verkettete Spur. `field_name` benennt die Spalte, damit der
    # Eintrag im Audit-Log auffindbar ist; der Grund steht in der eigenen
    # Tabelle, weil audit_log kein solches Feld hat.
    audit.log(
        db,
        user_id=actor,
        user_name=str(actor_user_name or actor),
        table_name="goals",
        record_id=str(goal.id),
        action="lifecycle_decision",
        field_name="lifecycle_decision",
        old_value=from_state,
        new_value=state,
        mandate_id=str(goal.mandate_id),
        client_id=str(goal.client_id),
        ip_address=ip_address,
    )

    # Die Entscheidung aendert die Wirtschaftlichkeit des Ziels (erfuellt
    # oder storniert heisst Verbindlichkeit null), und damit die
    # Zielerreichung JEDES anderen Ziels im Mandat -- sie konkurrieren um
    # dieselbe Kapazitaet. Der persistierte Nachweis ist danach veraltet
    # und wird in DIESER Transaktion geleert.
    invalidate_goal_achievability_evidence(db, str(goal.mandate_id))

    return transition


def invalidate_goal_achievability_evidence(db: Session, mandate_id: str) -> int:
    """Loescht die persistierte Zielerreichungs-Evidenz dieses Mandats.

    GOAL-PAST-DATE-LIFECYCLE-001, Pflichtteil "atomare Invalidierung":
    ``TargetAllocation.goal_achievability_json`` haelt pro Ziel eine
    Wahrscheinlichkeit und einen Status, gerechnet gegen den Zielzustand
    ZUM ZEITPUNKT DES LAUFS. Aendert sich ein Ziel, ist dieser Nachweis
    veraltet -- und wurde bisher dem UI weiter ausgeliefert.

    Der ``input_snapshot_hash`` enthaelt das Zieldatum und erzeugte dadurch
    ein generisches Drift-Banner. Daneben stand die veraltete Zahl PRO ZIEL
    unveraendert. Ein Hinweis neben einer falschen Zahl ist kein Ersatz
    dafuer, die Zahl zu entfernen.

    Nur ``is_current = 1``: aeltere Versionen sind der Audit-Trail. Ihre
    Evidenz war zum Zeitpunkt ihres Laufs korrekt, und genau das soll sie
    bezeugen -- sie nachtraeglich zu leeren waere Geschichtsfaelschung.

    Kein Commit: laeuft in der Transaktion des Aufrufers, damit die
    Invalidierung nicht ohne die ausloesende Aenderung bestehen bleibt (und
    umgekehrt).

    Die Allokation selbst bleibt unangetastet -- Strategietreue, ADR-003:
    eine Ziel-Aenderung loest kein Rebalancing aus.
    """
    return int(
        db.query(TargetAllocation)
        .filter(
            TargetAllocation.mandate_id == str(mandate_id),
            TargetAllocation.is_current == 1,
            TargetAllocation.deleted_at.is_(None),
            TargetAllocation.goal_achievability_json.isnot(None),
        )
        .update(
            {TargetAllocation.goal_achievability_json: None},
            synchronize_session=False,
        )
        or 0
    )


def lifecycle_history(db: Session, goal_id: str) -> list[GoalLifecycleTransition]:
    """Alle Transitionen eines Ziels, aelteste zuerst.

    Append-only heisst: diese Liste waechst nur. Eine zurueckgenommene
    Entscheidung erscheint als ZWEITER Eintrag, nicht als Korrektur des
    ersten -- genau deshalb ist sie als Nachweis brauchbar.
    """
    return (
        db.query(GoalLifecycleTransition)
        .filter(GoalLifecycleTransition.goal_id == str(goal_id))
        .order_by(GoalLifecycleTransition.created_at.asc())
        .all()
    )
