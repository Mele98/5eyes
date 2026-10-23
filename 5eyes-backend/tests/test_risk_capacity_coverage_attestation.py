"""RISK-CAPACITY-PLAUSIBILITY-001 Restbefunde A/B (Codex-Closure-Review PR #653,
2026-10-20).

A) Zeilenpraesenz ist keine Vollstaendigkeits-Evidence: eine einzige
   CHF-1-Ausgabenzeile durfte die Expense-Coverage nicht auf ``recorded`` und
   das Ergebnis nicht auf ``consistent`` schalten. ``recorded`` verlangt jetzt
   eine gueltige, gehashte FinancialCoverageAttestationV1 des Beraters
   (Haushalt, Kategorien, unregelmaessige Ausgaben, Stichtag, Quelle, Actor,
   Policy-Version, Cashflow-Fingerprint). Ohne Bestaetigung ist die Coverage
   hoechstens ``rows_unattested`` -> ``partial``; eine bereits zu hohe
   Untergrenze flaggt weiterhin einwegig.

B) ``partial``/``not_evaluable`` sind kanalweit sichtbar ("noch nicht
   verifiziert" + konkreter Aufloesungsauftrag): Strategy Reasoning,
   Berater-PDF, Audit, Monolith-Banner.

Die zwei Codex-Reproducer-Vertraege
(docs/audits/reproducers/test_2026_10_20_pr653_risk_capacity_coverage_residual_adversarial.py)
stehen unten unveraendert als regulaere Tests.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

import pytest
from fastapi import HTTPException

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from models.mandates import Mandate  # noqa: E402
from models.wealth import Cashflow, FinancialCoverageAttestation  # noqa: E402
from services.financial_coverage_attestation import (  # noqa: E402
    POLICY_VERSION,
    SCHEMA_VERSION,
    STATUS_EXPIRED,
    STATUS_HASH_MISMATCH,
    STATUS_HOUSEHOLD_MISMATCH,
    STATUS_INCOMPLETE,
    STATUS_INPUTS_CHANGED,
    STATUS_MISSING,
    STATUS_VALID,
    compute_attestation_hash,
    create_attestation,
    resolve_attestation,
    verify_attestation,
)
from services.risk_capacity_plausibility import (  # noqa: E402
    CHECK_OBLIGATIONS,
    CHECK_SAVINGS,
    COVERAGE_ROWS_UNATTESTED,
    PDF_ADVISOR_NOTE,
    REASON_CODE,
    VERIFICATION_CODE,
    DeclaredCapacity,
    RecordedFinancials,
    assess_plausibility,
    attach_to_strategy_payload,
    audit_payload,
    evaluate_mandate,
    pdf_advisor_note,
    strategy_reasoning_lines,
)
from tests.test_risk_capacity_plausibility import (  # noqa: E402,F401
    NOW,
    TODAY,
    _cashflow,
    _FakeRequest,
    _plausibility_audit_rows,
    _position,
    _risk_body,
    _seed,
    session_factory,
)

CHF = 100


# ---------------------------------------------------------------------------
# Codex-Reproducer (unveraendert uebernommen, ohne xfail)
# ---------------------------------------------------------------------------

def _declared_high_capacity() -> DeclaredCapacity:
    return DeclaredCapacity(
        income_band=3,       # CHF 12'000..20'000
        obligations_band=0,  # up to CHF 3'000
        free_wealth_band=3,  # CHF 1m..2m
        savings_band=3,      # 25..50 percent
        capacity_band=5,
        horizon_years=15,
        capacity_score_x10=100,
        willingness_score_x10=70,
        final_score_x10=70,
    )


def _recorded(*, expense_rappen: int, expense_rows: int, **extra) -> RecordedFinancials:
    return RecordedFinancials(
        gross_income_monthly_rappen=15_000 * CHF,
        recurring_expense_monthly_rappen=expense_rappen,
        liquid_assets_rappen=1_500_000 * CHF,
        gross_assets_rappen=1_500_000 * CHF,
        position_count=1,
        income_cashflow_count=1,
        expense_cashflow_count=expense_rows,
        **extra,
    )


def test_one_token_expense_row_is_not_completeness_evidence():
    """One CHF of recorded expense cannot certify the household budget."""
    missing = assess_plausibility(
        _declared_high_capacity(),
        _recorded(expense_rappen=0, expense_rows=0),
    )
    token_row = assess_plausibility(
        _declared_high_capacity(),
        _recorded(expense_rappen=1 * CHF, expense_rows=1),
    )

    assert missing["status"] == "partial"
    assert {CHECK_OBLIGATIONS, CHECK_SAVINGS} <= {
        row["check"] for row in missing["not_evaluable"]
    }

    assert token_row["status"] != "consistent"
    assert {CHECK_OBLIGATIONS, CHECK_SAVINGS} <= {
        row["check"] for row in token_row["not_evaluable"]
    }


def test_partial_capacity_coverage_is_visible_in_advisor_channels():
    """A coverage gap affecting risk capacity needs an actionable warning."""
    result = assess_plausibility(
        _declared_high_capacity(),
        _recorded(expense_rappen=0, expense_rows=0),
    )
    assert result["status"] == "partial"

    reasoning = strategy_reasoning_lines(result)
    strategy = attach_to_strategy_payload({"reasoning": []}, result)
    note = pdf_advisor_note(result)

    assert reasoning, "partial coverage is machine-readable but advisor-silent"
    assert strategy["reasoning"], "strategy payload hides the incomplete evidence"
    assert note, "advisor PDF omits the partial capacity-coverage warning"


# ---------------------------------------------------------------------------
# A) Zeilenpraesenz vs. Vollstaendigkeit (rein)
# ---------------------------------------------------------------------------

def _skipped(result):
    return {row["check"] for row in result["not_evaluable"]}


def test_many_unattested_rows_below_limit_stay_partial_with_own_coverage_state():
    result = assess_plausibility(
        _declared_high_capacity(), _recorded(expense_rappen=2_000 * CHF, expense_rows=7),
    )
    assert result["status"] == "partial"
    assert result["coverage"][CHECK_OBLIGATIONS] == COVERAGE_ROWS_UNATTESTED
    assert result["coverage"][CHECK_SAVINGS] == COVERAGE_ROWS_UNATTESTED
    assert {CHECK_OBLIGATIONS, CHECK_SAVINGS} <= _skipped(result)
    reason = next(r["reason"] for r in result["not_evaluable"] if r["check"] == CHECK_OBLIGATIONS)
    assert "nicht bestätigt" in reason and "Untergrenze" in reason
    assert result["data_basis"]["expense_coverage_attested"] is False


def test_attested_complete_coverage_allows_low_obligations_to_be_consistent():
    result = assess_plausibility(
        _declared_high_capacity(),
        _recorded(expense_rappen=2_000 * CHF, expense_rows=1, expense_coverage_attested=True),
    )
    assert result["status"] == "consistent"
    assert result["coverage"][CHECK_OBLIGATIONS] == "recorded"
    assert result["coverage"][CHECK_SAVINGS] == "recorded"
    assert strategy_reasoning_lines(result) == []
    assert pdf_advisor_note(result) == ""


def test_high_lower_bound_still_flags_without_attestation():
    result = assess_plausibility(
        _declared_high_capacity(),
        _recorded(expense_rappen=9_000 * CHF, expense_rows=1),
    )
    assert result["status"] == "inconsistent"
    assert {CHECK_OBLIGATIONS} <= {f["check"] for f in result["findings"]}
    assert CHECK_OBLIGATIONS not in _skipped(result)
    assert result["coverage"][CHECK_OBLIGATIONS] == COVERAGE_ROWS_UNATTESTED
    # Der Widerspruchskanal bleibt unveraendert.
    assert pdf_advisor_note(result) == PDF_ADVISOR_NOTE
    assert REASON_CODE in strategy_reasoning_lines(result)[0]


# ---------------------------------------------------------------------------
# B) partial / not_evaluable kanalweit sichtbar
# ---------------------------------------------------------------------------

def test_partial_names_open_checks_and_concrete_resolution_action():
    result = assess_plausibility(
        _declared_high_capacity(), _recorded(expense_rappen=1 * CHF, expense_rows=1),
    )
    assert result["verification_code"] == VERIFICATION_CODE == "RISK_CAPACITY_NOT_VERIFIED"
    assert result["reason_code"] is None  # kein Widerspruch
    actions = result["resolution_actions"]
    assert any("Ausgaben" in a and "bestätigen" in a for a in actions)

    line = strategy_reasoning_lines(result)[0]
    assert "noch nicht verifiziert" in line
    assert "Frage 5" in line and "Frage 7" in line
    assert actions[0] in line

    payload = attach_to_strategy_payload({"reasoning": ["House Matrix"]}, result)
    assert payload["reasoning"][0] == line  # zuoberst (UI zeigt die ersten Punkte)
    assert payload["reasoning"][1:] == ["House Matrix"]

    note = pdf_advisor_note(result)
    assert "noch nicht" in note and "verifiziert" in note
    assert "Ausgaben" in note
    assert "CHF" not in note  # PDF-Beraterteil ohne Betraege
    assert note != PDF_ADVISOR_NOTE


def test_missing_expenses_resolution_asks_to_record_and_confirm():
    result = assess_plausibility(
        _declared_high_capacity(), _recorded(expense_rappen=0, expense_rows=0),
    )
    assert any("erfassen" in a and "bestätigen" in a for a in result["resolution_actions"])


def test_not_evaluable_result_is_visible_too():
    from services.risk_capacity_plausibility import _not_evaluable_result

    result = _not_evaluable_result("Kein aktuelles Risikoprofil vorhanden.")
    assert strategy_reasoning_lines(result)
    note = pdf_advisor_note(result)
    assert "noch nicht" in note and "verifiziert" in note
    assert result["resolution_actions"]


def test_audit_payload_binds_status_open_checks_and_attestation():
    result = assess_plausibility(
        _declared_high_capacity(), _recorded(expense_rappen=1 * CHF, expense_rows=1),
    )
    payload = json.loads(audit_payload(result))
    assert payload["status"] == "partial"
    assert payload["verification_code"] == VERIFICATION_CODE
    assert {CHECK_OBLIGATIONS, CHECK_SAVINGS} <= set(payload["not_evaluable"])
    assert len(payload["evaluation_hash"]) == 64
    assert "CHF" not in audit_payload(result)


def test_evaluation_hash_is_deterministic_and_input_bound():
    a = assess_plausibility(_declared_high_capacity(), _recorded(expense_rappen=1 * CHF, expense_rows=1))
    b = assess_plausibility(_declared_high_capacity(), _recorded(expense_rappen=1 * CHF, expense_rows=1))
    c = assess_plausibility(_declared_high_capacity(), _recorded(expense_rappen=2 * CHF, expense_rows=1))
    assert a["evaluation_hash"] == b["evaluation_hash"] != c["evaluation_hash"]


# ---------------------------------------------------------------------------
# FinancialCoverageAttestationV1 (DB)
# ---------------------------------------------------------------------------

def _attest(session, advisor, **overrides):
    params = dict(
        household_persons=["Max Muster"],
        income_complete=True,
        expenses_complete=True,
        obligations_complete=True,
        irregular_expenses_reviewed=True,
        as_of_date=TODAY.isoformat(),
        source="Kundengespräch",
        now=NOW,
        today=TODAY,
    )
    params.update(overrides)
    row = create_attestation(session, session.get(Mandate, "m-rcp"), actor=advisor, **params)
    session.commit()
    return row


def _seed_budget(session):
    advisor = _seed(session)
    session.add_all([
        _cashflow("salary", "Income", 15_000),
        _cashflow("living", "Expense", 2_000),
        _position("depot", "Depot", "Beratungsvermögen", 1_500_000),
    ])
    session.commit()
    return advisor


def _assessment(session, advisor):
    from routers.profiling import create_risk_assessment

    return create_risk_assessment(
        mandate_id="m-rcp", body=_risk_body(q_obligations_points=4), request=_FakeRequest(),
        db=session, current_user=advisor,
    )


def test_attestation_row_is_hashed_and_bound_to_household_and_inputs(session_factory):
    with session_factory() as session:
        advisor = _seed_budget(session)
        row = _attest(session, advisor)
        assert row.schema_version == SCHEMA_VERSION == "FinancialCoverageAttestationV2"
        assert row.policy_version == POLICY_VERSION
        assert row.client_id == "cl-rcp" and row.mandate_id == "m-rcp"
        # DSG-ERASURE-NEW-EVIDENCE-001: Namen versiegelt, Personenzahl gebunden.
        from services.pii_vault import is_sealed, reveal

        assert is_sealed(row.household_persons_json)
        assert json.loads(reveal(session, row.household_persons_json)) == ["Max Muster"]
        assert row.household_person_count == 1
        assert row.actor_id == advisor.id
        assert len(row.cashflow_fingerprint) == 64 and row.cashflow_row_count == 2
        assert row.attestation_hash == compute_attestation_hash(row)
        assert verify_attestation(row)
        status = resolve_attestation(session, session.get(Mandate, "m-rcp"), today=TODAY)
        assert status["status"] == STATUS_VALID
        assert status["attestation_id"] == row.id
        assert status["attestation_hash"] == row.attestation_hash


def test_without_attestation_mandate_evaluation_is_partial_with_unattested_rows(session_factory):
    with session_factory() as session:
        advisor = _seed_budget(session)
        ra = _assessment(session, advisor)
        result = evaluate_mandate(session, session.get(Mandate, "m-rcp"), ra, today=TODAY)
        assert result["status"] == "partial"
        assert result["coverage"][CHECK_OBLIGATIONS] == COVERAGE_ROWS_UNATTESTED
        assert result["coverage_attestation"]["status"] == STATUS_MISSING


def test_valid_attestation_makes_mandate_evaluation_consistent(session_factory):
    with session_factory() as session:
        advisor = _seed_budget(session)
        _attest(session, advisor)
        ra = _assessment(session, advisor)
        result = evaluate_mandate(session, session.get(Mandate, "m-rcp"), ra, today=TODAY)
        assert result["status"] == "consistent", result["not_evaluable"]
        assert result["coverage"][CHECK_OBLIGATIONS] == "recorded"
        assert result["coverage_attestation"]["status"] == STATUS_VALID


@pytest.mark.parametrize("mutate, expected", [
    ("edit_amount", STATUS_INPUTS_CHANGED),
    ("add_row", STATUS_INPUTS_CHANGED),
    ("delete_row", STATUS_INPUTS_CHANGED),
    ("exclude_row", STATUS_INPUTS_CHANGED),
])
def test_changed_cashflow_inputs_invalidate_attestation(session_factory, mutate, expected):
    with session_factory() as session:
        advisor = _seed_budget(session)
        _attest(session, advisor)
        living = session.get(Cashflow, "living")
        if mutate == "edit_amount":
            living.amount_rappen = 2_100 * CHF
        elif mutate == "add_row":
            session.add(_cashflow("insurance", "Expense", 300))
        elif mutate == "delete_row":
            living.deleted_at = NOW
        elif mutate == "exclude_row":
            living.is_included = 0
        session.commit()
        ra = _assessment(session, advisor)
        result = evaluate_mandate(session, session.get(Mandate, "m-rcp"), ra, today=TODAY)
        assert result["coverage_attestation"]["status"] == expected
        assert result["status"] == "partial"
        if mutate in ("edit_amount", "add_row"):
            # Zeilen vorhanden, Bestaetigung ungueltig -> erneut bestaetigen.
            assert any("erneut bestätigen" in a for a in result["resolution_actions"])
        else:
            # Letzte Ausgabenzeile weg/ausgeschlossen -> erfassen + bestaetigen.
            assert any("erfassen" in a and "bestätigen" in a for a in result["resolution_actions"])


def test_label_only_edit_does_not_invalidate(session_factory):
    with session_factory() as session:
        advisor = _seed_budget(session)
        _attest(session, advisor)
        session.get(Cashflow, "living").updated_at = "2026-10-19T00:00:00.000Z"
        session.commit()
        status = resolve_attestation(session, session.get(Mandate, "m-rcp"), today=TODAY)
        assert status["status"] == STATUS_VALID


def test_expired_attestation_is_not_evidence(session_factory):
    with session_factory() as session:
        advisor = _seed_budget(session)
        _attest(session, advisor)
        mandate = session.get(Mandate, "m-rcp")
        assert resolve_attestation(session, mandate, today=date(2027, 10, 18))["status"] == STATUS_VALID
        assert resolve_attestation(session, mandate, today=date(2027, 10, 19))["status"] == STATUS_EXPIRED


@pytest.mark.parametrize("field", [
    "income_complete", "expenses_complete", "obligations_complete", "irregular_expenses_reviewed",
])
def test_incomplete_categories_are_not_evidence(session_factory, field):
    with session_factory() as session:
        advisor = _seed_budget(session)
        _attest(session, advisor, **{field: False})
        status = resolve_attestation(session, session.get(Mandate, "m-rcp"), today=TODAY)
        assert status["status"] == STATUS_INCOMPLETE


def test_newest_attestation_supersedes_older_one(session_factory):
    with session_factory() as session:
        advisor = _seed_budget(session)
        _attest(session, advisor)
        _attest(session, advisor, expenses_complete=False, now="2026-10-18T01:00:00.000Z")
        status = resolve_attestation(session, session.get(Mandate, "m-rcp"), today=TODAY)
        assert status["status"] == STATUS_INCOMPLETE


def test_household_mismatch_invalidates(session_factory):
    from models.clients import Client

    with session_factory() as session:
        advisor = _seed_budget(session)
        _attest(session, advisor)
        session.add(Client(
            id="cl-other", client_number="C-OTHER", first_name="Eva", last_name="Andere",
            country_of_residence="CH", language="DE", household_type="Einzelperson",
            client_classification="Privatkunde", is_professional_opt_out=0,
            is_qualified_investor=0, advisor_id=advisor.id, created_at=NOW, updated_at=NOW,
        ))
        mandate = session.get(Mandate, "m-rcp")
        mandate.client_id = "cl-other"
        session.commit()
        assert resolve_attestation(session, mandate, today=TODAY)["status"] == STATUS_HOUSEHOLD_MISMATCH


def test_tampered_attestation_fails_verification(session_factory):
    with session_factory() as session:
        advisor = _seed_budget(session)
        row = _attest(session, advisor)
        snapshot = {c.name: getattr(row, c.name) for c in FinancialCoverageAttestation.__table__.columns}
        assert verify_attestation(snapshot)
        snapshot["expenses_complete"] = 0
        assert not verify_attestation(snapshot)
        # Direkte Manipulation in der DB ist per Trigger verboten; wird der
        # Trigger umgangen, faellt der Hash auf.
        session.execute(__import__("sqlalchemy").text(
            "DROP TRIGGER trg_financial_coverage_attestations_no_update"))
        session.execute(__import__("sqlalchemy").text(
            "UPDATE financial_coverage_attestations SET as_of_date='2026-10-17'"))
        session.commit()
        session.expire_all()
        status = resolve_attestation(session, session.get(Mandate, "m-rcp"), today=TODAY)
        assert status["status"] == STATUS_HASH_MISMATCH


def test_attestation_table_is_append_only(session_factory):
    from sqlalchemy.exc import DatabaseError

    with session_factory() as session:
        advisor = _seed_budget(session)
        row = _attest(session, advisor)
        row.note = "nachtraeglich"
        with pytest.raises(DatabaseError, match="immutable"):
            session.commit()
        session.rollback()
        session.delete(session.get(FinancialCoverageAttestation, row.id))
        with pytest.raises(DatabaseError, match="immutable"):
            session.commit()


@pytest.mark.parametrize("bad", [
    {"household_persons": []},
    {"household_persons": ["  "]},
    {"as_of_date": "2026-10-19"},   # Stichtag in der Zukunft
    {"as_of_date": "2025-10-17"},   # bei Erfassung bereits abgelaufen
    {"source": "Bauchgefuehl"},
])
def test_create_attestation_rejects_invalid_input(session_factory, bad):
    with session_factory() as session:
        advisor = _seed_budget(session)
        with pytest.raises(ValueError):
            _attest(session, advisor, **bad)


# ---------------------------------------------------------------------------
# Endpunkte + Audit
# ---------------------------------------------------------------------------

def _post_body(**overrides):
    from schemas.wealth import FinancialCoverageAttestationCreate

    body = dict(
        household_persons=["Max Muster"], income_complete=True, expenses_complete=True,
        obligations_complete=True, irregular_expenses_reviewed=True,
        as_of_date=date.today().isoformat(), source="Kundengespräch",
    )
    body.update(overrides)
    return FinancialCoverageAttestationCreate(**body)


def test_post_endpoint_creates_attestation_audits_and_get_reports_status(session_factory):
    from models.review import AuditLog
    from routers.wealth import create_financial_coverage_attestation, get_financial_coverage_attestation

    with session_factory() as session:
        advisor = _seed_budget(session)
        created = create_financial_coverage_attestation(
            mandate_id="m-rcp", body=_post_body(), db=session, current_user=advisor,
        )
        assert created["status"] == STATUS_VALID
        assert created["attestation_id"]
        audit = session.query(AuditLog).filter(
            AuditLog.table_name == "financial_coverage_attestations").all()
        assert len(audit) == 1 and created["attestation_hash"] in audit[0].new_value
        current = get_financial_coverage_attestation(mandate_id="m-rcp", db=session, current_user=advisor)
        assert current["status"] == STATUS_VALID


def test_post_endpoint_maps_validation_errors_to_422(session_factory):
    from routers.wealth import create_financial_coverage_attestation

    with session_factory() as session:
        advisor = _seed_budget(session)
        with pytest.raises(HTTPException) as exc:
            create_financial_coverage_attestation(
                mandate_id="m-rcp", body=_post_body(household_persons=[]), db=session,
                current_user=advisor,
            )
        assert exc.value.status_code == 422


def test_partial_outcome_is_audited_on_risk_profile_save(session_factory):
    with session_factory() as session:
        advisor = _seed_budget(session)
        ra = _assessment(session, advisor)
        rows = _plausibility_audit_rows(session)
        assert len(rows) == 1 and rows[0].record_id == ra.id
        payload = json.loads(rows[0].new_value)
        assert payload["status"] == "partial"
        assert payload["verification_code"] == VERIFICATION_CODE
        assert payload["coverage_attestation"]["status"] == STATUS_MISSING


def test_attested_consistent_profile_writes_no_plausibility_audit(session_factory):
    with session_factory() as session:
        advisor = _seed_budget(session)
        _attest(session, advisor)
        _assessment(session, advisor)
        assert _plausibility_audit_rows(session) == []


def test_generate_endpoint_shows_partial_in_reasoning_and_audits(session_factory, monkeypatch):
    from types import SimpleNamespace

    import routers.allocation as allocation_router

    with session_factory() as session:
        advisor = _seed_budget(session)
        ra = _assessment(session, advisor)
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
        assert result["risk_capacity_plausibility"]["status"] == "partial"
        assert "noch nicht verifiziert" in result["reasoning"][0]
        assert result["reasoning"][1] == "Ausgangspunkt ist die House Matrix fuer Score 7."
        rows = [r for r in _plausibility_audit_rows(session) if r.table_name == "target_allocations"]
        assert len(rows) == 1 and json.loads(rows[0].new_value)["status"] == "partial"


def test_risk_profile_pdf_data_carries_partial_note(session_factory):
    from services.risk_capacity_plausibility import evaluate_mandate_safely

    with session_factory() as session:
        advisor = _seed_budget(session)
        ra = _assessment(session, advisor)
        note = pdf_advisor_note(evaluate_mandate_safely(session, session.get(Mandate, "m-rcp"), ra))
        assert "noch nicht" in note and "bestätigen" in note


# ---------------------------------------------------------------------------
# Schema-Quellen (ORM, Bootstrap, Runtime-Patch, Alembic)
# ---------------------------------------------------------------------------

SCHEMA_FILE = BACKEND_ROOT / "5eyes_schema_v4.0_FINAL.sql"
TRIGGERS = {
    "trg_financial_coverage_attestations_no_update",
    "trg_financial_coverage_attestations_no_delete",
}
MODEL_COLUMNS = {c.name for c in FinancialCoverageAttestation.__table__.columns}


def _sqlite_columns(db_path):
    with sqlite3.connect(str(db_path)) as conn:
        return {row[1] for row in conn.execute("PRAGMA table_info(financial_coverage_attestations)")}


def _sqlite_triggers(db_path):
    with sqlite3.connect(str(db_path)) as conn:
        return {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' "
            "AND tbl_name='financial_coverage_attestations'")}


def _alembic_cfg(db_url):
    from alembic.config import Config as AlembicConfig

    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return cfg


def test_fresh_bootstrap_has_attestation_table_and_triggers(tmp_path):
    import database as db_module

    db_path = tmp_path / "fresh.db"
    db_module.bootstrap_sqlite_schema(db_path=db_path, schema_path=SCHEMA_FILE)
    assert _sqlite_columns(db_path) == MODEL_COLUMNS
    assert _sqlite_triggers(db_path) == TRIGGERS


def test_runtime_patch_restores_attestation_table_on_legacy_db(tmp_path, monkeypatch):
    import database as db_module
    from sqlalchemy import create_engine

    db_path = tmp_path / "legacy.db"
    db_module.bootstrap_sqlite_schema(db_path=db_path, schema_path=SCHEMA_FILE)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("DROP TABLE financial_coverage_attestations")
        conn.commit()
    engine = create_engine(f"sqlite:///{db_path}")
    monkeypatch.setattr(db_module, "engine", engine)
    db_module.ensure_runtime_columns()
    db_module.ensure_runtime_columns()  # idempotent
    engine.dispose()
    assert _sqlite_columns(db_path) == MODEL_COLUMNS
    assert _sqlite_triggers(db_path) == TRIGGERS


def test_alembic_single_head_creates_table_and_downgrade_reverts(tmp_path):
    from alembic import command
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine, inspect

    script = ScriptDirectory.from_config(_alembic_cfg("sqlite://"))
    heads = script.get_heads()
    assert len(heads) == 1, heads
    chain = {rev.revision for rev in script.walk_revisions("base", heads[0])}
    assert "f3a8d1c6b4e2" in chain

    db_path = tmp_path / "alembic.db"
    cfg = _alembic_cfg(f"sqlite:///{db_path}")
    command.upgrade(cfg, "f3a8d1c6b4e2")
    engine = create_engine(f"sqlite:///{db_path}")
    # household_person_count kommt erst mit c4d9e2a7f1b6 (DSG-ERASURE-NEW-EVIDENCE-001).
    assert {c["name"] for c in inspect(engine).get_columns("financial_coverage_attestations")} == (
        MODEL_COLUMNS - {"household_person_count"}
    )
    engine.dispose()
    assert _sqlite_triggers(db_path) == TRIGGERS
    command.downgrade(cfg, "f3a8d1c6b4e2-1")
    engine = create_engine(f"sqlite:///{db_path}")
    assert "financial_coverage_attestations" not in inspect(engine).get_table_names()
    engine.dispose()


def test_alembic_emits_postgres_immutability_trigger():
    import io

    from alembic import command

    buffer = io.StringIO()
    cfg = _alembic_cfg("postgresql://user:pass@localhost/db")
    cfg.output_buffer = buffer
    command.upgrade(cfg, "e3c7a91f5b28:f3a8d1c6b4e2", sql=True)
    sql = buffer.getvalue()
    assert "CREATE TABLE financial_coverage_attestations" in sql
    assert "BEFORE UPDATE OR DELETE ON financial_coverage_attestations" in sql


def test_attestation_table_has_only_actor_fk(tmp_path):
    import database as db_module

    db_path = tmp_path / "fk.db"
    db_module.bootstrap_sqlite_schema(db_path=db_path, schema_path=SCHEMA_FILE)
    with sqlite3.connect(str(db_path)) as conn:
        targets = {row[2] for row in conn.execute(
            "PRAGMA foreign_key_list(financial_coverage_attestations)")}
    assert targets == {"users"}
    assert {fk.column.table.name for fk in FinancialCoverageAttestation.__table__.foreign_keys} == {"users"}


# ---------------------------------------------------------------------------
# Monolith: Banner zeigt partial + Bestaetigungsformular
# ---------------------------------------------------------------------------

HTML = (BACKEND_ROOT.parent / "5eyes-electron" / "frontend" / "5eyes_v2.html").read_text(encoding="utf-8")


def _js_function(name: str) -> str:
    marker = f"function {name}("
    assert marker in HTML, f"{name} fehlt"
    start = HTML.index(marker)
    return HTML[start:HTML.index("\n}\n", start)]


def test_monolith_banner_renders_partial_with_resolution_actions():
    render = _js_function("renderRiskCapacityPlausibility")
    assert "'partial'" in render and "'not_evaluable'" in render
    assert "resolution_actions" in render
    assert "noch nicht verifiziert" in render
    assert "escapeHtml(" in render


def test_monolith_offers_coverage_attestation_form_posting_to_endpoint():
    render = _js_function("renderRiskCapacityPlausibility")
    assert "coverage_attestation_required" in render
    submit = _js_function("submitFinancialCoverageAttestation")
    assert "'/mandates/'+mid+'/financial-coverage-attestations'" in submit
    for field in ("household_persons", "income_complete", "expenses_complete",
                  "obligations_complete", "irregular_expenses_reviewed", "as_of_date", "source"):
        assert field in submit, field
    assert "refreshRiskCapacityPlausibility(mid)" in submit
    assert "getActiveMandateId()" in submit
