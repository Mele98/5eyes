"""Kern-Integration Runde 3 (H-172): KN3-B + KN3-U auf dem Merge-Stand, ohne Route-Stub.

Ein durchgehender Ablauf mit echtem Backend-Prozess (Temp-DB/HOME/APPDATA,
Wegwerf-KEK, freier Port), echter App in Chromium und echtem Neustart auf
derselben Datenbank:

1. Kapitalschutz-Kunde mit Aktienbestand (Depot CHF + Depot USD), Strategie,
   "Portfolio generieren" (Produktlauf), Finalisieren, Einzelfreigabe.
2. Bandregel: Payload Aktien Band 0/0 (Ziel 0) bei Ist > 0, Review-Karte Aktien
   "Verletzt". Der Depotcheck ohne erfassten Bestand ist eine Soll-Analyse
   (IST = Zielbetraege; Aktien ausserhalb der Empfehlung sind nicht erfassbar,
   N-915-06 -> K3): API ``in_band`` nicht bewertbar, PDF ohne Bandaussage,
   Advisory-Report ohne "innerhalb der Toleranzbaender" (H-172-Befund).
3. Alle 12 Kunden-PDFs 200, ohne "−100 %"/Drawdown 100 % und ohne Umschriften
   (Detektor aus dem KN3-B-Waechter).
4. Berufsaenderung ueber die Stammdaten-Maske -> Server PUBLISHED/FRESH, UI "Publiziert".
5. Neustart (zweiter Serverprozess) -> Publikation PUBLISHED/FRESH, keine
   Zeile einer Abhaengigkeitstabelle geaendert.
6. Nach dem Neustart USD 0.88 -> 0.90 in der Administration: Betraege sofort
   ueberall gleich (Vermoegensseite, Strategiebasis der AA, Review-Kachel,
   Serversumme), Publikation "Veraltet · Wechselkurs USD geändert".

Pflichtlauf im CI-Job "Kern-Integration Livetest (Playwright Pflicht)".
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from tests.test_livetest_k2_kernkette_ui import CLOSE, _sync_api
from tests.test_livetest_kn3_b_customer_pdf_guard import (
    CLEAN_LEGAL_PROFILE, COMPANY, CUSTOMER_PDFS, _Api, _dependency_rows, _free_port, _pdf_text, _stop,
    umlaut_transliterations,
)

BACKEND = Path(__file__).resolve().parents[1]
USER, PWD = "kint3.admin", "Kint3-Probe-Passwort-2026!x"
CHIP = "(document.getElementById('aa-publication-status')||{textContent:''}).textContent.trim()"
CARDS = ("() => Array.prototype.map.call(document.querySelectorAll('#sr-implementation-steps > div'),"
         "function(c){return c.innerText.replace(/\\s+/g,' ').trim();})")
_MINUS_100 = re.compile(r"[−\-–]\s?100(?:[.,]0+)?\s?%")
_DRAWDOWN_100 = re.compile(r"drawdown[^\n%]{0,40}?\b100(?:[.,]0+)?\s?%", re.IGNORECASE)


def _start(tmp, db_path, kek, port):
    env = {
        **os.environ,
        "HOME": str(tmp / "home"), "USERPROFILE": str(tmp / "home"),
        "APPDATA": str(tmp / "appdata"), "LOCALAPPDATA": str(tmp / "localappdata"),
        "DB_PATH": str(db_path), "SECRET_KEY": "kint3-secret-key-0123456789abcdef-xyz",
        "SERVE_MAIN_FRONTEND": "1", "PRICE_SCHEDULER_ENABLED": "0", "BACKUP_SCHEDULER_ENABLED": "0",
        "MARKET_DATA_CACHE_PURGE_ENABLED": "0", "LOGIN_RATE_LIMIT_ENABLED": "0",
        "APP_ENV": "development", "TENANT_MASTER_KEK": kek, "PYTHONDONTWRITEBYTECODE": "1",
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(BACKEND), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 180
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2)
            return proc
        except Exception:  # noqa: BLE001 - Server startet noch
            if proc.poll() is not None:
                break
            time.sleep(1)
    _stop(proc)
    raise RuntimeError("Backend nicht gestartet")


def _login_api(base):
    api = _Api(base)
    st, body = api("POST", "/auth/login", {"username": USER, "password": PWD})
    assert st == 200, body
    api.token = body["access_token"]
    return api


def _page(browser, base, sync_api, errors):
    page = browser.new_page(viewport={"width": 1500, "height": 950})
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.goto(base + "/app/ares.html")
    try:
        page.wait_for_selector("#intro-screen .intro-skip:not([disabled])", timeout=20000)
        page.click("#intro-screen .intro-skip")
        page.wait_for_timeout(800)
    except sync_api.Error:
        pass
    page.evaluate("document.getElementById('intro-screen')&&document.getElementById('intro-screen').remove()")
    page.fill("#login-username", USER)
    page.fill("#login-password", PWD)
    page.evaluate("document.getElementById('btn-login-submit').click()")
    page.wait_for_timeout(3500)
    page.evaluate(CLOSE)
    return page


def _go(page, pg, wait=2500):
    page.evaluate(CLOSE)
    page.evaluate(f"go('{pg}')")
    page.wait_for_timeout(wait)
    page.evaluate(CLOSE)


def _load(page, cid, pg):
    page.evaluate(CLOSE)
    page.evaluate(f"loadClientById('{cid}')")
    page.wait_for_timeout(2500)
    _go(page, pg, 2000)


def _overview(api, mid):
    st, body = api("GET", f"/mandates/{mid}/allocation-publication")
    assert st == 200, body
    return body


def _setup(api, db_path):
    import tests.client_onboarding_fixture as onboarding
    from core import sustainability_preference as sp
    from tests.risk_fixture_helpers import standard_risk_payload
    from tests.test_livetest_e2b_strategy_blocks import _finalize_and_publish

    assert api("PUT", "/fx-rates", {"rates": [
        {"currency": "USD", "rate": 0.88, "source": "Manual", "confirm_current": True}]})[0] in (200, 201)
    advisor_id = api("GET", "/auth/me")[1]["id"]
    st, client = api("POST", "/clients", {
        "client_number": "KINT3-1", "first_name": "Klara", "last_name": "Kapitalschutz-Fiktiv",
        "advisor_id": advisor_id, "household_type": "Einzelperson", "date_of_birth": "1966-03-10", "canton": "ZH"})
    assert st == 201, client
    cid = client["id"]
    st, mandate = api("POST", f"/clients/{cid}/mandates", {"mandate_number": "M-KINT3-1", "mandate_type": "Anlageberatung"})
    assert st == 201, mandate
    mid = mandate["id"]
    risk = standard_risk_payload(income=1, wealth=1, savings=1, goal=0, pref=0, behav=0)  # Kapitalschutz
    assert api("POST", f"/mandates/{mid}/risk-assessments", risk)[0] == 201
    for pos in (
        {"label": "Depot CHF Klara (fiktiv)", "position_type": "Depot", "assignment": "Beratungsvermögen",
         "current_value_rappen": 40_000_000, "currency": "CHF", "depot_bank": "Testbank Fiktiv",
         "alloc_equities_bps": 4000, "alloc_bonds_bps": 5000, "alloc_liquidity_bps": 1000},
        {"label": "Depot USD Klara (fiktiv)", "position_type": "Depot", "assignment": "Beratungsvermögen",
         "current_value_rappen": 10_000_000, "currency": "USD", "depot_bank": "Testbank Fiktiv",
         "alloc_equities_bps": 7000, "alloc_bonds_bps": 3000},
        {"label": "Privatkonto Klara (fiktiv)", "position_type": "Liquidität", "assignment": "Beratungsvermögen",
         "current_value_rappen": 5_000_000, "currency": "CHF", "liquidity_instrument": "Kontoguthaben"},
    ):
        st, body = api("POST", f"/clients/{cid}/wealth-positions", pos)
        assert st in (200, 201), body
    for cf in ({"cashflow_type": "Income", "label": "Erwerb (fiktiv)", "amount_rappen": 12_000_000, "valid_until": "2031-03-31"},
               {"cashflow_type": "Expense", "label": "Lebenshaltung (fiktiv)", "amount_rappen": 9_000_000, "valid_until": None}):
        st, body = api("POST", f"/clients/{cid}/cashflows", {**cf, "currency": "CHF", "frequency": "jaehrlich",
                                                            "nature": "wiederkehrend", "valid_from": "2026-12-01",
                                                            "is_inflation_linked": False})
        assert st in (200, 201), body
    st, body = api("POST", f"/mandates/{mid}/sustainability-preferences", {
        "questionnaire_version": sp.QUESTIONNAIRE_VERSION, "definition_hash": sp.definition_hash(),
        "response_status": "declined", "esg_relevance": None, "esg_characteristic": None, "exclusions": [],
        "information_acknowledged": False, "client_confirmed": True, "capture_channel": "in_person"})
    assert st == 201, body
    st, body = api("POST", f"/mandates/{mid}/target-allocation/generate", {"preferences": {}})
    assert st == 200, body
    st, portfolio = api("POST", f"/mandates/{mid}/recommendations/generate", {})  # "Portfolio generieren"
    assert st == 200, portfolio
    original = onboarding.TEST_LEGAL_PROFILE
    onboarding.TEST_LEGAL_PROFILE = CLEAN_LEGAL_PROFILE
    try:
        _finalize_and_publish(api, db_path, mid)
    finally:
        onboarding.TEST_LEGAL_PROFILE = original
    return cid, mid, portfolio


def test_kern_integration_r3_band_pdfs_restart_and_amounts():
    sync_api = _sync_api()
    from cryptography.fernet import Fernet

    tmp = Path(tempfile.mkdtemp(prefix="kint_r3_"))
    for sub in ("home", "appdata", "localappdata"):
        (tmp / sub).mkdir()
    db_path, kek = tmp / "kint_r3.db", Fernet.generate_key().decode()
    port = _free_port()
    proc = _start(tmp, db_path, kek, port)
    base = f"http://127.0.0.1:{port}"
    errors: list[str] = []
    try:
        api = _Api(base)
        st, body = api("POST", "/auth/bootstrap-admin", {"username": USER, "password": PWD,
                                                          "full_name": "Kint Testberater", "company_name": COMPANY,
                                                          "home_jurisdiction": "CH"})
        assert st == 201, body
        api = _login_api(base)
        cid, mid, portfolio = _setup(api, db_path)
        start = _overview(api, mid)

        st, payload = api("GET", f"/mandates/{mid}/target-allocation/current/payload")
        assert st == 200, payload
        eq = next(b for b in payload["buckets"] if b["asset_class"] == "Aktien")
        st, depot = api("GET", f"/mandates/{mid}/depot-check")
        assert st == 200, depot
        pdfs = {}
        for name in CUSTOMER_PDFS:
            st, data = api("GET", f"/mandates/{mid}/reports/{name}.pdf", raw=True)
            pdfs[name] = (st, _pdf_text(data) if st == 200 else data.decode("utf-8", "replace")[:300])
        out = os.environ.get("ARES_KINT3_OUT")
        if out:
            import json as _json
            Path(out).mkdir(parents=True, exist_ok=True)
            Path(out, "depot_check.json").write_text(_json.dumps(depot, ensure_ascii=False, indent=1), encoding="utf-8")
            Path(out, "payload.json").write_text(_json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
            for name, (st_, text) in pdfs.items():
                Path(out, f"{name}.txt").write_text(str(st_) + "\n" + text, encoding="utf-8")

        with sync_api.sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                page = _page(browser, base, sync_api, errors)
                _load(page, cid, "rv")
                page.wait_for_function("() => document.querySelectorAll('#sr-implementation-steps > div').length >= 1",
                                       timeout=60000)
                page.wait_for_timeout(1500)
                cards = page.evaluate(CARDS)
                # Berufsaenderung ueber die echte Maske.
                _go(page, "sd")
                page.evaluate("()=>{openStammdatenModal();}")
                page.wait_for_selector("#es-profession", state="visible", timeout=15000)
                page.fill("#es-profession", "Bibliothekarin (fiktiv)")
                page.click("#btn-es-save")
                page.wait_for_function("() => /Gespeichert/.test((document.getElementById('es-error')||{textContent:''})"
                                       ".textContent)", timeout=30000)
                page.wait_for_timeout(2500)
                _go(page, "al", 3000)
                chip_profession = page.evaluate(CHIP)
                page.close()
            finally:
                browser.close()
        after_profession = _overview(api, mid)

        # Neustart: zweiter Serverprozess auf derselben DB und demselben KEK.
        rows_before = _dependency_rows(db_path)
        _stop(proc)
        port = _free_port()
        proc = _start(tmp, db_path, kek, port)
        base = f"http://127.0.0.1:{port}"
        api = _login_api(base)
        after_restart = _overview(api, mid)
        rows_after = _dependency_rows(db_path)

        with sync_api.sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                page = _page(browser, base, sync_api, errors)
                _load(page, cid, "vg")
                page.wait_for_function("() => /538/.test(document.getElementById('page-vg').innerText)", timeout=60000)
                chip_restart = None
                _go(page, "al", 3000)
                page.wait_for_function("() => /Publiziert/.test(" + CHIP + ")", timeout=60000)
                chip_restart = page.evaluate(CHIP)
                _go(page, "vg")
                page.evaluate("()=>{loadAdminFxRates();}")
                page.wait_for_selector(".admin-fx-rate-input[data-currency='USD']", state="attached", timeout=30000)
                page.evaluate("""()=>{var i=document.querySelector(".admin-fx-rate-input[data-currency='USD']");i.value='0.9';
                  document.querySelector(".admin-fx-rate-confirm[data-currency='USD']").checked=true;}""")
                page.evaluate("()=>{var b=Array.prototype.find.call(document.querySelectorAll('button'),"
                              "function(x){return /Wechselkurse speichern/.test(x.textContent);});b.click();}")
                page.wait_for_function("() => /540/.test(document.getElementById('page-vg').innerText)", timeout=60000)
                vg = page.evaluate("document.getElementById('page-vg').innerText")
                page.evaluate(CLOSE)
                _go(page, "al", 3000)
                page.wait_for_function("() => /540/.test((document.getElementById('dnleg')||{innerText:''}).innerText)",
                                       timeout=60000)
                page.wait_for_function("() => /Veraltet/.test(" + CHIP + ")", timeout=60000)
                aa = page.evaluate("({leg:(document.getElementById('dnleg')||{innerText:''}).innerText,chip:" + CHIP + ","
                                   "center:(document.querySelector('.dcv')||{innerText:''}).innerText})")
                _go(page, "rv")
                rv_wealth = page.evaluate("(document.getElementById('sr-wealth')||{textContent:''}).textContent")
            finally:
                browser.close()
        summary = api("GET", f"/clients/{cid}/wealth-summary?mandate_id={mid}")[1]
        after_fx = _overview(api, mid)
    finally:
        _stop(proc)
        shutil.rmtree(tmp, ignore_errors=True)

    # 1. Durchlauf bis zur Publikation, Portfolio generiert.
    assert start["publication_status"] == "PUBLISHED" and start["freshness"]["status"] == "FRESH", start
    assert portfolio, portfolio
    # 2. Bandregel UI = Backend = PDF.
    assert (eq["band_min_bps"], eq["band_max_bps"], eq["target_weight_bps"]) == (0, 0, 0), eq
    assert eq["current_weight_bps"] > 0, eq
    # Depotcheck ohne erfassten Bestand: IST = Zielbetraege (Soll-Analyse). Aktien
    # ausserhalb der Empfehlung sind (noch) nicht erfassbar (N-915-06 -> K3), darum
    # darf er keine Bandaussage machen -- weder API noch PDF noch Advisory-Report.
    assert depot["ist_basiert_auf_soll"] is True, depot
    assert all(b["in_band"] is None for b in depot["buckets"].values()), depot["buckets"]
    drift = " ".join(pdfs["depotcheck"][1].split())
    assert "ohne IST-Bestand (kein Depot erfasst)" in drift and "im Band" not in drift, drift[:3000]
    advisory = " ".join(pdfs["advisory-report"][1].split())
    assert "innerhalb der definierten Toleranzbänder" not in advisory, advisory[:3000]
    assert "Die Einhaltung der Toleranzbänder kann nicht beurteilt werden" in advisory, advisory[:3000]
    assert "Alle Anlageklassen liegen innerhalb des Toleranzbandes" not in advisory
    aktien_cards = [c for c in cards if "Aktien" in c]
    assert aktien_cards and all("Verletzt" in c and "Im Band" not in c for c in aktien_cards), cards
    # 3. Alle Kunden-PDFs: 200, kein -100 %, keine Umschriften.
    assert all(st == 200 for st, _ in pdfs.values()), {k: v for k, v in pdfs.items() if v[0] != 200}
    minus = {n: _MINUS_100.findall(" ".join(t.split())) + _DRAWDOWN_100.findall(" ".join(t.split()))
             for n, (_s, t) in pdfs.items()}
    assert not {n: h for n, h in minus.items() if h}, minus
    translit = {n: sorted(set(umlaut_transliterations(t))) for n, (_s, t) in pdfs.items()}
    assert not {n: w for n, w in translit.items() if w}, translit
    # 4. Beruf -> bleibt FRESH/"Publiziert".
    assert after_profession["publication_status"] == "PUBLISHED", after_profession
    assert after_profession["freshness"]["status"] == "FRESH", after_profession
    assert chip_profession.startswith("Publiziert"), chip_profession
    # 5. Neustart -> FRESH, keine gebundene Zeile geaendert.
    assert after_restart["publication_status"] == "PUBLISHED", after_restart
    assert after_restart["freshness"]["status"] == "FRESH", after_restart
    assert rows_before == rows_after
    assert chip_restart.startswith("Publiziert"), chip_restart
    # 6. Kursaenderung -> Betraege sofort ueberall gleich (538'000 -> 540'000).
    assert summary["advisory_wealth_rappen"] == 540_000_00, summary
    assert "540'000" in vg and "538'000" not in vg, vg
    assert "540'000" in aa["leg"] and "538'000" not in aa["leg"], aa
    assert "540" in aa["center"] and "538" not in aa["center"], aa
    assert "540" in rv_wealth and "538" not in rv_wealth, rv_wealth
    assert aa["chip"].startswith("Veraltet · Wechselkurs USD geändert"), aa
    assert after_fx["publication_status"] == "PUBLICATION_INVALID", after_fx
    assert any(c["kind"] == "fx_rate" and c["currencies"] == ["USD"] for c in after_fx["freshness"]["causes"]), after_fx
    assert not errors, errors


def test_ci_runs_this_behaviour_test_with_playwright_required():
    workflow = (BACKEND.parent / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    assert "test_livetest_kern_integration_r3.py" in workflow
