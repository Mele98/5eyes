"""H10 C-DSG-02: Betroffenenanfrage als Fall (Auskunft/Herausgabe,
Berichtigung, Loeschung).

Belegt: Eingang mit 30-Tage-Faelligkeit, Identitaets-Gate, begruendeter
Einschraenkungsentscheid, Export nur ueber den Fall (Legacy-Route
stillgelegt), Sperre bei offenen Owner-Angaben, Zustellnachweis, Fristen-
verlaengerung, RBAC, Mandantentrennung und Audit. Owner-Werte sind
Testwerte.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text

from services import privacy_subject_requests as sr
from tests.h10_support import (
    ADMIN_ID,
    CLIENT_ID,
    OTHER_CLIENT_ID,
    OTHER_TENANT,
    api,
    confirm_all_owner_fields,
    make_customer_output_ready,
    reason,
    user,
)


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _policy(client, days="30"):
    # Fristen-Policy der Firma (Owner-Feld, Testwert; Vertrag C-DSG-02: nie hardcodiert).
    client.put("/privacy/owner-fields/subject_request.deadline_days", json={"value": days})


def _open(client, *, request_type="ACCESS", received=None, client_id=CLIENT_ID, policy=True):
    if policy:
        _policy(client)
    received = received or _today().isoformat()
    return client.post("/privacy/subject-requests", json={
        "client_id": client_id, "request_type": request_type, "received_at": received,
        "received_channel": "LETTER", "request_summary": "Auskunft ueber alle Daten",
    })


def _verify(client, case_id, outcome="VERIFIED", **extra):
    return client.post(f"/privacy/subject-requests/{case_id}/identity", json={
        "outcome": outcome, "method": "ID_DOCUMENT_IN_PERSON", "evidence_reference": "Ausweis vor Ort geprueft",
        **extra,
    })


def test_legacy_direct_export_is_disabled_and_returns_no_data(tmp_path):
    with api(tmp_path) as (client, current, _factory):
        response = client.get(f"/clients/{CLIENT_ID}/data-export")
        assert response.status_code == 409
        assert reason(response) == "SUBJECT_REQUEST_REQUIRED"
        assert response.json()["detail"]["workflow"] == "/privacy/subject-requests"
        assert "Erika" not in response.text
        assert client.get(f"/clients/{OTHER_CLIENT_ID}/data-export").status_code == 404


def test_access_request_full_lifecycle_with_restriction_and_delivery(tmp_path):
    with api(tmp_path) as (client, _current, factory):
        received = (_today() - timedelta(days=3)).isoformat()
        opened = _open(client, received=received)
        assert opened.status_code == 201, opened.text
        case = opened.json()
        assert case["status"] == "RECEIVED"
        assert case["due_at"] == (date.fromisoformat(received) + timedelta(days=30)).isoformat()
        assert case["days_remaining"] == 27 and case["overdue"] is False
        case_id = case["id"]

        early = client.post(f"/privacy/subject-requests/{case_id}/export")
        assert early.status_code == 409 and reason(early) == "DSAR_IDENTITY_REQUIRED"
        undecided = client.post(f"/privacy/subject-requests/{case_id}/decision", json={"decision": "FULFILL"})
        assert reason(undecided) == "DSAR_IDENTITY_REQUIRED"

        no_evidence = _verify(client, case_id, evidence_reference="  ")
        assert no_evidence.status_code == 422 and reason(no_evidence) == "SUBJECT_REQUEST_INPUT_INVALID"
        verified = _verify(client, case_id)
        assert verified.status_code == 200 and verified.json()["status"] == "IDENTITY_VERIFIED"

        no_export_yet = client.post(f"/privacy/subject-requests/{case_id}/export")
        assert reason(no_export_yet) == "DSAR_DECISION_MISSING"
        no_reason = client.post(f"/privacy/subject-requests/{case_id}/decision",
                                json={"decision": "RESTRICT", "scope": ["mandate_report_notes"]})
        assert no_reason.status_code == 422
        unknown_scope = client.post(f"/privacy/subject-requests/{case_id}/decision",
                                    json={"decision": "RESTRICT", "reason": "x", "scope": ["erfunden"]})
        assert unknown_scope.status_code == 422
        decided = client.post(f"/privacy/subject-requests/{case_id}/decision", json={
            "decision": "RESTRICT", "reason": "Interessen Dritter (Testbegruendung)", "scope": ["risk_assessments"],
        })
        assert decided.status_code == 200 and decided.json()["decision_scope"] == ["risk_assessments"]

        blocked = client.post(f"/privacy/subject-requests/{case_id}/export")
        assert blocked.status_code == 409 and reason(blocked) == "PRIVACY_OWNER_VALUES_OPEN"
        assert any(f["key"] == "controller.name" for f in blocked.json()["detail"]["open_fields"])

        make_customer_output_ready(client)
        export = client.post(f"/privacy/subject-requests/{case_id}/export")
        assert export.status_code == 200, export.text
        document = export.json()
        assert document["export_kind"] == "PrivacySubjectRequestExportV1"
        assert document["export"]["sections"]["client"]["first_name"] == "Erika"
        assert document["export"]["sections"]["risk_assessments"] == []
        assert document["export"]["section_status"]["risk_assessments"] == "withheld_by_decision"
        assert document["withheld_by_decision"] == {"risk_assessments": "Interessen Dritter (Testbegruendung)"}
        info = document["privacy_information"]
        assert info["controller"]["name"]["value"] == "TESTWERT controller.name"
        assert {a["id"] for a in info["activities"]} >= {"PA-01", "PA-04"}
        assert "PA-07" not in {a["id"] for a in info["activities"]}

        refixed = client.post(f"/privacy/subject-requests/{case_id}/decision", json={"decision": "FULFILL"})
        assert refixed.status_code == 409 and reason(refixed) == "SUBJECT_REQUEST_STATE_INVALID"

        no_reference = client.post(f"/privacy/subject-requests/{case_id}/delivery", json={
            "delivered_at": _today().isoformat(), "delivery_channel": "LETTER"})
        assert no_reference.status_code == 422
        future = client.post(f"/privacy/subject-requests/{case_id}/delivery", json={
            "delivered_at": (_today() + timedelta(days=2)).isoformat(), "delivery_channel": "LETTER",
            "delivery_reference": "Einschreiben 98.00"})
        assert future.status_code == 422
        delivered = client.post(f"/privacy/subject-requests/{case_id}/delivery", json={
            "delivered_at": _today().isoformat(), "delivery_channel": "LETTER",
            "delivery_reference": "Einschreiben 98.00 (Testwert)"})
        assert delivered.status_code == 200, delivered.text
        final = delivered.json()
        assert final["status"] == "COMPLETED" and final["delivered_on_time"] is True
        assert final["export_sha256"] == document["export_sha256"] and final["overdue"] is False
        again = client.post(f"/privacy/subject-requests/{case_id}/export")
        assert again.status_code == 409 and reason(again) == "SUBJECT_REQUEST_STATE_INVALID"

        with factory() as s:
            steps = s.execute(text(
                "SELECT action, new_value FROM audit_log WHERE table_name = 'privacy_subject_requests' "
                "AND record_id = :id ORDER BY sequence"), {"id": case_id}).all()
            client_ids = set(s.execute(text(
                "SELECT client_id FROM audit_log WHERE table_name = 'privacy_subject_requests'")).scalars())
        actions = [row[0] for row in steps]
        assert actions == ["CREATE", "UPDATE", "UPDATE", "EXPORT", "UPDATE"]
        assert document["export_sha256"] in steps[3][1]
        assert client_ids == {CLIENT_ID}


def test_deadline_overdue_and_extension_rules(tmp_path):
    with api(tmp_path) as (client, _current, _factory):
        old = (_today() - timedelta(days=40)).isoformat()
        case = _open(client, received=old).json()
        assert case["overdue"] is True and case["days_remaining"] == -10
        status = client.get("/privacy/status").json()
        assert status["subject_requests_open"] == 1 and status["subject_requests_overdue"] == 1
        late = client.post(f"/privacy/subject-requests/{case['id']}/extension", json={
            "extended_due_at": (_today() + timedelta(days=20)).isoformat(), "reason": "Umfang (Testwert)",
            "notified_at": _today().isoformat()})
        assert late.status_code == 409 and reason(late) == "SUBJECT_REQUEST_EXTENSION_TOO_LATE"

        fresh = _open(client, received=(_today() - timedelta(days=5)).isoformat()).json()
        no_reason = client.post(f"/privacy/subject-requests/{fresh['id']}/extension", json={
            "extended_due_at": (_today() + timedelta(days=50)).isoformat(), "notified_at": _today().isoformat()})
        assert no_reason.status_code == 422
        earlier = client.post(f"/privacy/subject-requests/{fresh['id']}/extension", json={
            "extended_due_at": (_today() + timedelta(days=1)).isoformat(), "reason": "x",
            "notified_at": _today().isoformat()})
        assert earlier.status_code == 422
        extended = client.post(f"/privacy/subject-requests/{fresh['id']}/extension", json={
            "extended_due_at": (_today() + timedelta(days=50)).isoformat(), "reason": "Umfang (Testwert)",
            "notified_at": _today().isoformat()})
        assert extended.status_code == 200
        assert extended.json()["effective_due_at"] == (_today() + timedelta(days=50)).isoformat()

        future = _open(client, received=(_today() + timedelta(days=3)).isoformat())
        assert future.status_code == 422 and reason(future) == "SUBJECT_REQUEST_INPUT_INVALID"
        bad_type = client.post("/privacy/subject-requests", json={
            "client_id": CLIENT_ID, "request_type": "ALLES", "received_at": _today().isoformat(),
            "received_channel": "LETTER"})
        assert bad_type.status_code == 422


def test_failed_identity_only_allows_reasoned_refusal(tmp_path):
    with api(tmp_path) as (client, _current, _factory):
        case_id = _open(client).json()["id"]
        no_reason = _verify(client, case_id, outcome="FAILED")
        assert no_reason.status_code == 422
        failed = _verify(client, case_id, outcome="FAILED", failure_reason="Unterschrift weicht ab (Testwert)")
        assert failed.json()["status"] == "IDENTITY_FAILED"
        fulfil = client.post(f"/privacy/subject-requests/{case_id}/decision", json={"decision": "FULFILL"})
        assert fulfil.status_code == 409 and reason(fulfil) == "DSAR_IDENTITY_REQUIRED"
        refuse = client.post(f"/privacy/subject-requests/{case_id}/decision",
                             json={"decision": "REFUSE", "reason": "Identitaet nicht nachgewiesen (Testwert)"})
        assert refuse.status_code == 200
        export = client.post(f"/privacy/subject-requests/{case_id}/export")
        assert export.status_code == 409
        delivered = client.post(f"/privacy/subject-requests/{case_id}/delivery", json={
            "delivered_at": _today().isoformat(), "delivery_channel": "EMAIL",
            "delivery_reference": "Ablehnung per E-Mail (Testwert)"})
        assert delivered.status_code == 200 and delivered.json()["export_sha256"] is None


def test_rectification_and_erasure_need_proof_of_action(tmp_path):
    with api(tmp_path) as (client, _current, _factory):
        rect = _open(client, request_type="RECTIFICATION").json()["id"]
        _verify(client, rect)
        restrict = client.post(f"/privacy/subject-requests/{rect}/decision",
                               json={"decision": "RESTRICT", "reason": "x", "scope": ["client"]})
        assert restrict.status_code == 422
        client.post(f"/privacy/subject-requests/{rect}/decision", json={"decision": "FULFILL"})
        early = client.post(f"/privacy/subject-requests/{rect}/delivery", json={
            "delivered_at": _today().isoformat(), "delivery_channel": "LETTER", "delivery_reference": "Brief"})
        assert early.status_code == 409 and reason(early) == "SUBJECT_REQUEST_ACTION_MISSING"
        assert client.post(f"/privacy/subject-requests/{rect}/action", json={}).status_code == 422
        done = client.post(f"/privacy/subject-requests/{rect}/action",
                           json={"completion_note": "Adresse berichtigt (Testwert)"})
        assert done.status_code == 200 and done.json()["action_completed_at"]

        erase = _open(client, request_type="ERASURE").json()["id"]
        _verify(client, erase)
        client.post(f"/privacy/subject-requests/{erase}/decision", json={"decision": "FULFILL"})
        pending_case = client.post("/privacy/erasure-cases", json={"client_id": CLIENT_ID}).json()
        assert pending_case["status"] == "DECISION_PENDING"
        for erasure_case_id in (None, "unbekannt", pending_case["id"]):
            refused = client.post(f"/privacy/subject-requests/{erase}/action",
                                  json={"erasure_case_id": erasure_case_id})
            assert refused.status_code == 409 and reason(refused) == "SUBJECT_REQUEST_ERASURE_CASE_INVALID"


def test_rbac_and_tenant_isolation(tmp_path):
    with api(tmp_path) as (client, current, _factory):
        case_id = _open(client).json()["id"]
        current["user"] = user("advisor-1", role="advisor")
        assert client.get("/privacy/subject-requests").status_code == 403
        assert client.get(f"/privacy/subject-requests/{case_id}").status_code == 403
        assert _open(client).status_code == 403

        current["user"] = user(ADMIN_ID)
        granted = client.post("/privacy/roles", json={"user_id": "advisor-1", "privacy_role": "PRIVACY"})
        assert granted.status_code == 201
        current["user"] = user("advisor-1", role="advisor")
        assert client.get(f"/privacy/subject-requests/{case_id}").status_code == 200

        current["user"] = user("admin-b", tenant=OTHER_TENANT)
        assert client.get("/privacy/subject-requests").json() == []
        assert client.get(f"/privacy/subject-requests/{case_id}").status_code == 404
        assert _verify(client, case_id).status_code == 404
        assert _open(client, client_id=CLIENT_ID).status_code == 404
        own = _open(client, client_id=OTHER_CLIENT_ID)
        assert own.status_code == 201
        current["user"] = user(ADMIN_ID)
        assert client.get(f"/privacy/subject-requests/{own.json()['id']}").status_code == 404


def test_withdrawal_closes_the_case(tmp_path):
    with api(tmp_path) as (client, _current, _factory):
        case_id = _open(client).json()["id"]
        assert client.post(f"/privacy/subject-requests/{case_id}/withdraw", json={}).status_code == 422
        closed = client.post(f"/privacy/subject-requests/{case_id}/withdraw",
                             json={"reason": "Anfrage zurueckgezogen (Testwert)"})
        assert closed.json()["status"] == "WITHDRAWN" and closed.json()["overdue"] is False
        assert _verify(client, case_id).status_code == 409


def test_export_sections_match_the_real_export(tmp_path):
    from services.data_export import export_client_data

    with api(tmp_path) as (_client, _current, factory):
        with factory() as s:
            payload = export_client_data(s, CLIENT_ID)
    assert tuple(payload["sections"]) == sr.EXPORT_SECTIONS


def test_alembic_revision_single_head_and_sqlite_roundtrip(tmp_path):
    from models.privacy import PrivacySubjectRequest
    from tests.h10_support import assert_single_head_contains, assert_sqlite_upgrade_downgrade_upgrade

    assert_single_head_contains("f4b8d2e6a3c7", "e2f7c4a9d1b3")
    assert_sqlite_upgrade_downgrade_upgrade(
        tmp_path, "f4b8d2e6a3c7", {"privacy_subject_requests": PrivacySubjectRequest},
        later_columns=frozenset({"row_version"}),  # Nachtrag 1, Revision c4e8a2f6d0b7
    )


def test_alembic_postgres_ddl_creates_subject_requests():
    from tests.h10_support import postgres_offline_ddl

    ddl = postgres_offline_ddl("e2f7c4a9d1b3", "f4b8d2e6a3c7")
    assert "CREATE TABLE privacy_subject_requests" in ddl
    for name in ("ck_privacy_subject_request_type", "ck_privacy_subject_request_status",
                 "ix_privacy_subject_requests_status"):
        assert name in ddl


def test_tier1_client_without_tenant_counts_as_main(tmp_path):
    """Verhaltensprobe 9051: Bootstrap-Admin und Kunde ohne tenant_id (Tier 1)."""
    with api(tmp_path) as (client, current, factory):
        with factory() as s:
            s.execute(text("UPDATE clients SET tenant_id = NULL WHERE id = :id"), {"id": CLIENT_ID})
            s.commit()
        current["user"] = user(ADMIN_ID, tenant=None)
        opened = _open(client)
        assert opened.status_code == 201, opened.text
        assert client.get(f"/privacy/subject-requests/{opened.json()['id']}").status_code == 200
        current["user"] = user("admin-b", tenant=OTHER_TENANT)
        assert _open(client).status_code == 404


def test_swiss_calendar_date_after_midnight_is_not_future(tmp_path):
    """Verhaltensprobe 9051: um 00:30 Ortszeit ist das Schweizer Datum in UTC
    noch gestern; ein reines Datum gilt mit einem Tag Toleranz."""
    with api(tmp_path) as (client, _current, _factory):
        tomorrow_utc = (_today() + timedelta(days=1)).isoformat()
        assert _open(client, received=tomorrow_utc).status_code == 201
        assert _open(client, received=(_today() + timedelta(days=2)).isoformat()).status_code == 422


def test_deadline_comes_from_owner_policy_not_code(tmp_path):
    """Vertrag C-DSG-02: Frist aus freigegebener Policy, nicht hardcodiert."""
    with api(tmp_path) as (client, _current, _factory):
        case = _open(client, policy=False).json()
        assert case["due_at"] is None and case["deadline_policy_missing"] is True and case["overdue"] is False
        assert "DSAR_IDENTITY_REQUIRED" in [f["reason_code"] for f in case["findings"]]
        assert client.put("/privacy/owner-fields/subject_request.deadline_days",
                          json={"value": "abc"}).status_code == 422
        received = (_today() - timedelta(days=12)).isoformat()
        _policy(client, "10")
        later = _open(client, received=received, policy=False).json()
        assert later["due_at"] == (date.fromisoformat(received) + timedelta(days=10)).isoformat()
        assert later["overdue"] is True and "DSAR_OVERDUE" in [f["reason_code"] for f in later["findings"]]


def test_erasure_request_is_blocked_by_active_legal_hold(tmp_path):
    from models.privacy import PrivacyLegalHold

    with api(tmp_path) as (client, _current, factory):
        with factory() as s:
            s.add(PrivacyLegalHold(id="hold-1", tenant_id="main", client_id=CLIENT_ID, case_reference="TEST",
                                   legal_reason="Testwert", scope_json="[]", set_by="x", review_date="2027-01-01",
                                   status="ACTIVE", created_at="2026-11-01", updated_at="2026-11-01"))
            s.commit()
        case_id = _open(client, request_type="ERASURE").json()["id"]
        _verify(client, case_id)
        refused = client.post(f"/privacy/subject-requests/{case_id}/decision", json={"decision": "FULFILL"})
        assert refused.status_code == 409 and reason(refused) == "DSAR_LEGAL_HOLD"
        decided = client.post(f"/privacy/subject-requests/{case_id}/decision",
                              json={"decision": "REFUSE", "reason": "Legal Hold (Testwert)"})
        assert decided.status_code == 200
        assert "DSAR_DELIVERY_MISSING" in [f["reason_code"] for f in decided.json()["findings"]]
