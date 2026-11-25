"""H8 C-5 (Compliance-Audit 2026-11-07, Dok. 104, Luecke 5): GwG-Abklaerung im
SRO-/Fremdprozess; Ares erfasst die Pflicht-Bestaetigung (Formular A/K/S/T,
Datum, Referenz, Risikokategorie, PEP, Vier-Augen-Freigabe, naechste
Aktualisierung) als Gate. "Handelt auf eigene Rechnung" ist nicht mehr
vorbelegt; Bestandskunden gelten als "Bestaetigung fehlt". An der Basis rot:
Default True, keine Bestaetigung, kein Gate.
"""
from __future__ import annotations

import sys
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parent
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from h8_support import NOW, TENANT, Req, codes, mandate, sf, user  # noqa: E402,F401

from datetime import date, timedelta  # noqa: E402

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from pydantic import ValidationError  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from models.clients import KycConfirmation  # noqa: E402
from routers.clients import (  # noqa: E402
    approve_kyc_confirmation, create_kyc_confirmation, list_kyc_confirmations, upsert_due_diligence,
)
from schemas.clients import (  # noqa: E402
    ClientDueDiligenceResponse, ClientDueDiligenceUpdate, KycConfirmationApprovalCreate, KycConfirmationCreate,
    KycConfirmationRequest,
)
from services import recommendation_release_gate as gate  # noqa: E402

from client_onboarding_fixture import (  # noqa: E402
    confirm_test_kyc, ensure_test_kyc_review_policy, ensure_test_legal_profile, satisfy_client_onboarding,
)


def _review_policy(db):
    """C-890-01: Erfassung ueber die API braucht Sitzland (rechtliche Angaben)
    und eine freigegebene Wiedervorlage-Policy -- hier TESTWERTE der Fixture."""
    ensure_test_legal_profile(db, TENANT)
    ensure_test_kyc_review_policy(db, TENANT, actor_id="adm-1")
    db.commit()

BACKEND_ROOT = Path(__file__).resolve().parents[1]

def test_gate_blocks_new_mandate_with_specific_codes_and_owner_hints(sf):
    with sf() as db:
        findings = gate.client_onboarding_findings(db, mandate(db))
    codes = [f["reason_code"] for f in findings]
    assert codes == [
        "CLIENT_INFORMATION_TENANT_DATA_MISSING",
        "CLIENT_INFORMATION_NOT_DELIVERED",
        "KYC_BENEFICIAL_OWNER_UNANSWERED",
        # C-890-01: ohne Sitzland keine Jurisdiktion der Wiedervorlage-Policy.
        "KYC_REVIEW_POLICY_JURISDICTION_UNKNOWN",
        "KYC_CONFIRMATION_MISSING",
    ]
    tenant_finding = findings[0]
    assert "Ombudsstelle: Name" in tenant_finding["owner_action"]
    assert "Administration > Rechtliche Angaben" in tenant_finding["owner_action"]
    assert all(f["owner_action"] for f in findings)


def test_gate_is_green_only_with_profile_delivery_and_kyc(sf):
    with sf() as db:
        satisfy_client_onboarding(db, mandate(db), actor_id="adv-1")
        db.commit()
        assert codes(db) == []
        gate.assert_client_onboarding_release_eligible(db, mandate(db), channel=gate.CHANNEL_FINALIZATION)


def _kyc_body(**overrides):
    today = date.today()
    data = dict(form_type="A", form_completed_on=(today - timedelta(days=2)).isoformat(),
                external_reference="SRO-Dossier 4711", risk_category="normal", is_pep=False,
                identification_confirmed=True, identification_date=(today - timedelta(days=3)).isoformat(),
                next_review_due=(today + timedelta(days=180)).isoformat())  # C-890-01: innerhalb der Test-Policy
    data.update(overrides)
    return KycConfirmationRequest(**data)


def test_kyc_confirmation_has_no_defaults_for_pep_and_risk():
    with pytest.raises(ValidationError):
        KycConfirmationRequest(form_type="A", form_completed_on="2026-01-01", external_reference="Ref 1",
                              next_review_due="2027-01-01")


def test_own_account_question_is_no_longer_prefilled(sf):
    with sf() as db:
        resp = ClientDueDiligenceResponse.model_validate(upsert_due_diligence(
            client_id="c-1", body=ClientDueDiligenceUpdate(), db=db, current_user=user(db, "adv-1")))
        assert resp.acting_for_own_account is None and resp.acting_for_own_account_answered == 0
        assert "KYC_BENEFICIAL_OWNER_UNANSWERED" in codes(db)
        resp = ClientDueDiligenceResponse.model_validate(upsert_due_diligence(
            client_id="c-1", body=ClientDueDiligenceUpdate(acting_for_own_account=True),
            db=db, current_user=user(db, "adv-1")))
        assert resp.acting_for_own_account == 1 and resp.acting_for_own_account_answered == 1
        assert "KYC_BENEFICIAL_OWNER_UNANSWERED" not in codes(db)


def test_existing_customers_are_not_silently_compliant(sf):
    """Bestandszeile vor H8 (acting_for_own_account=1 vorbelegt) -> unbeantwortet."""
    with sf() as db:
        db.execute(text(
            "INSERT INTO client_due_diligence (id, client_id, pep_status, acting_for_own_account, "
            "fatca_crs_self_certified, created_at, updated_at) VALUES ('dd-1','c-1',0,1,0,:n,:n)"
        ), {"n": NOW})
        db.commit()
        assert {"KYC_BENEFICIAL_OWNER_UNANSWERED", "KYC_CONFIRMATION_MISSING"} <= set(codes(db))


def test_pep_or_elevated_risk_needs_approval_by_a_second_admin(sf):
    with sf() as db:
        _review_policy(db)
        upsert_due_diligence(client_id="c-1", body=ClientDueDiligenceUpdate(acting_for_own_account=True,
                                                                            pep_status=True),
                             db=db, current_user=user(db, "adv-1"))
        with pytest.raises(HTTPException) as exc:
            create_kyc_confirmation(client_id="c-1", body=_kyc_body(is_pep=False), request=Req(), db=db,
                                    current_user=user(db, "adm-1"))
        assert exc.value.detail["reason_code"] == "KYC_PEP_INCONSISTENT"
        conf = create_kyc_confirmation(client_id="c-1", body=_kyc_body(is_pep=True, risk_category="erhoeht"),
                                       request=Req(), db=db, current_user=user(db, "adm-1"))
        assert conf.requires_second_approval is True and conf.approval is None
        assert "KYC_SECOND_APPROVAL_MISSING" in codes(db)
        with pytest.raises(HTTPException) as exc:
            approve_kyc_confirmation(client_id="c-1", confirmation_id=conf.id,
                                     body=KycConfirmationApprovalCreate(), request=Req(), db=db,
                                     current_user=user(db, "adm-1"))
        assert exc.value.status_code == 403
        approved = approve_kyc_confirmation(client_id="c-1", confirmation_id=conf.id,
                                            body=KycConfirmationApprovalCreate(note="GL-Freigabe"),
                                            request=Req(), db=db, current_user=user(db, "adm-2"))
        assert approved.approval.approved_by == "adm-2"
        assert "KYC_SECOND_APPROVAL_MISSING" not in codes(db)
        assert [c.id for c in list_kyc_confirmations(client_id="c-1", db=db,
                                                     current_user=user(db, "adv-1"))] == [conf.id]


def test_overdue_kyc_confirmation_blocks(sf):
    with sf() as db:
        record = confirm_test_kyc(db, "c-1", actor_id="adv-1", tenant_id=TENANT)
        db.commit()
    with sf() as db:
        old = KycConfirmation(
            id="kyc-old", tenant_id=TENANT, client_id="c-1", process_scope="sro_oder_fremdprozess",
            form_type="A", form_completed_on="2020-01-01", external_reference="alt", risk_category="normal",
            is_pep=0, identification_confirmed=1, identification_date="2020-01-01",
            next_review_due="2021-01-01", requires_second_approval=0, recorded_by="adv-1",
            recorded_at="2999-01-01T00:00:00.000Z",
        )
        old.confirmation_hash = gate.row_seal(
            {c.name: getattr(old, c.name) for c in old.__table__.columns}, "confirmation_hash")
        db.add(old)
        db.commit()
        assert record.id
        assert "KYC_CONFIRMATION_REVIEW_OVERDUE" in codes(db)


def test_runtime_patch_marks_existing_due_diligence_rows_unanswered(tmp_path, monkeypatch):
    import database as db_module

    db_path = tmp_path / "runtime.db"
    db_module.bootstrap_sqlite_schema(db_path=db_path, schema_path=BACKEND_ROOT / "ares_schema.sql")
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS client_due_diligence (id TEXT PRIMARY KEY, client_id TEXT, "
            "pep_status INTEGER, acting_for_own_account INTEGER, fatca_crs_self_certified INTEGER, "
            "created_at TEXT, updated_at TEXT)"
        ))
        conn.execute(text("INSERT INTO client_due_diligence VALUES ('d','c',0,1,0,'n','n')"))
    monkeypatch.setattr(db_module, "engine", engine)
    db_module.ensure_runtime_columns()
    db_module.ensure_runtime_columns()
    with engine.connect() as conn:
        value = conn.execute(text("SELECT acting_for_own_account_answered FROM client_due_diligence")).scalar()
    engine.dispose()
    assert value == 0


def test_kyc_confirmations_and_approvals_are_append_only(sf):
    with sf() as db:
        confirm_test_kyc(db, "c-1", actor_id="adv-1", tenant_id=TENANT)
        db.commit()
    with sf() as db:
        with pytest.raises(Exception, match="immutable"):
            db.execute(text("UPDATE kyc_confirmations SET risk_category = 'erhoeht'"))
        db.rollback()
        with pytest.raises(Exception, match="immutable"):
            db.execute(text("DELETE FROM kyc_confirmations"))
        db.rollback()


def test_alembic_postgres_ddl_creates_kyc_tables_column_and_triggers():
    from h8_support import h8_postgres_ddl

    ddl = h8_postgres_ddl()
    for table in ("kyc_confirmations", "kyc_confirmation_approvals"):
        assert f"CREATE TABLE {table}" in ddl, table
        assert f"CREATE TRIGGER trg_{table}_immutable" in ddl, table
    assert "ALTER TABLE client_due_diligence ADD COLUMN acting_for_own_account_answered INTEGER DEFAULT 0 NOT NULL" in ddl



# ---------------------------------------------------------------------------
# N-890-03: Vier-Augen nicht umgehbar (Herabstufung, PEP-Ruecknahme)
# ---------------------------------------------------------------------------


def test_downgrade_from_elevated_to_normal_needs_second_approval(sf):
    with sf() as db:
        _review_policy(db)
        upsert_due_diligence(client_id="c-1", body=ClientDueDiligenceUpdate(acting_for_own_account=True),
                             db=db, current_user=user(db, "adv-1"))
        create_kyc_confirmation(client_id="c-1", body=_kyc_body(risk_category="erhoeht"),
                                request=Req(), db=db, current_user=user(db, "adv-1"))
        assert "KYC_SECOND_APPROVAL_MISSING" in codes(db)
        down = create_kyc_confirmation(client_id="c-1", body=_kyc_body(risk_category="normal"),
                                       request=Req(), db=db, current_user=user(db, "adv-1"))
        # Probe 1 der Pruefrunde: vorher release-ready ohne Freigabe.
        assert down.requires_second_approval is True
        assert "KYC_SECOND_APPROVAL_MISSING" in codes(db)
        approve_kyc_confirmation(client_id="c-1", confirmation_id=down.id,
                                 body=KycConfirmationApprovalCreate(note="Herabstufung geprueft"),
                                 request=Req(), db=db, current_user=user(db, "adm-2"))
        assert "KYC_SECOND_APPROVAL_MISSING" not in codes(db)
        # Nach wirksamer, freigegebener Herabstufung braucht "normal" keine Freigabe mehr.
        again = create_kyc_confirmation(client_id="c-1", body=_kyc_body(), request=Req(), db=db,
                                        current_user=user(db, "adv-1"))
        assert again.requires_second_approval is False


def test_pep_withdrawal_in_due_diligence_does_not_bypass_second_approval(sf):
    with sf() as db:
        _review_policy(db)
        adv = user(db, "adv-1")
        upsert_due_diligence(client_id="c-1", body=ClientDueDiligenceUpdate(
            acting_for_own_account=True, pep_status=True), db=db, current_user=adv)
        pep = create_kyc_confirmation(client_id="c-1", body=_kyc_body(is_pep=True), request=Req(), db=db,
                                      current_user=adv)
        approve_kyc_confirmation(client_id="c-1", confirmation_id=pep.id, body=KycConfirmationApprovalCreate(),
                                 request=Req(), db=db, current_user=user(db, "adm-2"))
        assert codes(db) == [] or "KYC_SECOND_APPROVAL_MISSING" not in codes(db)
        # Probe 2 der Pruefrunde: PEP in der Erfassung zuruecknehmen ...
        upsert_due_diligence(client_id="c-1", body=ClientDueDiligenceUpdate(
            acting_for_own_account=True, pep_status=False), db=db, current_user=adv)
        assert "KYC_PEP_INCONSISTENT" in codes(db)
        audit = db.execute(text(
            "SELECT old_value, new_value FROM audit_log WHERE field_name = 'pep_status'")).all()
        assert [tuple(r) for r in audit] == [("1", "0")]
        # ... und "kein PEP" bestaetigen: das ist eine Herabstufung -> Zweitfreigabe.
        down = create_kyc_confirmation(client_id="c-1", body=_kyc_body(is_pep=False), request=Req(), db=db,
                                       current_user=adv)
        assert down.requires_second_approval is True
        assert "KYC_SECOND_APPROVAL_MISSING" in codes(db)


def test_identification_of_contracting_party_is_mandatory():
    with pytest.raises(ValidationError):
        _kyc_body(identification_confirmed=False)
    with pytest.raises(ValidationError):
        _kyc_body(identification_date=(date.today() + timedelta(days=2)).isoformat())


def test_tampered_confirmation_seal_blocks(sf):
    with sf() as db:
        satisfy_client_onboarding(db, mandate(db), actor_id="adv-1")
        db.commit()
        assert not [c for c in codes(db) if c.startswith("KYC")]
        db.execute(text("DROP TRIGGER trg_kyc_confirmations_no_update"))
        db.execute(text("UPDATE kyc_confirmations SET risk_category = 'normal', form_type = 'K'"))
        db.commit()
        assert "KYC_CONFIRMATION_SEAL_INVALID" in codes(db)


def test_kyc_free_texts_can_only_be_redacted_to_the_erasure_marker(sf):
    from services.client_erasure import REDACTION_MARKER
    import database as db_module

    assert db_module.ERASURE_REDACTION_MARKER == REDACTION_MARKER
    with sf() as db:
        confirm_test_kyc(db, "c-1", actor_id="adv-1", tenant_id=TENANT)
        db.commit()
    with sf() as db:
        with pytest.raises(Exception, match="immutable"):
            db.execute(text("UPDATE kyc_confirmations SET external_reference = 'anderer Text'"))
        db.rollback()
        db.execute(text("UPDATE kyc_confirmations SET external_reference = :m, note = :m"),
                   {"m": REDACTION_MARKER})
        db.commit()
        assert db.execute(text("SELECT external_reference FROM kyc_confirmations")).scalar() == REDACTION_MARKER


# ---------------------------------------------------------------------------
# N-890-15 (Entscheid konservativ): PEP-Ruecknahme vor der ersten Bestaetigung
# ---------------------------------------------------------------------------


def test_pep_withdrawal_before_first_confirmation_requires_second_approval(sf):
    with sf() as db:
        _review_policy(db)
        adv = user(db, "adv-1")
        upsert_due_diligence(client_id="c-1", body=ClientDueDiligenceUpdate(
            acting_for_own_account=True, pep_status=True), db=db, current_user=adv)
        upsert_due_diligence(client_id="c-1", body=ClientDueDiligenceUpdate(
            acting_for_own_account=True, pep_status=False), db=db, current_user=adv)
        first = create_kyc_confirmation(client_id="c-1", body=_kyc_body(is_pep=False), request=Req(),
                                        db=db, current_user=adv)
        assert first.requires_second_approval is True
        assert "KYC_SECOND_APPROVAL_MISSING" in codes(db)
        approve_kyc_confirmation(client_id="c-1", confirmation_id=first.id,
                                 body=KycConfirmationApprovalCreate(note="PEP-Ruecknahme geprueft"),
                                 request=Req(), db=db, current_user=user(db, "adm-2"))
        assert "KYC_SECOND_APPROVAL_MISSING" not in codes(db)
        # Nach der freigegebenen Bestaetigung zaehlt die alte Ruecknahme nicht mehr.
        again = create_kyc_confirmation(client_id="c-1", body=_kyc_body(is_pep=False), request=Req(),
                                        db=db, current_user=adv)
        assert again.requires_second_approval is False


def test_without_pep_withdrawal_first_normal_confirmation_needs_no_second_approval(sf):
    """Gegenprobe: ohne PEP-Vorgeschichte bleibt die erste Bestaetigung
    "kein PEP, normal" ohne Zweitfreigabe."""
    with sf() as db:
        _review_policy(db)
        adv = user(db, "adv-1")
        upsert_due_diligence(client_id="c-1", body=ClientDueDiligenceUpdate(
            acting_for_own_account=True, pep_status=False), db=db, current_user=adv)
        first = create_kyc_confirmation(client_id="c-1", body=_kyc_body(is_pep=False), request=Req(),
                                        db=db, current_user=adv)
        assert first.requires_second_approval is False
        assert "KYC_SECOND_APPROVAL_MISSING" not in codes(db)
