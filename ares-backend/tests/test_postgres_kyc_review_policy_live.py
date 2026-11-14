"""C-890-01 gegen ECHTES PostgreSQL: Wiedervorlage-Policy der KYC-Bestaetigung.

Pflichtregressionen 9 und 11 (Vertrag C-890-01): die Alembic-Kette bis
``f4c2e8a6d1b3`` wird in einem eigenen Schema ausgefuehrt; geprueft werden
CHECK-/UNIQUE-Constraints, die Append-only-Trigger (inkl. der neuen
Bindungsspalten von ``kyc_confirmations``), der fail-closed Downgrade und
eine echte Parallelaktivierung zweier Transaktionen: hoechstens eine
Aktivierung auf denselben Vorgaenger wird wirksam.

Alle Fristen sind TESTWERTE (keine Owner-Frist). Ohne
``POSTGRES_TEST_DATABASE_URL`` uebersprungen; der CI-Job ``postgres-rls``
setzt sie und fuehrt diese Datei ausdruecklich aus.
"""
from __future__ import annotations

import os
import sys
import threading
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

POSTGRES_URL = os.getenv("POSTGRES_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="POSTGRES_TEST_DATABASE_URL nicht gesetzt; ohne echtes Postgres nicht pruefbar",
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

NOW = "2026-11-11T10:00:00.000Z"
# C-890-01 Nachtrag 2: a7d3c9e1f5b2 (Ablehnungen) folgt auf f4c2e8a6d1b3.
HEAD = "2c62f9012c73"  # Migrationskopf; RC-CH-1: H10 hinter C-890-01 (Nachtrag 3 d66fbf0588e3), E2 hinter H10, CCX-P1 hinter E2


def _qi(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


@pytest.fixture()
def pg_schema():
    pytest.importorskip("psycopg")
    from alembic import command
    from alembic.config import Config as AlembicConfig

    assert POSTGRES_URL is not None
    schema = f"c890_{uuid.uuid4().hex[:12]}"
    admin = create_engine(POSTGRES_URL, future=True)
    with admin.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA {_qi(schema)}"))
    sep = "&" if "?" in POSTGRES_URL else "?"
    url = f"{POSTGRES_URL}{sep}options=-csearch_path%3D{schema}"
    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    engine = create_engine(url, future=True)
    try:
        command.upgrade(cfg, "head")
        with engine.connect() as conn:
            landed = conn.execute(text(
                "SELECT 1 FROM information_schema.tables WHERE table_schema = :s "
                "AND table_name = 'kyc_review_policy_activations'"), {"s": schema}).scalar()
        assert landed == 1, "Migration nicht im Testschema gelandet"
        from sqlalchemy.orm import sessionmaker

        from models.users import User

        with sessionmaker(bind=engine)() as seed:
            for uid in ("adm-a", "adm-b"):
                seed.add(User(id=uid, username=f"{uid}-{schema}", password_hash="x", full_name=uid,
                              role="admin", is_active=1, created_at=NOW, updated_at=NOW))
            seed.commit()
        yield {"engine": engine, "config": cfg, "schema": schema}
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {_qi(schema)} CASCADE"))
        admin.dispose()


def _policy(conn, pid: str, version: int, *, normal: int = 24, elevated=None, tenant: str = "t-pg") -> None:
    conn.execute(text(
        "INSERT INTO kyc_review_policies (id, tenant_id, jurisdiction, policy_id, version, "
        "normal_max_months, elevated_max_months, valid_from, source_reference, created_by, created_at, "
        "policy_hash) VALUES (:id, :t, 'CH', 'TEST-C890-PG', :v, :n, :e, '2026-01-01', "
        "'TEST-C890 Testwert', 'adm-a', :now, 'h')"),
        {"id": pid, "t": tenant, "v": version, "n": normal, "e": elevated, "now": NOW})


def _activation(conn, aid: str, policy_row_id: str, predecessor: str = "GENESIS") -> None:
    conn.execute(text(
        "INSERT INTO kyc_review_policy_activations (id, tenant_id, jurisdiction, policy_row_id, "
        "predecessor_activation_id, approved_by, approved_at, approval_reference, policy_hash, "
        "activation_hash) VALUES (:id, 't-pg', 'CH', :p, :pred, 'adm-b', :now, 'TEST-C890', 'h', 'h')"),
        {"id": aid, "p": policy_row_id, "pred": predecessor, "now": NOW})


def test_checks_reject_zero_negative_and_looser_elevated_interval(pg_schema):
    engine = pg_schema["engine"]
    for normal, elevated in ((0, None), (-3, None), (12, 13), (12, 0)):
        with pytest.raises(Exception, match="ck_kyc_review_policies"):
            with engine.begin() as conn:
                _policy(conn, uuid.uuid4().hex, 1, normal=normal, elevated=elevated)
    with engine.begin() as conn:
        _policy(conn, "p-ok", 1, normal=12, elevated=12)
    with pytest.raises(Exception, match="uq_kyc_review_policies_version"):
        with engine.begin() as conn:
            _policy(conn, "p-dup", 1)


def test_policy_tables_and_binding_columns_are_append_only(pg_schema):
    engine = pg_schema["engine"]
    with engine.begin() as conn:
        _policy(conn, "p1", 1)
        _activation(conn, "a1", "p1")
        conn.execute(text(
            "INSERT INTO kyc_confirmations (id, tenant_id, client_id, process_scope, form_type, "
            "form_completed_on, external_reference, risk_category, is_pep, identification_confirmed, "
            "identification_date, next_review_due, requires_second_approval, recorded_by, recorded_at, "
            "confirmation_hash, review_policy_row_id, review_policy_activation_id, review_policy_id, "
            "review_policy_version, review_policy_hash, review_risk_class, review_interval_months, "
            "review_max_due) VALUES ('k1', 't-pg', 'c1', 'sro_oder_fremdprozess', 'A', '2026-11-01', "
            "'Ref', 'normal', 0, 1, '2026-11-01', '2028-11-01', 0, 'adm-a', :now, 'h', 'p1', 'a1', "
            "'TEST-C890-PG', 1, 'h', 'normal', 24, '2028-11-01')"), {"now": NOW})
    for sql in (
        "UPDATE kyc_review_policies SET normal_max_months = 99",
        "DELETE FROM kyc_review_policies",
        "UPDATE kyc_review_policy_activations SET approval_reference = 'x'",
        "DELETE FROM kyc_review_policy_activations",
        "UPDATE kyc_confirmations SET review_max_due = '2099-11-01'",
        "UPDATE kyc_confirmations SET review_policy_version = 9",
        "DELETE FROM kyc_confirmations",
    ):
        with pytest.raises(Exception, match="immutable"):
            with engine.begin() as conn:
                conn.execute(text(sql))
    # Redaktion der Freitexte bleibt erlaubt (DSG, N-890-09).
    with engine.begin() as conn:
        conn.execute(text("UPDATE kyc_confirmations SET external_reference = '[ERASED-DSG-ART-32]'"))


def test_parallel_activation_on_the_same_predecessor_yields_one_winner(pg_schema):
    """Zwei echte Transaktionen aktivieren gleichzeitig je eine Version auf
    denselben Vorgaenger (GENESIS): die zweite wartet auf die erste und
    scheitert am UNIQUE-Index; es gibt genau eine Aktivierung."""
    engine = pg_schema["engine"]
    with engine.begin() as conn:
        _policy(conn, "p-a", 1)
        _policy(conn, "p-b", 2, normal=12)
    barrier = threading.Barrier(2)
    results: dict[str, str] = {}

    def worker(name: str, policy_row_id: str, hold: float) -> None:
        conn = engine.connect()
        trans = conn.begin()
        try:
            barrier.wait(timeout=30)
            _activation(conn, f"act-{name}", policy_row_id)
            if hold:
                import time

                time.sleep(hold)
            trans.commit()
            results[name] = "committed"
        except Exception as exc:  # noqa: BLE001 - Ergebnis wird geprueft
            trans.rollback()
            results[name] = type(exc).__name__ + ": " + str(exc).splitlines()[0]
        finally:
            conn.close()

    threads = [threading.Thread(target=worker, args=("a", "p-a", 1.0)),
               threading.Thread(target=worker, args=("b", "p-b", 0.0))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert sorted(v == "committed" for v in results.values()) == [False, True], results
    loser = next(v for v in results.values() if v != "committed")
    assert "uq_kyc_review_policy_activations_chain" in loser, loser
    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM kyc_review_policy_activations")).scalar() == 1


def test_gate_resolution_on_postgres_sees_exactly_one_effective_version(pg_schema):
    from sqlalchemy.orm import sessionmaker

    from services import recommendation_release_gate as gate

    engine = pg_schema["engine"]
    session = sessionmaker(bind=engine)()
    try:
        from models.tenant import KycReviewPolicy, KycReviewPolicyActivation

        policy = KycReviewPolicy(
            id="p-gate", tenant_id="t-pg", jurisdiction="CH", policy_id="TEST-C890-PG", version=1,
            normal_max_months=24, elevated_max_months=12, valid_from="2026-01-01",
            source_reference="TEST-C890 Testwert", created_by="adm-a", created_at=NOW)
        policy.policy_hash = gate.row_seal({c.name: getattr(policy, c.name) for c in policy.__table__.columns},
                                           "policy_hash")
        session.add(policy)
        session.flush()
        act = KycReviewPolicyActivation(
            id="a-gate", tenant_id="t-pg", jurisdiction="CH", policy_row_id="p-gate",
            predecessor_activation_id="GENESIS", approved_by="adm-b", approved_at=NOW,
            approval_reference="TEST-C890", policy_hash=policy.policy_hash)
        act.activation_hash = gate.row_seal({c.name: getattr(act, c.name) for c in act.__table__.columns},
                                            "activation_hash")
        session.add(act)
        session.commit()
        resolved = gate.resolve_kyc_review_policy(session, "t-pg", "CH", "2026-11-11")
        assert (resolved["status"], resolved["policy"]["id"]) == ("effective", "p-gate")
        assert gate.resolve_kyc_review_policy(session, "t-pg", "DE", "2026-11-11")["reason_code"] == (
            "KYC_REVIEW_POLICY_MISSING")
    finally:
        session.close()


def test_downgrade_is_fail_closed_with_evidence_and_clean_without(pg_schema):
    from alembic import command

    engine, cfg = pg_schema["engine"], pg_schema["config"]
    with engine.begin() as conn:
        _policy(conn, "p-down", 1)
    with pytest.raises(Exception, match="fail-closed"):
        command.downgrade(cfg, "a9d4e2c6f1b3")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == HEAD
        assert conn.execute(text("SELECT COUNT(*) FROM kyc_review_policies")).scalar() == 1


def test_upgrade_downgrade_upgrade_without_evidence(pg_schema):
    from alembic import command

    engine, cfg = pg_schema["engine"], pg_schema["config"]
    command.downgrade(cfg, "a9d4e2c6f1b3")
    with engine.connect() as conn:
        assert conn.execute(text(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = :s "
            "AND table_name LIKE 'kyc_review_%'"), {"s": pg_schema["schema"]}).scalar() == 0
        assert conn.execute(text(
            "SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = :s "
            "AND table_name = 'kyc_confirmations' AND column_name LIKE 'review_%'"),
            {"s": pg_schema["schema"]}).scalar() == 0
    command.upgrade(cfg, "head")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == HEAD


def test_rejections_are_append_only_with_redaction_only(pg_schema):
    """Nachtrag 2: Ablehnung der Zweitfreigabe -- unveraenderlich, nur die
    Begruendung darf auf den DSG-Redaktionsmarker gesetzt werden; eine zweite
    Entscheidung zur selben Bestaetigung scheitert am UNIQUE-Index."""
    engine = pg_schema["engine"]
    insert = text(
        "INSERT INTO kyc_confirmation_rejections (id, tenant_id, confirmation_id, client_id, rejected_by, "
        "rejected_at, reason, confirmation_hash, rejection_hash) VALUES (:id, 't-pg', 'k1', 'c1', 'adm-b', "
        ":now, 'Mittelherkunft offen (Test)', 'h', 'h')")
    with engine.begin() as conn:
        conn.execute(insert, {"id": "rj1", "now": NOW})
    with pytest.raises(Exception):
        with engine.begin() as conn:
            conn.execute(insert, {"id": "rj2", "now": NOW})
    for sql in ("UPDATE kyc_confirmation_rejections SET reason = 'anders'",
                "UPDATE kyc_confirmation_rejections SET rejected_by = 'adm-a'",
                "DELETE FROM kyc_confirmation_rejections"):
        with pytest.raises(Exception, match="immutable"):
            with engine.begin() as conn:
                conn.execute(text(sql))
    with engine.begin() as conn:
        conn.execute(text("UPDATE kyc_confirmation_rejections SET reason = '[ERASED-DSG-ART-32]'"))


def test_parallel_decisions_on_postgres_yield_exactly_one(pg_schema):
    """N-897-08: zwei echte Transaktionen entscheiden gleichzeitig ueber
    dieselbe Bestaetigung (Freigabe vs. Ablehnung): genau eine gelingt."""
    engine = pg_schema["engine"]
    barrier = threading.Barrier(2)
    results: dict[str, str] = {}

    def worker(name: str, decision: str, hold: float) -> None:
        conn = engine.connect()
        trans = conn.begin()
        try:
            barrier.wait(timeout=30)
            conn.execute(text(
                "INSERT INTO kyc_confirmation_decisions (id, confirmation_id, tenant_id, decision, decided_by, "
                "decided_at, record_id, approver_ready, decision_hash) "
                "VALUES (:rid, 'k-par', 't-pg', :d, 'adm-b', :now, :rid, 1, 'h')"),
                {"d": decision, "now": NOW, "rid": f"r-{name}"})
            if hold:
                import time

                time.sleep(hold)
            trans.commit()
            results[name] = "committed"
        except Exception as exc:  # noqa: BLE001
            trans.rollback()
            results[name] = type(exc).__name__ + ": " + str(exc).splitlines()[0]
        finally:
            conn.close()

    threads = [threading.Thread(target=worker, args=("a", "approve", 1.0)),
               threading.Thread(target=worker, args=("b", "reject", 0.0))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert sorted(v == "committed" for v in results.values()) == [False, True], results
    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM kyc_confirmation_decisions")).scalar() == 1
    for sql in ("UPDATE kyc_confirmation_decisions SET decision = 'reject'", "DELETE FROM kyc_confirmation_decisions"):
        with pytest.raises(Exception, match="immutable"):
            with engine.begin() as conn:
                conn.execute(text(sql))
