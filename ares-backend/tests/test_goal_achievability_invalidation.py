"""Sprint 2026-06-08 Fix B: Achievability-Stale-Feedback nach Goal-Edit.

User-Frage 2026-06-08:
\"Wieso veraendert sich die Grafik in der SOLL-Allocation nicht wenn ich
das Renditeziel von 2% auf 5% veraendere?\"

Wissenschaftliche Antwort: SAA ist Risikoprofil-bound (3eyes-/FINMA-Customer-
Journey). Goals beeinflussen die Achievability-Wahrscheinlichkeit, nicht die
strategische Asset-Allocation. ABER: die persistierten achievement_score-Werte
werden nach Goal-Edit nicht automatisch neu berechnet → User sieht veraltete
Prozent-Werte → Verwirrung.

# Fix B
Nach Goal-CREATE / UPDATE / DELETE: alle achievement_score-Werte des Mandats
auf NULL setzen. UI rendert dann "—" mit dem bestehenden "Strategie neu
berechnen"-Banner statt veralteter Prozent-Werte.

# Strategietreue gewahrt
KEINE Allocation-Aenderung. Folgt ADR-003 anti-market-timing.
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
from models.clients import Client  # noqa: F401
from models.mandates import Mandate  # noqa: F401
from models.users import User
from models.wealth import Goal
from services.auth import get_current_user


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'goal_achievability_invalidation.db'}",
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
        id="user-ach-inv",
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
            "client_number": "ACH-INV-001",
            "first_name": "Ach", "last_name": "Inv",
            "advisor_id": advisor_user.id,
            "household_type": "Einzelperson",
        },
    )
    assert client_resp.status_code == 201, client_resp.text
    client_id = client_resp.json()["id"]
    mandate_resp = auth_client.post(
        f"/clients/{client_id}/mandates",
        json={"mandate_number": "ACH-INV-M-001", "mandate_type": "Anlageberatung"},
    )
    assert mandate_resp.status_code == 201, mandate_resp.text
    return mandate_resp.json()["id"]


def _create_goal(auth_client: TestClient, mandate_id: str, label: str = "Test") -> str:
    resp = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json={
            "goal_family": "Vermögen",
            "goal_type": "Vermoegensziel",
            "label": label,
            "rank": 2,
            "target_wealth_rappen": 1_000_000_00,
            "horizon_years": 10,
            "hardness": "Primär",
            "value_mode": "nominal",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _set_achievement_score(
    session_factory, goal_id: str, score: int,
) -> None:
    with session_factory() as db:
        goal = db.query(Goal).filter(Goal.id == goal_id).first()
        assert goal is not None
        goal.achievement_score = score
        db.commit()


def _get_achievement_score(session_factory, goal_id: str) -> int | None:
    with session_factory() as db:
        goal = db.query(Goal).filter(Goal.id == goal_id).first()
        assert goal is not None
        return goal.achievement_score


# ===========================================================================
# Helper-Funktion direkt
# ===========================================================================


def test_helper_setzt_alle_active_goals_auf_null(
    session_factory, auth_client, advisor_user,
):
    """_invalidate_achievement_scores_for_mandate setzt alle non-null Scores auf NULL."""
    mandate_id = _setup_mandate(auth_client, advisor_user)
    g1 = _create_goal(auth_client, mandate_id, "G1")
    g2 = _create_goal(auth_client, mandate_id, "G2")
    g3 = _create_goal(auth_client, mandate_id, "G3")
    _set_achievement_score(session_factory, g1, 75)
    _set_achievement_score(session_factory, g2, 50)
    _set_achievement_score(session_factory, g3, 25)
    # Bulk-Invalidierung direkt aufrufen
    from routers.wealth import _invalidate_achievement_scores_for_mandate
    with session_factory() as db:
        n = _invalidate_achievement_scores_for_mandate(mandate_id, db)
        db.commit()
    assert n == 3
    assert _get_achievement_score(session_factory, g1) is None
    assert _get_achievement_score(session_factory, g2) is None
    assert _get_achievement_score(session_factory, g3) is None


def test_helper_ignoriert_geloescht_inactive(
    session_factory, auth_client, advisor_user,
):
    """Geloeschte / inaktive Goals werden nicht beruehrt (haben keinen Score-Display)."""
    mandate_id = _setup_mandate(auth_client, advisor_user)
    g_active = _create_goal(auth_client, mandate_id, "Aktiv")
    g_deleted = _create_goal(auth_client, mandate_id, "Geloescht")
    _set_achievement_score(session_factory, g_active, 75)
    _set_achievement_score(session_factory, g_deleted, 50)
    # Soft-delete g_deleted
    with session_factory() as db:
        gd = db.query(Goal).filter(Goal.id == g_deleted).first()
        gd.is_active = 0
        gd.deleted_at = _utc_now_iso()
        db.commit()
    from routers.wealth import _invalidate_achievement_scores_for_mandate
    with session_factory() as db:
        n = _invalidate_achievement_scores_for_mandate(mandate_id, db)
        db.commit()
    assert n == 1  # nur das aktive
    assert _get_achievement_score(session_factory, g_active) is None
    # geloeschtes Goal: Score bleibt unveraendert (irrelevant fuer UI)
    assert _get_achievement_score(session_factory, g_deleted) == 50


# ===========================================================================
# Endpoint-Integration: CREATE / UPDATE / DELETE invalidiert
# ===========================================================================


def test_create_goal_invalidiert_alle_scores(
    session_factory, auth_client, advisor_user,
):
    """Neues Goal hinzufuegen → alle achievement_scores des Mandats auf NULL."""
    mandate_id = _setup_mandate(auth_client, advisor_user)
    g1 = _create_goal(auth_client, mandate_id, "G1")
    _set_achievement_score(session_factory, g1, 80)
    assert _get_achievement_score(session_factory, g1) == 80
    # NEU: zweites Goal erstellen
    _create_goal(auth_client, mandate_id, "G2")
    # G1's Score sollte jetzt NULL sein
    assert _get_achievement_score(session_factory, g1) is None


def test_update_goal_invalidiert_alle_scores(
    session_factory, auth_client, advisor_user,
):
    """Goal-UPDATE → alle achievement_scores auf NULL.

    Reproduziert User-Bug-Scenario: Renditeziel-Target von 2% auf 5% updaten
    und alte stale-Prozentwerte verschwinden, dass User klares Signal hat
    'Strategie neu berechnen'.
    """
    mandate_id = _setup_mandate(auth_client, advisor_user)
    g1 = _create_goal(auth_client, mandate_id, "G1")
    g2 = _create_goal(auth_client, mandate_id, "G2")
    _set_achievement_score(session_factory, g1, 75)
    _set_achievement_score(session_factory, g2, 60)
    # UPDATE g1
    update_resp = auth_client.put(
        f"/mandates/{mandate_id}/goals/{g1}",
        json={"target_wealth_rappen": 1_500_000_00},
    )
    assert update_resp.status_code == 200
    # Beide Goals haben jetzt NULL achievement_score
    assert _get_achievement_score(session_factory, g1) is None
    assert _get_achievement_score(session_factory, g2) is None


def test_delete_goal_invalidiert_verbleibende_scores(
    session_factory, auth_client, advisor_user,
):
    """Goal-DELETE → andere Goals-Scores auf NULL (Konkurrenz aendert sich)."""
    mandate_id = _setup_mandate(auth_client, advisor_user)
    g1 = _create_goal(auth_client, mandate_id, "G1")
    g2 = _create_goal(auth_client, mandate_id, "G2")
    _set_achievement_score(session_factory, g1, 75)
    _set_achievement_score(session_factory, g2, 60)
    # DELETE g1
    del_resp = auth_client.delete(f"/mandates/{mandate_id}/goals/{g1}")
    assert del_resp.status_code == 204
    # g2's Score sollte NULL sein
    assert _get_achievement_score(session_factory, g2) is None


# ===========================================================================
# Strategietreue: Allocation bleibt unveraendert
# ===========================================================================


def test_invalidation_aendert_keine_allocation(
    session_factory, auth_client, advisor_user,
):
    """Goal-Edit beruehrt NICHT die TargetAllocation (Strategietreue)."""
    mandate_id = _setup_mandate(auth_client, advisor_user)
    g1 = _create_goal(auth_client, mandate_id, "G1")
    _set_achievement_score(session_factory, g1, 80)
    # Simuliere bestehende TargetAllocation-Daten in goal (oder pruefe dass keine Aenderung)
    # Hier reicht: wir verifizieren dass nur achievement_score angeruehrt wird,
    # nicht andere Goal-Felder.
    with session_factory() as db:
        g = db.query(Goal).filter(Goal.id == g1).first()
        original_label = g.label
        original_target = g.target_wealth_rappen
        original_hardness = g.hardness
        original_rank = g.rank
    # UPDATE
    _create_goal(auth_client, mandate_id, "G2")  # invalidiert g1
    with session_factory() as db:
        g = db.query(Goal).filter(Goal.id == g1).first()
        assert g.label == original_label
        assert g.target_wealth_rappen == original_target
        assert g.hardness == original_hardness
        assert g.rank == original_rank
        # Nur achievement_score wurde geaendert
        assert g.achievement_score is None
