"""GOAL-RANK-HARDNESS-ROUNDTRIP-001 / ADR-10c: atomare Ziel-Reihenfolge.

``PUT /mandates/{id}/goals/order`` schreibt die vollstaendige Permutation der
aktiven Ziele: jede ID genau einmal, Raenge danach lueckenlos 1..n, Haerte
unveraendert. Optional prueft ``expected_goal_ids`` den zuletzt gesehenen
Stand (CAS, 409 bei Abweichung). Ungueltige Permutationen -> 422, ohne dass
ein Rang geschrieben wird.
"""
from __future__ import annotations

import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base, get_db
from main import app
from models.users import User
from models.wealth import Goal
from services.auth import get_current_user
from services.goal_reorder import GoalOrderConflictError, GoalOrderError, resolve_goal_order
from services.optimizer.goal_liabilities import _weight_bps
from tests.risk_fixture_helpers import noop_lifespan


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'goal_reorder.db'}",
        connect_args={"check_same_thread": False},
    )
    sf = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield sf
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def advisor_user():
    return User(
        id="user-goal-reorder", username="advisor-reorder", password_hash="h",
        full_name="Advisor", role="advisor", is_active=1,
        created_at=_now(), updated_at=_now(),
    )


@pytest.fixture()
def auth_client(session_factory, advisor_user, monkeypatch):
    def override_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: advisor_user
    monkeypatch.setattr(app.router, "lifespan_context", noop_lifespan)
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def _mandate_with_goals(client: TestClient, advisor: User) -> tuple[str, list[str]]:
    c = client.post("/clients", json={
        "client_number": "REORDER-001", "first_name": "Re", "last_name": "Order",
        "advisor_id": advisor.id, "household_type": "Einzelperson",
    })
    assert c.status_code == 201, c.text
    m = client.post(f"/clients/{c.json()['id']}/mandates", json={
        "mandate_number": "REORDER-M-001", "mandate_type": "Anlageberatung",
    })
    assert m.status_code == 201, m.text
    mid = m.json()["id"]
    ids = []
    for rank, hardness in ((1, "Primär"), (2, "Hart"), (3, "Opportunistisch")):
        g = client.post(f"/mandates/{mid}/goals", json={
            "goal_family": "Vermögen", "goal_type": "Vermoegensziel",
            "label": f"g{rank}", "rank": rank, "target_wealth_rappen": 100_000_00,
            "horizon_years": 10, "hardness": hardness, "value_mode": "nominal",
        })
        assert g.status_code == 201, g.text
        ids.append(g.json()["id"])
    return mid, ids


def _ranks(client: TestClient, mid: str) -> dict[str, tuple[int, str]]:
    return {g["id"]: (g["rank"], g["hardness"]) for g in client.get(f"/mandates/{mid}/goals").json()}


def test_reorder_writes_gapless_ranks_and_keeps_hardness(auth_client, advisor_user, session_factory):
    mid, (g1, g2, g3) = _mandate_with_goals(auth_client, advisor_user)
    r = auth_client.put(f"/mandates/{mid}/goals/order", json={
        "goal_ids": [g3, g1, g2], "expected_goal_ids": [g1, g2, g3],
    })
    assert r.status_code == 200, r.text
    assert [g["id"] for g in r.json()] == [g3, g1, g2]
    assert _ranks(auth_client, mid) == {
        g3: (1, "Opportunistisch"), g1: (2, "Primär"), g2: (3, "Hart"),
    }
    # Das Default-Gewicht folgt dem neuen kanonischen Rang.
    with session_factory() as db:
        assert _weight_bps(db.get(Goal, g3)) == 10_000
        assert _weight_bps(db.get(Goal, g2)) == 2_500


@pytest.mark.parametrize("bad", ["duplicate", "missing", "unknown"])
def test_invalid_permutation_is_rejected_without_writing(auth_client, advisor_user, bad):
    mid, (g1, g2, g3) = _mandate_with_goals(auth_client, advisor_user)
    before = _ranks(auth_client, mid)
    goal_ids = {
        "duplicate": [g1, g1, g2, g3],
        "missing": [g2, g1],
        "unknown": [g3, g2, g1, "fremd"],
    }[bad]
    r = auth_client.put(f"/mandates/{mid}/goals/order", json={"goal_ids": goal_ids})
    assert r.status_code == 422, r.text
    assert _ranks(auth_client, mid) == before


def test_stale_expected_order_is_a_conflict(auth_client, advisor_user):
    mid, (g1, g2, g3) = _mandate_with_goals(auth_client, advisor_user)
    first = auth_client.put(f"/mandates/{mid}/goals/order", json={
        "goal_ids": [g2, g1, g3], "expected_goal_ids": [g1, g2, g3],
    })
    assert first.status_code == 200, first.text
    # Zweiter Client kennt noch die alte Folge -> 409, kein Ueberschreiben.
    stale = auth_client.put(f"/mandates/{mid}/goals/order", json={
        "goal_ids": [g3, g2, g1], "expected_goal_ids": [g1, g2, g3],
    })
    assert stale.status_code == 409, stale.text
    assert {k: v[0] for k, v in _ranks(auth_client, mid).items()} == {g2: 1, g1: 2, g3: 3}


def test_update_with_occupied_rank_keeps_own_rank(auth_client, advisor_user):
    """Keine automatische Herabstufung: belegter Wunschrang -> eigener Rang."""
    mid, (g1, g2, g3) = _mandate_with_goals(auth_client, advisor_user)
    r = auth_client.put(f"/mandates/{mid}/goals/{g3}", json={"rank": 1})
    assert r.status_code == 200, r.text
    assert r.json()["rank"] == 3
    free = auth_client.put(f"/mandates/{mid}/goals/{g3}", json={"rank": 7})
    assert free.status_code == 200 and free.json()["rank"] == 7


def test_resolver_tolerates_legacy_rank_ties_in_expected_order():
    class G:
        def __init__(self, gid, rank):
            self.id, self.rank = gid, rank

    goals = [G("a", 1), G("b", 1), G("c", 2)]
    # Gleichrangige Altdaten: beide Folgen von a/b passen zum Serverstand.
    assert resolve_goal_order(goals, ["c", "a", "b"], ["b", "a", "c"]) == {"c": 1, "a": 2, "b": 3}
    assert resolve_goal_order(goals, ["c", "a", "b"], ["a", "b", "c"]) == {"c": 1, "a": 2, "b": 3}
    with pytest.raises(GoalOrderConflictError):
        resolve_goal_order(goals, ["c", "a", "b"], ["c", "a", "b"])
    with pytest.raises(GoalOrderError):
        resolve_goal_order(goals, ["a", "b"])
