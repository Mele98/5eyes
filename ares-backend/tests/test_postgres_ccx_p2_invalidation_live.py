"""CCX-P2 Invalidation und Staleness live auf PostgreSQL unter FORCE RLS.

Echte Migrationskette bis Head in ein Wegwerf-Schema, Boot-RLS-Plan, Probe als
NON-owner/NON-superuser/NOBYPASSRLS-Rolle mit zwei Mandanten:

* RLS ENABLE + FORCE und Policy fuer Kanten und Ereignisse; SELECT nur im
  eigenen Mandanten;
* Trigger: FRESH nur mit Kanten, nie zurueck auf FRESH, Ereignis nur fuer einen
  STALE-Envelope, lueckenlose Sequenz (CCX_INVALIDATION_RACE), append-only auch
  fuer den Tabellen-Owner und ueber ON CONFLICT DO UPDATE, Mandant gebunden;
* zentraler Mutation Hook (ORM-Session) invalidiert im selben Commit;
* Race-Suite mit echten Transaktionen: Mutation waehrend der Versiegelung
  wartet auf die Mandatssperre und invalidiert danach; Versiegelung waehrend
  einer Mutation wartet; parallele Mutationen erhalten eindeutige,
  lueckenlose ``invalidation_sequence``;
* upgrade -> downgrade (auf CCX-P1) -> upgrade.

Ohne ``POSTGRES_TEST_DATABASE_URL`` uebersprungen (CI-Job ``postgres-rls``).
"""
from __future__ import annotations

import threading
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from tests.test_postgres_ccx_p1_envelopes_live import _bind, _draft, _manifest
from tests.test_postgres_mandate_evidence_tenant_boundary_live import (  # noqa: F401
    POSTGRES_URL,
    _alembic_cfg,
    _mandate,
    _qi,
    _scoped_url,
    pytestmark,
)
from tests.test_tenant_database_boundary import _raw_insert

ENVELOPES = "advisory_decision_envelopes"
EDGES = "advisory_dependency_edges"
EVENTS = "advisory_invalidation_events"
CCX_P1_REV = "2c62f9012c73"
NOW = "2026-11-14T00:00:00.000000Z"
H = "a" * 64


def _edge(conn, envelope_id, tenant_id, kind="client", object_id="c-a"):
    conn.execute(text(
        f"INSERT INTO {EDGES} (id, tenant_id, envelope_id, dependency_kind, dependency_object_id, "
        "dependency_hash, observed_at, created_by) VALUES (:id, :t, :e, :k, :o, :h, :now, 'adv')"
    ), {"id": f"d-{envelope_id}-{kind}", "t": tenant_id, "e": envelope_id, "k": kind, "o": object_id,
        "h": H, "now": NOW})


def _seal(conn, envelope_id, digest, freshness="FRESH"):
    return conn.execute(text(
        f"UPDATE {ENVELOPES} SET status = 'SEALED', canonical_payload_json = '{{}}', envelope_hash = :h, "
        "sealed_at = :now, sealed_by = 'adv', freshness_status = :f, "
        "optimistic_version = optimistic_version + 1 WHERE id = :id AND status = 'DRAFT'"
    ), {"id": envelope_id, "h": digest, "now": NOW, "f": freshness}).rowcount


def _fresh_envelope(conn, envelope_id, mandate_id, tenant_id, client_id, digest):
    _manifest(conn, f"man-{envelope_id}", mandate_id, tenant_id=tenant_id)
    _draft(conn, envelope_id, mandate_id, tenant_id=tenant_id)
    _bind(conn, f"b-{envelope_id}", envelope_id, tenant_id)
    _edge(conn, envelope_id, tenant_id, "client", client_id)
    assert _seal(conn, envelope_id, digest) == 1


def _event(conn, event_id, envelope_id, mandate_id, tenant_id, sequence):
    conn.execute(text(
        f"INSERT INTO {EVENTS} (id, tenant_id, mandate_id, envelope_id, source_kind, source_object_id, "
        "reason_code, invalidation_sequence, created_at, created_by) VALUES "
        "(:id, :t, :m, :e, 'goals', 'g', 'CCX_INPUT_STALE', :seq, :now, 'adv')"
    ), {"id": event_id, "t": tenant_id, "m": mandate_id, "e": envelope_id, "seq": sequence, "now": NOW})


def _mark_stale(conn, envelope_id):
    return conn.execute(text(
        f"UPDATE {ENVELOPES} SET freshness_status = 'STALE', stale_at = :now, "
        "stale_reason_code = 'CCX_INPUT_STALE', optimistic_version = optimistic_version + 1 WHERE id = :e"
    ), {"e": envelope_id, "now": NOW}).rowcount


CLIENTS = {
    "c-a": "t-a", "c-b": "t-b", "c-hook": "t-a", "c-r1": "t-a", "c-r2": "t-a", "c-r3": "t-a", "c-trig": "t-a",
    "c-r4": "t-a",
}


@pytest.fixture(scope="module")
def pg_p2():
    pytest.importorskip("psycopg")
    from alembic import command

    from services.postgres_rls import ensure_postgres_rls_policies
    from services.tenant_context import attach_tenant_context_reset

    token = uuid.uuid4().hex[:12]
    schema, role, password = f"ccxp2_{token}", f"ccxp2_app_{token}", f"pw_{token}"
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
            for cid, tid in CLIENTS.items():
                _raw_insert(conn, "clients", id=cid, client_number=cid, tenant_id=tid)
                _mandate(conn, "m" + cid[1:], cid, tid)
            _fresh_envelope(conn, "e-a", "m-a", "t-a", "c-a", "1" * 64)
            _fresh_envelope(conn, "e-b", "m-b", "t-b", "c-b", "2" * 64)
            _fresh_envelope(conn, "e-hook", "m-hook", "t-a", "c-hook", "3" * 64)
            _fresh_envelope(conn, "e-r3", "m-r3", "t-a", "c-r3", "6" * 64)
            _fresh_envelope(conn, "e-trig", "m-trig", "t-a", "c-trig", "7" * 64)
            # Mandanteneigene CMA-Zeile fuer den Wettlauf CMA-Aenderung <-> Siegel.
            conn.execute(text(
                "INSERT INTO capital_market_assumptions (id, tenant_id, valid_from, is_current, created_by, "
                "created_at, updated_at) VALUES ('cma-race', 't-a', '2026-01-01', 1, 'adv', :n, :n)"
            ), {"n": NOW})
            ensure_postgres_rls_policies(conn)
            conn.execute(text(
                f"CREATE ROLE {_qi(role)} LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD '{password}'"
            ))
            conn.execute(text(f"GRANT USAGE ON SCHEMA {_qi(schema)} TO {_qi(role)}"))
            conn.execute(text(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {_qi(schema)} TO {_qi(role)}"
            ))
            conn.execute(text(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {_qi(schema)} TO {_qi(role)}"))
        app_url = make_url(scoped).set(username=role, password=password).render_as_string(hide_password=False)
        app = create_engine(app_url, future=True, pool_size=4, max_overflow=0)
        attach_tenant_context_reset(app)
        yield {"app": app, "owner": owner, "schema": schema}
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
    session.info["ares_actor_user_id"] = "adv"
    return session


def _state(ctx, envelope_id):
    with ctx["owner"].connect() as conn:
        row = conn.execute(text(
            f"SELECT status, freshness_status, stale_reason_code, optimistic_version FROM {ENVELOPES} "
            "WHERE id = :e"), {"e": envelope_id}).one()
        seqs = [r[0] for r in conn.execute(text(
            f"SELECT invalidation_sequence FROM {EVENTS} WHERE envelope_id = :e ORDER BY 1"), {"e": envelope_id})]
    return row, seqs


def _touch_client(session, client_id, value):
    """ORM-Massen-UPDATE (do_orm_execute-Hook), ohne Kunden-Objekte zu laden."""
    from models.clients import Client

    session.query(Client).filter(Client.id == client_id).update({"notes": value}, synchronize_session=False)


# ── RLS und Trigger ──────────────────────────────────────────────────────────


def test_force_rls_and_tenant_bound_select(pg_p2):
    from services.postgres_rls import tenant_scoped_table_names, tenant_tables_missing_rls_policies

    assert {EDGES, EVENTS} <= set(tenant_scoped_table_names())
    with pg_p2["owner"].connect() as conn:
        assert tenant_tables_missing_rls_policies(conn, table_names=(EDGES, EVENTS), schema=pg_p2["schema"]) == []
        for table in (EDGES, EVENTS):
            forced = conn.execute(text(
                "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class c JOIN pg_namespace n "
                "ON n.oid = c.relnamespace WHERE n.nspname = :s AND c.relname = :t"
            ), {"s": pg_p2["schema"], "t": table}).scalar()
            assert forced is True, table
    with _session(pg_p2, "t-b") as db:
        assert {r[0] for r in db.execute(text(f"SELECT envelope_id FROM {EDGES}"))} == {"e-b"}
    with _session(pg_p2, None) as db:
        assert db.execute(text(f"SELECT count(*) FROM {EDGES}")).scalar() == 0


def test_fresh_requires_edges_and_never_returns_to_fresh(pg_p2):
    with _session(pg_p2, "t-a") as db:
        with pytest.raises(DBAPIError):
            _draft(db.connection(), "e-f0", "m-r1", tenant_id="t-a", freshness_status="FRESH")
        _rollback(db)
        _manifest(db.connection(), "man-nf", "m-r1", tenant_id="t-a")
        _draft(db.connection(), "e-nf", "m-r1", tenant_id="t-a")
        _bind(db.connection(), "b-nf", "e-nf", "t-a")
        with pytest.raises(DBAPIError, match="CCX_FRESHNESS_UNKNOWN"):
            _seal(db.connection(), "e-nf", "8" * 64)
        _rollback(db)
    with pg_p2["owner"].connect() as conn:
        assert _mark_stale(conn, "e-trig") == 1
        for statement in (
            f"UPDATE {ENVELOPES} SET freshness_status = 'FRESH', stale_at = NULL, stale_reason_code = NULL, "
            "optimistic_version = optimistic_version + 1 WHERE id = 'e-trig'",
            f"UPDATE {ENVELOPES} SET stale_at = '2000-01-01T00:00:00.000000Z', "
            "optimistic_version = optimistic_version + 1 WHERE id = 'e-trig'",
            f"UPDATE {ENVELOPES} SET freshness_status = 'STALE' WHERE id = 'e-a'",  # ohne Versionssprung
        ):
            savepoint = conn.begin_nested()
            with pytest.raises(DBAPIError):
                conn.execute(text(statement))
            savepoint.rollback()
        conn.rollback()


def test_events_need_stale_envelope_gapless_sequence_and_are_append_only(pg_p2):
    with pg_p2["owner"].begin() as conn:
        savepoint = conn.begin_nested()
        with pytest.raises(DBAPIError, match="CCX_INPUT_STALE"):
            _event(conn, "ev-fresh", "e-r3", "m-r3", "t-a", 1)
        savepoint.rollback()
    with _session(pg_p2, "t-a") as db:
        assert _mark_stale(db.connection(), "e-r3") == 1
        _event(db.connection(), "ev-1", "e-r3", "m-r3", "t-a", 1)
        db.commit()
        for sequence in (1, 3, 0):
            with pytest.raises(DBAPIError):
                _event(db.connection(), f"ev-x{sequence}", "e-r3", "m-r3", "t-a", sequence)
            _rollback(db)
        with pytest.raises(DBAPIError):  # Mandat passt nicht zum Envelope
            _event(db.connection(), "ev-m", "e-r3", "m-a", "t-a", 2)
        _rollback(db)
    for engine_key in ("app", "owner"):
        for statement in (
            f"UPDATE {EVENTS} SET new_hash = NULL WHERE id = 'ev-1'",
            f"DELETE FROM {EVENTS} WHERE id = 'ev-1'",
            f"INSERT INTO {EVENTS} SELECT * FROM {EVENTS} WHERE id = 'ev-1' "
            "ON CONFLICT (id) DO UPDATE SET new_hash = NULL",
            f"UPDATE {EDGES} SET dependency_hash = '{'9' * 64}' WHERE envelope_id = 'e-r3'",
            f"DELETE FROM {EDGES} WHERE envelope_id = 'e-r3'",
            f"INSERT INTO {EDGES} SELECT * FROM {EDGES} WHERE envelope_id = 'e-r3' "
            f"ON CONFLICT (id) DO UPDATE SET dependency_hash = '{'9' * 64}'",
        ):
            if engine_key == "app":
                with _session(pg_p2, "t-a") as db:
                    with pytest.raises(DBAPIError):
                        db.execute(text(statement))
                    db.rollback()
            else:
                with pg_p2["owner"].connect() as conn:
                    with pytest.raises(DBAPIError):
                        conn.execute(text(statement))
                    conn.rollback()
    assert _state(pg_p2, "e-r3")[1] == [1]


def test_foreign_tenant_cannot_write_event(pg_p2):
    with _session(pg_p2, "t-a") as db:
        with pytest.raises(DBAPIError):  # fremder Envelope unter RLS unsichtbar
            _event(db.connection(), "ev-foreign", "e-b", "m-b", "t-b", 1)
        _rollback(db)


# ── Zentraler Mutation Hook ──────────────────────────────────────────────────


def test_hook_invalidates_in_same_commit_and_audits(pg_p2):
    with _session(pg_p2, "t-a") as db:
        _touch_client(db, "c-hook", "geaendert")
        db.commit()
    row, seqs = _state(pg_p2, "e-hook")
    assert (row.status, row.freshness_status, row.stale_reason_code) == ("SEALED", "STALE", "CCX_INPUT_STALE")
    assert seqs == [1]
    with _session(pg_p2, "t-a") as db:
        audit = db.execute(text(
            "SELECT record_id, mandate_id, tenant_id FROM audit_log WHERE field_name = 'ccx.envelope.invalidated'"
        )).all()
        assert ("e-hook", "m-hook", "t-a") in [tuple(r) for r in audit]
    # Fremder Mandant bleibt unberuehrt
    assert _state(pg_p2, "e-b")[0].freshness_status == "FRESH"


# ── Race-Suite (echte parallele Transaktionen) ───────────────────────────────


def test_mutation_during_sealing_waits_and_invalidates_new_envelope(pg_p2):
    sealer = _session(pg_p2, "t-a")
    mutator = _session(pg_p2, "t-a")
    outcome: dict = {}
    try:
        from services.advisory_decision_envelope import lock_mandate_row

        lock_mandate_row(sealer, "m-r1")  # wie seal_advisory_envelope
        conn = sealer.connection()
        _manifest(conn, "man-r1", "m-r1", tenant_id="t-a")
        _draft(conn, "e-r1", "m-r1", tenant_id="t-a")
        _bind(conn, "b-r1", "e-r1", "t-a")
        _edge(conn, "e-r1", "t-a", "client", "c-r1")
        assert _seal(conn, "e-r1", "4" * 64) == 1

        def _mutate():
            try:
                _touch_client(mutator, "c-r1", "waehrend-siegel")
                mutator.commit()
                outcome["result"] = "committed"
            except Exception as exc:  # pragma: no cover - Diagnose
                mutator.rollback()
                outcome["result"] = f"error: {exc!r}"

        worker = threading.Thread(target=_mutate)
        worker.start()
        worker.join(timeout=1.5)
        assert worker.is_alive(), "die Mutation haette auf die Mandatssperre der Versiegelung warten muessen"
        sealer.commit()
        worker.join(timeout=30)
        assert not worker.is_alive() and outcome["result"] == "committed", outcome
    finally:
        sealer.close()
        mutator.close()
    row, seqs = _state(pg_p2, "e-r1")
    assert (row.status, row.freshness_status) == ("SEALED", "STALE")
    assert seqs == [1]


def test_sealing_waits_for_running_mutation(pg_p2):
    mutator = _session(pg_p2, "t-a")
    sealer = _session(pg_p2, "t-a")
    outcome: dict = {}
    try:
        _touch_client(mutator, "c-r2", "vor-siegel")  # Hook haelt die Mandatssperre
        mutator.flush()

        def _seal_later():
            from services.advisory_decision_envelope import lock_mandate_row

            try:
                lock_mandate_row(sealer, "m-r2")
                conn = sealer.connection()
                _manifest(conn, "man-r2", "m-r2", tenant_id="t-a")
                _draft(conn, "e-r2", "m-r2", tenant_id="t-a")
                _bind(conn, "b-r2", "e-r2", "t-a")
                _edge(conn, "e-r2", "t-a", "client", "c-r2")
                outcome["sealed"] = _seal(conn, "e-r2", "5" * 64)
                sealer.commit()
            except Exception as exc:  # pragma: no cover - Diagnose
                sealer.rollback()
                outcome["sealed"] = f"error: {exc!r}"

        worker = threading.Thread(target=_seal_later)
        worker.start()
        worker.join(timeout=1.5)
        # Der Hook der Mutation sperrt m-r2 nur, wenn es Mandate des Kunden gibt;
        # die Versiegelung wartet bis zum Commit der Mutation.
        assert worker.is_alive(), "die Versiegelung haette auf die Mutation warten muessen"
        mutator.commit()
        worker.join(timeout=30)
        assert outcome.get("sealed") == 1, outcome
    finally:
        mutator.close()
        sealer.close()
    row, seqs = _state(pg_p2, "e-r2")
    assert (row.status, row.freshness_status) == ("SEALED", "FRESH")  # liest erst nach der Mutation
    assert seqs == []


def test_parallel_mutations_get_unique_gapless_sequences(pg_p2):
    from models.mandates import Mandate

    first = _session(pg_p2, "t-a")
    second = _session(pg_p2, "t-a")
    outcome: dict = {}
    try:
        _touch_client(first, "c-a", "parallel-1")
        first.flush()  # Hook: Mandatssperre m-a, Ereignis 1 (nicht committet)

        def _second():
            try:
                second.query(Mandate).filter(Mandate.id == "m-a").update(
                    {"mandate_number": "m-a-2"}, synchronize_session=False)
                second.commit()
                outcome["result"] = "committed"
            except Exception as exc:  # pragma: no cover - Diagnose
                second.rollback()
                outcome["result"] = f"error: {exc!r}"

        worker = threading.Thread(target=_second)
        worker.start()
        worker.join(timeout=1.5)
        assert worker.is_alive()
        first.commit()
        worker.join(timeout=30)
        assert outcome["result"] == "committed", outcome
    finally:
        first.close()
        second.close()
    row, seqs = _state(pg_p2, "e-a")
    assert row.freshness_status == "STALE" and seqs == [1, 2]


def test_upgrade_downgrade_upgrade_on_postgres():
    pytest.importorskip("psycopg")
    from alembic import command
    from sqlalchemy import inspect

    token = uuid.uuid4().hex[:12]
    schema = f"ccxp2mig_{token}"
    admin = create_engine(POSTGRES_URL, future=True)
    with admin.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA {_qi(schema)}"))
    scoped = _scoped_url(POSTGRES_URL, schema)
    engine = create_engine(scoped, future=True)
    try:
        cfg = _alembic_cfg(scoped)
        command.upgrade(cfg, "head")
        command.downgrade(cfg, CCX_P1_REV)
        with engine.connect() as conn:
            assert not {EDGES, EVENTS} & set(inspect(conn).get_table_names(schema=schema))
            columns = {c["name"] for c in inspect(conn).get_columns(ENVELOPES, schema=schema)}
            assert not {"freshness_status", "stale_at", "stale_reason_code"} & columns
            source = conn.execute(text(
                "SELECT p.prosrc FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                "WHERE n.nspname = :s AND p.proname = :f"), {"s": schema, "f": f"{ENVELOPES}_guard"}).scalar()
            assert source and "freshness_status" not in source
        command.upgrade(cfg, "head")
        with engine.connect() as conn:
            assert {EDGES, EVENTS} <= set(inspect(conn).get_table_names(schema=schema))
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {_qi(schema)} CASCADE"))
        admin.dispose()


def test_cma_change_during_sealing_waits_and_invalidates(pg_p2):
    """N-908-01 (b): die Versiegelung sperrt die gebundene CMA FOR SHARE. Eine
    parallele CMA-Aenderung (Massen-Hook liest die Zeile FOR UPDATE) wartet bis
    zum Siegel-Commit, sieht danach die Kante und invalidiert den neuen
    Entscheid -- er bleibt nicht mit altem CMA-Hash FRESH."""
    from types import SimpleNamespace

    from models.allocation import CapitalMarketAssumption
    from services.advisory_decision_envelope import lock_bound_reference_rows, lock_mandate_row

    sealer = _session(pg_p2, "t-a")
    mutator = _session(pg_p2, "t-a")
    outcome: dict = {}
    try:
        lock_mandate_row(sealer, "m-r4")
        lock_bound_reference_rows(
            sealer, run=SimpleNamespace(capital_market_assumptions_id="cma-race", policy_id=None,
                                        cma_policy_row_id=None),
            target_allocation=SimpleNamespace(capital_market_assumptions_id=None, policy_id=None),
        )
        conn = sealer.connection()
        _manifest(conn, "man-r4", "m-r4", tenant_id="t-a")
        _draft(conn, "e-r4", "m-r4", tenant_id="t-a")
        _bind(conn, "b-r4", "e-r4", "t-a")
        _edge(conn, "e-r4", "t-a", "cma", "cma-race")
        assert _seal(conn, "e-r4", "9" * 64) == 1

        def _change_cma():
            try:
                mutator.query(CapitalMarketAssumption).filter(CapitalMarketAssumption.id == "cma-race").update(
                    {"notes": "neue Annahme"}, synchronize_session=False)
                mutator.commit()
                outcome["result"] = "committed"
            except Exception as exc:  # pragma: no cover - Diagnose
                mutator.rollback()
                outcome["result"] = f"error: {exc!r}"

        worker = threading.Thread(target=_change_cma)
        worker.start()
        worker.join(timeout=1.5)
        assert worker.is_alive(), "die CMA-Aenderung haette auf die FOR-SHARE-Sperre der Versiegelung warten muessen"
        sealer.commit()
        worker.join(timeout=30)
        assert not worker.is_alive() and outcome["result"] == "committed", outcome
    finally:
        sealer.close()
        mutator.close()
    row, seqs = _state(pg_p2, "e-r4")
    assert (row.status, row.freshness_status) == ("SEALED", "STALE")
    assert seqs == [1]
