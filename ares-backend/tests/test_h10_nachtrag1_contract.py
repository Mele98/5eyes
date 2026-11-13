"""H10 Nachtrag 1 (Codex-Vertrag 2026-11-12): offene Vertragspunkte.

* C-DSG-01: versionierte, append-only Freigaben je Bearbeitung mit Content-
  Hash; Gate PROCESSING_ACTIVITY_MISSING/_UNAPPROVED/_AMBIGUOUS/_STALE/
  _HASH_MISMATCH; Auskunft erst mit wirksamer Freigabe.
* C-DSG-03: Laufzeitschutz prueft die wirksame Kanal-Freigabe (Hash),
  EGRESS_MANIFEST_MISSING/_HASH_MISMATCH/_GUARANTEE_MISSING/
  _CONSENT_OR_BASIS_MISSING; persistentes Protokoll ohne Payload;
  Kundennamen-Pruefung fuer Suchbegriffe (EGRESS_CLIENT_NAME_DENIED).
* C-DSG-02/04: append-only, verkettete Ereignisse; Nachweise mit Hash
  (INCIDENT_EVIDENCE_HASH_MISMATCH); parallele Statuswechsel -> genau einer
  wirksam, der andere 409 (PRIVACY_CASE_CONCURRENT_UPDATE).
Alle Werte sind Testwerte.
"""
from __future__ import annotations

import http.client
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError
from sqlalchemy.orm.exc import StaleDataError

from services import egress_manifest as em
from services import privacy_versions as pv
from tests.h10_support import (
    ADMIN_ID,
    CLIENT_ID,
    OTHER_TENANT,
    api,
    approve_register,
    confirm_all_owner_fields,
    make_customer_output_ready,
    reason,
    user,
)


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _dsar_ready(client) -> str:
    client.put("/privacy/owner-fields/subject_request.deadline_days", json={"value": "30"})
    case = client.post("/privacy/subject-requests", json={
        "client_id": CLIENT_ID, "request_type": "ACCESS", "received_at": _today(), "received_channel": "LETTER"})
    assert case.status_code == 201, case.text
    case_id = case.json()["id"]
    client.post(f"/privacy/subject-requests/{case_id}/identity", json={
        "outcome": "VERIFIED", "method": "ID_DOCUMENT_IN_PERSON", "evidence_reference": "TEST"})
    client.post(f"/privacy/subject-requests/{case_id}/decision", json={"decision": "FULFILL"})
    return case_id


# ── C-DSG-01 Freigaben ─────────────────────────────────────────────────────────

def test_register_approval_lifecycle_missing_approved_stale(tmp_path):
    with api(tmp_path) as (client, current, factory):
        case_id = _dsar_ready(client)
        confirm_all_owner_fields(client, only_blocking=True)
        blocked = client.post(f"/privacy/subject-requests/{case_id}/export")
        assert blocked.status_code == 409 and reason(blocked) == "PROCESSING_ACTIVITY_MISSING"
        approve_register(client)
        view = client.get("/privacy/processing-register").json()
        assert view["approval_reason_codes"] == [] and all(r["effective"]["version"] == 1 for r in view["approval"])
        assert client.post(f"/privacy/subject-requests/{case_id}/export").status_code == 200

        assert client.put("/privacy/owner-fields/controller.name", json={"value": "TESTWERT neue Firma"}).status_code == 200
        view = client.get("/privacy/processing-register").json()
        assert view["approval_reason_codes"] == ["PROCESSING_ACTIVITY_STALE"]
        assert view["customer_output_ready"] is False
        approve_register(client)
        view = client.get("/privacy/processing-register").json()
        assert view["approval_reason_codes"] == []
        assert {r["effective"]["version"] for r in view["approval"]} == {2}

        current["user"] = user("admin-b", tenant=OTHER_TENANT)
        other = client.get("/privacy/processing-register").json()
        assert other["approval_reason_codes"] == ["PROCESSING_ACTIVITY_MISSING"]
        with factory() as s:
            versions = s.execute(text("SELECT count(*) FROM processing_activity_versions")).scalar()
        assert versions == 18  # 9 Bearbeitungen x 2 Fassungen, nur Mandant main


def test_approval_needs_owner_values_and_is_admin_or_privacy_role(tmp_path):
    with api(tmp_path) as (client, current, _factory):
        refused = client.post("/privacy/processing-register/approve", json={})
        assert refused.status_code == 409 and reason(refused) == "PRIVACY_OWNER_VALUES_OPEN"
        current["user"] = user("advisor-1", role="advisor")
        assert client.post("/privacy/processing-register/approve", json={}).status_code == 403


def test_inventory_rows_are_unapproved_and_tampering_is_detected(tmp_path):
    with api(tmp_path) as (client, _current, factory):
        with factory() as s:
            pv.ensure_inventory_rows(s, "main", {}, actor_id="system")
            s.commit()
        view = client.get("/privacy/processing-register").json()
        assert view["approval_reason_codes"] == ["PROCESSING_ACTIVITY_UNAPPROVED"]
        make_customer_output_ready(client)
        with factory() as s:
            with pytest.raises((IntegrityError, OperationalError, DBAPIError)):
                s.execute(text("UPDATE processing_activity_versions SET content_json = '{}'"))
            s.rollback()
            s.execute(text("DROP TRIGGER trg_processing_activity_versions_no_update"))
            s.execute(text(
                "UPDATE processing_activity_versions SET content_json = '{\"activity\": \"manipuliert\"}' "
                "WHERE activity_key = 'PA-01' AND status = 'APPROVED'"))
            s.commit()
        view = client.get("/privacy/processing-register").json()
        assert view["approval_reason_codes"] == ["PROCESSING_ACTIVITY_HASH_MISMATCH"]


def test_two_effective_versions_at_the_same_instant_are_ambiguous():
    row = SimpleNamespace(status="APPROVED", valid_from="2026-11-12T00:00:00.000000Z", content_json="{}",
                          content_sha256=pv._content_hash({}))
    code, effective = pv._evaluate([row, row], pv._content_hash({}), "2026-11-13", "activity")
    assert code == "PROCESSING_ACTIVITY_AMBIGUOUS" and effective is None
    assert pv._evaluate([row], pv._content_hash({}), "2026-11-13", "activity")[0] is None


# ── C-DSG-03 Freigabe zur Laufzeit, Protokoll, Kundennamen ────────────────────

def _settings(**extra):
    return SimpleNamespace(**{"smtp_enabled": True, "smtp_host": "smtp.mail-provider.example",
                              "eodhd_api_key": "TESTKEY", **extra})


def _request(host, target):
    from tests.test_h10_c_dsg_03_egress_manifest import _raw_request
    return _raw_request(host, target)


def test_runtime_requires_approved_channel_hash_and_logs_persistently(tmp_path, monkeypatch):
    import database
    from routers.privacy import install_egress_guard, uninstall_egress_guard

    with api(tmp_path) as (client, _current, factory):
        monkeypatch.setattr(database, "SessionLocal", factory)
        monkeypatch.setattr("config.settings.smtp_enabled", True)
        monkeypatch.setattr("config.settings.smtp_host", "smtp.mail-provider.example")
        install_egress_guard()
        try:
            with pytest.raises(em.EgressBlocked) as blocked:
                em.check_host("stooq.com")
            assert blocked.value.reason_code == "EGRESS_MANIFEST_MISSING"
            assert em.check_host("127.0.0.1") is None
            approved = client.post("/privacy/egress-manifest/approve", json={})
            assert approved.status_code == 200, approved.text
            assert em.check_host("stooq.com")["id"] == "market_data.stooq"
            with pytest.raises(em.EgressBlocked) as blocked:
                em.check_host("smtp.mail-provider.example")
            assert blocked.value.reason_code == "EGRESS_GUARANTEE_MISSING"

            for key in ("egress.mail.smtp.destination_country", "egress.mail.smtp.guarantee"):
                client.put(f"/privacy/owner-fields/{key}", json={"value": f"TESTWERT {key}"})
            with pytest.raises(em.EgressBlocked) as blocked:
                em.check_host("smtp.mail-provider.example")
            assert blocked.value.reason_code == "EGRESS_HASH_MISMATCH"  # Aenderung -> neu freigeben
            client.post("/privacy/egress-manifest/approve", json={"keys": ["mail.smtp"]})
            with pytest.raises(em.EgressBlocked) as blocked:
                em.check_host("smtp.mail-provider.example")
            assert blocked.value.reason_code == "EGRESS_CONSENT_OR_BASIS_MISSING"
            client.put("/privacy/owner-fields/egress.mail.smtp.legal_basis", json={"value": "TESTWERT Vertrag"})
            client.post("/privacy/egress-manifest/approve", json={"keys": ["mail.smtp"]})
            assert em.check_host("smtp.mail-provider.example")["id"] == "mail.smtp"

            client.put("/privacy/owner-fields/egress.market_data.stooq.destination_country",
                       json={"value": "TESTWERT Staat"})
            with pytest.raises(em.EgressBlocked) as blocked:
                em.check_host("stooq.com")
            assert blocked.value.reason_code == "EGRESS_HASH_MISMATCH"
            assert em.flush_events() >= 1
        finally:
            uninstall_egress_guard()
        events = client.get("/privacy/egress-events").json()
        codes = [e["reason_code"] for e in events]
        assert {"EGRESS_MANIFEST_MISSING", "EGRESS_GUARANTEE_MISSING", "EGRESS_HASH_MISMATCH",
                "EGRESS_CONSENT_OR_BASIS_MISSING"} <= set(codes)
        assert set(events[0]) == {"occurred_at", "channel_id", "channel_class", "destination_host", "reason_code",
                                  "result", "manifest_version", "channel_sha256", "manifest_sha256",
                                  "payload_schema_hash"}
        with factory() as s:
            columns = {row[1] for row in s.execute(text("PRAGMA table_info(privacy_egress_events)")).all()}
            tenants = set(s.execute(text("SELECT DISTINCT tenant_id FROM privacy_egress_events")).scalars())
        assert not {"payload", "body", "url", "query"} & columns and tenants == {"main"}


def test_operator_database_is_exempt_from_approval():
    from tests.h10_support import all_channel_states

    states = all_channel_states(em.load_manifest())
    states["operator.database"] = {"approved_sha256": None, "current_sha256": "x", "owner_block": None,
                                   "approval_exempt": True}
    em.activate(_settings(database_url="postgresql://u@db.firma-intern.example/ares"), channel_states=states)
    try:
        assert em.check_host("db.firma-intern.example")["id"] == "operator.database"
    finally:
        em.deactivate()


@pytest.fixture
def name_guard():
    from tests.h10_support import all_channel_states

    names = ["Erika Beispiel", "Hans Müller", " "]
    em.activate(_settings(), channel_states=all_channel_states(em.load_manifest()),
                client_name_provider=lambda: names)
    try:
        yield names
    finally:
        em.deactivate()


@pytest.mark.parametrize("term", ["Erika%20Beispiel", "Beispiel%20Erika%20Fonds", "HANS%20MULLER",
                                  "Hans%20M%C3%BCller"])
def test_search_terms_with_client_names_are_blocked(name_guard, term):
    with pytest.raises(em.EgressBlocked) as blocked:
        _request("eodhd.com", f"/api/search/{term}?api_token=T&fmt=json")
    assert blocked.value.reason_code == "EGRESS_CLIENT_NAME_DENIED"


def test_product_search_terms_pass_and_provider_failure_blocks(name_guard):
    assert _request("eodhd.com", "/api/search/iShares%20Core%20SPI?api_token=T&fmt=json")
    assert _request("eodhd.com", "/api/search/Erika?api_token=T&fmt=json")  # Vorname allein ist kein Name
    em._STATE.client_name_provider = lambda: (_ for _ in ()).throw(RuntimeError("db"))
    with pytest.raises(em.EgressBlocked) as blocked:
        _request("eodhd.com", "/api/search/SPI?api_token=T&fmt=json")
    assert blocked.value.reason_code == "EGRESS_CLIENT_NAME_DENIED"


def test_client_name_provider_reads_names_of_the_installation(tmp_path):
    from services.dsg_governance import _client_names

    with api(tmp_path) as (_client, _current, factory):
        names = _client_names(factory)()
    assert ("Erika", "Beispiel") in names


# ── C-DSG-04 Nachweis-Hash, Ereigniskette ─────────────────────────────────────

def test_incident_evidence_needs_hash_and_tampering_blocks_close(tmp_path):
    with api(tmp_path) as (client, _current, factory):
        client.put("/privacy/owner-fields/incident.escalation_contact", json={"value": "TESTWERT"})
        iid = client.post("/privacy/incidents", json={
            "discovered_at": (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "incident_type": "AVAILABILITY", "description": "Testvorfall"}).json()["id"]
        assert client.post(f"/privacy/incidents/{iid}/evidence",
                           json={"kind": "REPORT", "reference": "x"}).status_code == 422
        assert client.post(f"/privacy/incidents/{iid}/evidence",
                           json={"kind": "REPORT", "reference": "x", "sha256": "XYZ", "media_type": "application/pdf", "size_bytes": 1234}).status_code == 422
        out = client.post(f"/privacy/incidents/{iid}/evidence",
                          json={"kind": "REPORT", "reference": "Bericht (Testwert)", "sha256": "c" * 64, "media_type": "application/pdf", "size_bytes": 1234}).json()
        assert out["evidence_chain_ok"] is True and out["events"][-1]["artifact_sha256"] == "c" * 64
        for step, body in (("assessment", {"risk_level": "LOW", "rationale": "r"}),
                           ("notification-decision", {"decision": "NOT_REQUIRED", "reason": "r"}),
                           ("subject-notification-decision", {"decision": "NOT_REQUIRED", "reason": "r"}),
                           ("remediation", {"note": "erledigt"})):
            assert client.post(f"/privacy/incidents/{iid}/{step}", json=body).status_code == 200
        with factory() as s:
            s.execute(text("DROP TRIGGER trg_privacy_security_incident_events_no_update"))
            s.execute(text("UPDATE privacy_security_incident_events SET artifact_sha256 = :h "
                           "WHERE event_type = 'evidence'"), {"h": "d" * 64})
            s.commit()
        assert client.get(f"/privacy/incidents/{iid}").json()["evidence_chain_ok"] is False
        closed = client.post(f"/privacy/incidents/{iid}/close", json={"note": "fertig"})
        assert closed.status_code == 409 and reason(closed) == "INCIDENT_EVIDENCE_HASH_MISMATCH"


def test_case_events_are_append_only_and_chained(tmp_path):
    with api(tmp_path) as (client, _current, factory):
        case_id = _dsar_ready(client)
        out = client.get(f"/privacy/subject-requests/{case_id}").json()
        assert [e["event_type"] for e in out["events"]] == ["received", "identity", "decision"]
        assert out["events_chain_ok"] is True
        with factory() as s:
            with pytest.raises((IntegrityError, OperationalError, DBAPIError)):
                s.execute(text("DELETE FROM privacy_subject_request_events"))
            s.rollback()


# ── Parallele Bearbeitung ─────────────────────────────────────────────────────

@pytest.mark.parametrize("kind", ["dsar", "incident"])
def test_two_concurrent_status_changes_one_wins(tmp_path, kind):
    from models.privacy import PrivacySecurityIncident, PrivacySubjectRequest

    with api(tmp_path) as (client, _current, factory):
        if kind == "dsar":
            client.put("/privacy/owner-fields/subject_request.deadline_days", json={"value": "30"})
            cid = client.post("/privacy/subject-requests", json={
                "client_id": CLIENT_ID, "request_type": "ACCESS", "received_at": _today(),
                "received_channel": "LETTER"}).json()["id"]
            model, field, values = PrivacySubjectRequest, "status", ("IDENTITY_VERIFIED", "WITHDRAWN")
        else:
            cid = client.post("/privacy/incidents", json={
                "discovered_at": _today(), "incident_type": "AVAILABILITY", "description": "x"}).json()["id"]
            model, field, values = PrivacySecurityIncident, "risk_level", ("LOW", "HIGH")
        first, second = factory(), factory()
        try:
            a, b = first.get(model, cid), second.get(model, cid)
            setattr(a, field, values[0])
            setattr(b, field, values[1])
            first.commit()
            with pytest.raises(StaleDataError):
                second.commit()
        finally:
            first.close()
            second.close()
        with factory() as s:
            assert getattr(s.get(model, cid), field) == values[0]


def test_api_maps_a_concurrent_change_to_409(tmp_path, monkeypatch):
    from services import privacy_subject_requests

    with api(tmp_path) as (client, _current, factory):
        client.put("/privacy/owner-fields/subject_request.deadline_days", json={"value": "30"})
        cid = client.post("/privacy/subject-requests", json={
            "client_id": CLIENT_ID, "request_type": "ACCESS", "received_at": _today(),
            "received_channel": "LETTER"}).json()["id"]
        original = privacy_subject_requests.verify_identity

        def concurrent_writer(*args, **kwargs):
            result = original(*args, **kwargs)  # Aenderung im Speicher, noch nicht geschrieben
            with factory() as other:  # zweiter Bearbeiter schreibt zuerst
                other.execute(text("UPDATE privacy_subject_requests SET row_version = row_version + 1, "
                                   "status = 'WITHDRAWN' WHERE id = :id"), {"id": cid})
                other.commit()
            return result

        monkeypatch.setattr(privacy_subject_requests, "verify_identity", concurrent_writer)
        response = client.post(f"/privacy/subject-requests/{cid}/identity", json={
            "outcome": "VERIFIED", "method": "ID_DOCUMENT_IN_PERSON", "evidence_reference": "TEST"})
        assert response.status_code == 409 and reason(response) == "PRIVACY_CASE_CONCURRENT_UPDATE"
        with factory() as s:
            row = s.execute(text("SELECT status, identity_verified_at FROM privacy_subject_requests "
                                 "WHERE id = :id"), {"id": cid}).one()
        assert tuple(row) == ("WITHDRAWN", None)


def test_event_sequence_is_unique_per_case(tmp_path):
    from models.privacy import PrivacySubjectRequestEvent

    with api(tmp_path) as (_client, _current, factory):
        with factory() as s:
            for _ in range(2):
                s.add(PrivacySubjectRequestEvent(id=str(_), tenant_id="main", case_id="c", sequence=1,
                                                 event_type="x", actor_id="a", occurred_at="t", payload_json="{}",
                                                 event_sha256="e" * 64))
            with pytest.raises(IntegrityError):
                s.commit()


# ── Migration ─────────────────────────────────────────────────────────────────

def test_alembic_revision_single_head_and_sqlite_roundtrip(tmp_path):
    from models import privacy as m
    from tests.h10_support import assert_single_head_contains, assert_sqlite_upgrade_downgrade_upgrade

    assert_single_head_contains("c4e8a2f6d0b7", "a7c3e9f1b5d2")
    assert_sqlite_upgrade_downgrade_upgrade(tmp_path, "c4e8a2f6d0b7", {
        "processing_activity_versions": m.ProcessingActivityVersion,
        "outbound_processing_manifest_versions": m.OutboundManifestVersion,
        "privacy_egress_events": m.OutboundProcessingEvent,
        "privacy_subject_request_events": m.PrivacySubjectRequestEvent,
        "privacy_security_incident_events": m.PrivacySecurityIncidentEvent,
    }, later_columns=frozenset({"manifest_sha256", "payload_schema_hash"}))  # Nachtrag 2, e8f1b3c5a7d9


def test_alembic_postgres_ddl_creates_append_only_triggers_and_row_version():
    from tests.h10_support import postgres_offline_ddl

    ddl = postgres_offline_ddl("a7c3e9f1b5d2", "c4e8a2f6d0b7")
    for table in ("processing_activity_versions", "outbound_processing_manifest_versions", "privacy_egress_events",
                  "privacy_subject_request_events", "privacy_security_incident_events"):
        assert f"CREATE TABLE {table}" in ddl and f"CREATE TRIGGER trg_{table}_immutable" in ddl
    assert "ADD COLUMN row_version INTEGER DEFAULT '1' NOT NULL" in ddl
    assert "uq_processing_activity_version_valid_from" in ddl
