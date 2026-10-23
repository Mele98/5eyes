"""DSG-ERASURE-NEW-EVIDENCE-001: Freitext der seit #681 neu hinzugekommenen
append-only Evidence-Tabellen wird pro Kunde versiegelt (Crypto-Shredding).

* goal_revision_decisions.reason (GoalRevisionDecisionV1, #665)
* financial_coverage_attestations.household_persons_json (Personennamen) und
  .note (FinancialCoverageAttestationV1, #664)

Beide Tabellen verbieten UPDATE/DELETE per Trigger. Bisher standen Begruendung,
Namen und Notiz im Klartext in der Zeile UND im replaybaren audit_log-Snapshot
-- nach einer DSG-Art.-32-Loeschung unloeschbar.

Vertrag (wie tests/test_dsg_erasure_append_only_tables.py):
* nach ``erase_client_personal_data`` findet ein Scan ueber jede Textspalte
  jeder Tabelle keinen Klartext mehr;
* die Record-Hashes verifizieren weiter (der Hash bindet den Umschlag);
* UPDATE/DELETE bleiben verboten;
* vor der Erasure bleibt der Freitext ueber den Vault lesbar, danach zeigt
  die Berater-Sicht einen Platzhalter.
"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import models.client_login  # noqa: F401
from database import Base, ensure_audit_log_triggers
from services.client_erasure import REDACTION_MARKER, erase_client_personal_data
from services.postgres_rls import import_tenant_models

import_tenant_models()

from models.mandates import Mandate  # noqa: E402
from models.review import AuditLog  # noqa: E402
from models.wealth import FinancialCoverageAttestation, Goal, GoalRevisionDecision  # noqa: E402
from services import financial_coverage_attestation as fca  # noqa: E402
from services import goal_revision_decision as revision  # noqa: E402
from tests.test_goal_revision_decision import REASON, _allocation, _db_goal, _post  # noqa: E402
from tests.test_risk_capacity_plausibility import TODAY, _cashflow, _seed  # noqa: E402

PERSONS = ["Beat Beispielmann", "Carla Beispielfrau"]
NOTE = "Tochter Lea studiert in Bern, Unterhalt bis 2028 vereinbart"
ERASURE_REASON = "Kunde verlangt Loeschung seiner Personendaten gemaess DSG Art. 32."
NEEDLES = (REASON, "Beispielmann", "Beispielfrau", "Tochter Lea")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'dsg_new_evidence.db'}",
        connect_args={"check_same_thread": False},
    )
    sf = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    ensure_audit_log_triggers(engine)
    try:
        yield sf
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _post_attestation(session, advisor):
    from schemas.wealth import FinancialCoverageAttestationCreate
    from routers.wealth import create_financial_coverage_attestation

    return create_financial_coverage_attestation(
        mandate_id="m-rcp",
        body=FinancialCoverageAttestationCreate(
            household_persons=PERSONS, income_complete=True, expenses_complete=True,
            obligations_complete=True, irregular_expenses_reviewed=True,
            as_of_date=TODAY.isoformat(), source="Kundengespräch", note=NOTE,
        ),
        db=session, current_user=advisor,
    )


def _seed_all(session):
    advisor = _seed(session)
    session.add_all([_cashflow("salary", "Income", 15_000), _cashflow("living", "Expense", 4_000)])
    session.commit()
    goal = _db_goal(session)
    _allocation(session, goal)
    _post(session, advisor, REASON)
    _post_attestation(session, advisor)
    session.expire_all()
    return advisor


def _all_text_values(session):
    tables = [
        r[0] for r in session.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        ).all()
    ]
    for table in tables:
        cols = [r[1] for r in session.execute(text(f'PRAGMA table_info("{table}")')).all()]
        for row in session.execute(text(f'SELECT * FROM "{table}"')).all():
            for col, value in zip(cols, row):
                if isinstance(value, str):
                    yield table, col, value


def _plaintext_hits(session, *, tables=None):
    return sorted({
        (table, col)
        for table, col, value in _all_text_values(session)
        if (tables is None or table in tables) and any(n in value for n in NEEDLES)
    })


def _decision(session) -> GoalRevisionDecision:
    return session.query(GoalRevisionDecision).filter_by(goal_id="g-far").one()


def _attestation(session) -> FinancialCoverageAttestation:
    return session.query(FinancialCoverageAttestation).filter_by(mandate_id="m-rcp").one()


# ---------------------------------------------------------------------------
# Kein Klartext in append-only Zeilen und Audit-Snapshots
# ---------------------------------------------------------------------------


def test_new_evidence_rows_and_audit_snapshots_carry_no_plaintext(session_factory):
    from services.pii_vault import is_sealed, reveal

    with session_factory() as session:
        _seed_all(session)

        assert _plaintext_hits(
            session,
            tables={"goal_revision_decisions", "financial_coverage_attestations", "audit_log"},
        ) == []

        decision = _decision(session)
        attestation = _attestation(session)
        assert is_sealed(decision.reason)
        assert is_sealed(attestation.household_persons_json)
        assert is_sealed(attestation.note)
        assert revision.verify_decision(decision)
        assert fca.verify_attestation(attestation)

        # Lesbar ueber den Vault (Berater-Sicht), solange der Schluessel lebt.
        assert reveal(session, decision.reason) == REASON
        assert json.loads(reveal(session, attestation.household_persons_json)) == PERSONS
        assert reveal(session, attestation.note) == NOTE
        view = revision.goal_revision_view(session.get(Goal, "g-far"), decision, session)
        assert view["reason"] == REASON and view["active"] is True

        # Personenzahl ist strukturiert und hash-gebunden; die Bestaetigung gilt.
        assert attestation.household_person_count == len(PERSONS)
        status = fca.resolve_attestation(session, session.get(Mandate, "m-rcp"), today=TODAY)
        assert status["status"] == fca.STATUS_VALID

        # Audit-Snapshots binden den Umschlag (replaybar gegen den Hash).
        snapshots = {
            entry.table_name: json.loads(entry.new_value)
            for entry in session.query(AuditLog).filter(
                AuditLog.table_name.in_(["goal_revision_decisions", "financial_coverage_attestations"])
            ).all()
        }
        assert snapshots["goal_revision_decisions"]["reason"] == decision.reason
        assert snapshots["financial_coverage_attestations"]["note"] == attestation.note


def test_erasure_leaves_no_plaintext_hashes_verify_and_tables_stay_immutable(session_factory):
    from services.pii_vault import reveal

    with session_factory() as session:
        _seed_all(session)
        decision_hash = _decision(session).decision_hash
        attestation_hash = _attestation(session).attestation_hash

        summary = erase_client_personal_data(session, "cl-rcp", reason=ERASURE_REASON)
        session.commit()
        session.expire_all()

        assert summary["unsealed_append_only_rows"] == {}
        # Kern-Nachweis: in KEINER Textspalte KEINER Tabelle mehr Klartext.
        assert _plaintext_hits(session) == []

        decision = _decision(session)
        attestation = _attestation(session)
        assert decision.decision_hash == decision_hash
        assert attestation.attestation_hash == attestation_hash
        assert revision.verify_decision(decision)
        assert fca.verify_attestation(attestation)
        assert reveal(session, decision.reason) is None
        assert reveal(session, attestation.household_persons_json) is None
        assert reveal(session, attestation.note) is None

        # Berater-Sicht: Platzhalter statt Umschlag/Klartext, Hash-Status bleibt.
        view = revision.goal_revision_view(session.get(Goal, "g-far"), decision, session)
        assert view["reason"] == REDACTION_MARKER
        assert view["validity"] == "valid"

        for table in ("goal_revision_decisions", "financial_coverage_attestations", "audit_log"):
            with pytest.raises(Exception, match="immutable"):
                session.execute(text(f"UPDATE {table} SET created_at = 'x'"))
            session.rollback()
            with pytest.raises(Exception, match="immutable"):
                session.execute(text(f"DELETE FROM {table}"))
            session.rollback()


def test_after_erasure_new_free_text_is_refused_not_stored_in_plaintext(session_factory):
    from types import SimpleNamespace

    from services.pii_vault import PiiVaultError

    with session_factory() as session:
        advisor = _seed(session)
        erase_client_personal_data(session, "cl-rcp", reason=ERASURE_REASON)
        session.commit()
        with pytest.raises(PiiVaultError):
            fca.create_attestation(
                session, SimpleNamespace(id="m-rcp", client_id="cl-rcp"), actor=advisor,
                household_persons=PERSONS, income_complete=True, expenses_complete=True,
                obligations_complete=True, irregular_expenses_reviewed=True,
                as_of_date=TODAY.isoformat(), source="Kundengespräch", note=NOTE, today=TODAY,
            )
        session.rollback()
        assert session.query(FinancialCoverageAttestation).count() == 0
        assert _plaintext_hits(session) == []


def test_legacy_v1_plaintext_attestation_stays_valid_and_is_reported(session_factory):
    """Altbestand (FinancialCoverageAttestationV1, Klartext) bleibt mit dem
    V1-Hashvertrag verifizierbar und wird von der Erasure gemeldet -- pro
    Tabelle EINMAL je Zeile, auch wenn zwei Spalten Klartext tragen."""
    with session_factory() as session:
        advisor = _seed(session)
        fingerprint, count = fca.current_cashflow_fingerprint(session, "cl-rcp")
        row = {
            "id": "legacy-a1", "schema_version": "FinancialCoverageAttestationV1",
            "mandate_id": "m-rcp", "client_id": "cl-rcp",
            "household_persons_json": json.dumps(PERSONS, separators=(",", ":"), ensure_ascii=False),
            "income_complete": 1, "expenses_complete": 1, "obligations_complete": 1,
            "irregular_expenses_reviewed": 1, "as_of_date": TODAY.isoformat(),
            "source": "Kundengespräch", "note": NOTE, "cashflow_fingerprint": fingerprint,
            "cashflow_row_count": count, "actor_id": advisor.id,
            "attested_at": "2026-10-18T09:00:00.000Z", "policy_version": fca.POLICY_VERSION,
        }
        row["attestation_hash"] = fca.compute_attestation_hash(row)
        assert fca.verify_attestation(row)
        cols = list(row) + ["created_at"]
        session.execute(
            text(
                f"INSERT INTO financial_coverage_attestations ({', '.join(cols)}) "
                f"VALUES ({', '.join(':' + c for c in cols)})"
            ),
            {**row, "created_at": row["attested_at"]},
        )
        session.commit()
        status = fca.resolve_attestation(session, session.get(Mandate, "m-rcp"), today=TODAY)
        assert status["status"] == fca.STATUS_VALID

        summary = erase_client_personal_data(session, "cl-rcp", reason=ERASURE_REASON)
        session.commit()
        assert summary["unsealed_append_only_rows"] == {"financial_coverage_attestations": 1}


def test_sealed_columns_registry_covers_new_tables():
    from services.pii_vault import SEALED_APPEND_ONLY_COLUMNS

    assert ("goal_revision_decisions", "reason") in SEALED_APPEND_ONLY_COLUMNS
    assert ("financial_coverage_attestations", "household_persons_json") in SEALED_APPEND_ONLY_COLUMNS
    assert ("financial_coverage_attestations", "note") in SEALED_APPEND_ONLY_COLUMNS


# ---------------------------------------------------------------------------
# Schema: household_person_count in ORM, Bootstrap-SQL, Runtime-Patch, Alembic
# ---------------------------------------------------------------------------

PERSON_COUNT_REVISION = "c4d9e2a7f1b6"
FCA_TRIGGERS = {
    "trg_financial_coverage_attestations_no_update",
    "trg_financial_coverage_attestations_no_delete",
}


def _fca_columns_and_triggers(db_path):
    import sqlite3

    with sqlite3.connect(str(db_path)) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(financial_coverage_attestations)")}
        triggers = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger' "
                "AND tbl_name='financial_coverage_attestations'"
            )
        }
    return cols, triggers


def _alembic_cfg(db_url):
    from pathlib import Path

    from alembic.config import Config as AlembicConfig

    root = Path(__file__).resolve().parents[1]
    cfg = AlembicConfig(str(root / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    cfg.set_main_option("script_location", str(root / "alembic"))
    return cfg


def test_person_count_column_in_bootstrap_and_runtime_patch(tmp_path, monkeypatch):
    import sqlite3
    from pathlib import Path

    import database as db_module

    model_cols = {c.name for c in FinancialCoverageAttestation.__table__.columns}
    assert "household_person_count" in model_cols
    schema = Path(__file__).resolve().parents[1] / "5eyes_schema_v4.0_FINAL.sql"
    fresh = tmp_path / "fresh.db"
    db_module.bootstrap_sqlite_schema(db_path=fresh, schema_path=schema)
    assert _fca_columns_and_triggers(fresh) == (model_cols, FCA_TRIGGERS)

    # Bestands-DB mit V1-Tabelle (ohne Spalte): Runtime-Patch ergaenzt sie,
    # Trigger bleiben, idempotent.
    legacy = tmp_path / "legacy.db"
    db_module.bootstrap_sqlite_schema(db_path=legacy, schema_path=schema)
    with sqlite3.connect(str(legacy)) as conn:
        conn.execute("ALTER TABLE financial_coverage_attestations DROP COLUMN household_person_count")
        conn.commit()
    assert "household_person_count" not in _fca_columns_and_triggers(legacy)[0]
    engine = create_engine(f"sqlite:///{legacy}")
    monkeypatch.setattr(db_module, "engine", engine)
    db_module.ensure_runtime_columns()
    db_module.ensure_runtime_columns()
    engine.dispose()
    assert _fca_columns_and_triggers(legacy) == (model_cols, FCA_TRIGGERS)


def test_alembic_person_count_revision_chain_upgrade_and_downgrade(tmp_path):
    from alembic import command
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_alembic_cfg("sqlite://"))
    heads = script.get_heads()
    assert len(heads) == 1, heads
    chain = {rev.revision for rev in script.walk_revisions("base", heads[0])}
    assert PERSON_COUNT_REVISION in chain
    assert script.get_revision(PERSON_COUNT_REVISION).down_revision == "a3f6c1e8d924"

    db_path = tmp_path / "alembic.db"
    cfg = _alembic_cfg(f"sqlite:///{db_path}")
    command.upgrade(cfg, PERSON_COUNT_REVISION)
    cols, triggers = _fca_columns_and_triggers(db_path)
    assert "household_person_count" in cols and triggers == FCA_TRIGGERS
    command.downgrade(cfg, "a3f6c1e8d924")
    cols, triggers = _fca_columns_and_triggers(db_path)
    # Downgrade ohne Tabellen-Neubau: Immutability-Trigger ueberleben.
    assert "household_person_count" not in cols and triggers == FCA_TRIGGERS
