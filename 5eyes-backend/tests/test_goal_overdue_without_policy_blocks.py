"""Red test fuer GOAL-PAST-DATE-LIFECYCLE-001 (Pflichttest 4, Kontrollrunde 38).

Siehe docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md,
Abschnitt "Finding GOAL-PAST-DATE-LIFECYCLE-001", Pflichttest 4:
"Overdue ohne Policy/Evidence blockiert statt Jahr eins zu erfinden."

Heutiger Stand (verifiziert gegen `models/wealth.py::Goal`, Stand develop d1fe2e8):
Das Goal-Schema besitzt `is_active`/`deleted_at`, aber KEIN Lifecycle-Feld
(kein `status` fuer planned/due/overdue/fulfilled/cancelled) und keinen
Outstanding-Betrag. `goal_to_liability()` (services/optimizer/goal_liabilities.py)
hat keinen `as_of`-Parameter und keine Moeglichkeit, eine Owner-Policy fuer ein
ueberfaelliges aktives Ziel entgegenzunehmen. `_resolve_target_year_index()`
wendet unbedingt `max(1, calendar_years_until(anchor))` an -- ein vergangenes
Zieldatum wird so IMMER zu Jahr eins geklemmt, ohne jede Unterscheidung
zwischen "historisch erfuellt", "ueberfaellig und offen" oder "heute faellig".

Dieser Test dokumentiert den fehlenden Blocker: ein aktives Einmalziel mit
Zieldatum 2020-01-01 (weit in der Vergangenheit, kein Lifecycle-Entscheid
vorhanden) darf laut Reparaturvertrag NICHT kommentarlos als normale
Jahr-eins-Zahlung materialisiert werden. Es muss entweder blockieren (Exception)
oder die Liability muss einen expliziten "ueberfaellig/ungeklaert"-Hinweis
tragen (z.B. via `evaluation_note`). Aktuell tut es keines von beidem.
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
from database import Base  # noqa: E402
from models import (  # noqa: F401,E402
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
configure_mappers()

from services.optimizer.goal_liabilities import goal_to_liability  # noqa: E402


def _make_overdue_one_off_goal() -> SimpleNamespace:
    """Aktives Einmalziel, dessen Zieldatum weit in der Vergangenheit liegt.

    Es gibt im Schema kein Feld, um hier eine Lifecycle-Entscheidung
    (erfuellt/storniert/ueberfaellig-mit-Policy) zu hinterlegen -- das ist
    genau die Luecke, die dieser Test aufzeigt.
    """
    return SimpleNamespace(
        id="overdue-one-off-1",
        label="Ueberfaellige Einmalausgabe (2020)",
        goal_type="Einmalige_Ausgabe",
        target_amount_rappen=50_000_00,
        target_wealth_rappen=None,
        target_return_bps=None,
        horizon_years=10,
        target_date="2020-01-01",
        start_date=None,
        is_ongoing=0,
        frequency=None,
        hardness="Primaer",
        rank=1,
        weight_bps=None,
        value_mode="nominal",
        goal_scope="Beratungsvermoegen",
        pension_pillar=None,
        is_active=1,
        deleted_at=None,
    )


def test_goal_schema_carries_exactly_the_lifecycle_decision_column():
    """Das Goal-Schema traegt GENAU ein Lifecycle-Feld: die Entscheidung.

    Dieser Test hiess ``test_goal_schema_has_no_lifecycle_field_today`` und
    hielt die Schema-Luecke fest ("kein Status, kein Outstanding-Betrag").
    Er sagte in seinem eigenen Docstring, dass sein Fallen das Signal ist --
    genau das ist am 2026-10-12 mit ADR-3 Etappe 2 eingetreten.

    Umgeschrieben statt geloescht, und zwar auf die ENGERE Aussage: es darf
    nur die ENTSCHEIDUNG persistiert sein, nicht der Zustand.

    `planned -> due -> overdue` passiert durch Zeitablauf, hat also keinen
    Actor und keinen Grund -- die beiden Pflichtfelder von ADR-3a/3c. Ein
    gespeichertes `lifecycle_status` oder `lifecycle_state` waere eine
    Dublette, die still veraltet und einen Nachtjob braeuchte. Taucht so ein
    Feld hier auf, ist die Trennung aufgeweicht worden.
    """
    from models.wealth import Goal

    column_names = {c.name for c in Goal.__table__.columns}
    lifecycle_like = {
        name
        for name in column_names
        if "status" in name or "lifecycle" in name or "outstanding" in name
    }
    assert lifecycle_like == {"lifecycle_decision"}, (
        "Erwartet genau {'lifecycle_decision'} -- nur die Beraterentscheidung "
        f"wird persistiert. Gefunden: {lifecycle_like}. Ein zusaetzliches "
        "lifecycle_status/-state-Feld waere eine Dublette zum abgeleiteten "
        "Zeit-Zustand (services/goal_lifecycle.py) und koennte veralten."
    )


def test_lifecycle_transition_table_is_append_only_by_schema():
    """ADR-3a/3c: das Protokoll traegt Actor, Zeitstempel und Grund -- und
    hat bewusst KEIN updated_at und KEIN deleted_at.

    Ein veraenderbarer oder loeschbarer Eintrag waere als Nachweis
    wertlos. Eine Korrektur ist ein neuer Eintrag, nicht eine Aenderung des
    alten.
    """
    from models.wealth import GoalLifecycleTransition

    columns = {c.name: c for c in GoalLifecycleTransition.__table__.columns}

    for required in ("actor_user_id", "reason", "created_at", "to_state"):
        assert required in columns, required
        assert columns[required].nullable is False, (
            f"{required} muss NOT NULL sein -- ADR-3c macht den Nachweis zur "
            "Pflicht, nicht zur Option."
        )

    # from_state darf NULL sein: die erste Transition eines Ziels hat keinen
    # persistierten Vorzustand (der war abgeleitet).
    assert columns["from_state"].nullable is True

    for forbidden in ("updated_at", "deleted_at"):
        assert forbidden not in columns, (
            f"{forbidden} darf es nicht geben -- das Protokoll ist "
            "append-only. Eine Korrektur ist ein neuer Eintrag."
        )


def test_overdue_one_off_goal_without_policy_blocks_or_is_marked():
    """Ein ueberfaelliges aktives Ziel ohne Owner-Policy darf nicht als
    stille, normale Jahr-eins-Zahlung erscheinen.

    Erwartet (Soll-Vertrag): entweder
      (a) `goal_to_liability()` lehnt die Verarbeitung ab (Exception), weil
          keine Lifecycle-Entscheidung vorliegt, ODER
      (b) die resultierende `GoalLiability` traegt einen expliziten
          ueberfaelligen/ungeklaerten `evaluation_note`-Hinweis.

    ERFUELLT seit 2026-10-11 ueber Variante (b): das Ziel traegt einen
    expliziten UEBERFAELLIG-Hinweis mit Datum und dem Verweis auf den
    fehlenden Lifecycle-Status.

    **ADR-3 ist damit NICHT abgeschlossen.** Der Owner hat am 2026-10-11
    ausdruecklich Variante 3 gewaehlt -- fail-closed, die Berechnung wird
    blockiert, bis der Berater entscheidet. Ein Hinweistext ist kein
    Zustand: es gibt weiterhin keine Lifecycle-Spalte, kein
    append-only auditiertes Transitionsprotokoll und kein blockierendes
    Gate. Dieser Test prueft nur die Untergrenze "nicht stillschweigend",
    weil er beide Varianten als Erfolg akzeptiert.

    Der Hinweis entstand als Notbremse fuer einen anderen Fehler: mit der
    Umstellung auf Kalenderjahr-Buckets (ADR-2) lieferte ein 2020er Ziel
    bei Basisjahr 2026 den Index -5, und ``wealth_paths[:, -5]`` loest bei
    Horizont 10 auf Spalte 6 auf -- das ueberfaellige Ziel waere im Jahr 6
    bewertet worden. Siehe
    tests/test_goal_liability_target_year_index_never_wraps.py.

    Vorheriges (falsches) Verhalten: `goal_to_liability()` warf nichts und
    `evaluation_note` blieb `None` -- das 2020er Ziel wurde kommentarlos als
    normale Outflow-Zahlung in Jahr 1 des Horizonts materialisiert.
    """
    goal = _make_overdue_one_off_goal()
    as_of_today = date(2026, 10, 3)

    blocked = False
    liab = None
    try:
        liab = goal_to_liability(goal, horizon_years=10)
    except Exception:  # noqa: BLE001 - jede Exception gilt als "blockiert"
        blocked = True

    if blocked:
        return

    assert liab is not None
    overdue_marked = bool(liab.evaluation_note) and any(
        kw in (liab.evaluation_note or "").lower()
        for kw in ("ueberf", "overdue", "vergangen", "past", "ungeklaert", "unknown")
    )
    assert overdue_marked, (
        "Ueberfaelliges 2020er Ziel ohne Owner-Policy wurde weder blockiert "
        "noch als ueberfaellig/ungeklaert markiert. target_year_index="
        f"{liab.target_year_index}, liability_path_rappen="
        f"{liab.liability_path_rappen}, evaluation_note={liab.evaluation_note!r}. "
        f"(as_of Referenz fuer diesen Audit-Repro: {as_of_today.isoformat()}, "
        "aber goal_to_liability() nimmt gar keinen as_of-Parameter entgegen.)"
    )
