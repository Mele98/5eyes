"""F6 (Codex-Entscheid Runde 3, 2026-11-07): Startgrenze der Audit-Kettenpruefung.

Entscheid: "200'000 darf nur synchrone Vollpruefung begrenzen. Siegelbildung
muss vor dem Return erfolgen; Vollpruefung chunked/hintergruendig mit
sichtbarem Status."

Vorher kehrte run_startup_audit_chain_check() ueber der Grenze VOR
ensure_legacy_seal() zurueck: weder Siegel noch Pruefung, nur eine WARNING.

Geprueft (Grenze per Konfiguration klein gesetzt):
1. Siegel wird ueber der Grenze vor dem Return gebildet (genau eines,
   verkettet); Status 'pending' (mode background) ist persistiert.
2. Die Hintergrundpruefung laeuft in Teilschritten, schreibt Fortschritt nach
   jedem Teilschritt, endet mit 'ok' und dem letzten erfolgreich geprueften
   Kopf; ihr Bericht ist gleich dem synchronen.
3. Bruch: CRITICAL wie im synchronen Pfad, Status 'broken' mit Befundzahl,
   integrity_confirmed False; Kettenende abgeschnitten ebenso.
4. Waehrend der Pruefung angehaengte Eintraege werden mitgeprueft.
5. pending/running/error/unknown gelten als nicht bestaetigt (Status-Endpoint
   und Compliance-Warnung, ohne Inhalte); Fehler -> 'error'.
6. Synchroner Pfad schreibt ebenfalls den Status.
"""
from __future__ import annotations

import json
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
from database import Base, get_db  # noqa: E402
from main import app  # noqa: E402
from models.review import AuditLog  # noqa: E402
from services import audit as audit_service  # noqa: E402
from services.audit import (  # noqa: E402
    LEGACY_SEAL_MARKER,
    audit_log_integrity_report,
    get_audit_verification_status,
    log,
    run_chunked_audit_verification,
    run_startup_audit_chain_check,
)
from services.auth import get_current_user  # noqa: E402
from services.maintenance import build_compliance_status  # noqa: E402

SECRET = "Geheimer-Inhalt-F6-5521"


@pytest.fixture()
def session_local(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'f6.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    yield factory
    engine.dispose()


@pytest.fixture()
def small_threshold(monkeypatch):
    """Grenze per Konfiguration klein: 3 synchron, Teilschritt 2."""
    monkeypatch.setattr(config.settings, "audit_startup_check_max_rows", 3)
    monkeypatch.setattr(config.settings, "audit_verify_chunk_size", 2)


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


def _seals(session_local) -> list[AuditLog]:
    with session_local() as s:
        return s.query(AuditLog).filter(AuditLog.field_name == LEGACY_SEAL_MARKER).all()


def _status(session_local) -> dict:
    with session_local() as s:
        return get_audit_verification_status(s)


def _counter(session_local) -> tuple[int, str]:
    with session_local() as s:
        return tuple(s.execute(text(
            "SELECT value, last_hash FROM audit_log_sequence_counter WHERE id = 'singleton'"
        )).one())


# ---------------------------------------------------------------------------
# 1. Siegel vor dem Return, Status pending
# ---------------------------------------------------------------------------

def test_seal_is_formed_before_return_above_threshold(session_local, small_threshold, caplog):
    _legacy_rows(session_local, 2)
    _log_n(session_local, 4)
    jobs: list = []
    with caplog.at_level(logging.INFO, logger="services.audit"):
        result = run_startup_audit_chain_check(session_local, background_runner=jobs.append)
    assert result is None, "ueber der Grenze kein synchroner Bericht"
    seals = _seals(session_local)
    assert len(seals) == 1, "Siegel muss VOR dem Schwellen-Return entstehen"
    assert seals[0].sequence == 5, "verkettet an den Kopf"
    assert len(jobs) == 1, "Vollpruefung an den Hintergrund uebergeben"
    status = _status(session_local)
    assert status["state"] == "pending"
    assert status["mode"] == "background"
    assert status["total_rows"] == 6 and status["threshold"] == 3
    assert status["integrity_confirmed"] is False
    assert any("Hintergrund" in r.getMessage() for r in caplog.records)


def test_threshold_default_comes_from_settings():
    assert config.settings.audit_startup_check_max_rows == 200_000
    assert config.Settings.model_fields["audit_startup_check_max_rows"].default == 200_000


def test_seal_above_threshold_is_written_only_once(session_local, small_threshold):
    _legacy_rows(session_local, 2)
    _log_n(session_local, 4)
    run_startup_audit_chain_check(session_local, background_runner=lambda job: None)
    run_startup_audit_chain_check(session_local, background_runner=lambda job: None)
    assert len(_seals(session_local)) == 1


# ---------------------------------------------------------------------------
# 2. Chunked Hintergrundpruefung
# ---------------------------------------------------------------------------

def test_background_run_is_chunked_persists_progress_and_ends_ok(
    session_local, small_threshold, monkeypatch
):
    _legacy_rows(session_local, 2)
    _log_n(session_local, 7)
    progress: list[tuple] = []
    original = audit_service._write_verification_status

    def spy(factory, **fields):
        if "verified_through_sequence" in fields:
            progress.append((fields.get("state"), fields["verified_through_sequence"], fields.get("checked")))
        return original(factory, **fields)

    monkeypatch.setattr(audit_service, "_write_verification_status", spy)
    run_startup_audit_chain_check(session_local, background_runner=lambda job: job())

    chunk_steps = [p for p in progress if p[0] is None]
    # 8 verkettete Zeilen (7 + Siegel), Teilschritt 2 -> 4 Teilschritte.
    assert [p[1] for p in chunk_steps] == [2, 4, 6, 8]
    assert [p[2] for p in chunk_steps] == [2, 4, 6, 8]
    status = _status(session_local)
    counter_value, counter_hash = _counter(session_local)
    assert status["state"] == "ok"
    assert status["integrity_confirmed"] is True
    assert status["mode"] == "background"
    assert status["target_sequence"] == counter_value == 8
    assert status["verified_through_sequence"] == 8
    assert status["last_ok_sequence"] == 8
    assert status["last_ok_hash"] == counter_hash
    assert status["finding_count"] == 0


def test_background_report_equals_sync_report(session_local, small_threshold):
    _legacy_rows(session_local, 3)
    _log_n(session_local, 5)
    run_startup_audit_chain_check(session_local, background_runner=lambda job: None)
    with session_local() as s:
        sync_report = audit_log_integrity_report(s)
    background = run_chunked_audit_verification(session_local, chunk_size=2)
    for report in (sync_report, background):
        report.pop("checked_at")
    assert background == sync_report


# ---------------------------------------------------------------------------
# 3. Bruch und abgeschnittenes Ende
# ---------------------------------------------------------------------------

def test_background_break_is_critical_and_status_broken(session_local, small_threshold, caplog):
    _log_n(session_local, 6)
    with session_local() as s:
        s.execute(text("UPDATE audit_log SET old_value = 'manipuliert' WHERE sequence = 3"))
        s.commit()
    with caplog.at_level(logging.INFO, logger="services.audit"):
        run_startup_audit_chain_check(session_local, background_runner=lambda job: job())
    critical = [r for r in caplog.records if r.levelno == logging.CRITICAL]
    assert len(critical) == 1
    assert "AUDIT-LOG-INTEGRITAET VERLETZT" in critical[0].getMessage()
    status = _status(session_local)
    assert status["state"] == "broken"
    assert status["integrity_confirmed"] is False
    assert status["findings"]["hash_mismatch_count"] == 1
    assert status["finding_count"] >= 1
    assert status["last_ok_sequence"] is None
    rendered = json.dumps(status) + " ".join(r.getMessage() for r in caplog.records)
    assert SECRET not in rendered


def test_background_detects_truncated_tail(session_local, small_threshold):
    _log_n(session_local, 6)
    with session_local() as s:
        s.execute(text("DELETE FROM audit_log WHERE sequence = 6"))
        s.commit()
    run_startup_audit_chain_check(session_local, background_runner=lambda job: job())
    status = _status(session_local)
    assert status["state"] == "broken"
    assert status["findings"]["gap_count"] == 1


def test_previous_ok_head_is_kept_when_later_run_breaks(session_local, small_threshold):
    _log_n(session_local, 5)
    run_startup_audit_chain_check(session_local, background_runner=lambda job: job())
    first = _status(session_local)
    assert first["state"] == "ok" and first["last_ok_sequence"] == 5
    with session_local() as s:
        s.execute(text("UPDATE audit_log SET new_value = 'x' WHERE sequence = 2"))
        s.commit()
    run_startup_audit_chain_check(session_local, background_runner=lambda job: job())
    second = _status(session_local)
    assert second["state"] == "broken"
    assert second["last_ok_sequence"] == 5 and second["last_ok_at"] == first["last_ok_at"]


# ---------------------------------------------------------------------------
# 4. Waehrend der Pruefung angehaengte Eintraege
# ---------------------------------------------------------------------------

def test_rows_appended_during_background_run_are_verified(session_local, monkeypatch):
    _log_n(session_local, 4)
    original = audit_service._chain_rows_after
    appended = {"done": False}

    def rows_after(db, after, limit):
        rows = original(db, after, limit)
        if after is not None and not appended["done"]:
            appended["done"] = True
            _log_n(session_local, 3, start=100)
        return rows

    monkeypatch.setattr(audit_service, "_chain_rows_after", rows_after)
    report = run_chunked_audit_verification(session_local, chunk_size=2)
    assert report["ok"], report
    assert report["chain"]["checked"] == 7
    status = _status(session_local)
    assert status["target_sequence"] == 4
    assert status["verified_through_sequence"] == 7


# ---------------------------------------------------------------------------
# 5. Sichtbarer Status: nicht bestaetigt bis 'ok'
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("state", ["pending", "running", "error", "unknown"])
def test_unconfirmed_states_warn_in_compliance(state):
    payload = build_compliance_status(audit_verification={
        "state": state, "integrity_confirmed": False, "checked": 10, "total_rows": 300_000,
    })
    assert payload["controls"]["audit_chain_integrity_confirmed"] is False
    assert payload["controls"]["audit_chain_verification_state"] == state
    assert any("Integritaet" in w and "nicht bestaetigt" in w for w in payload["warnings"])
    assert payload["status"] == "warning"


def test_broken_state_is_first_compliance_warning():
    payload = build_compliance_status(audit_verification={
        "state": "broken", "integrity_confirmed": False, "finding_count": 3,
    })
    assert payload["warnings"][0].startswith("Audit-Log-Integritaet verletzt (3 Befunde)")


def test_ok_state_adds_no_audit_warning():
    payload = build_compliance_status(audit_verification={"state": "ok", "integrity_confirmed": True})
    assert payload["controls"]["audit_chain_integrity_confirmed"] is True
    assert not any("Audit" in w for w in payload["warnings"])


def test_background_failure_sets_error_state(session_local, monkeypatch, caplog):
    _log_n(session_local, 3)

    def boom(db, after, limit):
        raise RuntimeError(SECRET)

    monkeypatch.setattr(audit_service, "_chain_rows_after", boom)
    with caplog.at_level(logging.WARNING, logger="services.audit"):
        assert run_chunked_audit_verification(session_local, chunk_size=2) is None
    status = _status(session_local)
    assert status["state"] == "error"
    assert status["error"] == "RuntimeError"
    assert status["integrity_confirmed"] is False
    assert SECRET not in json.dumps(status)


def test_status_without_row_is_unknown(session_local):
    status = _status(session_local)
    assert status["state"] == "unknown" and status["integrity_confirmed"] is False


def test_sync_path_records_ok_status(session_local):
    _log_n(session_local, 3)
    report = run_startup_audit_chain_check(session_local, max_rows=100)
    assert report["ok"]
    status = _status(session_local)
    assert status["state"] == "ok" and status["mode"] == "sync"
    assert status["last_ok_sequence"] == 3
    assert status["last_ok_hash"] == _counter(session_local)[1]


def test_sync_path_records_broken_status(session_local):
    _log_n(session_local, 3)
    with session_local() as s:
        s.execute(text("UPDATE audit_log SET old_value = 'x' WHERE sequence = 1"))
        s.commit()
    run_startup_audit_chain_check(session_local, max_rows=100)
    status = _status(session_local)
    assert status["state"] == "broken" and status["mode"] == "sync"


# ---------------------------------------------------------------------------
# Status-Endpoint
# ---------------------------------------------------------------------------

def _client(session_local, role: str, monkeypatch) -> TestClient:
    monkeypatch.setattr(config.settings, "strict_tenant_isolation", False, raising=False)

    def _db():
        db = session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id="u-admin", role=role, tenant_id=None, full_name="Admin", email="a@example.invalid",
        is_active=1,
    )
    return TestClient(app)


@pytest.fixture()
def clean_overrides():
    yield
    app.dependency_overrides.clear()


def test_status_endpoint_shows_progress_without_contents(
    session_local, small_threshold, monkeypatch, clean_overrides
):
    _legacy_rows(session_local, 2)
    _log_n(session_local, 4)
    run_startup_audit_chain_check(session_local, background_runner=lambda job: None)
    client = _client(session_local, "super_admin", monkeypatch)
    response = client.get("/admin/system/audit-log/verification-status")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "pending" and body["integrity_confirmed"] is False
    assert SECRET not in response.text


@pytest.mark.parametrize("role", ["advisor", "assistant", "viewer", "client"])
def test_status_endpoint_rejects_non_admin_roles(session_local, monkeypatch, clean_overrides, role):
    client = _client(session_local, role, monkeypatch)
    assert client.get("/admin/system/audit-log/verification-status").status_code == 403
