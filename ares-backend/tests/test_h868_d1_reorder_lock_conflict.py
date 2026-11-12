"""H-868-D1 (Dok. 86, Delta-Pruefrunde #868), PG-Restpunkte des Reorders:

* ``with_for_update()`` ohne ``ORDER BY``: zwei Reorders konnten die
  Zeilensperren gegenlaeufig nehmen ("deadlock detected" -> 500).
* Ein PG-Deadlock bzw. Lock-Timeout entsteht beim SELECT/UPDATE, nicht in
  ``acquire_goal_order_write_lock`` -> wurde nicht auf 409 abgebildet.

Ohne lokales PostgreSQL: SQL-Mitschnitt fuer die Sperrreihenfolge und
injizierte ``OperationalError`` mit PG-SQLSTATE fuer die Abbildung.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Query

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import routers.wealth as wealth_router  # noqa: E402
from services.goal_reorder import GOAL_ORDER_CHANGED_DETAIL, is_goal_order_lock_conflict  # noqa: E402
from tests.test_goal_reorder_real_schema_unique_index import (  # noqa: E402,F401
    _mandate_with_goals,
    _ranks,
    advisor_user,
    auth_client,
    session_factory,
)


class _PgError(Exception):
    def __init__(self, sqlstate: str):
        super().__init__(f"pg error {sqlstate}")
        self.sqlstate = sqlstate


def _op_error(sqlstate: str) -> OperationalError:
    return OperationalError("SELECT ... FOR UPDATE", {}, _PgError(sqlstate))


@pytest.mark.parametrize("sqlstate", ["40P01", "55P03", "40001"])
def test_lock_conflict_sqlstates_are_recognised(sqlstate):
    assert is_goal_order_lock_conflict(_op_error(sqlstate))


def test_other_operational_errors_are_not_lock_conflicts():
    assert not is_goal_order_lock_conflict(_op_error("08006"))  # connection_failure
    assert not is_goal_order_lock_conflict(OperationalError("x", {}, Exception("disk I/O error")))


def test_reorder_reads_goals_in_fixed_id_order(auth_client, advisor_user, session_factory):
    mid, (g1, g2, g3) = _mandate_with_goals(auth_client, advisor_user)
    engine = session_factory.kw["bind"]
    statements: list[str] = []

    def _capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(" ".join(statement.split()))

    event.listen(engine, "before_cursor_execute", _capture)
    try:
        res = auth_client.put(f"/mandates/{mid}/goals/order", json={"goal_ids": [g3, g1, g2]})
    finally:
        event.remove(engine, "before_cursor_execute", _capture)
    assert res.status_code == 200, res.text
    reads = [s for s in statements if s.startswith("SELECT") and "FROM goals" in s and "goals.is_active" in s]
    assert reads, statements
    assert all("ORDER BY goals.id" in s for s in reads), reads


@pytest.mark.parametrize("sqlstate", ["40P01", "55P03"])
def test_pg_lock_conflict_on_select_is_409(auth_client, advisor_user, session_factory, monkeypatch, sqlstate):
    mid, (g1, g2, g3) = _mandate_with_goals(auth_client, advisor_user)
    real_all = Query.all

    def _all(self):
        if self.column_descriptions and self.column_descriptions[0].get("entity") is wealth_router.Goal \
                and getattr(self, "_for_update_arg", None) is not None:
            raise _op_error(sqlstate)
        return real_all(self)

    monkeypatch.setattr(Query, "all", _all)
    res = auth_client.put(f"/mandates/{mid}/goals/order", json={"goal_ids": [g3, g1, g2]})
    monkeypatch.setattr(Query, "all", real_all)
    assert res.status_code == 409, res.text
    assert res.json()["detail"] == GOAL_ORDER_CHANGED_DETAIL
    assert _ranks(auth_client, mid) == {g1: 1, g2: 2, g3: 3}


def test_pg_deadlock_on_write_is_409(auth_client, advisor_user, session_factory, monkeypatch):
    mid, (g1, g2, g3) = _mandate_with_goals(auth_client, advisor_user)

    def _deadlock(*args, **kwargs):
        raise _op_error("40P01")

    monkeypatch.setattr(wealth_router, "_write_goal_ranks", _deadlock)
    res = auth_client.put(f"/mandates/{mid}/goals/order", json={"goal_ids": [g3, g1, g2]})
    assert res.status_code == 409, res.text
    assert _ranks(auth_client, mid) == {g1: 1, g2: 2, g3: 3}
