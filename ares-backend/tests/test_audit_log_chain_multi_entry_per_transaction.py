"""N-862-1 (Pruefrunde #862): Hash-Kette bei mehreren Audit-Eintraegen pro
Transaktion.

Befund: ``database.SessionLocal`` laeuft mit ``autoflush=False``. log() suchte
den Vorgaenger (``sequence - 1``) per DB-Abfrage; ein in DERSELBEN
Transaktion zuvor geloggter, noch ungeflushter Eintrag lag nur in den
pending objects der Session und wurde nicht gefunden -> previous_hash = "" ->
verify_audit_chain meldete "Kette gebrochen" fuer jede Transaktion mit zwei
oder mehr Eintraegen.

Die bestehenden SEC-003-Tests (test_sec003_audit_log_hash_chain_sequence.py)
liefen mit ``autoflush=True`` -- dort flusht die Vorgaenger-Abfrage selbst,
der Defekt war dadurch unsichtbar. Hier deshalb durchgehend die
Produktionskonfiguration ``autoflush=False``.

Abgedeckt:
* mehrere log() in einer Transaktion (Service-Ebene), gemischt mit Flush;
* Rollback nach Teil-Logs (ganze Transaktion und Savepoint): keine Luecke,
  kein Bruch;
* echte Nebenlaeufigkeit (Threads, eigene Engines) mit mehreren Eintraegen
  je Transaktion;
* je real betroffenem Endpunkt-Typ aus dem Inventar ein Endpunkt-Test:
  Schleife (PUT /fx-rates mehrere Waehrungen, PUT goals/order,
  Depot-Check-Evidenzzeilen), Log + Service-Helfer (POST risk-assessments mit
  Plausibilitaets-Befund), mehrere bedingte Logs (Override eines bereits
  unterschriebenen Risikoprofils).
"""
from __future__ import annotations

import datetime
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import database as db_module
from database import (
    Base,
    bootstrap_sqlite_schema,
    ensure_audit_log_actions,
    ensure_audit_log_triggers,
    ensure_runtime_columns,
    get_db,
)
from models import allocation, clients, mandates, profiling, review, snapshots, tenant, users, wealth  # noqa: F401
import models.client_login  # noqa: F401
import models.fx_rate  # noqa: F401
from models.review import AuditLog
from models.users import User
from services.audit import log, verify_audit_chain

SCHEMA_PATH = BACKEND_ROOT / "ares_schema.sql"


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


def _log(session, record_id: str, action: str = "UPDATE") -> None:
    # tenant_id explizit -> keine users-Abfrage noetig (reine Ketten-Ebene).
    log(session, user_id="u1", user_name="A", table_name="t", record_id=record_id,
        action=action, tenant_id="tenant-1")


def _prod_engine(db_path: Path):
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(engine, "connect")
    def _pragma(dbapi_connection, _record):
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA busy_timeout = 5000")
        cur.execute("PRAGMA journal_mode = WAL")
        cur.close()

    return engine


@pytest.fixture()
def chain_db(tmp_path, monkeypatch):
    """Vollstaendig gebootete SQLite-DB (Rohschema + Laufzeitspalten +
    Unveraenderlichkeits-Trigger) mit der PRODUKTIONS-Session-Konfiguration."""
    db_path = tmp_path / "chain.db"
    bootstrap_sqlite_schema(db_path=str(db_path), schema_path=str(SCHEMA_PATH))
    engine = _prod_engine(db_path)
    monkeypatch.setattr(db_module, "engine", engine)
    ensure_runtime_columns()
    ensure_audit_log_actions(engine)
    ensure_audit_log_triggers(engine)
    Base.metadata.create_all(bind=engine)
    session_local = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    try:
        yield db_path, session_local
    finally:
        engine.dispose()


def _assert_chain(session_local, expected_count: int | None = None) -> list[AuditLog]:
    with session_local() as s:
        result = verify_audit_chain(s)
        assert result["ok"] is True, result["errors"]
        rows = s.query(AuditLog).filter(AuditLog.sequence.isnot(None)).order_by(AuditLog.sequence).all()
        assert [r.sequence for r in rows] == list(range(1, len(rows) + 1))
        for prev, cur in zip(rows, rows[1:]):
            assert cur.previous_hash == prev.integrity_hash
        if expected_count is not None:
            assert len(rows) == expected_count
        return rows


# ---------------------------------------------------------------------------
# Service-Ebene
# ---------------------------------------------------------------------------


def test_two_log_calls_without_flush_keep_the_chain(chain_db):
    """Minimalprobe des Pruefers: zwei log() ohne Flush dazwischen."""
    _path, session_local = chain_db
    with session_local() as s:
        _log(s, "1", "CREATE")
        _log(s, "2")
        s.commit()
    _assert_chain(session_local, expected_count=2)


def test_many_log_calls_in_one_transaction_mixed_with_flush(chain_db):
    _path, session_local = chain_db
    with session_local() as s:
        _log(s, "pre")
        s.commit()
        _log(s, "a")
        _log(s, "b")
        s.flush()
        _log(s, "c")
        _log(s, "d")
        _log(s, "e")
        s.commit()
    rows = _assert_chain(session_local, expected_count=6)
    assert [r.record_id for r in rows] == ["pre", "a", "b", "c", "d", "e"]


def test_rollback_after_partial_logs_leaves_no_gap_and_no_break(chain_db):
    _path, session_local = chain_db
    with session_local() as s:
        _log(s, "kept-1")
        s.commit()
        _log(s, "lost-1")
        _log(s, "lost-2")
        s.rollback()
        _log(s, "kept-2")
        _log(s, "kept-3")
        s.commit()
    rows = _assert_chain(session_local, expected_count=3)
    assert [r.record_id for r in rows] == ["kept-1", "kept-2", "kept-3"]


def test_savepoint_rollback_after_partial_logs_leaves_no_gap_and_no_break(chain_db):
    _path, session_local = chain_db
    with session_local() as s:
        _log(s, "outer-1")
        nested = s.begin_nested()
        _log(s, "inner-lost-1")
        _log(s, "inner-lost-2")
        nested.rollback()
        _log(s, "outer-2")
        _log(s, "outer-2b")
        with s.begin_nested():
            _log(s, "inner-kept")
        _log(s, "outer-3")
        s.commit()
    rows = _assert_chain(session_local, expected_count=5)
    assert [r.record_id for r in rows] == ["outer-1", "outer-2", "outer-2b", "inner-kept", "outer-3"]


def test_concurrent_transactions_with_several_entries_each_form_one_linear_chain(chain_db):
    """Nebenlaeufigkeit: vier Threads mit EIGENER Engine (eigene Verbindungen)
    gegen dieselbe Datei, je drei Eintraege pro Transaktion. Der Zaehler-UPDATE
    haelt den SQLite-Schreib-Lock bis zum Commit; die Kette muss linear und
    lueckenlos sein, die Eintraege jeder Transaktion zusammenhaengend."""
    db_path, session_local = chain_db
    workers = 4
    per_tx = 3
    barrier = threading.Barrier(workers)
    errors: list[Exception] = []

    def _worker(idx: int) -> None:
        engine = _prod_engine(db_path)
        sl = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
        try:
            with sl() as s:
                barrier.wait(timeout=10)
                for n in range(per_tx):
                    _log(s, f"w{idx}-{n}")
                s.commit()
        except Exception as exc:  # noqa: BLE001 -- im Haupt-Thread pruefen
            errors.append(exc)
        finally:
            engine.dispose()

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not errors, errors
    rows = _assert_chain(session_local, expected_count=workers * per_tx)
    for start in range(0, len(rows), per_tx):
        block = {r.record_id.split("-")[0] for r in rows[start:start + per_tx]}
        assert len(block) == 1, f"Transaktionen verschraenkt: {[r.record_id for r in rows]}"


# ---------------------------------------------------------------------------
# Endpunkt-Ebene (je real betroffenem Typ aus dem Inventar)
# ---------------------------------------------------------------------------


@pytest.fixture()
def api(chain_db):
    from main import app
    from services.auth import get_current_user
    from tests.risk_fixture_helpers import noop_lifespan

    _path, session_local = chain_db
    advisor = User(
        id="advisor-chain", username="advisor-chain", password_hash="h",
        full_name="Chain Advisor", role="advisor", is_active=1,
        created_at=_now(), updated_at=_now(),
    )
    with session_local() as s:
        s.add(User(
            id=advisor.id, username=advisor.username, password_hash="h",
            full_name=advisor.full_name, role="advisor", is_active=1,
            created_at=_now(), updated_at=_now(),
        ))
        s.commit()

    def override_db():
        with session_local() as s:
            yield s

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: advisor
    original_lifespan = app.router.lifespan_context
    app.router.lifespan_context = noop_lifespan
    try:
        with TestClient(app) as client:
            yield client, advisor, session_local
    finally:
        app.router.lifespan_context = original_lifespan
        app.dependency_overrides.clear()


def _audit_count(session_local) -> int:
    with session_local() as s:
        return s.query(AuditLog).filter(AuditLog.sequence.isnot(None)).count()


def _client_and_mandate(client, advisor, suffix: str) -> tuple[str, str]:
    c = client.post("/clients", json={
        "client_number": f"CHAIN-{suffix}", "first_name": "Ket", "last_name": "Te",
        "advisor_id": advisor.id, "household_type": "Einzelperson",
    })
    assert c.status_code == 201, c.text
    m = client.post(f"/clients/{c.json()['id']}/mandates", json={
        "mandate_number": f"CHAIN-M-{suffix}", "mandate_type": "Anlageberatung",
    })
    assert m.status_code == 201, m.text
    return c.json()["id"], m.json()["id"]


def test_endpoint_loop_fx_upsert_several_currencies(api):
    client, _advisor, session_local = api
    before = _audit_count(session_local)
    r = client.put("/fx-rates", json={"rates": [
        {"currency": "usd", "rate": 0.9, "source": "Manual"},
        {"currency": "eur", "rate": 0.95, "source": "Manual"},
        {"currency": "gbp", "rate": 1.1, "source": "Manual"},
    ]})
    assert r.status_code == 200, r.text
    assert _audit_count(session_local) - before == 3
    _assert_chain(session_local)


def test_endpoint_loop_goal_reorder(api):
    client, advisor, session_local = api
    _cid, mid = _client_and_mandate(client, advisor, "REORDER")
    ids = []
    # Startraenge 4..6: das Rohschema hat ux_goals_rank_active (mandate_id,
    # rank) -- die neue Reihenfolge 1..3 kollidiert so mit keinem Altrang
    # (Permutationen derselben Raenge siehe Nebenbefund im PR-Text).
    for rank, hardness in ((4, "Primär"), (5, "Hart"), (6, "Opportunistisch")):
        g = client.post(f"/mandates/{mid}/goals", json={
            "goal_family": "Vermögen", "goal_type": "Vermögensziel",
            "label": f"g{rank}", "rank": rank, "target_wealth_rappen": 100_000_00,
            "horizon_years": 10, "hardness": hardness, "value_mode": "nominal",
        })
        assert g.status_code == 201, g.text
        ids.append(g.json()["id"])
    before = _audit_count(session_local)
    r = client.put(f"/mandates/{mid}/goals/order", json={
        "goal_ids": [ids[2], ids[0], ids[1]], "expected_goal_ids": ids,
    })
    assert r.status_code == 200, r.text
    assert _audit_count(session_local) - before >= 2
    _assert_chain(session_local)


def test_endpoint_log_plus_service_helper_risk_assessment_create(api):
    """POST risk-assessments schreibt den CREATE-Eintrag und -- ohne
    Vermoegens-/Cashflowdaten ist die Risikofaehigkeit nicht pruefbar -- den
    Plausibilitaets-Befund (audit_if_inconsistent) in DERSELBEN Transaktion."""
    from tests.risk_fixture_helpers import standard_risk_payload

    client, advisor, session_local = api
    _cid, mid = _client_and_mandate(client, advisor, "RA")
    before = _audit_count(session_local)
    r = client.post(f"/mandates/{mid}/risk-assessments", json=standard_risk_payload())
    assert r.status_code == 201, r.text
    assert _audit_count(session_local) - before >= 2
    _assert_chain(session_local)


def test_endpoint_conditional_logs_override_of_signed_risk_profile(api):
    """Override eines bereits unterschriebenen Profils: Override-Eintrag +
    Signatur-Invalidierung in einer Transaktion."""
    from models.profiling import RiskAssessment
    from tests.risk_fixture_helpers import standard_risk_payload

    client, advisor, session_local = api
    _cid, mid = _client_and_mandate(client, advisor, "OVR")
    ra = client.post(f"/mandates/{mid}/risk-assessments", json=standard_risk_payload())
    assert ra.status_code == 201, ra.text
    ra_id = ra.json()["id"]
    with session_local() as s:
        row = s.get(RiskAssessment, ra_id)
        row.client_signed_at = _now()
        s.commit()
    before = _audit_count(session_local)
    r = client.post(f"/mandates/{mid}/risk-assessments/{ra_id}/override", json={
        "override_score_x10": 70,
        "override_profile": "Wachstumsorientiert",
        "override_reason": (
            "Kunde wuenscht ausdruecklich erhoehte Risikobereitschaft "
            "wegen langem Anlagehorizont und solider Liquiditaetsreserve."
        ),
    })
    assert r.status_code == 200, r.text
    with session_local() as s:
        fields = [
            e.field_name for e in s.query(AuditLog)
            .filter(AuditLog.sequence > before).order_by(AuditLog.sequence).all()
        ]
    assert "override" in fields and "client_signed_invalidated" in fields, fields
    _assert_chain(session_local)


def test_depot_check_evidence_rows_logged_in_one_transaction(chain_db):
    """GET depotcheck-PDF loggt je neu angelegter Evidenzzeile (Snapshot +
    Analyse) einen Eintrag in einer Schleife und committet danach einmal."""
    from routers.pdf_reports import _log_depot_check_rows

    _path, session_local = chain_db
    request = SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1"))
    user = SimpleNamespace(id="u1", full_name="A")
    mandate = SimpleNamespace(id="m1", client_id="c1")
    with session_local() as s:
        _log_depot_check_rows(s, request, mandate, user, [
            ("depot_snapshots", "snap-1", "h1"),
            ("depot_check_analysis_snapshots", "ana-1", "h2"),
        ])
        s.commit()
    _assert_chain(session_local, expected_count=2)
