"""Audit Kontrollrunde 37, Finding GOAL-RANK-HARDNESS-ROUNDTRIP-001 (Repro 4).

Siehe docs/audits/2026-09-28-goal-funding-priority-and-achievability-attribution-audit.md

Root-Cause (zwei Schichten):

1. Frontend (ares-desktop/frontend/ares.html, openGoalEditor(), aktuell
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

GESCHLOSSEN 2026-10-25: (1) der Classic-Select ist ein reines Haerte-Control,
der Rang kommt aus dem persistierten Rang bzw. der Listenreihenfolge (ADR-10b);
(2) ein Update mit belegtem Wunschrang behaelt den eigenen Rang statt ans Ende
geschoben zu werden (keine automatische Herabstufung). Umsortieren laeuft ueber
``PUT /mandates/{id}/goals/order`` (ADR-10c).
"""
from __future__ import annotations

import datetime
import json
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

HTML_PATH = BACKEND_ROOT.parents[0] / "ares-desktop" / "frontend" / "ares.html"

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
        "priorityMap literal not found in ares.html -- Classic goal "
        "editor's hardness->priority mapping moved; update this extraction "
        "regex before trusting the test below"
    )
    return match.group(0)


def _extract_stored_priority_statement(html: str) -> str:
    match = re.search(r"var storedPriority=priorityMap\[goal\.hardness\]\|\|'2';", html)
    assert match, (
        "storedPriority derivation in openGoalEditor() changed shape -- "
        "update this extraction regex before trusting the test below"
    )
    return match.group(0)


def _extract_hardness_map_literal(html: str) -> str:
    match = re.search(r"var hardnessMap=\{[^}]*\};", html)
    assert match, "hardnessMap literal not found in saveGoal()"
    return match.group(0)


def _extract_save_rank_expression(html: str) -> str:
    """Der Ausdruck, mit dem saveGoal() den Rang in den Payload schreibt."""
    save_src = html[html.index("async function saveGoal(options){"):]
    match = re.search(r"\n    rank:(\(function\(\)\{.*?\}\)\(\)),\n", save_src)
    assert match, "rank expression in saveGoal() payload changed shape"
    return match.group(1)


def _run_classic_roundtrip(goals: list[dict], edit_id: str | None) -> dict:
    """Fuehrt die ECHTEN Ausdruecke aus ares.html in node aus:
    Edit-Initialisierung des Haerte-Selects (openGoalEditor) und Rang/Haerte
    im Speicher-Payload (saveGoal)."""
    html = _html()
    goal = next((g for g in goals if g["id"] == edit_id), {"hardness": "Primär"})
    script = "\n".join([
        f"var currentGoals = {json.dumps(goals)};",
        f"var goal = {json.dumps(goal)};",
        f"var isEdit = {json.dumps(edit_id is not None)};",
        f"var goalIdBeforeSave = {json.dumps(edit_id)};",
        _extract_priority_map_literal(html),
        _extract_stored_priority_statement(html),
        _extract_hardness_map_literal(html),
        "var prio = storedPriority;",
        "var rank = " + _extract_save_rank_expression(html) + ";",
        "process.stdout.write(JSON.stringify({prio: storedPriority, rank: rank, hardness: hardnessMap[prio]}));",
    ])
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=10, check=False)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


_HARDNESS = ["Hart", "Primär", "Opportunistisch"]


@pytest.mark.parametrize("rank", [1, 2, 3, 4, 5])
@pytest.mark.parametrize("hardness", _HARDNESS)
def test_classic_noop_edit_roundtrips_rank_and_hardness_independently(rank, hardness):
    """Pflichttest 1/2: Roundtrip-Matrix Rang 1..5 x Haerte. Der Classic-
    Select ist ein reines Haerte-Control; der Rang kommt beim Speichern aus
    dem persistierten Rang des Ziels (Rang = Listenreihenfolge). Ein No-op-
    Edit schreibt beide Felder unveraendert zurueck."""
    if shutil.which("node") is None:
        pytest.skip("node binary not available to execute extracted JS")
    others = [{"id": f"o{r}", "rank": r, "hardness": "Primär"} for r in range(1, 7) if r != rank]
    goals = others + [{"id": "g", "rank": rank, "hardness": hardness}]
    out = _run_classic_roundtrip(goals, "g")
    assert out["rank"] == rank
    assert out["hardness"] == hardness


def test_classic_edit_select_init_reads_hardness_not_rank():
    """Das konkrete Audit-Beispiel: Rang 2 / Hart. Der Select zeigt Hart
    ('1'), der Payload behaelt Rang 2 -- vorher wurde aus demselben Wert auch
    rank=1 gesendet."""
    if shutil.which("node") is None:
        pytest.skip("node binary not available to execute extracted JS")
    goals = [
        {"id": "g1", "rank": 1, "hardness": "Primär"},
        {"id": "g2", "rank": 2, "hardness": "Hart"},
        {"id": "g3", "rank": 3, "hardness": "Opportunistisch"},
    ]
    out = _run_classic_roundtrip(goals, "g2")
    assert out == {"prio": "1", "rank": 2, "hardness": "Hart"}


def test_classic_new_goal_is_appended_after_the_last_rank():
    """Neues Ziel: Rang = letzter Rang + 1, unabhaengig von der Haerte; ohne
    Ziele Rang 1. Umsortieren erfolgt danach per Drag (atomare Reihenfolge)."""
    if shutil.which("node") is None:
        pytest.skip("node binary not available to execute extracted JS")
    goals = [{"id": "g1", "rank": 1, "hardness": "Opportunistisch"}, {"id": "g2", "rank": 4, "hardness": "Hart"}]
    assert _run_classic_roundtrip(goals, None)["rank"] == 5
    assert _run_classic_roundtrip([], None)["rank"] == 1


# ---------------------------------------------------------------------------
# (b) Backend layer: a no-op edit that (due to bug (a)) resends rank=1 for
#     g2 must not silently drift g2's rank to 4 and its derived weight from
#     5000bps to 1250bps.
# ---------------------------------------------------------------------------


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
