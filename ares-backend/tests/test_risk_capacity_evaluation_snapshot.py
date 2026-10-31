"""RISK-CAPACITY-EVALUATION-SNAPSHOT-001: RiskCapacityPlausibilityEvaluationV1.

Residual der Codex-Closure-Reviews PR #647/#653/#677: die Plausibilitaets-
pruefung der Risikofaehigkeit lief nur live und ungehasht. Spaetere
Datenaenderungen veraenderten nachtraeglich, was bei der Beratung galt.

Vertrag:

* Speichern des Risikoprofils und Generierung der Soll-Allokation binden
  genau die angezeigte Bewertung als append-only Zeile (Eingaben,
  Regelversion, Ergebnis, kanonischer Hash), mandantengetrennt.
* Replay prueft den Hash, rechnet das Ergebnis aus den gespeicherten Eingaben
  neu und erkennt Manipulation bzw. Abweichung.
* Neue Daten oder ein neues Profil machen die Evidenz sichtbar "neu zu
  pruefen"; die alte Zeile bleibt bytegleich.
* Kein Freitext (Ziel-Bezeichnungen) in der append-only Evidenz.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import text

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from models.mandates import Mandate  # noqa: E402
from models.profiling import RiskCapacityPlausibilityEvaluation as Row  # noqa: E402
from models.wealth import Goal  # noqa: E402
from services import risk_capacity_evaluation_snapshot as rces  # noqa: E402
from services import risk_capacity_plausibility as rcp  # noqa: E402
from tests.test_risk_capacity_plausibility import (  # noqa: E402,F401
    NOW,
    _cashflow,
    _FakeRequest,
    _position,
    _risk_body,
    _seed,
    session_factory,
)

TABLE = "risk_capacity_plausibility_evaluations"


def _seed_inconsistent(session):
    advisor = _seed(session)
    session.add_all([
        _cashflow("salary", "Income", 7_000),
        _cashflow("living", "Expense", 6_500),
        _position("depot", "Depot", "Beratungsvermögen", 150_000),
    ])
    session.commit()
    return advisor


def _save_profile(session, advisor):
    from routers.profiling import create_risk_assessment

    return create_risk_assessment(
        mandate_id="m-rcp", body=_risk_body(), request=_FakeRequest(), db=session,
        current_user=advisor,
    )


def _rows(session):
    return session.query(Row).order_by(Row.evaluated_at).all()


def _get(session, advisor):
    from routers.profiling import get_risk_capacity_plausibility

    return get_risk_capacity_plausibility(mandate_id="m-rcp", db=session, current_user=advisor)


def _list(session, advisor):
    from routers.profiling import list_risk_capacity_plausibility_evaluations

    return list_risk_capacity_plausibility_evaluations(
        mandate_id="m-rcp", db=session, current_user=advisor,
    )


def _tamper(session, sql, **params):
    session.execute(text(f"DROP TRIGGER trg_{TABLE}_no_update"))
    session.execute(text(sql), params)
    session.commit()
    session.expire_all()


# ---------------------------------------------------------------------------
# Bindung beim Speichern des Risikoprofils und bei der Generierung
# ---------------------------------------------------------------------------

def test_saving_risk_profile_binds_the_shown_evaluation_as_snapshot(session_factory):
    with session_factory() as session:
        advisor = _seed_inconsistent(session)
        ra = _save_profile(session, advisor)

        rows = _rows(session)
        assert len(rows) == 1
        row = rows[0]
        assert row.schema_version == rces.SCHEMA_VERSION
        assert row.binding_context == rces.CONTEXT_RISK_ASSESSMENT_SAVED
        assert row.binding_record_id == ra.id
        assert row.assessment_id == ra.id
        assert (row.mandate_id, row.client_id, row.actor_id) == ("m-rcp", "cl-rcp", advisor.id)
        assert row.rules_version == rcp.PLAUSIBILITY_RULES_VERSION
        assert row.status == "inconsistent"
        assert row.snapshot_hash == rces.compute_snapshot_hash(row)

        inputs = json.loads(row.inputs_json)
        assert inputs["rules_version"] == rcp.PLAUSIBILITY_RULES_VERSION
        assert inputs["thresholds"] == json.loads(json.dumps(rcp.THRESHOLDS))
        assert inputs["recorded"]["gross_income_monthly_rappen"] == 7_000 * 100
        assert inputs["declared"]["income_band"] == 3
        result = json.loads(row.result_json)
        assert result["reason_code"] == rcp.REASON_CODE
        assert {f["check"] for f in result["findings"]} >= {rcp.CHECK_INCOME, rcp.CHECK_OBLIGATIONS}

        # Dieselbe Bewertung wie im Audit-Log (kein zweiter, abweichender Lauf).
        from tests.test_risk_capacity_plausibility import _plausibility_audit_rows

        audit = json.loads(_plausibility_audit_rows(session)[0].new_value)
        assert audit["evaluation_hash"] == row.evaluation_hash


def test_consistent_evaluation_is_bound_too(session_factory):
    """Auch ``consistent`` ist Evidenz -- nicht nur Widersprueche."""
    from datetime import date

    from services.financial_coverage_attestation import create_attestation

    with session_factory() as session:
        advisor = _seed(session)
        session.add_all([
            _cashflow("salary", "Income", 15_000),
            _cashflow("living", "Expense", 4_000),
            _position("depot", "Depot", "Beratungsvermögen", 1_500_000),
        ])
        session.commit()
        create_attestation(
            session, session.get(Mandate, "m-rcp"), actor=advisor,
            household_persons=["Max Muster"], income_complete=True,
            expenses_complete=True, obligations_complete=True,
            irregular_expenses_reviewed=True, as_of_date=date.today().isoformat(),
            source="Kundengespräch",
        )
        session.commit()
        _save_profile(session, advisor)
        rows = _rows(session)
        assert [r.status for r in rows] == ["consistent"]
        inputs = json.loads(rows[0].inputs_json)
        assert inputs["coverage_attestation"]["status"] == "valid"
        assert inputs["coverage_attestation"]["attestation_hash"]


def test_generation_binds_snapshot_to_new_target_allocation(session_factory, monkeypatch):
    import routers.allocation as allocation_router

    with session_factory() as session:
        advisor = _seed_inconsistent(session)
        ra = _save_profile(session, advisor)
        monkeypatch.setattr(
            allocation_router, "generate_target_allocation",
            lambda **kwargs: {
                "target_allocation": SimpleNamespace(id="ta-rcp"),
                "risk_assessment": ra,
                "reasoning": ["Ausgangspunkt ist die House Matrix fuer Score 7."],
            },
        )
        monkeypatch.setattr(allocation_router, "refresh_system_review_triggers", lambda *a, **k: None)
        monkeypatch.setattr(session, "refresh", lambda obj: None)
        result = allocation_router.generate_target_allocation_endpoint(
            mandate_id="m-rcp", body=allocation_router.TargetAllocationGenerateRequest(),
            request=_FakeRequest(), db=session, current_user=advisor,
        )
        rows = [r for r in _rows(session) if r.binding_context == rces.CONTEXT_ALLOCATION_GENERATED]
        assert len(rows) == 1
        assert rows[0].binding_record_id == "ta-rcp"
        assert rows[0].assessment_id == ra.id
        reference = result["risk_capacity_plausibility"]["evaluation_snapshot"]
        assert reference["evaluation_id"] == rows[0].id
        assert reference["snapshot_hash"] == rows[0].snapshot_hash
        assert rows[0].evaluation_hash == result["risk_capacity_plausibility"]["evaluation_hash"]


def test_snapshot_rows_are_append_only(session_factory):
    from sqlalchemy.exc import DatabaseError

    with session_factory() as session:
        advisor = _seed_inconsistent(session)
        _save_profile(session, advisor)
        with pytest.raises(DatabaseError, match="immutable"):
            session.execute(text(f"UPDATE {TABLE} SET status='consistent'"))
        session.rollback()
        with pytest.raises(DatabaseError, match="immutable"):
            session.execute(text(f"DELETE FROM {TABLE}"))
        session.rollback()
        assert len(_rows(session)) == 1


def test_goal_labels_are_never_persisted(session_factory):
    with session_factory() as session:
        advisor = _seed_inconsistent(session)
        session.add(Goal(
            id="g-near", mandate_id="m-rcp", client_id="cl-rcp", goal_family="Konsum",
            goal_type="Einmalige Ausgabe", label="Ferienhaus Engadin Privatname",
            rank=1, goal_scope="Beratungsvermögen", value_mode="nominal",
            target_amount_rappen=120_000 * 100, target_date="2027-06-30",
            hardness="Primär", created_at=NOW, updated_at=NOW,
        ))
        session.commit()
        _save_profile(session, advisor)
        row = _rows(session)[0]
        assert "Ferienhaus" not in row.inputs_json
        assert "Ferienhaus" not in row.result_json
        assert json.loads(row.inputs_json)["recorded"]["near_term_goal_need_rappen"] == 120_000 * 100


# ---------------------------------------------------------------------------
# Replay: Manipulation, Abweichung, Aktualitaet
# ---------------------------------------------------------------------------

def test_untouched_snapshot_replays_verified_and_current(session_factory):
    with session_factory() as session:
        advisor = _seed_inconsistent(session)
        _save_profile(session, advisor)
        bound = _get(session, advisor)["bound_evaluation"]
        assert bound["integrity"] == rces.INTEGRITY_VERIFIED
        assert bound["currency"] == rces.CURRENCY_CURRENT
        assert bound["needs_recheck"] is False
        assert bound["stale_reasons"] == []
        assert bound["evaluation_id"] == _rows(session)[0].id


def test_data_change_marks_bound_evaluation_recheck_and_never_overwrites(session_factory):
    with session_factory() as session:
        advisor = _seed_inconsistent(session)
        _save_profile(session, advisor)
        before = _rows(session)[0]
        frozen = (before.id, before.snapshot_hash, before.inputs_json, before.result_json)

        session.add(_cashflow("bonus", "Income", 20_000))
        session.commit()

        live = _get(session, advisor)
        bound = live["bound_evaluation"]
        assert bound["integrity"] == rces.INTEGRITY_VERIFIED
        assert bound["needs_recheck"] is True
        assert bound["currency"] == rces.CURRENCY_STALE
        assert rces.STALE_INPUTS_CHANGED in bound["stale_reasons"]
        assert bound["recheck_code"] == rces.RECHECK_CODE
        assert bound["recheck_label"] == "neu zu prüfen"

        session.expire_all()
        rows = _rows(session)
        assert len(rows) == 1
        after = rows[0]
        assert (after.id, after.snapshot_hash, after.inputs_json, after.result_json) == frozen
        # Die damalige Bewertung bleibt die damalige.
        assert after.status == "inconsistent"


def test_new_risk_profile_marks_old_snapshot_recheck(session_factory):
    with session_factory() as session:
        advisor = _seed_inconsistent(session)
        _save_profile(session, advisor)
        first = _rows(session)[0]
        _save_profile(session, advisor)

        listing = _list(session, advisor)
        by_id = {e["evaluation_id"]: e for e in listing["evaluations"]}
        assert len(by_id) == 2
        old = by_id[first.id]
        assert old["needs_recheck"] is True
        assert rces.STALE_ASSESSMENT_CHANGED in old["stale_reasons"]
        newest = listing["evaluations"][0]
        assert newest["risk_assessment_id"] == listing["current_risk_assessment_id"]
        assert newest["needs_recheck"] is False


def test_tampered_status_is_detected_by_hash(session_factory):
    with session_factory() as session:
        advisor = _seed_inconsistent(session)
        _save_profile(session, advisor)
        _tamper(session, f"UPDATE {TABLE} SET status='consistent'")
        bound = _get(session, advisor)["bound_evaluation"]
        assert bound["integrity"] == rces.INTEGRITY_HASH_MISMATCH
        assert bound["needs_recheck"] is True
        assert rces.STALE_INTEGRITY in bound["stale_reasons"]


def test_rehashed_forged_result_is_detected_by_rule_replay(session_factory):
    """Ein Angreifer mit DB-Zugriff faelscht Ergebnis UND Hash: das
    Nachrechnen aus den gespeicherten Eingaben deckt es auf."""
    with session_factory() as session:
        advisor = _seed_inconsistent(session)
        _save_profile(session, advisor)
        row = _rows(session)[0]
        forged = json.loads(row.result_json)
        forged.update(status="consistent", reason_code=None, findings=[])
        forged_json = json.dumps(forged, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        payload = rces.snapshot_payload(row)
        payload.update(status="consistent", result_json=forged_json)
        forged_hash = rces.compute_snapshot_hash(payload)
        _tamper(
            session,
            f"UPDATE {TABLE} SET status='consistent', result_json=:r, snapshot_hash=:h",
            r=forged_json, h=forged_hash,
        )
        bound = _get(session, advisor)["bound_evaluation"]
        assert bound["integrity"] == rces.INTEGRITY_RESULT_MISMATCH
        assert bound["needs_recheck"] is True


def test_rules_version_change_is_not_replayed_as_verified(session_factory, monkeypatch):
    with session_factory() as session:
        advisor = _seed_inconsistent(session)
        _save_profile(session, advisor)
        monkeypatch.setattr(rcp, "PLAUSIBILITY_RULES_VERSION", "RCP-test-next")
        row = _rows(session)[0]
        assert rces.verify_integrity(row, session.get(Mandate, "m-rcp")) == rces.INTEGRITY_RULES_CHANGED


def test_foreign_mandate_snapshot_is_neither_listed_nor_verified(session_factory):
    with session_factory() as session:
        advisor = _seed_inconsistent(session)
        _save_profile(session, advisor)
        own = _rows(session)[0]
        other = SimpleNamespace(id="m-other", client_id="cl-other", tenant_id=None)
        assert rces.list_snapshots(session, other) == []
        assert rces.verify_integrity(own, other) == rces.INTEGRITY_BINDING_MISMATCH
        tenant_b = SimpleNamespace(id="m-rcp", client_id="cl-rcp", tenant_id="tenant-b")
        assert rces.list_snapshots(session, tenant_b) == []
        assert rces.verify_integrity(own, tenant_b) == rces.INTEGRITY_BINDING_MISMATCH


def test_snapshot_binds_mandate_tenant_in_hash(session_factory):
    with session_factory() as session:
        advisor = _seed_inconsistent(session)
        mandate = session.get(Mandate, "m-rcp")
        result = rcp.evaluate_mandate_safely(session, mandate, None)
        tenant_mandate = SimpleNamespace(id="m-rcp", client_id="cl-rcp", tenant_id="tenant-a")
        row = rces.record_snapshot(
            session, tenant_mandate, None, result, {}, actor=advisor,
            binding_context=rces.CONTEXT_RISK_ASSESSMENT_SAVED, binding_record_id="ra-x",
        )
        assert row.tenant_id == "tenant-a"
        assert rces.snapshot_payload(row)["tenant_id"] == "tenant-a"
        # Fehlerpfad ohne auswertbare Eingaben: belegt, aber nicht nachrechenbar.
        assert row.inputs_json is None and row.status == "not_evaluable"
        assert rces.verify_integrity(row, tenant_mandate) == rces.INTEGRITY_NOT_REPLAYABLE
        with pytest.raises(ValueError):
            rces.record_snapshot(
                session, tenant_mandate, None, result, {}, actor=advisor,
                binding_context="anything", binding_record_id="x",
            )


def test_rule_replay_reproduces_every_stored_status(session_factory):
    """Positivkontrolle der Replay-Funktion selbst: fuer partial,
    inconsistent und consistent reproduziert sie das gespeicherte Ergebnis."""
    from tests.test_risk_capacity_plausibility import _declared, _recorded

    cases = [
        (_declared(), _recorded()),
        (_declared(), _recorded(recurring_expense_monthly_rappen=20_000 * 100)),
        (_declared(), _recorded(expense_cashflow_count=0, recurring_expense_monthly_rappen=0)),
    ]
    statuses = set()
    for declared, recorded in cases:
        captured = {"declared": declared, "recorded": recorded, "as_of_date": "2026-10-18",
                    "coverage_attestation": {}}
        inputs = rces.inputs_payload(captured)
        stored = rces.structured_result(rcp.assess_plausibility(declared, recorded))
        statuses.add(stored["status"])
        assert rces._recompute_from_inputs(json.loads(json.dumps(inputs))) == json.loads(json.dumps(stored))
    assert len(statuses) >= 2


# ---------------------------------------------------------------------------
# Schema-Quellen (ORM, Bootstrap, Runtime-Patch, Alembic, Mandanten-Inventar)
# ---------------------------------------------------------------------------

SCHEMA_FILE = BACKEND_ROOT / "ares_schema.sql"
REVISION = "a7c4e9b2d1f3"
TRIGGERS = {f"trg_{TABLE}_no_update", f"trg_{TABLE}_no_delete"}
MODEL_COLUMNS = {c.name for c in Row.__table__.columns}


def _sqlite_columns(db_path):
    with sqlite3.connect(str(db_path)) as conn:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({TABLE})")}


def _sqlite_triggers(db_path):
    with sqlite3.connect(str(db_path)) as conn:
        return {row[0] for row in conn.execute(
            f"SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='{TABLE}'")}


def _alembic_cfg(db_url):
    from alembic.config import Config as AlembicConfig

    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return cfg


def test_fresh_bootstrap_has_table_and_triggers(tmp_path):
    import database as db_module

    db_path = tmp_path / "fresh.db"
    db_module.bootstrap_sqlite_schema(db_path=db_path, schema_path=SCHEMA_FILE)
    assert _sqlite_columns(db_path) == MODEL_COLUMNS
    assert _sqlite_triggers(db_path) == TRIGGERS
    with sqlite3.connect(str(db_path)) as conn:
        targets = {row[2] for row in conn.execute(f"PRAGMA foreign_key_list({TABLE})")}
    assert targets == {"users"}
    assert {fk.column.table.name for fk in Row.__table__.foreign_keys} == {"users"}


def test_runtime_patch_creates_table_on_legacy_db(tmp_path, monkeypatch):
    import database as db_module
    from sqlalchemy import create_engine

    db_path = tmp_path / "legacy.db"
    db_module.bootstrap_sqlite_schema(db_path=db_path, schema_path=SCHEMA_FILE)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(f"DROP TABLE {TABLE}")
        conn.commit()
    engine = create_engine(f"sqlite:///{db_path}")
    monkeypatch.setattr(db_module, "engine", engine)
    db_module.ensure_runtime_columns()
    db_module.ensure_runtime_columns()  # idempotent
    engine.dispose()
    assert _sqlite_columns(db_path) == MODEL_COLUMNS
    assert _sqlite_triggers(db_path) == TRIGGERS


def test_alembic_chain_creates_table_and_downgrade_reverts(tmp_path):
    from alembic import command
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine, inspect

    script = ScriptDirectory.from_config(_alembic_cfg("sqlite://"))
    heads = script.get_heads()
    assert len(heads) == 1, heads
    chain = {rev.revision for rev in script.walk_revisions("base", heads[0])}
    assert REVISION in chain

    db_path = tmp_path / "alembic.db"
    cfg = _alembic_cfg(f"sqlite:///{db_path}")
    command.upgrade(cfg, REVISION)
    engine = create_engine(f"sqlite:///{db_path}")
    assert {c["name"] for c in inspect(engine).get_columns(TABLE)} == MODEL_COLUMNS
    engine.dispose()
    assert _sqlite_triggers(db_path) == TRIGGERS
    command.downgrade(cfg, f"{REVISION}-1")
    engine = create_engine(f"sqlite:///{db_path}")
    assert TABLE not in inspect(engine).get_table_names()
    engine.dispose()


def test_alembic_emits_postgres_immutability_and_tenant_guard():
    import io

    from alembic import command
    from alembic.script import ScriptDirectory

    down = ScriptDirectory.from_config(_alembic_cfg("sqlite://")).get_revision(REVISION).down_revision
    buffer = io.StringIO()
    cfg = _alembic_cfg("postgresql://user:pass@localhost/db")
    cfg.output_buffer = buffer
    command.upgrade(cfg, f"{down}:{REVISION}", sql=True)
    sql = buffer.getvalue()
    assert f"CREATE TABLE {TABLE}" in sql
    assert f"BEFORE UPDATE OR DELETE ON {TABLE}" in sql
    assert f"trg_{TABLE}_tenant_guard" in sql


def test_table_is_tenant_direct_in_rls_plan():
    from database import Base
    from services import tenant_scope_inventory as inventory
    from services.postgres_rls import tenant_scoped_table_names

    assert TABLE in inventory.TENANT_DIRECT_TABLES
    assert TABLE in tenant_scoped_table_names()
    assert inventory.inventory_problems(Base.metadata.tables) == []
