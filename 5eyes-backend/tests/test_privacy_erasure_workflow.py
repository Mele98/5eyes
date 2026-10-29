"""PRIVACY-001: Loeschgesuch mit Dispositionen, Legal Hold, Sperrarchiv,
Fristablauf und Suppression-Ledger.

Vertrag (docs ARES_OPEN_DECISIONS_RECOMMENDATION_2026-10-27 §4):
* Ohne genehmigte Policy: "Entscheid ausstehend" -- weder Loeschung noch
  Sperre, nichts wird ausgefuehrt.
* RETAIN_RESTRICTED nur mit Rechtsgrundlage + Fristausloeser; LEGAL_HOLD
  nur durch benannte Legal-/Privacy-Personen (Fall-ID, Rechtsgrund, Umfang,
  Genehmiger, Review-Datum).
* Gesperrte Nachweisarten sind ueber ``restricted_evidence_types`` sichtbar.
* Loeschbeleg ohne kopierte Personendaten.
* Nach Backup-Restore werden Vorgang, Sperrvermerke und Schluessel-
  vernichtungen vor der Freigabe erneut angewendet.

Die Policy-Werte in diesem Test (Rechtsgrundlage, Monate, Matrixtexte) sind
reine Testplatzhalter, keine fachlichen Vorgaben.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import models.client_login  # noqa: F401
from database import Base, ensure_audit_log_triggers
from services.postgres_rls import import_tenant_models

import_tenant_models()

from models.privacy import PrivacyErasureCase, PrivacyErasureDisposition  # noqa: E402
from models.users import User  # noqa: E402
from models.wealth import GoalRevisionDecision  # noqa: E402
from services import pii_vault  # noqa: E402
from services import privacy_erasure as pe  # noqa: E402
from services import privacy_erasure_inventory as inv  # noqa: E402
from services.backup import backup_database  # noqa: E402
from services.client_erasure import ERASURE_LEDGER_FILENAME, REDACTION_MARKER  # noqa: E402
from services.maintenance import restore_backup  # noqa: E402
from tests.test_dsg_erasure_new_evidence_tables import NEEDLES, PERSONS, _seed_all  # noqa: E402
from tests.test_goal_revision_decision import REASON  # noqa: E402

CLIENT = "cl-rcp"
NOW = datetime(2026, 10, 27, 9, 0, tzinfo=timezone.utc)
MATRIX = {key: f"TEST-{key}" for key in pe.REQUIRED_MATRIX_KEYS}
TIER_A_CATEGORIES = {
    (category.evidence_type, category.name)
    for entry in inv.PERSONAL_DATA_INVENTORY.values()
    for category in entry.categories
    if category.method == inv.TIER_A_REDACTION
}


def _engine(db_path: Path):
    return create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})


@pytest.fixture()
def db_path(tmp_path):
    path = tmp_path / "privacy.db"
    engine = _engine(path)
    Base.metadata.create_all(bind=engine)
    ensure_audit_log_triggers(engine)
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    with factory() as session:
        _seed_all(session)
        for uid in ("priv-a", "legal-a", "admin-a"):
            session.add(User(
                id=uid, username=uid, password_hash="h", full_name=uid, role="admin",
                is_active=1, created_at="2026-10-01", updated_at="2026-10-01",
            ))
        session.commit()
        pe.grant_privacy_role(session, tenant_id=None, user_id="priv-a", privacy_role="PRIVACY",
                              granted_by="admin-a", now=NOW)
        pe.grant_privacy_role(session, tenant_id=None, user_id="legal-a", privacy_role="LEGAL",
                              granted_by="admin-a", now=NOW)
        session.commit()
    engine.dispose()
    return path


@pytest.fixture()
def session(db_path):
    engine = _engine(db_path)
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    with factory() as s:
        yield s
    engine.dispose()


def _approve(session, evidence_type, category, disposition, *, tenant_id=None, **kwargs):
    if disposition == inv.RETAIN_RESTRICTED:
        kwargs.setdefault("retention_trigger", "ERASURE_REQUEST")
        kwargs.setdefault("retention_months", 12)
    policy = pe.propose_policy(
        session, tenant_id=tenant_id, evidence_type=evidence_type, data_category=category,
        disposition=disposition, matrix=MATRIX, proposed_by="adv-rcp",
        legal_basis="TEST-RECHTSGRUNDLAGE", now=NOW, **kwargs,
    )
    return pe.approve_policy(session, policy_id=policy.id, approved_by="priv-a", now=NOW)


def _retain_evidence_erase_identity(session, **retain_kwargs):
    for evidence_type in inv.EVIDENCE_TYPES:
        _approve(session, evidence_type, "*", inv.RETAIN_RESTRICTED, **retain_kwargs)
    for evidence_type, category in sorted(TIER_A_CATEGORIES):
        _approve(session, evidence_type, category, inv.DELETE)
    session.commit()


def _lines(session, case_id):
    return {
        (line.table_name, line.data_category): line
        for line in session.query(PrivacyErasureDisposition).filter_by(case_id=case_id)
    }


def _client(session):
    return session.execute(
        text("SELECT first_name, last_name, erased_at FROM clients WHERE id = :id"), {"id": CLIENT},
    ).one()


def _sealed_reason_readable(session) -> bool:
    decision = session.query(GoalRevisionDecision).filter_by(goal_id="g-far").one()
    return pe_reveal(session, decision.reason) == REASON


def pe_reveal(session, value):
    return pii_vault.reveal(session, value)


def _ledger(db_path: Path) -> list[dict]:
    path = db_path.parent / ERASURE_LEDGER_FILENAME
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Fail-closed ohne genehmigte Policy
# ---------------------------------------------------------------------------

def test_without_approved_policy_case_stays_pending_and_nothing_is_executed(session, db_path):
    # PROPOSED allein hat keine Wirkung.
    pe.propose_policy(session, tenant_id=None, evidence_type="client_master_data", data_category="*",
                      disposition=inv.DELETE, matrix=MATRIX, proposed_by="adv-rcp",
                      legal_basis="TEST", now=NOW)
    case = pe.open_erasure_case(session, client_id=CLIENT, opened_by="admin-a", now=NOW)
    session.commit()

    assert case.status == "DECISION_PENDING"
    lines = _lines(session, case.id)
    assert lines[("clients", "IDENTITY")].decision_status == "DECISION_PENDING"
    assert lines[("clients", "IDENTITY")].failure_code == "NO_APPROVED_POLICY"
    assert lines[("clients", "IDENTITY")].disposition is None
    assert lines[("clients", "IDENTITY")].row_count == 1
    # Plausibilitaetsnachweise gehoeren in Suche und Klassifikation.
    assert lines[("financial_coverage_attestations", "SEALED_FREE_TEXT")].row_count == 1
    assert lines[("risk_capacity_plausibility_evaluations", "RECORD")].evidence_type == (
        "risk_capacity_plausibility_evidence"
    )

    with pytest.raises(HTTPException) as exc:
        pe.execute_erasure_case(session, case_id=case.id, executed_by="admin-a", now=NOW)
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "PRIVACY_DECISION_PENDING"
    session.rollback()

    assert _client(session).first_name == "Max"
    assert _sealed_reason_readable(session)
    assert pe.restricted_evidence_types(session, client_id=CLIENT) == frozenset()
    assert _ledger(db_path) == []


def test_policy_approval_requires_designated_role_four_eyes_and_complete_matrix(session):
    policy = pe.propose_policy(session, tenant_id=None, evidence_type="audit_trail", data_category="*",
                               disposition=inv.RETAIN_RESTRICTED, matrix=MATRIX, proposed_by="priv-a",
                               legal_basis="TEST", now=NOW)
    with pytest.raises(HTTPException) as exc:
        pe.approve_policy(session, policy_id=policy.id, approved_by="adv-rcp", now=NOW)
    assert exc.value.detail["code"] == "PRIVACY_ROLE_REQUIRED"
    with pytest.raises(HTTPException) as exc:
        pe.approve_policy(session, policy_id=policy.id, approved_by="priv-a", now=NOW)
    assert exc.value.detail["code"] == "PRIVACY_FOUR_EYES"
    with pytest.raises(HTTPException) as exc:
        pe.approve_policy(session, policy_id=policy.id, approved_by="legal-a", now=NOW)
    assert exc.value.detail["code"] == "PRIVACY_POLICY_INCOMPLETE"
    assert "Fristausloeser" in exc.value.detail["message"]

    incomplete = pe.propose_policy(session, tenant_id=None, evidence_type="audit_trail", data_category="*",
                                   disposition=inv.DELETE, matrix={"purpose": "TEST"},
                                   proposed_by="adv-rcp", now=NOW)
    with pytest.raises(HTTPException) as exc:
        pe.approve_policy(session, policy_id=incomplete.id, approved_by="legal-a", now=NOW)
    assert "Rechtsgrundlage fehlt" in exc.value.detail["message"]
    assert "backups" in exc.value.detail["message"]

    with pytest.raises(HTTPException) as exc:
        pe.propose_policy(session, tenant_id=None, evidence_type="audit_trail", data_category="*",
                          disposition=inv.LEGAL_HOLD, matrix=MATRIX, proposed_by="adv-rcp", now=NOW)
    assert exc.value.detail["code"] == "PRIVACY_DISPOSITION_INVALID"


def test_retention_trigger_without_date_keeps_case_pending(session):
    for evidence_type in inv.EVIDENCE_TYPES:
        _approve(session, evidence_type, "*", inv.RETAIN_RESTRICTED, retention_trigger="RELATIONSHIP_END")
    session.commit()
    case = pe.open_erasure_case(session, client_id=CLIENT, opened_by="admin-a", now=NOW)
    line = _lines(session, case.id)[("clients", "RECORD")]
    assert case.status == "DECISION_PENDING"
    assert line.failure_code == "RETENTION_TRIGGER_DATE_MISSING"
    assert line.retain_until is None


# ---------------------------------------------------------------------------
# Ausfuehrung, Sperrarchiv, Loeschbeleg
# ---------------------------------------------------------------------------

def test_execution_erases_identity_restricts_evidence_and_writes_pii_free_receipt(session, db_path):
    _retain_evidence_erase_identity(session)
    case = pe.open_erasure_case(session, client_id=CLIENT, opened_by="admin-a", now=NOW)
    assert case.status == "READY"
    pe.execute_erasure_case(session, case_id=case.id, executed_by="admin-a", now=NOW)
    session.commit()

    assert case.status == "EXECUTED"
    lines = _lines(session, case.id)
    assert lines[("clients", "IDENTITY")].decision_status == "APPLIED"
    assert lines[("clients", "IDENTITY")].disposition == inv.DELETE
    record = lines[("financial_coverage_attestations", "RECORD")]
    assert record.disposition == inv.RETAIN_RESTRICTED
    assert record.retention_trigger == "ERASURE_REQUEST"
    assert record.retain_until == "2027-10-27"
    assert record.legal_basis == "TEST-RECHTSGRUNDLAGE"

    client = _client(session)
    assert client.first_name == REDACTION_MARKER and client.erased_at
    # Gesperrt aufbewahrte versiegelte Evidenz wird nicht mitvernichtet.
    assert _sealed_reason_readable(session)
    restricted = pe.restricted_evidence_types(session, mandate_id="m-rcp")
    assert {"risk_capacity_plausibility_evidence", "goals_planning", "client_master_data"} <= restricted

    receipt_text = case.receipt_json
    assert pe._sha256(receipt_text) == case.receipt_sha256
    receipt = json.loads(receipt_text)
    assert receipt["schema"] == pe.RECEIPT_SCHEMA and receipt["case_id"] == case.id
    for needle in ("Max", "Muster", CLIENT, *NEEDLES, *PERSONS):
        assert needle not in receipt_text
    entries = [e for e in _ledger(db_path) if e.get("kind") == pe.LEDGER_KIND_CASE]
    assert len(entries) == 1 and entries[0]["keys_shredded"] is False
    assert "client_id" not in entries[0]  # Alt-Leser ignoriert den Eintrag
    ledger_text = json.dumps(entries[0])
    for needle in ("Max", "Muster", *NEEDLES):
        assert needle not in ledger_text
    legacy = [e for e in _ledger(db_path) if not e.get("kind")]
    assert legacy and legacy[0]["pii_keys_shredded"] is False


def test_partial_failure_is_visible_and_never_silent(session):
    """DELETE fuer ganze Datensaetze hat keine Methode, und ein geteilter
    Kundenschluessel kann nicht teilweise vernichtet werden."""
    _retain_evidence_erase_identity(session)
    _approve(session, "audit_trail", "RECORD", inv.DELETE)
    _approve(session, "goals_planning", "SEALED_FREE_TEXT", inv.DELETE)
    session.commit()
    case = pe.open_erasure_case(session, client_id=CLIENT, opened_by="admin-a", now=NOW)
    pe.execute_erasure_case(session, case_id=case.id, executed_by="admin-a", now=NOW)
    session.commit()

    assert case.status == "PARTIALLY_EXECUTED"
    lines = _lines(session, case.id)
    goal_text = lines[("goal_revision_decisions", "SEALED_FREE_TEXT")]
    assert goal_text.decision_status == "FAILED"
    assert goal_text.failure_code == "SHARED_KEY_RETAINED"
    audit = lines[("audit_log", "RECORD")]
    if audit.row_count:
        assert audit.failure_code == "METHOD_NOT_IMPLEMENTED"
    receipt = json.loads(case.receipt_json)
    assert any(line["failure_code"] == "SHARED_KEY_RETAINED" for line in receipt["lines"])
    assert _sealed_reason_readable(session)


def test_retained_identity_blocks_tier_a_instead_of_destroying_it(session):
    _retain_evidence_erase_identity(session)
    _approve(session, "client_master_data", "IDENTITY", inv.RETAIN_RESTRICTED)
    session.commit()
    case = pe.open_erasure_case(session, client_id=CLIENT, opened_by="admin-a", now=NOW)
    pe.execute_erasure_case(session, case_id=case.id, executed_by="admin-a", now=NOW)
    session.commit()

    lines = _lines(session, case.id)
    assert lines[("clients", "IDENTITY")].decision_status == "APPLIED"
    assert lines[("clients", "FREE_TEXT")].failure_code == "TIER_A_NOT_SEPARABLE"
    assert case.status == "PARTIALLY_EXECUTED"
    assert _client(session).first_name == "Max"


def test_mid_execution_failure_rolls_back_everything(session, db_path, monkeypatch):
    _retain_evidence_erase_identity(session)
    case = pe.open_erasure_case(session, client_id=CLIENT, opened_by="admin-a", now=NOW)
    session.commit()

    import services.client_erasure as ce

    def _boom(*_args, **_kwargs):
        raise RuntimeError("Teilausfall")

    monkeypatch.setattr(ce, "erase_client_personal_data", _boom)
    with pytest.raises(RuntimeError):
        pe.execute_erasure_case(session, case_id=case.id, executed_by="admin-a", now=NOW)
    session.rollback()

    session.expire_all()
    assert session.get(PrivacyErasureCase, case.id).status == "READY"
    assert not any(line.decision_status == "APPLIED" for line in _lines(session, case.id).values())
    assert _client(session).first_name == "Max"
    assert _ledger(db_path) == []


def test_unwritable_ledger_aborts_execution(session, monkeypatch):
    _retain_evidence_erase_identity(session)
    case = pe.open_erasure_case(session, client_id=CLIENT, opened_by="admin-a", now=NOW)
    session.commit()

    import services.client_erasure as ce

    def _fail(*_args, **_kwargs):
        raise OSError("read-only")

    monkeypatch.setattr(ce, "_append_ledger_entry", _fail)
    with pytest.raises(HTTPException) as exc:
        pe.execute_erasure_case(session, case_id=case.id, executed_by="admin-a", now=NOW)
    assert exc.value.status_code == 503
    session.rollback()
    session.expire_all()
    assert _client(session).first_name == "Max"
    assert session.get(PrivacyErasureCase, case.id).status == "READY"


def test_repetition_is_refused_and_does_not_duplicate(session, db_path):
    _retain_evidence_erase_identity(session)
    case = pe.open_erasure_case(session, client_id=CLIENT, opened_by="admin-a", now=NOW)
    with pytest.raises(HTTPException) as exc:
        pe.open_erasure_case(session, client_id=CLIENT, opened_by="admin-a", now=NOW)
    assert exc.value.detail["code"] == "PRIVACY_CASE_ALREADY_OPEN"
    pe.execute_erasure_case(session, case_id=case.id, executed_by="admin-a", now=NOW)
    session.commit()
    receipt = case.receipt_sha256
    with pytest.raises(HTTPException) as exc:
        pe.execute_erasure_case(session, case_id=case.id, executed_by="admin-a", now=NOW)
    assert exc.value.detail["code"] == "PRIVACY_CASE_ALREADY_EXECUTED"
    session.rollback()
    assert session.get(PrivacyErasureCase, case.id).receipt_sha256 == receipt
    assert len([e for e in _ledger(db_path) if e.get("kind") == pe.LEDGER_KIND_CASE]) == 1


# ---------------------------------------------------------------------------
# Legal Hold
# ---------------------------------------------------------------------------

def _hold(session, *, approved_by="priv-a", **overrides):
    values = dict(
        client_id=CLIENT, case_reference="FALL-TEST-1", legal_reason="TEST-RECHTSGRUND",
        scope=["risk_profile_evidence", "goals_planning"], review_date="2027-04-30",
        set_by="legal-a", now=NOW,
    )
    values.update(overrides)
    hold = pe.create_legal_hold(session, **values)
    if approved_by is None:
        return hold
    return pe.approve_legal_hold(session, hold_id=hold.id, approved_by=approved_by, now=NOW)


def test_legal_hold_requires_privacy_roles_four_eyes_and_complete_fields(session):
    for overrides, code in (
        ({"set_by": "adv-rcp"}, "PRIVACY_ROLE_REQUIRED"),
        ({"approved_by": "admin-a"}, "PRIVACY_ROLE_REQUIRED"),
        ({"approved_by": "legal-a"}, "PRIVACY_FOUR_EYES"),
        ({"case_reference": " "}, "PRIVACY_HOLD_INCOMPLETE"),
        ({"review_date": ""}, "PRIVACY_HOLD_INCOMPLETE"),
        ({"scope": []}, "PRIVACY_HOLD_SCOPE_EMPTY"),
        ({"scope": ["unbekannt"]}, "PRIVACY_EVIDENCE_TYPE_UNKNOWN"),
    ):
        with pytest.raises(HTTPException) as exc:
            _hold(session, **overrides)
        assert exc.value.detail["code"] == code, overrides
        session.rollback()

    # Ein nur vorgeschlagener Hold wirkt nicht.
    proposed = _hold(session, approved_by=None)
    assert proposed.status == "PROPOSED"
    assert pe.active_legal_holds(session, tenant_id=None, client_id=CLIENT, now=NOW) == []
    hold = pe.approve_legal_hold(session, hold_id=proposed.id, approved_by="priv-a", now=NOW)
    assert hold.status == "ACTIVE" and hold.approved_by == "priv-a" and hold.set_by == "legal-a"
    assert [h.id for h in pe.active_legal_holds(session, tenant_id=None, client_id=CLIENT, now=NOW)] == [hold.id]

    extended = pe.extend_legal_hold(session, hold_id=hold.id, review_date="2027-10-31", actor="priv-a", now=NOW)
    assert extended.extension_count == 1 and extended.review_date == "2027-10-31"
    with pytest.raises(HTTPException) as exc:
        pe.extend_legal_hold(session, hold_id=hold.id, review_date="2028-01-31", actor="adv-rcp", now=NOW)
    assert exc.value.detail["code"] == "PRIVACY_ROLE_REQUIRED"
    with pytest.raises(HTTPException) as exc:
        pe.release_legal_hold(session, hold_id=hold.id, actor="admin-a", now=NOW)
    assert exc.value.detail["code"] == "PRIVACY_ROLE_REQUIRED"


def test_legal_hold_overrides_delete_policy_and_blocks_expiry(session):
    for evidence_type in inv.EVIDENCE_TYPES:
        _approve(session, evidence_type, "*", inv.RETAIN_RESTRICTED, retention_months=1)
    for evidence_type, category in sorted(TIER_A_CATEGORIES):
        _approve(session, evidence_type, category, inv.DELETE)
    _approve(session, "goals_planning", "RECORD", inv.DELETE)
    session.commit()
    hold = _hold(session)
    case = pe.open_erasure_case(session, client_id=CLIENT, opened_by="admin-a", now=NOW)
    lines = _lines(session, case.id)
    assert lines[("goal_revision_decisions", "RECORD")].disposition == inv.LEGAL_HOLD
    assert lines[("goal_revision_decisions", "RECORD")].legal_hold_id == hold.id
    pe.execute_erasure_case(session, case_id=case.id, executed_by="admin-a", now=NOW)
    session.commit()

    later = datetime(2028, 1, 15, tzinfo=timezone.utc)
    result = pe.process_retention_expiry(session, now=later)
    session.commit()
    # goals_planning ist unter Hold -> nicht faellig; der Schluessel bleibt.
    assert lines[("goal_revision_decisions", "SEALED_FREE_TEXT")].decision_status == "APPLIED"
    assert lines[("goal_revision_decisions", "RECORD")].decision_status == "APPLIED"
    assert lines[("clients", "RECORD")].decision_status == "DISPOSAL_DUE"
    assert result["keys_shredded_clients"] == []
    assert _sealed_reason_readable(session)

    pe.release_legal_hold(session, hold_id=hold.id, actor="priv-a", now=later)
    result = pe.process_retention_expiry(session, now=later)
    session.commit()
    assert result["keys_shredded_clients"] == [CLIENT]
    assert lines[("goal_revision_decisions", "SEALED_FREE_TEXT")].decision_status == "DISPOSED"
    assert not _sealed_reason_readable(session)


# ---------------------------------------------------------------------------
# Fristablauf
# ---------------------------------------------------------------------------

def test_expiry_makes_restricted_evidence_due_and_irrecoverable(session):
    _retain_evidence_erase_identity(session, retention_months=1)
    case = pe.open_erasure_case(session, client_id=CLIENT, opened_by="admin-a", now=NOW)
    pe.execute_erasure_case(session, case_id=case.id, executed_by="admin-a", now=NOW)
    session.commit()

    before = pe.process_retention_expiry(session, now=datetime(2026, 11, 26, tzinfo=timezone.utc))
    assert before == {"disposal_due": 0, "disposed": 0, "keys_shredded_clients": []}
    assert _sealed_reason_readable(session)

    after = pe.process_retention_expiry(session, now=datetime(2026, 11, 27, tzinfo=timezone.utc))
    session.commit()
    assert after["disposal_due"] > 0 and after["keys_shredded_clients"] == [CLIENT]
    lines = _lines(session, case.id)
    assert lines[("risk_profile_signoffs", "SEALED_FREE_TEXT")].decision_status in ("DISPOSED", "NO_DATA")
    assert lines[("goal_revision_decisions", "SEALED_FREE_TEXT")].decision_status == "DISPOSED"
    # Ohne Entsorgungsmethode bleibt die Zeile sichtbar faellig (und gesperrt).
    assert lines[("risk_capacity_plausibility_evaluations", "RECORD")].decision_status in (
        "DISPOSAL_DUE", "NO_DATA",
    )
    assert lines[("clients", "RECORD")].decision_status == "DISPOSAL_DUE"
    assert "client_master_data" in pe.restricted_evidence_types(session, client_id=CLIENT)
    assert not _sealed_reason_readable(session)


# ---------------------------------------------------------------------------
# Backup-Restore + Wiederanwendung
# ---------------------------------------------------------------------------

def test_restore_of_older_backup_reapplies_case_restriction_and_key_shredding(db_path, tmp_path):
    backups = tmp_path / "backups"
    pre = backup_database(target_dir=backups, source_db_path=db_path)

    engine = _engine(db_path)
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    with factory() as s:
        _retain_evidence_erase_identity(s, retention_months=1)
        case = pe.open_erasure_case(s, client_id=CLIENT, opened_by="admin-a", now=NOW)
        pe.execute_erasure_case(s, case_id=case.id, executed_by="admin-a", now=NOW)
        s.commit()
        case_id, receipt = case.id, case.receipt_sha256
        pe.process_retention_expiry(s, now=datetime(2026, 12, 1, tzinfo=timezone.utc))
        s.commit()
    engine.dispose()

    result = restore_backup(backup_path=pre.path, target_db_path=db_path)
    privacy = result["erasure_reapply"]["privacy"]
    assert privacy["cases_restored"] == [case_id]
    assert privacy["keys_shredded"] == [CLIENT]
    assert result["erasure_reapply"]["reapplied"] == [CLIENT]

    engine = _engine(db_path)
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    with factory() as s:
        assert _client(s).first_name == REDACTION_MARKER
        restored = s.get(PrivacyErasureCase, case_id)
        assert restored.status == "EXECUTED" and restored.receipt_sha256 == receipt
        assert "risk_capacity_plausibility_evidence" in pe.restricted_evidence_types(s, mandate_id="m-rcp")
        assert _lines(s, case_id)[("goal_revision_decisions", "SEALED_FREE_TEXT")].decision_status == "DISPOSED"
        assert not _sealed_reason_readable(s)
    engine.dispose()

    # Wiederholung: zweiter Restore-Durchlauf ist idempotent.
    again = restore_backup(backup_path=pre.path, target_db_path=db_path)
    assert again["erasure_reapply"]["privacy"]["cases_restored"] == [case_id]
    engine = _engine(db_path)
    with sessionmaker(bind=engine)() as s:
        assert s.query(PrivacyErasureCase).count() == 1
    engine.dispose()


def test_restore_keeps_retained_sealed_evidence_readable(db_path, tmp_path):
    """Die Alt-Wiederanwendung darf den Schluessel nicht vernichten, wenn der
    Vorgang versiegelte Evidenz gesperrt aufbewahrt."""
    pre = backup_database(target_dir=tmp_path / "b", source_db_path=db_path)
    engine = _engine(db_path)
    with sessionmaker(expire_on_commit=False, bind=engine)() as s:
        _retain_evidence_erase_identity(s)
        case = pe.open_erasure_case(s, client_id=CLIENT, opened_by="admin-a", now=NOW)
        pe.execute_erasure_case(s, case_id=case.id, executed_by="admin-a", now=NOW)
        s.commit()
    engine.dispose()

    restore_backup(backup_path=pre.path, target_db_path=db_path)
    engine = _engine(db_path)
    with sessionmaker(bind=engine)() as s:
        assert _client(s).first_name == REDACTION_MARKER
        assert _sealed_reason_readable(s)
    engine.dispose()


# ---------------------------------------------------------------------------
# Mandantentrennung
# ---------------------------------------------------------------------------

def test_tenant_separation_of_policies_roles_holds_and_restrictions(session):
    session.execute(text(
        "INSERT INTO clients (id, client_number, first_name, last_name, country_of_residence, language, "
        "household_type, client_classification, is_professional_opt_out, is_qualified_investor, "
        "advisor_id, tenant_id, created_at, updated_at) VALUES ('cl-b', 'C-B', 'Bea', 'Andere', 'CH', 'DE', "
        "'Einzelperson', 'Privatkunde', 0, 0, 'adv-rcp', 't-b', '2026-10-01', '2026-10-01')"
    ))
    for uid in ("priv-b", "legal-b"):
        session.add(User(id=uid, username=uid, password_hash="h", full_name=uid, role="admin",
                         tenant_id="t-b", is_active=1, created_at="2026-10-01", updated_at="2026-10-01"))
    session.commit()
    with pytest.raises(HTTPException) as exc:
        pe.grant_privacy_role(session, tenant_id=None, user_id="priv-b", privacy_role="PRIVACY",
                              granted_by="admin-a")
    assert exc.value.detail["code"] == "PRIVACY_USER_NOT_IN_TENANT"
    pe.grant_privacy_role(session, tenant_id="t-b", user_id="priv-b", privacy_role="PRIVACY", granted_by="x")
    pe.grant_privacy_role(session, tenant_id="t-b", user_id="legal-b", privacy_role="LEGAL", granted_by="x")

    # Policies aus Mandant t-b entscheiden keinen Vorgang des anderen Mandanten.
    for evidence_type in inv.EVIDENCE_TYPES:
        policy = pe.propose_policy(session, tenant_id="t-b", evidence_type=evidence_type, data_category="*",
                                   disposition=inv.RETAIN_RESTRICTED, matrix=MATRIX, proposed_by="adv-rcp",
                                   legal_basis="TEST", retention_trigger="ERASURE_REQUEST",
                                   retention_months=12, now=NOW)
        with pytest.raises(HTTPException):
            pe.approve_policy(session, policy_id=policy.id, approved_by="priv-a", now=NOW)
        pe.approve_policy(session, policy_id=policy.id, approved_by="priv-b", now=NOW)
    session.commit()
    case_a = pe.open_erasure_case(session, client_id=CLIENT, opened_by="admin-a", now=NOW)
    assert case_a.status == "DECISION_PENDING"

    # Rollen aus t-b duerfen keinen Hold auf einen Kunden ausserhalb setzen.
    with pytest.raises(HTTPException) as exc:
        _hold(session, set_by="legal-b", approved_by=None)
    assert exc.value.detail["code"] == "PRIVACY_ROLE_REQUIRED"

    case_b = pe.open_erasure_case(session, client_id="cl-b", opened_by="priv-b", now=NOW)
    assert case_b.tenant_id == "t-b" and case_b.status == "READY"
    pe.execute_erasure_case(session, case_id=case_b.id, executed_by="priv-b", now=NOW)
    session.commit()
    assert pe.restricted_evidence_types(session, client_id="cl-b") == {"client_master_data"}
    assert pe.restricted_evidence_types(session, client_id=CLIENT) == frozenset()
    # Fristablauf eines Mandanten beruehrt den anderen nicht.
    result = pe.process_retention_expiry(session, now=datetime(2030, 1, 1, tzinfo=timezone.utc))
    assert result["disposal_due"] == 0
    result = pe.process_retention_expiry(session, now=datetime(2030, 1, 1, tzinfo=timezone.utc),
                                         tenant_id="t-b")
    assert result["disposal_due"] == 3  # clients: IDENTITY, FREE_TEXT, RECORD


def test_restriction_lookup_on_schema_without_privacy_tables_is_empty(tmp_path):
    engine = _engine(tmp_path / "old.db")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE mandates (id TEXT PRIMARY KEY, client_id TEXT)"))
    with sessionmaker(bind=engine)() as s:
        assert pe.restricted_evidence_types(s, mandate_id="m-x") == frozenset()
        assert s.execute(text("SELECT COUNT(*) FROM mandates")).scalar() == 0
    engine.dispose()
