"""N-888-16 (Pruefrunde ESG 02dc0d24, Dok. 86 ab Z. 9801): "Portfolio
umsetzen" blieb nach einem Mandat mit verletzter Untergrenze fuer ALLE
weiteren Mandate deaktiviert (globale Restwirkung von ``disabled``).

Echter Ablauf statt Nachbildung: isolierter Backend-Prozess (Temp-DB/HOME/
APPDATA/LOCALAPPDATA, Wegwerf-KEK, freier Port), echte App ``/app/ares.html``,
echter Login und echter Mandatswechsel (``loadClientById``) in Chromium:

* Mandat A: Strategie mit ``tobacco=overweight``, danach Ausschluss Tabak
  erfasst -> AA: Button ausgeblendet und deaktiviert, Banner "veraltet".
* Wechsel auf Mandat B (sauber, Strategie ohne Praeferenz): Button sichtbar
  UND aktiv, Klick oeffnet ``m-pu``.
* Zurueck auf A: wieder ausgeblendet.

Pflichtlauf im CI-Job "Frontend Reporting Tests" (``ARES_REQUIRE_PLAYWRIGHT=1``),
sonst sichtbarer Skip.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
USER, PWD = "n888.admin", "N888-Probe-Passwort-2026!x"


def _playwright_sync_api():
    if os.environ.get("ARES_REQUIRE_PLAYWRIGHT") == "1":
        import playwright.sync_api as sync_api  # Pflicht: ImportError ist rot

        return sync_api
    return pytest.importorskip(
        "playwright.sync_api",
        reason="Playwright fehlt; Pflichtlauf im CI-Job 'Frontend Reporting Tests' (N-888-16)",
    )


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
            return exc.code, exc.read()[:400]


@pytest.fixture(scope="module")
def server():
    _playwright_sync_api()
    from cryptography.fernet import Fernet

    tmp = Path(tempfile.mkdtemp(prefix="n888_16_"))
    for sub in ("home", "appdata", "localappdata"):
        (tmp / sub).mkdir()
    port = _free_port()
    env = {
        **os.environ,
        "HOME": str(tmp / "home"), "USERPROFILE": str(tmp / "home"),
        "APPDATA": str(tmp / "appdata"), "LOCALAPPDATA": str(tmp / "localappdata"),
        "DB_PATH": str(tmp / "n888.db"), "SECRET_KEY": "n888-16-secret-key-0123456789abcdef",
        "SERVE_MAIN_FRONTEND": "1", "PRICE_SCHEDULER_ENABLED": "0", "BACKUP_SCHEDULER_ENABLED": "0",
        "APP_ENV": "development", "TENANT_MASTER_KEK": Fernet.generate_key().decode(),
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
        yield base
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()


def _seed_mandate(api: _Api, advisor_id: str, label: str, tilts: dict) -> tuple[str, str]:
    from tests.risk_fixture_helpers import standard_risk_payload

    stamp = f"{label}-{int(time.time() * 1000)}"
    status, client = api("POST", "/clients", {
        "client_number": f"N888-{stamp}", "first_name": label, "last_name": "Probe",
        "advisor_id": advisor_id, "household_type": "Einzelperson", "date_of_birth": "1975-05-01"})
    assert status == 201, client
    cid = client["id"]
    status, mandate = api("POST", f"/clients/{cid}/mandates",
                          {"mandate_number": f"M-{stamp}", "mandate_type": "Anlageberatung"})
    assert status == 201, mandate
    mid = mandate["id"]
    assert api("POST", f"/clients/{cid}/wealth-positions", {
        "label": "Depot", "position_type": "Depot", "assignment": "Beratungsvermögen",
        "current_value_rappen": 50_000_000, "alloc_equities_bps": 4000, "alloc_bonds_bps": 3000,
        "alloc_liquidity_bps": 2000, "alloc_alternatives_bps": 1000})[0] == 201
    assert api("POST", f"/mandates/{mid}/risk-assessments", standard_risk_payload())[0] == 201
    status, body = api("POST", f"/mandates/{mid}/target-allocation/generate",
                       {"preferences": {"tilts": tilts}})
    assert status == 200, body
    return cid, mid


def test_umsetzen_button_follows_the_real_current_mandate(server):
    from core import sustainability_preference as sp

    sync_api = _playwright_sync_api()
    api = _Api(server)
    api("POST", "/auth/bootstrap-admin", {"username": USER, "password": PWD, "full_name": "N888 Admin",
                                          "company_name": "Probe AG", "home_jurisdiction": "CH"})
    status, login = api("POST", "/auth/login", {"username": USER, "password": PWD})
    assert status == 200, login
    api.token = login["access_token"]
    advisor_id = api("GET", "/auth/me")[1]["id"]
    cid_bad, mid_bad = _seed_mandate(api, advisor_id, "Verletzt", {"tobacco": "overweight"})
    cid_ok, _mid_ok = _seed_mandate(api, advisor_id, "Sauber", {})
    status, body = api("POST", f"/mandates/{mid_bad}/sustainability-preferences", {
        "questionnaire_version": sp.QUESTIONNAIRE_VERSION, "definition_hash": sp.definition_hash(),
        "response_status": "answered", "esg_relevance": "yes", "esg_characteristic": "esg_factors",
        "exclusions": ["tobacco"], "information_acknowledged": True, "client_confirmed": True})
    assert status == 201 and body["allocation_floor_status"] == "violated", body

    close = "document.querySelectorAll('.overlay.open').forEach(function(o){o.classList.remove('open');})"
    state = ("() => {const u=document.getElementById('btn-portfolio-umsetzen');"
             "const b=document.getElementById('al-dirty-banner');"
             "return {button: getComputedStyle(u).display, disabled: u.disabled,"
             " banner: getComputedStyle(b).display};}")
    with sync_api.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        errors: list[str] = []
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(server + "/app/ares.html")
            page.wait_for_timeout(1500)
            page.evaluate("document.getElementById('intro-screen')&&document.getElementById('intro-screen').remove()")
            page.fill("#login-username", USER)
            page.fill("#login-password", PWD)
            page.evaluate("document.getElementById('btn-login-submit').click()")
            page.wait_for_timeout(3000)

            def open_mandate(cid: str) -> dict:
                page.evaluate(close)
                page.evaluate(f"loadClientById('{cid}')")
                page.wait_for_timeout(3000)
                page.evaluate(close)
                page.evaluate("go('al')")
                page.wait_for_timeout(3000)
                page.evaluate(close)
                return page.evaluate(state)

            bad = open_mandate(cid_bad)
            ok = open_mandate(cid_ok)
            page.click("#btn-portfolio-umsetzen")
            page.wait_for_timeout(500)
            opened = page.evaluate("document.getElementById('m-pu').classList.contains('open')")
            page.evaluate(close)
            bad_again = open_mandate(cid_bad)
        finally:
            browser.close()
    assert bad == {"button": "none", "disabled": True, "banner": "flex"}, bad
    assert ok["button"] != "none" and ok["disabled"] is False, ok
    assert opened is True
    assert bad_again["button"] == "none" and bad_again["disabled"] is True, bad_again
    assert not errors, errors


def test_ci_runs_this_behaviour_test_with_playwright_required():
    workflow = (BACKEND.parent / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    job = workflow[workflow.index("\n  vitest:"):]
    assert 'ARES_REQUIRE_PLAYWRIGHT: "1"' in job
    assert "tests/test_livetest_n888_16_real_mandate_switch.py" in job
