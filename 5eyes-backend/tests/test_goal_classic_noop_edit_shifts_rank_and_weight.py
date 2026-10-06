"""Audit Kontrollrunde 37, Finding GOAL-RANK-HARDNESS-ROUNDTRIP-001 (Repro 4).

Siehe docs/audits/2026-09-28-goal-funding-priority-and-achievability-attribution-audit.md

Root-Cause (zwei Schichten):

1. Frontend (5eyes-electron/frontend/5eyes_v2.html, openGoalEditor(), aktuell
   Zeile ~27119-27125): Beim OEFFNEN eines bestehenden Ziels zum Bearbeiten
   wird der Wert des Prioritaets-<select> ("nz-prio") primaer aus der
   persistierten HAERTE abgeleitet (`priorityMap[goal.hardness]`) und nur
   als Fallback aus dem persistierten RANG (`String(goal.rank||2)`). Rang und
   Haerte sind laut der Backend-Doku in `_resolve_goal_rank_conflict`
   (routers/wealth.py) aber ausdruecklich ZWEI verschiedene Dinge ("Rang ist
   KEINE Haerte-Klassifikation"). Fuer ein Ziel wie g2 (rank=2,
   hardness='Hart') liefert diese Zeile daher faelschlich '1' statt des
   korrekten, rundreise-sicheren '2'.

2. Backend (routers/wealth.py, update_goal() -> _resolve_goal_rank_conflict()):
   Speichert man dieses (durch Bug 1 falsch initialisierte) Formular ohne
   jede inhaltliche Aenderung ("No-op-Edit"), sendet das Frontend rank=1 fuer
   g2. Der echte Rang-Konflikt-Resolver findet rank=1 bereits von g1 belegt
   und vergibt `max(andere Raenge)+1` = max(1 [g1], 3 [g3]) + 1 = 4 -- NICHT
   den urspruenglichen Rang 2, erst recht nicht den gewuenschten 1. Weil
   `weight_bps` fuer g2 nie explizit gesetzt wurde, leitet
   services/optimizer/goal_liabilities.py::_weight_bps() das Default-Gewicht
   aus dem (jetzt driftenden) Rang ab: 5000bps (Rang 2) -> 1250bps (Rang 4).
   Ein voelliger No-op-Edit veraendert so lautlos sowohl die Sortierung als
   auch die Optimizer-Gewichtung eines Ziels.

Beide Tests unten sind bewusst RED (xfail/strict) -- sie dokumentieren den
Bug, der Fix selbst ist nicht Teil dieses Runde-47-Auftrags.
"""
from __future__ import annotations

import datetime
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

HTML_PATH = BACKEND_ROOT.parents[0] / "5eyes-electron" / "frontend" / "5eyes_v2.html"

from database import Base, get_db  # noqa: E402
from main import app  # noqa: E402
from models.clients import Client  # noqa: F401,E402 — SQLAlchemy metadata
from models.mandates import Mandate  # noqa: F401,E402
from models.users import User  # noqa: E402
from services.auth import get_current_user  # noqa: E402


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Fixtures (same shape as tests/test_goal_rank_auto_resolution.py)
# ---------------------------------------------------------------------------


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'goal_classic_noop_rank_drift.db'}",
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
        id="user-rank-drift",
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
            "client_number": "RANK-DRIFT-001",
            "first_name": "Rank",
            "last_name": "DriftClient",
            "advisor_id": advisor_user.id,
            "household_type": "Einzelperson",
        },
    )
    assert client_resp.status_code == 201, client_resp.text
    client_id = client_resp.json()["id"]
    mandate_resp = auth_client.post(
        f"/clients/{client_id}/mandates",
        json={"mandate_number": "RANK-DRIFT-M-001", "mandate_type": "Anlageberatung"},
    )
    assert mandate_resp.status_code == 201, mandate_resp.text
    return mandate_resp.json()["id"]


def _vermoegensziel_payload(rank: int, hardness: str, label: str) -> dict:
    return {
        "goal_family": "Vermögen",
        "goal_type": "Vermoegensziel",
        "label": label,
        "rank": rank,
        "target_wealth_rappen": 1_000_000_00,
        "horizon_years": 10,
        "hardness": hardness,
        "value_mode": "nominal",
    }


# ---------------------------------------------------------------------------
# (a) Frontend layer: Classic edit-select initialization must round-trip
#     the persisted rank, not re-derive a value from hardness.
# ---------------------------------------------------------------------------


def _extract_priority_map_literal(html: str) -> str:
    match = re.search(r"var priorityMap=\{[^}]*\};", html)
    assert match, (
        "priorityMap literal not found in 5eyes_v2.html -- Classic goal "
        "editor's hardness->priority mapping moved; update this extraction "
        "regex before trusting the test below"
    )
    return match.group(0)


def _extract_stored_priority_statement(html: str) -> str:
    match = re.search(
        r"var storedPriority=priorityMap\[goal\.hardness\]\|\|String\(goal\.rank\|\|2\);",
        html,
    )
    assert match, (
        "storedPriority derivation in openGoalEditor() changed shape -- "
        "update this extraction regex before trusting the test below"
    )
    return match.group(0)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "GOAL-RANK-HARDNESS-ROUNDTRIP-001 -- round 47 red test (Classic "
        "no-op edit shifts rank 2->4 and weight 5000->1250), see audit "
        "docs/audits/2026-09-28-goal-funding-priority-and-achievability-"
        "attribution-audit.md"
    ),
)
def test_classic_edit_select_init_should_roundtrip_persisted_rank_not_hardness():
    """Extracts the REAL `priorityMap` literal and `storedPriority` derivation
    line out of 5eyes_v2.html's openGoalEditor() and executes them with Node
    against g2's real persisted state (rank=2, hardness='Hart'). A round-trip-
    safe implementation would initialize the select to '2' (the persisted
    rank). The real code instead maps hardness='Hart' -> '1' via priorityMap
    and only falls back to rank when hardness is unmapped, so this yields
    '1' -- the wrong value a subsequent no-op save would send to the backend.
    """
    if shutil.which("node") is None:
        pytest.skip("node binary not available to execute extracted JS")

    html = _html()
    priority_map_literal = _extract_priority_map_literal(html)
    stored_priority_statement = _extract_stored_priority_statement(html)

    node_script = (
        priority_map_literal + "\n"
        "var goal = {rank: 2, hardness: 'Hart'};\n"
        + stored_priority_statement + "\n"
        "console.log(storedPriority);\n"
    )
    result = subprocess.run(
        ["node", "-e", node_script],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    stored_priority = result.stdout.strip()

    # Round-trip-safe expectation: opening g2 (persisted rank=2) for editing
    # and changing nothing must keep the select on '2'.
    assert stored_priority == "2", (
        f"expected round-trip-safe priority '2' (g2's persisted rank), got "
        f"{stored_priority!r} -- openGoalEditor() mapped from "
        f"hardness='Hart' via priorityMap instead of using the persisted "
        f"rank=2"
    )


# ---------------------------------------------------------------------------
# (b) Backend layer: a no-op edit that (due to bug (a)) resends rank=1 for
#     g2 must not silently drift g2's rank to 4 and its derived weight from
#     5000bps to 1250bps.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "GOAL-RANK-HARDNESS-ROUNDTRIP-001 -- round 47 red test (Classic "
        "no-op edit shifts rank 2->4 and weight 5000->1250), see audit "
        "docs/audits/2026-09-28-goal-funding-priority-and-achievability-"
        "attribution-audit.md"
    ),
)
def test_classic_noop_edit_resend_does_not_silently_drift_rank_and_weight(
    auth_client, advisor_user, session_factory,
):
    from routers.wealth import _resolve_goal_rank_conflict
    from services.optimizer.goal_liabilities import _weight_bps

    mandate_id = _setup_mandate(auth_client, advisor_user)

    g1 = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json=_vermoegensziel_payload(1, "Hart", "g1"),
    )
    assert g1.status_code == 201, g1.text
    g2 = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json=_vermoegensziel_payload(2, "Primär", "g2"),
    )
    assert g2.status_code == 201, g2.text
    g3 = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json=_vermoegensziel_payload(3, "Opportunistisch", "g3"),
    )
    assert g3.status_code == 201, g3.text

    # g2 as actually persisted: rank=2, hardness='Primär'. The audit's
    # confirmed repro uses hardness='Hart' for g2 to make the frontend bug
    # bite (priorityMap['Hart']='1'); re-create g2 with that exact hardness
    # via a direct update so we exercise the identical scenario as Repro 4
    # while keeping goal creation simple above.
    g2_id = g2.json()["id"]
    fix_hardness = auth_client.put(
        f"/mandates/{mandate_id}/goals/{g2_id}",
        json={"hardness": "Hart"},
    )
    assert fix_hardness.status_code == 200, fix_hardness.text
    assert fix_hardness.json()["rank"] == 2
    assert fix_hardness.json()["hardness"] == "Hart"
    assert fix_hardness.json()["weight_bps"] is None  # never explicitly set

    # Fetch the real ORM Goal row for g2 and confirm the rank=2 default weight.
    from models.wealth import Goal

    with session_factory() as db:
        goal_row = db.query(Goal).filter(Goal.id == g2_id).first()
        assert goal_row is not None
        assert goal_row.rank == 2
        weight_before = _weight_bps(goal_row)
    assert weight_before == 5000

    # Simulate the Classic UI's no-op-edit bug: openGoalEditor() mapped g2's
    # hardness='Hart' to priority '1' (see part (a)), and saveGoal() sends
    # that straight through as rank=1 even though the user changed nothing.
    noop_edit_resend = auth_client.put(
        f"/mandates/{mandate_id}/goals/{g2_id}",
        json={"rank": 1},
    )
    assert noop_edit_resend.status_code == 200, noop_edit_resend.text
    resolved_rank = noop_edit_resend.json()["rank"]

    # Desired/round-trip-safe behavior: a no-op edit must not move g2 away
    # from its own original rank (2). The real resolver instead treats this
    # as a fresh conflict against g1 (rank=1) and appends g2 at
    # max(other active ranks)+1 = max(1, 3)+1 = 4 -- further from the truth
    # than even the wrongly-requested rank=1.
    assert resolved_rank == 2, (
        f"no-op edit silently drifted g2's rank from 2 to {resolved_rank} "
        "(expected the resolver to leave g2's own unchanged rank alone)"
    )

    # Cross-check directly against the real resolver helper with the exact
    # three-goal layout from the audit's confirmed repro.
    with session_factory() as db:
        direct_result = _resolve_goal_rank_conflict(
            mandate_id, 1, db, existing_id=g2_id,
        )
    assert direct_result == 2, (
        f"_resolve_goal_rank_conflict resolved g2's wrongly-resent rank=1 "
        f"to {direct_result} instead of preserving g2's original rank=2"
    )

    # Weight side-effect: because weight_bps was never explicitly set, the
    # default derived from rank drops once the rank has drifted.
    with session_factory() as db:
        goal_row_after = db.query(Goal).filter(Goal.id == g2_id).first()
        assert goal_row_after is not None
        weight_after = _weight_bps(goal_row_after)

    assert weight_after == weight_before == 5000, (
        f"derived default weight_bps silently changed from {weight_before} "
        f"(rank 2) to {weight_after} (rank {goal_row_after.rank}) as a "
        "side-effect of a purely cosmetic no-op edit"
    )
