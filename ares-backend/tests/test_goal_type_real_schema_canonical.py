"""RC-CH-1-F1 Befund 1: Ziel "Umbau Wohneigentum" lieferte 500 statt 201.

Ursache: ``GoalCreate`` akzeptiert ``goal_type="Vermoegensziel"`` (ASCII-
Schreibweise, so sendet sie der Walkthrough), der Router speicherte den Wert
aber unveraendert. Die CHECK-Constraints der Tabelle ``goals`` im echten
Schema (``ares_schema.sql``: Wertelisten-CHECK auf ``goal_type`` UND
Familien/Typ-Konsistenz-CHECK UND Pflichtfeld-CHECK) kennen nur die
Umlaut-Form ``Vermögensziel`` -> ``IntegrityError`` -> HTTP 500. Dieselbe
Luecke hatte ``hardness`` (``'Primaer'``/``'hart'`` passierten die Pydantic-
Pruefung, der CHECK kennt nur ``'Hart','Primär','Opportunistisch'``) und
``GoalUpdate`` (freie Strings fuer goal_family/goal_type/goal_scope/
value_mode/hardness).

``Base.metadata.create_all()`` kennt diese CHECKs nicht; deshalb laufen diese
Tests auf dem echten Desktop-Startpfad (``init_db`` mit Rohschema-Bootstrap).

Fix: Eingabe-Aliase werden an der API-Grenze auf genau den DB-Wert
kanonisiert (``core.goal_vocabulary.canonicalize_goal_payload``,
fuer GoalCreate und GoalUpdate gleich), unbekannte Werte sind 422 -- kein Schema-
Umbau, weil die Engine beide Schreibweisen ohnehin gleich behandelt.
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import database as db_module
from database import get_db, init_db
from main import app
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, tenant, users, wealth,
)
from models.users import User
from services.auth import get_current_user
from tests.risk_fixture_helpers import noop_lifespan

configure_mappers()


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path, monkeypatch):
    db_path = tmp_path / "goal_type_real_schema.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    db_module.attach_sqlite_pragmas(engine)
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module.settings, "db_bootstrap_schema_on_startup", True)
    init_db(engine)
    sf = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    try:
        yield sf
    finally:
        engine.dispose()


@pytest.fixture()
def advisor_user():
    return User(
        id="user-goal-type-real", username="advisor-goal-type-real", password_hash="h",
        full_name="Advisor", role="advisor", is_active=1,
        created_at=_now(), updated_at=_now(),
    )


@pytest.fixture()
def auth_client(session_factory, advisor_user, monkeypatch):
    with session_factory() as db:
        db.merge(advisor_user)
        db.commit()

    def override_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: advisor_user
    monkeypatch.setattr(app.router, "lifespan_context", noop_lifespan)
    # raise_server_exceptions=False: ein 500 soll als Status sichtbar sein,
    # nicht als Exception im Test (genau das ist der Befund).
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
    app.dependency_overrides.clear()


def _assert_real_goal_checks(session_factory) -> None:
    """Vorbedingung: ohne die Rohschema-CHECKs waere jeder Test gruen ohne Aussage."""
    with session_factory() as db:
        sql = db.execute(text(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='goals'"
        )).scalar()
    assert sql and "goal_type IN" in sql and "'Vermögensziel'" in sql
    assert "'Vermoegensziel'" not in sql, "Test setzt das echte (Umlaut-)Schema voraus"


def _mandate(client: TestClient, advisor: User) -> str:
    c = client.post("/clients", json={
        "client_number": "GOAL-TYPE-REAL-001", "first_name": "Thierry", "last_name": "Test",
        "advisor_id": advisor.id, "household_type": "Einzelperson",
    })
    assert c.status_code == 201, c.text
    m = client.post(f"/clients/{c.json()['id']}/mandates", json={
        "mandate_number": "GOAL-TYPE-REAL-M-001", "mandate_type": "Anlageberatung",
    })
    assert m.status_code == 201, m.text
    return m.json()["id"]


def _stored(session_factory, goal_id: str) -> tuple[str, str, str]:
    with session_factory() as db:
        row = db.execute(text(
            "SELECT goal_family, goal_type, hardness FROM goals WHERE id = :id"
        ), {"id": goal_id}).one()
    return tuple(row)


UMBAU = {
    "goal_family": "Vermögen", "goal_type": "Vermoegensziel",
    "label": "Umbau Wohneigentum", "rank": 1,
    "target_wealth_rappen": 250_000_00, "horizon_years": 6,
    "hardness": "Hart", "value_mode": "nominal",
}


def test_umbau_wohneigentum_ascii_goal_type_is_saved_canonically(session_factory, auth_client, advisor_user):
    _assert_real_goal_checks(session_factory)
    mid = _mandate(auth_client, advisor_user)
    r = auth_client.post(f"/mandates/{mid}/goals", json=UMBAU)
    assert r.status_code == 201, r.text
    assert r.json()["goal_type"] == "Vermögensziel"
    assert _stored(session_factory, r.json()["id"]) == ("Vermögen", "Vermögensziel", "Hart")


@pytest.mark.parametrize("raw, canonical", [
    ("Primaer", "Primär"), ("primär", "Primär"), ("hart", "Hart"),
    ("OPPORTUNISTISCH", "Opportunistisch"),
])
def test_hardness_aliases_are_saved_canonically(session_factory, auth_client, advisor_user, raw, canonical):
    mid = _mandate(auth_client, advisor_user)
    body = dict(UMBAU, goal_type="Vermögensziel", hardness=raw)
    r = auth_client.post(f"/mandates/{mid}/goals", json=body)
    assert r.status_code == 201, r.text
    assert r.json()["hardness"] == canonical
    assert _stored(session_factory, r.json()["id"])[2] == canonical


def test_update_with_ascii_alias_and_hardness_alias_is_saved_canonically(session_factory, auth_client, advisor_user):
    mid = _mandate(auth_client, advisor_user)
    created = auth_client.post(f"/mandates/{mid}/goals", json=dict(
        UMBAU, goal_type="Kapitalerhalt",
    ))
    assert created.status_code == 201, created.text
    gid = created.json()["id"]
    r = auth_client.put(f"/mandates/{mid}/goals/{gid}", json={
        "goal_type": "Vermoegensziel", "hardness": "Primaer", "goal_family": "Vermoegen",
    })
    assert r.status_code == 200, r.text
    assert _stored(session_factory, gid) == ("Vermögen", "Vermögensziel", "Primär")


@pytest.mark.parametrize("field, value", [
    ("goal_type", "Quatsch"),
    ("goal_family", "Immobilien"),
    ("goal_scope", "Teilvermögen"),
    ("value_mode", "inflationiert"),
    ("hardness", "weich"),
])
def test_update_rejects_values_outside_the_db_domain_with_422(session_factory, auth_client, advisor_user, field, value):
    mid = _mandate(auth_client, advisor_user)
    created = auth_client.post(f"/mandates/{mid}/goals", json=dict(UMBAU, goal_type="Vermögensziel"))
    gid = created.json()["id"]
    r = auth_client.put(f"/mandates/{mid}/goals/{gid}", json={field: value})
    assert r.status_code == 422, (r.status_code, r.text)
    # N-903-04 (geschaerft): die Ablehnung kommt jetzt aus GoalUpdate selbst
    # (Pydantic-Fehlerliste mit Feldnamen). An fb83c8e7 lehnten -- wenn
    # ueberhaupt -- Router-Pruefungen mit Freitext ab bzw. erst die DB.
    detail = r.json()["detail"]
    assert isinstance(detail, list), detail
    assert field in detail[0]["msg"], detail


def test_update_family_type_mismatch_is_422_not_500(session_factory, auth_client, advisor_user):
    """goal_family + goal_type einer anderen Familie im selben Update: GoalUpdate
    lehnt mit Feldbezug ab (an fb83c8e7 lehnte erst eine Router-Pruefung ab)."""
    mid = _mandate(auth_client, advisor_user)
    created = auth_client.post(f"/mandates/{mid}/goals", json=dict(UMBAU, goal_type="Vermögensziel"))
    gid = created.json()["id"]
    r = auth_client.put(f"/mandates/{mid}/goals/{gid}", json={"goal_type": "Maximierung", "goal_family": "Vermögen"})
    assert r.status_code == 422, (r.status_code, r.text)
    # N-903-04 (geschaerft): Familie/Typ-Konsistenz prueft GoalUpdate selbst.
    detail = r.json()["detail"]
    assert isinstance(detail, list) and "goal_family" in detail[0]["msg"], detail
    assert _stored(session_factory, gid)[1] == "Vermögensziel"


@pytest.mark.parametrize("raw, canonical", [
    ("Gesamtvermoegen", "Gesamtvermögen"), ("Beratungsvermoegen", "Beratungsvermögen"),
])
def test_update_goal_scope_alias_is_saved_canonically(session_factory, auth_client, advisor_user, raw, canonical):
    mid = _mandate(auth_client, advisor_user)
    created = auth_client.post(f"/mandates/{mid}/goals", json=dict(UMBAU, goal_type="Vermögensziel"))
    gid = created.json()["id"]
    r = auth_client.put(f"/mandates/{mid}/goals/{gid}", json={"goal_scope": raw})
    assert r.status_code == 200, r.text
    with session_factory() as db:
        stored = db.execute(text("SELECT goal_scope FROM goals WHERE id = :id"), {"id": gid}).scalar()
    assert stored == canonical
