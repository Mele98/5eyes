"""Round 38 red test -- GOAL-PAST-DATE-LIFECYCLE-001.

Audit: docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-
validation-audit.md, finding GOAL-PAST-DATE-LIFECYCLE-001.

Finding (paraphrased): Goals have no typed lifecycle/transition mechanism at
all. A Goal's "past/overdue" economic status today is represented only
implicitly -- most directly by editing ``target_date`` into the past (see
``routers.wealth._goal_horizon_from_date``, which silently floors any goal
whose target lies in the past to ``horizon_years = 1`` with NO error, NO
status flag, and NO lifecycle transition of any kind) or by toggling
``Goal.is_active``.

Separately, ``models/allocation.py::TargetAllocation`` persists
per-mandate-generation *evidence* that was computed against a goal's state
at generation time:

  - ``TargetAllocation.goal_achievability_json`` -- a JSON list of per-goal
    achievability/probability entries (read back in
    ``services/portfolio_engine.py`` around the ``goal_achievability_json``
    parsing block and fed into ``classify_messages`` to build the strategy
    report's goal-achievability pills).
  - ``TargetAllocation.input_snapshot_hash`` -- a hash over wealth/cashflow/
    goal inputs (see ``services/portfolio_engine.py::
    _compute_input_snapshot_hash``, which *does* include each goal's
    ``target_date``) used only to show a generic textual drift "Hinweis"
    banner (``_strategy_drift_warnings``) -- it never clears or recomputes
    the stale per-goal ``goal_achievability_json`` entries themselves.

Today's actual invalidation path for goal edits
(``routers/wealth.py::_invalidate_achievement_scores_for_mandate``, wired
into ``create_goal`` / ``update_goal`` / ``delete_goal``) ONLY nulls
``Goal.achievement_score``. It never touches ``TargetAllocation.
goal_achievability_json`` (or any other persisted allocation/probability
evidence) at all -- confirmed by reading every call site in
``routers/wealth.py``.

Desired contract under test: when a goal's economic status transitions to
"past due" (its ``target_date`` is edited into the past -- the only
materialized lifecycle signal that exists today), any cached/stored
allocation or probability evidence computed against the *old* (still-future)
liability must be invalidated atomically with that edit, in the SAME
request/transaction -- not just flagged with a generic drift banner while
the stale per-goal payload is still served to the UI.

This test reproduces that gap directly against the persistence layer (no
solver run needed): it seeds a ``TargetAllocation.goal_achievability_json``
entry representing evidence computed while the goal's ``target_date`` was
still in the future, then PUTs the goal's ``target_date`` into the past, and
asserts the stored per-goal evidence entry was invalidated. It fails today
because no such invalidation exists; it is marked ``xfail(strict=True)`` so
the suite stays green until GOAL-PAST-DATE-LIFECYCLE-001 is fixed.
"""
from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, get_db
from main import app
from models.allocation import TargetAllocation
from models.clients import Client  # noqa: F401 - SQLAlchemy metadata/relationships
from models.mandates import Mandate  # noqa: F401 - SQLAlchemy metadata/relationships
from models.users import User
from models.wealth import Goal
from services.auth import get_current_user


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'goal_lifecycle_transition_invalidation.db'}",
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
        id="user-goal-lifecycle",
        username="advisor",
        password_hash="h",
        full_name="Advisor",
        role="advisor",
        is_active=1,
        created_at=_utc_now_iso(),
        updated_at=_utc_now_iso(),
    )


@pytest.fixture()
def auth_client(session_factory, advisor_user):
    def override_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: advisor_user
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def _setup_mandate(auth_client: TestClient, advisor_user: User) -> str:
    client_resp = auth_client.post(
        "/clients",
        json={
            "client_number": "GOAL-LC-001",
            "first_name": "Lifecycle", "last_name": "Test",
            "advisor_id": advisor_user.id,
            "household_type": "Einzelperson",
        },
    )
    assert client_resp.status_code == 201, client_resp.text
    client_id = client_resp.json()["id"]
    mandate_resp = auth_client.post(
        f"/clients/{client_id}/mandates",
        json={"mandate_number": "GOAL-LC-M-001", "mandate_type": "Anlageberatung"},
    )
    assert mandate_resp.status_code == 201, mandate_resp.text
    return mandate_resp.json()["id"]


def _create_future_cashflow_goal(auth_client: TestClient, mandate_id: str) -> str:
    """Creates a one-off expense goal whose liability is still in the future."""
    resp = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json={
            "goal_family": "Cashflow",
            "goal_type": "Einmalige_Ausgabe",
            "label": "Eigenmittel Immobilie",
            "rank": 1,
            "target_amount_rappen": 250_000_00,
            "start_date": "2015-01-01",
            "target_date": "2031-06-01",
            "hardness": "Primär",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _seed_target_allocation_with_goal_evidence(
    session_factory, mandate_id: str, goal_id: str,
) -> str:
    """Directly persists a TargetAllocation carrying goal_achievability_json
    evidence computed while the goal's liability was still in the future --
    mirrors what services/portfolio_engine.py writes on a real solver run,
    without needing to run the solver.
    """
    allocation_id = "ta-goal-lifecycle-001"
    evidence = [
        {
            "goal_id": goal_id,
            "label": "Eigenmittel Immobilie",
            "probability_pct": 82,
            "status": "on_track",
            "computed_against_target_date": "2031-06-01",
        }
    ]
    with session_factory() as db:
        allocation = TargetAllocation(
            id=allocation_id,
            mandate_id=mandate_id,
            version=1,
            is_current=1,
            target_equities_bps=4000,
            target_bonds_bps=4000,
            target_real_estate_bps=1000,
            target_alternatives_bps=500,
            target_liquidity_bps=500,
            band_equities_min_bps=3000,
            band_equities_max_bps=5000,
            band_bonds_min_bps=3000,
            band_bonds_max_bps=5000,
            band_real_estate_min_bps=0,
            band_real_estate_max_bps=2000,
            band_alternatives_min_bps=0,
            band_alternatives_max_bps=1000,
            band_liquidity_min_bps=200,
            band_liquidity_max_bps=1000,
            goal_achievability_json=json.dumps(evidence),
            policy_id="policy-goal-lifecycle",
            set_by="user-goal-lifecycle",
            set_at=_utc_now_iso(),
            created_at=_utc_now_iso(),
            updated_at=_utc_now_iso(),
        )
        db.add(allocation)
        db.commit()
    return allocation_id


def _load_goal_evidence_entry(
    session_factory, allocation_id: str, goal_id: str,
) -> dict | None:
    with session_factory() as db:
        allocation = db.query(TargetAllocation).filter(
            TargetAllocation.id == allocation_id,
        ).first()
        assert allocation is not None
        raw = allocation.goal_achievability_json
        if not raw:
            return None
        entries = json.loads(raw)
        for entry in entries:
            if entry.get("goal_id") == goal_id:
                return entry
    return None


@pytest.mark.xfail(
    strict=True,
    reason=(
        "GOAL-PAST-DATE-LIFECYCLE-001 -- round 38 red test, see "
        "docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md"
    ),
)
def test_goal_target_date_transition_to_past_invalidates_cached_allocation_evidence(
    session_factory, auth_client, advisor_user,
):
    """Desired contract: editing a goal's target_date into the past (the
    goal's only materialized past/overdue transition today) must atomically
    invalidate any TargetAllocation.goal_achievability_json evidence that was
    computed against that goal while its liability was still in the future.

    Today, routers.wealth.update_goal only nulls Goal.achievement_score via
    _invalidate_achievement_scores_for_mandate -- it never touches
    TargetAllocation.goal_achievability_json. So the stale "on_track" /
    82%-probability evidence -- computed against a 2031-06-01 liability that
    no longer reflects reality once the date has been moved into the past --
    continues to be served completely untouched, with no error and no
    staleness marker of any kind. This assertion therefore fails today.
    """
    mandate_id = _setup_mandate(auth_client, advisor_user)
    goal_id = _create_future_cashflow_goal(auth_client, mandate_id)
    allocation_id = _seed_target_allocation_with_goal_evidence(
        session_factory, mandate_id, goal_id,
    )

    # Sanity: evidence exists and reflects the future-liability computation
    # before the lifecycle transition.
    before = _load_goal_evidence_entry(session_factory, allocation_id, goal_id)
    assert before is not None
    assert before["status"] == "on_track"
    assert before["probability_pct"] == 82

    # Act: transition the goal's economic status to "past due" by moving its
    # target_date into the past. This is the only lifecycle transition the
    # system materializes today (no typed status field exists at all).
    update_resp = auth_client.put(
        f"/mandates/{mandate_id}/goals/{goal_id}",
        json={"target_date": "2020-01-01"},
    )
    assert update_resp.status_code == 200, update_resp.text

    # Assert (desired behavior): the stored evidence for THIS goal must have
    # been invalidated atomically with the transition -- either removed
    # entirely, or explicitly marked stale/unscored. A stale "on_track" /
    # 82%-probability payload computed against the old future date must
    # never still be served after the goal has become overdue.
    after = _load_goal_evidence_entry(session_factory, allocation_id, goal_id)
    assert after is None or after.get("status") in {
        "stale",
        "stale_past_date_transition",
        "needs_recalculation",
    }, (
        "Expected goal_achievability_json evidence for the goal to be "
        "invalidated after its target_date transitioned into the past, "
        f"but found unchanged stale evidence: {after!r}"
    )
