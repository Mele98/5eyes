"""H10 Nachtrag 3: unabhaengige Pruefung 4b029f82 (Dok. 86 ab Z. 10563).

N-899-01 Offsite-Backup als Manifest-Kanal + Subprozess-Scan, N-899-02 Hosts
aus Einstellungen im Fassungs-Hash, N-899-03 alle Sperrgruende im Status,
N-899-05/06 Meldeentscheid endgueltig, kein Abschluss mit Risiko UNKNOWN,
N-899-07 geschaerfte Kundennamen-Pruefung, N-899-08 Socket-Connect-Schutz und
yfinance-Pin, N-899-09 Desktop-Update an Freigabe gebunden, Hinweise
(Zaehler, CLI-Export, FX-Datenstand). Werte sind Testwerte.
"""
from __future__ import annotations

import json
import re
import shutil
import socket
import subprocess
from datetime import datetime, timedelta, timezone
from importlib import metadata
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from services import egress_manifest as em
from services import privacy_versions as pv
from tests.h10_support import ADMIN_ID, CLIENT_ID, all_channel_states, api, reason

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
TARGET = "backup@nas.firma-a.example:/srv/ares"


@pytest.fixture(autouse=True)
def _guard_off():
    yield
    em.deactivate()
    em.update_channel_states(None)


def _install(monkeypatch, factory, **settings_values):
    import database
    from routers.privacy import install_egress_guard

    monkeypatch.setattr(database, "SessionLocal", factory)
    for key, value in settings_values.items():
        monkeypatch.setattr(f"config.settings.{key}", value)
    install_egress_guard()


# ── N-899-01 Offsite-Backup ───────────────────────────────────────────────────

def _offsite_values(client, host="nas.firma-a.example"):
    for key, value in (("target_host", host), ("destination_country", "TESTWERT CH"),
                       ("guarantee", "TESTWERT nur Schweiz"), ("legal_basis", "TESTWERT Auftragsbearbeitung"),
                       ("encryption", "TESTWERT SQLCipher + SSH")):
        assert client.put(f"/privacy/owner-fields/egress.operator.backup_offsite.{key}",
                          json={"value": value}).status_code == 200


def test_offsite_backup_runs_only_with_approved_channel(tmp_path, monkeypatch):
    from services import backup

    monkeypatch.setattr(backup.shutil, "which", lambda _name: "/usr/bin/rsync")
    archive = tmp_path / "a.db"
    archive.write_bytes(b"x")
    with api(tmp_path) as (client, _current, factory):
        _install(monkeypatch, factory, backup_offsite_enabled=True, backup_offsite_target=TARGET)
        result = backup.replicate_offsite(archive, TARGET)
        assert result.ok is False and "EGRESS_MANIFEST_MISSING" in result.detail
        status = client.get("/privacy/egress-status").json()
        assert any(c["channel_id"] == "operator.backup_offsite" for c in status["blocked_channels"])

        client.post("/privacy/egress-manifest/approve", json={})
        assert "EGRESS_GUARANTEE_MISSING" in backup.replicate_offsite(archive, TARGET).detail
        _offsite_values(client, host="anderer-host.example")
        client.post("/privacy/egress-manifest/approve", json={"keys": ["operator.backup_offsite"]})
        assert "EGRESS_DESTINATION_DENIED" in backup.replicate_offsite(archive, TARGET).detail
        _offsite_values(client)
        client.post("/privacy/egress-manifest/approve", json={"keys": ["operator.backup_offsite"]})
        allowed = backup.replicate_offsite(archive, TARGET)
        assert "EGRESS_" not in allowed.detail  # Schutz passiert, rsync fehlt in der Testumgebung
        assert "EGRESS_DESTINATION_DENIED" in backup.replicate_offsite(archive, "x@fremd.example:/a").detail


def test_unbound_network_tool_is_blocked():
    em.activate(SimpleNamespace(), channel_states=all_channel_states(em.load_manifest()))
    with pytest.raises(em.EgressBlocked) as blocked:
        subprocess.run(["curl", "https://tracker.example/x"], check=False)
    assert blocked.value.reason_code == "EGRESS_DESTINATION_DENIED"


_SUBPROCESS_CALL = re.compile(r"subprocess\.(?:run|Popen|call|check_call|check_output)\(|os\.system\(|os\.popen\(")


def test_every_network_tool_subprocess_is_bound_to_a_manifest_channel():
    manifest = em.load_manifest()
    bound = {ref for c in manifest["channels"] if c.get("subprocess_tools") for ref in c["code_references"]}
    offenders = []
    skip = {"tests", "alembic", "migrations", "scripts", "venv", ".venv", "node_modules"}
    for path in BACKEND.rglob("*.py"):
        if path.relative_to(BACKEND).parts[0] in skip:
            continue
        text_ = path.read_text(encoding="utf-8", errors="ignore")
        if not _SUBPROCESS_CALL.search(text_):
            continue
        tools = {t for t in em.NETWORK_TOOLS if re.search(rf"[\"'\s]{t}[\"'\s]", text_)}
        if tools and path.relative_to(REPO).as_posix() not in bound:
            offenders.append((path.relative_to(REPO).as_posix(), sorted(tools)))
    assert offenders == []


# ── N-899-02 Hosts im Fassungs-Hash ───────────────────────────────────────────

@pytest.mark.parametrize(("channel", "setting", "first", "second"), [
    ("mail.smtp", "smtp_host", "smtp.a.example", "smtp.b.example"),
    ("telemetry.error_reporting", "telemetry_dsn", "https://k@a.example/1", "https://k@b.example/1"),
    ("alerting.market_data_webhook", "market_data_alert_webhook_url", "https://a.example/h", "https://b.example/h"),
    ("operator.database", "database_url", "postgresql://u@db-a.example/x", "postgresql://u@db-b.example/x"),
    ("operator.backup_offsite", "backup_offsite_target", "u@a.example:/x", "u@b.example:/x"),
])
def test_host_change_invalidates_the_approved_version(channel, setting, first, second):
    a = pv.channel_contents({}, SimpleNamespace(**{setting: first}))[channel]
    b = pv.channel_contents({}, SimpleNamespace(**{setting: second}))[channel]
    assert a["configured_hosts"] != b["configured_hosts"]
    assert pv._content_hash(a) != pv._content_hash(b)


def test_desktop_update_url_is_part_of_the_hash(monkeypatch, tmp_path):
    package = tmp_path / "package.json"
    package.write_text(json.dumps({"desktopUpdates": {"enabled": True, "feedUrl": "https://updates.a.example/x"}}))
    monkeypatch.setattr(pv, "DESKTOP_PACKAGE_JSON", package)
    first = pv.channel_contents({})["updates.desktop"]
    package.write_text(json.dumps({"desktopUpdates": {"enabled": True, "feedUrl": "https://updates.b.example/x"}}))
    second = pv.channel_contents({})["updates.desktop"]
    assert first["configured_hosts"] == ["updates.a.example"] and pv._content_hash(first) != pv._content_hash(second)


def test_runtime_blocks_after_smtp_host_change(tmp_path, monkeypatch):
    with api(tmp_path) as (client, _current, factory):
        _install(monkeypatch, factory, smtp_enabled=True, smtp_host="smtp.a.example")
        for key in ("destination_country", "guarantee", "legal_basis"):
            client.put(f"/privacy/owner-fields/egress.mail.smtp.{key}", json={"value": f"TESTWERT {key}"})
        client.post("/privacy/egress-manifest/approve", json={})
        assert em.check_host("smtp.a.example")["id"] == "mail.smtp"
        monkeypatch.setattr("config.settings.smtp_host", "smtp.b.example")
        with factory() as s:
            from services import dsg_governance
            dsg_governance.refresh_egress_confirmations(s, "main")
        with pytest.raises(em.EgressBlocked) as blocked:
            em.check_host("smtp.b.example")
        assert blocked.value.reason_code == "EGRESS_HASH_MISMATCH"


# ── N-899-03 alle Sperrgruende im Status ──────────────────────────────────────

def test_status_lists_every_blocked_channel_with_reason(tmp_path, monkeypatch):
    with api(tmp_path) as (client, _current, factory):
        monkeypatch.setattr("config.settings.smtp_enabled", True)
        monkeypatch.setattr("config.settings.smtp_host", "smtp.a.example")
        client.post("/privacy/egress-manifest/approve", json={})
        status = client.get("/privacy/egress-status").json()
        smtp = next(c for c in status["blocked_channels"] if c["channel_id"] == "mail.smtp")
        assert smtp["reason_code"] == "EGRESS_GUARANTEE_MISSING" and status["approved"] is False
        assert "market_data.stooq" in status["approved_channels"]
        for key in ("destination_country", "guarantee"):
            client.put(f"/privacy/owner-fields/egress.mail.smtp.{key}", json={"value": "TESTWERT"})
        client.post("/privacy/egress-manifest/approve", json={})
        smtp = next(c for c in client.get("/privacy/egress-status").json()["blocked_channels"]
                    if c["channel_id"] == "mail.smtp")
        assert smtp["reason_code"] == "EGRESS_CONSENT_OR_BASIS_MISSING" and "Grundlage" in smtp["reason"]


def test_status_shows_fx_data_as_of_and_default_rates(tmp_path):
    with api(tmp_path) as (client, _current, _factory):
        asof = client.get("/privacy/egress-status").json()["data_as_of"]
        assert asof["fx_default_currencies"] and asof["fx_message"].startswith("Ersatzkurs – nicht aktuell")


# ── N-899-05/06 Vorfaelle ─────────────────────────────────────────────────────

def _incident(client):
    client.put("/privacy/owner-fields/incident.escalation_contact", json={"value": "TESTWERT"})
    return client.post("/privacy/incidents", json={
        "discovered_at": (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "incident_type": "CONFIDENTIALITY", "description": "Testvorfall"}).json()["id"]


def test_notify_is_final_live_path_high_notify_low_not_required_close(tmp_path):
    with api(tmp_path) as (client, _current, _factory):
        iid = _incident(client)
        client.post(f"/privacy/incidents/{iid}/assessment", json={"risk_level": "HIGH", "rationale": "r"})
        assert client.post(f"/privacy/incidents/{iid}/notification-decision",
                           json={"decision": "NOTIFY"}).status_code == 200
        lowered = client.post(f"/privacy/incidents/{iid}/assessment", json={"risk_level": "LOW", "rationale": "neu"})
        assert lowered.json()["notification_decision"] == "NOTIFY"
        flip = client.post(f"/privacy/incidents/{iid}/notification-decision",
                           json={"decision": "NOT_REQUIRED", "reason": "x"})
        assert flip.status_code == 409 and reason(flip) == "INCIDENT_NOTIFICATION_DECISION_FINAL"
        note = client.post(f"/privacy/incidents/{iid}/notification-note", json={"note": "Risiko neu bewertet"})
        assert note.status_code == 200 and note.json()["notification_decision"] == "NOTIFY"
        assert [e["event_type"] for e in note.json()["events"]][-1] == "notification_note"
        client.post(f"/privacy/incidents/{iid}/subject-notification-decision",
                    json={"decision": "NOT_REQUIRED", "reason": "r"})
        client.post(f"/privacy/incidents/{iid}/remediation", json={"note": "erledigt"})
        assert client.post(f"/privacy/incidents/{iid}/close", json={"note": "x"}).status_code == 409
        client.post(f"/privacy/incidents/{iid}/edoeb-notification", json={
            "notified_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "reference": "Quittung"})
        no_receipt = client.post(f"/privacy/incidents/{iid}/close", json={"note": "x"})
        assert no_receipt.status_code == 409
        assert "EDOEB-Meldenachweis als Artefakt mit Hash fehlt" in no_receipt.json()["detail"]["problems"]
        client.post(f"/privacy/incidents/{iid}/evidence", json={
            "kind": "EDOEB_RECEIPT", "reference": "Quittung", "sha256": "a" * 64, "media_type": "application/pdf",
            "size_bytes": 10})
        assert client.post(f"/privacy/incidents/{iid}/close", json={"note": "x"}).status_code == 200


def test_close_with_unknown_risk_is_forbidden(tmp_path):
    with api(tmp_path) as (client, _current, _factory):
        iid = _incident(client)
        client.post(f"/privacy/incidents/{iid}/assessment", json={"risk_level": "UNKNOWN", "rationale": "r"})
        client.post(f"/privacy/incidents/{iid}/remediation", json={"note": "x"})
        closed = client.post(f"/privacy/incidents/{iid}/close", json={"note": "x"})
        assert closed.status_code == 409 and reason(closed) == "INCIDENT_RISK_UNKNOWN_AT_CLOSE"


# ── N-899-07 Kundennamen ──────────────────────────────────────────────────────

@pytest.fixture
def names():
    em.activate(SimpleNamespace(eodhd_api_key="T", alphavantage_api_key="T"),
                channel_states=all_channel_states(em.load_manifest()),
                client_name_provider=lambda: ["Erika Beispiel", "Hans Müller", "Li Wu", "Anna Gold", "Jörg Strauß"])


@pytest.mark.parametrize("term", [
    "Erika Beispiel", "ErikaBeispiel", "E. Beispiel", "E Beispiel", "Beispiel", "Hans Mueller", "Hans Muller",
    "HansMueller", "Mueller", "Li Wu", "Wu Li", "Joerg Strauss", "Strauss", "Anna Gold", "A. Gold",
])
def test_name_variants_are_blocked(names, term):
    assert em._client_name_hit(term), term


@pytest.mark.parametrize("term", ["iShares Core SPI", "Gold ETF", "Vanguard FTSE All-World", "Erika", "Wu",
                                  "UBS ETF MSCI World", "Swiss Gold Fund"])
def test_product_terms_are_not_blocked(names, term):
    assert not em._client_name_hit(term), term


def test_alphavantage_keywords_are_screened(names):
    from tests.test_h10_c_dsg_03_egress_manifest import _raw_request

    assert _raw_request("www.alphavantage.co", "/query?function=SYMBOL_SEARCH&keywords=Nestle&apikey=T")
    with pytest.raises(em.EgressBlocked) as blocked:
        _raw_request("www.alphavantage.co", "/query?function=SYMBOL_SEARCH&keywords=Hans%20Mueller&apikey=T")
    assert blocked.value.reason_code == "EGRESS_CLIENT_NAME_DENIED"


# ── N-899-08 Socket-Ebene und yfinance-Pin ────────────────────────────────────

def test_direct_socket_connect_to_non_manifest_address_is_blocked():
    em.activate(SimpleNamespace(), channel_states=all_channel_states(em.load_manifest()))
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.2)
    try:
        with pytest.raises(em.EgressBlocked) as blocked:
            sock.connect(("203.0.113.7", 443))
        assert blocked.value.reason_code == "EGRESS_DESTINATION_DENIED"
        with pytest.raises(em.EgressBlocked):
            socket.create_connection(("tracker.unlisted.invalid", 80), timeout=0.2)
        em._STATE.resolved["203.0.113.8"] = 1e18  # zuvor fuer einen erlaubten Host aufgeloest
        em.check_connect(("203.0.113.8", 443))
        em.check_connect(("127.0.0.1", 9))
    finally:
        sock.close()


def test_yfinance_pin_has_no_curl_cffi():
    requirements = (BACKEND / "requirements.txt").read_text(encoding="utf-8")
    pin = re.search(r"^yfinance==(\d+)\.(\d+)\.(\d+)\s*$", requirements, re.M)
    assert pin, "yfinance muss exakt gepinnt sein"
    assert tuple(int(x) for x in pin.groups()) <= (0, 2, 54), "Upgrade: curl_cffi umgeht den Socket-Schutz"
    assert "curl_cffi" not in requirements and "curl-cffi" not in requirements
    requires = metadata.requires("yfinance") or []
    assert not any(r.lower().startswith(("curl_cffi", "curl-cffi")) for r in requires)


# ── N-899-09 Desktop-Update ───────────────────────────────────────────────────

def test_desktop_update_gate_node_tests():
    if shutil.which("node") is None:
        pytest.skip("node fehlt")
    out = subprocess.run(["node", "--test", "tests/update-egress-gate.test.js"], cwd=str(REPO / "ares-desktop"),
                         capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert out.returncode == 0, out.stdout + out.stderr


# ── Hinweise: Zaehler, CLI-Export ─────────────────────────────────────────────

def test_allowed_transfers_are_counted_without_content(tmp_path, monkeypatch):
    from tests.test_h10_c_dsg_03_egress_manifest import _raw_request

    with api(tmp_path) as (client, _current, factory):
        _install(monkeypatch, factory)
        client.post("/privacy/egress-manifest/approve", json={})
        for _ in range(3):
            _raw_request("stooq.com", "/q/d/l/?s=spx&i=d")
        em.flush_events()
        counts = client.get("/privacy/egress-counts").json()
        assert {(c["channel_id"], c["allowed_count"]) for c in counts} == {("market_data.stooq", 3)}
        with factory() as s:
            columns = {r[1] for r in s.execute(text("PRAGMA table_info(privacy_egress_daily_counts)")).all()}
        assert columns == {"id", "tenant_id", "day", "channel_id", "allowed_count", "updated_at"}


def test_cli_export_needs_case_or_audited_emergency(tmp_path, capsys):
    from scripts.data_export import main

    with api(tmp_path) as (client, _current, factory):
        with pytest.raises(SystemExit):
            main(["--client-id", CLIENT_ID], session_factory=factory)
        with pytest.raises(SystemExit):
            main(["--emergency-admin", ADMIN_ID, "--client-id", CLIENT_ID], session_factory=factory)
        with pytest.raises(SystemExit):
            main(["--emergency-admin", "advisor-1", "--reason", "x", "--client-id", CLIENT_ID],
                 session_factory=factory)
        out = tmp_path / "x.json"
        assert main(["--emergency-admin", ADMIN_ID, "--reason", "Backend defekt (Testwert)", "--client-id",
                     CLIENT_ID, "--output", str(out)], session_factory=factory) == 0
        assert json.loads(out.read_text(encoding="utf-8"))["client_id"] == CLIENT_ID
        with factory() as s:
            audit = s.execute(text("SELECT field_name, new_value FROM audit_log WHERE action = 'EXPORT'")).all()
        assert audit and audit[-1][0] == "cli_emergency_export" and "Backend defekt" in audit[-1][1]

        case = client.post("/privacy/subject-requests", json={
            "client_id": CLIENT_ID, "request_type": "ACCESS", "received_at": "2026-11-12",
            "received_channel": "LETTER"}).json()
        from core.reason_codes import DomainError
        with pytest.raises(DomainError):
            main(["--subject-request-id", case["id"], "--actor-user-id", ADMIN_ID], session_factory=factory)


def test_alembic_revision_single_head_and_sqlite_roundtrip(tmp_path):
    from models.privacy import OutboundTransferDailyCount
    from tests.h10_support import assert_single_head_contains, assert_sqlite_upgrade_downgrade_upgrade

    assert_single_head_contains("f2a4c6e8b0d1", "e8f1b3c5a7d9")
    assert_sqlite_upgrade_downgrade_upgrade(tmp_path, "f2a4c6e8b0d1",
                                            {"privacy_egress_daily_counts": OutboundTransferDailyCount})
