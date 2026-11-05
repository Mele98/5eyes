"""H-865-2 (Pruefrunde #865): Kettenpruefung des Audit-Logs zur Laufzeit.

verify_audit_chain() wurde bisher nur in Tests aufgerufen; fuer Altzeilen ohne
sequence gab es gar keinen Pruefer. Abgedeckt:

1. Strukturierter Verifier: Brueche, Luecken (auch abgeschnittenes Ende ueber
   den Sequenzzaehler), Duplikate und Hash-Abweichungen als Sequenznummern.
2. Pruefung pro Zeile fuer Altzeilen (sequence IS NULL) in allen historischen
   Payload-Formaten (13/14/15 Felder, '|'), mit rekonstruiertem Vorgaenger.
3. Admin-Endpoint GET /admin/system/audit-log/verify: Rollen (super_admin;
   admin nur ohne strict_tenant_isolation), Antwort ohne Inhalte.
4. Startpruefung: CRITICAL bei Bruch, blockiert den Start nie.
"""
from __future__ import annotations

import hashlib
import inspect
import logging
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
import main  # noqa: E402
from database import Base, get_db  # noqa: E402
from main import app  # noqa: E402
from models.review import AuditLog  # noqa: E402
from services import audit as audit_service  # noqa: E402
from services.audit import (  # noqa: E402
    _audit_integrity_payload,
    _legacy_payload_variants,
    _verify_audit_chain_detail,
    audit_log_integrity_report,
    log,
    run_startup_audit_chain_check,
    verify_audit_chain,
    verify_audit_legacy_rows,
)
from services.auth import get_current_user  # noqa: E402

SECRET_MARKER = "Geheimer-Inhalt-7731"


@pytest.fixture()
def session_local(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'audit_verify.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    yield factory
    engine.dispose()


def _log_n(session_local, n: int, *, per_transaction: int = 1) -> None:
    written = 0
    while written < n:
        with session_local() as s:
            for _ in range(min(per_transaction, n - written)):
                written += 1
                log(s, user_id="u1", user_name=f"Berater {SECRET_MARKER}", table_name="clients",
                    record_id=f"c{written}", action="UPDATE", field_name="note",
                    old_value=SECRET_MARKER, new_value=f"{SECRET_MARKER}-{written}",
                    ip_address="198.51.100.9", tenant_id="tenant-a")
            s.commit()


def _sql(session_local, statement: str, **params) -> None:
    with session_local() as s:
        s.execute(text(statement), params)
        s.commit()


# ---------------------------------------------------------------------------
# 1. Sequenz-Kette
# ---------------------------------------------------------------------------

def test_intact_chain_reports_ok_with_counter(session_local):
    _log_n(session_local, 6, per_transaction=3)
    with session_local() as s:
        result = _verify_audit_chain_detail(s)
        public = verify_audit_chain(s)
    assert public == {"ok": True, "checked": 6, "errors": []}, "oeffentlicher Vertrag bleibt"
    assert result["ok"], result["errors"]
    assert result["checked"] == 6
    assert result["last_sequence"] == 6
    assert result["counter_value"] == 6
    assert result["breaks"] == result["gaps"] == result["duplicates"] == result["hash_mismatches"] == []


def test_deleted_middle_row_reports_gap_and_break(session_local):
    _log_n(session_local, 5)
    _sql(session_local, "DELETE FROM audit_log WHERE sequence = 3")
    with session_local() as s:
        result = _verify_audit_chain_detail(s)
    assert not result["ok"]
    assert result["gaps"] == [{"from_sequence": 3, "to_sequence": 3}]
    assert result["breaks"] == [4]
    assert result["hash_mismatches"] == []


def test_truncated_tail_is_detected_via_counter(session_local):
    """Ohne Zaehlervergleich waere ein abgeschnittenes Kettenende unsichtbar:
    die verbleibenden Zeilen sind untereinander konsistent."""
    _log_n(session_local, 5)
    _sql(session_local, "DELETE FROM audit_log WHERE sequence >= 4")
    with session_local() as s:
        result = _verify_audit_chain_detail(s)
    assert not result["ok"]
    assert result["breaks"] == [] and result["hash_mismatches"] == []
    assert result["gaps"] == [{"from_sequence": 4, "to_sequence": 5}]
    assert result["counter_value"] == 5 and result["last_sequence"] == 3


def test_tampered_content_and_duplicate_are_reported(session_local):
    _log_n(session_local, 4)
    _sql(session_local, "UPDATE audit_log SET new_value = 'manipuliert' WHERE sequence = 2")
    with session_local() as s:
        row = s.query(AuditLog).filter(AuditLog.sequence == 4).one()
        s.add(AuditLog(
            id="dup-4", user_id=row.user_id, user_name=row.user_name, table_name=row.table_name,
            record_id=row.record_id, action=row.action, created_at=row.created_at,
            integrity_hash=row.integrity_hash, sequence=4, previous_hash=row.previous_hash,
        ))
        s.commit()
    with session_local() as s:
        result = _verify_audit_chain_detail(s)
    assert not result["ok"]
    assert result["hash_mismatches"][0] == 2
    assert 4 in result["duplicates"]


# ---------------------------------------------------------------------------
# 2. Altzeilen ohne sequence
# ---------------------------------------------------------------------------

def _legacy_fields(row_id, created_at, ip=None, tenant=None, new_value="v"):
    return dict(
        id=row_id, user_id="u0", user_name=f"Alt {SECRET_MARKER}", table_name="clients",
        record_id="c0", action="CREATE", field_name=None, old_value=None,
        new_value=new_value, mandate_id=None, client_id=None, created_at=created_at,
        ip_address=ip, tenant_id=tenant,
    )


def _insert_legacy(session_local, *, fields: dict, n_fields: int, previous_hash: str) -> str:
    """Schreibt eine Altzeile, gehasht im historischen Format mit n_fields
    Feldern ('|'), so wie log() sie damals geschrieben hat."""
    probe = SimpleNamespace(**fields)
    variants = _legacy_payload_variants(probe, previous_hash)
    payload = {13: variants[0], 14: variants[1], 15: variants[2]}[n_fields]
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    with session_local() as s:
        s.add(AuditLog(integrity_hash=digest, sequence=None, previous_hash=None, **fields))
        s.commit()
    return digest


def _legacy_history(session_local) -> list[str]:
    h1 = _insert_legacy(session_local, fields=_legacy_fields("L1", "2026-08-01T08:00:00.000Z"),
                        n_fields=13, previous_hash="")
    # unhashed Zeile dazwischen (vor dem Hash bzw. Alt-BACKFILL)
    with session_local() as s:
        s.add(AuditLog(id="L2", user_id="u0", user_name="Alt", table_name="asset_class_annual_returns",
                       record_id="2005-2024", action="BACKFILL", created_at="2026-08-01T09:00:00.000000"))
        s.commit()
    h3 = _insert_legacy(session_local, fields=_legacy_fields("L3", "2026-08-07T10:00:00.000Z",
                        ip="203.0.113.1"), n_fields=14, previous_hash="")
    h4 = _insert_legacy(session_local, fields=_legacy_fields("L4", "2026-08-09T10:00:00.000Z",
                        ip="203.0.113.1", tenant="tenant-a"), n_fields=15, previous_hash=h3)
    h5 = _insert_legacy(session_local, fields=_legacy_fields("L5", "2026-08-10T10:00:00.000Z",
                        tenant="tenant-a"), n_fields=15, previous_hash=h4)
    return [h1, h3, h4, h5]


def test_payload_variants_match_current_and_frozen_schemas():
    """Die 15-Felder-Varianten sind byte-gleich mit den Schreib-Funktionen
    (Unit-Separator = log() heute, '|' = eingefrorene Altfassung)."""
    fields = _legacy_fields("X", "2026-09-01T00:00:00.000Z", ip="1.2.3.4", tenant="t")
    probe = SimpleNamespace(**fields)
    variants = _legacy_payload_variants(probe, "abc")
    current = _audit_integrity_payload(
        entry_id="X", user_id="u0", user_name=fields["user_name"], table_name="clients",
        record_id="c0", action="CREATE", field_name=None, old_value=None, new_value="v",
        mandate_id=None, client_id=None, created_at=fields["created_at"], previous_hash="abc",
        ip_address="1.2.3.4", tenant_id="t",
    )
    assert variants[3] == current
    assert variants[2] == current.replace("\x1f", "|")
    assert variants[1] == variants[2][: variants[2].rfind("|")]
    assert variants[0] == variants[1][: variants[1].rfind("|")]


def test_legacy_rows_all_formats_verified(session_local):
    _legacy_history(session_local)
    _log_n(session_local, 2)  # neue Kette daneben stoert nicht
    with session_local() as s:
        result = verify_audit_legacy_rows(s)
    assert result["ok"], result
    assert result["total"] == 5 and result["hashed"] == 4 and result["unhashed"] == 1
    assert result["verified"] == 4
    assert result["link_unconfirmed"] == 0 and result["mismatches"] == 0


def test_legacy_row_tampering_is_detected(session_local):
    _legacy_history(session_local)
    _sql(session_local, "UPDATE audit_log SET new_value = 'manipuliert' WHERE id = 'L4'")
    with session_local() as s:
        result = verify_audit_legacy_rows(s)
    assert not result["ok"]
    assert result["mismatch_ids"] == ["L4"]


def test_removed_legacy_row_breaks_successor(session_local):
    """Entfernte Altzeile: der Nachfolger hat den Hash des entfernten
    Vorgaengers in seiner Payload -- er ist nicht mehr bestaetigbar und wird
    als Abweichung gemeldet (die Loeschung bleibt also sichtbar)."""
    _legacy_history(session_local)
    _sql(session_local, "DELETE FROM audit_log WHERE id = 'L4'")
    with session_local() as s:
        result = verify_audit_legacy_rows(s)
    assert not result["ok"]
    assert result["mismatch_ids"] == ["L5"]


def test_forked_legacy_row_is_link_unconfirmed_not_mismatch(session_local):
    """SEC-003-Gabelung: zwei Schreiber lasen denselben Vorgaenger (L3).
    L5 ist inhaltlich intakt, die Verkettung zu L4 aber nicht gegeben --
    Hinweis, kein Integritaetsfehler."""
    h1 = _insert_legacy(session_local, fields=_legacy_fields("L1", "2026-08-09T10:00:00.000Z"),
                        n_fields=15, previous_hash="")
    _insert_legacy(session_local, fields=_legacy_fields("L2", "2026-08-09T10:00:00.001Z"),
                   n_fields=15, previous_hash=h1)
    _insert_legacy(session_local, fields=_legacy_fields("L3", "2026-08-09T10:00:00.002Z"),
                   n_fields=15, previous_hash=h1)
    with session_local() as s:
        result = verify_audit_legacy_rows(s)
    assert result["ok"]
    assert result["verified"] == 2
    assert result["link_unconfirmed_ids"] == ["L3"]


# ---------------------------------------------------------------------------
# 3. Admin-Endpoint
# ---------------------------------------------------------------------------

def _client(session_local, role: str) -> TestClient:
    def override_get_db():
        db = session_local()
        try:
            yield db
        finally:
            db.close()

    user = SimpleNamespace(id=f"user-{role}", role=role, tenant_id="tenant-a",
                           full_name="X", email="x@example.test")
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


@pytest.fixture()
def tier1(monkeypatch):
    monkeypatch.setattr(config.settings, "strict_tenant_isolation", False, raising=False)
    monkeypatch.setattr(config.settings, "deployment_tier", "tier1", raising=False)
    monkeypatch.setattr(config.settings, "tenancy_mode", "single", raising=False)


@pytest.mark.parametrize("role", ["super_admin", "admin"])
def test_verify_endpoint_reports_without_contents(session_local, tier1, role):
    _legacy_history(session_local)
    _log_n(session_local, 4, per_transaction=2)
    try:
        resp = _client(session_local, role).get("/admin/system/audit-log/verify")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["chain"]["checked"] == 4 and body["chain"]["break_count"] == 0
    assert body["legacy"]["verified"] == 4
    # Keine Inhalte: weder Namen/Werte noch IPs noch Hashes.
    assert SECRET_MARKER not in resp.text
    assert "198.51.100.9" not in resp.text
    assert "integrity_hash" not in resp.text


def test_verify_endpoint_reports_breaks_and_gaps(session_local, tier1):
    _log_n(session_local, 5)
    _sql(session_local, "DELETE FROM audit_log WHERE sequence = 2")
    try:
        resp = _client(session_local, "super_admin").get("/admin/system/audit-log/verify")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    chain = resp.json()["chain"]
    assert resp.json()["ok"] is False
    assert chain["gaps"] == [{"from_sequence": 2, "to_sequence": 2}]
    assert chain["breaks"] == [3]


@pytest.mark.parametrize("role", ["advisor", "portfolio_management", "client"])
def test_verify_endpoint_rejects_non_admin_roles(session_local, tier1, role):
    try:
        resp = _client(session_local, role).get("/admin/system/audit-log/verify")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 403


def test_verify_endpoint_tenant_admin_rejected_in_multi_tenant(session_local, monkeypatch):
    """Die Kette ist global (alle Tenants). In einer mandantenfaehigen
    Installation bleibt die Pruefung dem super_admin vorbehalten."""
    monkeypatch.setattr(config.settings, "strict_tenant_isolation", True, raising=False)
    try:
        admin = _client(session_local, "admin").get("/admin/system/audit-log/verify")
        superadmin = _client(session_local, "super_admin").get("/admin/system/audit-log/verify")
    finally:
        app.dependency_overrides.clear()
    assert admin.status_code == 403
    assert superadmin.status_code == 200


# ---------------------------------------------------------------------------
# 4. Startpruefung
# ---------------------------------------------------------------------------

def test_startup_check_logs_critical_on_break_and_does_not_raise(session_local, caplog):
    _log_n(session_local, 3)
    _sql(session_local, "UPDATE audit_log SET old_value = 'x' WHERE sequence = 1")
    with caplog.at_level(logging.INFO, logger="services.audit"):
        report = run_startup_audit_chain_check(session_local)
    assert report is not None and report["ok"] is False
    critical = [r for r in caplog.records if r.levelno == logging.CRITICAL]
    assert len(critical) == 1
    assert "AUDIT-LOG-INTEGRITAET VERLETZT" in critical[0].getMessage()
    assert SECRET_MARKER not in critical[0].getMessage()


def test_startup_check_intact_logs_info_only(session_local, caplog):
    _log_n(session_local, 3)
    with caplog.at_level(logging.INFO, logger="services.audit"):
        report = run_startup_audit_chain_check(session_local)
    assert report["ok"] is True
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_startup_check_never_blocks_on_error(caplog):
    def broken_factory():
        raise RuntimeError("DB nicht erreichbar")

    with caplog.at_level(logging.WARNING, logger="services.audit"):
        assert run_startup_audit_chain_check(broken_factory) is None
    assert any("nicht durchfuehrbar" in r.getMessage() for r in caplog.records)


def test_startup_check_skips_above_row_limit(session_local, caplog):
    _log_n(session_local, 3)
    with caplog.at_level(logging.WARNING, logger="services.audit"):
        assert run_startup_audit_chain_check(session_local, max_rows=2) is None
    assert any("uebersprungen" in r.getMessage() for r in caplog.records)


def test_lifespan_runs_startup_check_after_init_db():
    source = inspect.getsource(main.lifespan)
    assert "run_startup_audit_chain_check()" in source
    assert source.index("init_db()") < source.index("run_startup_audit_chain_check()")
    assert main.run_startup_audit_chain_check is audit_service.run_startup_audit_chain_check


def test_report_equals_endpoint_contract(session_local):
    _log_n(session_local, 2)
    with session_local() as s:
        report = audit_log_integrity_report(s)
    from schemas.review import AuditChainVerification

    AuditChainVerification.model_validate(report)


# ---------------------------------------------------------------------------
# N-869-2 (Pruefrunde #869): Feldverschiebung, eingefuegte Fremdzeilen
# ---------------------------------------------------------------------------

def test_field_shift_ip_tenant_is_not_verified(session_local):
    """P1 aus #869: L4 (15-Felder-Hash) bekommt ip_address='ip|tenant' und
    tenant_id=NULL -- passt dann zur 14-Felder-Variante. Die Tenant-Zuordnung
    waere ohne Neuberechnung des Hashes entfernt; frueher 'verified'."""
    _legacy_history(session_local)
    _sql(session_local,
         "UPDATE audit_log SET ip_address = '203.0.113.1|tenant-a', tenant_id = NULL WHERE id = 'L4'")
    with session_local() as s:
        result = verify_audit_legacy_rows(s)
    assert not result["ok"]
    assert result["ambiguous_ids"] == ["L4"]
    assert result["verified"] == 3


def test_format_bound_to_introduction_date(session_local):
    """Eine 14-Felder-Zeile mit created_at VOR der Einfuehrung von
    ip_address (2026-08-07) kann es nicht geben -> nicht bestaetigt."""
    _insert_legacy(session_local, fields=_legacy_fields("E1", "2026-07-01T10:00:00.000Z",
                   ip="203.0.113.1"), n_fields=14, previous_hash="")
    with session_local() as s:
        result = verify_audit_legacy_rows(s)
    assert result["mismatch_ids"] == ["E1"]


def test_unknown_fields_must_be_empty_for_shorter_format(session_local):
    """13-Felder-Variante gilt nur, wenn ip_address und tenant_id leer sind:
    eine nachtraeglich gesetzte tenant_id wird nicht als bestaetigt gemeldet."""
    _insert_legacy(session_local, fields=_legacy_fields("F1", "2026-06-01T10:00:00.000Z"),
                   n_fields=13, previous_hash="")
    _sql(session_local, "UPDATE audit_log SET tenant_id = 'fremd' WHERE id = 'F1'")
    with session_local() as s:
        result = verify_audit_legacy_rows(s)
    assert result["mismatch_ids"] == ["F1"]


def test_pipe_inside_value_is_ambiguous_not_verified(session_local):
    """'|' in einem Feldwert: beim '|'-Format sind die Feldgrenzen nicht
    beweisbar (old_value='A|B', new_value='C' == 'A', 'B|C')."""
    fields = _legacy_fields("P1", "2026-08-09T10:00:00.000Z", tenant="tenant-a", new_value="B|C")
    fields["old_value"] = "A"
    _insert_legacy(session_local, fields=fields, n_fields=15, previous_hash="")
    with session_local() as s:
        result = verify_audit_legacy_rows(s)
    assert not result["ok"]
    assert result["ambiguous_ids"] == ["P1"]


def test_inserted_unhashed_row_between_hashed_rows_is_a_finding(session_local):
    """P3b aus #869: gefaelschte Zeile ohne Hash zwischen L4 und L5 -- war
    nur 'link_unconfirmed'/unhashed+1, ok=True. Jetzt Befund."""
    _legacy_history(session_local)
    with session_local() as s:
        s.add(AuditLog(id="FAKE", user_id="u9", user_name="X", table_name="clients", record_id="c1",
                       action="DELETE", created_at="2026-08-09T12:00:00.000Z"))
        s.commit()
    with session_local() as s:
        result = verify_audit_legacy_rows(s)
    assert not result["ok"]
    assert result["unexpected_unhashed_ids"] == ["FAKE"]


def test_known_legacy_unhashed_writers_are_only_counted(session_local):
    _legacy_history(session_local)  # enthaelt eine Alt-BACKFILL-Zeile
    with session_local() as s:
        s.add(AuditLog(id="PB1", user_id="u0", user_name="Alt", table_name="protocol_bausteine",
                       record_id="b1", action="CREATE", created_at="2026-08-20T10:00:00.000Z"))
        s.commit()
    with session_local() as s:
        result = verify_audit_legacy_rows(s)
    assert result["ok"], result
    assert result["unhashed"] == 2 and result["unexpected_unhashed"] == 0


def test_chain_pipe_fallback_rejects_pipe_in_values(session_local):
    """Ketten-Zeile: der Fallback auf das '|'-Schema gilt nur ohne '|' in den
    Feldwerten (sonst Feldgrenzen nicht beweisbar)."""
    _log_n(session_local, 1)
    with session_local() as s:
        row = s.query(AuditLog).one()
        fields = audit_service._payload_fields(row, "")
        fields[7], fields[8] = "A|B", "C"
        pipe_payload = "|".join(fields + [str(row.ip_address or ""), str(row.tenant_id or "")])
        forged = hashlib.sha256(pipe_payload.encode("utf-8")).hexdigest()
    _sql(session_local,
         "UPDATE audit_log SET old_value='A', new_value='B|C', integrity_hash=:h WHERE sequence=1",
         h=forged)
    with session_local() as s:
        result = _verify_audit_chain_detail(s)
    assert result["hash_mismatches"] == [1]
