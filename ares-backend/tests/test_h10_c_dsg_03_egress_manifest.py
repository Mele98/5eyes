"""H10 C-DSG-03: zentrales, fail-closed Egress-Manifest mit Laufzeitschutz.

* Manifest vollstaendig und gueltig; Code-Suche: jede Netzwerk-Aufrufstelle
  und jeder Host-Literal des Backends ist einem Kanal zugeordnet.
* Laufzeitschutz: nicht im Manifest = blockiert (Namensaufloesung und
  HTTP-Request), lokal erlaubt, Feld-Allowlist, Personendaten-Muster,
  Kanaele mit Personendaten erst nach Bestaetigung, fehlendes Manifest sperrt
  alles. Payload-Tests ueber die echten Produktionspfade (urllib, requests)
  mit einer aufzeichnenden Socket-Attrappe, ohne Netzwerk.
* Telemetrie: nur Fehlerart und Programmstelle verlassen das System.
* Desktop: Update-Gate und Renderer-CSP passen zum Manifest.
"""
from __future__ import annotations

import http.client
import io
import json
import re
import socket
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from services import egress_manifest as em

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
MANDATE_UUID = "5d8c5f53-0f2e-4b0d-9a77-1c2b3d4e5f60"
CLIENT_EMAIL = "erika.beispiel@example.ch"


def _settings(**overrides):
    base = dict(
        alphavantage_api_key=None, twelvedata_api_key="TESTKEY", eodhd_api_key="TESTKEY", openfigi_api_key=None,
        smtp_enabled=False, smtp_host="", telemetry_enabled=True,
        telemetry_dsn="https://key@o1.errors.example-telemetry.test/1",
        market_data_alert_webhook_url="https://hooks.example-chat.test/T1", backup_alert_webhook_url="",
        database_url=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture
def guard():
    em.activate(_settings())
    try:
        yield
    finally:
        em.deactivate()
        em.update_confirmed_channels(())


class _FakeSocket:
    def __init__(self, sink: list, body: bytes = b"ok") -> None:
        self.sink = sink
        self._response = (
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n"
            + f"Content-Length: {len(body)}\r\n\r\n".encode() + body
        )

    def sendall(self, data):
        self.sink.append(bytes(data))

    def makefile(self, *_a, **_k):
        return io.BytesIO(self._response)

    def settimeout(self, _t):
        pass

    def gettimeout(self):
        return None

    def setsockopt(self, *_a):
        pass

    def close(self):
        pass

    def shutdown(self, *_a):
        pass


@pytest.fixture
def wire(monkeypatch):
    """Zeichnet die Bytes auf, die die echten HTTP-Stacks senden wuerden."""
    import urllib3.connection

    sink: list[bytes] = []
    state = {"body": b"[]"}

    def fake_connect(self):
        self.sock = _FakeSocket(sink, state["body"])

    for cls in (http.client.HTTPConnection, http.client.HTTPSConnection,
                urllib3.connection.HTTPConnection, urllib3.connection.HTTPSConnection):
        monkeypatch.setattr(cls, "connect", fake_connect)
    return SimpleNamespace(sink=sink, state=state, text=lambda: b"".join(sink).decode("latin-1"))


def _raw_request(host: str, target: str, body: bytes | None = None, method: str = "GET") -> list[bytes]:
    sink: list[bytes] = []
    conn = http.client.HTTPSConnection(host)
    conn.sock = _FakeSocket(sink)
    conn.request(method, target, body=body, headers={"Content-Type": "application/json"} if body else {})
    return sink


# ── Manifest und Code-Suche ───────────────────────────────────────────────────

def test_manifest_is_valid_and_has_required_classes_and_tokens():
    manifest = em.load_manifest()
    assert em.manifest_problems(manifest) == []
    classes = {c["class"] for c in manifest["channels"]}
    assert {"market_data", "updates", "telemetry", "mail", "reference_data"} <= classes
    for channel in manifest["channels"]:
        assert "destination_country" in channel and "guarantee" in channel, channel["id"]
        assert "value" not in channel["destination_country"], "Staat nie vorbelegt"


def test_manifest_gate_flags_broken_channels():
    manifest = em.load_manifest()
    broken = json.loads(json.dumps(manifest))
    yahoo = em.channel_by_id(broken, "market_data.yfinance")
    yahoo["allowed_fields"] = []
    smtp = em.channel_by_id(broken, "mail.smtp")
    smtp["guarantee"] = {"status": "NOT_REQUIRED", "reason": "x"}
    broken["channels"] = [c for c in broken["channels"] if c["class"] != "updates"]
    problems = em.manifest_problems(broken)
    assert any("market_data.yfinance: Kanal ohne Personendaten braucht allowed_fields" in p for p in problems)
    assert any("mail.smtp: Kanal mit Personendaten ohne sperrendes Garantie-Owner-Feld" in p for p in problems)
    assert "Pflichtklasse updates fehlt" in problems


_NETWORK_CALL = re.compile(
    r"\burlopen\(|\brequests\.(?:get|post|put|delete|request|Session)\(|\bself\._session\.(?:get|post)\("
    r"|\bsmtplib\.SMTP|\byf\.(?:Ticker|download)\(|\bsentry_sdk\.init\(|\bblpapi\.|\bhttpx\.(?:get|post|Client)\("
)
_URL_HOST = re.compile(r"https?://([A-Za-z0-9.\-]+)")
# Hosts, die nur in Texten/Doku vorkommen (keine Verbindung).
_DOCUMENTATION_HOSTS = {
    "www.bloomberg.com": "Installationshinweis im Bloomberg-Stub",
    "blpapi.bloomberg.com": "pip-Index im Installationshinweis (kein Abruf zur Laufzeit)",
    "help.yahoo.com": "Doku-Link zu Ticker-Suffixen",
    "www.sqlite.org": "Doku-Link",
    "www.bfs.admin.ch": "Quellenangabe Sterbetafeln (statische Daten im Repo)",
}


def _backend_sources():
    skip = {"tests", "alembic", "migrations", "scripts", "venv", ".venv", "node_modules"}
    for path in BACKEND.rglob("*.py"):
        rel = path.relative_to(BACKEND)
        if rel.parts[0] in skip:
            continue
        yield path, path.read_text(encoding="utf-8", errors="ignore")


def test_code_search_every_network_call_site_is_covered_by_the_manifest():
    manifest = em.load_manifest()
    covered = {ref for c in manifest["channels"] for ref in c["code_references"]}
    covered |= {ref for f in manifest["excluded_flows"] for ref in f["code_references"]}
    missing = []
    for path, text in _backend_sources():
        if _NETWORK_CALL.search(text):
            rel = path.relative_to(REPO).as_posix()
            if rel not in covered:
                missing.append(rel)
    assert missing == [], f"Netzwerk-Aufrufstellen ohne Kanal im Egress-Manifest: {missing}"


def test_code_search_every_host_literal_is_a_manifest_host_or_documentation():
    manifest = em.load_manifest()
    hosts = {h for c in manifest["channels"] for h in c.get("hosts") or []}
    unknown = set()
    for _path, text in _backend_sources():
        for host in _URL_HOST.findall(text):
            host = host.lower().rstrip(".")
            if host in hosts or host in _DOCUMENTATION_HOSTS or em.is_loopback(host):
                continue
            if host.endswith((".example", ".invalid", ".test")) or host in {"example.com", "evil.com"}:
                continue
            unknown.add(host)
    assert unknown == set(), f"Host-Literale ohne Kanal: {sorted(unknown)}"


def test_code_search_gate_detects_a_new_unlisted_call_site(tmp_path):
    text = "from urllib.request import urlopen\nurlopen('https://tracker.example-ads.com/x')\n"
    assert _NETWORK_CALL.search(text)
    assert _URL_HOST.findall(text) == ["tracker.example-ads.com"]


# ── Laufzeitschutz ────────────────────────────────────────────────────────────

def test_unlisted_host_is_blocked_at_name_resolution_and_loopback_is_allowed(guard):
    with pytest.raises(em.EgressBlocked) as blocked:
        socket.getaddrinfo("tracker.unlisted-host.invalid", 443)
    assert blocked.value.reason_code == "EGRESS_DESTINATION_DENIED"
    assert socket.getaddrinfo("localhost", 80)
    assert socket.getaddrinfo("127.0.0.1", 80)
    entry = em.recent_blocked()[-1]
    assert entry["host"] == "tracker.unlisted-host.invalid" and set(entry) == {"at", "reason_code", "channel", "host"}


def test_guard_is_inactive_without_activation():
    em.deactivate()
    assert em.is_active() is False
    sink = _raw_request("tracker.unlisted-host.invalid", f"/?id={MANDATE_UUID}")
    assert sink, "ohne Aktivierung greift der Schutz nicht (nur Test-Gegenprobe)"


def test_allowed_request_passes_and_minimised_fields_only(guard):
    sink = _raw_request("stooq.com", "/q/d/l/?s=spx&i=d&d1=20261101&d2=20261111")
    assert sink and sink[0].startswith(b"GET /q/d/l/?s=spx&i=d")


@pytest.mark.parametrize(("host", "target", "code"), [
    ("stooq.com", "/q/d/l/?s=spx&client_name=Erika+Beispiel", "EGRESS_FIELD_DENIED"),
    ("stooq.com", f"/q/d/l/?s={MANDATE_UUID}", "EGRESS_VALUE_REJECTED"),
    ("query2.finance.yahoo.com", f"/v8/finance/chart/{CLIENT_EMAIL}?range=1d", "EGRESS_VALUE_REJECTED"),
    ("stooq.com", "/q/d/l/?s=CH9300762011623852957", "EGRESS_VALUE_REJECTED"),
    ("stooq.com", "/q/d/l/?s=756.1234.5678.97", "EGRESS_VALUE_REJECTED"),
    ("www.justetf.com", "/en/etf-profile.html?isin=Erika", "EGRESS_VALUE_REJECTED"),
    ("eodhd.com", "/api/search/Erika%40example.ch?api_token=T&fmt=json", "EGRESS_PATH_REJECTED"),
    ("www.alphavantage.co", "/query?function=X&symbol=SPY", "EGRESS_CHANNEL_DISABLED"),
])
def test_requests_with_personal_data_or_unlisted_fields_are_blocked(guard, host, target, code):
    with pytest.raises(em.EgressBlocked) as blocked:
        _raw_request(host, target)
    assert blocked.value.reason_code == code


def test_json_body_fields_and_values_are_checked(guard):
    ok = json.dumps([{"idType": "ID_ISIN", "idValue": "CH0012345678"}]).encode()
    assert _raw_request("api.openfigi.com", "/v3/mapping", ok, "POST")
    for body, code in (
        ([{"idType": "TICKER", "idValue": MANDATE_UUID}], "EGRESS_VALUE_REJECTED"),
        ([{"idType": "ID_ISIN", "idValue": "CH0012345678", "client": "Erika"}], "EGRESS_FIELD_DENIED"),
    ):
        with pytest.raises(em.EgressBlocked) as blocked:
            _raw_request("api.openfigi.com", "/v3/mapping", json.dumps(body).encode(), "POST")
        assert blocked.value.reason_code == code


def test_opaque_provider_tokens_are_not_value_screened(guard):
    assert _raw_request("query1.finance.yahoo.com", f"/v8/finance/chart/%5ESSMI?range=1d&crumb={MANDATE_UUID}")


def test_personal_data_channel_needs_owner_confirmation(guard):
    with pytest.raises(em.EgressBlocked) as blocked:
        em.check_host("o1.errors.example-telemetry.test")
    assert blocked.value.reason_code == "EGRESS_GUARANTEE_MISSING"
    em.update_confirmed_channels({"telemetry.error_reporting"})
    assert em.check_host("o1.errors.example-telemetry.test")["id"] == "telemetry.error_reporting"


def test_missing_manifest_blocks_every_external_host(tmp_path):
    em.activate(_settings(), manifest_path=tmp_path / "missing.json")
    try:
        with pytest.raises(em.EgressBlocked) as blocked:
            em.check_host("stooq.com")
        assert blocked.value.reason_code == "EGRESS_MANIFEST_MISSING"
        assert em.check_host("127.0.0.1") is None
        assert em.runtime_status()["manifest_loaded"] is False
    finally:
        em.deactivate()
        em.activate(_settings())
        em.deactivate()


# ── Payload-Tests ueber echte Produktionspfade ────────────────────────────────

def test_stooq_provider_sends_only_symbol_and_dates(guard, wire):
    from services.market_data.providers.stooq_provider import StooqProvider

    wire.state["body"] = b"Date,Open,High,Low,Close,Volume\n2026-11-10,1,1,1,1,1\n"
    StooqProvider().get_history("SPY.US", date(2026, 11, 1), date(2026, 11, 11))
    request = wire.text()
    assert request.startswith("GET /q/d/l/?s=spy.us") and "Host: stooq.com" in request
    with pytest.raises(Exception):
        StooqProvider().get_history(MANDATE_UUID, date(2026, 11, 1), date(2026, 11, 11))


def test_openfigi_client_minimises_and_blocks_identifiers(guard, wire):
    from services.openfigi_client import preview_openfigi_mapping

    wire.state["body"] = b'[{"data": []}]'
    preview_openfigi_mapping(isin="CH0012345678")
    body = wire.sink[-1].split(b"\r\n\r\n", 1)[-1]
    assert json.loads(body) == [{"idType": "ID_ISIN", "idValue": "CH0012345678"}]
    count = len(wire.sink)
    with pytest.raises(RuntimeError):
        preview_openfigi_mapping(symbol=f"{MANDATE_UUID}")
    assert len(wire.sink) == count, "blockierter Request darf das System nicht verlassen"


def test_eodhd_search_blocks_personal_search_terms(guard, wire, monkeypatch):
    from config import settings
    from services import eodhd_client

    monkeypatch.setattr(settings, "eodhd_api_key", "TESTKEY")
    eodhd_client._search_eodhd("iShares Core SPI")
    assert "GET /api/search/iShares%20Core%20SPI?api_token=TESTKEY&fmt=json&limit=10" in wire.text()
    count = len(wire.sink)
    with pytest.raises(RuntimeError):
        eodhd_client._search_eodhd(CLIENT_EMAIL)
    assert len(wire.sink) == count


def test_alert_webhook_payload_without_personal_data(guard, wire):
    from services.market_data.notifier import build_alert_payload, post_alert

    result = SimpleNamespace(is_alert=True, symbol="SPY", diff_bps=120, median_close="510.2", n_providers=2)
    assert post_alert("https://hooks.example-chat.test/T1", build_alert_payload([result], "2026-11-10", 50))
    count = len(wire.sink)
    assert post_alert("https://hooks.example-chat.test/T1", {"text": f"Kunde {CLIENT_EMAIL}"}) is False
    assert post_alert("https://hooks.example-chat.test/T1", {"text": "x", "mandate_id": "M-1"}) is False
    assert len(wire.sink) == count
    assert post_alert("https://hooks.other-target.test/x", {"text": "x"}) is False


def test_requests_stack_never_sends_a_blocked_body(guard, wire):
    import requests

    with pytest.raises(requests.exceptions.ConnectionError):
        requests.post("https://api.openfigi.com/v3/mapping",
                      json=[{"idType": "TICKER", "idValue": MANDATE_UUID}], timeout=5)
    assert MANDATE_UUID not in wire.text()


def test_captured_bytes_never_contain_client_sentinels(guard, wire):
    from services.market_data.providers.stooq_provider import StooqProvider
    from services.openfigi_client import preview_openfigi_mapping

    wire.state["body"] = b"Date,Open,High,Low,Close,Volume\n"
    for symbol in ("SPY.US", "CSBGC.SW"):
        try:
            StooqProvider().get_history(symbol, date(2026, 11, 1), date(2026, 11, 11))
        except Exception:  # noqa: BLE001 - leere CSV ist hier egal
            pass
    wire.state["body"] = b'[{"data": []}]'
    preview_openfigi_mapping(isin="US0378331005")
    text = wire.text()
    for sentinel in ("Erika", "Beispiel", MANDATE_UUID, CLIENT_EMAIL, "123456.78"):
        assert sentinel not in text


# ── Telemetrie ────────────────────────────────────────────────────────────────

def test_telemetry_scrubber_keeps_only_error_type_and_location():
    from services.telemetry import REMOVED, _scrub_event

    event = {
        "event_id": "e1", "level": "error", "environment": "production", "message": f"Kunde {CLIENT_EMAIL}",
        "user": {"email": CLIENT_EMAIL}, "request": {"url": "/clients/x", "data": {"name": "Erika"}},
        "extra": {"mandate_id": MANDATE_UUID}, "breadcrumbs": {"values": [{"message": "Erika"}]},
        "exception": {"values": [{
            "type": "ValueError", "module": "builtins", "value": f"Erika Beispiel {MANDATE_UUID}",
            "stacktrace": {"frames": [{"filename": "services/x.py", "function": "f", "lineno": 3,
                                        "vars": {"client": "Erika"}, "context_line": "name = 'Erika'"}]},
        }]},
    }
    scrubbed = _scrub_event(event)
    text = json.dumps(scrubbed)
    for sentinel in ("Erika", MANDATE_UUID, CLIENT_EMAIL, "/clients/x"):
        assert sentinel not in text
    frame = scrubbed["exception"]["values"][0]["stacktrace"]["frames"][0]
    assert frame == {"filename": "services/x.py", "function": "f", "lineno": 3}
    assert scrubbed["exception"]["values"][0]["value"] == REMOVED and scrubbed["message"] == REMOVED


def test_telemetry_init_installs_scrubber(monkeypatch):
    import sys
    from unittest.mock import MagicMock

    from services import telemetry

    telemetry._reset_for_testing()
    monkeypatch.setattr("config.settings.telemetry_enabled", True)
    monkeypatch.setattr("config.settings.telemetry_dsn", "https://x@errors.example-telemetry.test/1")
    sentry = MagicMock()
    monkeypatch.setitem(sys.modules, "sentry_sdk", sentry)
    try:
        assert telemetry.configure_telemetry() is True
        kwargs = sentry.init.call_args.kwargs
        assert kwargs["before_send"] is telemetry._scrub_event
        assert kwargs["include_local_variables"] is False and kwargs["max_breadcrumbs"] == 0
    finally:
        telemetry._reset_for_testing()


# ── Desktop ───────────────────────────────────────────────────────────────────

def desktop_update_problems(package_json: dict, manifest: dict) -> list[str]:
    """Ein aktivierter Updater braucht einen Update-Host im Manifest."""
    updates = (package_json.get("desktopUpdates") or {})
    channel = em.channel_by_id(manifest, "updates.desktop") or {}
    if not updates.get("enabled"):
        return []
    feed = str(updates.get("feedUrl") or updates.get("url") or "")
    host = em._host_from_setting(feed)
    return [] if host and host in (channel.get("hosts") or []) else [f"Update-Host {host or '?'} nicht im Manifest"]


def test_desktop_updates_are_disabled_or_listed_in_the_manifest():
    package_json = json.loads((REPO / "ares-desktop" / "package.json").read_text(encoding="utf-8"))
    manifest = em.load_manifest()
    assert package_json["desktopUpdates"]["enabled"] is False
    assert desktop_update_problems(package_json, manifest) == []
    enabled = {"desktopUpdates": {"enabled": True, "feedUrl": "https://updates.firma-a.example/ares"}}
    assert desktop_update_problems(enabled, manifest) == ["Update-Host updates.firma-a.example nicht im Manifest"]


def test_renderer_csp_connects_only_to_the_local_backend():
    from tests.monolith_source import read_monolith_bundle

    html = read_monolith_bundle()
    csp = re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', html).group(1)
    connect = next(part for part in csp.split(";") if part.strip().startswith("connect-src")).split()[1:]
    for source in connect:
        host = re.sub(r"^[a-z]+://", "", source).split(":")[0]
        assert source == "'self'" or host in ("localhost", "127.0.0.1"), source


# ── Start und API ─────────────────────────────────────────────────────────────

def test_main_lifespan_installs_the_guard_after_init_db_and_removes_it_on_shutdown():
    source = (BACKEND / "main.py").read_text(encoding="utf-8")
    lifespan = source[source.index("async def lifespan"):source.index("app = FastAPI(")]
    assert lifespan.index("init_db()") < lifespan.index("install_egress_guard()") < lifespan.index(
        "start_price_scheduler()")
    assert "uninstall_egress_guard()" in lifespan[lifespan.index("finally:"):]


def test_install_reads_confirmations_from_the_database(tmp_path, monkeypatch):
    import database
    from routers.privacy import install_egress_guard, uninstall_egress_guard
    from tests.h10_support import api

    with api(tmp_path) as (client, _current, factory):
        for key in ("egress.telemetry.error_reporting.destination_country",
                    "egress.telemetry.error_reporting.guarantee"):
            assert client.put(f"/privacy/owner-fields/{key}", json={"value": f"TESTWERT {key}"}).status_code == 200
        monkeypatch.setattr(database, "SessionLocal", factory)
        install_egress_guard()
        try:
            assert em.is_active()
            status = {c["id"]: c for c in em.runtime_status()["channels"]}
            assert status["telemetry.error_reporting"]["owner_confirmed"] is True
            assert status["mail.smtp"]["owner_confirmed"] is False
        finally:
            uninstall_egress_guard()
            em.update_confirmed_channels(())
        assert em.is_active() is False


def test_egress_api_is_admin_only_and_shows_open_owner_fields(tmp_path):
    from tests.h10_support import api, user

    with api(tmp_path) as (client, current, _factory):
        body = client.get("/privacy/egress-manifest").json()
        assert body["available"] is True and body["problems"] == []
        smtp = next(c for c in body["manifest"]["channels"] if c["id"] == "mail.smtp")
        assert smtp["guarantee"]["status"] == "OPEN" and smtp["destination_country"]["value"] is None
        current["user"] = user("advisor-1", role="advisor")
        assert client.get("/privacy/egress-manifest").status_code == 403


def test_configured_personal_channel_blocks_customer_output_until_confirmed(tmp_path, monkeypatch):
    from config import settings
    from tests.h10_support import api, confirm_all_owner_fields, owner_test_value

    monkeypatch.setattr(settings, "smtp_enabled", True)
    monkeypatch.setattr(settings, "smtp_host", "smtp.mail-provider.example")
    with api(tmp_path) as (client, _current, _factory):
        for field in client.get("/privacy/owner-fields").json():
            if field["blocking"] == "customer_output":
                client.put(f"/privacy/owner-fields/{field['key']}", json={"value": owner_test_value(field)})
        view = client.get("/privacy/processing-register").json()
        assert {f["key"] for f in view["open_blocking_fields"]} == {
            "egress.mail.smtp.destination_country", "egress.mail.smtp.guarantee"}
        confirm_all_owner_fields(client)
        assert client.get("/privacy/processing-register").json()["customer_output_ready"] is True


def test_manifest_is_packaged_with_the_backend():
    script = (REPO / "ares-desktop" / "scripts" / "build-backend.js").read_text(encoding="utf-8")
    assert "'config/outbound_processing_manifest.json'" in script



def test_yahoo_consent_flow_passes_but_values_are_screened(guard):
    """Verhaltensprobe 9051: yfinance sendet im Einwilligungsablauf von Yahoo
    vorgegebene Felder (u. a. consentUUID); sie duerfen passieren, Personen-
    daten-Muster bleiben gesperrt, und die Kursabfrage selbst bleibt strikt."""
    body = b"agree=agree&agree=agree&consentUUID=default&sessionId=3_cc-session_" + MANDATE_UUID.encode()         + b"&csrfToken=abc&originalDoneUrl=https%3A%2F%2Ffinance.yahoo.com%2F&namespace=yahoo"
    assert _raw_request("consent.yahoo.com", "/v2/collectConsent?sessionId=3_cc-session_x&lang=de-CH", body, "POST")
    with pytest.raises(em.EgressBlocked) as blocked:
        _raw_request("consent.yahoo.com", "/v2/collectConsent", f"namespace={CLIENT_EMAIL}".encode(), "POST")
    assert blocked.value.reason_code == "EGRESS_VALUE_REJECTED"
    with pytest.raises(em.EgressBlocked) as blocked:
        _raw_request("query2.finance.yahoo.com", "/v8/finance/chart/SPY?range=1d&consentUUID=default")
    assert blocked.value.reason_code == "EGRESS_FIELD_DENIED"


def test_screen_only_policy_needs_reason_and_no_personal_data():
    manifest = em.load_manifest()
    broken = json.loads(json.dumps(manifest))
    consent = em.channel_by_id(broken, "market_data.yfinance_consent")
    consent["field_policy_reason"] = ""
    smtp = em.channel_by_id(broken, "mail.smtp")
    smtp["field_policy"] = "screen_values_only"
    smtp["field_policy_reason"] = "x"
    problems = em.manifest_problems(broken)
    assert "market_data.yfinance_consent: screen_values_only ohne Begruendung" in problems
    assert "mail.smtp: screen_values_only nur fuer Kanaele ohne Personendaten" in problems
