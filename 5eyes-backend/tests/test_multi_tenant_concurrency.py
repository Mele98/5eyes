"""Roadmap #84: Last-/Concurrency-Test Multi-Tenant.

Ziel: parallele HTTP-Requests VERSCHIEDENER Tenant-User (echte JWTs, echter
Auth-Pfad ueber HTTPBearer -> get_current_user, KEIN dependency_override fuer
get_current_user) duerfen unter Last
  (a) NIEMALS Daten eines fremden Tenants zurueckgeben (Cross-Leak), und
  (b) NICHT an SQLite-'database is locked'-Fehlern scheitern.

Nur `get_db` wird ueberschrieben (auf eine tmp-SQLite-Datei mit denselben
Pragmas wie die echte App, s. database.build_connect_args /
attach_sqlite_pragmas: WAL + busy_timeout=5000 + check_same_thread=False).
Damit testen wir denselben Nebenlaeufigkeits-Pfad, den die App in
Produktion auch nutzt (kein staerker/schwaecher konfiguriertes Setup).

Threading via concurrent.futures.ThreadPoolExecutor gegen ein einzelnes
TestClient(app) (Starlette/httpx-ASGI-Transport). Jeder Request traegt sein
EIGENES Bearer-Token im Header -> Tenant-Zuordnung entsteht pro Request aus
dem JWT, nicht aus geteiltem State. Das ist die einzige Art, mit einem
FastAPI-TestClient echte Multi-User-Nebenlaeufigkeit zu simulieren (ein
globales app.dependency_overrides[get_current_user] koennte pro Request
immer nur EINEN User liefern und wuerde die Tenant-Trennung selbst nicht
mehr pruefen).
"""
from __future__ import annotations

import datetime
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, attach_sqlite_pragmas, build_connect_args, get_db  # noqa: E402
from main import app  # noqa: E402  (registriert alle Router + Models)
import models.allocation  # noqa: E402,F401
import models.client_login  # noqa: E402,F401
import models.clients  # noqa: E402,F401
import models.fx_rate  # noqa: E402,F401
import models.mandates  # noqa: E402,F401
import models.profiling  # noqa: E402,F401
import models.protocol_bausteine  # noqa: E402,F401
import models.review  # noqa: E402,F401
import models.snapshots  # noqa: E402,F401
import models.tax  # noqa: E402,F401
import models.tenant  # noqa: E402,F401
import models.users  # noqa: E402,F401
import models.wealth  # noqa: E402,F401
from models.clients import Client  # noqa: E402
from models.tenant import Tenant  # noqa: E402
from models.users import User  # noqa: E402
from services.auth import issue_token_for_user  # noqa: E402


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


def _make_tenant(tid: str) -> Tenant:
    """PRAGMA foreign_keys=ON (Produktions-Pragma, s. attach_sqlite_pragmas)
    erzwingt eine echte tenants-Zeile fuer jede User/Client.tenant_id -- im
    Gegensatz zu einigen aelteren Tenant-Isolation-Tests, die FKs nicht
    aktiviert haben und mit reinen String-tenant_id ohne Tenant-Zeile
    ausgekommen sind."""
    return Tenant(
        id=tid, display_name=tid, slug=tid.lower(),
        is_active=1, created_at=_now(), updated_at=_now(),
    )


@pytest.fixture
def session_factory(tmp_path):
    """Datei-basierte SQLite-DB mit denselben Pragmas wie database.py
    (WAL, busy_timeout=5000, check_same_thread=False) -> realistischer
    Nebenlaeufigkeits-Test statt eines staerker/schwaecher konfigurierten
    Test-Setups. WAL braucht eine echte Datei (keine :memory:), sonst
    verhaelt sich SQLite unter mehreren Verbindungen anders als in Produktion.
    """
    db_url = f"sqlite:///{tmp_path / 'concurrency.db'}"
    connect_args = build_connect_args(database_url=db_url)
    engine = create_engine(db_url, connect_args=connect_args, pool_timeout=30)
    attach_sqlite_pragmas(engine)
    sf = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield sf
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _make_user(uid: str, tenant_id: str, role: str = "advisor") -> User:
    return User(
        id=uid, username=uid, password_hash="h", full_name=uid,
        role=role, is_active=1, tenant_id=tenant_id,
        created_at=_now(), updated_at=_now(),
    )


def _make_client(cid: str, advisor_id: str, tenant_id: str) -> Client:
    return Client(
        id=cid, client_number=cid, first_name=cid, last_name="Test",
        advisor_id=advisor_id, tenant_id=tenant_id,
        household_type="Einzelperson", client_classification="Privatkunde",
        country_of_residence="CH", language="DE",
        created_at=_now(), updated_at=_now(),
    )


def _seed_two_tenants(db, clients_per_tenant: int):
    """Firma A (adv-a + N Clients) und Firma B (adv-b + N Clients), disjunkt."""
    tenant_a = _make_tenant("firm-A")
    tenant_b = _make_tenant("firm-B")
    user_a = _make_user("adv-a", "firm-A")
    user_b = _make_user("adv-b", "firm-B")
    clients_a = [_make_client(f"c-a-{i}", "adv-a", "firm-A") for i in range(clients_per_tenant)]
    clients_b = [_make_client(f"c-b-{i}", "adv-b", "firm-B") for i in range(clients_per_tenant)]
    db.add_all([tenant_a, tenant_b, user_a, user_b, *clients_a, *clients_b])
    db.commit()
    return user_a, user_b, {c.id for c in clients_a}, {c.id for c in clients_b}


def _build_test_client(session_factory) -> TestClient:
    """TestClient MIT get_db-Override, OHNE get_current_user-Override.
    Auth laeuft ueber echte Bearer-Token je Request (siehe Modul-Docstring)."""

    def override_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ===========================================================================
# 1. Parallele Reads: kein Cross-Tenant-Leak unter Last, keine DB-Lock-Fehler
# ===========================================================================


def test_concurrent_reads_no_cross_tenant_leak_and_no_db_locks(session_factory):
    """20 parallele GET /clients, verschraenkt zwischen Tenant A und Tenant B
    (je 10). Jede einzelne Response darf AUSSCHLIESSLICH Clients des
    anfragenden Tenants enthalten -- auch unter gleichzeitiger Last."""
    with session_factory() as db:
        user_a, user_b, ids_a, ids_b = _seed_two_tenants(db, clients_per_tenant=8)
    token_a = issue_token_for_user(user_a)
    token_b = issue_token_for_user(user_b)

    client = _build_test_client(session_factory)
    try:
        requests = []
        for _ in range(10):
            requests.append(("A", token_a, ids_a, ids_b))
            requests.append(("B", token_b, ids_b, ids_a))

        def _do_request(tag, token, own_ids, foreign_ids):
            resp = client.get("/clients", headers=_auth_headers(token))
            return tag, resp, own_ids, foreign_ids

        results = []
        errors = []
        with ThreadPoolExecutor(max_workers=16) as pool:
            futures = [pool.submit(_do_request, *r) for r in requests]
            for fut in as_completed(futures):
                try:
                    results.append(fut.result())
                except OperationalError as exc:  # pragma: no cover - Diagnose-Pfad
                    errors.append(str(exc))

        assert not errors, (
            "SQLite-Lock-Fehler unter parallelen Reads (sollte mit WAL + "
            f"busy_timeout nicht auftreten): {errors[:3]}"
        )
        assert len(results) == len(requests)

        for tag, resp, own_ids, foreign_ids in results:
            assert resp.status_code == 200, (
                f"{tag}: unerwarteter Status {resp.status_code}: {resp.text}"
            )
            returned_ids = {c["id"] for c in resp.json()}
            leaked = returned_ids & foreign_ids
            assert not leaked, f"{tag}: CROSS-TENANT-LEAK unter Last: {leaked}"
            assert returned_ids == own_ids, (
                f"{tag}: erwartete eigene Clients {own_ids}, erhalten {returned_ids}"
            )
    finally:
        app.dependency_overrides.clear()


def test_concurrent_reads_flaky_check_repeatable(session_factory):
    """Wiederholt denselben Last-Szenario 5x IN EINEM Testlauf (Flakiness-
    Haerte-Check zusaetzlich zu den 3 externen pytest-Wiederholungen des
    Auftrags): jede Iteration muss unabhaengig leak-frei sein."""
    with session_factory() as db:
        user_a, user_b, ids_a, ids_b = _seed_two_tenants(db, clients_per_tenant=5)
    token_a = issue_token_for_user(user_a)
    token_b = issue_token_for_user(user_b)

    client = _build_test_client(session_factory)
    try:
        for _iteration in range(5):
            requests = [("A", token_a, ids_a, ids_b)] * 6 + [("B", token_b, ids_b, ids_a)] * 6

            def _do_request(tag, token, own_ids, foreign_ids):
                resp = client.get("/clients", headers=_auth_headers(token))
                return tag, resp, own_ids, foreign_ids

            with ThreadPoolExecutor(max_workers=12) as pool:
                futures = [pool.submit(_do_request, *r) for r in requests]
                for fut in as_completed(futures):
                    tag, resp, own_ids, foreign_ids = fut.result()
                    assert resp.status_code == 200
                    returned_ids = {c["id"] for c in resp.json()}
                    assert not (returned_ids & foreign_ids), (
                        f"{tag}: Leak in Iteration {_iteration}: "
                        f"{returned_ids & foreign_ids}"
                    )
                    assert returned_ids == own_ids
    finally:
        app.dependency_overrides.clear()


# ===========================================================================
# 2. Parallele Writes: beide Tenants erfolgreich, keine Fehl-Zuordnung
# ===========================================================================


def test_concurrent_writes_isolated_per_tenant(session_factory):
    """8 parallele POST /clients/{id}/cashflows fuer Tenant A gegen 8 fuer
    Tenant B (verschraenkt). Erwartung:
    (a) alle 16 Requests liefern 201 (keine 500er durch DB-Locks),
    (b) am Ende hat jeder Client genau seine eigenen 8 Cashflows -- keiner
        landet beim falschen Client/Tenant,
    (c) ein Cross-Tenant-Leseversuch bleibt auch danach mit 404 geblockt."""
    with session_factory() as db:
        tenant_a = _make_tenant("firm-A")
        tenant_b = _make_tenant("firm-B")
        user_a = _make_user("adv-a-w", "firm-A")
        user_b = _make_user("adv-b-w", "firm-B")
        client_a = _make_client("c-a-w", "adv-a-w", "firm-A")
        client_b = _make_client("c-b-w", "adv-b-w", "firm-B")
        db.add_all([tenant_a, tenant_b, user_a, user_b, client_a, client_b])
        db.commit()
    token_a = issue_token_for_user(user_a)
    token_b = issue_token_for_user(user_b)

    client = _build_test_client(session_factory)
    n = 8
    try:
        def _create_cashflow(tag, token, client_id, idx):
            body = {
                "cashflow_type": "Income",
                "label": f"{tag}-cf-{idx}",
                "amount_rappen": 100_000 + idx,
                "currency": "CHF",
                "frequency": "jährlich",
                "nature": "wiederkehrend",
            }
            resp = client.post(
                f"/clients/{client_id}/cashflows",
                json=body,
                headers=_auth_headers(token),
            )
            return tag, resp

        tasks = []
        for i in range(n):
            tasks.append(("A", token_a, "c-a-w", i))
            tasks.append(("B", token_b, "c-b-w", i))

        results = []
        errors = []
        with ThreadPoolExecutor(max_workers=16) as pool:
            futures = [pool.submit(_create_cashflow, *t) for t in tasks]
            for fut in as_completed(futures):
                try:
                    results.append(fut.result())
                except OperationalError as exc:  # pragma: no cover - Diagnose-Pfad
                    errors.append(str(exc))

        if errors:
            pytest.fail(
                "SQLite 'database is locked'-Fehler unter parallelen Writes "
                "(mit WAL + busy_timeout=5000 wie in Produktion konfiguriert; "
                f"waere ein reales App-Verhaltensproblem, nicht Test-Artefakt): {errors[:3]}"
            )

        assert len(results) == len(tasks)
        for tag, resp in results:
            assert resp.status_code == 201, f"{tag}: {resp.status_code} {resp.text}"

        cf_a = client.get(
            "/clients/c-a-w/cashflows", headers=_auth_headers(token_a),
        ).json()
        cf_b = client.get(
            "/clients/c-b-w/cashflows", headers=_auth_headers(token_b),
        ).json()
        assert len(cf_a) == n, f"Tenant A: erwartet {n} Cashflows, hat {len(cf_a)}"
        assert len(cf_b) == n, f"Tenant B: erwartet {n} Cashflows, hat {len(cf_b)}"
        assert all(c["label"].startswith("A-") for c in cf_a), (
            "Tenant A hat Cashflows, die unter Last von Tenant B geschrieben wurden"
        )
        assert all(c["label"].startswith("B-") for c in cf_b), (
            "Tenant B hat Cashflows, die unter Last von Tenant A geschrieben wurden"
        )

        # Auch nach der parallelen Last bleibt der Tenant-Filter wirksam:
        cross_resp = client.get(
            "/clients/c-b-w/cashflows", headers=_auth_headers(token_a),
        )
        assert cross_resp.status_code == 404, (
            "LEAK: Tenant A konnte nach paralleler Last Cashflows von Tenant B lesen"
        )
    finally:
        app.dependency_overrides.clear()
