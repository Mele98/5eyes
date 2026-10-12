"""Typisierter Goal-Lifecycle (ADR-3).

Owner-Entscheide vom 2026-10-11:
* 3a -- mindestens ``planned | due | overdue | fulfilled | cancelled |
  historical_unknown``, Transitionen append-only auditiert (Actor,
  Zeitstempel, Grund).
* 3b -- **Variante 3**: fail-closed. Ein ueberfaelliges Ziel ohne
  dokumentierte Entscheidung blockiert die Berechnung, bis der Berater
  klaert. Zulaessige Aufloesungen sind genau zwei: sofortiger t0-Bedarf
  (Variante 1) oder neu verhandeltes Faelligkeitsdatum (Variante 2).
* 3c -- kein Terminal-Zustand ohne Begruendungstext, Zeitstempel und Actor.

Befund, den das schliesst (GOAL-PAST-DATE-LIFECYCLE-001, Audit Repro 3):
die Goal-Domain kannte nur ``is_active`` und ``deleted_at``. Ein 2020
abgelaufener dreijaehriger Zahlungsstrom wurde 2026 als drei NEUE Jahre
Zahlungspflicht wiederbelebt, weil ``max(1, calendar_years_until(...))``
jedes vergangene Datum stillschweigend auf "Jahr 1 ab jetzt" hob.

Gespeichert vs. abgeleitet -- eine Entscheidung, die die Spec offen laesst
=========================================================================
ADR-3a listet sechs Zustaende und verlangt, dass jede Transition einen
Actor, einen Zeitstempel und einen Grund traegt. Aber
``planned -> due -> overdue`` passiert durch ZEITABLAUF: dort gibt es
keinen Actor und keinen Grund, also genau die beiden Pflichtfelder nicht.
Ein gespeichertes ``planned`` veraltet zudem still und braeuchte einen
Nachtjob, der es nachzieht.

Deshalb wird getrennt:

* GESPEICHERT werden nur ENTSCHEIDUNGEN -- ``fulfilled``, ``cancelled``,
  ``accepted_as_due_now``, ``historical_unknown``. Jede hat einen Actor und
  einen Grund, jede ist auditierbar.
* ABGELEITET werden die ZEIT-Zustaende -- ``planned``, ``due``, ``overdue``
  -- aus dem Zieldatum gegen den Bewertungsstichtag. Sie koennen nicht
  veralten, weil sie bei jedem Lesen neu entstehen.

Die beiden zulaessigen Aufloesungen aus 3b fallen sauber hinein:
Variante 1 wird als ``accepted_as_due_now`` gespeichert; Variante 2
braucht gar keinen eigenen Zustand -- der Berater setzt ein neues
``target_date``, und der abgeleitete Zustand wird dadurch von selbst
wieder ``planned``.

``is_active`` wird NICHT als ``cancelled`` gelesen
==================================================
``is_active=0`` ist der heute einzige Proxy fuer "vom Berater
ausgeschlossen", sagt aber nicht, OB erfuellt oder storniert. Diese
Unterscheidung zu erfinden waere eine Behauptung ueber einen
Kundensachverhalt, den niemand erfasst hat. Der Zustand heisst deshalb
``inactive``: wirtschaftlich null (wie ein Terminal-Zustand), aber ohne
Aussage darueber, warum. Erst Etappe 2 gibt dem Berater die Mittel, das zu
typisieren.
"""
from __future__ import annotations

from datetime import date

# ---------------------------------------------------------------------------
# Zustaende
# ---------------------------------------------------------------------------

#: Zieldatum liegt in der Zukunft -- der Normalfall.
PLANNED = "planned"
#: Zieldatum ist heute.
DUE = "due"
#: Zieldatum liegt in der Vergangenheit und es gibt keine Entscheidung.
OVERDUE = "overdue"
#: Berater hat bestaetigt, dass das Ziel erfuellt ist (Terminal, 3c).
FULFILLED = "fulfilled"
#: Berater hat das Ziel storniert (Terminal, 3c).
CANCELLED = "cancelled"
#: ADR-3b Variante 1: faelliger Betrag wird als t0-Bedarf uebernommen.
ACCEPTED_AS_DUE_NOW = "accepted_as_due_now"
#: Legacy-Zeile ohne eindeutigen Anker. Nur fuer die Migration, nie fuer
#: neue Ziele -- und wirtschaftlich null, statt interpretiert zu werden.
HISTORICAL_UNKNOWN = "historical_unknown"
#: ``is_active=0``/``is_included=0``: ausgeschlossen, Grund nicht erfasst.
INACTIVE = "inactive"

#: Zustaende, die ein Berater setzt. Nur diese werden persistiert.
DECIDED_STATES = frozenset({
    FULFILLED,
    CANCELLED,
    ACCEPTED_AS_DUE_NOW,
    HISTORICAL_UNKNOWN,
})

#: Zustaende, die aus dem Zieldatum entstehen.
DERIVED_TIME_STATES = frozenset({PLANNED, DUE, OVERDUE})

#: Zustaende, bei denen der Zahlungsplan NICHT mehr gilt -- unabhaengig
#: davon, was der Enumerator rechnen wuerde.
ECONOMICALLY_NULL_STATES = frozenset({
    FULFILLED,
    CANCELLED,
    HISTORICAL_UNKNOWN,
    INACTIVE,
})

#: Zustaende, die eine Beraterentscheidung brauchen, bevor gerechnet werden
#: darf (ADR-3b Variante 3, fail-closed).
REQUIRES_RESOLUTION_STATES = frozenset({OVERDUE})

ALL_STATES = frozenset(
    DERIVED_TIME_STATES | DECIDED_STATES | {INACTIVE}
)


class GoalLifecycleError(ValueError):
    """Ein Lifecycle-Zustand ist ungueltig oder nicht aufloesbar."""


# ---------------------------------------------------------------------------
# Auflösung
# ---------------------------------------------------------------------------


def _parse_iso(value) -> date | None:
    raw = str(value or "").strip()[:10]
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _stored_decision(goal) -> str | None:
    """Liest den persistierten Entscheidungs-Zustand, falls vorhanden.

    Die Spalte kommt erst mit Etappe 2 (Alembic). Bis dahin liefert diese
    Funktion ``None`` und alle Zustaende sind abgeleitet -- die Aufloesung
    funktioniert also schon vor der Migration, ohne Sonderfall beim
    Aufrufer.
    """
    raw = getattr(goal, "lifecycle_decision", None)
    if raw is None:
        return None
    value = str(raw).strip()
    if not value:
        return None
    if value not in DECIDED_STATES:
        raise GoalLifecycleError(
            f"Unbekannter persistierter Lifecycle-Zustand {value!r}; "
            f"zulaessig sind {sorted(DECIDED_STATES)}."
        )
    return value


def _lifecycle_anchor(goal) -> date | None:
    """Das Datum, an dem der Lifecycle dieses Ziels haengt.

    Fuer wiederkehrende Stroeme ist das ENDE maßgeblich, nicht der Beginn:
    ein Strom, der laeuft, ist nicht ueberfaellig, auch wenn er in der
    Vergangenheit begonnen hat. Fuer alle anderen Zieltypen ist es das
    Zieldatum.
    """
    goal_type = str(getattr(goal, "goal_type", "") or "").strip()
    target_date = _parse_iso(getattr(goal, "target_date", None))
    if goal_type in ("Wiederkehrende_Ausgabe", "Pensionsausgabe"):
        if bool(int(getattr(goal, "is_ongoing", 0) or 0)) and target_date is None:
            # Laufender Strom ohne Ende: per Definition nie ueberfaellig.
            return None
        return target_date
    return target_date


def resolve_lifecycle_state(goal, *, as_of: date | None = None) -> str:
    """Der Lifecycle-Zustand dieses Ziels.

    ``as_of`` ist der Bewertungsstichtag. Default ist ``date.today()`` --
    ADR-1b wird den persistierten Stichtag durchreichen, ohne dass sich
    diese Signatur noch aendern muss.

    Reihenfolge (die erste zutreffende Regel gewinnt):

    1. persistierte Entscheidung (Berater hat geklaert)
    2. ``is_active=0`` oder ``is_included=0`` -> ``inactive``
    3. Zieldatum gegen ``as_of`` -> ``overdue`` / ``due`` / ``planned``
    4. kein Lifecycle-Anker -> ``planned``

    Dass die Entscheidung VOR dem Datum geprueft wird, ist der Kern: ein
    erfuelltes Ziel bleibt erfuellt, auch wenn sein Datum vergangen ist.
    """
    decision = _stored_decision(goal)
    if decision is not None:
        return decision

    is_active = int(getattr(goal, "is_active", 1) or 0)
    is_included = getattr(goal, "is_included", 1)
    is_included = 1 if is_included is None else int(is_included or 0)
    if not is_active or not is_included:
        return INACTIVE

    anchor = _lifecycle_anchor(goal)
    if anchor is None:
        return PLANNED

    valuation_date = as_of or date.today()
    if anchor < valuation_date:
        return OVERDUE
    if anchor == valuation_date:
        return DUE
    return PLANNED


def is_economically_null(state: str) -> bool:
    """Traegt dieses Ziel keinerlei Verbindlichkeit mehr?

    Pflichttest 5 von GOAL-PAST-DATE-LIFECYCLE-001: ein erfuelltes oder
    storniertes Ziel bleibt sichtbar und abfragbar, muss aber NULL zur
    Optimizer-Liability beitragen. Entscheidend ist, dass
    ``goal_to_liability()`` das SELBST durchsetzt: die einzige bisherige
    Absicherung lag ausserhalb des Moduls
    (``portfolio_engine._strictly_active_rows()``), ein direkter Aufruf
    rechnete fuer ein storniertes Ziel die volle Verbindlichkeit.
    """
    return state in ECONOMICALLY_NULL_STATES


def requires_advisor_resolution(state: str) -> bool:
    """Blockiert dieser Zustand die Berechnung (ADR-3b Variante 3)?"""
    return state in REQUIRES_RESOLUTION_STATES

def assert_no_unresolved_overdue_goals(goals, *, as_of: date | None = None) -> None:
    """Fail-closed Gate: ueberfaellige Ziele blockieren die Berechnung.

    ADR-3b, **Variante 3** (Owner-Entscheid 2026-10-11). Von den drei
    vorgelegten Optionen ist das die gewaehlte; Variante 1 (sofortiger
    t0-Bedarf) und Variante 2 (neu verhandeltes Datum) sind die beiden
    einzigen zulaessigen Aufloesungen, und beide muessen vom Berater
    AUSDRUECKLICH gesetzt werden.

    Warum blockieren und nicht weiterrechnen: die abgeloeste Stille machte
    aus einer 2020-2022 abgelaufenen Verpflichtung drei NEUE Jahre
    2026-2028. Das ist keine konservative Schaetzung, sondern eine
    erfundene Tatsache. Eine Eignungspruefung auf dieser Grundlage
    exponiert den Berater (Sorgfaltspflicht, Art. 398 OR) und die Firma
    gegenueber einem Kunden, der sich auf eine falsche Liquiditaetsplanung
    verlaesst. Das Projekt hat dieses Prinzip mehrfach selbst angewandt
    (Fail-open -> fail-closed, Backend-Complete-State-Guard mit HTTP 422);
    Variante 3 setzt denselben Haus-Standard fort.

    Die Kosten sind echt und bewusst in Kauf genommen: der Berater muss
    klaeren, bevor fuer dieses Mandat ueberhaupt gerechnet wird.

    Wirft ``GoalLifecycleError`` mit allen betroffenen Zielen auf einmal --
    nicht beim ersten Treffer abbrechen, sonst arbeitet sich der Berater
    durch eine Fehlermeldung pro Ziel.
    """
    blocked: list[str] = []
    for goal in goals or []:
        state = resolve_lifecycle_state(goal, as_of=as_of)
        if not requires_advisor_resolution(state):
            continue
        label = str(getattr(goal, "label", "") or "Ziel").strip() or "Ziel"
        anchor = _lifecycle_anchor(goal)
        blocked.append(
            f"'{label}' (faellig {anchor.isoformat() if anchor else 'unbekannt'})"
        )

    if not blocked:
        return

    raise GoalLifecycleError(
        "Berechnung blockiert: "
        + str(len(blocked))
        + (" ueberfaelliges Ziel" if len(blocked) == 1 else " ueberfaellige Ziele")
        + " ohne dokumentierte Entscheidung -- "
        + ", ".join(blocked)
        + ". Bitte pro Ziel entscheiden: Betrag als sofortigen Bedarf "
        "uebernehmen, neues Faelligkeitsdatum vereinbaren, oder das Ziel "
        "als erfuellt bzw. storniert abschliessen."
    )
