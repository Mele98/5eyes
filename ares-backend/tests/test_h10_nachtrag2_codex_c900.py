"""H10 Nachtrag 2: Codex-Pruefung H-154 (REJECTED_AT_SHA 19b5da11), C-900-02/03.

* C-900-02: persistente Egress-Ereignisse mit Manifest-Hash und Schema-Hash
  des Payloads (nur Form, nie Werte).
* C-900-03: Nachweis-Artefakte als append-only Zeilen mit Digest, Medientyp,
  Groesse, Erfassungszeit, Siegel und Bindung an die Fallkette; ausgetauschtes
  oder veraendertes Artefakt -> INCIDENT_EVIDENCE_HASH_MISMATCH.
(C-900-01 und Parallelbearbeitung: tests/test_h10_nachtrag1_contract.py.)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError

from services import egress_manifest as em
from tests.h10_support import api, reason

PDF = {"media_type": "application/pdf", "size_bytes": 48213}


def _incident(client) -> str:
    client.put("/privacy/owner-fields/incident.escalation_contact", json={"value": "TESTWERT"})
    return client.post("/privacy/incidents", json={
        "discovered_at": (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "incident_type": "AVAILABILITY", "description": "Testvorfall"}).json()["id"]


def _ready_to_close(client, iid):
    for step, body in (("assessment", {"risk_level": "LOW", "rationale": "r"}),
                       ("notification-decision", {"decision": "NOT_REQUIRED", "reason": "r"}),
                       ("subject-notification-decision", {"decision": "NOT_REQUIRED", "reason": "r"}),
                       ("remediation", {"note": "erledigt"})):
        assert client.post(f"/privacy/incidents/{iid}/{step}", json=body).status_code == 200


def test_artifact_rows_carry_digest_media_type_size_and_time(tmp_path):
    with api(tmp_path) as (client, _current, _factory):
        iid = _incident(client)
        missing = client.post(f"/privacy/incidents/{iid}/evidence",
                              json={"kind": "REPORT", "reference": "x", "sha256": "e" * 64})
        assert missing.status_code == 422
        out = client.post(f"/privacy/incidents/{iid}/evidence", json={
            "kind": "REPORT", "reference": "Forensik-Bericht (Testwert)", "sha256": "e" * 64, **PDF}).json()
        artifact = out["artifacts"][0]
        assert (artifact["sha256"], artifact["media_type"], artifact["size_bytes"]) == ("e" * 64, "application/pdf",
                                                                                        48213)
        assert artifact["recorded_at"] and len(artifact["row_sha256"]) == 64 and out["evidence_chain_ok"] is True
        ok = client.post(f"/privacy/incidents/{iid}/artifacts/{artifact['id']}/verify", json={"sha256": "e" * 64})
        assert ok.status_code == 200 and ok.json()["match"] is True
        swapped = client.post(f"/privacy/incidents/{iid}/artifacts/{artifact['id']}/verify", json={"sha256": "f" * 64})
        assert swapped.status_code == 409 and reason(swapped) == "INCIDENT_EVIDENCE_HASH_MISMATCH"


@pytest.mark.parametrize("tamper", [
    "UPDATE privacy_security_incident_artifacts SET sha256 = '{h}'",
    "UPDATE privacy_security_incident_artifacts SET size_bytes = 1",
])
def test_manipulated_artifact_row_blocks_close(tmp_path, tamper):
    with api(tmp_path) as (client, _current, factory):
        iid = _incident(client)
        client.post(f"/privacy/incidents/{iid}/evidence",
                    json={"kind": "REPORT", "reference": "Bericht", "sha256": "e" * 64, **PDF})
        _ready_to_close(client, iid)
        with factory() as s:
            with pytest.raises((IntegrityError, OperationalError, DBAPIError)):
                s.execute(text("DELETE FROM privacy_security_incident_artifacts"))
            s.rollback()
            s.execute(text("DROP TRIGGER trg_privacy_security_incident_artifacts_no_update"))
            s.execute(text(tamper.format(h="0" * 64)))
            s.commit()
        assert client.get(f"/privacy/incidents/{iid}").json()["evidence_chain_ok"] is False
        closed = client.post(f"/privacy/incidents/{iid}/close", json={"note": "fertig"})
        assert closed.status_code == 409 and reason(closed) == "INCIDENT_EVIDENCE_HASH_MISMATCH"


def test_egress_events_store_manifest_and_payload_schema_hash_without_values(tmp_path, monkeypatch):
    import database
    from routers.privacy import install_egress_guard, uninstall_egress_guard
    from tests.test_h10_c_dsg_03_egress_manifest import _raw_request

    with api(tmp_path) as (client, _current, factory):
        monkeypatch.setattr(database, "SessionLocal", factory)
        install_egress_guard()
        try:
            client.post("/privacy/egress-manifest/approve", json={})
            for target in ("/q/d/l/?s=spx&client_name=Erika", "/q/d/l/?s=spx&mandate=Erika2"):
                with pytest.raises(em.EgressBlocked):
                    _raw_request("stooq.com", target)
            with pytest.raises(em.EgressBlocked):
                em.check_host("tracker.unlisted.invalid")
            em.flush_events()
        finally:
            uninstall_egress_guard()
        events = client.get("/privacy/egress-events").json()
        by_code = {}
        for event in events:
            by_code.setdefault(event["reason_code"], []).append(event)
        field_events = by_code["EGRESS_FIELD_DENIED"]
        assert len({e["payload_schema_hash"] for e in field_events}) == 2  # andere Feldnamen -> anderer Hash
        assert all(len(e["payload_schema_hash"]) == 64 and len(e["manifest_sha256"]) == 64 for e in events)
        connect = by_code["EGRESS_DESTINATION_DENIED"][0]
        assert connect["payload_schema_hash"] == em.payload_schema_hash(None)
        with factory() as s:
            dump = " ".join(str(v) for row in s.execute(text("SELECT * FROM privacy_egress_events")).all() for v in row)
        assert "Erika" not in dump and "spx" not in dump


def test_payload_schema_hash_ignores_values():
    first = em.payload_shape(b"GET /q/d/l/?s=spx&i=d HTTP/1.1\r\nHost: stooq.com\r\n\r\n")
    second = em.payload_shape(b"GET /q/d/l/?s=nesn&i=w HTTP/1.1\r\nHost: stooq.com\r\n\r\n")
    third = em.payload_shape(b"GET /q/d/l/?s=spx&x=1 HTTP/1.1\r\nHost: stooq.com\r\n\r\n")
    assert em.payload_schema_hash(first) == em.payload_schema_hash(second) != em.payload_schema_hash(third)
    assert first == {"kind": "request", "method": "GET", "path_depth": 3, "query_fields": ["i", "s"], "body_fields": []}


def test_alembic_revision_single_head_and_sqlite_roundtrip(tmp_path):
    from models.privacy import SecurityIncidentArtifact
    from tests.h10_support import assert_single_head_contains, assert_sqlite_upgrade_downgrade_upgrade

    assert_single_head_contains("e8f1b3c5a7d9", "c4e8a2f6d0b7")
    assert_sqlite_upgrade_downgrade_upgrade(
        tmp_path, "e8f1b3c5a7d9", {"privacy_security_incident_artifacts": SecurityIncidentArtifact})


def test_alembic_postgres_ddl():
    from tests.h10_support import postgres_offline_ddl

    ddl = postgres_offline_ddl("c4e8a2f6d0b7", "e8f1b3c5a7d9")
    assert "CREATE TABLE privacy_security_incident_artifacts" in ddl
    assert "CREATE TRIGGER trg_privacy_security_incident_artifacts_immutable" in ddl
    assert "ADD COLUMN payload_schema_hash VARCHAR(64)" in ddl and "ADD COLUMN manifest_sha256 VARCHAR(64)" in ddl
