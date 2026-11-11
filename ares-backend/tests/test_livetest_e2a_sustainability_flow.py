"""E2a Pflicht-Livetest (Codex-Vertrag E2): Nachhaltigkeitspraeferenzen im
echten Risikoprofil-Flow, Barrierefreiheit und echter Mandatswechsel A -> B -> A.

Echter Ablauf: isolierter Backend-Prozess (Temp-DB/HOME/APPDATA/
LOCALAPPDATA, Wegwerf-KEK, freier Port), echte App ``/app/ares.html``,
echter Login, echter Mandatswechsel (``loadClientById``) in Chromium.

* Zuerst nur Frage 1 (Ja / Nicht relevant / Keine Angabe), Folgefragen und
  Abschluss verborgen; Folgefragen nur bei "Ja" (per Tastatur ausgeloest).
* Ausschluesse ausgegraut mit Grund (aria-describedby), Verzicht nur im
  Anlageberatungs-Mandat.
* Fehlerzusammenfassung mit Fokus, Links und aria-invalid; Labels fuer jede
  Eingabe; Kontrast >= 4.5:1 fuer die Texte der Maske.
* Mandatswechsel A -> B -> A: keine Antwort, kein Zustand, kein Verzicht-
  Feld und kein Entwurf leckt; der Zustand ist der des Servers.
* Speichern ueber die Maske; Browser und API zeigen denselben Zustand.

Pflichtlauf im CI-Job "Frontend Reporting Tests" (``ARES_REQUIRE_PLAYWRIGHT=1``),
sonst sichtbarer Skip. Screenshots optional nach ``ARES_E2_SCREENSHOT_DIR``.
"""
from __future__ import annotations

import json
import os
import shutil
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
USER, PWD = "e2a.admin", "E2a-Probe-Passwort-2026!x"


def _playwright_sync_api():
    if os.environ.get("ARES_REQUIRE_PLAYWRIGHT") == "1":
        import playwright.sync_api as sync_api  # Pflicht: ImportError ist rot

        return sync_api
    return pytest.importorskip(
        "playwright.sync_api",
        reason="Playwright fehlt; Pflichtlauf im CI-Job 'Frontend Reporting Tests' (E2a)",
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

    tmp = Path(tempfile.mkdtemp(prefix="e2a_flow_"))
    for sub in ("home", "appdata", "localappdata"):
        (tmp / sub).mkdir()
    port = int(os.environ.get("ARES_E2_PORT") or _free_port())
    env = {
        **os.environ,
        "HOME": str(tmp / "home"), "USERPROFILE": str(tmp / "home"),
        "APPDATA": str(tmp / "appdata"), "LOCALAPPDATA": str(tmp / "localappdata"),
        "DB_PATH": str(tmp / "e2a.db"), "SECRET_KEY": "e2a-flow-secret-key-0123456789abcdef",
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
            proc.wait(timeout=30)
        # N-888-17: Temp-Verzeichnis inkl. Test-DB wieder entfernen.
        for _ in range(40):
            shutil.rmtree(tmp, ignore_errors=True)
            if not tmp.exists():
                break
            time.sleep(0.5)


def _seed_mandate(api: _Api, advisor_id: str, label: str, mandate_type: str) -> tuple[str, str]:
    from tests.risk_fixture_helpers import standard_risk_payload

    stamp = f"{label}-{int(time.time() * 1000)}"
    status, client = api("POST", "/clients", {
        "client_number": f"E2A-{stamp}", "first_name": label, "last_name": "Probe",
        "advisor_id": advisor_id, "household_type": "Einzelperson", "date_of_birth": "1975-05-01"})
    assert status == 201, client
    cid = client["id"]
    status, mandate = api("POST", f"/clients/{cid}/mandates",
                          {"mandate_number": f"M-{stamp}", "mandate_type": mandate_type})
    assert status == 201, mandate
    mid = mandate["id"]
    assert api("POST", f"/mandates/{mid}/risk-assessments", standard_risk_payload())[0] == 201
    return cid, mid


_CARD_STATE = """() => {
  const q = (s) => document.querySelector(s);
  const card = q('#sust-card');
  return {
    visible: !!card && getComputedStyle(card).display !== 'none',
    state: q('#sust-state') ? q('#sust-state').dataset.state : null,
    stateText: q('#sust-state') ? q('#sust-state').textContent : '',
    checked: Array.from(document.querySelectorAll('#sust-card input:checked')).map(e => e.id),
    yesHidden: q('#sust-yes-block') ? q('#sust-yes-block').hidden : null,
    finishHidden: q('#sust-finish') ? q('#sust-finish').hidden : null,
    waiver: !!q('#sust-q4'),
    result: q('#sust-result') ? getComputedStyle(q('#sust-result')).display : null,
    exclusions: Array.from(document.querySelectorAll('#sust-card .sust-excl')).map(e => ({
      disabled: e.disabled, describedBy: e.getAttribute('aria-describedby'),
      reason: e.getAttribute('aria-describedby') && document.getElementById(e.getAttribute('aria-describedby'))
        ? document.getElementById(e.getAttribute('aria-describedby')).textContent : ''})),
  };
}"""

_A11Y = """() => {
  const card = document.getElementById('sust-card');
  const unlabeled = Array.from(card.querySelectorAll('input,select,textarea,button')).filter(el => {
    if (el.tagName === 'BUTTON') return !el.textContent.trim();
    return !(el.id && card.querySelector('label[for="' + el.id + '"]')) && !el.getAttribute('aria-label');
  }).map(el => el.id || el.name);
  function lum(c) {
    const m = c.match(/\\d+(\\.\\d+)?/g).map(Number);
    const ch = m.slice(0, 3).map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); });
    return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2];
  }
  function bg(el) {
    while (el) { const c = getComputedStyle(el).backgroundColor; if (c && !/rgba\\(0, 0, 0, 0\\)|transparent/.test(c)) return c; el = el.parentElement; }
    return 'rgb(255, 255, 255)';
  }
  const low = [];
  card.querySelectorAll('legend, label, p, #sust-state, #sust-policy, .cht').forEach(el => {
    if (!el.offsetParent || el.querySelector('input:disabled')) return;
    const a = lum(getComputedStyle(el).color), b = lum(bg(el));
    const ratio = (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
    if (ratio < 4.5) low.push([el.id || el.tagName, Math.round(ratio * 100) / 100]);
  });
  return {unlabeled, low, heading: !!card.querySelector('[role="heading"]'),
          legends: card.querySelectorAll('fieldset > legend').length};
}"""


def test_sustainability_flow_a11y_and_real_mandate_switch(server):
    from core import sustainability_preference as sp

    sync_api = _playwright_sync_api()
    shots = os.environ.get("ARES_E2_SCREENSHOT_DIR")
    api = _Api(server)
    api("POST", "/auth/bootstrap-admin", {"username": USER, "password": PWD, "full_name": "E2a Admin",
                                          "company_name": "Probe AG", "home_jurisdiction": "CH"})
    status, login = api("POST", "/auth/login", {"username": USER, "password": PWD})
    assert status == 200, login
    api.token = login["access_token"]
    advisor_id = api("GET", "/auth/me")[1]["id"]
    cid_a, mid_a = _seed_mandate(api, advisor_id, "Anna", "Anlageberatung")
    cid_b, mid_b = _seed_mandate(api, advisor_id, "Beat", "Vermögensverwaltung")
    status, body = api("POST", f"/mandates/{mid_a}/sustainability-preferences", {
        "questionnaire_version": sp.QUESTIONNAIRE_VERSION, "definition_hash": sp.definition_hash(),
        "response_status": "answered", "esg_relevance": "yes", "esg_characteristic": "sdg_alignment",
        "exclusions": [], "information_acknowledged": True, "client_confirmed": True,
        "capture_channel": "in_person"})
    assert status == 201 and body["state"] == "preference_stated", body

    close = "document.querySelectorAll('.overlay.open').forEach(function(o){o.classList.remove('open');})"
    with sync_api.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        errors: list[str] = []
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 1100})
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(server + "/app/ares.html")
            # Intro regulaer beenden (entfernt auch seinen Tastatur-Listener,
            # der sonst Enter/Leertaste abfaengt), danach sicherheitshalber weg.
            try:
                page.wait_for_selector("#intro-screen .intro-skip:not([disabled])", timeout=20000)
                page.click("#intro-screen .intro-skip")
                page.wait_for_timeout(1000)
            except sync_api.Error:
                pass
            page.evaluate("document.getElementById('intro-screen')&&document.getElementById('intro-screen').remove()")
            page.fill("#login-username", USER)
            page.fill("#login-password", PWD)
            page.evaluate("document.getElementById('btn-login-submit').click()")
            page.wait_for_timeout(3000)

            def open_rp(cid: str) -> dict:
                page.evaluate(close)
                page.evaluate(f"loadClientById('{cid}')")
                page.wait_for_timeout(3000)
                page.evaluate(close)
                page.evaluate("go('rp')")
                page.wait_for_timeout(2500)
                page.evaluate(close)
                return page.evaluate(_CARD_STATE)

            def shot(name):
                if shots:
                    Path(shots).mkdir(parents=True, exist_ok=True)
                    page.locator("#sust-card").screenshot(path=str(Path(shots) / name))

            a_first = open_rp(cid_a)
            shot("e2a_1_mandat_a_erfasst.png")
            # Tastatur: Frage 1 "Ja" per Leertaste -> Folgefragen erscheinen.
            page.focus("#sust-q1-yes")
            page.keyboard.press("Space")
            page.wait_for_timeout(200)
            a_yes = page.evaluate(_CARD_STATE)
            page.check("#sust-q2-esg_factors")  # Entwurf, nicht gespeichert
            shot("e2a_2_mandat_a_ja_entwurf.png")
            a11y = page.evaluate(_A11Y)
            b_state = open_rp(cid_b)
            shot("e2a_3_mandat_b_nicht_erfasst.png")
            # Fehlerzusammenfassung: Speichern ohne Antwort ist nur ueber
            # Frage 1 erreichbar -> Frage 1 waehlen, Rest leer lassen.
            page.check("#sust-q1-not_relevant")
            page.click("#btn-sust-save")
            page.wait_for_timeout(300)
            summary = page.evaluate("""() => ({
              focused: document.activeElement && document.activeElement.id,
              links: Array.from(document.querySelectorAll('#sust-errors a')).map(a => a.getAttribute('href')),
              invalid: Array.from(document.querySelectorAll('#sust-card [aria-invalid="true"]')).map(e => e.id)})""")
            shot("e2a_4_fehlerzusammenfassung.png")
            page.click("#sust-errors a[href='#sust-channel']")
            focused_after_link = page.evaluate("document.activeElement && document.activeElement.id")
            page.select_option("#sust-channel", "phone")
            page.check("#sust-confirm")
            page.click("#btn-sust-save")
            page.wait_for_timeout(1500)
            b_saved = page.evaluate(_CARD_STATE)
            shot("e2a_5_mandat_b_gespeichert.png")
            a_again = open_rp(cid_a)
            b_again = open_rp(cid_b)
        finally:
            browser.close()

    # Mandat A: Zustand vom Server, Frage 1 zuerst, keine Vorauswahl.
    assert a_first["visible"] and a_first["state"] == "preference_stated", a_first
    assert a_first["checked"] == [] and a_first["yesHidden"] is True and a_first["finishHidden"] is True
    assert a_first["result"] != "none"
    # "Ja" per Tastatur: Folgefragen + Abschluss sichtbar; Ausschluesse
    # ausgegraut mit Grund; Verzicht nur Anlageberatung.
    assert a_yes["checked"] == ["sust-q1-yes"] and a_yes["yesHidden"] is False and a_yes["finishHidden"] is False
    assert a_yes["waiver"] is True
    assert len(a_yes["exclusions"]) == 6
    assert all(e["disabled"] and e["describedBy"] and e["reason"] for e in a_yes["exclusions"]), a_yes
    # A11y.
    assert a11y["unlabeled"] == [] and a11y["low"] == [], a11y
    assert a11y["heading"] and a11y["legends"] >= 3
    # Wechsel auf B: nichts von A (Antwort, Entwurf, Verzicht, Ergebnis).
    assert b_state["visible"] and b_state["state"] == "unanswered", b_state
    assert b_state["checked"] == [] and b_state["waiver"] is False and b_state["result"] == "none"
    assert b_state["yesHidden"] is True and b_state["finishHidden"] is True
    assert "Noch nicht erfasst" in b_state["stateText"]
    # Fehlerzusammenfassung.
    assert summary["focused"] == "sust-errors"
    assert set(summary["links"]) == {"#sust-channel", "#sust-confirm"}
    assert set(summary["invalid"]) == {"sust-channel", "sust-confirm"}
    assert focused_after_link == "sust-channel"
    # Speichern in B ueber die Maske; API zeigt denselben Zustand.
    assert b_saved["state"] == "no_preference" and b_saved["checked"] == []
    api_b = api("GET", f"/mandates/{mid_b}/sustainability-preferences")[1]
    assert api_b["state"] == "no_preference" and api_b["current"]["capture_channel"] == "phone"
    api_a = api("GET", f"/mandates/{mid_a}/sustainability-preferences")[1]
    assert api_a["current"]["esg_characteristic"] == "sdg_alignment" and len(api_a["history"]) == 1
    # Zurueck auf A und B: kein Entwurf, Zustand je Mandat.
    assert a_again["state"] == "preference_stated" and a_again["checked"] == [] and a_again["waiver"] is True
    assert b_again["state"] == "no_preference" and b_again["waiver"] is False
    assert not errors, errors


def test_ci_runs_this_behaviour_test_with_playwright_required():
    workflow = (BACKEND.parent / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    job = workflow[workflow.index("\n  vitest:"):]
    assert 'ARES_REQUIRE_PLAYWRIGHT: "1"' in job
    assert "tests/test_livetest_e2a_sustainability_flow.py" in job
