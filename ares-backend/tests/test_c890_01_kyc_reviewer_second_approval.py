"""C-890-01 Nachtrag 2: H8-Vier-Augen-Freigabe (PEP, erhoehtes Risiko,
Herabstufung, PEP-Ruecknahme) auch durch die externe Compliance-Person.

Ansicht "Offene Freigaben" (GET /compliance/kyc-approvals) datenminimiert,
Entscheid (POST /compliance/kyc-approvals/{id}/decision) mit Pflicht-
Begruendung und Hash-Bestaetigung; Selbstfreigabe (gleiche ID oder gleiche
E-Mail) 403; Gate akzeptiert Freigaben von admin ODER compliance_reviewer.
Fristen der Fixture-Policy sind TESTWERTE.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import text

TESTS_ROOT = Path(__file__).resolve().parent
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from test_c890_01_compliance_reviewer_role import (  # noqa: E402,F401
    NOW, PW, TENANT, _auth, client, session_factory,
)

from models.clients import KycConfirmation, KycConfirmationApproval, KycConfirmationRejection  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from models.review import AuditLog  # noqa: E402
from models.users import User  # noqa: E402
from schemas.clients import KYC_PENDING_APPROVAL_FIELDS  # noqa: E402
from services import recommendation_release_gate as gate  # noqa: E402
from services.auth import COMPLIANCE_APPROVER_ROLES, COMPLIANCE_REVIEWER_SCOPE, hash_password  # noqa: E402

from client_onboarding_fixture import ensure_test_kyc_review_policy  # noqa: E402

TODAY = datetime.now(timezone.utc).date()


def _iso(days: int) -> str:
    return (TODAY + timedelta(days=days)).isoformat()


@pytest.fixture()
def seeded(session_factory):
    with session_factory() as db:
        ensure_test_kyc_review_policy(db, TENANT, actor_id="adm-1")
        db.query(User).filter(User.id == "adv-1").update({"email": "berater@example.invalid"})
        db.add(User(id="adm-dup", username="adm-dup", password_hash=hash_password(PW), full_name="Zweitkonto",
                    role="admin", is_active=1, tenant_id=TENANT, email="BERATER@example.invalid",
                    created_at=NOW, updated_at=NOW))
        db.commit()
    return session_factory


def _dd(client, headers, *, pep: bool):
    r = client.put("/clients/c-1/due-diligence", headers=headers,
                   json={"acting_for_own_account": True, "pep_status": pep})
    assert r.status_code in (200, 201), r.text


def _kyc(client, headers, **overrides):
    body = {"form_type": "A", "form_completed_on": _iso(-2), "external_reference": "SRO-Dossier 4711",
            "risk_category": "normal", "is_pep": False, "identification_confirmed": True,
            "identification_date": _iso(-3), "next_review_due": _iso(60), "note": "Testbemerkung C890"}
    body.update(overrides)
    r = client.post("/clients/c-1/kyc-confirmations", headers=headers, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _codes(session_factory):
    with session_factory() as db:
        mandate = db.get(Mandate, "m-1")
        return [f["reason_code"] for f in gate._kyc_findings(db, mandate, gate._utc_now_iso()[:10])]


def _decide(client, headers, item, decision="approve", **overrides):
    body = {"decision": decision, "reason": "Unterlagen geprueft (Test)",
            "confirmation_hash": item["confirmation_hash"]}
    body.update(overrides)
    return client.post(f"/compliance/kyc-approvals/{item['confirmation_id']}/decision", headers=headers, json=body)


def test_pep_flow_reviewer_approves_gate_turns_green(client, seeded):
    adv, rev = _auth(client, "adv-1"), _auth(client, "rev-1")
    _dd(client, adv, pep=True)
    conf = _kyc(client, adv, is_pep=True, next_review_due=_iso(30))
    assert conf["requires_second_approval"] is True
    assert "KYC_SECOND_APPROVAL_MISSING" in _codes(seeded)
    listing = client.get("/compliance/kyc-approvals", headers=rev)
    assert listing.status_code == 200
    items = listing.json()["items"]
    assert len(items) == 1
    item = items[0]
    assert set(item) == set(KYC_PENDING_APPROVAL_FIELDS)
    assert (item["client_number"], item["is_pep_new"], item["risk_category_new"], item["approval_reasons"]) == (
        "K-1", True, "normal", ["pep"])
    assert item["recorded_by_self"] is False and item["recorded_by_name"] == "ADV-1"
    assert "Eva" not in str(item) and "Muster" not in str(item)
    assert _decide(client, rev, item, confirmation_hash="0" * 64).json()["detail"]["reason_code"] == (
        "KYC_APPROVAL_HASH_MISMATCH")
    assert _decide(client, rev, item, reason="kurz").status_code == 422
    r = _decide(client, rev, item)
    assert r.status_code == 200, r.text
    assert "KYC_SECOND_APPROVAL_MISSING" not in _codes(seeded)
    assert client.get("/compliance/kyc-approvals", headers=rev).json()["items"] == []
    assert _decide(client, rev, item).json()["detail"]["reason_code"] == "KYC_SECOND_APPROVAL_ALREADY_DECIDED"
    with seeded() as db:
        audit = db.query(AuditLog).filter(AuditLog.field_name == "kyc_second_approval").all()
        assert [(a.user_id, a.tenant_id, a.new_value.split(";")[0]) for a in audit] == [("rev-1", TENANT, conf["id"])]
        # N-897-02: Herkunft des Freigeberkontos steht im Protokoll.
        assert "eingeladen von ADM-1" in audit[0].new_value and "2FA selbst" in audit[0].new_value


def test_rejection_keeps_gate_red_and_blocks_later_approval(client, seeded):
    adv, rev, adm = _auth(client, "adv-1"), _auth(client, "rev-1"), _auth(client, "adm-2")
    _dd(client, adv, pep=False)
    conf = _kyc(client, adv, risk_category="erhoeht", next_review_due=_iso(30))
    item = client.get("/compliance/kyc-approvals", headers=rev).json()["items"][0]
    assert item["approval_reasons"] == ["erhoehtes_risiko"]
    assert _decide(client, rev, item, decision="reject", reason="Mittelherkunft nicht belegt").status_code == 200
    codes = _codes(seeded)
    assert "KYC_CONFIRMATION_REJECTED" in codes and "KYC_SECOND_APPROVAL_MISSING" not in codes
    r = client.post(f"/clients/c-1/kyc-confirmations/{conf['id']}/approve", headers=adm, json={})
    assert r.status_code == 409 and r.json()["detail"]["reason_code"] == "KYC_SECOND_APPROVAL_ALREADY_DECIDED"
    with seeded() as db:
        assert db.query(KycConfirmationApproval).count() == 0
        rejection = db.query(KycConfirmationRejection).one()
        assert rejection.confirmation_hash == conf["confirmation_hash"]
        with pytest.raises(Exception, match="immutable"):
            db.execute(text("UPDATE kyc_confirmation_rejections SET reason = 'anders'"))
        db.rollback()


def test_downgrade_and_pep_withdrawal_show_old_and_new_values(client, seeded):
    adv, rev = _auth(client, "adv-1"), _auth(client, "rev-1")
    _dd(client, adv, pep=True)
    first = _kyc(client, adv, is_pep=True, risk_category="erhoeht", next_review_due=_iso(30))
    item = client.get("/compliance/kyc-approvals", headers=rev).json()["items"][0]
    assert _decide(client, rev, item).status_code == 200
    _dd(client, adv, pep=False)
    _kyc(client, adv, is_pep=False, risk_category="normal", next_review_due=_iso(30))
    item = client.get("/compliance/kyc-approvals", headers=rev).json()["items"][0]
    assert item["confirmation_id"] != first["id"]
    assert (item["risk_category_previous"], item["risk_category_new"]) == ("erhoeht", "normal")
    assert (item["is_pep_previous"], item["is_pep_new"]) == (True, False)
    assert set(item["approval_reasons"]) == {"herabstufung", "pep_ruecknahme"}
    assert item["pep_withdrawal_recorded"] is True
    assert "KYC_SECOND_APPROVAL_MISSING" in _codes(seeded)
    assert _decide(client, rev, item).status_code == 200
    assert "KYC_SECOND_APPROVAL_MISSING" not in _codes(seeded)


def test_self_approval_blocked_by_id_and_by_same_email(client, seeded):
    adv, adm1, dup = _auth(client, "adv-1"), _auth(client, "adm-1"), _auth(client, "adm-dup")
    _dd(client, adm1, pep=True)
    own = _kyc(client, adm1, is_pep=True, next_review_due=_iso(30))
    item = client.get("/compliance/kyc-approvals", headers=adm1).json()["items"][0]
    assert item["recorded_by_self"] is True
    r = _decide(client, adm1, item)
    assert r.status_code == 403 and r.json()["detail"]["reason_code"] == "KYC_SECOND_APPROVAL_SAME_PERSON"
    assert own["id"] == item["confirmation_id"]
    # Berater erfasst, dieselbe Person (gleiche E-Mail) versucht es mit einem Admin-Zweitkonto.
    second = _kyc(client, adv, is_pep=True, next_review_due=_iso(30))
    item = client.get("/compliance/kyc-approvals", headers=dup).json()["items"][0]
    assert item["confirmation_id"] == second["id"] and item["recorded_by_self"] is True
    r = _decide(client, dup, item)
    assert r.status_code == 403 and r.json()["detail"]["reason_code"] == "KYC_SECOND_APPROVAL_SAME_PERSON"
    r = client.post(f"/clients/c-1/kyc-confirmations/{second['id']}/approve", headers=dup, json={})
    assert r.status_code == 403


def test_gate_ignores_approvals_from_roles_without_approval_right_or_same_email(client, seeded):
    adv = _auth(client, "adv-1")
    _dd(client, adv, pep=True)
    conf = _kyc(client, adv, is_pep=True, next_review_due=_iso(30))
    with seeded() as db:
        approval = KycConfirmationApproval(id="ap-x", tenant_id=TENANT, confirmation_id=conf["id"],
                                           client_id="c-1", approved_by="adm-dup", approved_at=NOW, note="x")
        approval.approval_hash = gate.row_seal(
            {c.name: getattr(approval, c.name) for c in approval.__table__.columns}, "approval_hash")
        db.add(approval)
        db.commit()
    assert "KYC_SECOND_APPROVAL_MISSING" in _codes(seeded)
    assert gate.KYC_APPROVER_ROLES == COMPLIANCE_APPROVER_ROLES


def test_gate_ignores_approval_by_advisor_role(seeded):
    with seeded() as db:
        conf = KycConfirmation(
            id="k-adv", tenant_id=TENANT, client_id="c-1", process_scope="sro_oder_fremdprozess", form_type="A",
            form_completed_on=_iso(-2), external_reference="x", risk_category="erhoeht", is_pep=0,
            identification_confirmed=1, identification_date=_iso(-2), next_review_due=_iso(30),
            requires_second_approval=1, recorded_by="adm-1", recorded_at="2999-01-01T00:00:00.000Z")
        conf.confirmation_hash = gate.row_seal(
            {c.name: getattr(conf, c.name) for c in conf.__table__.columns
             if c.name not in gate.KYC_REVIEW_BINDING_COLUMNS}, "confirmation_hash")
        db.add(conf)
        approval = KycConfirmationApproval(id="ap-adv", tenant_id=TENANT, confirmation_id="k-adv",
                                           client_id="c-1", approved_by="adv-1", approved_at=NOW, note="x")
        approval.approval_hash = gate.row_seal(
            {c.name: getattr(approval, c.name) for c in approval.__table__.columns}, "approval_hash")
        db.add(approval)
        db.commit()
        found = gate.latest_kyc_confirmation(db, "c-1", "m-1")
        assert found["id"] == "k-adv" and found["approval_by"] is None


@pytest.mark.parametrize("method, path, body", [
    ("GET", "/clients/c-1", None),
    ("GET", "/clients/c-1/kyc-confirmations", None),
    ("POST", "/clients/c-1/kyc-confirmations", {}),
    ("POST", "/clients/c-1/kyc-confirmations/x/approve", {}),
    ("PUT", "/clients/c-1/due-diligence", {"pep_status": False}),
    ("GET", "/clients/c-1/wealth-summary", None),
    ("GET", "/clients/c-1/cashflow-projection", None),
    ("GET", "/mandates/m-1/client-onboarding/status", None),
    ("GET", "/mandates/m-1/reports/anlagestrategie.pdf", None),
    ("GET", "/mandates/m-1/reports/risikoprofil.pdf", None),
])
def test_reviewer_still_has_no_client_detail_wealth_pdf_or_edit_access(client, seeded, method, path, body):
    rev = _auth(client, "rev-1")
    r = client.request(method, path, headers=rev, json=body)
    assert r.status_code == 403, (path, r.status_code, r.text)
    assert r.json()["detail"]["reason_code"] == COMPLIANCE_REVIEWER_SCOPE


def test_foreign_tenant_reviewer_sees_nothing_and_gets_404(client, seeded):
    adv, foreign = _auth(client, "adv-1"), _auth(client, "rev-f")
    _dd(client, adv, pep=True)
    conf = _kyc(client, adv, is_pep=True, next_review_due=_iso(30))
    assert client.get("/compliance/kyc-approvals", headers=foreign).json()["items"] == []
    r = client.post(f"/compliance/kyc-approvals/{conf['id']}/decision", headers=foreign,
                    json={"decision": "approve", "reason": "fremder Tenant", "confirmation_hash": conf["confirmation_hash"]})
    assert r.status_code == 404


def test_advisor_cannot_use_the_approval_view(client, seeded):
    adv = _auth(client, "adv-1")
    assert client.get("/compliance/kyc-approvals", headers=adv).status_code == 403


def test_allowlist_covers_exactly_the_approval_view():
    from services.auth import compliance_reviewer_may_call

    assert compliance_reviewer_may_call("GET", "/compliance/kyc-approvals")
    assert compliance_reviewer_may_call("POST", "/compliance/kyc-approvals/abc/decision")
    for method, path in (("GET", "/compliance/kyc-approvals/abc"), ("PUT", "/compliance/kyc-approvals/abc/decision"),
                         ("POST", "/compliance/kyc-approvals"), ("GET", "/compliance/kyc-approvals/abc/decision"),
                         ("POST", "/clients/c-1/kyc-confirmations/abc/approve")):
        assert not compliance_reviewer_may_call(method, path), (method, path)
