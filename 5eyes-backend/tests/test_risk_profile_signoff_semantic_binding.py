"""RISK-OVERRIDE-WRITE-BOUNDARY-001 / PG-002 (Codex-Closure-Review PR #662).

A) Semantischer Binding-Verifier: der Zeilenhash beweist nur, dass die
   Signoff-Zeile unveraendert ist. Ein Signoff gilt erst als gueltig, wenn
   Input-Hash, Final-/Effective-Werte, Override, Mandat, Client, Tenant,
   Decision und optionales Dokument noch zum Assessment passen. Jede
   Abweichung -> ``integrity_mismatch`` (API, Strategie, PDF-Zeilen).
B) Direkte Mandantenbindung der Evidence-Tabellen: tenant_id aus dem Mandat,
   V2-Hash bindet ihn, die DB weist widerspruechliche Kombinationen ab,
   V1-Altzeilen bleiben verifizierbar. Migration entlang der Kette.

Die PostgreSQL-Live-Pruefung (FORCE RLS, Nicht-Owner-Rolle, zwei Tenants)
liegt in ``tests/test_postgres_risk_evidence_tenant_boundary_live.py``.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from models.profiling import RiskAssessment, RiskOverrideDecision, RiskProfileSignoff
from routers import profiling as profiling_router
from routers.profiling import RiskProfileSignRequest
from services import risk_evidence_tenant_boundary as retb
from services import risk_override_decision as decision_service
from services import risk_profile_signoff as signoff_service
from services import tenant_scope_inventory as inventory
from services.postgres_rls import tenant_scoped_table_names
from services.risk_override_decision import resolve_assessment_decision
from services.risk_profile_signoff import (
    STATE_INTEGRITY_MISMATCH,
    STATUS_SIGNED,
    build_signoff_view,
    signoff_view_lines,
)
from tests.test_risk_capacity_plausibility import (
    NOW,
    _FakeRequest,
    _seed,
    session_factory,  # noqa: F401 - pytest fixture re-export
)
from tests.test_risk_override_current_gate_decision_log import _assessment, _override

BACKEND_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_REVISION = "b5d2e8f41a73"
MIGRATION_DOWN_REVISION = "3960ca037812"


def _sign(session, advisor, body=None):
    return profiling_router.sign_risk_profile(
        mandate_id="m-rcp", request=_FakeRequest(), body=body, db=session, current_user=advisor,
    )


def _fresh(session, ra_id="ra-current") -> RiskAssessment:
    session.expire_all()
    return session.get(RiskAssessment, ra_id)


def _lines(view) -> str:
    return " ".join(text_ for _, text_ in signoff_view_lines(view))


@pytest.fixture
def seeded(session_factory):  # noqa: F811
    with session_factory() as session:
        advisor = _seed(session)
        session.add(_assessment("ra-current", advisor.id, version=1, is_current=1))
        session.commit()
        yield session, advisor


def _assert_mismatch(session, expected: str) -> dict:
    from services.allocation_messages import WARN_OVERRIDE, classify_messages

    ra = _fresh(session)
    view = build_signoff_view(session, ra)
    assert view["state"] == STATE_INTEGRITY_MISMATCH
    assert view["signoff_verified"] is False
    assert view["signoff_binding_verified"] is False
    assert expected in view["integrity_mismatches"], view["integrity_mismatches"]
    joined = _lines(view)
    assert "Hash verifiziert" not in joined
    assert "Fachliche Bindung NICHT verifiziert" in joined
    # API (ORM-Property) und Strategie-Meldung nutzen denselben Verifier.
    assert ra.signoff_state == STATE_INTEGRITY_MISMATCH
    if int(ra.is_overridden or 0) == 1 and ra.override_score_x10 is not None:
        msg = [m for m in classify_messages(None, [], "optimal", None, ra) if m["code"] == WARN_OVERRIDE][0]
        assert msg["signoff_state"] == STATE_INTEGRITY_MISMATCH
        assert msg["signoff_id"] is None
    return view


# --- A) semantischer Binding-Verifier ------------------------------------------


def test_unchanged_signoff_is_fully_verified_with_two_statements(seeded):
    session, advisor = seeded
    _sign(session, advisor)
    ra = _fresh(session)
    view = build_signoff_view(session, ra)
    assert view["state"] == STATUS_SIGNED and ra.signoff_state == STATUS_SIGNED
    assert view["signoff_verified"] is True
    assert view["signoff_row_verified"] is True and view["signoff_binding_verified"] is True
    assert view["integrity_mismatches"] == []
    joined = _lines(view)
    assert "Hash verifiziert" in joined and "fachliche Bindung" in joined


@pytest.mark.parametrize(
    ("statement", "expected"),
    [
        ("UPDATE risk_assessments SET final_score_x10 = final_score_x10 + 10 WHERE id = 'ra-current'",
         "final_score_x10"),
        ("UPDATE risk_assessments SET final_profile = 'Aktien' WHERE id = 'ra-current'", "final_profile"),
        ("UPDATE risk_assessments SET risk_capacity_score_x10 = 99 WHERE id = 'ra-current'",
         "assessment_input_hash"),
    ],
    ids=["final-score", "final-profile", "input-field"],
)
def test_assessment_drift_at_same_version_is_integrity_mismatch(seeded, statement, expected):
    session, advisor = seeded
    _sign(session, advisor)
    session.execute(text(statement))
    session.commit()
    _assert_mismatch(session, expected)


def test_changed_or_deleted_answer_is_input_hash_mismatch(seeded):
    from models.profiling import RiskAssessmentAnswer

    session, advisor = seeded
    session.add(RiskAssessmentAnswer(
        id="ans-1", assessment_id="ra-current", question_number=1, question_section="capacity",
        answer_label="A", answer_points=3, created_at=NOW,
    ))
    session.commit()
    _sign(session, advisor)
    assert build_signoff_view(session, _fresh(session))["signoff_verified"] is True
    session.execute(text("UPDATE risk_assessment_answers SET answer_points = 1 WHERE id = 'ans-1'"))
    session.commit()
    _assert_mismatch(session, "assessment_input_hash")
    session.execute(text("DELETE FROM risk_assessment_answers WHERE id = 'ans-1'"))
    session.commit()
    _assert_mismatch(session, "assessment_input_hash")


def test_override_projection_drift_after_signoff_is_mismatch(seeded):
    session, advisor = seeded
    _override(session, advisor, "ra-current", score=40, profile="Defensiv")
    _sign(session, advisor)
    assert build_signoff_view(session, _fresh(session))["signoff_verified"] is True
    session.execute(text(
        "UPDATE risk_assessments SET override_profile = 'Aktien' WHERE id = 'ra-current'"
    ))
    session.commit()
    view = _assert_mismatch(session, "effective_profile")
    assert "override_decision_unverified" in view["integrity_mismatches"]


def test_mandate_client_changed_is_mismatch(seeded):
    from models.clients import Client

    session, advisor = seeded
    _sign(session, advisor)
    other = Client(
        id="cl-other", client_number="C-OTHER", first_name="Eva", last_name="Andere",
        country_of_residence="CH", language="DE", household_type="Einzelperson",
        client_classification="Privatkunde", is_professional_opt_out=0, is_qualified_investor=0,
        advisor_id=advisor.id, created_at=NOW, updated_at=NOW,
    )
    session.add(other)
    session.commit()
    session.execute(text("UPDATE mandates SET client_id = 'cl-other' WHERE id = 'm-rcp'"))
    session.commit()
    _assert_mismatch(session, "client_id")


def test_mandate_tenant_changed_is_mismatch(seeded):
    from models.tenant import Tenant

    session, advisor = seeded
    _sign(session, advisor)
    session.add(Tenant(id="tenant-x", display_name="X", slug="tenant-x", created_at=NOW, updated_at=NOW))
    session.commit()
    session.execute(text("UPDATE mandates SET tenant_id = 'tenant-x' WHERE id = 'm-rcp'"))
    session.commit()
    _assert_mismatch(session, "tenant_id")


def _document(session, advisor, doc_id="doc-1", checksum="c" * 64):
    from models.review import ContractDocument

    session.add(ContractDocument(
        id=doc_id, mandate_id="m-rcp", document_type="Risikoprofil", title="Risikoprofil",
        checksum_sha256=checksum, status="Entwurf", signed_by_advisor=0, signed_by_client=0,
        version=1, created_by=advisor.id, created_at=NOW, updated_at=NOW,
    ))
    session.commit()


def test_document_binding_verified_then_unverifiable_after_change(seeded):
    session, advisor = seeded
    _document(session, advisor)
    _sign(session, advisor, RiskProfileSignRequest(document_id="doc-1"))
    view = build_signoff_view(session, _fresh(session))
    assert view["signoff_verified"] is True
    assert view["document_binding_status"] == "verified"
    assert "Dokument-Hash verifiziert" in _lines(view)

    session.execute(text("UPDATE contract_documents SET checksum_sha256 = 'd' WHERE id = 'doc-1'"))
    session.commit()
    view = _assert_mismatch(session, "document")
    assert view["document_binding_status"] == "document_unverifiable"
    assert "Dokument-Hash verifiziert" not in _lines(view)


def test_document_soft_deleted_is_unverifiable(seeded):
    session, advisor = seeded
    _document(session, advisor)
    _sign(session, advisor, RiskProfileSignRequest(document_id="doc-1"))
    session.execute(text("UPDATE contract_documents SET deleted_at = '2026-10-24' WHERE id = 'doc-1'"))
    session.commit()
    _assert_mismatch(session, "document")


def test_resigning_after_mismatch_restores_a_verified_signoff(seeded):
    session, advisor = seeded
    _sign(session, advisor)
    session.execute(text("UPDATE risk_assessments SET final_score_x10 = final_score_x10 + 10 WHERE id = 'ra-current'"))
    session.commit()
    ra = _fresh(session)
    assert ra.signoff_state == STATE_INTEGRITY_MISMATCH
    _sign(session, advisor, RiskProfileSignRequest(expected_signoff_id=ra.signoff_id))
    assert build_signoff_view(session, _fresh(session))["signoff_verified"] is True


# --- B) Mandantenbindung + versionsspezifischer Hash ---------------------------


def test_evidence_tables_are_tenant_direct_in_inventory_and_rls_plan():
    scoped = set(tenant_scoped_table_names())
    for table in retb.RISK_EVIDENCE_TENANT_TABLES:
        assert table in scoped
        assert table in inventory.TENANT_DIRECT_TABLES
        assert table not in inventory.TENANT_DERIVED_TABLES
        assert table in inventory.rls_planned_tables()


def test_new_rows_carry_the_mandate_tenant_in_the_v2_hash(seeded):
    from models.tenant import Tenant

    session, advisor = seeded
    session.add(Tenant(id="tenant-a", display_name="A", slug="tenant-a", created_at=NOW, updated_at=NOW))
    session.commit()
    session.execute(text("UPDATE mandates SET tenant_id = 'tenant-a' WHERE id = 'm-rcp'"))
    session.commit()
    _override(session, advisor, "ra-current", score=40, profile="Defensiv")
    result = _sign(session, advisor)
    signoff = session.get(RiskProfileSignoff, result["signoff_id"])
    decision = session.get(RiskOverrideDecision, result["override_decision_id"])
    assert signoff.schema_version == "RiskProfileSignoffV2" and signoff.tenant_id == "tenant-a"
    assert decision.schema_version == "RiskOverrideDecisionV2" and decision.tenant_id == "tenant-a"
    assert signoff_service.signoff_payload(signoff)["tenant_id"] == "tenant-a"
    assert decision_service.decision_payload(decision)["tenant_id"] == "tenant-a"
    assert resolve_assessment_decision(session, _fresh(session))[2] is True
    assert build_signoff_view(session, _fresh(session))["signoff_verified"] is True


def _payload(**extra):
    base = {name: None for name in signoff_service.HASHED_FIELDS}
    base.update(id="s-1", assessment_id="ra", mandate_id="m", effective_score_x10=50)
    base.update(extra)
    return base


def test_signoff_hash_is_version_specific():
    v1 = _payload(schema_version=signoff_service.SCHEMA_VERSION_V1, tenant_id="tenant-a")
    v1["signoff_hash"] = signoff_service.compute_signoff_hash(v1)
    v1_without_tenant = dict(v1, tenant_id="tenant-b")
    # V1 band keinen Mandanten: der Altbestand bleibt verifizierbar.
    assert signoff_service.verify_signoff(v1) is True
    assert signoff_service.verify_signoff(v1_without_tenant) is True

    v2 = _payload(schema_version=signoff_service.SCHEMA_VERSION, tenant_id="tenant-a")
    v2["signoff_hash"] = signoff_service.compute_signoff_hash(v2)
    assert signoff_service.verify_signoff(v2) is True
    assert signoff_service.verify_signoff(dict(v2, tenant_id="tenant-b")) is False

    unknown = dict(v2, schema_version="RiskProfileSignoffV9")
    assert signoff_service.verify_signoff(unknown) is False


def test_decision_hash_is_version_specific():
    base = {name: None for name in decision_service.HASHED_FIELDS}
    base.update(id="d-1", mandate_id="m", tenant_id="tenant-a")
    v1 = dict(base, schema_version=decision_service.SCHEMA_VERSION_V1)
    v1["decision_hash"] = decision_service.compute_decision_hash(v1)
    assert decision_service.verify_decision(dict(v1, tenant_id="tenant-b")) is True
    v2 = dict(base, schema_version=decision_service.SCHEMA_VERSION)
    v2["decision_hash"] = decision_service.compute_decision_hash(v2)
    assert decision_service.verify_decision(v2) is True
    assert decision_service.verify_decision(dict(v2, tenant_id="tenant-b")) is False
    assert decision_service.verify_decision(dict(v2, schema_version="RiskOverrideDecisionV9")) is False


def _raw_signoff(session, **extra):
    values = dict(
        id="s-raw", schema_version="RiskProfileSignoffV2", assessment_id="ra-current",
        mandate_id="m-rcp", client_id="cl-rcp", tenant_id=None, assessment_version=1, sequence_no=9,
        effective_score_x10=50, effective_profile="Ausgewogen", final_score_x10=50,
        final_profile="Ausgewogen", is_overridden=0, override_binding="no_override",
        assessment_input_hash="h", method="advisor_recorded", evidence_level="advisor_attested",
        actor_id="adv-rcp", signed_at=NOW, rules_version="r", signoff_hash="x", created_at=NOW,
    )
    values.update(extra)
    columns = ", ".join(values)
    params = ", ".join(f":{k}" for k in values)
    session.execute(text(f"INSERT INTO risk_profile_signoffs ({columns}) VALUES ({params})"), values)
    session.flush()


@pytest.mark.parametrize(
    "extra",
    [
        {"tenant_id": "tenant-b"},
        {"client_id": "cl-foreign"},
        {"mandate_id": "m-zzz", "client_id": None},
    ],
    ids=["spoofed-tenant", "foreign-client", "assessment-of-other-mandate"],
)
def test_database_rejects_inconsistent_evidence_combinations(seeded, extra):
    session, _advisor = seeded
    _raw_signoff(session, id="s-ok", sequence_no=8)  # Positivkontrolle: konsistent
    session.commit()
    with pytest.raises(IntegrityError):
        _raw_signoff(session, **extra)
    session.rollback()


def test_foreign_mandate_decision_is_not_verified(seeded):
    session, advisor = seeded
    _override(session, advisor, "ra-current", score=40, profile="Defensiv")
    ra = _fresh(session)
    decision = session.get(RiskOverrideDecision, ra.override_decision_id)
    assert resolve_assessment_decision(session, ra)[2] is True
    # Altbestand/Rohpfad ohne Guard: eine korrekt gehashte Decision, die einem
    # anderen Mandat gehoert, darf nie als wirksamer Nachweis gelten.
    session.execute(text(f"DROP TRIGGER {retb.guard_trigger_name('risk_override_decisions')}"))
    foreign = {name: getattr(decision, name) for name in decision_service.HASHED_FIELDS}
    foreign.update(id="rod-foreign", mandate_id="m-zzz", sequence_no=99)
    foreign["decision_hash"] = decision_service.compute_decision_hash(foreign)
    foreign["created_at"] = NOW
    columns = ", ".join(foreign)
    session.execute(
        text(f"INSERT INTO risk_override_decisions ({columns}) VALUES ({', '.join(':' + k for k in foreign)})"),
        foreign,
    )
    session.execute(text(
        "UPDATE risk_assessments SET override_decision_id = 'rod-foreign', "
        "override_decision_hash = :h WHERE id = 'ra-current'"
    ), {"h": foreign["decision_hash"]})
    session.commit()
    assert decision_service.verify_decision(session.get(RiskOverrideDecision, "rod-foreign")) is True
    assert resolve_assessment_decision(session, _fresh(session))[2] is False


# --- Migration entlang der Kette + SQLite-Runtime-Patch -------------------------


def _alembic_config(database_url: str):
    from alembic.config import Config as AlembicConfig

    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return cfg


def test_migration_is_in_the_single_head_chain():
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_alembic_config("sqlite://"))
    heads = script.get_heads()
    assert len(heads) == 1, heads
    chain = {rev.revision for rev in script.walk_revisions("base", heads[0])}
    assert MIGRATION_REVISION in chain
    assert script.get_revision(MIGRATION_REVISION).down_revision == MIGRATION_DOWN_REVISION


def _seed_legacy_evidence(conn) -> None:
    from tests.test_tenant_database_boundary import _raw_insert

    _raw_insert(conn, "tenants", id="t-a", display_name="t-a", slug="t-a")
    _raw_insert(conn, "users", id="adv", tenant_id="t-a")
    _raw_insert(conn, "clients", id="c-a", client_number="c-a", tenant_id="t-a")
    conn.execute(text(
        "INSERT INTO mandates (id, client_id, mandate_number, mandate_type, status, base_currency, "
        "advisory_language, opened_at, investment_universe, tenant_id, created_at, updated_at) "
        "VALUES ('m-a', 'c-a', 'M-A', 'Anlageberatung', 'Aktiv', 'CHF', 'DE', '2026-01-01', "
        "'Standard', 't-a', :n, :n)"
    ), {"n": NOW})
    for sid, mandate in (("s-a", "m-a"), ("s-purged", "m-purged")):
        conn.execute(text(
            "INSERT INTO risk_profile_signoffs (id, schema_version, assessment_id, mandate_id, client_id, "
            "assessment_version, sequence_no, effective_score_x10, effective_profile, final_score_x10, "
            "is_overridden, override_binding, assessment_input_hash, method, evidence_level, actor_id, "
            "signed_at, rules_version, signoff_hash, created_at) VALUES (:id, 'RiskProfileSignoffV1', "
            ":ra, :m, NULL, 1, 1, 50, 'Ausgewogen', 50, 0, 'no_override', 'h', 'advisor_recorded', "
            "'advisor_attested', 'adv', :n, 'r', 'x', :n)"
        ), {"id": sid, "ra": f"ra-{sid}", "m": mandate, "n": NOW})


def _mandate_columns_ok(conn) -> bool:
    return "tenant_id" in {row[1] for row in conn.execute(text("PRAGMA table_info(mandates)")).all()}


def test_migration_backfills_from_mandate_quarantines_orphans_and_downgrades(tmp_path):
    from alembic import command

    url = f"sqlite:///{tmp_path / 'chain.db'}"
    cfg = _alembic_config(url)
    command.upgrade(cfg, MIGRATION_DOWN_REVISION)
    engine = create_engine(url)
    try:
        with engine.begin() as conn:
            assert _mandate_columns_ok(conn)
            _seed_legacy_evidence(conn)
        command.upgrade(cfg, MIGRATION_REVISION)
        with engine.connect() as conn:
            rows = dict(conn.execute(text("SELECT id, tenant_id FROM risk_profile_signoffs")).all())
        # Deterministisch aus dem Mandat; verwaiste Evidence bleibt quarantaeniert.
        assert rows == {"s-a": "t-a", "s-purged": None}
        # Append-only gilt nach dem Backfill wieder.
        with pytest.raises(Exception, match="immutable"):
            with engine.begin() as conn:
                conn.execute(text("UPDATE risk_profile_signoffs SET note = 'x' WHERE id = 's-a'"))
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                conn.execute(text(
                    "INSERT INTO risk_profile_signoffs (id, schema_version, assessment_id, mandate_id, "
                    "tenant_id, assessment_version, sequence_no, effective_score_x10, effective_profile, "
                    "final_score_x10, is_overridden, override_binding, assessment_input_hash, method, "
                    "evidence_level, actor_id, signed_at, rules_version, signoff_hash, created_at) VALUES "
                    "('s-spoof', 'RiskProfileSignoffV2', 'ra-x', 'm-a', 't-b', 1, 1, 50, 'A', 50, 0, "
                    "'no_override', 'h', 'advisor_recorded', 'advisor_attested', 'adv', :n, 'r', 'x', :n)"
                ), {"n": NOW})
        command.downgrade(cfg, MIGRATION_DOWN_REVISION)
        with engine.connect() as conn:
            for table in retb.RISK_EVIDENCE_TENANT_TABLES:
                columns = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})")).all()}
                assert "tenant_id" not in columns, table
            guards = conn.execute(text(
                "SELECT count(*) FROM sqlite_master WHERE type = 'trigger' AND name LIKE '%tenant_guard'"
                " AND tbl_name IN ('risk_override_decisions', 'risk_profile_signoffs')"
            )).scalar()
            assert guards == 0
        command.upgrade(cfg, MIGRATION_REVISION)
    finally:
        engine.dispose()


def test_postgres_offline_sql_backfills_with_bypass_and_installs_guard():
    import io

    from alembic import command

    buffer = io.StringIO()
    cfg = _alembic_config("postgresql://user:pass@localhost/db")
    cfg.output_buffer = buffer
    command.upgrade(cfg, f"{MIGRATION_DOWN_REVISION}:{MIGRATION_REVISION}", sql=True)
    sql = buffer.getvalue()
    for table in retb.RISK_EVIDENCE_TENANT_TABLES:
        assert f"ALTER TABLE {table} DISABLE TRIGGER trg_{table}_immutable" in sql
        assert f"ALTER TABLE {table} ENABLE TRIGGER trg_{table}_immutable" in sql
        assert f"CREATE TRIGGER {retb.guard_trigger_name(table)}" in sql
    assert retb.POSTGRES_FUNCTION_NAME in sql
    assert "app.rls_bypass" in sql or "set_config" in sql


def test_sqlite_runtime_patch_backfills_legacy_desktop_rows(tmp_path):
    from database import Base

    url = f"sqlite:///{tmp_path / 'legacy.db'}"
    engine = create_engine(url)
    try:
        Base.metadata.create_all(bind=engine)
        with engine.begin() as conn:
            for table in retb.RISK_EVIDENCE_TENANT_TABLES:
                conn.execute(text(f"DROP TRIGGER IF EXISTS {retb.guard_trigger_name(table)}"))
            _seed_legacy_evidence(conn)
        assert retb.ensure_sqlite_risk_evidence_tenant_boundary(engine) == {
            "risk_override_decisions": 0, "risk_profile_signoffs": 1,
        }
        with engine.connect() as conn:
            rows = dict(conn.execute(text("SELECT id, tenant_id FROM risk_profile_signoffs")).all())
            triggers = {
                row[0] for row in conn.execute(text(
                    "SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'risk_profile_signoffs'"
                )).all()
            }
        assert rows == {"s-a": "t-a", "s-purged": None}
        assert {"trg_risk_profile_signoffs_no_update", retb.guard_trigger_name("risk_profile_signoffs")} <= triggers
        # idempotent
        assert retb.ensure_sqlite_risk_evidence_tenant_boundary(engine)["risk_profile_signoffs"] == 1
    finally:
        engine.dispose()
    with sqlite3.connect(str(tmp_path / "legacy.db")) as raw:
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            raw.execute("UPDATE risk_profile_signoffs SET note = 'x'")
