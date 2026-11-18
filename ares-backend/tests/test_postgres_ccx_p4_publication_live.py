"""CCX-P4 Publikationsentscheide und Active-Pointer live auf PostgreSQL unter
FORCE RLS.

Echte Migrationskette bis Head in ein Wegwerf-Schema, Boot-RLS-Plan, Probe als
NON-owner/NON-superuser/NOBYPASSRLS-Rolle mit zwei Mandanten:

* RLS ENABLE + FORCE und Policy fuer beide Tabellen; SELECT nur im eigenen
  Mandanten, ohne Kontext nichts;
* INSERT-Guard: gespoofter Mandant und fremdes Mandat werden abgelehnt;
* publizierbarer Entscheid nur fuer einen SEALED+FRESH Envelope desselben
  Mandats mit gleichem Hash; Sequenz lueckenlos (``CCX_PUBLICATION_RACE``);
* Entscheide append-only, Pointer nie geloescht, nur vorwaerts mit Version+1
  (App-Rolle UND Owner), UPSERT ueberschreibt nichts;
* zwei echte parallele Publisher (zwei Transaktionen, gleiche Sequenz):
  genau ein Sieger;
* N-910-04: echtes ``publish_allocation`` gegen eine Invalidierung unter
  derselben Mandatssperre (zwei Transaktionen): gewinnt die Invalidierung,
  lautet der Code ``CCX_INPUT_STALE``; gewinnt die Publikation, wartet die
  Invalidierung bis zum Commit und macht den Envelope danach STALE;
* N-910-06: Soll-Allokation (FK, Mandat) und Freigeber/Ersteller (Mandant)
  sind DB-seitig gebunden;
* upgrade -> downgrade (vor CCX-P4) -> upgrade.

Ohne ``POSTGRES_TEST_DATABASE_URL`` uebersprungen (CI-Job ``postgres-rls``).
"""
from __future__ import annotations

import threading
import uuid

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from tests.test_postgres_ccx_p2_invalidation_live import _fresh_envelope, _mark_stale
from tests.test_postgres_mandate_evidence_tenant_boundary_live import (  # noqa: F401
    POSTGRES_URL,
    _alembic_cfg,
    _mandate,
    _qi,
    _scoped_url,
    pytestmark,
)
from tests.test_tenant_database_boundary import _raw_insert

DECISIONS = "allocation_publication_decisions"
POINTER = "allocation_active_publications"
TABLES = (DECISIONS, POINTER)
CCX_P3_REV = "6814c14575e9"
NOW = "2026-11-14T00:00:00.000000Z"
H = "d" * 64


# Benutzer je Mandant (N-910-06: Freigeber/Ersteller aus demselben Mandanten).
ADVISOR = {"t-a": "adv", "t-b": "adv-b"}
MANDATES = {"m-a": ("c-a", "t-a"), "m-b": ("c-b", "t-b"), "m-r": ("c-r", "t-a"), "m-s": ("c-s", "t-a"),
            "m-t": ("c-t", "t-a")}


def _target_allocation(conn, mandate_id):
    """Minimale Soll-Allokation (alle Pflichtspalten aus dem ORM)."""
    from sqlalchemy import Integer

    from models.allocation import TargetAllocation

    values = {}
    for column in TargetAllocation.__table__.columns:
        if column.nullable and column.name not in ("created_at", "updated_at"):
            continue
        if column.name == "id":
            values["id"] = f"ta-{mandate_id}"
        elif column.name == "mandate_id":
            values["mandate_id"] = mandate_id
        elif column.name == "policy_id":
            values["policy_id"] = "op-p4"
        elif column.name in ("set_by", "approved_by"):
            values[column.name] = ADVISOR[MANDATES[mandate_id][1]]
        elif column.name in ("created_at", "updated_at", "generated_at"):
            values[column.name] = NOW
        elif isinstance(column.type, Integer):
            values[column.name] = 10_000 if column.name in ("target_liquidity_bps",) or column.name.endswith(
                "_max_bps") else (1 if column.name in ("version", "is_current") else 0)
        else:
            values[column.name] = "x"
    conn.execute(text(
        f"INSERT INTO target_allocations ({', '.join(values)}) VALUES ({', '.join(':' + k for k in values)})"
    ), values)


def _decision(conn, row_id, mandate_id, tenant_id, sequence, *, envelope_id=None, envelope_hash=None,
              publishable=1):
    actor = ADVISOR.get(tenant_id, "adv")
    values = {"id": row_id, "tenant_id": tenant_id, "mandate_id": mandate_id,
              "schema_version": "ares/allocation-publication/1", "envelope_id": envelope_id,
              "target_allocation_id": f"ta-{mandate_id}" if publishable else None, "publication_sequence": sequence,
              "validation_hash": H, "approval_hash": H if publishable else None,
              "approval_mode": "four_eyes" if publishable else None, "approved_at": NOW if publishable else None,
              "approved_by": actor if publishable else None, "publishable": publishable,
              "blocker_codes_json": "[]" if publishable else '["CCX_ENVELOPE_MISSING"]',
              "published_envelope_hash": envelope_hash if publishable else None,
              "eligible_approver_count": 2 if publishable else None, "single_person_firm": 0 if publishable else None,
              "created_at": NOW, "created_by": actor}
    conn.execute(text(
        f"INSERT INTO {DECISIONS} ({', '.join(values)}) VALUES ({', '.join(':' + k for k in values)})"
    ), values)


def _pointer(conn, row_id, mandate_id, tenant_id, publication_id, version=1):
    conn.execute(text(
        f"INSERT INTO {POINTER} (id, tenant_id, mandate_id, publication_id, optimistic_version, updated_at, "
        "updated_by) VALUES (:id, :t, :m, :p, :v, :now, 'adv')"
    ), {"id": row_id, "t": tenant_id, "m": mandate_id, "p": publication_id, "v": version, "now": NOW})


@pytest.fixture(scope="module")
def pg_p4():
    pytest.importorskip("psycopg")
    from alembic import command

    from services.postgres_rls import ensure_postgres_rls_policies
    from services.tenant_context import attach_tenant_context_reset

    token = uuid.uuid4().hex[:12]
    schema, role, password = f"ccxp4_{token}", f"ccxp4_app_{token}", f"pw_{token}"
    admin = create_engine(POSTGRES_URL, future=True)
    with admin.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA {_qi(schema)}"))
    scoped = _scoped_url(POSTGRES_URL, schema)
    owner = create_engine(scoped, future=True)
    app = None
    try:
        command.upgrade(_alembic_cfg(scoped), "head")
        with owner.begin() as conn:
            for tid in ("t-a", "t-b"):
                _raw_insert(conn, "tenants", id=tid, display_name=tid, slug=tid)
            _raw_insert(conn, "users", id="adv", tenant_id="t-a")
            _raw_insert(conn, "users", id="adv-b", username="adv-b", tenant_id="t-b")
            _raw_insert(conn, "users", id="adv2", username="adv2", tenant_id="t-a")
            conn.execute(text(
                "INSERT INTO optimizer_policies (id, policy_name, version, is_current, valid_from, optimizer_engine, "
                "max_real_estate_bps, max_alternatives_bps, min_liquidity_bps, allow_other_assets_for_goals, "
                "created_by, created_at, updated_at) VALUES ('op-p4', 'P4', 1, 1, '2026-01-01', 'goal_based_v1', "
                "10000, 10000, 0, 0, 'adv', :n, :n)"
            ), {"n": NOW})
            for mid, (cid, tid) in MANDATES.items():
                _raw_insert(conn, "clients", id=cid, client_number=cid, tenant_id=tid)
                _mandate(conn, mid, cid, tid)
                _target_allocation(conn, mid)
            _fresh_envelope(conn, "e-a", "m-a", "t-a", "c-a", "1" * 64)
            _fresh_envelope(conn, "e-b", "m-b", "t-b", "c-b", "2" * 64)
            _fresh_envelope(conn, "e-r", "m-r", "t-a", "c-r", "3" * 64)
            _fresh_envelope(conn, "e-s", "m-s", "t-a", "c-s", "4" * 64)
            _fresh_envelope(conn, "e-t", "m-t", "t-a", "c-t", "5" * 64)
            _decision(conn, "d-a1", "m-a", "t-a", 1, envelope_id="e-a", envelope_hash="1" * 64)
            _pointer(conn, "p-a", "m-a", "t-a", "d-a1")
            _decision(conn, "d-b1", "m-b", "t-b", 1, envelope_id="e-b", envelope_hash="2" * 64)
            _pointer(conn, "p-b", "m-b", "t-b", "d-b1")
            ensure_postgres_rls_policies(conn)
            conn.execute(text(
                f"CREATE ROLE {_qi(role)} LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD '{password}'"
            ))
            conn.execute(text(f"GRANT USAGE ON SCHEMA {_qi(schema)} TO {_qi(role)}"))
            conn.execute(text(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {_qi(schema)} TO {_qi(role)}"
            ))
        app_url = make_url(scoped).set(username=role, password=password).render_as_string(hide_password=False)
        app = create_engine(app_url, future=True, pool_size=4, max_overflow=0)
        attach_tenant_context_reset(app)
        yield {"app": app, "owner": owner, "schema": schema, "url": scoped}
    finally:
        if app is not None:
            app.dispose()
        owner.dispose()
        with admin.begin() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {_qi(schema)} CASCADE"))
            conn.execute(text(f"DROP ROLE IF EXISTS {_qi(role)}"))
        admin.dispose()


def _rollback(db):
    from services.audit import restore_tenant_after_rollback
    from services.tenant_context import set_tenant_context

    restore_tenant_after_rollback(db, set_tenant_context)


def _session(ctx, tenant):
    from services.tenant_context import set_tenant_context

    session = sessionmaker(bind=ctx["app"])()
    set_tenant_context(session, tenant)
    return session


def test_force_rls_and_policies(pg_p4):
    from services.postgres_rls import tenant_scoped_table_names, tenant_tables_missing_rls_policies

    assert set(TABLES) <= set(tenant_scoped_table_names())
    with pg_p4["owner"].connect() as conn:
        assert tenant_tables_missing_rls_policies(conn, table_names=TABLES, schema=pg_p4["schema"]) == []
        for table in TABLES:
            forced = conn.execute(text(
                "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class c JOIN pg_namespace n "
                "ON n.oid = c.relnamespace WHERE n.nspname = :s AND c.relname = :t"
            ), {"s": pg_p4["schema"], "t": table}).scalar()
            assert forced is True, table


def test_select_is_tenant_bound(pg_p4):
    with _session(pg_p4, "t-a") as db:
        assert {r[0] for r in db.execute(text(f"SELECT id FROM {DECISIONS}"))} >= {"d-a1"}
        assert "d-b1" not in {r[0] for r in db.execute(text(f"SELECT id FROM {DECISIONS}"))}
        assert "p-b" not in {r[0] for r in db.execute(text(f"SELECT id FROM {POINTER}"))}
    with _session(pg_p4, None) as db:
        for table in TABLES:
            assert db.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 0


@pytest.mark.parametrize("variant", [
    {"mandate_id": "m-a", "tenant_id": "t-b"},   # gespoofter Mandant
    {"mandate_id": "m-b", "tenant_id": "t-a"},   # fremdes Mandat (unter RLS unsichtbar)
])
def test_foreign_tenant_cannot_write_decision(pg_p4, variant):
    with _session(pg_p4, "t-a") as db:
        with pytest.raises(DBAPIError):
            _decision(db.connection(), "x-dec", sequence=2, publishable=0, **variant)
        _rollback(db)


def test_publishable_requires_sealed_fresh_envelope_with_same_hash_and_contiguous_sequence(pg_p4):
    with _session(pg_p4, "t-a") as db:
        with pytest.raises(DBAPIError, match="CCX_ALLOCATION_NOT_PUBLISHABLE"):
            _decision(db.connection(), "x-hash", "m-r", "t-a", 1, envelope_id="e-r", envelope_hash="9" * 64)
        _rollback(db)
        with pytest.raises(DBAPIError, match="CCX_PUBLICATION_RACE"):
            _decision(db.connection(), "x-gap", "m-r", "t-a", 3, envelope_id="e-r", envelope_hash="3" * 64)
        _rollback(db)
        with pytest.raises(DBAPIError, match="CCX_PUBLICATION_RACE"):
            _decision(db.connection(), "x-blocked", "m-r", "t-a", 1, publishable=0)
            _pointer(db.connection(), "x-ptr", "m-r", "t-a", "x-blocked")
        _rollback(db)


@pytest.mark.parametrize("engine_key", ["app", "owner"])
@pytest.mark.parametrize("statement", [
    f"UPDATE {DECISIONS} SET validation_hash = '{'e' * 64}'",
    f"DELETE FROM {DECISIONS}",
    f"DELETE FROM {POINTER}",
    f"UPDATE {POINTER} SET optimistic_version = optimistic_version + 5",
    f"UPDATE {POINTER} SET optimistic_version = optimistic_version + 1",  # gleiche Publikation, nicht vorwaerts
])
def test_decisions_append_only_and_pointer_only_forward(pg_p4, engine_key, statement):
    from services.tenant_context import set_tenant_context

    session = sessionmaker(bind=pg_p4[engine_key])()
    try:
        set_tenant_context(session, "t-a")
        with pytest.raises(DBAPIError):
            session.execute(text(statement + " WHERE tenant_id = 't-a' AND mandate_id = 'm-a'"))
            session.flush()
    finally:
        session.rollback()
        session.close()


@pytest.mark.parametrize("table,assign", [
    (DECISIONS, "validation_hash = EXCLUDED.validation_hash"),
    (POINTER, "optimistic_version = 99"),
])
def test_upsert_cannot_overwrite(pg_p4, table, assign):
    from services.tenant_context import set_tenant_context

    for engine_key in ("app", "owner"):
        session = sessionmaker(bind=pg_p4[engine_key])()
        try:
            set_tenant_context(session, "t-a")
            with pytest.raises(DBAPIError):
                session.execute(text(
                    f"INSERT INTO {table} SELECT * FROM {table} WHERE tenant_id = 't-a' AND mandate_id = 'm-a' "
                    f"ON CONFLICT (id) DO UPDATE SET {assign}"
                ))
                session.flush()
        finally:
            session.rollback()
            session.close()


def test_two_parallel_publishers_have_exactly_one_winner(pg_p4):
    """Zwei echte Transaktionen publizieren denselben Envelope mit derselben
    gelesenen Sequenz: die zweite wartet am Unique-Index und scheitert nach dem
    Commit der ersten (Sequenz/Unique/one_per_envelope)."""
    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def publish(tag):
        with _session(pg_p4, "t-a") as db:
            try:
                barrier.wait(timeout=10)
                _decision(db.connection(), f"race-{tag}", "m-r", "t-a", 1, envelope_id="e-r",
                          envelope_hash="3" * 64)
                db.commit()
                outcomes.append("won")
            except DBAPIError:
                db.rollback()
                outcomes.append("lost")

    threads = [threading.Thread(target=publish, args=(tag,)) for tag in ("x", "y")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert sorted(outcomes) == ["lost", "won"]
    with _session(pg_p4, "t-a") as db:
        assert db.execute(text(
            f"SELECT count(*) FROM {DECISIONS} WHERE mandate_id = 'm-r' AND publishable = 1")).scalar() == 1


def test_binding_guard_target_allocation_and_actor_tenant(pg_p4):
    """N-910-06 (PG): Soll-Allokation eines anderen Mandats bzw. unbekannt,
    Ersteller aus einem fremden Mandanten -> abgelehnt."""
    insert = (f"INSERT INTO {DECISIONS} (id, tenant_id, mandate_id, schema_version, target_allocation_id, "
              "publication_sequence, validation_hash, publishable, blocker_codes_json, created_at, created_by) "
              "VALUES (:id, 't-a', 'm-r', 'ares/allocation-publication/1', :ta, 1, :h, 0, '[\"X\"]', :now, :cb)")
    for case in ({"ta": "ta-m-a", "cb": "adv"}, {"ta": "gibt-es-nicht", "cb": "adv"}, {"ta": None, "cb": "adv-b"}):
        with pg_p4["owner"].connect() as conn:
            with pytest.raises(DBAPIError):
                conn.execute(text(insert), {"id": "g6", "h": H, "now": NOW, **case})
            conn.rollback()


class _Mandate:
    def __init__(self, mandate_id, tenant_id="t-a"):
        self.id = mandate_id
        self.tenant_id = tenant_id
        self.client_id = MANDATES[mandate_id][0]


def _patched_gate(monkeypatch, mandate_id, envelope_id, envelope_hash, *, after_lock=None):
    """Echtes ``publish_allocation`` (Sperre, Insert, Pointer, Fehler-Mapping);
    ersetzt sind nur die Pruefung (SQLite-belegt; hier ein vor der Sperre
    gelesener, bestandener Stand), der Freigabemodus und der HMAC (Schluessel)."""
    import services.allocation_publication_gate as gate
    from services.allocation_publication_approval import ApprovalBasis

    def evaluation(db, mandate, collect_drift=None):
        if after_lock is not None:
            after_lock()
        return gate.PublicationEvaluation(
            tenant_id="t-a", mandate_id=mandate_id, target_allocation_id=f"ta-{mandate_id}",
            envelope_id=envelope_id, envelope_hash=envelope_hash, sealed_by="adv", blockers=(),
            validation_hash="7" * 64, record={"active_publication": None},
        )

    monkeypatch.setattr(gate, "evaluate_allocation_publication", evaluation)
    monkeypatch.setattr(gate, "approval_basis", lambda db, **kw: ApprovalBasis("four_eyes", 2, 0))
    monkeypatch.setattr(gate, "approval_hash_for", lambda db, **kw: "f" * 64)
    monkeypatch.setattr(gate, "log", lambda *a, **k: None)
    return gate


def test_publish_vs_invalidation_invalidation_wins_is_input_stale(pg_p4, monkeypatch):
    """N-910-04: die Invalidierung haelt die Mandatssperre und macht den
    Envelope STALE; ``publish_allocation`` wartet an derselben Sperre und
    verliert danach am Insert-Trigger -- Code CCX_INPUT_STALE (nicht
    CCX_PUBLICATION_RACE), kein Pointer."""
    from core.reason_codes import DomainError
    from types import SimpleNamespace

    gate = _patched_gate(monkeypatch, "m-s", "e-s", "4" * 64)
    locked = threading.Event()
    outcome = {}

    with _session(pg_p4, "t-a") as invalidator:
        invalidator.execute(text("SELECT id FROM mandates WHERE id = 'm-s' FOR UPDATE"))
        assert _mark_stale(invalidator.connection(), "e-s") == 1
        locked.set()

        def publish():
            with _session(pg_p4, "t-a") as db:
                try:
                    gate.publish_allocation(db, _Mandate("m-s"), user=SimpleNamespace(id="adv2", full_name="A2"),
                                            expected_validation_hash="7" * 64, expected_target_allocation_id="ta-m-s")
                    outcome["result"] = "published"
                except DomainError as exc:
                    outcome["result"] = exc.reason_code

        thread = threading.Thread(target=publish)
        locked.wait(5)
        thread.start()
        thread.join(timeout=2)
        assert thread.is_alive(), "publish_allocation muss an der Mandatssperre warten"
        invalidator.commit()
    thread.join(timeout=60)
    assert outcome["result"] == "CCX_INPUT_STALE"
    with _session(pg_p4, "t-a") as db:
        assert db.execute(text(f"SELECT count(*) FROM {POINTER} WHERE mandate_id = 'm-s'")).scalar() == 0
        assert db.execute(text(
            f"SELECT count(*) FROM {DECISIONS} WHERE mandate_id = 'm-s' AND publishable = 1")).scalar() == 0


def test_publish_vs_invalidation_publish_wins_then_invalidation_follows(pg_p4, monkeypatch):
    """N-910-04: haelt die Publikation die Sperre, wartet die Invalidierung
    bis zum Commit; danach ist der Envelope STALE (die Publikation gilt beim
    naechsten tiefen Lesen nicht mehr)."""
    from types import SimpleNamespace

    started = threading.Event()
    release = threading.Event()

    def after_lock():
        started.set()
        release.wait(10)

    gate = _patched_gate(monkeypatch, "m-t", "e-t", "5" * 64, after_lock=after_lock)
    order = []
    seen = {}

    def publish():
        with _session(pg_p4, "t-a") as db:
            gate.publish_allocation(db, _Mandate("m-t"), user=SimpleNamespace(id="adv2", full_name="A2"),
                                    expected_validation_hash="7" * 64, expected_target_allocation_id="ta-m-t")
            order.append("published")

    def invalidate():
        with _session(pg_p4, "t-a") as db:
            db.execute(text("SELECT id FROM mandates WHERE id = 'm-t' FOR UPDATE"))
            # Beim Erhalt der Sperre ist die Publikation bereits committet.
            seen["published_rows_at_lock"] = db.execute(text(
                f"SELECT count(*) FROM {DECISIONS} WHERE mandate_id = 'm-t' AND publishable = 1")).scalar()
            _mark_stale(db.connection(), "e-t")
            db.commit()

    publisher = threading.Thread(target=publish)
    publisher.start()
    assert started.wait(10)
    invalidator = threading.Thread(target=invalidate)
    invalidator.start()
    invalidator.join(timeout=2)
    assert invalidator.is_alive(), "die Invalidierung muss an der Mandatssperre warten"
    release.set()
    publisher.join(timeout=60)
    invalidator.join(timeout=60)
    assert order == ["published"]
    assert seen["published_rows_at_lock"] == 1
    with _session(pg_p4, "t-a") as db:
        assert db.execute(text(f"SELECT count(*) FROM {POINTER} WHERE mandate_id = 'm-t'")).scalar() == 1
        assert db.execute(text(
            "SELECT freshness_status FROM advisory_decision_envelopes WHERE id = 'e-t'")).scalar() == "STALE"


def test_upgrade_downgrade_upgrade(pg_p4):
    from alembic import command

    url = pg_p4["url"]
    command.downgrade(_alembic_cfg(url), CCX_P3_REV)
    engine = create_engine(url, future=True)
    try:
        insp = inspect(engine)
        assert not set(TABLES) & set(insp.get_table_names())
    finally:
        engine.dispose()
    command.upgrade(_alembic_cfg(url), "head")
    engine = create_engine(url, future=True)
    try:
        assert set(TABLES) <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
