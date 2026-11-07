"""F4 (Codex-Entscheid Runde 3, 2026-11-07): Audit-Anker.

Entscheid: "signiertes Backup-Manifest plus externer append-only/WORM-/
Treuhand-Anker. Mindestens ein verifizierter Kettenkopf-/Siegel-Anker vor
produktiver Weiterberatung nach Umstieg."

Die Kette allein erkennt weder ein abgeschnittenes Ende (Zeilen + Zaehler
zurueckgesetzt) noch eine vollstaendige Neuberechnung (Pruefrunde #869,
Abschnitt 4). Geprueft:

1. Export nur nach erfolgreicher Vollpruefung; Quittung ohne Inhalte/Pfade,
   Fingerabdruck, Signatur bei konfiguriertem backup_hmac_key.
2. Verify: angehaengte Eintraege ok; abgeschnittenes Ende, Neuberechnung,
   geaenderter Altbestand und manipulierte Quittung -> nicht ok (die
   Kettenpruefung allein meldet dabei ok).
3. Backup-Manifest (jedes Backup): Kettenkopf + Siegel des Snapshots,
   HMAC-signiert; verify_backup_manifest erkennt Manipulation.
4. Restore-Abgleich: Anker gegen die wiederhergestellte Datenbank.
5. Endpoints (Rollen, 409 bei Bruch, Audit-Eintrag) und CLI.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import config  # noqa: E402
import database  # noqa: E402
from database import Base, get_db  # noqa: E402
from main import app  # noqa: E402
from models.review import AuditLog  # noqa: E402
from services import backup as backup_engine  # noqa: E402
from services.audit import (  # noqa: E402
    LEGACY_SEAL_SCHEME,
    AuditAnchorError,
    AuditAnchorNotVerified,
    _audit_integrity_payload,
    audit_log_integrity_report,
    backup_snapshot_anchor,
    export_audit_anchor,
    format_anchor_text,
    log,
    parse_anchor_text,
    run_startup_audit_chain_check,
    verify_audit_anchor,
)
from services.auth import get_current_user  # noqa: E402

SECRET = "Geheimer-Inhalt-F4-8812"
KEY = "f4-test-signaturschluessel-nicht-produktiv"


@pytest.fixture()
def db_file(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "db_use_sqlcipher", False)
    monkeypatch.setattr(config.settings, "backup_hmac_key", "")
    return tmp_path / "f4.db"


@pytest.fixture()
def session_local(db_file):
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    yield factory
    engine.dispose()


def _factory_for(path: Path):
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    return engine, sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)


def _legacy_rows(session_local, n: int = 2) -> None:
    with session_local() as s:
        for i in range(n):
            s.add(AuditLog(
                id=f"L{i}", user_id="u0", user_name=f"Alt {SECRET}", table_name="clients",
                record_id=f"c{i}", action="UPDATE", old_value=SECRET, new_value=f"{SECRET}-{i}",
                created_at=f"2026-03-0{i + 1}T10:00:00.000Z",
            ))
        s.commit()


def _log_n(session_local, n: int, start: int = 0) -> None:
    for i in range(start, start + n):
        with session_local() as s:
            log(s, user_id="u1", user_name=f"Berater {SECRET}", table_name="clients",
                record_id=f"c{i}", action="UPDATE", field_name="note", old_value=SECRET,
                new_value=f"{SECRET}-{i}", ip_address="198.51.100.7", tenant_id="tenant-a")
            s.commit()


def _sql(session_local, statement: str, **params) -> None:
    with session_local() as s:
        s.execute(text(statement), params)
        s.commit()


def _prepared(session_local) -> None:
    """Altbestand + Siegel (Startpruefung) + verkettete Eintraege."""
    _legacy_rows(session_local, 2)
    run_startup_audit_chain_check(session_local, max_rows=10_000)
    _log_n(session_local, 4)


def _export(session_local, key: str | None = None) -> dict:
    with session_local() as s:
        return export_audit_anchor(s, key=key)


def _verify(session_local, payload, key: str | None = None) -> dict:
    with session_local() as s:
        return verify_audit_anchor(s, payload, key=key)


def _truncate_tail(session_local, keep: int) -> None:
    """Angreifer mit Dateizugriff: Zeilen am Ende loeschen, Zaehler und
    last_hash konsistent zuruecksetzen. Die Kette allein bleibt 'ok'."""
    with session_local() as s:
        head = s.execute(text("SELECT integrity_hash FROM audit_log WHERE sequence = :n"), {"n": keep}).scalar()
        s.execute(text("DELETE FROM audit_log WHERE sequence > :n"), {"n": keep})
        s.execute(text("UPDATE audit_log_sequence_counter SET value = :n, last_hash = :h"), {"n": keep, "h": head})
        s.commit()


# ---------------------------------------------------------------------------
# 1. Export
# ---------------------------------------------------------------------------

def test_export_contains_head_and_seal_without_contents(session_local):
    _prepared(session_local)
    anchor = _export(session_local)
    with session_local() as s:
        counter = s.execute(text("SELECT value, last_hash FROM audit_log_sequence_counter")).one()
        seal = s.query(AuditLog).filter(AuditLog.field_name == "LEGACY_SEAL").one()
    assert anchor["scheme"] == "ares-audit-anchor-v1" and anchor["product"] == "Ares"
    assert anchor["verified"] == "yes" and anchor["source"] == "live"
    assert anchor["chain_sequence"] == counter[0] == 5
    assert anchor["chain_head_hash"] == counter[1]
    assert anchor["legacy_seal_sequence"] == seal.sequence == 1
    assert anchor["legacy_seal_entry_hash"] == seal.integrity_hash
    assert anchor["legacy_seal_digest"] == json.loads(seal.new_value)["sha256"]
    assert anchor["legacy_seal_count"] == 2
    assert anchor["signature"] == "none"
    receipt = format_anchor_text(anchor)
    assert SECRET not in receipt and "198.51.100.7" not in receipt and "tenant-a" not in receipt
    assert "\r" not in receipt and receipt.isascii()
    assert parse_anchor_text(receipt) == anchor


def test_export_is_refused_on_broken_chain(session_local):
    _prepared(session_local)
    _sql(session_local, "UPDATE audit_log SET old_value = 'x' WHERE sequence = 3")
    with pytest.raises(AuditAnchorNotVerified):
        _export(session_local)


def test_export_is_refused_on_inconsistent_head(session_local):
    _prepared(session_local)
    _sql(session_local, "UPDATE audit_log_sequence_counter SET last_hash = :h", h="0" * 64)
    with pytest.raises(AuditAnchorError):
        _export(session_local)


def test_signed_anchor_verifies_and_detects_wrong_key(session_local):
    _prepared(session_local)
    anchor = _export(session_local, key=KEY)
    assert anchor["signature"].startswith("hmac-sha256:")
    receipt = format_anchor_text(anchor)
    assert _verify(session_local, receipt, key=KEY)["ok"] is True
    wrong = _verify(session_local, receipt, key="anderer-schluessel")
    assert wrong["ok"] is False and wrong["signature"] == "invalid"
    missing = _verify(session_local, receipt, key=None)
    assert missing["ok"] is False and "signature_key_missing" in missing["reasons"]


# ---------------------------------------------------------------------------
# 2. Verify
# ---------------------------------------------------------------------------

def test_anchor_stays_valid_when_chain_grows(session_local):
    _prepared(session_local)
    receipt = format_anchor_text(_export(session_local))
    _log_n(session_local, 3, start=50)
    result = _verify(session_local, receipt)
    assert result["ok"] is True, result
    assert result["current_sequence"] == 8 and result["anchor_sequence"] == 5
    assert result["full_chain_ok"] is True


def test_truncated_tail_is_invisible_to_chain_but_caught_by_anchor(session_local):
    _prepared(session_local)
    receipt = format_anchor_text(_export(session_local))
    _truncate_tail(session_local, keep=3)
    with session_local() as s:
        assert audit_log_integrity_report(s)["ok"] is True, "Kette allein erkennt das nicht"
    result = _verify(session_local, receipt)
    assert result["ok"] is False
    assert "chain_prefix_changed" in result["reasons"] and "chain_head_mismatch" in result["reasons"]


def test_full_recomputation_is_caught_by_anchor(session_local):
    """Angreifer aendert Zeile 3 und berechnet alle Hashes ab dort neu."""
    _prepared(session_local)
    receipt = format_anchor_text(_export(session_local))
    with session_local() as s:
        rows = s.query(AuditLog).filter(AuditLog.sequence.isnot(None)).order_by(AuditLog.sequence).all()
        previous = ""
        for row in rows:
            if row.sequence == 3:
                row_old = "umgeschrieben"
            else:
                row_old = row.old_value
            new_hash = hashlib.sha256(_audit_integrity_payload(
                entry_id=row.id, user_id=row.user_id, user_name=row.user_name, table_name=row.table_name,
                record_id=row.record_id, action=row.action, field_name=row.field_name, old_value=row_old,
                new_value=row.new_value, mandate_id=row.mandate_id, client_id=row.client_id,
                ip_address=row.ip_address, created_at=row.created_at, previous_hash=previous,
                tenant_id=row.tenant_id,
            ).encode("utf-8")).hexdigest()
            s.execute(text(
                "UPDATE audit_log SET old_value = :o, previous_hash = :p, integrity_hash = :h WHERE id = :i"
            ), {"o": row_old, "p": previous, "h": new_hash, "i": row.id})
            previous = new_hash
        s.execute(text("UPDATE audit_log_sequence_counter SET last_hash = :h"), {"h": previous})
        s.commit()
    with session_local() as s:
        assert audit_log_integrity_report(s)["ok"] is True, "Neuberechnung ist fuer die Kette unsichtbar"
    result = _verify(session_local, receipt)
    assert result["ok"] is False and "chain_head_mismatch" in result["reasons"]


def test_changed_legacy_rows_are_caught(session_local):
    _prepared(session_local)
    receipt = format_anchor_text(_export(session_local))
    _sql(session_local, "UPDATE audit_log SET new_value = 'x' WHERE id = 'L1'")
    result = _verify(session_local, receipt)
    assert result["ok"] is False and "legacy_rows_changed" in result["reasons"]


def test_edited_receipt_fails_fingerprint(session_local):
    _prepared(session_local)
    anchor = _export(session_local)
    receipt = format_anchor_text(anchor)
    forged = receipt.replace(f"chain_sequence: {anchor['chain_sequence']}", "chain_sequence: 3")
    result = _verify(session_local, forged)
    assert result["ok"] is False and "fingerprint_mismatch" in result["reasons"]


@pytest.mark.parametrize("payload", [
    "",
    "scheme: ares-audit-anchor-v1\n",
    "unbekannt: 1\n",
])
def test_unreadable_receipt_is_rejected(payload):
    with pytest.raises(AuditAnchorError):
        parse_anchor_text(payload)


# ---------------------------------------------------------------------------
# 3./4. Backup-Manifest und Restore-Abgleich
# ---------------------------------------------------------------------------

def test_every_backup_manifest_carries_signed_snapshot_anchor(session_local, db_file, tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "backup_hmac_key", KEY)
    _prepared(session_local)
    result = backup_engine.backup_database(
        tmp_path / "backups", source_db_path=db_file, snapshot_anchor=backup_snapshot_anchor
    )
    manifest_path = result.manifest_path
    assert manifest_path == result.path.with_suffix(".db.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    with session_local() as s:
        counter = s.execute(text("SELECT value, last_hash FROM audit_log_sequence_counter")).one()
    anchor = manifest["audit_anchor"]
    assert anchor["source"] == "backup-snapshot" and anchor["verified"] == "no"
    assert (anchor["chain_sequence"], anchor["chain_head_hash"]) == (counter[0], counter[1])
    assert anchor["legacy_seal_count"] == 2
    assert manifest["manifest_signature"].startswith("hmac-sha256:")
    assert backup_engine.verify_backup_manifest(manifest_path) == {
        "ok": True, "signature": "valid", "db_sha256_ok": True,
        "audit_anchor": anchor, "audit_anchor_error": None,
    }
    assert SECRET not in manifest_path.read_text(encoding="utf-8")

    manifest["audit_anchor"]["chain_sequence"] = 3
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    tampered = backup_engine.verify_backup_manifest(manifest_path)
    assert tampered["ok"] is False and tampered["signature"] == "invalid"


def test_unsigned_manifest_is_not_ok_once_key_is_configured(session_local, db_file, tmp_path, monkeypatch):
    _prepared(session_local)
    result = backup_engine.backup_database(
        tmp_path / "backups", source_db_path=db_file, snapshot_anchor=backup_snapshot_anchor
    )
    assert backup_engine.verify_backup_manifest(result.manifest_path)["signature"] == "none"
    monkeypatch.setattr(config.settings, "backup_hmac_key", KEY)
    check = backup_engine.verify_backup_manifest(result.manifest_path)
    assert check["ok"] is False and check["signature"] == "missing"


def test_restore_reconciliation_against_exported_and_manifest_anchor(session_local, db_file, tmp_path):
    _prepared(session_local)
    exported = format_anchor_text(_export(session_local))
    result = backup_engine.backup_database(
        tmp_path / "backups", source_db_path=db_file, snapshot_anchor=backup_snapshot_anchor
    )
    restored_path = tmp_path / "restored" / "ares.db"
    backup_engine.restore_database(result.path, target_db_path=restored_path)
    engine, restored = _factory_for(restored_path)
    try:
        assert _verify(restored, exported)["ok"] is True
        assert _verify(restored, result.audit_anchor)["ok"] is True
    finally:
        engine.dispose()


def test_restore_of_older_backup_fails_newer_anchor(session_local, db_file, tmp_path):
    """Ein Anker nach dem Backup passt nicht zu einem aelteren Restore: der
    Restore-Abgleich zeigt fehlende Eintraege statt sie zu verdecken."""
    _prepared(session_local)
    result = backup_engine.backup_database(
        tmp_path / "backups", source_db_path=db_file, snapshot_anchor=backup_snapshot_anchor
    )
    _log_n(session_local, 2, start=70)
    newer = format_anchor_text(_export(session_local))
    restored_path = tmp_path / "restored" / "ares.db"
    backup_engine.restore_database(result.path, target_db_path=restored_path)
    engine, restored = _factory_for(restored_path)
    try:
        assert _verify(restored, newer)["ok"] is False
    finally:
        engine.dispose()


def test_manifest_of_database_without_chain_keeps_backup(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "db_use_sqlcipher", False)
    plain = tmp_path / "plain.db"
    import sqlite3

    conn = sqlite3.connect(plain)
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.commit()
    conn.close()
    result = backup_engine.backup_database(tmp_path / "b", source_db_path=plain, snapshot_anchor=backup_snapshot_anchor)
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["audit_anchor"] is None and manifest["audit_anchor_error"] == "OperationalError"


# ---------------------------------------------------------------------------
# 5. Endpoints und CLI
# ---------------------------------------------------------------------------

@pytest.fixture()
def client_for(session_local, monkeypatch):
    monkeypatch.setattr(config.settings, "strict_tenant_isolation", False, raising=False)

    def make(role: str) -> TestClient:
        def _db():
            db = session_local()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            id=f"user-{role}", role=role, tenant_id=None, full_name="Operator", email="op@example.invalid",
        )
        return TestClient(app)

    yield make
    app.dependency_overrides.clear()


def test_export_and_verify_endpoints(session_local, client_for):
    _prepared(session_local)
    client = client_for("super_admin")
    exported = client.post("/admin/system/audit-log/anchor/export")
    assert exported.status_code == 200, exported.text
    body = exported.json()
    assert body["anchor"]["chain_sequence"] == 5
    assert SECRET not in exported.text
    with session_local() as s:
        entry = s.query(AuditLog).filter(AuditLog.table_name == "audit_anchor").one()
    assert entry.action == "EXPORT" and entry.sequence == 6
    assert entry.record_id == body["anchor"]["fingerprint"]
    verified = client.post("/admin/system/audit-log/anchor/verify", json={"anchor_text": body["text"]})
    assert verified.status_code == 200 and verified.json()["ok"] is True
    unreadable = client.post("/admin/system/audit-log/anchor/verify", json={"anchor_text": "kaputt"})
    assert unreadable.status_code == 422


def test_export_endpoint_refuses_broken_chain(session_local, client_for):
    _prepared(session_local)
    _sql(session_local, "UPDATE audit_log SET old_value = 'x' WHERE sequence = 2")
    response = client_for("super_admin").post("/admin/system/audit-log/anchor/export")
    assert response.status_code == 409
    with session_local() as s:
        assert s.query(AuditLog).filter(AuditLog.table_name == "audit_anchor").count() == 0


@pytest.mark.parametrize("role", ["advisor", "assistant", "viewer", "client"])
def test_anchor_endpoints_reject_non_admin_roles(session_local, client_for, role):
    client = client_for(role)
    assert client.post("/admin/system/audit-log/anchor/export").status_code == 403
    assert client.post(
        "/admin/system/audit-log/anchor/verify", json={"anchor_text": "x"}
    ).status_code == 403


def test_cli_export_verify_and_never_overwrite(session_local, tmp_path, monkeypatch, capsys):
    sys.path.insert(0, str(BACKEND_ROOT / "scripts"))
    import audit_anchor as cli

    _prepared(session_local)
    monkeypatch.setattr(database, "SessionLocal", session_local)
    out = tmp_path / "anker.txt"
    assert cli.main(["export", "--out", str(out)]) == 0
    assert out.read_bytes().count(b"\r") == 0
    assert cli.main(["export", "--out", str(out)]) == 2, "nie ueberschreiben"
    assert cli.main(["verify", str(out)]) == 0
    _truncate_tail(session_local, keep=3)
    assert cli.main(["verify", str(out)]) == 1
    captured = capsys.readouterr()
    assert SECRET not in captured.out + captured.err
