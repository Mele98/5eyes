"""N-865-1 (Pruefrunde #865): Ziel-Umsortierung auf dem ECHTEN Schema.

``ares_schema.sql`` legt den partiellen Unique-Index
``ux_goals_rank_active ON goals(mandate_id, rank) WHERE is_active = 1 AND
deleted_at IS NULL`` an. ``PUT /mandates/{id}/goals/order`` schrieb die neuen
Raenge Zeile fuer Zeile; SQLite prueft den Index nach JEDER Zeile. Sobald zwei
Ziele ihre Raenge tauschen (z.B. 1..3 -> [3,1,2]), kollidiert das erste
UPDATE mit dem noch unveraenderten Nachbarn -> IntegrityError -> HTTP 500.

``tests/test_goal_reorder_atomic_endpoint.py`` merkte das nicht, weil
``Base.metadata.create_all()`` diesen Index nicht kennt. Diese Tests
bootstrappen deshalb die Datenbank wie die Desktop-App aus dem Rohschema.

Fix: Zwei-Phasen-Update in derselben Transaktion (Zwischenraenge oberhalb
aller belegten Raenge, flush, dann Zielraenge). Mitgeprueft:

* Audit: genau ein ``goals``/``UPDATE`` je tatsaechlich verschobenem Ziel,
  keine Spur der Zwischenraenge; Ketten-Pruefung nur, wenn der Fix aus #865
  (Audit-Vorgaenger aus pending Objekten) enthalten ist.
* Ungueltige Permutationen bleiben 422 ohne Schreibzugriff.
* Geschwister-Pfad: Reaktivieren eines Ziels, dessen Rang inzwischen ein
  aktives Ziel belegt, lief in denselben Index (500) -- jetzt ans Ende.
"""
from __future__ import annotations

import datetime
import itertools
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
from models.review import AuditLog
from models.users import User
from services import audit as audit_service
from services.auth import get_current_user
from tests.risk_fixture_helpers import noop_lifespan

configure_mappers()

# #865 (r5/audit-chain-flush) liest den Audit-Vorgaenger aus den pending
# Objekten der Session. Ohne diesen Fix bricht JEDE Transaktion mit mehreren
# log()-Aufrufen die Kette -- unabhaengig von diesem Befund.
AUDIT_CHAIN_MULTI_ENTRY_FIXED = hasattr(audit_service, "_pending_audit_entry")


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path, monkeypatch):
    """Der echte Desktop-Startpfad: init_db() faehrt bootstrap_sqlite_schema()
    (Rohschema MIT ux_goals_rank_active) plus Wartung/Stammdaten -- nicht
    Base.metadata.create_all(), das den Index nicht kennt."""
    db_path = tmp_path / "goal_reorder_real_schema.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    # Wie die App-Engine: WAL, busy_timeout, foreign_keys (Nebenlaeufigkeit).
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
        id="user-goal-reorder-real", username="advisor-reorder-real", password_hash="h",
        full_name="Advisor", role="advisor", is_active=1,
        created_at=_now(), updated_at=_now(),
    )


@pytest.fixture()
def auth_client(session_factory, advisor_user, monkeypatch):
    # foreign_keys=ON (App-Pragmas): der Berater muss als Zeile existieren.
    with session_factory() as db:
        db.merge(advisor_user)
        db.commit()

    def override_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: advisor_user
    monkeypatch.setattr(app.router, "lifespan_context", noop_lifespan)
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def _assert_real_index(session_factory) -> None:
    """Vorbedingung: ohne den Index waere jeder Test hier gruen ohne Aussage."""
    with session_factory() as db:
        sql = db.execute(text(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name='ux_goals_rank_active'"
        )).scalar()
    assert sql and "UNIQUE" in sql.upper(), "ux_goals_rank_active fehlt im Test-Schema"


def _mandate_with_goals(client: TestClient, advisor: User, n: int = 3) -> tuple[str, list[str]]:
    c = client.post("/clients", json={
        "client_number": "REORDER-REAL-001", "first_name": "Re", "last_name": "Order",
        "advisor_id": advisor.id, "household_type": "Einzelperson",
    })
    assert c.status_code == 201, c.text
    m = client.post(f"/clients/{c.json()['id']}/mandates", json={
        "mandate_number": "REORDER-REAL-M-001", "mandate_type": "Anlageberatung",
    })
    assert m.status_code == 201, m.text
    mid = m.json()["id"]
    ids = []
    hardness = ("Primär", "Hart", "Opportunistisch")
    for rank in range(1, n + 1):
        g = client.post(f"/mandates/{mid}/goals", json={
            "goal_family": "Vermögen", "goal_type": "Vermögensziel",
            "label": f"g{rank}", "rank": rank, "target_wealth_rappen": 100_000_00,
            "horizon_years": 10, "hardness": hardness[(rank - 1) % 3], "value_mode": "nominal",
        })
        assert g.status_code == 201, g.text
        assert g.json()["rank"] == rank
        ids.append(g.json()["id"])
    return mid, ids


def _ranks(client: TestClient, mid: str) -> dict[str, int]:
    return {g["id"]: g["rank"] for g in client.get(f"/mandates/{mid}/goals").json()
            if g["is_active"]}


def _goal_updates(session_factory, ids) -> list[str]:
    with session_factory() as db:
        rows = db.query(AuditLog).filter(
            AuditLog.table_name == "goals", AuditLog.action == "UPDATE",
            AuditLog.record_id.in_(list(ids)),
        ).all()
        return sorted(str(r.record_id) for r in rows)


@pytest.mark.parametrize(
    "perm",
    [p for p in itertools.permutations(range(3)) if p != (0, 1, 2)],
    ids=lambda p: "".join(str(i + 1) for i in p),
)
def test_reorder_any_permutation_on_real_schema(auth_client, advisor_user, session_factory, perm):
    _assert_real_index(session_factory)
    mid, ids = _mandate_with_goals(auth_client, advisor_user)
    order = [ids[i] for i in perm]
    r = auth_client.put(f"/mandates/{mid}/goals/order", json={
        "goal_ids": order, "expected_goal_ids": ids,
    })
    assert r.status_code == 200, r.text
    assert [g["id"] for g in r.json()] == order
    assert _ranks(auth_client, mid) == {gid: i + 1 for i, gid in enumerate(order)}
    # Audit: genau ein UPDATE je tatsaechlich verschobenem Ziel.
    moved = sorted(gid for i, gid in enumerate(order) if ids.index(gid) != i)
    assert _goal_updates(session_factory, ids) == moved


def test_reorder_finding_example_312_and_back(auth_client, advisor_user, session_factory):
    """Exakt das Befund-Beispiel: 1..3 -> [3,1,2], danach zurueck auf 1..3."""
    _assert_real_index(session_factory)
    mid, (g1, g2, g3) = _mandate_with_goals(auth_client, advisor_user)
    r = auth_client.put(f"/mandates/{mid}/goals/order", json={"goal_ids": [g3, g1, g2]})
    assert r.status_code == 200, r.text
    assert _ranks(auth_client, mid) == {g3: 1, g1: 2, g2: 3}
    back = auth_client.put(f"/mandates/{mid}/goals/order", json={
        "goal_ids": [g1, g2, g3], "expected_goal_ids": [g3, g1, g2],
    })
    assert back.status_code == 200, back.text
    assert _ranks(auth_client, mid) == {g1: 1, g2: 2, g3: 3}
    assert _goal_updates(session_factory, [g1, g2, g3]) == sorted([g1, g1, g2, g2, g3, g3])


def test_reorder_compacts_gaps_and_ignores_inactive_goal_rank(auth_client, advisor_user, session_factory):
    """Lueckenhafte Raenge (1,2,7) plus ein deaktiviertes Ziel: die neue
    Folge ist lueckenlos 1..n, das inaktive Ziel bleibt unberuehrt."""
    _assert_real_index(session_factory)
    mid, (g1, g2, g3, g4) = _mandate_with_goals(auth_client, advisor_user, n=4)
    assert auth_client.put(f"/mandates/{mid}/goals/{g3}", json={"rank": 7}).status_code == 200
    off = auth_client.put(f"/mandates/{mid}/goals/{g4}", json={"is_active": False})
    assert off.status_code == 200, off.text
    r = auth_client.put(f"/mandates/{mid}/goals/order", json={"goal_ids": [g3, g2, g1]})
    assert r.status_code == 200, r.text
    assert _ranks(auth_client, mid) == {g3: 1, g2: 2, g1: 3}
    inactive = [g for g in auth_client.get(f"/mandates/{mid}/goals").json() if g["id"] == g4]
    if inactive:  # Liste kann inaktive Ziele ausblenden
        assert inactive[0]["rank"] == 4


@pytest.mark.parametrize("bad", ["duplicate", "missing", "unknown"])
def test_invalid_permutation_still_422_on_real_schema(auth_client, advisor_user, session_factory, bad):
    _assert_real_index(session_factory)
    mid, (g1, g2, g3) = _mandate_with_goals(auth_client, advisor_user)
    goal_ids = {
        "duplicate": [g3, g3, g1, g2],
        "missing": [g3, g1],
        "unknown": [g3, g1, g2, "fremd"],
    }[bad]
    r = auth_client.put(f"/mandates/{mid}/goals/order", json={"goal_ids": goal_ids})
    assert r.status_code == 422, r.text
    assert _ranks(auth_client, mid) == {g1: 1, g2: 2, g3: 3}
    assert _goal_updates(session_factory, [g1, g2, g3]) == []


@pytest.mark.skipif(
    not AUDIT_CHAIN_MULTI_ENTRY_FIXED,
    reason="Kettenpruefung erst mit #865 (r5/audit-chain-flush) aussagekraeftig",
)
def test_reorder_keeps_audit_chain_intact(auth_client, advisor_user, session_factory):
    mid, (g1, g2, g3) = _mandate_with_goals(auth_client, advisor_user)
    r = auth_client.put(f"/mandates/{mid}/goals/order", json={"goal_ids": [g3, g1, g2]})
    assert r.status_code == 200, r.text
    with session_factory() as db:
        result = audit_service.verify_audit_chain(db)
    assert result["ok"] is True, result


def test_reactivating_goal_with_occupied_rank_appends_instead_of_500(
    auth_client, advisor_user, session_factory,
):
    """Geschwister-Pfad derselben Index-Klasse: Ziel g3 (Rang 3) wird
    deaktiviert, ein neues Ziel bekommt den freien Rang 3, dann wird g3
    reaktiviert. Vorher: IntegrityError -> 500. Jetzt: g3 ans Ende (Rang 4),
    wie ein neu angelegtes Ziel mit belegtem Wunschrang."""
    _assert_real_index(session_factory)
    mid, (g1, g2, g3) = _mandate_with_goals(auth_client, advisor_user)
    off = auth_client.put(f"/mandates/{mid}/goals/{g3}", json={"is_active": False})
    assert off.status_code == 200, off.text
    new = auth_client.post(f"/mandates/{mid}/goals", json={
        "goal_family": "Vermögen", "goal_type": "Vermögensziel",
        "label": "neu", "rank": 3, "target_wealth_rappen": 100_000_00,
        "horizon_years": 10, "hardness": "Primär", "value_mode": "nominal",
    })
    assert new.status_code == 201, new.text
    assert new.json()["rank"] == 3
    on = auth_client.put(f"/mandates/{mid}/goals/{g3}", json={"is_active": True})
    assert on.status_code == 200, on.text
    assert on.json()["rank"] == 4
    assert _ranks(auth_client, mid) == {g1: 1, g2: 2, new.json()["id"]: 3, g3: 4}


def test_reactivating_goal_with_free_rank_keeps_it(auth_client, advisor_user, session_factory):
    _assert_real_index(session_factory)
    mid, (g1, g2, g3) = _mandate_with_goals(auth_client, advisor_user)
    assert auth_client.put(f"/mandates/{mid}/goals/{g2}", json={"is_active": False}).status_code == 200
    on = auth_client.put(f"/mandates/{mid}/goals/{g2}", json={"is_active": True})
    assert on.status_code == 200, on.text
    assert on.json()["rank"] == 2
