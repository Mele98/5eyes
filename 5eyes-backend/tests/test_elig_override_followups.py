"""Follow-ups to ELIG-OVERRIDE-CAPTURE-001 (CIO decisions 2026-10-27).

ELIG-OVERRIDE-SINGLE-APPROVER-001
    An advisor without a second person entitled to approve may confirm their
    own override only through the attestation path of the rule approval
    (services/product_eligibility_governance.py::approve_rule): explicit
    attestation, reason of at least 20 characters, and the tenant has
    EXACTLY ONE active person entitled to approve (here: the roles that
    ``require_advisor`` admits). Stored and shown as
    ``approval_mode='single_approver_attested'``; never the default.

ELIG-OVERRIDE-APPEND-ONLY-001
    ``product_eligibility_overrides`` is append-only in the database:
    UPDATE and DELETE are rejected by triggers (SQLite and PostgreSQL). Like
    the other append-only evidence tables it carries no hard foreign key to
    the recommendation run, so the demo purge and the run cleanup still
    work; the evidence rows stay (Purge-fest, like audit_log).
"""
from __future__ import annotations

import io
import sqlite3
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import DatabaseError, IntegrityError
from sqlalchemy.orm import sessionmaker

TESTS_ROOT = Path(__file__).resolve().parent
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from test_elig_override_capture import (  # noqa: E402
    REASON,
    _base,
    _blocked,
    _override_ctx,
    _request_and_approve,
    _user,
    api,  # noqa: F401  (fixture; resolves session_factory below)
)

from database import Base  # noqa: E402
from models.product_eligibility import ProductEligibilityOverride  # noqa: E402
from models.review import AuditLog, RecommendationRun  # noqa: E402
from models.users import User  # noqa: E402

BACKEND_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_REVISION = "f4b8d2a6c1e7"
MIGRATION_DOWN_REVISION = "d3e1a7c9b4f2"
ATTEST_REASON = "Einzelberater ohne zweite Person; Ausnahme selbst geprueft und dokumentiert."


@pytest.fixture()
def session_factory(tmp_path):
    """File DB with foreign keys enforced, as on the desktop
    (database.py::attach_sqlite_pragmas)."""
    engine = create_engine(f"sqlite:///{tmp_path / 'followups.db'}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield factory
    finally:
        engine.dispose()


def _persist_user(session_factory, user_id: str, role: str, tenant_id: str | None = None,
                  is_active: int = 1) -> None:
    now = "2026-10-27T00:00:00+00:00"
    with session_factory() as s:
        s.add(User(id=user_id, username=user_id, password_hash="h", full_name=user_id,
                   role=role, is_active=is_active, tenant_id=tenant_id, created_at=now, updated_at=now))
        s.commit()


def _request(api, ctx):
    created = api("POST", _base(ctx), ctx["advisor_user"],
                  json={"product_id": ctx["product"], "reason_text": REASON})
    assert created.status_code == 201, created.text
    return created.json()


def _attest(api, ctx, request_id, *, reason=ATTEST_REASON, attestation=True):
    return api("POST", _base(ctx) + f"/{request_id}/approve", ctx["advisor_user"],
               json={"single_approver_attestation": attestation, "attestation_reason": reason})


# ---------------------------------------------------------------------------
# ELIG-OVERRIDE-SINGLE-APPROVER-001
# ---------------------------------------------------------------------------

def test_sole_approver_attests_own_override_and_finalize_is_unblocked(session_factory, monkeypatch, api):
    ctx = _override_ctx(session_factory, monkeypatch, "sole")
    request = _request(api, ctx)
    response = _attest(api, ctx, request["id"])
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["approval_mode"] == "single_approver_attested"
    assert body["approved_by"] == body["requested_by"] == ctx["advisor"]
    assert not _blocked(session_factory, ctx)

    listing = api("GET", _base(ctx), ctx["advisor_user"]).json()
    assert listing["approver_count"] == 1 and listing["current_user_is_sole_approver"] is True
    [item] = listing["items"]
    assert item["has_valid_override"] is True
    valid = [o for o in item["overrides"] if o["state"] == "valid"]
    assert [o["approval_mode"] for o in valid] == ["single_approver_attested"]

    with session_factory() as s:
        trail = [r.new_value for r in s.query(AuditLog).filter(
            AuditLog.table_name == "product_eligibility_overrides").all()]
    assert any("approval_mode=single_approver_attested" in v and ATTEST_REASON in v for v in trail), trail


def test_attestation_is_refused_when_a_second_person_may_approve(session_factory, monkeypatch, api):
    ctx = _override_ctx(session_factory, monkeypatch, "two")
    _persist_user(session_factory, "two-colleague", "advisor")
    request = _request(api, ctx)
    response = _attest(api, ctx, request["id"])
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["reason_code"] == "FOUR_EYES_REQUIRED"
    assert _blocked(session_factory, ctx)
    listing = api("GET", _base(ctx), ctx["advisor_user"]).json()
    assert listing["approver_count"] == 2 and listing["current_user_is_sole_approver"] is False


def test_inactive_or_foreign_tenant_users_do_not_count_as_second_approver(session_factory, monkeypatch, api):
    from models.tenant import Tenant

    ctx = _override_ctx(session_factory, monkeypatch, "count")
    with session_factory() as s:
        s.add(Tenant(id="other-firm", display_name="Andere Firma", slug="other-firm",
                     created_at="2026-10-27T00:00:00+00:00", updated_at="2026-10-27T00:00:00+00:00"))
        s.commit()
    _persist_user(session_factory, "count-other-firm", "admin", tenant_id="other-firm")
    _persist_user(session_factory, "count-client", "client")
    _persist_user(session_factory, "count-inactive", "advisor", is_active=0)
    request = _request(api, ctx)
    assert _attest(api, ctx, request["id"]).status_code == 201


@pytest.mark.parametrize("attestation,reason,code", [
    (False, ATTEST_REASON, "FOUR_EYES_REQUIRED"),
    (True, "zu kurz", "ATTESTATION_REASON_REQUIRED"),
    (True, None, "ATTESTATION_REASON_REQUIRED"),
])
def test_self_approval_without_complete_attestation_is_refused(
    session_factory, monkeypatch, api, attestation, reason, code,
):
    ctx = _override_ctx(session_factory, monkeypatch, f"incomplete-{attestation}-{len(reason or '')}")
    request = _request(api, ctx)
    response = _attest(api, ctx, request["id"], reason=reason, attestation=attestation)
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["reason_code"] == code
    assert _blocked(session_factory, ctx)


def test_second_person_approval_stays_four_eyes_even_with_attestation_flag(session_factory, monkeypatch, api):
    ctx = _override_ctx(session_factory, monkeypatch, "flag")
    request = _request(api, ctx)
    response = api("POST", _base(ctx) + f"/{request['id']}/approve", ctx["admin_user"],
                   json={"single_approver_attestation": True, "attestation_reason": ATTEST_REASON})
    assert response.status_code == 201, response.text
    assert response.json()["approval_mode"] == "four_eyes"
    assert not _blocked(session_factory, ctx)


def test_self_approved_row_without_attested_mode_is_no_evidence(session_factory, monkeypatch, api):
    """A row whose approver equals the requester counts only if it was
    stored as single_approver_attested (the mode is part of the hash)."""
    from services.product_eligibility_override import (
        decision_binding_hash, decision_context, evaluate, override_evidence_hash,
    )
    from database import new_uuid
    from models.mandates import Mandate
    from models.review import Product
    from test_elig_finalization_eligibility import _iso

    ctx = _override_ctx(session_factory, monkeypatch, "forged")
    with session_factory() as s:
        row = ProductEligibilityOverride(
            id=new_uuid(), rule_id=ctx["rule"], product_id=ctx["product"],
            recommendation_run_id=ctx["run"], original_decision="indeterminate",
            overridden_dimension="override", reason_code="ADVISOR_DOCUMENTED_EXCEPTION",
            reason_text=REASON, requested_by=ctx["advisor"], approved_by=ctx["advisor"],
            valid_from=_iso(-1), expires_at=_iso(30), approval_mode="four_eyes",
            created_at=_iso(0), updated_at=_iso(0),
        )
        dctx = decision_context(s, s.get(Mandate, ctx["mandate"]), s.get(RecommendationRun, ctx["run"]))
        decision = evaluate(s, dctx, s.get(Product, ctx["product"]), 0)
        row.evidence_hash = override_evidence_hash(row, decision_binding_hash(dctx, decision))
        s.add(row)
        s.commit()
    assert _blocked(session_factory, ctx)


# ---------------------------------------------------------------------------
# ELIG-OVERRIDE-APPEND-ONLY-001
# ---------------------------------------------------------------------------

def test_override_rows_reject_update_and_delete(session_factory, monkeypatch, api):
    ctx = _override_ctx(session_factory, monkeypatch, "immutable")
    _request_and_approve(api, ctx)
    for statement in (
        "UPDATE product_eligibility_overrides SET expires_at = '2999-01-01T00:00:00+00:00'",
        "UPDATE product_eligibility_overrides SET approved_by = 'someone-else'",
        "DELETE FROM product_eligibility_overrides",
    ):
        with session_factory() as s:
            with pytest.raises((IntegrityError, DatabaseError), match="immutable"):
                s.execute(text(statement))
                s.flush()
            s.rollback()
    with session_factory() as s:
        assert s.query(ProductEligibilityOverride).count() == 2
    assert not _blocked(session_factory, ctx)


def test_run_cleanup_with_override_evidence_keeps_the_evidence(session_factory, monkeypatch, api):
    """Draft-run cleanup hard-deletes old runs; an override on such a run
    must neither block it (no FK) nor be deleted (append-only)."""
    from datetime import datetime, timedelta, timezone

    from services.recommendation_run_cleanup import cleanup_recommendation_runs

    ctx = _override_ctx(session_factory, monkeypatch, "cleanup")
    _request_and_approve(api, ctx)
    with session_factory() as s:
        result = cleanup_recommendation_runs(
            s, retention_days=90, now=datetime.now(timezone.utc) + timedelta(days=365),
        )
        s.commit()
        assert ctx["run"] not in {r.id for r in s.query(RecommendationRun).all()}
        assert result.deleted_runs >= 1
        assert s.query(ProductEligibilityOverride).count() == 2


def _alembic_config(database_url: str):
    from alembic.config import Config as AlembicConfig

    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return cfg


_LEGACY_ROW = (
    "INSERT INTO product_eligibility_overrides (id, product_id, recommendation_run_id, "
    "original_decision, overridden_dimension, reason_code, reason_text, requested_by, approved_by, "
    "valid_from, expires_at, evidence_hash, created_at, updated_at) VALUES ('legacy-1', 'p-1', 'run-1', "
    "'indeterminate', 'override', 'ADVISOR_DOCUMENTED_EXCEPTION', 'Begruendung', 'adv', '', "
    "'2026-10-01', '2026-10-01', 'h', '2026-10-01', '2026-10-01')"
)


def _run_fk(conn) -> list:
    return [row for row in conn.execute(text("PRAGMA foreign_key_list(product_eligibility_overrides)")).all()
            if row[3] == "recommendation_run_id"]


def _columns(conn) -> set[str]:
    return {row[1] for row in conn.execute(text("PRAGMA table_info(product_eligibility_overrides)")).all()}


def _seed_legacy_row(conn) -> None:
    # Plain engine: SQLite does not enforce the FKs, the parents may be missing.
    conn.execute(text(_LEGACY_ROW))


def test_migration_is_in_the_single_head_chain():
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_alembic_config("sqlite://"))
    heads = script.get_heads()
    assert len(heads) == 1, heads
    chain = {rev.revision for rev in script.walk_revisions("base", heads[0])}
    assert MIGRATION_REVISION in chain
    assert script.get_revision(MIGRATION_REVISION).down_revision == MIGRATION_DOWN_REVISION


def test_migration_drops_run_fk_installs_triggers_keeps_rows_and_downgrades(tmp_path):
    from alembic import command

    url = f"sqlite:///{tmp_path / 'chain.db'}"
    cfg = _alembic_config(url)
    command.upgrade(cfg, MIGRATION_DOWN_REVISION)
    engine = create_engine(url)
    try:
        with engine.begin() as conn:
            assert _run_fk(conn), "precondition: legacy table has the run FK"
            _seed_legacy_row(conn)
        command.upgrade(cfg, MIGRATION_REVISION)
        with engine.connect() as conn:
            assert _run_fk(conn) == []
            assert "approval_mode" in _columns(conn)
            assert conn.execute(text("SELECT reason_text FROM product_eligibility_overrides")).scalar() == "Begruendung"
            indexes = {row[1] for row in conn.execute(text("PRAGMA index_list(product_eligibility_overrides)")).all()}
            assert "ix_product_eligibility_overrides_run_product" in indexes
        with sqlite3.connect(str(tmp_path / "chain.db")) as raw:
            with pytest.raises(sqlite3.DatabaseError, match="immutable"):
                raw.execute("UPDATE product_eligibility_overrides SET reason_text = 'x'")
            with pytest.raises(sqlite3.DatabaseError, match="immutable"):
                raw.execute("DELETE FROM product_eligibility_overrides")
        command.downgrade(cfg, MIGRATION_DOWN_REVISION)
        with engine.connect() as conn:
            triggers = conn.execute(text(
                "SELECT count(*) FROM sqlite_master WHERE type = 'trigger' "
                "AND tbl_name = 'product_eligibility_overrides'"
            )).scalar()
            assert triggers == 0 and "approval_mode" not in _columns(conn)
            assert conn.execute(text("SELECT count(*) FROM product_eligibility_overrides")).scalar() == 1
        command.upgrade(cfg, MIGRATION_REVISION)
    finally:
        engine.dispose()


def test_postgres_offline_sql_drops_run_fk_and_installs_immutability_trigger():
    from alembic import command

    buffer = io.StringIO()
    cfg = _alembic_config("postgresql://user:pass@localhost/db")
    cfg.output_buffer = buffer
    command.upgrade(cfg, f"{MIGRATION_DOWN_REVISION}:{MIGRATION_REVISION}", sql=True)
    sql = buffer.getvalue()
    assert "DROP CONSTRAINT IF EXISTS product_eligibility_overrides_recommendation_run_id_fkey" in sql
    assert "ADD COLUMN approval_mode" in sql
    assert "CREATE TRIGGER trg_product_eligibility_overrides_immutable" in sql
    assert "BEFORE UPDATE OR DELETE ON product_eligibility_overrides" in sql


def test_sqlite_runtime_patch_upgrades_legacy_desktop_table(tmp_path):
    from services.product_eligibility_override_schema import ensure_sqlite_override_append_only

    url = f"sqlite:///{tmp_path / 'legacy.db'}"
    engine = create_engine(url)
    try:
        Base.metadata.create_all(bind=engine)
        with engine.begin() as conn:
            # Legacy shape (as created before this change): run FK, no
            # approval_mode, no triggers.
            conn.execute(text("DROP TABLE product_eligibility_overrides"))
            conn.execute(text(
                "CREATE TABLE product_eligibility_overrides (id VARCHAR NOT NULL PRIMARY KEY, "
                "snapshot_id VARCHAR REFERENCES product_eligibility_snapshots(id), "
                "rule_id VARCHAR REFERENCES product_eligibility_rules(id), "
                "product_id VARCHAR NOT NULL REFERENCES products(id), "
                "recommendation_run_id VARCHAR NOT NULL REFERENCES recommendation_runs(id), "
                "original_decision VARCHAR NOT NULL, overridden_dimension VARCHAR NOT NULL, "
                "reason_code VARCHAR NOT NULL, reason_text VARCHAR, requested_by VARCHAR NOT NULL, "
                "approved_by VARCHAR NOT NULL, client_acknowledgement_id VARCHAR, warning_delivery_id VARCHAR, "
                "valid_from VARCHAR NOT NULL, expires_at VARCHAR NOT NULL, policy_basis VARCHAR, "
                "evidence_hash VARCHAR NOT NULL, created_at VARCHAR NOT NULL, updated_at VARCHAR NOT NULL)"
            ))
            _seed_legacy_row(conn)
        assert ensure_sqlite_override_append_only(engine) is True
        assert ensure_sqlite_override_append_only(engine) is False  # idempotent
        with engine.connect() as conn:
            assert _run_fk(conn) == []
            assert "approval_mode" in _columns(conn)
            assert conn.execute(text("SELECT count(*) FROM product_eligibility_overrides")).scalar() == 1
        with sqlite3.connect(str(tmp_path / "legacy.db")) as raw:
            with pytest.raises(sqlite3.DatabaseError, match="immutable"):
                raw.execute("UPDATE product_eligibility_overrides SET reason_text = 'x'")
    finally:
        engine.dispose()


def test_runtime_ddl_matches_the_orm_columns():
    from services.product_eligibility_override_schema import OVERRIDE_COLUMNS

    assert list(OVERRIDE_COLUMNS) == [c.name for c in ProductEligibilityOverride.__table__.columns]
    fk_columns = {fk.parent.name for fk in ProductEligibilityOverride.__table__.foreign_keys}
    assert "recommendation_run_id" not in fk_columns
