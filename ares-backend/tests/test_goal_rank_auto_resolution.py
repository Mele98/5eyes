"""Sprint 2026-06-06 Fix: Goal-Rank-Conflict Auto-Resolution.

User-Bug-Report 2026-06-06: "Ich kann momentan kein neues Ziel erfassen und
ich habe ein bestehendes geloescht und konnte kein neues erfassen."

Root-Cause:
- Frontend mapped Haerte -> Rang (Hart=1, Primaer=2, Opp=3)
- Backend hatte Rang-Unique-Check -> 409 wenn schon belegt
- Folge: max 3 Goals erfassbar pro Mandat (eines pro Haerte-Klasse)

Fix (PR 2026-06-06): Backend loest Rang-Konflikte auto via _resolve_goal_rank_conflict
(append-at-end mit max+1). Haerte bleibt im hardness-Feld semantisch korrekt.
"""
from __future__ import annotations

import datetime
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
from models.clients import Client  # noqa: F401 — SQLAlchemy metadata
from models.mandates import Mandate  # noqa: F401
from models.users import User
from services.auth import get_current_user


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'goal_rank_auto_resolution.db'}",
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
        id="user-rank-fix",
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
            "client_number": "RANK-FIX-001",
            "first_name": "Rank",
            "last_name": "TestClient",
            "advisor_id": advisor_user.id,
            "household_type": "Einzelperson",
        },
    )
    assert client_resp.status_code == 201, client_resp.text
    client_id = client_resp.json()["id"]
    mandate_resp = auth_client.post(
        f"/clients/{client_id}/mandates",
        json={"mandate_number": "RANK-FIX-M-001", "mandate_type": "Anlageberatung"},
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
# Hauptbug: Mehrere Goals mit gleicher Haerte (= gleichem Rang vom Frontend)
# ---------------------------------------------------------------------------


def test_zwei_hart_goals_beide_erfassbar(auth_client, advisor_user):
    """Pre-Fix: 2. Hart-Goal warf 409. Post-Fix: beide gespeichert, 2. erhaelt
    auto-resolved rank."""
    mandate_id = _setup_mandate(auth_client, advisor_user)
    r1 = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json=_vermoegensziel_payload(1, "Hart", "Pension"),
    )
    assert r1.status_code == 201, r1.text
    assert r1.json()["rank"] == 1
    assert r1.json()["hardness"] == "Hart"

    r2 = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json=_vermoegensziel_payload(1, "Hart", "Eigenheim"),
    )
    assert r2.status_code == 201, r2.text
    # Haerte bleibt korrekt
    assert r2.json()["hardness"] == "Hart"
    # Rang wurde auto-shifted weg vom Konflikt
    assert r2.json()["rank"] != 1
    assert r2.json()["rank"] >= 2


def test_fuenf_goals_gleiche_haerte_alle_erfassbar(auth_client, advisor_user):
    """User-Report-Szenario: viele Goals der gleichen Haerte muessen erfassbar sein."""
    mandate_id = _setup_mandate(auth_client, advisor_user)
    ranks_received: list[int] = []
    for i, label in enumerate(["Pension", "Eigenheim", "Ferienhaus", "Studienreserve", "Erbschaft"]):
        r = auth_client.post(
            f"/mandates/{mandate_id}/goals",
            json=_vermoegensziel_payload(2, "Primär", label),
        )
        assert r.status_code == 201, f"Goal {i+1} ({label}) failed: {r.text}"
        ranks_received.append(int(r.json()["rank"]))
        assert r.json()["hardness"] == "Primär"
    # Alle Raenge eindeutig
    assert len(set(ranks_received)) == 5, f"Ranks not unique: {ranks_received}"


def test_haerte_bleibt_korrekt_nach_rank_shift(auth_client, advisor_user):
    """Auto-Rank-Shift darf NICHT die Haerte verfaelschen."""
    mandate_id = _setup_mandate(auth_client, advisor_user)
    auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json=_vermoegensziel_payload(2, "Primär", "Erstes"),
    )
    r = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json=_vermoegensziel_payload(2, "Opportunistisch", "Zweites"),
    )
    assert r.status_code == 201, r.text
    # Haerte des zweiten Goals bleibt Opportunistisch (nicht ueberschrieben)
    assert r.json()["hardness"] == "Opportunistisch"


# ---------------------------------------------------------------------------
# Edit-Flow: Update darf nicht in eigenen Rang kollidieren
# ---------------------------------------------------------------------------


def test_update_mit_gleichem_rank_kein_conflict(auth_client, advisor_user):
    """Goal kann seinen eigenen Rang beim Update beibehalten."""
    mandate_id = _setup_mandate(auth_client, advisor_user)
    create_resp = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json=_vermoegensziel_payload(2, "Primär", "Test"),
    )
    goal_id = create_resp.json()["id"]
    update_resp = auth_client.put(
        f"/mandates/{mandate_id}/goals/{goal_id}",
        json={"rank": 2, "label": "Test Updated"},
    )
    assert update_resp.status_code == 200, update_resp.text
    assert update_resp.json()["rank"] == 2
    assert update_resp.json()["label"] == "Test Updated"


def test_update_mit_belegtem_rank_auto_shifted(auth_client, advisor_user):
    """Update auf einen belegten Rang shiftet auto auf max+1."""
    mandate_id = _setup_mandate(auth_client, advisor_user)
    g1_resp = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json=_vermoegensziel_payload(1, "Hart", "Goal1"),
    )
    g2_resp = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json=_vermoegensziel_payload(2, "Primär", "Goal2"),
    )
    goal2_id = g2_resp.json()["id"]
    # G2 will to rank=1 — sollte auto-shiftet werden
    update_resp = auth_client.put(
        f"/mandates/{mandate_id}/goals/{goal2_id}",
        json={"rank": 1},
    )
    assert update_resp.status_code == 200, update_resp.text
    # G2 bekommt nicht den Rang 1 (belegt) sondern shifted
    assert update_resp.json()["rank"] != 1
    # G1 hat noch rank=1
    g1_check = auth_client.get(f"/mandates/{mandate_id}/goals")
    g1_data = next(g for g in g1_check.json() if g["id"] == g1_resp.json()["id"])
    assert g1_data["rank"] == 1


# ---------------------------------------------------------------------------
# Delete-Loeschung-Wieder-Erfassung (User-Report-Szenario)
# ---------------------------------------------------------------------------


def test_loeschen_und_neu_erfassen_kein_conflict(auth_client, advisor_user):
    """User-Report 2026-06-06: 'habe ein bestehendes geloescht und konnte kein
    neues erfassen'. Post-Fix: Loeschung + Neu-Erfassung muss klappen."""
    mandate_id = _setup_mandate(auth_client, advisor_user)
    create_resp = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json=_vermoegensziel_payload(2, "Primär", "Erstes"),
    )
    goal_id = create_resp.json()["id"]
    delete_resp = auth_client.delete(f"/mandates/{mandate_id}/goals/{goal_id}")
    assert delete_resp.status_code == 204
    # Neu erfassen mit gleichem Rang sollte gehen (geloeschtes blockt nicht)
    new_resp = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json=_vermoegensziel_payload(2, "Primär", "Neues"),
    )
    assert new_resp.status_code == 201, new_resp.text
    # Da das alte soft-deleted ist, kann das neue Rang 2 erhalten
    assert new_resp.json()["rank"] == 2


# ---------------------------------------------------------------------------
# Backwards-Compat: Freier Rang wird direkt verwendet
# ---------------------------------------------------------------------------


def test_freier_rang_wird_direkt_verwendet(auth_client, advisor_user):
    """Bei keinem Conflict bleibt der angefragte Rang. Wichtig fuer Reihenfolge
    der ersten Goals."""
    mandate_id = _setup_mandate(auth_client, advisor_user)
    r1 = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json=_vermoegensziel_payload(1, "Hart", "A"),
    )
    r2 = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json=_vermoegensziel_payload(2, "Primär", "B"),
    )
    r3 = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json=_vermoegensziel_payload(3, "Opportunistisch", "C"),
    )
    assert r1.json()["rank"] == 1
    assert r2.json()["rank"] == 2
    assert r3.json()["rank"] == 3


# ---------------------------------------------------------------------------
# Helper-Funktion direkt (unit-level)
# ---------------------------------------------------------------------------


def test_resolve_goal_rank_conflict_helper_returnt_requested_wenn_frei(session_factory):
    """Direkt-Test der Helper-Funktion: freier Rang wird zurueckgegeben."""
    from routers.wealth import _resolve_goal_rank_conflict
    with session_factory() as db:
        result = _resolve_goal_rank_conflict("non-existing-mandate", 5, db)
        assert result == 5


def test_resolve_goal_rank_conflict_helper_shifted_bei_conflict(
    session_factory, auth_client, advisor_user,
):
    """Wenn ein Goal mit Rang 1 existiert, gibt der Helper max+1 zurueck."""
    mandate_id = _setup_mandate(auth_client, advisor_user)
    auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json=_vermoegensziel_payload(1, "Hart", "X"),
    )
    auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json=_vermoegensziel_payload(2, "Primär", "Y"),
    )
    from routers.wealth import _resolve_goal_rank_conflict
    with session_factory() as db:
        # Conflict mit rank=1 → expected max+1
        result = _resolve_goal_rank_conflict(mandate_id, 1, db)
        assert result >= 3  # max(1,2) + 1
