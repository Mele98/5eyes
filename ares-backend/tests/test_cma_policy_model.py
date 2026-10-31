"""CMA-001: versioniertes CMA_POLICY-Modell, Vier-Augen-Freigabe, Gate.

Prueft Workflow und Gate -- KEINE Fachwerte. Alle Zahlen in diesem Test
sind beliebige Platzhalter, deren einzige Aufgabe ist, Domaenenregeln
(Bereich, Vorzeichen, Doppelanwendung) auszuloesen.
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for _p in (BACKEND_ROOT, TESTS_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import models  # noqa: E402,F401
from database import Base  # noqa: E402
from models.allocation import CapitalMarketAssumption  # noqa: E402
from models.cma_policy import CmaPolicy, CmaPolicyApproval, CmaPolicyComponent  # noqa: E402
from models.users import User  # noqa: E402
from services import cma_policy as svc  # noqa: E402

REVISION = "b5d2e8f1c4a7"
SCHEMA_FILE = BACKEND_ROOT / "ares_schema.sql"
TABLES = ("cma_policies", "cma_policy_components", "cma_policy_approvals")
APPROVAL_TRIGGERS = {
    "trg_cma_policy_approvals_no_update",
    "trg_cma_policy_approvals_no_delete",
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


@pytest.fixture()
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'cma_policy.db'}")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    now = _now()
    for uid in ("creator", "approver-a", "approver-b", "approver-c"):
        session.add(User(id=uid, username=uid, password_hash="h", full_name=uid,
                         role="portfolio_management", is_active=1,
                         created_at=now, updated_at=now))
    session.add(CapitalMarketAssumption(
        id="cma-1", assumption_set_name="Test", version=1, valid_from="2026-01-01",
        is_current=1, created_by="creator", created_at=now, updated_at=now,
    ))
    session.add(CapitalMarketAssumption(
        id="cma-2", assumption_set_name="Test", version=2, valid_from="2026-01-01",
        is_current=0, created_by="creator", created_at=now, updated_at=now,
    ))
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _component(**overrides):
    base = {
        "asset_key": "equities",
        "component": "erp",
        "value_bps": 1,
        "unit": "bps_pa",
        "horizon_years": 1,
        "method": "Platzhalter",
        "source": "Platzhalter",
        "sign": "either",
        "confidence": None,
        "range_min_bps": 0,
        "range_max_bps": 2,
    }
    base.update(overrides)
    return base


def _draft(db, *, cma_id="cma-1", policy_id="CMA-POLICY-TEST", components=None, **overrides):
    data = {
        "policy_id": policy_id,
        "capital_market_assumptions_id": cma_id,
        "correlation_policy_ref": "CMA-CORR-001",
        "valid_from": "2026-01-01",
        "valid_until": None,
        "data_as_of": "2026-01-01",
        "base_currency": "CHF",
        "return_basis": "nominal",
        "fee_basis": "gross",
        "method_version": "v-test",
        "sources_json": [{"source": "Platzhalter", "digest": "abc"}],
        "rationale": "Test",
        "components": components if components is not None else [
            _component(),
            _component(component="risk_free"),
        ],
    }
    data.update(overrides)
    policy = svc.create_draft(db, "creator", data)
    db.commit()
    return policy


def _activate(db, policy, *, today=date(2026, 6, 1)):
    svc.validate_policy(db, policy, "creator")
    svc.approve_policy(db, policy, "approver-a", "ok")
    svc.approve_policy(db, policy, "approver-b", "ok")
    svc.activate_policy(db, policy, "approver-a", today=today)
    db.commit()
    return policy


# ── Lebenszyklus ─────────────────────────────────────────────────────────


def test_full_lifecycle_requires_two_independent_approvals(db):
    policy = _draft(db)
    assert policy.status == svc.STATUS_DRAFT and policy.version == 1
    svc.validate_policy(db, policy, "creator")
    assert policy.status == svc.STATUS_VALIDATED and policy.content_hash
    svc.approve_policy(db, policy, "approver-a", "ok")
    assert policy.status == svc.STATUS_VALIDATED  # eine Freigabe reicht nicht
    svc.approve_policy(db, policy, "approver-b", "ok")
    assert policy.status == svc.STATUS_APPROVED
    svc.activate_policy(db, policy, "approver-a", today=date(2026, 6, 1))
    assert policy.status == svc.STATUS_ACTIVE and policy.activated_at


def test_self_approval_and_double_approval_are_refused(db):
    policy = _draft(db)
    svc.validate_policy(db, policy, "creator")
    with pytest.raises(svc.CmaPolicyConflict):
        svc.approve_policy(db, policy, "creator", "selbst")
    svc.approve_policy(db, policy, "approver-a", "ok")
    with pytest.raises(svc.CmaPolicyConflict):
        svc.approve_policy(db, policy, "approver-a", "nochmal")
    assert policy.status == svc.STATUS_VALIDATED


def test_content_is_frozen_after_draft(db):
    policy = _draft(db)
    svc.validate_policy(db, policy, "creator")
    with pytest.raises(svc.CmaPolicyConflict):
        svc.replace_components(db, policy, [_component()])


def test_new_version_supersedes_and_retires_previous_active(db):
    first = _activate(db, _draft(db))
    second = _draft(db, supersedes_id=first.id)
    assert second.version == 2
    _activate(db, second)
    db.refresh(first)
    assert first.status == svc.STATUS_RETIRED and first.retired_at
    assert second.status == svc.STATUS_ACTIVE


def test_revoke_requires_reason(db):
    policy = _activate(db, _draft(db))
    with pytest.raises(svc.CmaPolicyError):
        svc.revoke_policy(db, policy, "approver-a", " ")
    svc.revoke_policy(db, policy, "approver-a", "Fehler entdeckt")
    assert policy.status == svc.STATUS_REVOKED


@pytest.mark.parametrize(
    "components, message",
    [
        ([], "Komponentenledger"),
        ([_component(component="unbekannt")], "unbekannte Komponente"),
        ([_component(value_bps=5, range_max_bps=2)], "Bereich"),
        ([_component(sign="positive", value_bps=-1, range_min_bps=-2)], "Vorzeichen"),
        ([_component(unit="prozent")], "Einheit"),
        ([_component(range_min_bps=-20000)], "unplausibel"),
    ],
)
def test_validation_rejects_incomplete_or_inconsistent_components(db, components, message):
    policy = _draft(db, components=components)
    with pytest.raises(svc.CmaPolicyError, match=message):
        svc.validate_policy(db, policy, "creator")
    assert policy.status == svc.STATUS_DRAFT


def test_component_ledger_prevents_double_application(db):
    with pytest.raises(svc.CmaPolicyError, match="Doppelanwendung"):
        _draft(db, components=[_component(), _component(value_bps=2)])


def test_sources_need_digest(db):
    with pytest.raises(svc.CmaPolicyError, match="Digest"):
        _draft(db, sources_json=[{"source": "x"}])


def test_activation_outside_validity_is_refused(db):
    policy = _draft(db, valid_from="2027-01-01")
    svc.validate_policy(db, policy, "creator")
    svc.approve_policy(db, policy, "approver-a", "ok")
    svc.approve_policy(db, policy, "approver-b", "ok")
    with pytest.raises(svc.CmaPolicyConflict, match="Gueltigkeit"):
        svc.activate_policy(db, policy, "approver-a", today=date(2026, 6, 1))


def test_tampered_content_blocks_activation(db):
    policy = _draft(db)
    svc.validate_policy(db, policy, "creator")
    svc.approve_policy(db, policy, "approver-a", "ok")
    svc.approve_policy(db, policy, "approver-b", "ok")
    db.commit()
    # Direktes Ueberschreiben am Workflow vorbei.
    db.execute(text("UPDATE cma_policy_components SET value_bps = 2 WHERE policy_row_id = :id"),
               {"id": policy.id})
    db.commit()
    db.expire_all()
    with pytest.raises(svc.CmaPolicyConflict, match="Hash"):
        svc.activate_policy(db, policy, "approver-a", today=date(2026, 6, 1))


def test_approvals_are_append_only(db):
    policy = _draft(db)
    svc.validate_policy(db, policy, "creator")
    svc.approve_policy(db, policy, "approver-a", "ok")
    db.commit()
    with pytest.raises(DatabaseError):
        db.execute(text("UPDATE cma_policy_approvals SET rationale = 'x'"))
    db.rollback()
    with pytest.raises(DatabaseError):
        db.execute(text("DELETE FROM cma_policy_approvals"))
    db.rollback()
    assert db.query(CmaPolicyApproval).count() == 1


# ── Gate ─────────────────────────────────────────────────────────────────


def test_gate_is_inactive_until_first_activation(db):
    _draft(db)  # nur Entwurf: Modell vorhanden, nicht scharf
    assert svc.policy_model_enforced(db) is False
    assert svc.finalization_policy_check(db, "cma-1") == (None, None)


def test_gate_codes_once_enforced(db):
    policy = _activate(db, _draft(db, valid_until="2026-12-31"))
    assert svc.policy_model_enforced(db) is True

    granted, block = svc.finalization_policy_check(db, "cma-1", today=date(2026, 6, 1))
    assert block is None and granted.id == policy.id

    _granted, block = svc.finalization_policy_check(db, "cma-2", today=date(2026, 6, 1))
    assert block[0] == svc.CMA_POLICY_MISSING

    _granted, block = svc.finalization_policy_check(db, "cma-1", today=date(2027, 1, 1))
    assert block[0] == svc.CMA_POLICY_EXPIRED

    _draft(db, cma_id="cma-2", policy_id="CMA-POLICY-OTHER")
    _granted, block = svc.finalization_policy_check(db, "cma-2", today=date(2026, 6, 1))
    assert block[0] == svc.CMA_POLICY_NOT_ACTIVE

    svc.revoke_policy(db, policy, "approver-a", "Widerruf")
    db.commit()
    _granted, block = svc.finalization_policy_check(db, "cma-1", today=date(2026, 6, 1))
    assert block[0] == svc.CMA_POLICY_NOT_ACTIVE


def test_gate_reports_integrity_violation(db):
    _activate(db, _draft(db))
    db.execute(text("UPDATE cma_policies SET rationale = 'anders'"))
    db.commit()
    db.expire_all()
    _granted, block = svc.finalization_policy_check(db, "cma-1", today=date(2026, 6, 1))
    assert block[0] == svc.CMA_POLICY_INTEGRITY


# ── Finalisierung ────────────────────────────────────────────────────────


def test_finalization_blocked_once_model_is_enforced(tmp_path):
    from models.review import RecommendationRun
    from routers.review import finalize_recommendation
    from test_finalization_ignores_risk_budget_violated_lock import (
        _FakeRequest,
        _add_full_position,
        _allocation_policy_and_cma,
        _current_allocation_id,
        _make_run,
        _seed_realistic_mandate,
    )

    engine = create_engine(f"sqlite:///{tmp_path / 'final.db'}",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    advisor_id, _cid, mid, aid, _gid = _seed_realistic_mandate(SF, suffix="cmapol")
    alloc_id = _current_allocation_id(SF, mid, advisor_id)
    policy_id, cma_id = _allocation_policy_and_cma(SF, alloc_id)
    run_id = _make_run(SF, mid, alloc_id, aid, advisor_id, policy_id, cma_id)
    _add_full_position(SF, run_id)

    # Eine fremde CMA traegt eine aktive Policy -> Modell ist scharf, die
    # CMA dieses Laufs hat aber keine Policy.
    now = _now()
    with SF() as s:
        for uid in ("creator", "approver-a", "approver-b"):
            s.add(User(id=uid, username=uid, password_hash="h", full_name=uid,
                       role="portfolio_management", is_active=1,
                       created_at=now, updated_at=now))
        s.add(CapitalMarketAssumption(
            id="cma-other", assumption_set_name="Other", version=1,
            valid_from="2026-01-01", is_current=0, created_by="creator",
            created_at=now, updated_at=now,
        ))
        s.commit()
        _activate(s, _draft(s, cma_id="cma-other"), today=date.today())

    with SF() as s:
        advisor = s.query(User).filter(User.id == advisor_id).one()
        with pytest.raises(HTTPException) as exc:
            finalize_recommendation(
                mandate_id=mid, run_id=run_id, request=_FakeRequest(),
                db=s, current_user=advisor,
            )
    assert exc.value.status_code == 422
    assert exc.value.detail["reason_code"] == svc.CMA_POLICY_MISSING
    with SF() as s:
        run = s.query(RecommendationRun).filter(RecommendationRun.id == run_id).one()
        assert run.result_status == "Draft"
        assert run.cma_policy_row_id is None
    engine.dispose()


# ── Schema-Quellen ───────────────────────────────────────────────────────


def _alembic_cfg(db_url):
    from alembic.config import Config as AlembicConfig

    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return cfg


def _sqlite_columns(db_path, table):
    with sqlite3.connect(str(db_path)) as conn:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _sqlite_triggers(db_path):
    with sqlite3.connect(str(db_path)) as conn:
        return {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' "
            "AND tbl_name='cma_policy_approvals'")}


_MODELS = {
    "cma_policies": CmaPolicy,
    "cma_policy_components": CmaPolicyComponent,
    "cma_policy_approvals": CmaPolicyApproval,
}


def test_fresh_bootstrap_matches_models(tmp_path):
    import database as db_module

    db_path = tmp_path / "fresh.db"
    db_module.bootstrap_sqlite_schema(db_path=db_path, schema_path=SCHEMA_FILE)
    for table, model in _MODELS.items():
        assert _sqlite_columns(db_path, table) == {c.name for c in model.__table__.columns}
    assert _sqlite_triggers(db_path) == APPROVAL_TRIGGERS


def test_runtime_patch_adds_run_column_and_triggers(tmp_path, monkeypatch):
    import database as db_module

    db_path = tmp_path / "legacy.db"
    db_module.bootstrap_sqlite_schema(db_path=db_path, schema_path=SCHEMA_FILE)
    with sqlite3.connect(str(db_path)) as conn:
        for trigger in APPROVAL_TRIGGERS:
            conn.execute(f"DROP TRIGGER {trigger}")
        conn.commit()
    engine = create_engine(f"sqlite:///{db_path}")
    monkeypatch.setattr(db_module, "engine", engine)
    db_module.ensure_runtime_columns()
    db_module.ensure_runtime_columns()  # idempotent
    engine.dispose()
    assert "cma_policy_row_id" in _sqlite_columns(db_path, "recommendation_runs")
    assert _sqlite_triggers(db_path) == APPROVAL_TRIGGERS


def test_alembic_chain_creates_tables_and_downgrade_reverts(tmp_path):
    from alembic import command
    from alembic.script import ScriptDirectory
    from sqlalchemy import inspect

    script = ScriptDirectory.from_config(_alembic_cfg("sqlite://"))
    heads = script.get_heads()
    assert len(heads) == 1, heads
    chain = {rev.revision for rev in script.walk_revisions("base", heads[0])}
    assert REVISION in chain

    db_path = tmp_path / "alembic.db"
    cfg = _alembic_cfg(f"sqlite:///{db_path}")
    command.upgrade(cfg, REVISION)
    engine = create_engine(f"sqlite:///{db_path}")
    inspector = inspect(engine)
    for table, model in _MODELS.items():
        assert {c["name"] for c in inspector.get_columns(table)} == {
            c.name for c in model.__table__.columns
        }
    assert "cma_policy_row_id" in {c["name"] for c in inspector.get_columns("recommendation_runs")}
    engine.dispose()
    assert _sqlite_triggers(db_path) == APPROVAL_TRIGGERS
    command.downgrade(cfg, f"{REVISION}-1")
    engine = create_engine(f"sqlite:///{db_path}")
    inspector = inspect(engine)
    assert not set(TABLES) & set(inspector.get_table_names())
    assert "cma_policy_row_id" not in {c["name"] for c in inspector.get_columns("recommendation_runs")}
    engine.dispose()


def test_alembic_emits_postgres_immutability():
    import io

    from alembic import command
    from alembic.script import ScriptDirectory

    down = ScriptDirectory.from_config(_alembic_cfg("sqlite://")).get_revision(REVISION).down_revision
    buffer = io.StringIO()
    cfg = _alembic_cfg("postgresql://user:pass@localhost/db")
    cfg.output_buffer = buffer
    command.upgrade(cfg, f"{down}:{REVISION}", sql=True)
    sql = buffer.getvalue()
    for table in TABLES:
        assert f"CREATE TABLE {table}" in sql
    assert "BEFORE UPDATE OR DELETE ON cma_policy_approvals" in sql
    assert "ADD COLUMN cma_policy_row_id" in sql


def test_tables_are_classified_global_reference():
    from services import tenant_scope_inventory as inventory

    for table in TABLES:
        assert table in inventory.GLOBAL_REFERENCE_PLAIN_TABLES
    assert inventory.inventory_problems(Base.metadata.tables) == []
