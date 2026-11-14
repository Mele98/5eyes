"""H11 (Hygiene-Folgepunkt E2): Ausschluss-Optionen ungestubbt, nur die juengste Antwort gilt.

Pflicht-Livetest (Pruefrunde E2 d5ea7619, Empfehlung + Hinweis H-1):

* Ungestubbt: echter Server-Endpunkt ``exclusion-options`` in der echten App
  (echter Login, echtes Mandat), synthetischer Nachweis-Seed wie im
  E2b-Livetest. Disjunkte Nachweise: je benoetigter Anlageklasse ein zweites
  Produkt (ueber die API angelegt); Tabak ist nur an den Originalen, Alkohol nur
  an den Zweitprodukten belegt. Einzeln sind beide waehlbar, zusammen nicht.
* Reihenfolge: Die Antwort auf "Tabak gewaehlt" wird zurueckgehalten (echte
  Server-Antwort, nur verzoegert), danach wird Tabak abgewaehlt. Kommt die
  aeltere Antwort zuletzt an, darf sie den Zustand nicht mehr setzen
  (Anfragezaehler in ``sustRefreshExclusions``) -- sonst stuende Alkohol
  faelschlich gesperrt.

Isoliert: eigener Backend-Prozess (Temp-DB/HOME/APPDATA/LOCALAPPDATA,
Wegwerf-KEK). Pflichtlauf im CI-Job "Frontend Reporting Tests"
(``ARES_REQUIRE_PLAYWRIGHT=1``).
"""
from __future__ import annotations

import sqlite3
import time
import uuid
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from tests.test_livetest_e2a_sustainability_flow import _Api, _playwright_sync_api
from tests.test_livetest_e2b_strategy_blocks import _seed_mandate, server  # noqa: F401  (Fixture)

BACKEND = Path(__file__).resolve().parents[1]
USER, PWD = "e2b.admin", "E2b-Probe-Passwort-2026!x"
LIQ = ("Liquidität", "Liquiditaet")


def _products(db_path: Path) -> list[tuple]:
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(
            "SELECT id, product_name, product_type, asset_class, sub_asset_class, currency FROM products "
            "WHERE is_active = 1 AND deleted_at IS NULL"
        ).fetchall()
    finally:
        conn.close()


def _seed_evidence(db_path: Path, product_ids: list[str], category: str, advisor_id: str) -> None:
    """Freigegebener synthetischer Ausschlussnachweis (Quelle Prospekt, Stichtag gestern)."""
    today = date.today()
    now = today.isoformat() + "T00:00:00.000Z"
    conn = sqlite3.connect(str(db_path))
    try:
        for product_id in product_ids:
            conn.execute(
                "INSERT INTO product_sustainability_attributes (id, product_id, tenant_id, category, kind, "
                "revenue_threshold_bps, source_type, source_reference, as_of, valid_until, status, "
                "created_by, created_at, approved_by, approved_at, approval_mode, updated_at) VALUES "
                "(?, ?, NULL, ?, 'exclusion_policy', 0, 'prospectus', 'Synthetischer Prospekt', "
                "?, ?, 'approved', ?, ?, ?, ?, 'single_approver_attested', ?)",
                (str(uuid.uuid4()), product_id, category, (today - timedelta(days=1)).isoformat(),
                 (today + timedelta(days=300)).isoformat(), advisor_id, now, advisor_id, now, now),
            )
        conn.commit()
    finally:
        conn.close()


def _options(api: _Api, mid: str, selected: list[str]) -> dict:
    qs = "&".join(f"selected={k}" for k in selected)
    status, body = api("GET", f"/mandates/{mid}/sustainability-preferences/exclusion-options" + (f"?{qs}" if qs else ""))
    assert status == 200, body
    return {o["key"]: o for o in body}


def _wait_until(page, js: str, timeout_ms: int = 20000) -> None:
    """Polling ueber evaluate (wait_for_function scheitert an der CSP ohne unsafe-eval)."""
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        if page.evaluate(js):
            return
        page.wait_for_timeout(200)
    raise AssertionError(f"Zustand nicht erreicht: {js}")


STATE = ("() => ({q: document.getElementById('sust-q1-yes').checked,"
         " t: document.getElementById('sust-excl-tobacco').disabled,"
         " tc: document.getElementById('sust-excl-tobacco').checked,"
         " a: document.getElementById('sust-excl-alcohol').disabled,"
         " aw: document.getElementById('sust-excl-why-alcohol').textContent})")


def test_unstubbed_exclusion_options_apply_only_the_latest_answer(server):  # noqa: F811
    sync_api = _playwright_sync_api()
    api = _Api(server["base"])
    status, login = api("POST", "/auth/login", {"username": USER, "password": PWD})
    if status != 200:
        api("POST", "/auth/bootstrap-admin", {"username": USER, "password": PWD, "full_name": "H11 Admin",
                                              "company_name": "Probe AG", "home_jurisdiction": "CH"})
        status, login = api("POST", "/auth/login", {"username": USER, "password": PWD})
    assert status == 200, login
    api.token = login["access_token"]
    advisor_id = api("GET", "/auth/me")[1]["id"]
    cid, mid = _seed_mandate(api, advisor_id, f"H11-{int(time.time())}", {})

    # Disjunkter Nachweis-Seed: je Nicht-Liquiditaets-Produkt ein Zwilling (API).
    originals = [p for p in _products(server["db"]) if p[3] not in LIQ]
    twins = []
    for pid, name, ptype, asset, sub, ccy in originals:
        status, body = api("POST", "/products", {
            "product_name": f"{name} (Zweitprodukt H11)", "product_type": ptype, "asset_class": asset,
            "sub_asset_class": sub, "currency": ccy, "suitability_profile_from": 1, "suitability_profile_to": 10})
        assert status == 201, body
        # Einzelberater-Freigabe der Entwurfs-Eignungsregel (eine Person in der Wegwerf-Verwaltung).
        status, approved = api("POST", f"/products/{body['id']}/eligibility-rule/approve", {
            "single_approver_attestation": True,
            "attestation_reason": "Livetest H11: synthetisches Zweitprodukt fuer disjunkte Ausschlussnachweise."})
        assert status == 200, approved
        twins.append(body["id"])
    _seed_evidence(server["db"], [p[0] for p in originals], "tobacco", advisor_id)
    _seed_evidence(server["db"], twins, "alcohol", advisor_id)

    # Server-Vertrag (Plausibilisierung des Seeds): einzeln waehlbar, zusammen nicht.
    none = _options(api, mid, [])
    assert none["tobacco"]["available"] and none["alcohol"]["available"], none["alcohol"]
    with_tobacco = _options(api, mid, ["tobacco"])
    assert not with_tobacco["alcohol"]["available"], with_tobacco["alcohol"]

    held: list = []
    calls: list[list[str]] = []

    def handle(route):
        selected = parse_qs(urlparse(route.request.url).query).get("selected", [])
        calls.append(selected)
        if selected == ["tobacco"] and not held:
            held.append(route)  # echte Antwort, nur verzoegert (s. u.)
            return
        route.continue_()

    with sync_api.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        errors: list[str] = []
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 1100})
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(server["base"] + "/app/ares.html")
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
            page.evaluate(f"loadClientById('{cid}')")
            page.wait_for_timeout(3000)
            page.evaluate("document.querySelectorAll('.overlay.open').forEach(function(o){o.classList.remove('open');})")
            page.evaluate("go('rp')")
            page.wait_for_selector("#sust-q1-yes", timeout=30000)
            # Karte erst bedienbar, wenn alle Nachlade-Anfragen durch sind (spaetes Neu-Rendern, E2 H-2).
            page.wait_for_load_state("networkidle", timeout=60000)
            page.wait_for_timeout(3000)
            page.route("**/sustainability-preferences/exclusion-options*", handle)
            page.check("#sust-q1-yes")
            _wait_until(page, "() => !document.getElementById('sust-excl-alcohol').disabled")
            start = page.evaluate(STATE)
            # 1) Tabak an -> Antwort zurueckgehalten; 2) Tabak ab -> juengste Antwort (beide frei).
            page.check("#sust-excl-tobacco")
            page.wait_for_timeout(300)
            assert held, calls
            page.uncheck("#sust-excl-tobacco")
            page.wait_for_timeout(2500)
            latest = page.evaluate(STATE)
            # 3) Die aeltere echte Antwort kommt jetzt (Alkohol waere damit gesperrt).
            held[0].continue_()
            page.wait_for_timeout(2500)
            after_stale = page.evaluate(STATE)
            # 4) Positivkontrolle ohne Verzoegerung: Tabak an -> Alkohol gesperrt mit Grund.
            assert after_stale["q"], after_stale  # Karte nicht zwischendurch neu aufgebaut
            page.check("#sust-excl-tobacco")
            _wait_until(page, "() => document.getElementById('sust-excl-alcohol').disabled")
            live_combo = page.evaluate(STATE)
        finally:
            browser.close()

    assert start["t"] is False and start["a"] is False, start
    assert latest["tc"] is False and latest["a"] is False, latest
    assert after_stale["a"] is False and after_stale["tc"] is False, after_stale  # alte Antwort verworfen
    assert live_combo["tc"] and live_combo["a"] is True and "Tabak" in live_combo["aw"], live_combo
    assert calls[:2] == [["tobacco"], []] and calls.count(["tobacco"]) == 2, calls
    assert not errors, errors


def test_ci_runs_this_live_test_with_playwright_required():
    workflow = (BACKEND.parent / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    job = workflow[workflow.index("\n  vitest:"):]
    assert 'ARES_REQUIRE_PLAYWRIGHT: "1"' in job
    assert "tests/test_livetest_h11_exclusion_options_unstubbed.py" in job


def test_refresh_uses_a_request_counter():
    src = (BACKEND.parent / "ares-desktop" / "frontend" / "sustainability-preferences.js").read_text(encoding="utf-8")
    fn = src[src.index("function sustRefreshExclusions("):]
    fn = fn[:fn.index("\n}\n")]
    assert "req=++SUST.exclReq" in fn and "req!==SUST.exclReq" in fn
