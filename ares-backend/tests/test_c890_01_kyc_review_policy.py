"""C-890-01 (Codex, First-Customer-Blocker): KYC-Wiedervorlage braucht einen
freigegebenen Maximalabstand -- fail-closed, ohne erfundene Frist.

Vertrag: docs/audits/2026-11-08-c890-01-implementation-contract.md (Codex-
Worktree), Pflichtregressionen 1-12. An der Basis 31fc43f9 rot: dort gab es
weder Policy noch Bindung; ``next_review_due`` musste nur nach
``form_completed_on`` liegen (2099 gueltig).

ALLE Fristen in dieser Datei sind TESTWERTE (Kennzeichen ``TEST-C890``),
keine Owner-Frist und kein Produktdefault -- das Produkt kennt keine Frist.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parent
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from h8_support import NOW, TENANT, Req, codes, mandate, sf, user  # noqa: E402,F401

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from pydantic import ValidationError  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402

from core.reason_codes import DomainError, ReasonCode  # noqa: E402
from database import new_uuid  # noqa: E402
from models.clients import KycConfirmation  # noqa: E402
from models.review import AuditLog, ContractDocument  # noqa: E402
from models.tenant import KycReviewPolicy, KycReviewPolicyActivation, Tenant  # noqa: E402
from models.users import User  # noqa: E402
from routers.clients import create_kyc_confirmation, upsert_due_diligence  # noqa: E402
from routers.review import (  # noqa: E402
    activate_kyc_review_policy, create_kyc_review_policy, get_client_onboarding_status,
    list_kyc_review_policies,
)
from schemas.clients import (  # noqa: E402
    ClientDueDiligenceUpdate, KycConfirmationCreate, KycConfirmationRequest,
)
from schemas.review import KycReviewPolicyActivate, KycReviewPolicyCreate  # noqa: E402
from services import recommendation_release_gate as gate  # noqa: E402

from client_onboarding_fixture import (  # noqa: E402
    ensure_test_kyc_review_policy, ensure_test_legal_profile, satisfy_client_onboarding,
)

TODAY = date.today()
TEST_SOURCE = "TEST-C890 Testwert (keine Owner-Frist)"


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------


def _iso(days: int = 0) -> str:
    return (TODAY + timedelta(days=days)).isoformat()


def _setup(db, *, answered: bool = True) -> None:
    ensure_test_legal_profile(db, TENANT)
    db.commit()
    if answered:
        upsert_due_diligence(client_id="c-1", body=ClientDueDiligenceUpdate(acting_for_own_account=True),
                             db=db, current_user=user(db, "adv-1"))


def _propose(db, *, by="adm-1", normal=24, elevated=None, valid_from=None, valid_until=None,
             jurisdiction="CH", policy_id="TEST-C890-REVIEW"):
    return create_kyc_review_policy(
        body=KycReviewPolicyCreate(
            jurisdiction=jurisdiction, policy_id=policy_id, normal_max_months=normal,
            elevated_max_months=elevated, valid_from=valid_from or _iso(0), valid_until=valid_until,
            source_reference=TEST_SOURCE,
        ),
        request=Req(), db=db, current_user=user(db, by),
    )


def _activate(db, row, *, by="adm-2", policy_hash=None):
    return activate_kyc_review_policy(
        policy_row_id=row.id,
        body=KycReviewPolicyActivate(policy_hash=policy_hash or row.policy_hash,
                                     approval_reference="TEST-C890 Testfreigabe"),
        request=Req(), db=db, current_user=user(db, by),
    )


def _policy(db, **kwargs):
    return _activate(db, _propose(db, **kwargs))


def _body(**overrides) -> KycConfirmationRequest:
    data = dict(form_type="A", form_completed_on=_iso(-2), external_reference="SRO-Dossier 4711",
                risk_category="normal", is_pep=False, identification_confirmed=True,
                identification_date=_iso(-3), next_review_due=_iso(30))
    data.update(overrides)
    return KycConfirmationRequest(**data)


def _confirm(db, by="adv-1", **overrides):
    return create_kyc_confirmation(client_id="c-1", body=_body(**overrides), request=Req(), db=db,
                                   current_user=user(db, by))


def _blocked_code(db, **overrides) -> tuple[int, dict]:
    with pytest.raises(HTTPException) as exc:
        _confirm(db, **overrides)
    return exc.value.status_code, exc.value.detail


def _review_audit(db) -> list[str]:
    return [row.new_value for row in db.query(AuditLog).filter(
        AuditLog.field_name == "kyc_review_policy_blocked").order_by(AuditLog.created_at).all()]


def _kyc_codes(db, today=None) -> list[str]:
    today = today or gate._utc_now_iso()[:10]
    return [f["reason_code"] for f in gate._kyc_findings(db, mandate(db), today)]


def _insert_confirmation(db, **values) -> KycConfirmation:
    data = dict(
        id=new_uuid(), tenant_id=TENANT, client_id="c-1", process_scope="sro_oder_fremdprozess",
        form_type="A", form_completed_on=_iso(-2), external_reference="Bestand", risk_category="normal",
        is_pep=0, identification_confirmed=1, identification_date=_iso(-2), next_review_due=_iso(30),
        requires_second_approval=0, recorded_by="adv-1", recorded_at="2999-01-01T00:00:00.000Z",
    )
    data.update(values)
    record = KycConfirmation(**data)
    record.confirmation_hash = gate.row_seal(
        {c.name: getattr(record, c.name) for c in record.__table__.columns}, "confirmation_hash")
    db.add(record)
    db.commit()
    return record


def _legacy_confirmation(db) -> KycConfirmation:
    """Bestandsbestaetigung aus H8 (vor C-890-01): ohne Bindungsspalten, das
    Siegel deckt nur die damaligen Spalten (wie in der Datenbank vorgefunden)."""
    record = KycConfirmation(
        id=new_uuid(), tenant_id=TENANT, client_id="c-1", process_scope="sro_oder_fremdprozess",
        form_type="A", form_completed_on=_iso(-2), external_reference="Bestand H8", risk_category="normal",
        is_pep=0, identification_confirmed=1, identification_date=_iso(-2), next_review_due=_iso(30),
        requires_second_approval=0, recorded_by="adv-1", recorded_at="2999-01-01T00:00:00.000Z",
    )
    legacy = {c.name: getattr(record, c.name) for c in record.__table__.columns
              if c.name not in gate.KYC_REVIEW_BINDING_COLUMNS}
    record.confirmation_hash = gate.row_seal(legacy, "confirmation_hash")
    db.add(record)
    db.commit()
    return record


# ---------------------------------------------------------------------------
# Codex-Reproducer (wortgleich) und Grundsatz "keine Frist ohne Policy"
# ---------------------------------------------------------------------------


def test_codex_reproducer_2099_without_policy_is_rejected():
    with pytest.raises(ValidationError):
        KycConfirmationCreate(
            form_type="A", form_completed_on="2026-11-01", external_reference="SRO-DOSSIER-123",
            risk_category="normal", is_pep=False, identification_confirmed=True,
            identification_date="2026-11-01", next_review_due="2099-11-01",
        )


def test_policy_bound_schema_accepts_only_up_to_the_server_max():
    base = dict(form_type="A", form_completed_on=_iso(-2), external_reference="SRO-1", risk_category="normal",
                is_pep=False, identification_confirmed=True, identification_date=_iso(-2))
    binding = {"reason_code": None, "form_completed_on": _iso(-2), "risk_class": "normal", "max_due": _iso(40)}
    ok = KycConfirmationCreate.model_validate({**base, "next_review_due": _iso(40)},
                                              context={"kyc_review_binding": binding})
    assert ok.next_review_due == _iso(40)
    for due in (_iso(41), "2099-11-01"):
        with pytest.raises(ValidationError, match="KYC_REVIEW_DUE_EXCEEDS_POLICY"):
            KycConfirmationCreate.model_validate({**base, "next_review_due": due},
                                                 context={"kyc_review_binding": binding})
    with pytest.raises(ValidationError, match="KYC_REVIEW_POLICY_EXPIRED"):
        KycConfirmationCreate.model_validate({**base, "next_review_due": _iso(10)},
                                             context={"kyc_review_binding": {"reason_code": "KYC_REVIEW_POLICY_EXPIRED"}})


def test_no_product_default_interval_exists():
    """Kein Produktdefault: nirgends im Produktcode (ohne Tests) wird einer
    Frist eine Zahl zugewiesen; Alembic legt keine Policy-Zeile an."""
    import re

    backend = Path(__file__).resolve().parents[1]
    pattern = re.compile(r"(normal|elevated)_max_months[\"']?\s*[:=]\s*-?\d")
    offenders = []
    for path in backend.rglob("*.py"):
        rel = path.relative_to(backend).as_posix()
        if rel.startswith(("tests/", "venv/", ".venv/")):
            continue
        if pattern.search(path.read_text(encoding="utf-8", errors="ignore")):
            offenders.append(rel)
    assert offenders == []
    migration = (backend / "alembic" / "versions" / "f4c2e8a6d1b3_kyc_review_policy.py").read_text(encoding="utf-8")
    assert "INSERT INTO kyc_review_policies" not in migration and "bulk_insert" not in migration


# ---------------------------------------------------------------------------
# 1. fehlende, unfreigegebene, abgelaufene, mehrdeutige Policy -> rot
# ---------------------------------------------------------------------------


def test_missing_policy_blocks_entry_and_gate_with_tenant_bound_audit(sf):
    with sf() as db:
        _setup(db)
        status, detail = _blocked_code(db)
        assert (status, detail["reason_code"], detail["kyc_review_status"]) == (
            409, "KYC_REVIEW_POLICY_MISSING", "policy_missing")
        assert db.query(KycConfirmation).count() == 0
        assert "KYC_REVIEW_POLICY_MISSING" in codes(db)
        audit = db.query(AuditLog).filter(AuditLog.field_name == "kyc_review_policy_blocked").all()
        assert [(a.new_value, a.tenant_id) for a in audit] == [
            ("KYC_REVIEW_POLICY_MISSING;kanal=kyc_confirmation_create;policy=-@v-;jurisdiktion=CH", TENANT)]


def test_unknown_jurisdiction_blocks(sf):
    with sf() as db:
        _policy(db)
        db.execute(text("UPDATE tenant_legal_profiles SET address_country = NULL"))
        db.commit()
        status, detail = _blocked_code(db)
        assert (status, detail["reason_code"]) == (409, "KYC_REVIEW_POLICY_JURISDICTION_UNKNOWN")


def test_unapproved_policy_blocks(sf):
    with sf() as db:
        _setup(db)
        _propose(db)
        status, detail = _blocked_code(db)
        assert (status, detail["reason_code"]) == (409, "KYC_REVIEW_POLICY_UNAPPROVED")
        assert "KYC_REVIEW_POLICY_UNAPPROVED" in codes(db)


def test_self_approved_activation_is_not_effective(sf):
    with sf() as db:
        _setup(db)
        row = _propose(db)
        with pytest.raises(HTTPException) as exc:
            _activate(db, row, by="adm-1")
        assert (exc.value.status_code, exc.value.detail["reason_code"]) == (403, "KYC_REVIEW_POLICY_SAME_PERSON")
        # Direktzugriff an der API vorbei: Ersteller = Freigeber gilt nie.
        act = KycReviewPolicyActivation(
            id=new_uuid(), tenant_id=TENANT, jurisdiction="CH", policy_row_id=row.id,
            predecessor_activation_id="GENESIS", approved_by="adm-1", approved_at=NOW,
            approval_reference="x", policy_hash=row.policy_hash)
        act.activation_hash = gate.row_seal({c.name: getattr(act, c.name) for c in act.__table__.columns},
                                            "activation_hash")
        db.add(act)
        db.commit()
        assert _blocked_code(db)[1]["reason_code"] == "KYC_REVIEW_POLICY_UNAPPROVED"


def test_not_yet_effective_policy_blocks(sf):
    with sf() as db:
        _setup(db)
        _policy(db, valid_from=_iso(10))
        assert _blocked_code(db)[1]["reason_code"] == "KYC_REVIEW_POLICY_NOT_YET_EFFECTIVE"
        assert "KYC_REVIEW_POLICY_NOT_YET_EFFECTIVE" in codes(db)


def test_expired_policy_blocks(sf):
    with sf() as db:
        _setup(db)
        ensure_test_kyc_review_policy(db, TENANT, actor_id="adm-1", policy_id="TEST-C890-EXPIRED",
                                      normal_max_months=24, valid_until="2001-01-01")
        db.commit()
        status, detail = _blocked_code(db)
        assert (status, detail["reason_code"], detail["kyc_review_status"]) == (
            409, "KYC_REVIEW_POLICY_EXPIRED", "policy_expired")
        with pytest.raises(HTTPException) as exc:
            _activate(db, _propose(db, valid_from="2000-01-01", valid_until="2000-12-31"))
        assert exc.value.detail["reason_code"] == "KYC_REVIEW_POLICY_VALIDITY_INVALID"


def test_ambiguous_policy_chain_blocks(sf):
    with sf() as db:
        _setup(db)
        _policy(db)
        second = _propose(db, normal=12)
        orphan = KycReviewPolicyActivation(
            id=new_uuid(), tenant_id=TENANT, jurisdiction="CH", policy_row_id=second.id,
            predecessor_activation_id="unbekannter-vorgaenger", approved_by="adm-2", approved_at=NOW,
            approval_reference="x", policy_hash=second.policy_hash)
        orphan.activation_hash = gate.row_seal(
            {c.name: getattr(orphan, c.name) for c in orphan.__table__.columns}, "activation_hash")
        db.add(orphan)
        db.commit()
        assert _blocked_code(db)[1]["reason_code"] == "KYC_REVIEW_POLICY_AMBIGUOUS"
        assert "KYC_REVIEW_POLICY_AMBIGUOUS" in codes(db)
        with pytest.raises(HTTPException) as exc:
            _activate(db, _propose(db, normal=6))
        assert exc.value.detail["reason_code"] == "KYC_REVIEW_POLICY_AMBIGUOUS"


# ---------------------------------------------------------------------------
# 2. Abstand null/negativ, PEP-Frist lockerer als Normalfrist -> rot
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("normal, elevated, code", [
    (0, None, "KYC_REVIEW_POLICY_INTERVAL_INVALID"),
    (-6, None, "KYC_REVIEW_POLICY_INTERVAL_INVALID"),
    (12, 0, "KYC_REVIEW_POLICY_INTERVAL_INVALID"),
    (12, -1, "KYC_REVIEW_POLICY_INTERVAL_INVALID"),
    (12, 13, "KYC_REVIEW_POLICY_ELEVATED_LOOSER"),
])
def test_invalid_intervals_are_rejected_at_capture(sf, normal, elevated, code):
    with sf() as db:
        _setup(db)
        with pytest.raises(HTTPException) as exc:
            _propose(db, normal=normal, elevated=elevated)
        assert (exc.value.status_code, exc.value.detail["reason_code"]) == (422, code)
        assert db.query(KycReviewPolicy).count() == 0


def test_database_checks_reject_invalid_intervals(sf):
    with sf() as db:
        for normal, elevated in ((0, None), (-1, None), (12, 13), (12, 0)):
            db.add(KycReviewPolicy(
                id=new_uuid(), tenant_id=TENANT, jurisdiction="CH", policy_id="TEST-C890", version=1,
                normal_max_months=normal, elevated_max_months=elevated, valid_from="2026-01-01",
                source_reference=TEST_SOURCE, created_by="adm-1", created_at=NOW, policy_hash="h"))
            with pytest.raises(IntegrityError):
                db.commit()
            db.rollback()


def test_looser_elevated_interval_is_rejected_at_activation_and_in_gate(sf):
    """Auch eine an der API/CHECK vorbei geschriebene lockerere PEP-Frist wird
    bei der Aktivierung abgelehnt und gilt im Gate nie."""
    with sf() as db:
        _setup(db)
        db.execute(text("PRAGMA ignore_check_constraints = ON"))
        row = KycReviewPolicy(
            id=new_uuid(), tenant_id=TENANT, jurisdiction="CH", policy_id="TEST-C890-LOOSE", version=1,
            normal_max_months=12, elevated_max_months=36, valid_from=_iso(0),
            source_reference=TEST_SOURCE, created_by="adm-1", created_at=NOW)
        row.policy_hash = gate.row_seal({c.name: getattr(row, c.name) for c in row.__table__.columns},
                                        "policy_hash")
        db.add(row)
        db.commit()
        with pytest.raises(HTTPException) as exc:
            _activate(db, row)
        assert exc.value.detail["reason_code"] == "KYC_REVIEW_POLICY_ELEVATED_LOOSER"
        act = KycReviewPolicyActivation(
            id=new_uuid(), tenant_id=TENANT, jurisdiction="CH", policy_row_id=row.id,
            predecessor_activation_id="GENESIS", approved_by="adm-2", approved_at=NOW,
            approval_reference="x", policy_hash=row.policy_hash)
        act.activation_hash = gate.row_seal({c.name: getattr(act, c.name) for c in act.__table__.columns},
                                            "activation_hash")
        db.add(act)
        db.commit()
        assert _blocked_code(db)[1]["reason_code"] == "KYC_REVIEW_POLICY_INVALID"


# ---------------------------------------------------------------------------
# 3. 2099 rot, exakte Obergrenze gruen, ein Tag dahinter rot
# ---------------------------------------------------------------------------


def test_2099_and_one_day_after_max_are_red_exact_max_is_green(sf):
    with sf() as db:
        _setup(db)
        _policy(db, normal=24)
        completed = _iso(-2)
        exact = gate.add_months_clamped(completed, 24)
        for due in ("2099-11-01", (date.fromisoformat(exact) + timedelta(days=1)).isoformat()):
            status, detail = _blocked_code(db, form_completed_on=completed, next_review_due=due)
            assert (status, detail["reason_code"], detail["max_due"]) == (422, "KYC_REVIEW_DUE_EXCEEDS_POLICY", exact)
        assert db.query(KycConfirmation).count() == 0
        conf = _confirm(db, form_completed_on=completed, next_review_due=exact)
        assert (conf.next_review_due, conf.review_max_due, conf.review_interval_months) == (exact, exact, 24)
        assert _kyc_codes(db) == []
        assert len(_review_audit(db)) == 2


# ---------------------------------------------------------------------------
# 4. 29. Februar und Monatsende reproduzierbar
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("start, months, expected", [
    ("2024-02-29", 12, "2025-02-28"),
    ("2024-02-29", 48, "2028-02-29"),
    ("2024-02-29", 36, "2027-02-28"),
    ("2028-01-31", 1, "2028-02-29"),
    ("2026-01-31", 1, "2026-02-28"),
    ("2026-03-31", 1, "2026-04-30"),
    ("2026-08-31", 1, "2026-09-30"),
    ("2026-12-31", 2, "2027-02-28"),
    ("2026-11-30", 3, "2027-02-28"),
    ("2026-05-15", 12, "2027-05-15"),
    ("2026-12-15", 1, "2027-01-15"),
])
def test_calendar_contract_month_end_and_leap_day(start, months, expected):
    assert gate.add_months_clamped(start, months) == expected
    assert gate.add_months_clamped(start, months) == gate.add_months_clamped(start, months)


def test_calendar_rejects_non_positive_interval():
    for months in (0, -1):
        with pytest.raises(ValueError):
            gate.add_months_clamped("2026-01-31", months)


def test_leap_day_completion_through_the_api(sf):
    with sf() as db:
        _setup(db)
        _policy(db, normal=36)
        assert _blocked_code(db, form_completed_on="2024-02-29", identification_date="2024-02-29",
                             next_review_due="2027-03-01")[1]["max_due"] == "2027-02-28"
        conf = _confirm(db, form_completed_on="2024-02-29", identification_date="2024-02-29",
                        next_review_due="2027-02-28")
        assert conf.review_max_due == "2027-02-28"


# ---------------------------------------------------------------------------
# 5. Normal, PEP und erhoehtes Risiko verwenden die richtige Version
# ---------------------------------------------------------------------------


def test_risk_classes_use_the_effective_version_and_their_interval(sf):
    with sf() as db:
        _setup(db)
        _policy(db, normal=24, elevated=12)
        v2 = _policy(db, normal=20, elevated=8, policy_id="TEST-C890-REVIEW-2")
        assert v2.version == 2 and v2.status == "wirksam"
        completed = _iso(-2)
        normal = _confirm(db, form_completed_on=completed, next_review_due=gate.add_months_clamped(completed, 20))
        assert (normal.review_policy_version, normal.review_risk_class, normal.review_interval_months) == (
            2, "normal", 20)
        upsert_due_diligence(client_id="c-1", body=ClientDueDiligenceUpdate(acting_for_own_account=True,
                                                                            pep_status=True),
                             db=db, current_user=user(db, "adv-1"))
        assert _blocked_code(db, is_pep=True, form_completed_on=completed,
                             next_review_due=gate.add_months_clamped(completed, 9))[1]["max_due"] == (
            gate.add_months_clamped(completed, 8))
        pep = _confirm(db, is_pep=True, form_completed_on=completed,
                       next_review_due=gate.add_months_clamped(completed, 8))
        assert (pep.review_policy_version, pep.review_risk_class, pep.review_interval_months) == (2, "erhoeht", 8)
        upsert_due_diligence(client_id="c-1", body=ClientDueDiligenceUpdate(acting_for_own_account=True,
                                                                            pep_status=False),
                             db=db, current_user=user(db, "adv-1"))
        high = _confirm(db, is_pep=False, risk_category="erhoeht", form_completed_on=completed,
                        next_review_due=gate.add_months_clamped(completed, 8))
        assert (high.review_policy_version, high.review_risk_class, high.review_interval_months) == (
            2, "erhoeht", 8)


def test_without_separate_elevated_interval_pep_uses_the_normal_interval(sf):
    with sf() as db:
        _setup(db)
        _policy(db, normal=18)
        completed = _iso(-2)
        conf = _confirm(db, risk_category="erhoeht", form_completed_on=completed,
                        next_review_due=gate.add_months_clamped(completed, 18))
        assert (conf.review_risk_class, conf.review_interval_months) == ("erhoeht", 18)


# ---------------------------------------------------------------------------
# 6. Verkuerzung macht bestehende Evidenz sofort faellig
# 7. Verlaengerung verlaengert einen gebundenen Termin nicht rueckwirkend
# ---------------------------------------------------------------------------


def test_shortened_policy_makes_existing_confirmation_due_from_its_effective_date(sf):
    with sf() as db:
        _setup(db)
        _policy(db, normal=24)
        completed = _iso(-2)
        due = gate.add_months_clamped(completed, 24)
        _confirm(db, form_completed_on=completed, next_review_due=due)
        assert _kyc_codes(db) == []
        # Verkuerzung ab in 10 Tagen: bis dahin gilt die alte Version.
        _policy(db, normal=6, valid_from=_iso(10), policy_id="TEST-C890-SHORT")
        assert _kyc_codes(db) == []
        later = _iso(10)
        assert _kyc_codes(db, later) == ["KYC_REVIEW_POLICY_SHORTENED"]
        finding = gate._kyc_findings(db, mandate(db), later)[0]
        assert finding["current_max_due"] == gate.add_months_clamped(completed, 6)
        assert finding["bound_next_review_due"] == due
        assert finding["kyc_review_status"] == "due_under_shortened_policy"
        assert finding["policy_ref"]["policy_id"] == "TEST-C890-SHORT"


def test_shortened_policy_effective_today_blocks_all_release(sf):
    with sf() as db:
        _setup(db)
        _policy(db, normal=24)
        completed = _iso(-2)
        _confirm(db, form_completed_on=completed, next_review_due=gate.add_months_clamped(completed, 24))
        _policy(db, normal=6, policy_id="TEST-C890-SHORT")
        assert "KYC_REVIEW_POLICY_SHORTENED" in codes(db)
        # Remediation: neue Bestaetigung unter der neuen Policy.
        _confirm(db, form_completed_on=completed, next_review_due=gate.add_months_clamped(completed, 6))
        assert _kyc_codes(db) == []


def test_extended_policy_does_not_extend_a_bound_due_date(sf):
    with sf() as db:
        _setup(db)
        _policy(db, normal=6)
        completed = _iso(-2)
        due = gate.add_months_clamped(completed, 6)
        conf = _confirm(db, form_completed_on=completed, next_review_due=due)
        _policy(db, normal=48, policy_id="TEST-C890-LONG")
        assert _kyc_codes(db) == []
        record = db.query(KycConfirmation).filter(KycConfirmation.id == conf.id).first()
        assert (record.next_review_due, record.review_max_due, record.review_policy_version) == (due, due, 1)
        after = (date.fromisoformat(due) + timedelta(days=1)).isoformat()
        assert _kyc_codes(db, after) == ["KYC_CONFIRMATION_REVIEW_OVERDUE"]
        status = gate.kyc_review_status(db, mandate(db), gate.latest_kyc_confirmation(db, "c-1", "m-1"), after)
        assert (status["status"], status["policy"]["version"]) == ("review_overdue", 2)


# ---------------------------------------------------------------------------
# 8. Hash-, Tenant-, Versions- und Zeitmanipulation blockiert
# ---------------------------------------------------------------------------


def _bound(db):
    _setup(db)
    _policy(db, normal=24)
    completed = _iso(-2)
    conf = _confirm(db, form_completed_on=completed, next_review_due=gate.add_months_clamped(completed, 24))
    assert _kyc_codes(db) == []
    return conf


def test_tampered_policy_row_or_activation_invalidates_everything(sf):
    with sf() as db:
        _bound(db)
        db.execute(text("DROP TRIGGER trg_kyc_review_policies_no_update"))
        db.execute(text("UPDATE kyc_review_policies SET normal_max_months = 120"))
        db.commit()
        assert set(_kyc_codes(db)) == {"KYC_REVIEW_POLICY_BINDING_INVALID", "KYC_REVIEW_POLICY_INVALID"}
        assert _blocked_code(db)[1]["reason_code"] == "KYC_REVIEW_POLICY_INVALID"


def test_tampered_activation_hash_invalidates(sf):
    with sf() as db:
        _bound(db)
        db.execute(text("DROP TRIGGER trg_kyc_review_policy_activations_no_update"))
        db.execute(text("UPDATE kyc_review_policy_activations SET approval_reference = 'andere Referenz'"))
        db.commit()
        assert "KYC_REVIEW_POLICY_INVALID" in _kyc_codes(db)


def test_wrong_seen_hash_at_activation_is_rejected(sf):
    with sf() as db:
        _setup(db)
        row = _propose(db)
        with pytest.raises(HTTPException) as exc:
            _activate(db, row, policy_hash="0" * 64)
        assert exc.value.detail["reason_code"] == "KYC_REVIEW_POLICY_HASH_MISMATCH"
        assert db.query(KycReviewPolicyActivation).count() == 0


@pytest.mark.parametrize("column, value, defect", [
    ("review_policy_version", 7, "version"),
    ("review_policy_id", "ANDERE-POLICY", "version"),
    ("review_policy_hash", "f" * 64, "policy_hash"),
    ("review_max_due", "2099-11-01", "max_due"),
    ("next_review_due", "2099-11-01", "max_due"),
    ("review_interval_months", 120, "interval"),
    ("review_risk_class", "erhoeht", "risk_class"),
    ("tenant_id", "t-fremd", "tenant"),
])
def test_resealed_binding_manipulation_is_detected(sf, column, value, defect):
    """Angreifer mit Schreibzugriff, der sogar das Siegel neu berechnet: die
    Bindung wird gegen Policy, Aktivierung und Kalender nachgerechnet."""
    with sf() as db:
        conf = _bound(db)
        row = db.query(KycConfirmation).filter(KycConfirmation.id == conf.id).first()
        values = {c.name: getattr(row, c.name) for c in row.__table__.columns}
        values.update({"id": new_uuid(), column: value})
        if column == "next_review_due":
            values["review_max_due"] = "2099-11-01"
        values.pop("confirmation_hash")
        values["recorded_at"] = values["recorded_at"] if column == "recorded_at" else "2999-01-01T00:00:00.000Z"
        _insert_confirmation(db, **values)
        findings = gate._kyc_findings(db, mandate(db), gate._utc_now_iso()[:10])
        bad = [f for f in findings if f["reason_code"] == "KYC_REVIEW_POLICY_BINDING_INVALID"]
        assert bad and bad[0]["binding_defect"] in {defect, "max_due", "next_review_due"}
        if column not in ("next_review_due",):
            assert bad[0]["binding_defect"] == defect


def test_backdated_recording_before_policy_activation_is_detected(sf):
    """Zeitmanipulation: Erfassungszeit vor der Freigabe der gebundenen Policy."""
    with sf() as db:
        _setup(db)
        row = _policy(db, normal=24)
        completed = _iso(-2)
        due = gate.add_months_clamped(completed, 24)
        _insert_confirmation(
            db, form_completed_on=completed, next_review_due=due, recorded_at="2000-01-01T00:00:00.000Z",
            review_policy_row_id=row.id, review_policy_activation_id=row.activation_id,
            review_policy_id=row.policy_id, review_policy_version=row.version,
            review_policy_hash=row.policy_hash, review_risk_class="normal",
            review_interval_months=24, review_max_due=due)
        bad = [f for f in gate._kyc_findings(db, mandate(db), gate._utc_now_iso()[:10])
               if f["reason_code"] == "KYC_REVIEW_POLICY_BINDING_INVALID"]
        assert bad and bad[0]["binding_defect"] == "time"


def test_unresealed_binding_manipulation_breaks_the_seal(sf):
    with sf() as db:
        _bound(db)
        db.execute(text("DROP TRIGGER trg_kyc_confirmations_no_update"))
        db.execute(text("UPDATE kyc_confirmations SET next_review_due = '2099-11-01', review_max_due = '2099-11-01'"))
        db.commit()
        assert {"KYC_CONFIRMATION_SEAL_INVALID", "KYC_REVIEW_POLICY_BINDING_INVALID"} <= set(_kyc_codes(db))


def test_binding_columns_are_append_only(sf):
    with sf() as db:
        _bound(db)
        for column, value in (("review_max_due", "'2099-01-01'"), ("review_policy_version", "9"),
                              ("review_policy_hash", "'x'")):
            with pytest.raises(Exception, match="immutable"):
                db.execute(text(f"UPDATE kyc_confirmations SET {column} = {value}"))
            db.rollback()
        for table in ("kyc_review_policies", "kyc_review_policy_activations"):
            with pytest.raises(Exception, match="immutable"):
                db.execute(text(f"UPDATE {table} SET tenant_id = 'x'"))
            db.rollback()
            with pytest.raises(Exception, match="immutable"):
                db.execute(text(f"DELETE FROM {table}"))
            db.rollback()


def _second_tenant(db):
    db.add(Tenant(id="t-fremd", display_name="Fremd", slug="t-fremd", created_at=NOW, updated_at=NOW))
    for uid in ("adm-f1", "adm-f2"):
        db.add(User(id=uid, username=uid, password_hash="x", full_name=uid, role="admin", is_active=1,
                    tenant_id="t-fremd", created_at=NOW, updated_at=NOW))
    db.commit()


def test_policy_of_another_tenant_never_applies_and_is_not_reachable(sf):
    """Tenant-/IDOR-Negativtests: fremde Policy gilt nicht, ist nicht
    sichtbar und nicht aktivierbar."""
    with sf() as db:
        _setup(db)
        _second_tenant(db)
        ensure_test_legal_profile(db, "t-fremd")
        db.commit()
        foreign = _propose(db, by="adm-f1")
        assert foreign.tenant_id == "t-fremd"
        _activate(db, foreign, by="adm-f2")
        assert _blocked_code(db)[1]["reason_code"] == "KYC_REVIEW_POLICY_MISSING"
        assert list_kyc_review_policies(jurisdiction=None, db=db, current_user=user(db, "adm-1")).policies == []
        own = _propose(db)
        with pytest.raises(HTTPException) as exc:
            _activate(db, own, by="adm-f1")
        assert exc.value.status_code == 404
        with pytest.raises(HTTPException) as exc:
            activate_kyc_review_policy(
                policy_row_id=foreign.id,
                body=KycReviewPolicyActivate(policy_hash=foreign.policy_hash, approval_reference="x" * 3),
                request=Req(), db=db, current_user=user(db, "adm-2"))
        assert exc.value.status_code == 404
        # Bestaetigung des eigenen Kunden, gebunden an die fremde Policy.
        _activate(db, own)
        foreign_act = db.query(KycReviewPolicyActivation).filter(
            KycReviewPolicyActivation.tenant_id == "t-fremd").first()
        completed = _iso(-2)
        _insert_confirmation(
            db, form_completed_on=completed, next_review_due=gate.add_months_clamped(completed, 24),
            recorded_at=gate._utc_now_iso(),
            review_policy_row_id=foreign.id, review_policy_activation_id=foreign_act.id,
            review_policy_id=foreign.policy_id, review_policy_version=foreign.version,
            review_policy_hash=foreign.policy_hash, review_risk_class="normal",
            review_interval_months=24, review_max_due=gate.add_months_clamped(completed, 24))
        bad = [f for f in gate._kyc_findings(db, mandate(db), gate._utc_now_iso()[:10])
               if f["reason_code"] == "KYC_REVIEW_POLICY_BINDING_INVALID"]
        assert bad and bad[0]["binding_defect"] == "tenant"


# ---------------------------------------------------------------------------
# 9. Parallelaktivierung -> hoechstens eine wirksame Version (SQLite)
# ---------------------------------------------------------------------------


def test_database_allows_only_one_activation_per_predecessor(sf):
    with sf() as db:
        _setup(db)
        first, second = _propose(db, normal=24), _propose(db, normal=12)
        for row in (first, second):
            act = KycReviewPolicyActivation(
                id=new_uuid(), tenant_id=TENANT, jurisdiction="CH", policy_row_id=row.id,
                predecessor_activation_id="GENESIS", approved_by="adm-2", approved_at=NOW,
                approval_reference="x", policy_hash=row.policy_hash, activation_hash="h")
            db.add(act)
            if row is first:
                db.commit()
            else:
                with pytest.raises(IntegrityError):
                    db.commit()
                db.rollback()
        assert db.query(KycReviewPolicyActivation).count() == 1


def test_racing_activation_through_the_api_yields_409_and_one_version(sf, monkeypatch):
    """Zwei Admins aktivieren gleichzeitig auf denselben Stand: der zweite
    sieht noch den alten Kettenkopf (simuliert) und scheitert am UNIQUE."""
    import routers.review as review_router

    with sf() as db:
        _setup(db)
        first, second = _propose(db, normal=24), _propose(db, normal=12)
        stale = review_router.resolve_kyc_review_policy(db, TENANT, "CH", "9999-12-31")
        _activate(db, first)
        monkeypatch.setattr(review_router, "resolve_kyc_review_policy", lambda *a, **k: stale)
        with pytest.raises(HTTPException) as exc:
            _activate(db, second)
        assert (exc.value.status_code, exc.value.detail["reason_code"]) == (
            409, "KYC_REVIEW_POLICY_ACTIVATION_CONFLICT")
        monkeypatch.undo()
        assert db.query(KycReviewPolicyActivation).count() == 1
        overview = list_kyc_review_policies(jurisdiction=None, db=db, current_user=user(db, "adv-1"))
        assert [p.status for p in overview.policies] == ["entwurf", "wirksam"]
        assert overview.effective_policy["id"] == first.id


def test_stale_version_cannot_be_activated_after_a_newer_one(sf):
    with sf() as db:
        _setup(db)
        older, newer = _propose(db, normal=24), _propose(db, normal=12)
        _activate(db, newer)
        with pytest.raises(HTTPException) as exc:
            _activate(db, older)
        assert exc.value.detail["reason_code"] == "KYC_REVIEW_POLICY_VERSION_STALE"


# ---------------------------------------------------------------------------
# 10. UI/API/PDF/Signatur/Handoff: derselbe Reason-Code und Status
# ---------------------------------------------------------------------------


def _channels(db, code: str, status: str) -> None:
    """Prueft Status-Endpoint (API/UI-Quelle), Finalisierungs-, Signatur-,
    Handoff-Gate, Vor-Ort-Signatur und Kunden-PDF (vertrag.pdf)."""
    from routers.onsite_signature import _release_gates
    from routers.pdf_reports import get_vertrag_pdf

    view = get_client_onboarding_status(mandate_id="m-1", db=db, current_user=user(db, "adv-1"))
    assert code in [f["reason_code"] for f in view["findings"]]
    assert view["kyc_review_policy"]["reason_code"] == code
    assert view["kyc_review_policy"]["status"] == status
    assert not view["release_ready"]
    for channel in (gate.CHANNEL_FINALIZATION, gate.CHANNEL_SIGNATURE, gate.CHANNEL_HANDOFF):
        with pytest.raises(DomainError) as exc:
            gate.assert_client_onboarding_release_eligible(db, mandate(db), channel=channel)
        assert code in exc.value.extra["finding_codes"]
        finding = next(f for f in exc.value.extra["findings"] if f["reason_code"] == code)
        assert finding["kyc_review_status"] == status
    doc_id = new_uuid()
    db.add(ContractDocument(
        id=doc_id, mandate_id="m-1", document_type="Beratungsvertrag", title="Vertrag", status="Bereit",
        signed_by_advisor=0, signed_by_client=0, version=1, checksum_sha256="c" * 64,
        pdf_base64="JVBERg==", created_by="adv-1", created_at=NOW, updated_at=NOW))
    db.commit()
    doc = db.query(ContractDocument).filter(ContractDocument.id == doc_id).first()
    with pytest.raises(DomainError) as exc:
        _release_gates(db, mandate(db), doc, current_user=user(db, "adv-1"), request=None)
    assert code in exc.value.extra["finding_codes"]
    with pytest.raises(DomainError) as exc:
        get_vertrag_pdf(mandate_id="m-1", document_id=None, db=db, current_user=user(db, "adv-1"))
    assert exc.value.reason_code == "CLIENT_ONBOARDING_INCOMPLETE"
    assert code in exc.value.extra["finding_codes"]
    assert next(f for f in exc.value.extra["findings"] if f["reason_code"] == code)["kyc_review_status"] == status
    audit = _review_audit(db)
    assert any(v.startswith(f"{code};kanal=onsite_signature_blocked;") for v in audit), audit
    assert any(v.startswith(f"{code};kanal=client_pdf_blocked;") for v in audit), audit
    tenants = {a.tenant_id for a in db.query(AuditLog).filter(
        AuditLog.field_name == "kyc_review_policy_blocked").all()}
    assert tenants == {TENANT}


def test_existing_confirmation_is_policy_binding_missing_in_every_channel(sf):
    with sf() as db:
        satisfy_client_onboarding(db, mandate(db), actor_id="adv-1")
        db.commit()
        assert _kyc_codes(db) == []
        _legacy_confirmation(db)
        assert _kyc_codes(db) == ["KYC_REVIEW_POLICY_BINDING_MISSING"]
        _channels(db, "KYC_REVIEW_POLICY_BINDING_MISSING", "policy_binding_missing")


def test_expired_policy_reports_the_same_code_in_every_channel(sf):
    with sf() as db:
        satisfy_client_onboarding(db, mandate(db), actor_id="adv-1")
        db.commit()
        policy = db.query(KycReviewPolicy).first()
        ensure_test_kyc_review_policy(db, TENANT, actor_id="adm-1", policy_id="TEST-C890-EXPIRED",
                                      normal_max_months=policy.normal_max_months, valid_until="2001-01-01",
                                      approved_at="2000-06-01T00:00:00.000Z")
        db.commit()
        _channels(db, "KYC_REVIEW_POLICY_EXPIRED", "policy_expired")
        assert _blocked_code(db)[1]["reason_code"] == "KYC_REVIEW_POLICY_EXPIRED"


def test_every_client_pdf_endpoint_calls_the_central_review_gate():
    import ast

    source = (Path(__file__).resolve().parents[1] / "routers" / "pdf_reports.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        calls = {getattr(n.func, "id", None) for n in ast.walk(node) if isinstance(n, ast.Call)}
        if "_assert_client_pdf_signoff" in calls or node.name == "get_vertrag_pdf":
            assert "_assert_client_pdf_kyc_review" in calls, node.name


def test_reason_codes_are_in_the_catalog():
    # Geschlossener Wertebereich der durchgereichten Wiedervorlage-Codes.
    for code in list(gate._REVIEW_MESSAGES) + list(gate.KYC_REVIEW_STATUS_BY_CODE):
        assert ReasonCode(code).value == code
    for name in dir(gate):
        if name.startswith("KYC_REVIEW_POLICY_") or name == "KYC_REVIEW_DUE_EXCEEDS_POLICY":
            value = getattr(gate, name)
            if isinstance(value, str):
                assert ReasonCode(value).value == value


# ---------------------------------------------------------------------------
# 11. SQLite: Schema, Runtime-Patch einer H8-Datenbank, Paritaet
# ---------------------------------------------------------------------------


def test_constants_match_between_gate_models_and_database():
    import database as db_module
    from models.tenant import KYC_REVIEW_GENESIS

    assert gate.KYC_REVIEW_GENESIS == KYC_REVIEW_GENESIS
    assert gate.KYC_REVIEW_BINDING_COLUMNS == db_module.KYC_CONFIRMATION_REVIEW_BINDING_COLUMNS
    assert set(db_module.KYC_CONFIRMATION_FIXED_COLUMNS) | set(db_module.KYC_CONFIRMATION_REDACTABLE_COLUMNS) == {
        c.name for c in KycConfirmation.__table__.columns}


def test_runtime_patch_upgrades_an_h8_database(tmp_path, monkeypatch):
    """Eine H8-SQLite-DB (kyc_confirmations ohne Bindungsspalten, alter
    Trigger) bekommt die Spalten und einen Trigger, der sie mitschuetzt;
    die Bestandszeile bleibt unveraendert ohne Bindung."""
    from sqlalchemy import create_engine

    import database as db_module

    db_path = tmp_path / "h8.db"
    db_module.bootstrap_sqlite_schema(db_path=db_path,
                                      schema_path=Path(__file__).resolve().parents[1] / "ares_schema.sql")
    engine = create_engine(f"sqlite:///{db_path}")
    h8_fixed = db_module.KYC_CONFIRMATION_FIXED_COLUMNS[:16]
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE kyc_confirmations (" + ", ".join(
                f"{c} TEXT" for c in h8_fixed + db_module.KYC_CONFIRMATION_REDACTABLE_COLUMNS) + ")"))
        for ddl in db_module._redaction_only_sqlite_triggers(
                "kyc_confirmations", h8_fixed, db_module.KYC_CONFIRMATION_REDACTABLE_COLUMNS):
            conn.execute(text(ddl))
        conn.execute(text("INSERT INTO kyc_confirmations (id, client_id) VALUES ('k1', 'c1')"))
    monkeypatch.setattr(db_module, "engine", engine)
    db_module.ensure_runtime_columns()
    db_module.ensure_runtime_columns()
    with engine.begin() as conn:
        columns = {row[1] for row in conn.execute(text("PRAGMA table_info(kyc_confirmations)"))}
        assert set(gate.KYC_REVIEW_BINDING_COLUMNS) <= columns
        assert conn.execute(text("SELECT review_policy_row_id FROM kyc_confirmations")).scalar() is None
    with engine.connect() as conn:
        with pytest.raises(Exception, match="immutable"):
            conn.execute(text("UPDATE kyc_confirmations SET review_max_due = '2099-01-01'"))
    engine.dispose()


def test_alembic_sqlite_upgrade_downgrade_upgrade_and_fail_closed_downgrade(tmp_path):
    from alembic import command
    from sqlalchemy import create_engine, inspect

    from h8_support import alembic_cfg

    url = f"sqlite:///{tmp_path / 'mig.db'}"
    cfg = alembic_cfg(url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "d8e4b2a6c1f9")
    engine = create_engine(url)
    assert "kyc_review_policies" not in inspect(engine).get_table_names()
    assert "review_policy_row_id" not in {c["name"] for c in inspect(engine).get_columns("kyc_confirmations")}
    engine.dispose()
    command.upgrade(cfg, "head")
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO kyc_review_policies (id, tenant_id, jurisdiction, policy_id, version, "
            "normal_max_months, valid_from, source_reference, created_by, created_at, policy_hash) "
            "VALUES ('p1','t','CH','TEST-C890',1,12,'2026-01-01','TEST-C890 Testwert','u','n','h')"))
        with pytest.raises(Exception):
            conn.execute(text(
                "INSERT INTO kyc_review_policies (id, tenant_id, jurisdiction, policy_id, version, "
                "normal_max_months, elevated_max_months, valid_from, source_reference, created_by, "
                "created_at, policy_hash) VALUES ('p2','t','CH','TEST-C890',2,12,24,'2026-01-01','x','u','n','h')"))
    engine.dispose()
    with pytest.raises(RuntimeError, match="fail-closed"):
        command.downgrade(cfg, "d8e4b2a6c1f9")
    engine = create_engine(url)
    assert "kyc_review_policies" in inspect(engine).get_table_names()
    engine.dispose()


def test_alembic_postgres_ddl_for_kyc_review_policy():
    import io

    from alembic import command

    from h8_support import alembic_cfg

    out = io.StringIO()
    command.upgrade(alembic_cfg("postgresql://u:p@localhost/db", out), "d8e4b2a6c1f9:f4c2e8a6d1b3", sql=True)
    ddl = out.getvalue()
    for table in ("kyc_review_policies", "kyc_review_policy_activations"):
        assert f"CREATE TABLE {table}" in ddl
        assert f"CREATE TRIGGER trg_{table}_immutable" in ddl
    assert "uq_kyc_review_policy_activations_chain UNIQUE (tenant_id, jurisdiction, predecessor_activation_id)" in ddl
    assert "CONSTRAINT ck_kyc_review_policies_elevated CHECK" in ddl
    assert "CREATE OR REPLACE FUNCTION kyc_confirmations_immutable()" in ddl
    assert "NEW.review_max_due IS DISTINCT FROM OLD.review_max_due" in ddl
    for column in gate.KYC_REVIEW_BINDING_COLUMNS:
        assert f"ALTER TABLE kyc_confirmations ADD COLUMN {column}" in ddl


# ---------------------------------------------------------------------------
# 12. bestehendes Gate fuer abgelaufene Termine bleibt gruen getestet
# ---------------------------------------------------------------------------


def test_bound_confirmation_past_its_due_date_is_overdue(sf):
    with sf() as db:
        _bound(db)
        conf = gate.latest_kyc_confirmation(db, "c-1", "m-1")
        after = (date.fromisoformat(conf["next_review_due"]) + timedelta(days=1)).isoformat()
        assert _kyc_codes(db, after) == ["KYC_CONFIRMATION_REVIEW_OVERDUE"]
        assert [f["reason_code"] for f in gate.kyc_review_release_findings(db, mandate(db), after)] == [
            "KYC_CONFIRMATION_REVIEW_OVERDUE"]
        assert _kyc_codes(db, conf["next_review_due"]) == []
