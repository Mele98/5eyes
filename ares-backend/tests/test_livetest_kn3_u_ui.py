"""KN3-U (Dok. 118, H-167 R2): Pflicht-Livetest der Classic-Berateroberflaeche
gegen das echte Backend, ohne Route-Stub.

Isolierter Backend-Prozess (Temp-DB/HOME/APPDATA/LOCALAPPDATA, Wegwerf-KEK,
freier Port), echte App ``/app/ares.html`` in Chromium, echter Login, echte
Klicks auf Speichern-Knoepfe. Publikationen entstehen ueber die echte API
(Generate -> Produktlauf -> Finalisieren -> Publish-Gate als Ein-Personen-Firma).

* E2E3-01  Kapitalschutz-Profil mit Aktienbestand: Karte "Verletzt", Kopfzeile
           zaehlt Aktien nicht als "im Band" (Band 0/0 = Obergrenze 0).
* E2E3-05  Berufsaenderung: kein lokales "Strategie veraltet", weiter publiziert.
* E2E3-06  Geburtsdatum: Ursache wortgleich aus ``freshness.causes``.
* N-917R2-03  Zielkonflikt-Banner von A steht nach dem Wechsel nicht mehr im DOM.
* E2E3-02  Kursaenderung in der Administration: Vermoegen, AA und Review zeigen
           den neuen CHF-Betrag ohne Mandatswechsel.
* E2E3-07  Hypothekarzins im Vermoegensdialog geaendert, waehrend die Cashflow-
           Seite offen ist: automatische Zeilen sofort neu.
* N-917R2-06  Ursache = Status-API (nicht 409-Text) auf AA, Portfolio, Review.
* E2E3-13  Amortisation nicht "unbefristet".
* E2E3-08/09/12/14/10  Depot ohne Aufteilung (Servermeldung, kein Versprechen),
           KYC-Formular bleibt gefuellt, neues Mandat sofort auffindbar, kein
           "veraltet" ohne Strategie, leere Prognose ohne fremde Achse.

Pflichtlauf im eigenen CI-Job "KN3-U Livetest (Playwright Pflicht)".
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from tests.test_livetest_e2b_strategy_blocks import _finalize_and_publish
from tests.test_livetest_k2_kernkette_ui import CLOSE, _Api, _load, _login, _open, _sync_api
from tests.test_livetest_kern_integration_r2 import _backend

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def server():
    _sync_api()
    with _backend(frozen=False) as srv:
        yield srv


def _shot(page, name, selector=None):
    target = os.environ.get("ARES_KN3U_SCREENSHOT_DIR")
    if target:
        Path(target).mkdir(parents=True, exist_ok=True)
        if selector:
            page.locator(selector).first.scroll_into_view_if_needed()
            page.locator(selector).first.screenshot(path=str(Path(target) / name))
        else:
            page.screenshot(path=str(Path(target) / name))


def _new_client(api, first, last, dob, positions, risk=None, mandate_type="Anlageberatung"):
    from tests.risk_fixture_helpers import standard_risk_payload

    advisor_id = api("GET", "/auth/me")[1]["id"]
    stamp = f"{first}-{time.time_ns()}"
    st, client = api("POST", "/clients", {"client_number": f"KN3U-{stamp}", "first_name": first, "last_name": last,
                                          "advisor_id": advisor_id, "household_type": "Einzelperson", "date_of_birth": dob})
    assert st == 201, client
    st, mandate = api("POST", f"/clients/{client['id']}/mandates", {"mandate_number": f"M-{stamp}", "mandate_type": mandate_type})
    assert st == 201, mandate
    if risk is not False:
        assert api("POST", f"/mandates/{mandate['id']}/risk-assessments", risk or standard_risk_payload())[0] == 201
    ids = []
    for pos in positions:
        st, body = api("POST", f"/clients/{client['id']}/wealth-positions", pos)
        assert st in (200, 201), body
        ids.append(body["id"])
    return client["id"], mandate["id"], ids


def _cashflows(api, cid, income=18000000, expense=12000000):
    for cf in ({"cashflow_type": "Income", "label": "Erwerb (fiktiv)", "amount_rappen": income, "valid_until": "2031-03-31"},
               {"cashflow_type": "Expense", "label": "Lebenshaltung (fiktiv)", "amount_rappen": expense, "valid_until": None}):
        st, body = api("POST", f"/clients/{cid}/cashflows", {**cf, "currency": "CHF", "frequency": "jaehrlich", "nature": "wiederkehrend",
                                                            "valid_from": "2026-12-01", "is_inflation_linked": False})
        assert st in (200, 201), body


def _esg_declined(api, mid):
    from core import sustainability_preference as sp

    st, body = api("POST", f"/mandates/{mid}/sustainability-preferences", {
        "questionnaire_version": sp.QUESTIONNAIRE_VERSION, "definition_hash": sp.definition_hash(),
        "response_status": "declined", "esg_relevance": None, "esg_characteristic": None, "exclusions": [],
        "information_acknowledged": False, "client_confirmed": True, "capture_channel": "in_person"})
    assert st == 201, body


def _publish(api, db, mid):
    st, body = api("POST", f"/mandates/{mid}/target-allocation/generate", {"preferences": {}})
    assert st == 200, body
    st, body = api("POST", f"/mandates/{mid}/recommendations/generate", {})
    assert st == 200, body
    _finalize_and_publish(api, db, mid)


def _overview(api, mid):
    st, body = api("GET", f"/mandates/{mid}/allocation-publication")
    assert st == 200, body
    return body


def _server_cause(api, mid):
    fresh = _overview(api, mid).get("freshness") or {}
    seen, texts = set(), []
    for c in fresh.get("causes") or []:
        text = ("Wechselkurs " + ", ".join(c["currencies"]) + " geändert") if c.get("kind") == "fx_rate" and c.get("currencies") else c.get("text")
        if text and text not in seen:
            seen.add(text)
            texts.append(text)
    return fresh.get("status"), "; ".join(texts)


def _chip_shows_server_cause(page, api, mid, timeout_s=60.0):
    """N-917R2-06 / H-185: Chip und Server-Ursache werden BEIDE wiederholt
    gelesen. Fertig erst, wenn die Server-Ursache in zwei Lesungen in Folge
    gleich ist UND der Chip genau sie zeigt ("Veraltet · " + Ursache). Sonst
    AssertionError mit den letzten Lesungen (Chip, Server), damit ein CI-Fehler
    zeigt, was die Oberflaeche tatsaechlich anzeigte."""
    deadline = time.monotonic() + timeout_s
    seen, prev = [], None
    while True:
        status, cause = _server_cause(api, mid)
        chip = page.evaluate(CHIP)
        seen.append({"status": status, "cause": cause, "chip": chip})
        if cause and cause == prev and chip == "Veraltet · " + cause:
            return status, cause, chip
        prev = cause
        if time.monotonic() > deadline:
            raise AssertionError(f"Chip zeigt nicht die Server-Ursache (letzte Lesungen): {seen[-6:]}")
        page.wait_for_timeout(500)


def _page(browser, srv, sync_api, errors):
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    _open(page, srv["base"], sync_api)
    _login(page)
    return page


def _go(page, pg, wait=2500):
    page.evaluate(CLOSE)
    page.evaluate(f"go('{pg}')")
    page.wait_for_timeout(wait)
    page.evaluate(CLOSE)


CHIP = "(document.getElementById('aa-publication-status')||{textContent:''}).textContent.trim()"
CARDS = """() => Array.prototype.map.call(document.querySelectorAll('#sr-implementation-steps > div'), function(c){return c.innerText.replace(/\\s+/g,' ').trim();})"""
BANNERS = """() => ['al-message-banner','rv-message-banner'].map(function(id){var b=document.getElementById(id);if(!b)return '';
  return Array.prototype.map.call(b.querySelectorAll('.al-banner-title,.al-banner-body,.al-banner-actions,.rv-message-title,.rv-message-body'),
    function(e){return e.textContent;}).join(' ').replace(/\\s+/g,' ').trim();})"""


def _persona_a(api, db):
    """Persona A (Dok. 118): Kapitalschutz, Depot 40/50/10 + Konto, Eigenheim mit Hypothek, Zielkonflikt."""
    from tests.risk_fixture_helpers import standard_risk_payload

    cid, mid, ids = _new_client(api, "Anna", "Bandprobe-Fiktiv", "1966-03-10", [
        {"label": "Depot Anna (fiktiv)", "position_type": "Depot", "assignment": "Beratungsvermögen", "current_value_rappen": 40_000_000,
         "currency": "CHF", "depot_bank": "Testbank Fiktiv", "alloc_equities_bps": 4000, "alloc_bonds_bps": 5000, "alloc_liquidity_bps": 1000},
        {"label": "Privatkonto Anna (fiktiv)", "position_type": "Liquidität", "assignment": "Beratungsvermögen",
         "current_value_rappen": 5_000_000, "currency": "CHF", "liquidity_instrument": "Kontoguthaben"},
    ], risk=standard_risk_payload(income=1, wealth=1, savings=1, goal=0, pref=0, behav=0))
    _cashflows(api, cid)
    st, body = api("POST", f"/mandates/{mid}/goals", {
        "goal_family": "Vermögen", "goal_type": "Vermögensziel", "label": "Seehaus Bandprobe (fiktiv)", "rank": 1,
        "target_wealth_rappen": 5_000_000_000, "horizon_years": 8, "hardness": "Primär", "value_mode": "nominal"})
    assert st == 201, body
    _esg_declined(api, mid)
    _publish(api, db, mid)
    return cid, mid


def test_kn3u_kapitalschutz_band_review_causes_and_banner_reset(server):
    sync_api = _sync_api()
    api = _Api(server["base"]).login()
    cid, mid = _persona_a(api, server["db"])
    st, payload = api("GET", f"/mandates/{mid}/target-allocation/current/payload")
    assert st == 200, payload
    eq = next(b for b in payload["buckets"] if b["asset_class"] == "Aktien")
    assert (eq["band_min_bps"], eq["band_max_bps"], eq["target_weight_bps"]) == (0, 0, 0), eq  # Profil schliesst Aktien aus
    assert eq["current_weight_bps"] > 3000, eq
    conflict = [m for m in payload.get("messages") or [] if m.get("severity") in ("conflict", "warning")]
    other_cid, _omid, _ = _new_client(api, "Otto", "Ohnekonflikt-Fiktiv", "1985-01-01", [
        {"label": "Depot Otto (fiktiv)", "position_type": "Depot", "assignment": "Beratungsvermögen", "current_value_rappen": 20_000_000,
         "currency": "CHF", "depot_bank": "Testbank Fiktiv", "alloc_equities_bps": 6000, "alloc_bonds_bps": 3000, "alloc_liquidity_bps": 1000}])

    with sync_api.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        errors: list[str] = []
        try:
            page = _page(browser, server, sync_api, errors)
            _load(page, cid, "rv")
            page.wait_for_function("() => document.querySelectorAll('#sr-implementation-steps > div').length >= 1", timeout=60000)
            page.wait_for_timeout(1500)
            cards = page.evaluate(CARDS)
            hero = page.evaluate("(document.getElementById('rv-hero')||{innerText:''}).innerText")
            _shot(page, "kn3u_01_review_kopfzeile.png")
            _shot(page, "kn3u_01_review_aktien_verletzt.png", "#sr-implementation-steps")
            banners_a = page.evaluate(BANNERS)

            # E2E3-05: nur den Beruf aendern (echte Maske, echter Speichern-Knopf).
            _go(page, "sd")
            page.evaluate("()=>{openStammdatenModal();}")
            page.wait_for_selector("#es-profession", state="visible", timeout=15000)
            page.fill("#es-profession", "Gärtnerin (fiktiv)")
            page.click("#btn-es-save")
            page.wait_for_function("() => /Gespeichert/.test((document.getElementById('es-error')||{textContent:''}).textContent)", timeout=30000)
            page.wait_for_timeout(2500)
            _go(page, "al")
            prof = page.evaluate(f"""({{chip:{CHIP},
              dirty:(function(){{var b=document.getElementById('al-dirty-banner');return b?getComputedStyle(b).display:'none';}})(),
              notice:(document.getElementById('al-dirty-banner-body')||{{textContent:''}}).textContent,
              stale:document.getElementById('page-al').classList.contains('aa-stale'),
              umsetzen:(function(){{var b=document.getElementById('btn-portfolio-umsetzen');return b?b.style.display:'';}})()}})""")
            _shot(page, "kn3u_05_beruf_bleibt_publiziert.png")
            prof_api = _overview(api, mid)

            # E2E3-06: Geburtsdatum aendern -> Ursache aus freshness.causes.
            _go(page, "sd")
            page.evaluate("()=>{openStammdatenModal();}")
            page.wait_for_selector("#es-dob", state="visible", timeout=15000)
            page.fill("#es-dob", "1965-03-10")
            page.click("#btn-es-save")
            page.wait_for_function("() => /Gespeichert/.test((document.getElementById('es-error')||{textContent:''}).textContent)", timeout=30000)
            page.wait_for_timeout(3000)
            dob_status, dob_cause = _server_cause(api, mid)
            _go(page, "al", 3500)
            page.wait_for_function("() => /Veraltet/.test(" + CHIP + ")", timeout=60000)
            aa_chip = page.evaluate(CHIP)
            _shot(page, "kn3u_06_geburtsdatum_ursache.png")
            _go(page, "po")
            po = page.evaluate("({status:(document.getElementById('po-status')||{textContent:''}).textContent,"
                               "umsetzen:(document.getElementById('btn-portfolio-umsetzen')||{style:{}}).style.display})")
            _go(page, "rv")
            rv = page.evaluate("(document.getElementById('rv-stale-cause')||{textContent:''}).textContent")

            # N-917R2-03: Wechsel zu einem Kunden ohne Zielkonflikt -- kein Banner-Text von A im DOM.
            _load(page, other_cid, "al")
            banners_al = page.evaluate(BANNERS)
            _go(page, "rv")
            banners_rv = page.evaluate(BANNERS)
        finally:
            browser.close()

    # E2E3-01: Karte und Kopfzeile bewerten Aktien gleich (verletzt).
    aktien = [c for c in cards if "Aktien" in c]
    assert aktien and all("Verletzt" in c and "Im Band" not in c for c in aktien), cards
    in_band_cards = [c for c in cards if c.startswith("Im Band")]
    m = __import__("re").search(r"(\d+)/(\d+) Anlageklassen im Band", hero)
    assert m, hero
    assert int(m.group(1)) <= int(m.group(2)) - 1, hero  # Aktien zaehlt nicht als "im Band"
    assert "Aktien" not in " ".join(in_band_cards), cards
    # E2E3-05
    assert prof_api["publication_status"] == "PUBLISHED" and prof_api["freshness"]["status"] == "FRESH", prof_api
    assert prof["chip"].startswith("Publiziert"), prof
    assert prof["dirty"] == "none" and "Anlagehorizont" not in prof["notice"] and prof["stale"] is False, prof
    assert prof["umsetzen"] != "none", prof
    # E2E3-06 / N-917R2-06: UI-Ursache = Status-API wortgleich.
    assert dob_status == "STALE" and "Stammdaten des Kunden geändert" in dob_cause, dob_cause
    assert aa_chip == "Veraltet · " + dob_cause, (aa_chip, dob_cause)
    # Portfolio: "Portfolio umsetzen" gesperrt; die Statuszeile kann ein spaeterer Portfolio-Hinweis ueberschreiben.
    assert po["umsetzen"] == "none" and rv == dob_cause, (po, rv, dob_cause)
    # N-917R2-03 (mit echtem Zielkonflikt bei A, sonst waere die Pruefung leer)
    assert conflict and any("Seehaus Bandprobe" in b for b in banners_a), (conflict, banners_a)
    assert banners_al == ["", ""] and banners_rv == ["", ""], (banners_al, banners_rv)
    assert not errors, errors


def test_kn3u_amounts_reload_after_fx_and_mortgage_change(server):
    sync_api = _sync_api()
    api = _Api(server["base"]).login()
    assert api("PUT", "/fx-rates", {"rates": [{"currency": "USD", "rate": 0.88, "source": "Manual", "confirm_current": True}]})[0] in (200, 201)
    st, mand = 0, None
    cid, mid, ids = _new_client(api, "Bea", "Kursprobe-Fiktiv", "1986-06-01", [
        {"label": "Depot CHF Bea (fiktiv)", "position_type": "Depot", "assignment": "Beratungsvermögen", "current_value_rappen": 40_000_000,
         "currency": "CHF", "depot_bank": "Testbank Fiktiv", "alloc_equities_bps": 6000, "alloc_bonds_bps": 3000, "alloc_liquidity_bps": 1000},
        {"label": "Depot USD Bea (fiktiv)", "position_type": "Depot", "assignment": "Beratungsvermögen", "current_value_rappen": 10_000_000,
         "currency": "USD", "depot_bank": "Testbank Fiktiv", "alloc_equities_bps": 7000, "alloc_bonds_bps": 3000},
        {"label": "Eigenheim Bea (fiktiv)", "position_type": "Immobilien", "assignment": "Anderes Vermögen", "current_value_rappen": 80_000_000,
         "currency": "CHF", "property_usage": "Selbstgenutzt"},
    ])
    st, body = api("POST", f"/clients/{cid}/wealth-positions", {
        "label": "Hypothek Bea (fiktiv)", "position_type": "Hypothek", "assignment": "Verbindlichkeit", "current_value_rappen": 50_000_000,
        "currency": "CHF", "mortgage_interest_rate_bps": 180, "mortgage_amortization_rappen": 500_000,
        "mortgage_amortization_type": "Indirekt (Säule 3a)", "mortgage_linked_property_id": ids[2]})
    assert st in (200, 201), body
    mortgage_id = body["id"]
    _cashflows(api, cid)
    _esg_declined(api, mid)
    _publish(api, server["db"], mid)
    assert _overview(api, mid)["freshness"]["status"] == "FRESH"

    with sync_api.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        errors: list[str] = []
        try:
            page = _page(browser, server, sync_api, errors)
            _load(page, cid, "vg")
            page.wait_for_function("() => /488/.test(document.getElementById('page-vg').innerText)", timeout=60000)
            # E2E3-02: Kurs in der Administration aendern (echter Speichern-Knopf), Mandat bleibt offen.
            page.evaluate("()=>{loadAdminFxRates();}")
            page.wait_for_selector(".admin-fx-rate-input[data-currency='USD']", state="attached", timeout=30000)
            page.evaluate("""()=>{var i=document.querySelector(".admin-fx-rate-input[data-currency='USD']");i.value='0.9';
              document.querySelector(".admin-fx-rate-confirm[data-currency='USD']").checked=true;}""")
            page.evaluate("()=>{var b=Array.prototype.find.call(document.querySelectorAll('button'),function(x){return /Wechselkurse speichern/.test(x.textContent);});b.click();}")
            page.wait_for_function("() => /490/.test(document.getElementById('page-vg').innerText)", timeout=60000)
            vg = page.evaluate("document.getElementById('page-vg').innerText")
            _shot(page, "kn3u_02_vermoegen_490.png")
            _go(page, "al", 3000)
            page.wait_for_function("() => /490/.test((document.getElementById('dnleg')||{innerText:''}).innerText)", timeout=60000)
            aa = page.evaluate("({leg:(document.getElementById('dnleg')||{innerText:''}).innerText,chip:" + CHIP + ","
                               "center:(document.querySelector('.dcv')||{innerText:''}).innerText})")
            _shot(page, "kn3u_02_aa_strategiebasis_490.png")
            _go(page, "rv")
            rv_wealth = page.evaluate("(document.getElementById('sr-wealth')||{textContent:''}).textContent")
            _shot(page, "kn3u_02_review_490.png")

            # E2E3-07: Cashflow-Seite offen, Hypothekarzins im Vermoegensdialog aendern -> Zeilen sofort neu.
            _go(page, "cf")
            page.wait_for_function("() => /Hypothekarzins/.test(document.getElementById('abfluss-rows').innerText)", timeout=60000)
            cf_before = page.evaluate("document.getElementById('abfluss-rows').innerText")
            page.evaluate(f"()=>{{openWealthPositionEditor('{mortgage_id}');}}")
            page.wait_for_selector("#maw-mortgage-rate", state="visible", timeout=15000)
            page.fill("#maw-mortgage-rate", "2.1")
            page.click("#btn-maw-save")
            page.wait_for_function("() => /10.?500/.test(document.getElementById('abfluss-rows').innerText)", timeout=60000)
            cf_after = page.evaluate("document.getElementById('abfluss-rows').innerText")
            page_now = page.evaluate("(document.querySelector('.tstep.active')||{dataset:{}}).dataset.page")
            _shot(page, "kn3u_07_cashflow_hypothek_neu.png")
            _go(page, "al", 3000)
            # H-185: Ursache nicht einmalig 2,5 s nach dem Speichern lesen, sondern
            # Chip und Status-API gemeinsam pollen, bis beide uebereinstimmen.
            status, cause, aa_chip = _chip_shows_server_cause(page, api, mid)
            _go(page, "po")
            po = page.evaluate("({status:(document.getElementById('po-status')||{textContent:''}).textContent,"
                               "umsetzen:(document.getElementById('btn-portfolio-umsetzen')||{style:{}}).style.display})")
            _go(page, "rv")
            rv = page.evaluate("(document.getElementById('rv-stale-cause')||{textContent:''}).textContent")
        finally:
            browser.close()

    # E2E3-02
    assert "490'000" in vg and "488'000" not in vg, vg
    assert "490'000" in aa["leg"] and "488'000" not in aa["leg"], aa
    assert "490" in aa["center"] and "488" not in aa["center"], aa  # Tortenmitte "Beratungsvermögen"
    assert aa["chip"].startswith("Veraltet · Wechselkurs USD geändert"), aa
    assert "490" in rv_wealth and "488" not in rv_wealth, rv_wealth
    # E2E3-07 / E2E3-13
    assert "9'000" in cf_before and "10'500" in cf_after and "9'000" not in cf_after.split("Amortisation")[0], (cf_before, cf_after)
    assert page_now == "cf", page_now
    amort = [line for line in cf_after.splitlines() if "Amortisation" in line or "Pensionierung" in line or "Planungshorizont" in line]
    assert "unbefristet" not in " ".join(amort) and any("bis" in line for line in amort), cf_after
    # N-917R2-06: Ursache = Status-API, auf allen drei Seiten gleich.
    assert status == "STALE" and "Wechselkurs USD geändert" in cause and "Vermögen" in cause, cause
    assert aa_chip == "Veraltet · " + cause and po["umsetzen"] == "none" and rv == cause, (aa_chip, po, rv, cause)
    assert not errors, errors


def test_kn3u_forms_new_mandate_and_empty_strategy(server):
    sync_api = _sync_api()
    api = _Api(server["base"]).login()
    # Kunde ohne KYC (nach den Publikationen angelegt) und nur mit Risikoprofil.
    cid, mid, _ = _new_client(api, "Emil", "NurRisiko-Fiktiv", "1979-02-02", [])
    # Vorheriger Kunde mit berechneter Strategie (grosse Prognose-Achse).
    big_cid, big_mid, _ = _new_client(api, "Gustav", "Grossachse-Fiktiv", "1970-07-07", [
        {"label": "Depot Gustav (fiktiv)", "position_type": "Depot", "assignment": "Beratungsvermögen", "current_value_rappen": 500_000_000,
         "currency": "CHF", "depot_bank": "Testbank Fiktiv", "alloc_equities_bps": 6000, "alloc_bonds_bps": 3000, "alloc_liquidity_bps": 1000}])
    st, body = api("POST", f"/mandates/{big_mid}/target-allocation/generate", {"preferences": {}})
    assert st == 200, body
    first = f"Lena{time.time_ns() % 100000}"

    with sync_api.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        errors: list[str] = []
        try:
            page = _page(browser, server, sync_api, errors)
            # E2E3-10/14: Kunde mit Strategie (Achse gross), dann E ohne Strategie.
            _load(page, big_cid, "al")
            page.wait_for_timeout(2500)
            big_ymax = page.evaluate("(typeof charts!=='undefined'&&charts.opt&&charts.opt.options.scales.y.max)||null")
            _load(page, cid, "al")
            page.wait_for_timeout(2500)
            e_state = page.evaluate("""() => ({
              dirty:(function(){var b=document.getElementById('al-dirty-banner');return b?getComputedStyle(b).display:'none';})(),
              leg:(document.getElementById('dnleg')||{innerText:''}).innerText,
              ymax:(typeof charts!=='undefined'&&charts.opt&&charts.opt.options.scales.y.max)||null,
              values:(typeof charts!=='undefined'&&charts.opt)?projectionChartValues(charts.opt).length:0})""")
            _shot(page, "kn3u_14_ohne_strategie.png")
            # Risikoprofil-Speichern ist ein typischer Ausloeser; ohne Strategie bleibt "veraltet" weg.
            page.evaluate("markStrategyDirty('Risikoprofil gespeichert: Strategie neu berechnen.', true)")
            page.wait_for_timeout(500)
            after_mark = page.evaluate("""() => ({dirty:(function(){var b=document.getElementById('al-dirty-banner');return b?getComputedStyle(b).display:'none';})(),
              leg:(document.getElementById('dnleg')||{innerText:''}).innerText})""")

            # E2E3-08: Depot ohne Aufteilung -> Servermeldung, kein Versprechen einer Annahme.
            _go(page, "vg")
            page.evaluate("()=>{openLegacyWealthModalRedirect('Depot');}")
            page.wait_for_selector("#maw-depot-label", state="visible", timeout=15000)
            hint = page.evaluate("document.getElementById('aw-alloc-split').textContent")
            page.fill("#maw-depot-label", "Depot Emil (fiktiv)")
            page.fill("#maw-depot-value", "100000")
            page.click("#btn-maw-save")
            page.wait_for_function("() => { var e=document.getElementById('maw-error'); return e && /Fehler/.test(e.textContent); }", timeout=30000)
            depot_err = page.evaluate("document.getElementById('maw-error').textContent")
            _shot(page, "kn3u_08_depot_ohne_aufteilung.png")
            positions = api("GET", f"/clients/{cid}/wealth-positions")[1]
            page.evaluate(CLOSE)

            # E2E3-09: KYC ohne "Naechste Aktualisierung" -> Formular bleibt gefuellt.
            _go(page, "sd", 3000)
            page.wait_for_selector("#kyc-form", state="attached", timeout=60000)
            fill = """()=>{var s=function(id,v){var e=document.getElementById(id);e.value=v;};
              s('kyc-form','A');s('kyc-date','2026-11-01');s('kyc-ref','REF-FIKTIV-1');s('kyc-risk','normal');s('kyc-pep','false');
              s('kyc-ident-date','2026-11-01');document.getElementById('kyc-ident-ok').checked=true;}"""
            snap = """()=>['kyc-form','kyc-date','kyc-ref','kyc-risk','kyc-pep','kyc-review','kyc-ident-date'].map(function(id){return document.getElementById(id).value;})
              .concat([document.getElementById('kyc-ident-ok').checked])"""
            page.evaluate(fill)
            page.evaluate("()=>{createKycConfirmation();}")
            page.wait_for_timeout(1500)
            kyc_missing = page.evaluate(snap)
            # Serverfehler (Datum vor dem Formulardatum): Panel wird neu gezeichnet, Eingaben bleiben.
            page.evaluate("()=>{document.getElementById('kyc-review').value='2026-10-01';}")
            page.evaluate("()=>{createKycConfirmation();}")
            page.wait_for_timeout(3000)
            kyc_server = page.evaluate(snap)
            _shot(page, "kn3u_09_kyc_bleibt_gefuellt.png", "#sd-client-compliance")

            # E2E3-12: neues Mandat ueber den echten Dialog, sofort per Suche auffindbar.
            page.evaluate(CLOSE)
            page.evaluate("()=>{om('m-nc');}")
            page.wait_for_selector("#nc-firstname", state="visible", timeout=15000)
            page.fill("#nc-firstname", first)
            page.fill("#nc-lastname", "Neuanlage-Fiktiv")
            page.click("#btn-nc-submit")
            page.wait_for_function("() => !document.getElementById('m-nc').classList.contains('open')", timeout=60000)
            page.wait_for_timeout(1500)
            page.fill("#client-search", first.lower())
            page.evaluate("()=>{filterClientRegister(document.getElementById('client-search').value);}")
            page.wait_for_timeout(500)
            found = page.evaluate("""(q) => Array.prototype.filter.call(document.querySelectorAll('#sbl .client'), function(el){
              return el.style.display!=='none' && el.innerText.toLowerCase().indexOf(q)>=0;}).length""", first.lower())
            prompt = page.evaluate("(document.getElementById('sb-prompt')||{textContent:''}).textContent")
            _shot(page, "kn3u_12_neues_mandat_gefunden.png")
        finally:
            browser.close()

    total_clients = len(api("GET", "/clients")[1])
    # E2E3-14 / E2E3-10
    assert e_state["dirty"] == "none" and "veraltet" not in e_state["leg"].lower(), e_state
    assert big_ymax, big_ymax
    assert e_state["values"] > 0 or e_state["ymax"] is None, (e_state, big_ymax)
    assert after_mark["dirty"] == "none" and "veraltet" not in after_mark["leg"].lower(), after_mark
    # E2E3-08
    assert "automatisch" not in hint and "Pflicht" in hint, hint
    assert "Value error" not in depot_err and "automatisch" not in depot_err and depot_err.startswith("Fehler"), depot_err
    assert not [p for p in positions if p.get("label") == "Depot Emil (fiktiv)"], positions
    # E2E3-09
    expected = ["A", "2026-11-01", "REF-FIKTIV-1", "normal", "false"]
    assert kyc_missing[:5] == expected and kyc_missing[5] == "" and kyc_missing[6] == "2026-11-01" and kyc_missing[7] is True, kyc_missing
    assert kyc_server[:5] == expected and kyc_server[5] == "2026-10-01" and kyc_server[7] is True, kyc_server
    # E2E3-12
    assert found == 1, found
    assert prompt.startswith(f"{total_clients} Mandate"), (prompt, total_clients)
    assert not errors, errors


def test_ci_runs_this_behaviour_test_with_playwright_required():
    workflow = (BACKEND.parent / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    assert "test_livetest_kn3_u_ui.py" in workflow
