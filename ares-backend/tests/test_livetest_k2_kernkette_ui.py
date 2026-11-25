"""K2 Pflicht-Livetest (Dok. 115, Kernkette CH bis "Portfolio generieren").

Echter Ablauf: isolierter Backend-Prozess (Temp-DB/HOME/APPDATA/LOCALAPPDATA,
Wegwerf-KEK, freier Port), echte App ``/app/ares.html`` in Chromium, echter
Erst-Einrichtungs-Assistent, echter Login, echte Masken. Wo ein Zustand nur mit
viel Vorlauf erreichbar ist (Publikation, Umrechnung durch K1), bestimmt eine
Playwright-Route genau die Serverantwort, damit die UI-Logik geprueft wird.

* E2E-02/13: Erst-Einrichtung fragt bei Lizenz fuer einen Benutzer ausdruecklich
  (Ja -> single_person_firm=1, auditiert); Administration > Firma schaltet um
  (Gegenprobe zurueck auf 0); 409 der Plausibilisierung im Klartext; die
  Vier-Augen-Sperre nennt beide Wege und springt zur Firma; als Ein-Personen-
  Firma fragt sie die Begruendung ab.
* E2E-01: Position in USD ueber die Maske; Laden und Bearbeiten behalten USD;
  neue Position defaultet auf die Mandatswaehrung.
* E2E-04: fehlender Kurs -> sichtbare Sperre mit Waehrung und Ursache; Kurseditor
  aus der Sperre; danach rechnet die Strategie.
* E2E-05: gemischte Waehrungen -> keine Summen/Anteile ohne Umrechnung, klare
  Kennzeichnung; umgerechnete Serversumme wird gezeigt; reiner CHF-Kunde unveraendert.
* E2E-06/07/10/11/12/14/15/16/17/18: siehe einzelne Abschnitte.

Pflichtlauf im CI-Job "Frontend Reporting Tests" (``ARES_REQUIRE_PLAYWRIGHT=1``),
sonst sichtbarer Skip. Screenshots optional nach ``ARES_K2_SCREENSHOT_DIR``.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

import pytest

from product_evidence_test_support import provision_database
BACKEND = Path(__file__).resolve().parents[1]
USER, PWD = "k2.admin", "K2-Probe-Passwort-2026!x"
CLOSE = "document.querySelectorAll('.overlay.open').forEach(function(o){if(o.id!=='m-ui-dialog')o.classList.remove('open');})"


def _sync_api():
    if os.environ.get("ARES_REQUIRE_PLAYWRIGHT") == "1":
        import playwright.sync_api as sync_api  # Pflicht: ImportError ist rot

        return sync_api
    return pytest.importorskip("playwright.sync_api",
                               reason="Playwright fehlt; Pflichtlauf im CI-Job 'Frontend Reporting Tests' (K2)")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class _Api:
    def __init__(self, base: str):
        self.base, self.token = base, None

    def __call__(self, method, path, body=None):
        req = urllib.request.Request(self.base + path, method=method,
                                     data=None if body is None else json.dumps(body).encode())
        req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", "Bearer " + self.token)
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                return resp.status, json.loads(resp.read() or b"null")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()[:600]

    def login(self):
        status, body = self("POST", "/auth/login", {"username": USER, "password": PWD})
        if status == 401:  # Einzellauf ohne den Erst-Einrichtungs-Test
            self("POST", "/auth/bootstrap-admin", {"username": USER, "password": PWD, "full_name": "K2 Admin Fiktiv",
                                                  "company_name": "Probe AG Fiktiv", "home_jurisdiction": "CH"})
            status, body = self("POST", "/auth/login", {"username": USER, "password": PWD})
        assert status == 200, body
        self.token = body["access_token"]
        return self


class _ServerBase(str):
    """Basis-URL des Livetest-Servers samt Pfad seiner Wegwerf-Datenbank."""

    database = ""


@pytest.fixture(scope="module")
def server():
    _sync_api()
    from cryptography.fernet import Fernet

    tmp = Path(tempfile.mkdtemp(prefix="k2_kernkette_"))
    for sub in ("home", "appdata", "localappdata"):
        (tmp / sub).mkdir()
    port = int(os.environ.get("ARES_K2_PORT") or _free_port())
    env = {
        **os.environ,
        "HOME": str(tmp / "home"), "USERPROFILE": str(tmp / "home"),
        "APPDATA": str(tmp / "appdata"), "LOCALAPPDATA": str(tmp / "localappdata"),
        "DB_PATH": str(tmp / "k2.db"), "SECRET_KEY": "k2-kernkette-secret-key-0123456789abcdef",
        "SERVE_MAIN_FRONTEND": "1", "PRICE_SCHEDULER_ENABLED": "0", "BACKUP_SCHEDULER_ENABLED": "0",
        "MARKET_DATA_CACHE_PURGE_ENABLED": "0", "LOGIN_RATE_LIMIT_ENABLED": "0",
        "APP_ENV": "development", "TENANT_MASTER_KEK": Fernet.generate_key().decode(),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(BACKEND), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 180
        while time.time() < deadline:
            try:
                urllib.request.urlopen(base + "/", timeout=2)
                break
            except OSError:
                time.sleep(1)
        else:
            pytest.fail("Backend nicht gestartet")
        live = _ServerBase(base)
        live.database = env["DB_PATH"]
        yield live
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=30)
        for _ in range(40):
            shutil.rmtree(tmp, ignore_errors=True)
            if not tmp.exists():
                break
            time.sleep(0.5)


def _shot(page, name, selector=None):
    target = os.environ.get("ARES_K2_SCREENSHOT_DIR")
    if not target:
        return
    Path(target).mkdir(parents=True, exist_ok=True)
    path = str(Path(target) / name)
    if selector:
        page.locator(selector).first.screenshot(path=path)
    else:
        page.screenshot(path=path)


def _open(page, base, sync_api):
    page.goto(base + "/app/ares.html")
    try:
        page.wait_for_selector("#intro-screen .intro-skip:not([disabled])", timeout=20000)
        page.click("#intro-screen .intro-skip")
        page.wait_for_timeout(800)
    except sync_api.Error:
        pass
    page.evaluate("document.getElementById('intro-screen')&&document.getElementById('intro-screen').remove()")


def _login(page):
    page.fill("#login-username", USER)
    page.fill("#login-password", PWD)
    page.evaluate("document.getElementById('btn-login-submit').click()")
    page.wait_for_timeout(3500)
    page.evaluate(CLOSE)


def _dialog(page, timeout=15000):
    page.wait_for_selector("#m-ui-dialog.open", timeout=timeout)
    return page.evaluate("({title:document.getElementById('m-ui-dialog-title').textContent,"
                         "msg:document.getElementById('m-ui-dialog-msg').textContent,"
                         "ok:document.getElementById('m-ui-dialog-ok').textContent,"
                         "cancel:document.getElementById('m-ui-dialog-cancel').textContent})")


def _client(api: _Api, label: str, positions: list[dict], mandate_type="Anlageberatung"):
    from tests.risk_fixture_helpers import standard_risk_payload

    advisor_id = api("GET", "/auth/me")[1]["id"]
    stamp = f"{label}-{int(time.time() * 1000)}"
    status, client = api("POST", "/clients", {
        "client_number": f"K2-{stamp}", "first_name": label, "last_name": "Testkunde-Fiktiv",
        "advisor_id": advisor_id, "household_type": "Einzelperson", "date_of_birth": "1980-05-01"})
    assert status == 201, client
    status, mandate = api("POST", f"/clients/{client['id']}/mandates",
                          {"mandate_number": f"M-{stamp}", "mandate_type": mandate_type})
    assert status == 201, mandate
    assert api("POST", f"/mandates/{mandate['id']}/risk-assessments", standard_risk_payload())[0] == 201
    for pos in positions:
        status, body = api("POST", f"/clients/{client['id']}/wealth-positions", pos)
        assert status in (200, 201), body
    api("POST", f"/clients/{client['id']}/cashflows", {
        "cashflow_type": "Income", "label": "Erwerb (fiktiv)", "amount_rappen": 13000000, "currency": "CHF",
        "frequency": "jaehrlich", "nature": "wiederkehrend", "valid_from": "2026-12-01", "valid_until": "2045-05-31",
        "is_inflation_linked": False})
    api("POST", f"/clients/{client['id']}/cashflows", {
        "cashflow_type": "Expense", "label": "Lebenshaltung (fiktiv)", "amount_rappen": 7500000, "currency": "CHF",
        "frequency": "jaehrlich", "nature": "wiederkehrend", "valid_from": "2026-12-01", "valid_until": None,
        "is_inflation_linked": True})
    return client["id"], mandate["id"]


def _chf_depot(value_rappen=15000000):
    return {"label": "Depot CHF (fiktiv)", "position_type": "Depot", "assignment": "Beratungsvermögen",
            "current_value_rappen": value_rappen, "currency": "CHF", "depot_bank": "Testbank Fiktiv",
            "alloc_equities_bps": 6000, "alloc_bonds_bps": 3000, "alloc_liquidity_bps": 1000}


def _load(page, cid, pg):
    page.evaluate(CLOSE)
    page.evaluate(f"loadClientById('{cid}')")
    page.wait_for_timeout(2500)
    page.evaluate(CLOSE)
    page.evaluate(f"go('{pg}')")
    page.wait_for_timeout(2000)
    page.evaluate(CLOSE)


def test_k2_bootstrap_question_firm_switch_and_four_eyes(server):
    """E2E-02 / E2E-13."""
    sync_api = _sync_api()
    api = _Api(server)
    with sync_api.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        errors: list[str] = []
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            _open(page, server, sync_api)
            # E2E-17: vor dem Login keine fiktiven Platzhalterdaten.
            before_login = page.evaluate("""() => ({sidebar: document.getElementById('sbl').innerText,
              badge: !!document.getElementById('alert-count'),
              sdSub: document.querySelector('#page-sd .ph-s').textContent,
              asset: document.getElementById('asset-view').innerText,
              complete: document.getElementById('sd-completeness-label').textContent})""")
            _shot(page, "k2_e17_vor_login.png")
            # Erst-Einrichtung ueber die echte Maske.
            page.evaluate("showBootstrap()")
            page.fill("#bootstrap-company-name", "Probe AG Fiktiv")
            page.fill("#bootstrap-full-name", "K2 Admin Fiktiv")
            page.fill("#bootstrap-username", USER)
            page.fill("#bootstrap-password", PWD)
            page.fill("#bootstrap-password-confirm", PWD)
            page.click("#btn-bootstrap-submit")
            page.wait_for_selector("#m-firm-question", timeout=30000)
            question = page.evaluate("({title:document.getElementById('firmq-title').textContent,yes:document.getElementById('firmq-yes').textContent,no:document.getElementById('firmq-no').textContent,msg:document.getElementById('firmq-msg').textContent})")
            _shot(page, "k2_e02_ersteinrichtung_frage.png", "#m-firm-question .modal")
            page.click("#firmq-yes")
            page.wait_for_timeout(2500)
            api.login()
            after_yes = api("GET", "/tenants/me")[1]
            audit_status, audit = api("GET", "/admin/system/audit-log?limit=200")
            # Administration > Firma: ausschalten (Gegenprobe), Speichern mit Bestaetigung.
            page.evaluate(CLOSE)
            page.evaluate("()=>{openAdminFirmSection(true);}")
            page.wait_for_selector("#firm-single-person", timeout=15000)
            panel_checked = page.evaluate("document.getElementById('firm-single-person').checked")
            _shot(page, "k2_e02_admin_firma.png", "#sec-firm")
            page.uncheck("#firm-single-person")
            page.click("#btn-firm-save")
            confirm_off = _dialog(page)
            page.click("#m-ui-dialog-ok")
            page.wait_for_timeout(1500)
            after_off = api("GET", "/tenants/me")[1]
            # 409 der Plausibilisierung (H12) im Klartext; Schalter springt zurueck.
            def reject_put(route):
                if route.request.method == "PUT":
                    route.fulfill(status=409, content_type="application/json", body=json.dumps(
                        {"detail": "Es sind 2 aktive freigabeberechtigte Personen erfasst."}))
                else:
                    route.continue_()
            page.route("**/tenants/me", reject_put)
            page.check("#firm-single-person")
            page.click("#btn-firm-save")
            _dialog(page)
            page.click("#m-ui-dialog-ok")
            page.wait_for_timeout(1200)
            conflict = page.evaluate("({text:document.getElementById('firm-status').textContent,"
                                     "checked:document.getElementById('firm-single-person').checked})")
            _shot(page, "k2_e02_admin_firma_409.png", "#sec-firm")
            page.unroute("**/tenants/me")
            page.evaluate("cm('m-admin')")

            # Erst-Einrichtung, Gegenprobe "Nein" und Lizenz > 1 (Serverantwort per Route).
            puts: list[dict] = []
            tenant = {"max_users": 1, "single_person_firm": 0}

            def fake_tenant(route):
                if route.request.method == "PUT":
                    puts.append(json.loads(route.request.post_data or "{}"))
                    route.fulfill(status=200, content_type="application/json", body=json.dumps({**tenant, "id": "main"}))
                else:
                    route.fulfill(status=200, content_type="application/json", body=json.dumps({**tenant, "id": "main"}))
            page.route("**/tenants/me", fake_tenant)
            # N-915-08: Schliessen (X bzw. Esc) ist kein "Nein" -- nichts gespeichert, Frage bleibt offen.
            page.evaluate("()=>{window.__k2ask=askSinglePersonFirmAfterBootstrap();}")
            page.wait_for_selector("#m-firm-question", timeout=15000)
            page.click("#firmq-later")
            page.wait_for_timeout(800)
            answer_closed = page.evaluate("window.__k2ask")
            puts_after_close = len(puts)
            page.evaluate("()=>{window.__k2ask=askSinglePersonFirmAfterBootstrap();}")
            page.wait_for_selector("#m-firm-question", timeout=15000)
            page.keyboard.press("Escape")
            page.wait_for_timeout(800)
            answer_esc = page.evaluate("window.__k2ask")
            puts_after_esc = len(puts)
            page.evaluate("()=>{window.__k2ask=askSinglePersonFirmAfterBootstrap();}")
            page.wait_for_selector("#m-firm-question", timeout=15000)
            page.click("#firmq-no")
            page.wait_for_timeout(800)
            answer_no = page.evaluate("window.__k2ask")
            tenant["max_users"] = 3
            answer_multi = page.evaluate("askSinglePersonFirmAfterBootstrap()")
            dialog_multi = page.evaluate("!!document.getElementById('m-firm-question')")
            page.unroute("**/tenants/me")

            # Vier-Augen-Sperre beim Publizieren (Serverantworten per Route).
            cid, mid = _client(api, "Freigabe", [_chf_depot()])
            _load(page, cid, "al")
            state = {"mandate_id": mid, "target_allocation_id": "ta-k2", "publication_status": "DRAFT",
                     "validation_status": "VALID", "validation_hash": "0" * 64, "blocker_codes": [],
                     "can_publish": True, "already_published": False, "prepared_by": None,
                     "active_publication": {"status": "NONE"}}
            posts: list[dict] = []

            def publication(route):
                if route.request.method == "POST":
                    body = json.loads(route.request.post_data or "{}")
                    posts.append(body)
                    if body.get("single_approver_attestation"):
                        route.fulfill(status=201, content_type="application/json", body="{}")
                    else:
                        route.fulfill(status=409, content_type="application/json", body=json.dumps({"detail": {
                            "reason_code": "CCX_APPROVAL_BINDING_MISSING", "message": "Vier-Augen-Prinzip",
                            "blocker_codes": ["FOUR_EYES_REQUIRED"]}}))
                else:
                    route.fulfill(status=200, content_type="application/json", body=json.dumps(state))
            page.route("**/allocation-publication", publication)
            page.evaluate(f"allocationPublicationState={json.dumps(state)}")
            page.evaluate("()=>{publishAllocation();}")
            four_eyes = _dialog(page)
            _shot(page, "k2_e02_vier_augen_wege.png", "#m-ui-dialog-box")
            page.click("#m-ui-dialog-ok")
            page.wait_for_selector("#firm-single-person", timeout=15000)
            jumped = page.evaluate("getComputedStyle(document.getElementById('sec-firm')).display!=='none'"
                                   "&&document.getElementById('m-admin').classList.contains('open')")
            page.evaluate("cm('m-admin')")
            assert api("PUT", "/tenants/me", {"single_person_firm": True})[0] == 200
            page.evaluate(f"allocationPublicationState={json.dumps(state)}")
            page.evaluate("()=>{publishAllocation();}")
            single = _dialog(page)
            page.fill("#m-ui-dialog-input", "Ein-Personen-Firma, Freigabe dokumentiert im Probelauf.")
            page.click("#m-ui-dialog-ok")
            page.wait_for_timeout(1500)
            page.unroute("**/allocation-publication")
        finally:
            browser.close()

    assert "Lukas Meier" not in before_login["sidebar"] and "HH-001" not in before_login["sidebar"]
    assert before_login["badge"] is False
    assert before_login["sdSub"].strip() == "" and "Mueller-Weber" not in before_login["sdSub"]
    assert "UBS" not in before_login["asset"] and "1'850'000" not in before_login["asset"]
    assert before_login["complete"].strip() == ""
    assert question["title"] == "Arbeiten Sie allein?"
    assert question["yes"] == "Ja, Ein-Personen-Firma" and "Vier-Augen" in question["no"]
    assert "Schliessen Sie den Dialog, bleibt die Frage offen" in question["msg"] and "Attest" not in question["msg"]
    assert answer_closed is None and answer_esc is None and puts_after_close == 0 and puts_after_esc == 0
    assert after_yes["single_person_firm"] == 1, after_yes
    assert audit_status == 200, audit
    entries = audit["entries"]
    assert any(e.get("field_name") == "tenant.single_person_firm" and e.get("new_value") == "1" for e in entries), audit
    assert panel_checked is True
    assert "Vier-Augen" in confirm_off["title"]
    assert after_off["single_person_firm"] == 0, after_off
    assert conflict["checked"] is False and conflict["text"].startswith("Nicht möglich")
    assert "2 aktive freigabeberechtigte Personen" in conflict["text"]
    assert puts and puts[0] == {"single_person_firm": False} and answer_no is False
    assert answer_multi is None and dialog_multi is False and len(puts) == 1
    assert four_eyes["title"] == "Freigabe durch eine zweite Person nötig"
    assert "Admin" in four_eyes["msg"] and "Ein-Personen-Firma" in four_eyes["msg"]
    assert four_eyes["ok"] == "Zu Administration › Firma" and jumped is True
    assert single["title"].startswith("Einzelfreigabe")
    assert posts[-1].get("single_approver_attestation") is True
    assert len(posts[-1]["attestation_reason"]) >= 20
    assert not errors, errors


def test_k2_wealth_currency_fx_blocker_and_sums(server):
    """E2E-01 / E2E-04 / E2E-05."""
    sync_api = _sync_api()
    api = _Api(server).login()
    cid, mid = _client(api, "Bravo", [_chf_depot(), {
        "label": "Sparkonto (fiktiv)", "position_type": "Liquidität", "assignment": "Beratungsvermögen",
        "current_value_rappen": 4000000, "currency": "CHF", "liquidity_instrument": "Sparkonto"}],
        mandate_type="Vermögensverwaltung")
    cid_chf, _ = _client(api, "Alpha", [_chf_depot(30000000)])
    with sync_api.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        errors: list[str] = []
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            _open(page, server, sync_api)
            _login(page)
            _load(page, cid, "vg")
            # E2E-01: neue Position in USD.
            page.evaluate("om('m-aw')")
            page.wait_for_function("() => document.querySelector('#maw-currency option[value=\"USD\"]')", timeout=15000)
            default_ccy = page.evaluate("document.getElementById('maw-currency').value")
            page.select_option("#maw-currency", "USD")
            page.fill("#maw-depot-label", "Depot USD (fiktiv)")
            page.fill("#maw-depot-value", "100000")
            page.fill("#sc-akt", "100")
            labels = page.evaluate("Array.from(document.querySelectorAll('#aw-Depot .ccy')).map(e=>e.textContent)")
            _shot(page, "k2_e01_positionsmaske_usd.png", "#m-aw .modal")
            page.click("#btn-maw-save")
            page.wait_for_timeout(2500)
            page.evaluate(CLOSE)
            positions = api("GET", f"/clients/{cid}/wealth-positions")[1]
            usd = [p for p in positions if p["label"] == "Depot USD (fiktiv)"][0]
            # Bearbeiten: Waehrung bleibt USD (auch nach Reload).
            _open(page, server, sync_api)  # Reload; Sitzung bleibt ggf. bestehen
            page.wait_for_timeout(2500)
            if page.is_visible("#login-username"):
                _login(page)
            _load(page, cid, "vg")
            page.evaluate(f"openWealthPositionEditor('{usd['id']}')")
            page.wait_for_timeout(500)
            edit = page.evaluate("({ccy:document.getElementById('maw-currency').value,"
                                 "label:document.querySelector('#aw-Depot .ccy').textContent})")
            page.fill("#maw-depot-value", "110000")
            page.click("#btn-maw-save")
            page.wait_for_timeout(2500)
            page.evaluate(CLOSE)
            usd_after = api("GET", f"/clients/{cid}/wealth-positions/{usd['id']}")
            if usd_after[0] != 200:
                usd_after = (200, [p for p in api("GET", f"/clients/{cid}/wealth-positions")[1] if p["id"] == usd["id"]][0])
            # E2E-05: gemischte Waehrungen ohne Umrechnung -> gekennzeichnet, keine Anteile.
            page.wait_for_selector("[data-wealth-fx-notice]", timeout=15000)
            page.wait_for_function("() => !/geprüft …/.test(document.querySelector('[data-wealth-fx-notice]').textContent)", timeout=15000)
            mixed = page.evaluate("document.getElementById('asset-view').innerText")
            _shot(page, "k2_e05_vermoegen_gemischt.png", "#asset-view")
            # Umgerechnete Serversumme (Vertrag K1/CK-01) wird gezeigt -- per Route.
            converted = {"client_id": cid, "client_name": "Bravo", "client_classification": None,
                         "gross_wealth_rappen": 27800000, "liabilities_rappen": 0, "net_worth_rappen": 27800000,
                         "advisory_wealth_rappen": 27800000, "gross_wealth_chf": 278000.0, "liabilities_chf": 0.0,
                         "net_worth_chf": 278000.0, "advisory_wealth_chf": 278000.0, "amount_currency": "CHF",
                         "fx_basis_hash": "f" * 64, "valuation_as_of": "2026-11-19", "mandate_id": mid}
            seen_urls: list[str] = []

            def summary_ok(route):
                seen_urls.append(route.request.url)
                route.fulfill(status=200, content_type="application/json", body=json.dumps(converted))
            page.route("**/wealth-summary*", summary_ok)
            page.evaluate("resetWealthSummaryCache();renderWealthPositions(currentWealthPositions)")
            page.wait_for_function("() => !document.querySelector('[data-wealth-fx-notice]')", timeout=15000)
            conv_text = page.evaluate("document.getElementById('asset-view').innerText")
            _shot(page, "k2_e05_vermoegen_umgerechnet.png", "#asset-view")
            page.unroute("**/wealth-summary*")

            def summary_409(route):
                route.fulfill(status=409, content_type="application/json", body=json.dumps({"detail": {
                    "reason_code": "CCX_FX_BASIS_MISSING", "message": "kein Kurs", "currencies": ["USD"], "fx_status": "MISSING"}}))
            page.route("**/wealth-summary*", summary_409)
            page.evaluate("resetWealthSummaryCache();renderWealthPositions(currentWealthPositions)")
            page.wait_for_function("() => document.querySelector('[data-wealth-fx-notice]')&&/Kurs nicht belegt/.test(document.querySelector('[data-wealth-fx-notice]').textContent)", timeout=15000)
            blocked_text = page.evaluate("document.querySelector('[data-wealth-fx-notice]').textContent")
            page.unroute("**/wealth-summary*")
            # Vertrag K1 Stand 47bb7f5f: 200 ohne Betrag mit typisierter Sperre (abgelaufener Kurs).
            k1_blocked = {**converted, "amount_currency": None, "gross_wealth_rappen": None, "liabilities_rappen": None,
                          "net_worth_rappen": None, "advisory_wealth_rappen": None, "gross_wealth_chf": None,
                          "liabilities_chf": None, "net_worth_chf": None, "advisory_wealth_chf": None, "fx_basis_hash": None,
                          "amount_block_reason_code": "CCX_FX_BASIS_STALE", "amount_block_message": "Kurs abgelaufen",
                          "amount_block_currencies": ["USD"]}
            page.route("**/wealth-summary*", lambda route: route.fulfill(status=200, content_type="application/json",
                                                                           body=json.dumps(k1_blocked)))
            page.evaluate("resetWealthSummaryCache();renderWealthPositions(currentWealthPositions)")
            page.wait_for_function("() => document.querySelector('[data-wealth-fx-notice]')&&/abgelaufen/.test(document.querySelector('[data-wealth-fx-notice]').textContent)", timeout=15000)
            k1_text = page.evaluate("document.getElementById('asset-view').innerText")
            # N-913-03: KPI und Depot-Check zeigen bei gesperrter Summe nie 0/0 %, sondern die Ursache.
            page.evaluate(f"()=>refreshWealthUI('{cid}')")
            page.wait_for_timeout(1500)
            k1_kpi = page.evaluate("(function(){var k=document.getElementById('kpi-reinvermoegen');return {t:k.textContent,title:k.title};})()")
            page.route("**/depot-check", lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps({
                "total_advisory_wealth_rappen": None, "amount_block_reason_code": "CCX_FX_BASIS_MISSING",
                "amount_block_currencies": ["USD"], "amount_block_message": "kein Kurs", "buckets": {},
                "country_exposure_bps": {}, "sector_exposure_bps": {}, "currency_exposure_bps": {},
                "concentration_hhi": {}, "fund_characteristics": {}, "warnings": []})))
            page.route("**/backtest/stress-replays", lambda route: route.fulfill(status=404, content_type="application/json", body="{}"))
            page.evaluate("()=>{openDepotCheck();}")
            page.wait_for_function("() => !/Lädt/.test((document.getElementById('dc-status')||{}).textContent||'Lädt')", timeout=15000)
            k1_dc = page.evaluate("document.getElementById('dc-status').textContent")
            page.evaluate("cm('m-dc')")
            page.unroute("**/depot-check")
            page.unroute("**/backtest/stress-replays")
            page.unroute("**/wealth-summary*")
            # Gegenprobe: reiner CHF-Kunde zeigt Summen und Anteile wie bisher.
            _load(page, cid_chf, "vg")
            chf_text = page.evaluate("document.getElementById('asset-view').innerText")
            chf_derived = page.evaluate("({goal:goalEditorInitialRappen(),reason:wealthFxOpenReason(),snap:currentAllocationInputSnapshot().fxOpen})")
            # N-915-01/02: Review-Anteil, Ist-Pfad, Ist-Gewichte und Ziel-Vorbelegung des gemischten Kunden.
            _load(page, cid, "rv")
            mixed_derived = page.evaluate("""(function(){clearStrategySummaryForDirtyState();
              var t=buildCurrentWealthProjection('total');
              return {wealth:document.getElementById('sr-wealth').textContent,share:document.getElementById('sr-wealth-share').textContent,
                goal:goalEditorInitialRappen(),unavailable:!!t.unavailable,reason:istProjectionBasisUnavailableReason(),
                adv:wealthProjectionInputs('advisory').fxOpen,alloc:(typeof alloc!=='undefined'&&alloc[0])?alloc[0].n:null};})()""")
            _shot(page, "k2_n91501_review_gemischt.png", "#page-rv")
            # E2E-04: Kurs fehlt -> sichtbare Sperre, Kurseditor aus der Sperre.
            _load(page, cid, "al")
            page.evaluate("()=>{calculateInvestmentStrategy();}")
            page.wait_for_function("() => (function(){var b=document.getElementById('aa-calc-blocker');return b&&b.style.display!=='none'&&/USD/.test(b.textContent);})()", timeout=120000)
            page.evaluate(CLOSE)
            blocker = page.evaluate("(function(){var b=document.getElementById('aa-calc-blocker');var r=b.getBoundingClientRect();"
                                    "return {text:b.textContent,code:b.getAttribute('data-reason-code'),top:r.top,h:r.height,"
                                    "page:document.getElementById('page-al').classList.contains('active')};})()")
            _shot(page, "k2_e04_aa_kurs_fehlt.png")
            page.click("#btn-aa-fx-fix")
            page.wait_for_selector("#fxq-rate-USD", timeout=15000)
            fx_editor = page.evaluate("Array.from(document.querySelectorAll('#fxq-grid .fxq-input')).map(e=>e.getAttribute('data-currency'))")
            page.fill("#fxq-rate-USD", "0.8")
            page.check("#fxq-grid .fxq-confirm[data-currency='USD']")
            _shot(page, "k2_e04_kurseditor.png", "#m-fx-quick .modal")
            page.click("#btn-fxq-save")
            page.wait_for_function("() => /Gespeichert/.test(document.getElementById('fxq-status').textContent)", timeout=15000)
            rates = {r["currency"]: r for r in api("GET", "/fx-rates/current")[1]}
            blocker_after_save = page.evaluate("document.getElementById('aa-calc-blocker').style.display")
            page.evaluate("cm('m-fx-quick')")
            page.evaluate("()=>{calculateInvestmentStrategy();}")
            page.wait_for_function("() => !!(strategyState&&strategyState.allocation&&strategyState.allocation.target_allocation"
                                   "&&strategyState.allocation.target_allocation.id)", timeout=240000)
            page.wait_for_timeout(1500)
            page.evaluate(CLOSE)
            recalculated = page.evaluate("document.getElementById('aa-calc-blocker').style.display")
            _shot(page, "k2_e04_aa_nach_kurs.png")
            # N-915-10 / E2E-06: echter Publikationsstatus des Servers -> Wegweiser neben "Publizieren".
            page.evaluate("()=>refreshAllocationPublication(true)")
            page.wait_for_timeout(1500)
            real_pub = page.evaluate("""(function(){var s=allocationPublicationState||{};var l=document.getElementById('btn-aa-goto-finalize');
              return {codes:s.blocker_codes||[],chip:document.getElementById('aa-publication-status').textContent,
                link:!!(l&&l.offsetParent)};})()""")
            _shot(page, "k2_e06_aa_wegweiser_echt.png", "#page-al .ph")
            # N-915-10 / E2E-07: echtes Portfolio aus dem Seed-Katalog -> Musterprodukt-Warnung; N-915-11 aktiv.
            provision_database(server.database)  # C-COMP-02: synthetische Nachweise
            page.evaluate("go('po')")
            page.wait_for_timeout(1500)
            page.evaluate(CLOSE)
            page.evaluate("()=>{refreshPortfolioFromStoredState();}")
            page.wait_for_function("() => (document.getElementById('po-portfolio-sections')||{innerText:''}).innerText.indexOf('Musterprodukt')>=0", timeout=240000)
            page.wait_for_timeout(1000)
            page.evaluate(CLOSE)
            real_po = page.evaluate("""(function(){var w=document.getElementById('po-sample-warning');var b=document.getElementById('btn-po-finalize');
              var h=document.getElementById('po-finalize-hint');
              return {warn:w?w.textContent:'',visible:!!(w&&w.style.display!=='none'),rows:document.getElementById('po-portfolio-sections').innerText,
                positions:(strategyState.recommendation&&strategyState.recommendation.positions||[]).map(function(p){return [p.product_name,p.provider,p.isin||null];}),
                finalizeDisabled:!!(b&&b.disabled),hint:!!(h&&h.style.display!=='none')};})()""")
            _shot(page, "k2_e07_portfolio_echt.png")
        finally:
            browser.close()

    assert default_ccy == "CHF"
    assert labels and set(labels) == {"USD"}, labels
    assert usd["currency"] == "USD" and usd["current_value_rappen"] == 10000000
    assert edit == {"ccy": "USD", "label": "USD"}, edit
    assert usd_after[1]["currency"] == "USD" and usd_after[1]["current_value_rappen"] == 11000000
    assert "Positionen in mehreren Währungen (CHF, USD)" in mixed
    assert "Umrechnung offen" in mixed and "des Bruttovermögens" not in mixed and "—" not in mixed
    assert "USD 110'000" in mixed  # Position bleibt in ihrer Waehrung sichtbar
    assert seen_urls and all(f"mandate_id={mid}" in u for u in seen_urls)
    assert "CHF 278'000" in conv_text and "des Bruttovermögens" in conv_text and "Umrechnung offen" not in conv_text
    assert "Kurs nicht belegt: USD" in blocked_text
    assert "Kurs nicht belegt: USD (abgelaufen)" in k1_text and "Umrechnung offen" in k1_text
    assert "des Bruttovermögens" not in k1_text and "—" not in k1_text
    assert " 0 %" not in k1_text and "CHF 0" not in k1_text
    assert k1_kpi["t"] == "Umrechnung offen" and "Kurs USD abgelaufen" in k1_kpi["title"], k1_kpi
    assert "Umrechnung offen – Kurs USD fehlt oder nur Ersatzkurs" in k1_dc and "CHF 0" not in k1_dc, k1_dc
    assert "Umrechnung offen" not in chf_text and "des Bruttovermögens" in chf_text and "mehreren Währungen" not in chf_text
    assert mixed_derived["wealth"] == "Umrechnung offen" and "Kein Anteil" in mixed_derived["share"], mixed_derived
    assert "%" not in mixed_derived["share"] and mixed_derived["goal"] == 0, mixed_derived
    assert mixed_derived["unavailable"] is True and "mehreren Währungen (CHF, USD)" in mixed_derived["reason"], mixed_derived
    assert mixed_derived["adv"] is True and mixed_derived["alloc"] == "Umrechnung offen", mixed_derived
    assert chf_derived["goal"] > 0 and chf_derived["reason"] == "" and chf_derived["snap"] is False, chf_derived
    assert blocker["page"] and blocker["code"] == "CCX_FX_BASIS_MISSING"
    assert "Wechselkurs nicht belegt" in blocker["text"] and "USD (Ersatzkurs – nicht bestätigt)" in blocker["text"]
    assert blocker["h"] > 0
    assert fx_editor == ["USD"]
    assert rates["USD"]["source"] == "Manual" and abs(rates["USD"]["rate"] - 0.8) < 1e-9
    assert blocker_after_save == "none" and recalculated == "none"
    assert "CCX_ENVELOPE_MISSING" in real_pub["codes"] and real_pub["link"] is True, real_pub
    assert "Portfolio › Empfehlung finalisieren" in real_pub["chip"], real_pub
    assert real_po["positions"] and real_po["visible"], real_po
    assert all(name.startswith("Musterprodukt") or name.startswith(("Kontoguthaben", "Festgeld")) for name, _p, _i in real_po["positions"]), real_po
    assert "Musterkatalog – nicht zur Umsetzung" in real_po["warn"] and "Musterprodukt – nicht zur Umsetzung" in real_po["rows"]
    assert real_po["finalizeDisabled"] is False and real_po["hint"] is False, real_po
    assert not errors, errors


def test_k2_flow_guidance_without_dead_ends(server):
    """E2E-06/07/10/11/12/14/15/16/18."""
    sync_api = _sync_api()
    api = _Api(server).login()
    cid, mid = _client(api, "Charlie", [_chf_depot()])
    with sync_api.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        errors: list[str] = []
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            _open(page, server, sync_api)
            _login(page)
            _load(page, cid, "vg")
            steps = page.evaluate("Array.from(document.querySelectorAll('.tnav .tstep .sn')).map(e=>e.textContent)")
            # E2E-15: Punkte der Risikobereitschaft nach dem Laden.
            page.evaluate("go('rp')")
            page.wait_for_timeout(2500)
            rsub = page.evaluate("Array.from(document.querySelectorAll('.rsub')).map(e=>e.textContent)")
            # E2E-14: Pensionierungsjahr im Schritt Cashflows & Ziele.
            page.evaluate("go('cf')")
            page.wait_for_selector("#cf-retirement", state="visible", timeout=15000)
            ret_before = page.evaluate("document.getElementById('cf-retirement-text').textContent")
            page.fill("#cf-retirement-year", "2041")
            page.click("#btn-cf-retirement-save")
            page.wait_for_function("() => /Jahr 2041/.test(document.getElementById('cf-retirement-text').textContent)", timeout=15000)
            _shot(page, "k2_e14_pensionierung.png", "#cf-retirement")
            mandate_after = api("GET", f"/mandates/{mid}")[1]
            # E2E-06: sichtbarer Schritt "Empfehlung finalisieren" + Wegweiser neben "Publizieren".
            page.evaluate("go('po')")
            page.wait_for_timeout(1500)
            page.evaluate(CLOSE)
            finalize_btn = page.evaluate("(function(){var b=document.getElementById('btn-po-finalize');var h=document.getElementById('po-finalize-hint');return b&&{text:b.textContent,visible:!!b.offsetParent,disabled:b.disabled,hint:!!(h&&h.offsetParent),hintText:h?h.textContent:''};})()")
            _shot(page, "k2_e06_portfolio_finalisieren.png", "#page-po .ph")
            page.evaluate("go('al')")
            page.wait_for_timeout(1200)
            page.evaluate(CLOSE)
            shortcut = page.evaluate("(function(){var shown=syncFinalizeShortcut({publication_status:'DRAFT',blocker_codes:['CCX_ENVELOPE_MISSING']});"
                                     "var l=document.getElementById('btn-aa-goto-finalize');return {shown:shown,visible:!!(l&&l.offsetParent),"
                                     "reason:allocationPublicationReason('CCX_ENVELOPE_MISSING')};})()")
            _shot(page, "k2_e06_aa_wegweiser.png", "#page-al .ph")
            page.click("#btn-aa-goto-finalize")
            page.wait_for_timeout(1200)
            jumped_po = page.evaluate("document.getElementById('page-po').classList.contains('active')")
            hidden_when_published = page.evaluate("(function(){syncFinalizeShortcut({publication_status:'PUBLISHED',blocker_codes:[]});"
                                                  "return document.getElementById('btn-aa-goto-finalize').style.display;})()")
            # E2E-10: Depotbank neutral bzw. aus eigenen Daten, kein Drittbank-Name.
            banks = page.evaluate("(function(){populateRecipeDepotBanks();return Array.from(document.querySelectorAll('#recipe-depot-bank option')).map(o=>[o.value,o.textContent]);})()")
            ums_text = page.evaluate("document.getElementById('m-ums').innerText")
            # E2E-07: Musterprodukte deutlich gekennzeichnet (Gegenprobe mit ISIN).
            sample = page.evaluate("""(function(){
              var rows=[{id:'p1',product_name:'Musterfonds A',isin:null,asset_class:'Aktien',sub_asset_class:'Aktien Welt',currency:'CHF',ter_bps:20,target_amount_rappen:5000000,target_weight_bps:5000},
                        {id:'p2',product_name:'Belegter Fonds B',isin:'CH0000000001',asset_class:'Aktien',sub_asset_class:'Aktien Welt',currency:'CHF',ter_bps:20,target_amount_rappen:5000000,target_weight_bps:5000}];
              renderPortfolioSections(rows);
              var w=document.getElementById('po-sample-warning');
              var out={warn:w.textContent,visible:w.style.display!=='none',rows:document.getElementById('po-portfolio-sections').innerText};
              renderPortfolioSections([rows[1]]);
              out.okVisible=document.getElementById('po-sample-warning').style.display!=='none';
              renderPortfolioSections([]);
              return out;})()""")
            # E2E-12: negative Prognose als Verzehr (Berechnung unveraendert).
            depletion = page.evaluate("""(function(){
              var L=['2026','2027','2028','2029'];
              return {all:fanDepletionSentence(L,[1,-1,-2,-3],[2,1,-0.5,-1],[3,0.5,-0.2,-0.5]),
                      low:fanDepletionSentence(L,[1,0.5,-0.1,-0.4],[2,2,2,2],[3,3,3,3]),
                      none:fanDepletionSentence(L,[1,1,1,1],[2,2,2,2],[3,3,3,3])};})()""")
            tile = page.evaluate("""(function(){
              var host=document.createElement('div');host.innerHTML='<div class="kl">Prognose Ende 2029</div><div id="k2-proj-test">x</div>';document.body.appendChild(host);
              var year=markProjectionDepletion('k2-proj-test',-150000000,{monte_carlo:{target_p50_series_rappen:[5,2,-1,-3],year_labels:[2026,2027,2028,2029]}});
              var lbl=host.firstChild.textContent;var pos=markProjectionDepletion('k2-proj-test',150000000,{});host.remove();
              return {year:year,label:lbl,positive:pos};})()""")
            # E2E-11: Horizont-Beschriftung = angezeigter Ausschnitt (Gegenprobe ohne Strategie).
            horizon = page.evaluate("""(function(){
              var orig=window.hasVisibleStrategyOutputs;
              charts.opt.data.labels=['2026','2040','2056'];
              window.hasVisibleStrategyOutputs=function(){return true;};syncAaHorizonControl();
              var withSim=document.getElementById('aa-horizon-eff').textContent;
              window.hasVisibleStrategyOutputs=function(){return false;};syncAaHorizonControl();
              var without=document.getElementById('aa-horizon-eff').textContent;
              window.hasVisibleStrategyOutputs=orig;return {withSim:withSim,without:without};})()""")
            # E2E-18: Uebergabe "diese Minute" wird sekundengenau gesendet.
            captured: list[dict] = []

            def deliveries(route):
                captured.append(json.loads(route.request.post_data or "{}"))
                route.fulfill(status=201, content_type="application/json", body="{}")
            page.route("**/client-information/deliveries", deliveries)
            minute_now = page.evaluate("""(function(){var n=new Date();var p=function(v){return String(v).padStart(2,'0');};
              var box=document.createElement('div');box.id='k2-ci-box';box.innerHTML='<input id="ci-delivered-at" type="datetime-local"><select id="ci-channel"><option value="post">Post</option></select><input id="ci-backdating">';
              document.body.appendChild(box);
              document.getElementById('ci-delivered-at').value=n.getFullYear()+'-'+p(n.getMonth()+1)+'-'+p(n.getDate())+'T'+p(n.getHours())+':'+p(n.getMinutes());
              document.getElementById('ci-channel').value='post';return n.toISOString();})()""")
            page.evaluate("()=>{recordClientInformationDelivery('doc-k2');}")
            page.wait_for_timeout(1200)
            page.evaluate("""(function(){var d=new Date(Date.now()-3*3600*1000);var p=function(v){return String(v).padStart(2,'0');};
              document.getElementById('ci-delivered-at').value=d.getFullYear()+'-'+p(d.getMonth()+1)+'-'+p(d.getDate())+'T'+p(d.getHours())+':'+p(d.getMinutes());})()""")
            page.evaluate("()=>{recordClientInformationDelivery('doc-k2');}")
            page.wait_for_timeout(1200)
            page.evaluate("document.getElementById('k2-ci-box').remove()")
            page.unroute("**/client-information/deliveries")
        finally:
            browser.close()

    assert steps == ["OK", "2", "3", "4", "5", "6", "7"], steps
    assert re.match(r"Punkte \d+/12", rsub[1]), rsub
    assert "nicht erfasst" in ret_before
    assert mandate_after["retirement_year"] == 2041
    assert finalize_btn["text"] == "Empfehlung finalisieren" and finalize_btn["visible"] is True, finalize_btn
    assert finalize_btn["disabled"] is True and finalize_btn["hint"] is True and "Anlagestrategie berechnen" in finalize_btn["hintText"]
    assert shortcut["shown"] is True and shortcut["visible"] is True
    assert "Portfolio › Empfehlung finalisieren" in shortcut["reason"]
    assert jumped_po is True and hidden_when_published == "none"
    assert banks[0] == ["", "Ohne Angabe (neutral)"] and ["Testbank Fiktiv", "Testbank Fiktiv"] in banks
    assert "UBS" not in json.dumps(banks) and "ZKB" not in json.dumps(banks) and "UBS" not in ums_text
    assert sample["visible"] and "1 von 2 Positionen sind Musterprodukte" in sample["warn"]
    assert "Musterprodukt – nicht zur Umsetzung" in sample["rows"] and sample["okVisible"] is False
    assert depletion["all"].startswith("Vermögen aufgebraucht ab 2028"), depletion
    assert "ab 2028" in depletion["low"] and "ungünstigen" in depletion["low"] and depletion["none"] == ""
    assert tile == {"year": "2028", "label": "Vermögen aufgebraucht ab 2028", "positive": None}, tile
    assert horizon["withSim"] == "= auto bis Ende 2055 (Simulationshorizont)", horizon  # KN-U E2E-11: Jahreswechsel-Label 2056 = Ende 2055
    assert "Simulationshorizont" not in horizon["without"]
    assert len(captured) == 2
    sent_now = datetime.fromisoformat(captured[0]["delivered_at"].replace("Z", "+00:00"))
    ref = datetime.fromisoformat(minute_now.replace("Z", "+00:00"))
    assert abs((sent_now - ref).total_seconds()) < 5, (captured[0], minute_now)
    sent_past = datetime.fromisoformat(captured[1]["delivered_at"].replace("Z", "+00:00"))
    assert sent_past.second == 0 and sent_past.microsecond == 0  # Gegenprobe: aeltere Eingabe bleibt minutengenau
    assert not errors, errors


def test_ci_runs_this_behaviour_test_with_playwright_required():
    workflow = (BACKEND.parent / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    job = workflow[workflow.index("\n  vitest:"):]
    assert 'ARES_REQUIRE_PLAYWRIGHT: "1"' in job
    assert "tests/test_livetest_k2_kernkette_ui.py" in job
