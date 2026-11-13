"""C-890-01 Nachtrag 4 (Delta-Pruefung 0474360c, N-897-10..13).

- N-897-10: Herkunftsindizien der Einladung (IP/User-Agent im Audit, Minuten
  bis zur Annahme, gleiche IP/gleiches Geraet) und Link nur per Mail, wenn ein
  Mailkanal konfiguriert ist.
- N-897-11: die Bereitschaftspruefung der KYC-Entscheid-Route ist gepinnt; ein
  nicht bereites Konto verbraucht keine Entscheidzeile.
- N-897-13: Bereitschaft wird beim Entscheid eingefroren; nur ein auditierter
  Widerruf wegen Kompromittierung entwertet Freigaben ab einem Zeitpunkt.
- N-897-12: Archivexemplar gekennzeichnet, Export-/CSV-Routen klassifiziert,
  kundenwirksame Berichte ohne KYC-Bestaetigung als Entwurf gekennzeichnet.
Alle Fristen sind TESTWERTE (TEST-C890).
"""
from __future__ import annotations

import base64
import io
import sys
import time
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

from models.clients import KycConfirmationApproval, KycConfirmationDecision  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from models.review import AuditLog, ContractDocument  # noqa: E402
from models.users import User  # noqa: E402
from services import recommendation_release_gate as gate  # noqa: E402

from client_onboarding_fixture import ensure_test_kyc_review_policy, satisfy_client_onboarding  # noqa: E402

TODAY = datetime.now(timezone.utc).date()


def _iso(days: int) -> str:
    return (TODAY + timedelta(days=days)).isoformat()


def _codes(sf):
    with sf() as db:
        return [f["reason_code"] for f in gate._kyc_findings(db, db.get(Mandate, "m-1"), gate._utc_now_iso()[:10])]


def _pep(client, sf):
    adv = _auth(client, "adv-1")
    with sf() as db:
        ensure_test_kyc_review_policy(db, TENANT, actor_id="adm-1")
        db.commit()
    client.put("/clients/c-1/due-diligence", headers=adv, json={"acting_for_own_account": True, "pep_status": True})
    r = client.post("/clients/c-1/kyc-confirmations", headers=adv, json={
        "form_type": "A", "form_completed_on": _iso(-2), "external_reference": "SRO-N4", "risk_category": "normal",
        "is_pep": True, "identification_confirmed": True, "identification_date": _iso(-2),
        "next_review_due": _iso(30)})
    assert r.status_code == 201, r.text
    return r.json()


def _decide(client, headers, conf, decision="approve"):
    return client.post(f"/compliance/kyc-approvals/{conf['id']}/decision", headers=headers, json={
        "decision": decision, "reason": "geprueft (Test N4)", "confirmation_hash": conf["confirmation_hash"]})


# ---------------------------------------------------------------------------
# N-897-10
# ---------------------------------------------------------------------------


def _invite(client, admin):
    return client.post("/users/invite", headers=admin, json={
        "username": "ext-4", "full_name": "Externe Pruefperson 4", "email": "pruef4@testfirma.ch",
        "role": "compliance_reviewer", "reviewer_organisation": "TEST-C890 Revision AG",
        "reviewer_reference": "TEST-C890 Mandat 4"})


def test_invite_accept_2fa_audited_with_ip_and_user_agent_and_origin_hint(client, session_factory):
    from services import totp

    admin = _auth(client, "adm-1")
    token = _invite(client, admin).json()["invite_token"]
    r = client.post("/auth/invite/accept", json={"token": token, "password": "Selbstgesetzt-C890"})
    ext = {"Authorization": "Bearer " + r.json()["access_token"]}
    secret = client.post("/auth/2fa/setup", headers=ext).json()["secret"]
    assert client.post("/auth/2fa/enable", headers=ext, json={"code": totp.totp_at(secret, time.time())}).status_code == 200
    with session_factory() as db:
        uid = db.query(User).filter(User.username == "ext-4").one().id
        rows = {a.action: a for a in db.query(AuditLog).filter(AuditLog.record_id == uid).all()}
        for action in ("INVITE", "INVITE_ACCEPT", "2FA_ENABLE"):
            assert rows[action].ip_address, action
            assert "testclient" in (rows[action].new_value or ""), action
            assert len(rows[action].new_value) < 120, action
        account = gate.kyc_approver_account(db, uid)
    assert account["accepted_after_minutes"] == 0
    assert account["same_ip_as_inviter"] is True and account["same_device_as_inviter"] is True
    assert account["origin_hint"].startswith("angenommen nach 0 Minuten; gleiche IP wie Einladender: ja")


def test_reviewer_invite_link_only_by_mail_when_mail_is_configured(client, monkeypatch):
    import routers.auth as auth_router

    monkeypatch.setattr(auth_router, "mail_configured", lambda: True)
    monkeypatch.setattr(auth_router, "send_invite_email", lambda *a, **k: True)
    admin = _auth(client, "adm-1")
    r = _invite(client, admin)
    assert r.status_code == 201
    body = r.json()
    assert (body["invite_token"], body["link_delivery"], body["email_sent"]) == (None, "nur_email", True)
    other = client.post("/users/invite", headers=admin, json={
        "username": "berater-2", "full_name": "Berater 2", "email": "b2@testfirma.ch", "role": "advisor"})
    assert other.json()["invite_token"] and other.json()["link_delivery"] == "anzeige"


def test_without_mail_the_link_is_shown(client):
    body = _invite(client, _auth(client, "adm-1")).json()
    assert body["invite_token"] and body["link_delivery"] == "anzeige"


# ---------------------------------------------------------------------------
# N-897-11
# ---------------------------------------------------------------------------


def test_unready_reviewer_gets_403_before_any_decision_row(client, session_factory):
    conf = _pep(client, session_factory)
    with session_factory() as db:
        db.execute(text("UPDATE users SET totp_enabled = 0, totp_set_by = NULL WHERE id = 'rev-1'"))
        db.commit()
    rev = _auth(client, "rev-1")
    r = _decide(client, rev, conf)
    assert r.status_code == 403 and r.json()["detail"]["reason_code"] == "COMPLIANCE_REVIEWER_2FA_REQUIRED"
    with session_factory() as db:
        assert db.query(KycConfirmationDecision).count() == 0
        assert db.query(KycConfirmationApproval).count() == 0
        db.execute(text("UPDATE users SET credentials_set_by = 'adm-1', totp_enabled = 1, totp_set_by = 'self' "
                        "WHERE id = 'rev-1'"))
        db.commit()
    r = _decide(client, rev, conf)
    assert r.status_code == 403 and r.json()["detail"]["reason_code"] == "COMPLIANCE_REVIEWER_ACCOUNT_UNVERIFIED"
    with session_factory() as db:
        db.execute(text("UPDATE users SET credentials_set_by = 'self' WHERE id = 'rev-1'"))
        db.commit()
    assert _decide(client, rev, conf).status_code == 200


# ---------------------------------------------------------------------------
# N-897-13
# ---------------------------------------------------------------------------


def test_readiness_is_frozen_at_decision_later_2fa_disable_keeps_approval(client, session_factory):
    conf = _pep(client, session_factory)
    rev = _auth(client, "rev-1")
    assert _decide(client, rev, conf).status_code == 200
    assert "KYC_SECOND_APPROVAL_MISSING" not in _codes(session_factory)
    with session_factory() as db:
        decision = db.query(KycConfirmationDecision).one()
        assert decision.approver_ready == 1 and decision.decision_hash
        db.execute(text("UPDATE users SET totp_enabled = 0, totp_set_by = NULL WHERE id = 'rev-1'"))
        db.commit()
    assert "KYC_SECOND_APPROVAL_MISSING" not in _codes(session_factory)
    # Manipulierter Entscheid (ohne neues Siegel) gilt nicht als eingefroren.
    with session_factory() as db:
        db.execute(text("DROP TRIGGER IF EXISTS trg_kyc_confirmation_decisions_no_update"))
        db.execute(text("UPDATE kyc_confirmation_decisions SET decided_at = '2000-01-01T00:00:00.000Z'"))
        db.commit()
    assert "KYC_SECOND_APPROVAL_MISSING" in _codes(session_factory)


def test_policy_activation_readiness_is_frozen(client, session_factory):
    admin, rev = _auth(client, "adm-1"), _auth(client, "rev-1")
    row = client.post("/compliance/kyc-review-policies", headers=admin, json={
        "jurisdiction": "CH", "policy_id": "TEST-C890-N4", "normal_max_months": 12, "valid_from": _iso(0),
        "source_reference": "TEST-C890 Testwert"}).json()
    r = client.post(f"/compliance/kyc-review-policies/{row['id']}/activate", headers=rev,
                    json={"policy_hash": row["policy_hash"], "approval_reference": "TEST-C890"})
    assert r.status_code == 200, r.text
    with session_factory() as db:
        db.execute(text("UPDATE users SET totp_enabled = 0, totp_set_by = NULL WHERE id = 'rev-1'"))
        db.commit()
        assert gate.resolve_kyc_review_policy(db, TENANT, "CH", gate._utc_now_iso()[:10])["reason_code"] is None


def test_compromise_revocation_invalidates_approvals_from_given_time(client, session_factory):
    conf = _pep(client, session_factory)
    admin, rev = _auth(client, "adm-1"), _auth(client, "rev-1")
    assert _decide(client, rev, conf).status_code == 200
    assert "KYC_SECOND_APPROVAL_MISSING" not in _codes(session_factory)
    # Zeitpunkt in der Zukunft unzulaessig; Begruendung Pflicht; nur Admin.
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    assert client.post("/users/rev-1/compromise", headers=admin,
                       json={"reason": "Verdacht auf Missbrauch (Test)", "compromised_since": future}).status_code == 422
    assert client.post("/users/rev-1/compromise", headers=admin,
                       json={"reason": "kurz", "compromised_since": NOW}).status_code == 422
    assert client.post("/users/rev-1/compromise", headers=_auth(client, "adv-1"),
                       json={"reason": "Verdacht auf Missbrauch (Test)", "compromised_since": NOW}).status_code == 403
    since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    r = client.post("/users/rev-1/compromise", headers=admin,
                    json={"reason": "Zugangsdaten moeglicherweise abgeflossen (Test)", "compromised_since": since})
    assert r.status_code == 200, r.text
    assert r.json()["compromised_since"] and r.json()["is_active"] == 0
    assert "KYC_SECOND_APPROVAL_MISSING" in _codes(session_factory)
    assert client.post("/users/rev-1/compromise", headers=admin,
                       json={"reason": "zweites Mal (Test)", "compromised_since": since}).status_code == 409
    with session_factory() as db:
        audit = db.query(AuditLog).filter(AuditLog.action == "COMPROMISE").one()
        assert audit.user_id == "adm-1" and "Grund:" in audit.new_value


def test_compromise_after_approval_time_keeps_earlier_approvals(client, session_factory):
    conf = _pep(client, session_factory)
    admin, rev = _auth(client, "adm-1"), _auth(client, "rev-1")
    assert _decide(client, rev, conf).status_code == 200
    time.sleep(0.01)
    since = datetime.now(timezone.utc).isoformat()
    assert client.post("/users/rev-1/compromise", headers=admin,
                       json={"reason": "Geraet verloren, ab jetzt (Test)", "compromised_since": since}).status_code == 200
    assert "KYC_SECOND_APPROVAL_MISSING" not in _codes(session_factory)


# ---------------------------------------------------------------------------
# N-897-12
# ---------------------------------------------------------------------------


def test_archive_copy_is_labelled_without_touching_the_bytes(client, session_factory):
    pdf = b"%PDF-1.4 TEST-C890 Archiv"
    with session_factory() as db:
        db.add(ContractDocument(
            id="arch-1", mandate_id="m-1", document_type="Anlagestrategie", title="Anlagestrategie",
            status="Archiviert", signed_by_advisor=0, signed_by_client=0, version=3, checksum_sha256="a" * 64,
            pdf_base64=base64.b64encode(pdf).decode(), pdf_generated_at="2026-10-01T10:00:00.000Z",
            created_by="adv-1", created_at=NOW, updated_at=NOW))
        db.commit()
    r = client.get("/mandates/m-1/documents/arch-1/pdf", headers=_auth(client, "adv-1"))
    assert r.status_code == 200 and r.content == pdf
    assert r.headers["X-Ares-Archive-Copy"] == "true" and r.headers["X-Ares-Archived-On"] == "2026-10-01"
    assert "Archivexemplar_2026-10-01_" in r.headers["Content-Disposition"]


def test_report_route_detection_covers_csv_exports_and_media_types():
    assert gate.is_report_route("/products/export/csv")
    assert gate.is_report_route("/products/import/csv/template")
    assert gate.is_report_route("/irgendwas/download", ("text/csv",))
    assert gate.is_report_route("/irgendwas/datei", ("application/pdf",))
    assert not gate.is_report_route("/clients/{client_id}")


def test_draft_mark_text_is_identical_in_footer_and_watermark():
    from services.pdf.components import footer, watermark

    assert footer.VORVERTRAG_TEXT == watermark.VORVERTRAG_TEXT == gate.KYC_DRAFT_NOTICE


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader

    return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages)


def test_client_pdf_without_any_kyc_confirmation_is_marked_as_draft(client, session_factory):
    with session_factory() as db:
        db.add(ContractDocument(
            id="vt-1", mandate_id="m-1", document_type="Beratungsvertrag", title="Beratungsvertrag",
            status="Entwurf", signed_by_advisor=0, signed_by_client=0, version=1, created_by="adv-1",
            created_at=NOW, updated_at=NOW))
        db.commit()
        assert gate.kyc_release_is_draft(db, db.get(Mandate, "m-1"))
    adv = _auth(client, "adv-1")
    r = client.get("/mandates/m-1/reports/vertrag.pdf?document_id=vt-1", headers=adv)
    assert r.status_code == 200, r.text[:300]
    assert "vor Vertragsabschluss" in _pdf_text(r.content)
    with session_factory() as db:
        satisfy_client_onboarding(db, db.get(Mandate, "m-1"), actor_id="adv-1")
        db.commit()
        assert not gate.kyc_release_is_draft(db, db.get(Mandate, "m-1"))
    r = client.get("/mandates/m-1/reports/vertrag.pdf?document_id=vt-1", headers=adv)
    assert r.status_code == 200, r.text[:300]
    assert "vor Vertragsabschluss" not in _pdf_text(r.content)


def test_kundeninformation_context_is_never_marked_as_draft(session_factory):
    from routers.pdf_reports import _build_pdf_context

    with session_factory() as db:
        mandate = db.get(Mandate, "m-1")
        adv = db.get(User, "adv-1")
        assert _build_pdf_context(mandate, adv, db).watermark_mode == "vorvertrag"
        assert _build_pdf_context(mandate, adv, db, draft_check=False).watermark_mode == "none"


@pytest.mark.parametrize("mode", ["vorvertrag"])
def test_advisory_watermark_mode_vorvertrag_is_supported(mode):
    from services.pdf.components.watermark import WATERMARK_MODES

    assert mode in WATERMARK_MODES
