"""COST-FINALIZATION-001: Finalisierung verlangt belegte Konflikt-Offenlegung.

CERT-COST-CONFLICT-001. Befund:
`_validate_recommendation_for_finalization()` prueft Risikoprofil,
Soll-Allokation und Policy -- aber nie den Nachweiszustand der
Interessenkonflikte. Ein Mandat mit einer nie offengelegten Retrozession
liess sich zertifizieren, und das FIDLEG-Dokument ging mit genau dem
Konflikt an den Kunden, dessen Offenlegung Art. 25/26 verlangt.

Das Gate kam BEWUSST erst zusammen mit den Aufloesungs-Endpunkten. Vorher
konnten die Flags nur 0/0 sein -- es haette jedes Mandat mit einer einzigen
Konfliktzeile blockiert, ohne dass ein Berater sie aufloesen KANN.
Fail-closed waere nicht sicher gewesen, sondern funktionsunfaehig.

Dieses Modul prueft deshalb beide Richtungen gleich gewichtet: dass das Gate
greift, UND dass es den Normalbetrieb nicht lahmlegt.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from database import new_uuid  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from models.review import ConflictOfInterestDisclosure, RecommendationRun  # noqa: E402
from models.users import User  # noqa: E402
from routers.review import (  # noqa: E402
    _validate_recommendation_for_finalization, finalize_recommendation,
)

from test_finalize_mandate_lock import (  # noqa: E402,F401
    _FakeRequest, _add_full_position, _allocation_policy_and_cma,
    _current_allocation_id, _make_run as _make_finalize_run,
)
from test_optimizer_shadow_mode import (  # noqa: E402,F401
    _seed_realistic_mandate, session_factory,
)


def _now() -> str:
    import datetime

    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


def _ready_run(session_factory, *, suffix: str):
    advisor_id, _client_id, mandate_id, assessment_id, _goal_id = (
        _seed_realistic_mandate(session_factory, suffix=suffix)
    )
    allocation_id = _current_allocation_id(session_factory, mandate_id, advisor_id)
    policy, cma = _allocation_policy_and_cma(session_factory, allocation_id)
    run_id = _make_finalize_run(
        session_factory, mandate_id, allocation_id, assessment_id,
        advisor_id, policy, cma,
    )
    _add_full_position(session_factory, run_id)
    return advisor_id, mandate_id, run_id


def _add_conflict(session_factory, mandate_id, advisor_id, **fields):
    defaults = dict(
        conflict_type="Retrozession / Inducement",
        description="Vertriebsentschaedigung",
        inducement_provider="Fund Provider AG",
        inducement_amount_rappen=50_000_00,
        inducement_frequency="jährlich",
        disclosed_to_client=0,
        client_acknowledged=0,
        reimbursed_to_client=0,
        disclosed_by=advisor_id,
    )
    defaults.update(fields)
    conflict_id = new_uuid()
    with session_factory() as db:
        db.add(ConflictOfInterestDisclosure(
            id=conflict_id, mandate_id=mandate_id,
            created_at=_now(), updated_at=_now(), **defaults,
        ))
        db.commit()
    return conflict_id


def _errors(session_factory, mandate_id, run_id) -> list[str]:
    with session_factory() as db:
        mandate = db.query(Mandate).filter(Mandate.id == mandate_id).first()
        run = db.query(RecommendationRun).filter(RecommendationRun.id == run_id).first()
        errors, _warnings = _validate_recommendation_for_finalization(db, mandate, run)
        return errors


def _finalize(session_factory, mandate_id, run_id, advisor_id):
    with session_factory() as db:
        advisor = db.query(User).filter(User.id == advisor_id).first()
        return finalize_recommendation(
            mandate_id=mandate_id, run_id=run_id, request=_FakeRequest(),
            db=db, current_user=advisor,
        )


# ---------------------------------------------------------------------------
# Das Gate greift
# ---------------------------------------------------------------------------


def test_undisclosed_conflict_blocks_and_names_what_is_missing(session_factory):
    advisor_id, mandate_id, run_id = _ready_run(session_factory, suffix="gate-a")
    _add_conflict(session_factory, mandate_id, advisor_id)

    errors = _errors(session_factory, mandate_id, run_id)
    assert any("Interessenkonflikte" in error for error in errors), errors
    # Handlungsfaehig, nicht bloss ablehnend: die Meldung muss den fehlenden
    # Nachweis benennen.
    assert any("conflict_not_disclosed" in error for error in errors), errors

    with pytest.raises(HTTPException):
        _finalize(session_factory, mandate_id, run_id, advisor_id)


def test_disclosed_but_unacknowledged_conflict_still_blocks(session_factory):
    advisor_id, mandate_id, run_id = _ready_run(session_factory, suffix="gate-b")
    _add_conflict(
        session_factory, mandate_id, advisor_id,
        disclosed_to_client=1, disclosed_at=_now(), document_id="doc-1",
    )

    errors = _errors(session_factory, mandate_id, run_id)
    assert any("conflict_not_acknowledged" in error for error in errors), errors


def test_contradictory_conflict_is_indeterminate_not_action_required(session_factory):
    """Bestaetigt ohne Offenlegung -- da ist nicht einmal klar, was zu tun ist.

    Die Meldung muss deshalb eine andere sein als bei einem schlicht offenen
    Konflikt; sonst wuerde der Berater nach einer Handlung suchen, die den
    Widerspruch nicht aufloest.
    """
    advisor_id, mandate_id, run_id = _ready_run(session_factory, suffix="gate-c")
    _add_conflict(
        session_factory, mandate_id, advisor_id,
        disclosed_to_client=0, client_acknowledged=1,
        client_acknowledged_at=_now(),
    )

    errors = _errors(session_factory, mandate_id, run_id)
    assert any("unklar" in error for error in errors), errors
    assert not any("conflict_not_disclosed" in error for error in errors), errors


# ---------------------------------------------------------------------------
# Gegenproben: das Gate darf den Normalbetrieb nicht lahmlegen
# ---------------------------------------------------------------------------


def test_mandate_without_conflicts_finalizes_normally(session_factory):
    """Die wichtigste Gegenprobe.

    Die meisten Mandate haben gar keinen Interessenkonflikt. Ein Gate, das
    sie blockiert, waere kein Nachweis, sondern ein Totalausfall -- und von
    den Tests oben nicht zu unterscheiden.
    """
    advisor_id, mandate_id, run_id = _ready_run(session_factory, suffix="gate-d")

    errors = _errors(session_factory, mandate_id, run_id)
    assert not any("Interessenkonflikte" in error for error in errors), errors

    _finalize(session_factory, mandate_id, run_id, advisor_id)
    with session_factory() as db:
        run = db.query(RecommendationRun).filter(RecommendationRun.id == run_id).first()
        assert run.result_status == "Final"


def test_fully_resolved_conflict_finalizes_normally(session_factory):
    """Der aufgeloeste Konflikt blockiert nicht -- sonst waere er unaufloesbar."""
    advisor_id, mandate_id, run_id = _ready_run(session_factory, suffix="gate-e")
    _add_conflict(
        session_factory, mandate_id, advisor_id,
        disclosed_to_client=1, disclosed_at=_now(), document_id="doc-signed",
        client_acknowledged=1, client_acknowledged_at=_now(),
    )

    errors = _errors(session_factory, mandate_id, run_id)
    assert not any("Interessenkonflikte" in error for error in errors), errors

    _finalize(session_factory, mandate_id, run_id, advisor_id)
    with session_factory() as db:
        run = db.query(RecommendationRun).filter(RecommendationRun.id == run_id).first()
        assert run.result_status == "Final"


def test_soft_deleted_conflict_does_not_block(session_factory):
    """Ein geloeschter Konflikt ist kein offener.

    Der Resolver filtert auf `deleted_at IS NULL`; dieser Test haelt das
    fest, damit ein spaeterer Umbau der Abfrage nicht unbemerkt alte,
    verworfene Zeilen zum Blocker macht.
    """
    advisor_id, mandate_id, run_id = _ready_run(session_factory, suffix="gate-f")
    _add_conflict(session_factory, mandate_id, advisor_id, deleted_at=_now())

    errors = _errors(session_factory, mandate_id, run_id)
    assert not any("Interessenkonflikte" in error for error in errors), errors


def test_conflict_of_another_mandate_does_not_block(session_factory):
    """Mandatsbindung: der Konflikt eines fremden Mandats ist nicht meiner."""
    advisor_id_a, mandate_a, run_a = _ready_run(session_factory, suffix="gate-g1")
    advisor_id_b, mandate_b, _run_b = _ready_run(session_factory, suffix="gate-g2")
    _add_conflict(session_factory, mandate_b, advisor_id_b)

    errors = _errors(session_factory, mandate_a, run_a)
    assert not any("Interessenkonflikte" in error for error in errors), errors
