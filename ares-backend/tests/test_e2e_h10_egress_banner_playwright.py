"""H10 Nachtrag 2: Ende-zu-Ende in echtem Chromium gegen ein echtes Backend.

Frische Instanz (Wegwerf-DB/-HOME, Wegwerf-KEK, Scheduler aus) -> Banner
Klartext "Datenuebermittlung ... pausiert" sichtbar -> Admin klickt "Jetzt freigeben" ->
"Manifest freigeben" -> Hash-Uebersicht -> "Freigabe bestaetigen" -> Banner
weg -> der Marktdatenkanal ist laut Laufzeitschutz erlaubt.

Die Seite laeuft unter dem Mock-Ursprung ``http://ares.test``; Playwright
leitet ``/api/*`` an das lokale Backend weiter (kein externer Netzaufruf,
kein CORS). Geladen wird das Modul ``privacy-governance.js`` mit einer
schlanken API-Bruecke; der Anmeldefluss des Monolithen ist nicht Gegenstand.

Pflichtlauf im CI-Job "Frontend Reporting Tests" (ARES_REQUIRE_PLAYWRIGHT=1).
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
MODULE = BACKEND.parent / "ares-desktop" / "frontend" / "privacy-governance.js"


def _sync_api():
    if os.environ.get("ARES_REQUIRE_PLAYWRIGHT") == "1":
        import playwright.sync_api as sync_api
        return sync_api
    return pytest.importorskip("playwright.sync_api", reason="Playwright fehlt; Pflichtlauf im CI-Job "
                                                              "'Frontend Reporting Tests'")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _call(base: str, method: str, path: str, body=None, token: str | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method, headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


@pytest.fixture(scope="module")
def backend(tmp_path_factory):
    from cryptography.fernet import Fernet

    root = tmp_path_factory.mktemp("h10e2e")
    for name in ("home", "appdata", "localappdata"):
        (root / name).mkdir()
    port = _free_port()
    env = {**os.environ, "HOME": str(root / "home"), "USERPROFILE": str(root / "home"),
           "APPDATA": str(root / "appdata"), "LOCALAPPDATA": str(root / "localappdata"),
           "DB_PATH": str(root / "ares-e2e.db"), "TENANT_MASTER_KEK": Fernet.generate_key().decode(),
           "SECRET_KEY": "h10-e2e-wegwerf-secret-key-0123456789abcdef", "PRICE_SCHEDULER_ENABLED": "false",
           "BACKUP_SCHEDULER_ENABLED": "false", "DATABASE_URL": ""}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(port),
         "--log-level", "warning"], cwd=str(BACKEND), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(120):
            try:
                if _call(base, "GET", "/health")[0] == 200:
                    break
            except OSError:
                pass
            time.sleep(1)
        else:
            pytest.fail("Backend startet nicht")
        status, raw = _call(base, "POST", "/auth/bootstrap-admin", {
            "username": "e2eadmin", "password": "E2E-Passwort-2026!x", "full_name": "E2E Admin"})
        assert status == 201, raw
        yield {"base": base, "token": json.loads(raw)["access_token"]}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()


SHELL = """<!doctype html><html><head><meta charset="utf-8"></head><body>
<button id="asec-audit">Protokoll</button><div id="sec-audit"></div>
<script>
var TOKEN = %(token)s;
async function call(method, url, body){
  var r = await fetch('/api' + url, {method: method, headers: {'Content-Type': 'application/json',
    'Authorization': 'Bearer ' + TOKEN}, body: body === undefined ? undefined : JSON.stringify(body)});
  var data = await r.json();
  if (!r.ok) { var e = new Error((data.detail && (data.detail.message || data.detail)) || r.status); throw e; }
  return data;
}
var API = {get: function(u){ return call('GET', u); }, post: function(u, b){ return call('POST', u, b || {}); },
           put: function(u, b){ return call('PUT', u, b); }};
function adminShowSection(id){ var el = document.getElementById(id); if (el) el.style.display = 'block'; }
function escapeHtml(v){ return String(v == null ? '' : v).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
</script>
<script>%(module)s</script>
</body></html>"""


def test_fresh_instance_banner_then_approval_then_market_data_allowed(backend):
    sync_api = _sync_api()
    base, token = backend["base"], backend["token"]
    html = SHELL % {"token": json.dumps(token), "module": MODULE.read_text(encoding="utf-8")}

    def handle(route):
        url = route.request.url
        if url.startswith("http://ares.test/api/"):
            body = route.request.post_data
            status, raw = _call(base, route.request.method, url[len("http://ares.test/api"):],
                                json.loads(body) if body else None, token)
            route.fulfill(status=status, body=raw, headers={"Content-Type": "application/json"})
        elif url.startswith("http://ares.test/"):
            route.fulfill(status=200, body=html, headers={"Content-Type": "text/html; charset=utf-8"})
        else:
            route.abort()

    with sync_api.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.route("**/*", handle)
            page.goto("http://ares.test/app")
            banner = page.locator("#pg-egress-banner")
            banner.wait_for(state="visible", timeout=15000)
            text = banner.inner_text()
            assert "Die Datenübermittlung muss einmal freigegeben werden – Marktdaten" in text
            assert "bis dahin pausiert." in text
            assert "Datenstand Kurse" in text and "nicht aktualisiert" in text

            banner.get_by_role("button", name="Jetzt freigeben").click()
            page.get_by_role("button", name="Manifest freigeben").click()
            confirm = page.locator("#pg-approve-confirm")
            confirm.get_by_role("button", name="Freigabe bestätigen").wait_for(timeout=10000)
            assert "market_data.stooq" in confirm.inner_text()
            confirm.get_by_role("button", name="Freigabe bestätigen").click()
            page.wait_for_function("() => !document.getElementById('pg-egress-banner')", timeout=15000)
        finally:
            browser.close()

    status, raw = _call(base, "GET", "/privacy/egress-manifest", token=token)
    runtime = {c["id"]: c for c in json.loads(raw)["runtime"]["channels"]}
    assert status == 200 and runtime["market_data.stooq"]["allowed_now"] is True
    assert json.loads(_call(base, "GET", "/privacy/egress-status", token=token)[1])["approved"] is True


def test_ci_runs_this_test_with_playwright_required():
    workflow = (BACKEND.parent / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    assert "tests/test_e2e_h10_egress_banner_playwright.py" in workflow


@pytest.fixture(scope="module")
def full_app(tmp_path_factory):
    """Echte Haupt-App (/app/ares.html) mit Browser-Hosting, frische Instanz."""
    from cryptography.fernet import Fernet

    root = tmp_path_factory.mktemp("h10e2efull")
    for name in ("home", "appdata", "localappdata"):
        (root / name).mkdir()
    port = _free_port()
    env = {**os.environ, "HOME": str(root / "home"), "USERPROFILE": str(root / "home"),
           "APPDATA": str(root / "appdata"), "LOCALAPPDATA": str(root / "localappdata"),
           "DB_PATH": str(root / "ares-e2e-full.db"), "TENANT_MASTER_KEK": Fernet.generate_key().decode(),
           "SECRET_KEY": "h10-e2e-full-wegwerf-secret-key-0123456789ab", "PRICE_SCHEDULER_ENABLED": "false",
           "BACKUP_SCHEDULER_ENABLED": "false", "DATABASE_URL": "", "SERVE_MAIN_FRONTEND": "true"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(port),
         "--log-level", "warning"], cwd=str(BACKEND), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(120):
            try:
                if _call(base, "GET", "/health")[0] == 200:
                    break
            except OSError:
                pass
            time.sleep(1)
        else:
            pytest.fail("Backend startet nicht")
        status, raw = _call(base, "POST", "/auth/bootstrap-admin", {
            "username": "e2efull", "password": "E2E-Passwort-2026!x", "full_name": "E2E Full Admin"})
        assert status == 201, raw
        yield base
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_real_app_shows_banner_right_after_login(full_app):
    """N-899-04: echte /app/ares.html, echter Login ueber die Maske; das Banner
    ist direkt nach dem Login sichtbar (Hook auf initApp), externe Ressourcen
    werden blockiert."""
    sync_api = _sync_api()
    with sync_api.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.route("**/*", lambda route: route.continue_() if route.request.url.startswith(full_app)
                       else route.abort())
            page.goto(f"{full_app}/app/ares.html")
            page.locator("#login-username").wait_for(state="visible", timeout=30000)
            assert page.locator("#pg-egress-banner").count() == 0  # vor dem Login kein Banner
            page.fill("#login-username", "e2efull")
            page.fill("#login-password", "E2E-Passwort-2026!x")
            page.press("#login-password", "Enter")
            banner = page.locator("#pg-egress-banner")
            banner.wait_for(state="visible", timeout=8000)
            text_ = banner.inner_text()
            # N-899-16: Klartext sichtbar, technische Angaben nur aufgeklappt
            assert "Die Datenübermittlung muss einmal freigegeben werden – Marktdaten" in text_
            assert "bis dahin pausiert." in text_ and "Jetzt freigeben" in text_
            assert "market_data." not in text_ and "EGRESS_" not in text_
            # Aufklappen per DOM (sticky Banner: Klick wird von der App-Leiste ueberdeckt)
            banner.locator("details").evaluate("d => { d.open = true; }")
            details = banner.inner_text()
            assert "market_data.stooq" in details and "EGRESS_MANIFEST_MISSING" in details
        finally:
            browser.close()
