"""N-868-2 (Pruefrunde #868): parallele Ziel-Umsortierung.

Ablauf "A liest, B committet, A schreibt": A hatte seine
``expected_goal_ids`` gegen einen Stand geprueft, den B danach geaendert
hat. Ergebnis war entweder HTTP 500 (A lief beim Schreiben in
``ux_goals_rank_active``) oder ein stilles Ueberschreiben von B trotz CAS.

Fix: Schreibsperre VOR dem Lesen (SQLite ``BEGIN IMMEDIATE``, PostgreSQL
``SELECT ... FOR UPDATE``), danach CAS; ein Rest-IntegrityError wird als
409 gemeldet. Die Tests rufen den Endpunkt in zwei Threads mit je eigener
Session auf dem echten Schema auf; Thread A wird nach dem Lesen angehalten.
"""
from __future__ import annotations

import threading

import pytest
from fastapi import HTTPException

import services.goal_reorder as goal_reorder
from models.review import AuditLog
from routers.wealth import reorder_goals
from schemas.wealth import GoalOrderUpdate
from tests.test_goal_reorder_real_schema_unique_index import (  # noqa: F401
    _assert_real_index,
    _mandate_with_goals,
    _ranks,
    advisor_user,
    auth_client,
    session_factory,
)

# (A will, B will) als Indizes in die Ausgangsfolge g1,g2,g3.
# "disjoint": A verschiebt g1/g2, B verschiebt g2/g3 -> ohne Sperre 500.
# "full": beide verschieben alle drei -> ohne Sperre ueberschreibt A B.
CASES = {
    "disjoint": ((1, 0, 2), (0, 2, 1)),
    "full": ((2, 0, 1), (1, 0, 2)),
}


def _call(session_factory, user, mid, goal_ids, expected, out, key):
    try:
        with session_factory() as db:
            reorder_goals(
                mid, GoalOrderUpdate(goal_ids=goal_ids, expected_goal_ids=expected),
                db=db, current_user=user,
            )
        out[key] = (200, None)
    except HTTPException as exc:
        out[key] = (exc.status_code, exc.detail)
    except Exception as exc:  # jeder andere Fehler waere ein 500
        out[key] = (500, repr(exc))


def _pause_reader_a(monkeypatch):
    """Haelt Thread A direkt nach dem Lesen (in resolve_goal_order) an."""
    a_has_read = threading.Event()
    release_a = threading.Event()
    original = goal_reorder.resolve_goal_order

    def paused(goals, goal_ids, expected=None):
        result = original(goals, goal_ids, expected)
        if threading.current_thread().name == "reorder-A":
            a_has_read.set()
            assert release_a.wait(10), "A wurde nicht freigegeben"
        return result

    monkeypatch.setattr(goal_reorder, "resolve_goal_order", paused)
    return a_has_read, release_a


def _race(session_factory, user, mid, ids, case, monkeypatch):
    a_perm, b_perm = CASES[case]
    a_order = [ids[i] for i in a_perm]
    b_order = [ids[i] for i in b_perm]
    a_has_read, release_a = _pause_reader_a(monkeypatch)
    out: dict = {}
    ta = threading.Thread(name="reorder-A", target=_call,
                          args=(session_factory, user, mid, a_order, ids, out, "A"))
    tb = threading.Thread(name="reorder-B", target=_call,
                          args=(session_factory, user, mid, b_order, ids, out, "B"))
    ta.start()
    assert a_has_read.wait(10)
    tb.start()
    # B bekommt Zeit, ohne Sperre vollstaendig zu committen.
    tb.join(1.0)
    b_finished_while_a_paused = not tb.is_alive()
    release_a.set()
    ta.join(15)
    tb.join(15)
    return out, a_order, b_order, b_finished_while_a_paused


def _goal_update_count(session_factory, ids) -> int:
    with session_factory() as db:
        return db.query(AuditLog).filter(
            AuditLog.table_name == "goals", AuditLog.action == "UPDATE",
            AuditLog.record_id.in_(list(ids)),
        ).count()


@pytest.mark.parametrize("case", sorted(CASES))
def test_parallel_reorder_is_serialized_never_500(
    auth_client, advisor_user, session_factory, monkeypatch, case,
):
    _assert_real_index(session_factory)
    mid, ids = _mandate_with_goals(auth_client, advisor_user)
    out, a_order, b_order, b_early = _race(
        session_factory, advisor_user, mid, ids, case, monkeypatch,
    )
    assert all(status != 500 for status, _ in out.values()), out
    # Sperre: B wartet auf A, statt dazwischen zu committen.
    assert not b_early, out
    assert out["A"][0] == 200, out
    assert out["B"][0] == 409, out
    assert _ranks(auth_client, mid) == {gid: i + 1 for i, gid in enumerate(a_order)}
    moved_by_a = sum(1 for i, gid in enumerate(a_order) if ids.index(gid) != i)
    assert _goal_update_count(session_factory, ids) == moved_by_a


def test_rank_collision_without_lock_is_409_not_500(
    auth_client, advisor_user, session_factory, monkeypatch,
):
    """Restfall-Absicherung: greift die Sperre nicht (hier abgeschaltet),
    meldet der Unique-Index-Konflikt 409 und schreibt keinen Teilstand."""
    _assert_real_index(session_factory)
    mid, ids = _mandate_with_goals(auth_client, advisor_user)
    monkeypatch.setattr(goal_reorder, "acquire_goal_order_write_lock", lambda db: None)
    out, a_order, b_order, b_early = _race(
        session_factory, advisor_user, mid, ids, "disjoint", monkeypatch,
    )
    assert b_early, out  # ohne Sperre committet B dazwischen
    assert out["B"][0] == 200, out
    assert out["A"] == (409, goal_reorder.GOAL_ORDER_CHANGED_DETAIL), out
    assert _ranks(auth_client, mid) == {gid: i + 1 for i, gid in enumerate(b_order)}
    moved_by_b = sum(1 for i, gid in enumerate(b_order) if ids.index(gid) != i)
    assert _goal_update_count(session_factory, ids) == moved_by_b


def test_sequential_reorders_unaffected_by_lock(auth_client, advisor_user, session_factory):
    mid, (g1, g2, g3) = _mandate_with_goals(auth_client, advisor_user)
    for order in ([g3, g1, g2], [g2, g3, g1], [g1, g2, g3]):
        r = auth_client.put(f"/mandates/{mid}/goals/order", json={"goal_ids": order})
        assert r.status_code == 200, r.text
        assert [g["id"] for g in r.json()] == order
