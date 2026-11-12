"""H10 C-DSG-04: Register der Verletzungen der Datensicherheit.

Belegt: Erfassung durch Mitarbeitende, Risikobewertung mit Begruendung,
Meldeentscheid (hohes Risiko nur 'melden', auch per CHECK), Meldenachweis,
Information der Betroffenen, Nachweise, Abschluss nur vollstaendig, Gate
(hohes Risiko ohne Entscheid/Nachweis sofort rot), interne Zielfrist nur als
Owner-Wert, RBAC, Mandantentrennung und Audit. Werte sind Testwerte.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests.h10_support import ADMIN_ID, OTHER_TENANT, api, reason, user


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _contact(client):
    # Vertrag C-DSG-04 (Tier 1): dokumentierter Eskalationskontakt vor dem Meldeentscheid (Testwert).
    assert client.put("/privacy/owner-fields/incident.escalation_contact",
                      json={"value": "TESTWERT externe Beratung"}).status_code == 200


def _record(client, *, hours_ago: float = 2, **extra):
    body = {
        "discovered_at": _iso(_now() - timedelta(hours=hours_ago)), "incident_type": "CONFIDENTIALITY",
        "description": "Laptop mit Exportdatei verloren (Testwert)",
        "affected_data_categories": ["client_master_data", "financial_situation"],
        "affected_subjects_count": 12, "containment_measures": "Fernloeschung ausgeloest (Testwert)",
    }
    body.update(extra)
    return client.post("/privacy/incidents", json=body)


def test_high_risk_incident_full_lifecycle_and_gate(tmp_path):
    with api(tmp_path) as (client, _current, factory):
        created = _record(client)
        assert created.status_code == 201, created.text
        incident = created.json()
        assert incident["status"] == "OPEN" and incident["reference"].startswith("INC-")
        iid = incident["id"]

        gate = client.get("/privacy/incidents/gate").json()
        assert gate["blocked"] is False
        assert [f["reason_code"] for f in gate["findings"]] == ["INCIDENT_RISK_UNASSESSED"]

        no_contact = client.post(f"/privacy/incidents/{iid}/notification-decision", json={"decision": "NOTIFY"})
        assert no_contact.status_code == 409 and reason(no_contact) == "INCIDENT_OWNER_CONTACT_MISSING"
        _contact(client)
        early = client.post(f"/privacy/incidents/{iid}/notification-decision", json={"decision": "NOTIFY"})
        assert early.status_code == 409 and reason(early) == "INCIDENT_RISK_UNASSESSED"
        assert client.post(f"/privacy/incidents/{iid}/assessment", json={"risk_level": "HIGH"}).status_code == 422
        assessed = client.post(f"/privacy/incidents/{iid}/assessment", json={
            "risk_level": "HIGH", "rationale": "Unverschluesselte Vermoegensdaten (Testwert)"})
        assert assessed.json()["status"] == "ASSESSED"

        gate = client.get("/privacy/incidents/gate").json()
        assert gate["blocked"] is True
        assert "INCIDENT_NOTIFICATION_DECISION_MISSING" in [f["reason_code"] for f in gate["findings"]]
        assert client.get("/privacy/status").json()["incident_gate_blocked"] is True

        refused = client.post(f"/privacy/incidents/{iid}/notification-decision",
                              json={"decision": "NOT_REQUIRED", "reason": "x"})
        assert refused.status_code == 409 and reason(refused) == "INCIDENT_HIGH_RISK_REQUIRES_NOTIFICATION"
        decided = client.post(f"/privacy/incidents/{iid}/notification-decision", json={"decision": "NOTIFY"})
        assert decided.json()["status"] == "DECIDED"
        gate = client.get("/privacy/incidents/gate").json()
        assert gate["blocked"] is True
        assert "INCIDENT_EDOEB_NOTIFICATION_PENDING" in [f["reason_code"] for f in gate["findings"]]

        blocked_close = client.post(f"/privacy/incidents/{iid}/close", json={"note": "fertig"})
        assert blocked_close.status_code == 409 and reason(blocked_close) == "INCIDENT_REMEDIATION_OPEN"
        assert "Meldenachweis an den EDOEB fehlt" in blocked_close.json()["detail"]["problems"]

        before = client.post(f"/privacy/incidents/{iid}/edoeb-notification", json={
            "notified_at": _iso(_now() - timedelta(hours=5)), "reference": "EDOEB-TEST-1"})
        assert before.status_code == 422
        notified = client.post(f"/privacy/incidents/{iid}/edoeb-notification", json={
            "notified_at": _iso(_now()), "reference": "Meldeportal-Quittung TEST-1"})
        assert notified.status_code == 200
        assert client.get("/privacy/incidents/gate").json()["blocked"] is False

        no_reason = client.post(f"/privacy/incidents/{iid}/subject-notification-decision",
                                json={"decision": "DEFERRED"})
        assert no_reason.status_code == 422
        client.post(f"/privacy/incidents/{iid}/subject-notification-decision", json={"decision": "NOTIFY"})
        assert client.post(f"/privacy/incidents/{iid}/close", json={"note": "x"}).status_code == 409
        informed = client.post(f"/privacy/incidents/{iid}/subject-notification", json={
            "notified_at": _iso(_now()), "channel": "LETTER", "reference": "Serienbrief 12 Empfaenger (Testwert)"})
        assert informed.status_code == 200
        evidence = client.post(f"/privacy/incidents/{iid}/evidence",
                               json={"kind": "EDOEB_RECEIPT", "reference": "Ablage DS-2026-01 (Testwert)"})
        assert evidence.json()["evidence"][0]["kind"] == "EDOEB_RECEIPT"
        assert client.post(f"/privacy/incidents/{iid}/remediation", json={}).status_code == 422
        assert client.post(f"/privacy/incidents/{iid}/remediation",
                           json={"note": "Geraet gesperrt, Passwoerter rotiert (Testwert)"}).status_code == 200
        assert client.post(f"/privacy/incidents/{iid}/close", json={}).status_code == 422
        closed = client.post(f"/privacy/incidents/{iid}/close", json={"note": "Abgeschlossen (Testwert)"})
        assert closed.status_code == 200 and closed.json()["status"] == "CLOSED"
        assert client.post(f"/privacy/incidents/{iid}/evidence",
                           json={"kind": "OTHER", "reference": "y"}).status_code == 409
        assert client.get("/privacy/incidents/gate").json()["findings"] == []

        with factory() as s:
            steps = s.execute(text(
                "SELECT action FROM audit_log WHERE table_name = 'privacy_security_incidents' AND record_id = :id "
                "ORDER BY sequence"), {"id": iid}).scalars().all()
        assert steps[0] == "CREATE" and len(steps) == 9


def test_low_risk_can_be_reasoned_not_reportable(tmp_path):
    with api(tmp_path) as (client, _current, _factory):
        _contact(client)
        iid = _record(client, incident_type="AVAILABILITY", affected_data_categories=[]).json()["id"]
        client.post(f"/privacy/incidents/{iid}/assessment",
                    json={"risk_level": "LOW", "rationale": "Kurzer Ausfall, Sicherung intakt (Testwert)"})
        assert client.post(f"/privacy/incidents/{iid}/notification-decision",
                           json={"decision": "NOT_REQUIRED"}).status_code == 422
        decided = client.post(f"/privacy/incidents/{iid}/notification-decision",
                              json={"decision": "NOT_REQUIRED", "reason": "Kein hohes Risiko (Testwert)"})
        assert decided.status_code == 200
        reassessed = client.post(f"/privacy/incidents/{iid}/assessment",
                                 json={"risk_level": "HIGH", "rationale": "Neue Erkenntnis (Testwert)"})
        assert reassessed.json()["notification_decision"] is None
        assert client.get("/privacy/incidents/gate").json()["blocked"] is True


def test_database_check_forbids_high_risk_without_notification(tmp_path):
    from models.privacy import PrivacySecurityIncident

    with api(tmp_path) as (client, _current, factory):
        iid = _record(client).json()["id"]
        with factory() as s:
            row = s.get(PrivacySecurityIncident, iid)
            row.risk_level = "HIGH"
            row.notification_decision = "NOT_REQUIRED"
            with pytest.raises(IntegrityError):
                s.commit()


def test_input_validation(tmp_path):
    with api(tmp_path) as (client, _current, _factory):
        assert _record(client, hours_ago=-3).status_code == 422
        assert _record(client, incident_type="SONSTIGES").status_code == 422
        unknown = _record(client, affected_data_categories=["erfunden"])
        assert unknown.status_code == 422 and reason(unknown) == "INCIDENT_INPUT_INVALID"
        assert _record(client, affected_subjects_count=-1).status_code == 422


def test_owner_target_hours_drive_an_additional_finding(tmp_path):
    with api(tmp_path) as (client, _current, _factory):
        _contact(client)
        iid = _record(client, hours_ago=30).json()["id"]
        client.post(f"/privacy/incidents/{iid}/assessment", json={"risk_level": "HIGH", "rationale": "r"})
        client.post(f"/privacy/incidents/{iid}/notification-decision", json={"decision": "NOTIFY"})
        gate = client.get("/privacy/incidents/gate").json()
        assert gate["notification_target_hours"] is None
        assert "INCIDENT_NOTIFICATION_TARGET_EXCEEDED" not in [f["reason_code"] for f in gate["findings"]]
        assert client.put("/privacy/owner-fields/incident.notification_target_hours",
                          json={"value": "24"}).status_code == 200
        gate = client.get("/privacy/incidents/gate").json()
        assert gate["notification_target_hours"] == 24.0
        assert "INCIDENT_NOTIFICATION_TARGET_EXCEEDED" in [f["reason_code"] for f in gate["findings"]]
        assert gate["escalation_contact"]["status"] == "CONFIRMED"


def test_rbac_and_tenant_isolation(tmp_path):
    with api(tmp_path) as (client, current, _factory):
        current["user"] = user("advisor-1", role="advisor")
        recorded = _record(client)
        assert recorded.status_code == 201
        iid = recorded.json()["id"]
        assert client.get("/privacy/incidents").status_code == 403
        assert client.get(f"/privacy/incidents/{iid}").status_code == 403
        assert client.post(f"/privacy/incidents/{iid}/assessment",
                           json={"risk_level": "LOW", "rationale": "r"}).status_code == 403
        current["user"] = user("advisor-1", role="client")
        assert _record(client).status_code == 403

        current["user"] = user("admin-b", tenant=OTHER_TENANT)
        assert client.get("/privacy/incidents").json() == []
        assert client.get(f"/privacy/incidents/{iid}").status_code == 404
        assert client.get("/privacy/incidents/gate").json()["open_incidents"] == 0
        current["user"] = user(ADMIN_ID)
        assert client.get(f"/privacy/incidents/{iid}").status_code == 200


def test_alembic_revision_single_head_and_sqlite_roundtrip(tmp_path):
    from models.privacy import PrivacySecurityIncident
    from tests.h10_support import assert_single_head_contains, assert_sqlite_upgrade_downgrade_upgrade

    assert_single_head_contains("a7c3e9f1b5d2", "f4b8d2e6a3c7")
    assert_sqlite_upgrade_downgrade_upgrade(
        tmp_path, "a7c3e9f1b5d2", {"privacy_security_incidents": PrivacySecurityIncident},
    )


def test_alembic_postgres_ddl_creates_incidents_with_high_risk_check():
    from tests.h10_support import postgres_offline_ddl

    ddl = postgres_offline_ddl("f4b8d2e6a3c7", "a7c3e9f1b5d2")
    assert "CREATE TABLE privacy_security_incidents" in ddl
    assert "ck_privacy_incident_high_risk_notify" in ddl


def test_unknown_risk_escalates_like_high(tmp_path):
    """Vertrag C-DSG-04: unbekannter Risikostatus bleibt offen und eskaliert."""
    with api(tmp_path) as (client, _current, _factory):
        _contact(client)
        iid = _record(client).json()["id"]
        client.post(f"/privacy/incidents/{iid}/assessment",
                    json={"risk_level": "UNKNOWN", "rationale": "Umfang noch unklar (Testwert)"})
        gate = client.get("/privacy/incidents/gate").json()
        assert gate["blocked"] is True
        refused = client.post(f"/privacy/incidents/{iid}/notification-decision",
                              json={"decision": "NOT_REQUIRED", "reason": "x"})
        assert reason(refused) == "INCIDENT_HIGH_RISK_REQUIRES_NOTIFICATION"
