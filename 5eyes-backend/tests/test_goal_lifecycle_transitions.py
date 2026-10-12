"""ADR-3 Etappe 2: Entscheidungs-Persistenz + append-only Protokoll.

GOAL-PAST-DATE-LIFECYCLE-001. Owner-Entscheide 3a (append-only auditiert:
Actor, Zeitstempel, Grund) und 3c (kein Terminal-Zustand ohne Nachweis).

Geprueft wird gegen eine echte SQLite-Session, weil die Aussage an der
Persistenz haengt: zwei Schreibvorgaenge (eigene Tabelle fuer den GRUND,
hash-verketteter audit_log als Nachweis der Unveraendertheit) in DERSELBEN
Transaktion wie die Zustandsaenderung am Ziel.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.orm import configure_mappers
from database import Base, new_uuid
# Wie in den Geschwister-Tests: `main` laedt den VOLLEN Modellgraphen, den
# metadata.create_all() braucht. Eine Teilmenge reicht nicht --
# product_eligibility hat einen Fremdschluessel auf `tenants`.
from main import app  # noqa: F401
configure_mappers()

from models.clients import Client
from models.mandates import Mandate
from models.users import User
from models.wealth import Goal, GoalLifecycleTransition
from services.goal_lifecycle import (
    ACCEPTED_AS_DUE_NOW,
    CANCELLED,
    FULFILLED,
    OVERDUE,
    PLANNED,
    GoalLifecycleError,
    is_economically_null,
    resolve_lifecycle_state,
)
from services.goal_lifecycle_transitions import (
    lifecycle_history,
    record_lifecycle_decision,
)
from services.optimizer.goal_liabilities import goal_to_liability

AS_OF = date(2026, 10, 12)
NOW = "2026-10-12T00:00:00.000Z"


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path/'lifecycle.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    yield sessionmaker(
        autocommit=False, autoflush=False, expire_on_commit=False, bind=engine
    )
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def _seed(session_factory, *, target_date: str):
    """Ein Mandat mit einem Ausgabenziel und einem Berater.

    Pflichtfelder uebernommen aus dem etablierten Seed-Muster in
    tests/test_optimizer_phase6.py -- username, client_number und
    mandate_number sind NOT NULL.
    """
    with session_factory() as s:
        advisor_id, cid, mid, gid = (new_uuid() for _ in range(4))
        s.add(User(
            id=advisor_id, username="adv-adr3", password_hash="h",
            full_name="Beraterin", role="advisor", is_active=1,
            created_at=NOW, updated_at=NOW,
        ))
        s.add(Client(
            id=cid, client_number=f"C-{cid[:6]}", first_name="A",
            last_name="B", advisor_id=advisor_id,
            created_at=NOW, updated_at=NOW,
        ))
        s.add(Mandate(
            id=mid, client_id=cid, mandate_number=f"M-{mid[:6]}",
            mandate_type="Anlageberatung", opened_at=NOW,
            created_at=NOW, updated_at=NOW,
        ))
        s.add(Goal(
            id=gid, mandate_id=mid, client_id=cid,
            goal_family="Cashflow", goal_type="Einmalige_Ausgabe",
            label="Altlast", rank=1, goal_scope="Beratungsvermoegen",
            value_mode="nominal", target_amount_rappen=100_000_00,
            target_date=target_date, is_ongoing=0, hardness="Primaer",
            is_active=1, is_included=1, created_at=NOW, updated_at=NOW,
        ))
        s.commit()
        return advisor_id, gid


# ---------------------------------------------------------------------------
# ADR-3c: fail-closed ohne Nachweis
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_reason", ["", "   ", None, "ab"])
def test_terminal_state_without_a_reason_is_rejected(session_factory, bad_reason):
    """Kein Terminal-Zustand ohne Begruendung -- das ist ADR-3c.

    Eine leere Begruendung durchzulassen waere genau die Luecke: ein Ziel
    waere als erfuellt markiert, ohne dass jemand sagen muss, warum.
    """
    advisor_id, goal_id = _seed(session_factory, target_date="2020-01-01")
    with session_factory() as s:
        goal = s.get(Goal, goal_id)
        with pytest.raises(GoalLifecycleError, match="Begruendung"):
            record_lifecycle_decision(
                s, goal, to_state=FULFILLED, reason=bad_reason,
                actor_user_id=advisor_id, actor_user_name="Beraterin",
                as_of=AS_OF,
            )


def test_decision_without_an_actor_is_rejected(session_factory):
    advisor_id, goal_id = _seed(session_factory, target_date="2020-01-01")
    with session_factory() as s:
        goal = s.get(Goal, goal_id)
        with pytest.raises(GoalLifecycleError, match="Actor"):
            record_lifecycle_decision(
                s, goal, to_state=CANCELLED, reason="Kunde hat verzichtet",
                actor_user_id="", actor_user_name="Beraterin", as_of=AS_OF,
            )


@pytest.mark.parametrize("time_state", [PLANNED, "due", OVERDUE])
def test_time_states_cannot_be_set_as_a_decision(session_factory, time_state):
    """Zeit-Zustaende entstehen aus dem Datum und werden nie gesetzt.

    Sie speicherbar zu machen waere die Dublette, die veralten kann -- der
    Grund, warum gespeicherte und abgeleitete Zustaende getrennt sind.
    """
    advisor_id, goal_id = _seed(session_factory, target_date="2031-01-01")
    with session_factory() as s:
        goal = s.get(Goal, goal_id)
        with pytest.raises(GoalLifecycleError, match="kein Entscheidungs-Zustand"):
            record_lifecycle_decision(
                s, goal, to_state=time_state, reason="egal",
                actor_user_id=advisor_id, actor_user_name="Beraterin",
                as_of=AS_OF,
            )


# ---------------------------------------------------------------------------
# Der Normalfall: Entscheidung setzen und protokollieren
# ---------------------------------------------------------------------------


def test_fulfilling_an_overdue_goal_records_the_transition(session_factory):
    advisor_id, goal_id = _seed(session_factory, target_date="2020-01-01")

    with session_factory() as s:
        goal = s.get(Goal, goal_id)
        assert resolve_lifecycle_state(goal, as_of=AS_OF) == OVERDUE

        record_lifecycle_decision(
            s, goal, to_state=FULFILLED,
            reason="Kunde hat das Eigenheim 2021 ohne Portfoliomittel gekauft.",
            actor_user_id=advisor_id, actor_user_name="Beraterin", as_of=AS_OF,
        )
        s.commit()

    with session_factory() as s:
        goal = s.get(Goal, goal_id)
        assert goal.lifecycle_decision == FULFILLED
        assert resolve_lifecycle_state(goal, as_of=AS_OF) == FULFILLED

        history = lifecycle_history(s, goal_id)
        assert len(history) == 1
        t = history[0]
        # Der tatsaechliche Uebergang, nicht zweimal der Zielzustand.
        assert t.from_state == OVERDUE
        assert t.to_state == FULFILLED
        assert "Eigenheim" in t.reason
        assert t.actor_user_id == advisor_id
        assert t.created_at.endswith("Z")
        assert t.mandate_id == goal.mandate_id
        assert t.client_id == goal.client_id


def test_transition_also_writes_the_hash_chained_audit_entry(session_factory):
    """Zwei Schreibvorgaenge: eigene Tabelle fuer den Grund, audit_log als
    Nachweis der Unveraendertheit. audit_log hat kein Begruendungsfeld --
    deshalb braucht es beide."""
    from models.review import AuditLog

    advisor_id, goal_id = _seed(session_factory, target_date="2020-01-01")
    with session_factory() as s:
        goal = s.get(Goal, goal_id)
        record_lifecycle_decision(
            s, goal, to_state=CANCELLED, reason="Ziel entfaellt, Scheidung.",
            actor_user_id=advisor_id, actor_user_name="Beraterin", as_of=AS_OF,
        )
        s.commit()

    with session_factory() as s:
        entries = (
            s.query(AuditLog)
            .filter(AuditLog.record_id == goal_id, AuditLog.action == "lifecycle_decision")
            .all()
        )
        assert len(entries) == 1
        e = entries[0]
        assert e.table_name == "goals"
        assert e.field_name == "lifecycle_decision"
        assert e.old_value == OVERDUE
        assert e.new_value == CANCELLED
        # Hash-Verkettung: der Eintrag traegt Sequenz und Vorgaenger-Hash.
        assert getattr(e, "sequence", None) is not None


def test_history_is_append_only_a_reversal_is_a_second_entry(session_factory):
    """Eine zurueckgenommene Entscheidung korrigiert nicht den ersten
    Eintrag, sie erzeugt einen zweiten. Genau deshalb ist das Protokoll als
    Nachweis brauchbar."""
    advisor_id, goal_id = _seed(session_factory, target_date="2020-01-01")

    with session_factory() as s:
        goal = s.get(Goal, goal_id)
        record_lifecycle_decision(
            s, goal, to_state=CANCELLED, reason="Erste Einschaetzung: entfaellt.",
            actor_user_id=advisor_id, actor_user_name="Beraterin", as_of=AS_OF,
        )
        s.commit()

    with session_factory() as s:
        goal = s.get(Goal, goal_id)
        record_lifecycle_decision(
            s, goal, to_state=ACCEPTED_AS_DUE_NOW,
            reason="Rueckfrage beim Kunden: Betrag wird doch benoetigt.",
            actor_user_id=advisor_id, actor_user_name="Beraterin", as_of=AS_OF,
        )
        s.commit()

    with session_factory() as s:
        history = lifecycle_history(s, goal_id)
        assert len(history) == 2
        assert [t.to_state for t in history] == [CANCELLED, ACCEPTED_AS_DUE_NOW]
        # Der zweite Eintrag kennt seinen Ausgangszustand.
        assert history[1].from_state == CANCELLED
        # Und die erste Begruendung ist unveraendert erhalten.
        assert "Erste Einschaetzung" in history[0].reason


def test_nothing_is_written_when_the_caller_rolls_back(session_factory):
    """Die Funktion committet nicht. Sonst koennte ein Protokolleintrag
    bestehen bleiben, waehrend die Zustandsaenderung zurueckgerollt wird --
    das Protokoll wuerde etwas behaupten, das nie passiert ist."""
    advisor_id, goal_id = _seed(session_factory, target_date="2020-01-01")

    with session_factory() as s:
        goal = s.get(Goal, goal_id)
        record_lifecycle_decision(
            s, goal, to_state=FULFILLED, reason="Versehen, wird zurueckgerollt.",
            actor_user_id=advisor_id, actor_user_name="Beraterin", as_of=AS_OF,
        )
        s.rollback()

    with session_factory() as s:
        assert s.get(Goal, goal_id).lifecycle_decision is None
        assert lifecycle_history(s, goal_id) == []
        assert s.query(GoalLifecycleTransition).count() == 0


# ---------------------------------------------------------------------------
# Wirtschaftliche Folge der Entscheidung
# ---------------------------------------------------------------------------


def test_fulfilled_goal_stops_contributing_to_the_liability(session_factory):
    """Pflichttest 5: sichtbar bleiben, wirtschaftlich null werden."""
    advisor_id, goal_id = _seed(
        session_factory,
        target_date=(AS_OF + timedelta(days=365 * 4)).isoformat(),
    )

    with session_factory() as s:
        goal = s.get(Goal, goal_id)
        before = goal_to_liability(goal, horizon_years=10, as_of=AS_OF)
        assert sum(before.liability_path_rappen) == 100_000_00
        assert before.lifecycle_status == PLANNED

        record_lifecycle_decision(
            s, goal, to_state=FULFILLED, reason="Aus Erbschaft bezahlt.",
            actor_user_id=advisor_id, actor_user_name="Beraterin", as_of=AS_OF,
        )
        s.commit()

    with session_factory() as s:
        goal = s.get(Goal, goal_id)
        after = goal_to_liability(goal, horizon_years=10, as_of=AS_OF)

        assert after.lifecycle_status == FULFILLED
        assert is_economically_null(after.lifecycle_status)
        assert sum(after.liability_path_rappen) == 0
        assert after.target_amount_rappen == 0
        # Sichtbar, nicht geloescht.
        assert goal.deleted_at is None
        assert s.get(Goal, goal_id) is not None
        assert "keine Verbindlichkeit" in (after.evaluation_note or "")


def test_accepted_as_due_now_keeps_the_liability(session_factory):
    """ADR-3b Variante 1: geklaert, aber nicht erledigt.

    Der Betrag wird als sofortiger Bedarf uebernommen -- das Ziel traegt
    weiter eine Verbindlichkeit. Es auf null zu setzen waere die stille
    Variante in die andere Richtung.
    """
    advisor_id, goal_id = _seed(session_factory, target_date="2020-01-01")

    with session_factory() as s:
        goal = s.get(Goal, goal_id)
        record_lifecycle_decision(
            s, goal, to_state=ACCEPTED_AS_DUE_NOW,
            reason="Betrag ist weiterhin offen, wird jetzt faellig.",
            actor_user_id=advisor_id, actor_user_name="Beraterin", as_of=AS_OF,
        )
        s.commit()

    with session_factory() as s:
        goal = s.get(Goal, goal_id)
        liab = goal_to_liability(goal, horizon_years=10, as_of=AS_OF)
        assert liab.lifecycle_status == ACCEPTED_AS_DUE_NOW
        assert is_economically_null(liab.lifecycle_status) is False
