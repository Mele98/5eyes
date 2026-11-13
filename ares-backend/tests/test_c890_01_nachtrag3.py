"""C-890-01 Nachtrag 3 (Pruefrunde ce523da9, N-897-01..09).

- N-897-01: alle PDF-/Berichtsrouten aus der echten App-Routentabelle sind
  klassifiziert; jede kundenwirksame sperrt bei ungebundener KYC-Bestaetigung.
- N-897-02: Freigeberkonten nur per Einladung, Passwort/2FA selbst gesetzt,
  keine Admin-Aenderung, Herkunft im Nachweis, E-Mail-Normalisierung.
- N-897-03..09: Kalender-Feed, Policy-Vier-Augen per Person, dauerhafte
  Verkuerzung, veraltete Freigabe, Freitext-Hinweise, genau ein Entscheid,
  Policy-Liste nur fuer Personal.
Alle Fristen sind TESTWERTE (TEST-C890).
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

TESTS_ROOT = Path(__file__).resolve().parent
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from test_c890_01_compliance_reviewer_role import (  # noqa: E402,F401
    NOW, PW, TENANT, _auth, client, session_factory,
)

from main import app  # noqa: E402
from models.clients import KycConfirmation, KycConfirmationDecision  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from models.review import AuditLog  # noqa: E402
from models.users import User  # noqa: E402
from services import recommendation_release_gate as gate  # noqa: E402
from services.auth import create_access_token, normalize_email_identity  # noqa: E402

from client_onboarding_fixture import ensure_test_kyc_review_policy, satisfy_client_onboarding  # noqa: E402

TODAY = datetime.now(timezone.utc).date()


def _iso(days: int) -> str:
    return (TODAY + timedelta(days=days)).isoformat()


def _codes(sf, today=None):
    with sf() as db:
        return [f["reason_code"] for f in gate._kyc_findings(db, db.get(Mandate, "m-1"),
                                                               today or gate._utc_now_iso()[:10])]


def _legacy(db):
    record = KycConfirmation(
        id="k-legacy", tenant_id=TENANT, client_id="c-1", process_scope="sro_oder_fremdprozess", form_type="A",
        form_completed_on=_iso(-2), external_reference="Bestand", risk_category="normal", is_pep=0,
        identification_confirmed=1, identification_date=_iso(-2), next_review_due=_iso(30),
        requires_second_approval=0, recorded_by="adv-1", recorded_at="2999-01-01T00:00:00.000Z")
    legacy = {c.name: getattr(record, c.name) for c in record.__table__.columns
              if c.name not in gate.KYC_REVIEW_BINDING_COLUMNS}
    record.confirmation_hash = gate.row_seal(legacy, "confirmation_hash")
    db.add(record)
    db.commit()


# ---------------------------------------------------------------------------
# N-897-01: Klassifikation aller PDF-/Berichtsrouten (App-Routentabelle)
# ---------------------------------------------------------------------------


def _report_routes() -> set[str]:
    found = set()
    for route in app.routes:
        path = getattr(route, "path", "")
        for method in sorted(getattr(route, "methods", None) or ()):
            if method in ("HEAD", "OPTIONS"):
                continue
            if gate.is_report_route(path):
                found.add(f"{method} {path}")
    return found


def test_every_report_route_is_classified_and_nothing_stale():
    routes = _report_routes()
    assert routes, "keine Berichtsrouten erkannt"
    assert routes - set(gate.REPORT_ROUTE_CLASSIFICATION) == set()
    assert set(gate.REPORT_ROUTE_CLASSIFICATION) - routes == set()
    for key, (kind, reason) in gate.REPORT_ROUTE_CLASSIFICATION.items():
        assert kind in (gate.REPORT_CLIENT_FACING, gate.REPORT_INTERNAL) and len(reason) > 10, key


def test_every_client_facing_report_route_blocks_without_policy_binding(client, session_factory):
    with session_factory() as db:
        satisfy_client_onboarding(db, db.get(Mandate, "m-1"), actor_id="adv-1")
        db.commit()
        _legacy(db)
        from models.client_login import ClientLogin

        db.add(User(id="cl-1", username="cl-1", password_hash="x", full_name="Kunde", role="client",
                    is_active=1, tenant_id=TENANT, created_at=NOW, updated_at=NOW))
        db.add(ClientLogin(id="cll-1", user_id="cl-1", client_id="c-1", created_by="adm-1", created_at=NOW,
                           is_active=1))
        db.commit()
    advisor = _auth(client, "adv-1")
    portal = {"Authorization": "Bearer " + create_access_token({"sub": "cl-1", "tid": TENANT})}
    client_facing = [k for k, (kind, _r) in gate.REPORT_ROUTE_CLASSIFICATION.items()
                     if kind == gate.REPORT_CLIENT_FACING]
    assert len(client_facing) == 13
    for key in client_facing:
        method, path = key.split(" ", 1)
        url = path.replace("{mandate_id}", "m-1")
        headers = portal if path.startswith("/client-portal/") else advisor
        r = client.request(method, url, headers=headers)
        assert r.status_code == 409, (key, r.status_code, r.text[:300])
        if path.startswith("/client-portal/"):
            with session_factory() as db:
                audit = db.query(AuditLog).filter(AuditLog.field_name == "client_portal_report_blocked").all()
                assert [a.new_value for a in audit] == ["KYC_REVIEW_POLICY_BINDING_MISSING"], key
            continue
        detail = r.json()["detail"]
        assert detail["reason_code"] == "CLIENT_ONBOARDING_INCOMPLETE", key
        assert "KYC_REVIEW_POLICY_BINDING_MISSING" in detail["finding_codes"], key


# ---------------------------------------------------------------------------
# N-897-02: Einladung, Selbst-Zugangsdaten, 2FA, keine Admin-Aenderung
# ---------------------------------------------------------------------------


def _invite(client, admin, **overrides):
    body = {"username": "ext-1", "full_name": "Externe Pruefperson", "email": "pruef@testfirma.ch",
            "role": "compliance_reviewer", "reviewer_organisation": "TEST-C890 Revision AG",
            "reviewer_reference": "TEST-C890 Mandat 1"}
    body.update(overrides)
    return client.post("/users/invite", headers=admin, json=body)


def _enable_2fa(client, headers):
    from services import totp

    secret = client.post("/auth/2fa/setup", headers=headers).json()["secret"]
    r = client.post("/auth/2fa/enable", headers=headers, json={"code": totp.totp_at(secret, time.time())})
    assert r.status_code == 200, r.text
    return secret


def test_reviewer_only_by_invitation_with_identity(client, session_factory):
    admin = _auth(client, "adm-1")
    r = client.post("/users", headers=admin, json={"username": "x", "password": "Testpasswort-1", "full_name": "X",
                                                   "role": "compliance_reviewer"})
    assert r.status_code == 403 and r.json()["detail"]["reason_code"] == "COMPLIANCE_REVIEWER_INVITE_REQUIRED"
    assert _invite(client, admin, reviewer_organisation="").status_code == 422
    assert _invite(client, admin, email=None).status_code == 422
    r = _invite(client, admin)
    assert r.status_code == 201, r.text
    with session_factory() as db:
        user = db.query(User).filter(User.username == "ext-1").one()
        assert (user.invited_by, user.activated_at, user.credentials_set_by) == ("adm-1", None, None)
        assert (user.reviewer_organisation, user.reviewer_reference) == ("TEST-C890 Revision AG", "TEST-C890 Mandat 1")
        audit = db.query(AuditLog).filter(AuditLog.action == "INVITE").one()
        assert (audit.field_name, audit.new_value) == ("role", "compliance_reviewer")


def test_invited_reviewer_needs_own_password_and_2fa_before_approving(client, session_factory):
    admin = _auth(client, "adm-1")
    with session_factory() as db:
        ensure_test_kyc_review_policy(db, TENANT, actor_id="adm-1")
        db.commit()
    token = _invite(client, admin).json()["invite_token"]
    r = client.post("/auth/invite/accept", json={"token": token, "password": "Selbstgesetzt-C890"})
    assert r.status_code == 200, r.text
    ext = {"Authorization": "Bearer " + r.json()["access_token"]}
    row = client.post("/compliance/kyc-review-policies", headers=admin, json={
        "jurisdiction": "CH", "policy_id": "TEST-C890-N3", "normal_max_months": 12,
        "valid_from": _iso(0), "source_reference": "TEST-C890 Testwert"}).json()
    body = {"policy_hash": row["policy_hash"], "approval_reference": "TEST-C890"}
    r = client.post(f"/compliance/kyc-review-policies/{row['id']}/activate", headers=ext, json=body)
    assert r.status_code == 403 and r.json()["detail"]["reason_code"] == "COMPLIANCE_REVIEWER_2FA_REQUIRED"
    _enable_2fa(client, ext)
    r = client.post(f"/compliance/kyc-review-policies/{row['id']}/activate", headers=ext, json=body)
    assert r.status_code == 200, r.text
    account = r.json()["approver_account"]
    assert account["invited_by"] == "adm-1" and account["activated_at"] and account["credentials_set_by"] == "selbst"
    assert account["totp_set_by"] == "selbst" and account["organisation"] == "TEST-C890 Revision AG"


def test_admin_cannot_change_reviewer_credentials_identity_or_role_but_can_deactivate(client, session_factory):
    admin = _auth(client, "adm-1")
    for body in ({"email": "anders@testfirma.ch"}, {"role": "admin"}, {"full_name": "Anders"}):
        r = client.put("/users/rev-1", headers=admin, json=body)
        assert r.status_code == 403 and r.json()["detail"]["reason_code"] == "COMPLIANCE_REVIEWER_ADMIN_CHANGE_FORBIDDEN"
    r = client.put("/users/rev-1/password", headers=admin, json={"new_password": "Adminpasswort-C890"})
    assert r.status_code == 403
    r = client.put("/users/adv-1", headers=admin, json={"role": "compliance_reviewer"})
    assert r.status_code == 403
    assert client.put("/users/rev-1", headers=admin, json={"is_active": False}).status_code == 200
    with session_factory() as db:
        assert db.get(User, "rev-1").is_active == 0


def test_gate_and_policy_chain_reject_approver_with_admin_set_credentials_or_without_2fa(client, session_factory):
    adv, rev = _auth(client, "adv-1"), _auth(client, "rev-1")
    with session_factory() as db:
        ensure_test_kyc_review_policy(db, TENANT, actor_id="adm-1")
        db.commit()
    client.put("/clients/c-1/due-diligence", headers=adv, json={"acting_for_own_account": True, "pep_status": True})
    r = client.post("/clients/c-1/kyc-confirmations", headers=adv, json={
        "form_type": "A", "form_completed_on": _iso(-2), "external_reference": "SRO-N3", "risk_category": "normal",
        "is_pep": True, "identification_confirmed": True, "identification_date": _iso(-2),
        "next_review_due": _iso(30)})
    assert r.status_code == 201, r.text
    item = client.get("/compliance/kyc-approvals", headers=rev).json()["items"][0]
    assert client.post(f"/compliance/kyc-approvals/{item['confirmation_id']}/decision", headers=rev, json={
        "decision": "approve", "reason": "geprueft (Test)", "confirmation_hash": item["confirmation_hash"]}
    ).status_code == 200
    assert "KYC_SECOND_APPROVAL_MISSING" not in _codes(session_factory)
    for column, value in (("credentials_set_by", "adm-1"), ("totp_enabled", 0), ("totp_set_by", None)):
        with session_factory() as db:
            db.execute(text(f"UPDATE users SET {column} = :v WHERE id = 'rev-1'"), {"v": value})
            db.commit()
        assert "KYC_SECOND_APPROVAL_MISSING" in _codes(session_factory), column
        with session_factory() as db:
            db.execute(text("UPDATE users SET credentials_set_by='self', totp_enabled=1, totp_set_by='self' "
                            "WHERE id = 'rev-1'"))
            db.commit()


def test_policy_four_eyes_in_gate_uses_person_rule(session_factory):
    with session_factory() as db:
        db.query(User).filter(User.id == "adm-1").update({"email": "chef@example.invalid"})
        db.add(User(id="adm-alias", username="adm-alias", password_hash="x", full_name="Alias", role="admin",
                    is_active=1, tenant_id=TENANT, email="Chef+kyc@Example.invalid", created_at=NOW, updated_at=NOW))
        db.commit()
        policy, activation = ensure_test_kyc_review_policy(db, TENANT, actor_id="adm-1")
        db.execute(text("DROP TRIGGER trg_kyc_review_policy_activations_no_update"))
        db.execute(text("UPDATE kyc_review_policy_activations SET approved_by='adm-alias'"))
        row = db.execute(text("SELECT * FROM kyc_review_policy_activations")).mappings().first()
        seal = gate.row_seal(dict(row), "activation_hash")
        db.execute(text("UPDATE kyc_review_policy_activations SET activation_hash=:h"), {"h": seal})
        db.commit()
        result = gate.resolve_kyc_review_policy(db, TENANT, "CH", gate._utc_now_iso()[:10])
        assert result["reason_code"] == "KYC_REVIEW_POLICY_UNAPPROVED"
        db.execute(text("UPDATE kyc_review_policy_activations SET approved_by='adv-1'"))
        row = db.execute(text("SELECT * FROM kyc_review_policy_activations")).mappings().first()
        db.execute(text("UPDATE kyc_review_policy_activations SET activation_hash=:h"),
                   {"h": gate.row_seal(dict(row), "activation_hash")})
        db.commit()
        assert gate.resolve_kyc_review_policy(db, TENANT, "CH", gate._utc_now_iso()[:10])["reason_code"] == (
            "KYC_REVIEW_POLICY_UNAPPROVED")


@pytest.mark.parametrize("a, b, same", [
    ("Max@Firma.ch", "max@firma.ch", True),
    (" max@firma.ch ", "MAX@FIRMA.CH", True),
    ("max+kyc@firma.ch", "max@firma.ch", True),
    ("max+a@firma.ch", "MAX+b@Firma.ch", True),
    ("max@firma.ch", "max@andere.ch", False),
    ("max.muster@firma.ch", "maxmuster@firma.ch", False),
])
def test_email_identity_normalization_is_identical_in_auth_and_gate(a, b, same):
    assert (normalize_email_identity(a) == normalize_email_identity(b)) is same
    assert (gate._email_identity(a) == gate._email_identity(b)) is same
    assert normalize_email_identity(a) == gate._email_identity(a)


def test_same_person_via_plus_alias_is_blocked(client, session_factory):
    with session_factory() as db:
        ensure_test_kyc_review_policy(db, TENANT, actor_id="adm-1")
        db.query(User).filter(User.id == "adv-1").update({"email": "berater@example.invalid"})
        db.add(User(id="adm-plus", username="adm-plus", password_hash="x", full_name="Plus", role="admin",
                    is_active=1, tenant_id=TENANT, email="Berater+freigabe@Example.invalid",
                    created_at=NOW, updated_at=NOW))
        db.commit()
    adv, plus = _auth(client, "adv-1"), {"Authorization": "Bearer " + create_access_token({"sub": "adm-plus", "tid": TENANT})}
    client.put("/clients/c-1/due-diligence", headers=adv, json={"acting_for_own_account": True, "pep_status": True})
    conf = client.post("/clients/c-1/kyc-confirmations", headers=adv, json={
        "form_type": "A", "form_completed_on": _iso(-2), "external_reference": "SRO-N3", "risk_category": "normal",
        "is_pep": True, "identification_confirmed": True, "identification_date": _iso(-2),
        "next_review_due": _iso(30)}).json()
    r = client.post(f"/compliance/kyc-approvals/{conf['id']}/decision", headers=plus, json={
        "decision": "approve", "reason": "Zweitkonto (Test)", "confirmation_hash": conf["confirmation_hash"]})
    assert r.status_code == 403 and r.json()["detail"]["reason_code"] == "KYC_SECOND_APPROVAL_SAME_PERSON"


# ---------------------------------------------------------------------------
# N-897-03: Kalender-Feed respektiert Rollen, Rollenwechsel widerruft
# ---------------------------------------------------------------------------


def test_calendar_feed_respects_roles_and_role_change_revokes(client, session_factory):
    from services.review_calendar_feed import _sha256

    with session_factory() as db:
        db.query(User).filter(User.id.in_(("adv-1", "rev-1"))).update(
            {"calendar_feed_token_hash": None}, synchronize_session=False)
        db.query(User).filter(User.id == "rev-1").update({"calendar_feed_token_hash": _sha256("tok-rev")})
        db.commit()
    adv = _auth(client, "adv-1")
    token = client.post("/me/calendar-feed-token", headers=adv).json()["token"]
    assert client.get(f"/calendar/reviews.ics?token={token}").status_code == 200
    assert client.get("/calendar/reviews.ics?token=tok-rev").status_code in (401, 403, 404)
    admin = _auth(client, "adm-1")
    assert client.put("/users/adv-1", headers=admin, json={"role": "readonly"}).status_code == 200
    with session_factory() as db:
        assert db.get(User, "adv-1").calendar_feed_token_hash is None
    assert client.get(f"/calendar/reviews.ics?token={token}").status_code in (401, 403, 404)


# ---------------------------------------------------------------------------
# N-897-05: Verkuerzung bleibt faellig bis zur neuen KYC (24 -> 12 -> 36)
# ---------------------------------------------------------------------------


def test_shortening_stays_due_after_later_extension(client, session_factory):
    adv, adm2 = _auth(client, "adv-1"), _auth(client, "adm-2")
    admin = _auth(client, "adm-1")

    def policy(months, pid):
        row = client.post("/compliance/kyc-review-policies", headers=admin, json={
            "jurisdiction": "CH", "policy_id": pid, "normal_max_months": months, "valid_from": _iso(0),
            "source_reference": "TEST-C890 Testwert"}).json()
        r = client.post(f"/compliance/kyc-review-policies/{row['id']}/activate", headers=adm2,
                        json={"policy_hash": row["policy_hash"], "approval_reference": "TEST-C890"})
        assert r.status_code == 200, r.text

    from client_onboarding_fixture import ensure_test_legal_profile  # noqa: F401
    policy(24, "TEST-C890-24")
    client.put("/clients/c-1/due-diligence", headers=adv, json={"acting_for_own_account": True, "pep_status": False})
    completed = _iso(-2)
    r = client.post("/clients/c-1/kyc-confirmations", headers=adv, json={
        "form_type": "A", "form_completed_on": completed, "external_reference": "SRO-24", "risk_category": "normal",
        "is_pep": False, "identification_confirmed": True, "identification_date": completed,
        "next_review_due": gate.add_months_clamped(completed, 24)})
    assert r.status_code == 201, r.text
    assert _codes(session_factory) == []
    policy(12, "TEST-C890-12")
    assert _codes(session_factory) == ["KYC_REVIEW_POLICY_SHORTENED"]
    policy(36, "TEST-C890-36")
    assert _codes(session_factory) == ["KYC_REVIEW_POLICY_SHORTENED"]
    with session_factory() as db:
        finding = gate._kyc_findings(db, db.get(Mandate, "m-1"), gate._utc_now_iso()[:10])[0]
        assert finding["shortened_by_policy_version"] == 2
        assert finding["current_max_due"] == gate.add_months_clamped(completed, 12)


# ---------------------------------------------------------------------------
# N-897-06 / -07 / -08 / -09
# ---------------------------------------------------------------------------


def _pep_confirmation(client, adv, ref="SRO-N3", note=None):
    body = {"form_type": "A", "form_completed_on": _iso(-2), "external_reference": ref, "risk_category": "normal",
            "is_pep": True, "identification_confirmed": True, "identification_date": _iso(-2),
            "next_review_due": _iso(30)}
    if note is not None:
        body["note"] = note
    return client.post("/clients/c-1/kyc-confirmations", headers=adv, json=body)


def test_mask_approval_of_superseded_confirmation_is_409(client, session_factory):
    adv, adm = _auth(client, "adv-1"), _auth(client, "adm-2")
    with session_factory() as db:
        ensure_test_kyc_review_policy(db, TENANT, actor_id="adm-1")
        db.commit()
    client.put("/clients/c-1/due-diligence", headers=adv, json={"acting_for_own_account": True, "pep_status": True})
    old = _pep_confirmation(client, adv).json()
    _pep_confirmation(client, adv, ref="SRO-N3-neu")
    r = client.post(f"/clients/c-1/kyc-confirmations/{old['id']}/approve", headers=adm, json={})
    assert r.status_code == 409 and r.json()["detail"]["reason_code"] == "KYC_APPROVAL_SUPERSEDED"


def test_free_text_limits_and_personal_data_warnings(client, session_factory):
    adv = _auth(client, "adv-1")
    with session_factory() as db:
        ensure_test_kyc_review_policy(db, TENANT, actor_id="adm-1")
        db.commit()
    client.put("/clients/c-1/due-diligence", headers=adv, json={"acting_for_own_account": True, "pep_status": True})
    assert _pep_confirmation(client, adv, ref="R" * 121).status_code == 422
    assert _pep_confirmation(client, adv, note="N" * 501).status_code == 422
    r = _pep_confirmation(client, adv, ref="SRO-77 Muster",
                          note="Kontakt eva@example.invalid, IBAN CH93 0076 2011 6238 5295 7, AHV 756.1234.5678.97")
    assert r.status_code == 201, r.text
    assert r.json()["personal_data_warnings"] == ["ahv", "email", "iban", "kundenname"]
    clean = _pep_confirmation(client, adv, ref="SRO-78", note="Unterlagen vollstaendig")
    assert clean.json()["personal_data_warnings"] == []


def test_exactly_one_decision_per_confirmation(client, session_factory):
    adv, rev, adm = _auth(client, "adv-1"), _auth(client, "rev-1"), _auth(client, "adm-2")
    with session_factory() as db:
        ensure_test_kyc_review_policy(db, TENANT, actor_id="adm-1")
        db.commit()
    client.put("/clients/c-1/due-diligence", headers=adv, json={"acting_for_own_account": True, "pep_status": True})
    conf = _pep_confirmation(client, adv).json()
    assert client.post(f"/clients/c-1/kyc-confirmations/{conf['id']}/approve", headers=adm, json={}).status_code == 200
    r = client.post(f"/compliance/kyc-approvals/{conf['id']}/decision", headers=rev, json={
        "decision": "reject", "reason": "zu spaet (Test)", "confirmation_hash": conf["confirmation_hash"]})
    assert r.status_code == 409 and r.json()["detail"]["reason_code"] == "KYC_SECOND_APPROVAL_ALREADY_DECIDED"
    with session_factory() as db:
        assert db.query(KycConfirmationDecision).count() == 1
        db.add(KycConfirmationDecision(confirmation_id=conf["id"], tenant_id=TENANT, decision="reject",
                                       decided_by="rev-1", decided_at=NOW, record_id="x"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        with pytest.raises(Exception, match="immutable"):
            db.execute(text("UPDATE kyc_confirmation_decisions SET decision = 'reject'"))
        db.rollback()


def test_racing_decisions_on_sqlite_yield_one_winner(client, session_factory, monkeypatch):
    """Zwei Entscheide, die beide noch "unentschieden" gesehen haben: der
    zweite scheitert am Primaerschluessel (409), es bleibt genau einer."""
    import routers.clients as clients_router

    adv, rev, adm = _auth(client, "adv-1"), _auth(client, "rev-1"), _auth(client, "adm-2")
    with session_factory() as db:
        ensure_test_kyc_review_policy(db, TENANT, actor_id="adm-1")
        db.commit()
    client.put("/clients/c-1/due-diligence", headers=adv, json={"acting_for_own_account": True, "pep_status": True})
    conf = _pep_confirmation(client, adv).json()
    monkeypatch.setattr(clients_router, "_decided", lambda db, cid: False)
    first = client.post(f"/compliance/kyc-approvals/{conf['id']}/decision", headers=rev, json={
        "decision": "approve", "reason": "zuerst (Test)", "confirmation_hash": conf["confirmation_hash"]})
    second = client.post(f"/compliance/kyc-approvals/{conf['id']}/decision", headers=adm, json={
        "decision": "reject", "reason": "parallel (Test)", "confirmation_hash": conf["confirmation_hash"]})
    assert first.status_code == 200 and second.status_code == 409
    with session_factory() as db:
        assert db.query(KycConfirmationDecision).count() == 1
        assert db.execute(text("SELECT COUNT(*) FROM kyc_confirmation_rejections")).scalar() == 0


def test_policy_list_is_staff_only(client, session_factory):
    with session_factory() as db:
        db.add(User(id="cl-2", username="cl-2", password_hash="x", full_name="Kunde", role="client",
                    is_active=1, tenant_id=TENANT, created_at=NOW, updated_at=NOW))
        db.commit()
    customer = {"Authorization": "Bearer " + create_access_token({"sub": "cl-2", "tid": TENANT})}
    assert client.get("/compliance/kyc-review-policies", headers=customer).status_code == 403
    assert client.get("/compliance/kyc-review-policies", headers=_auth(client, "adv-1")).status_code == 200
