"""KN-U Pflicht-Livetest (Dok. 117, Classic-Berateroberflaeche).

Echter Ablauf wie K2: isolierter Backend-Prozess (Temp-DB/HOME/APPDATA, freier
Port), echte App ``/app/ares.html`` in Chromium, echter Login. Kopfzeile und
Mandatsanlage mit echten Mausklicks (nicht per evaluate).

* E2E2-01: A (mit Strategie) -> C (neu, ohne Strategie) bzw. B (ohne Strategie):
  keine Werte von A in Review-Kacheln, Cashflow-HUD oder offenen Dialogen; auch
  nach Neuladen mit automatisch geoeffnetem Kunden.
* E2E2-02: Banner "Datenuebermittlung" verdeckt die Kopfzeile nicht.
* E2E2-05: Kursaenderung ohne Neuladen -> "Veraltet" mit derselben Ursache auf
  Asset Allokation, Portfolio und Review; nach Neuladen dieselbe Ursache.
* E2E2-06 / E2E-17: neues Mandat kennt seine Basiswaehrung; kein "Keine Mandate erfasst.".
* E2E2-07 / N-917-03 / E2E2-08 / E2E2-15: Umrechnung offen mit Ursache,
  Beratungsvermoegen wenn belegt, Ist-Projektion mit Hypothekar-Grund,
  Kurseditor nach dem Speichern.
"""
from __future__ import annotations

import time
from pathlib import Path

from product_evidence_test_support import provision_database
from tests.test_livetest_k2_kernkette_ui import (  # noqa: F401  (server = Fixture)
    CLOSE, PWD, USER, _Api, _chf_depot, _client, _load, _login, _open, _shot, _sync_api, server,
)


def _tiles(page):
    return page.evaluate("""(function(){function t(id){var e=document.getElementById(id);return e?e.textContent.trim():null;}
      var hud=document.getElementById('cf-projection');
      return {risk:t('sr-risk-score'),profile:t('sr-risk-profile'),wealth:t('sr-wealth'),goal:t('sr-goal-score'),
        proj:t('sr-proj-wealth'),strategy:t('sr-strategy-name'),horizon:t('sr-horizon'),
        hud:hud?(hud.style.display==='none'?'':hud.innerText):'',
        open:Array.from(document.querySelectorAll('.overlay.open')).map(function(o){return o.id;})};})()""")


def _compute(page):
    page.evaluate("()=>{calculateInvestmentStrategy();}")
    page.wait_for_function("() => !!(strategyState&&strategyState.allocation&&strategyState.allocation.target_allocation"
                           "&&strategyState.allocation.target_allocation.id&&!strategyState.loading)", timeout=240000)
    page.wait_for_timeout(1500)
    page.evaluate(CLOSE)


def _real_click_ok(page, selector):
    """Echter Mausklick: Playwright prueft Sichtbarkeit und dass kein anderes Element den Klick abfaengt."""
    page.locator(selector).first.click(timeout=8000)
    return True


def test_kn_u_mandate_switch_banner_and_new_mandate(server):
    """E2E2-01, E2E2-02, E2E2-06, E2E-17."""
    sync_api = _sync_api()
    api = _Api(server).login()
    cid_a, mid_a = _client(api, "Anna", [_chf_depot(45000000)])
    cid_b, _mid_b = _client(api, "Bea", [_chf_depot(20000000)], mandate_type="Vermögensverwaltung")
    with sync_api.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        errors: list[str] = []
        try:
            ctx = browser.new_context(viewport={"width": 1500, "height": 950})
            page = ctx.new_page()
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            _open(page, server, sync_api)
            _login(page)
            page.wait_for_selector("#pg-egress-banner", timeout=20000)
            banner = page.evaluate("""(function(){var b=document.getElementById('pg-egress-banner').getBoundingClientRect();
              var t=document.querySelector('.topbar').getBoundingClientRect();var l=document.querySelector('.layout').getBoundingClientRect();
              return {bTop:b.top,bBottom:b.bottom,tBottom:t.bottom,layoutTop:l.top};})()""")
            _shot(page, "knu_e2e2_02_banner.png")
            # E2E2-02: echte Mausklicks auf Kopfzeile (Admin, Schrittnavigation, + Mandat).
            page.locator("#btn-admin-open").click(timeout=8000)
            page.wait_for_timeout(1500)
            admin_open = page.evaluate("document.getElementById('m-admin').classList.contains('open')")
            page.evaluate("cm('m-admin')")
            page.locator(".tnav .tstep").nth(1).click(timeout=8000)
            page.wait_for_timeout(800)
            step_page = page.evaluate("document.querySelector('.page.active')&&document.querySelector('.page.active').id")
            page.evaluate(CLOSE)

            # A mit Strategie.
            _load(page, cid_a, "al")
            _compute(page)
            page.evaluate("go('rv')")
            page.wait_for_timeout(2500)
            page.evaluate(CLOSE)
            tiles_a = _tiles(page)
            _shot(page, "knu_e2e2_01_review_A.png", "#page-rv")
            # Offener mandatsgebundener Dialog von A (Handelsliste), Wechsel zu B ohne Strategie
            # (wie das automatische Oeffnen: programmatischer Wechsel, der Dialog verdeckt die Seitenleiste).
            page.evaluate("om('m-tl')")
            page.evaluate(f"loadClientById('{cid_b}')")
            page.wait_for_timeout(3000)
            tl_after_switch = page.evaluate("document.getElementById('m-tl').classList.contains('open')")
            page.evaluate("go('rv')")
            page.wait_for_timeout(2500)
            page.evaluate(CLOSE)
            tiles_b = _tiles(page)
            _shot(page, "knu_e2e2_01_review_B.png", "#page-rv")
            # Neues Mandat C ueber die Maske (echter Klick auf "+ Mandat").
            page.locator(".topbar button:has-text('Mandat')").first.click(timeout=8000)
            page.wait_for_selector("#m-nc.open", timeout=10000)
            page.fill("#nc-firstname", "Carla")
            page.fill("#nc-lastname", "Testkundin-Fiktiv")
            page.fill("#nc-dob", "1980-03-01")
            page.locator("#btn-nc-submit").click(timeout=8000)
            page.wait_for_function("() => !document.getElementById('m-nc').classList.contains('open')", timeout=30000)
            page.wait_for_timeout(1500)
            page.evaluate(CLOSE)
            new_mandate = page.evaluate("""({ccy:mandateCurrency(),birth:(currentMandateData||{}).client_birth_year||null,
              sidebar:document.getElementById('sbl').innerText})""")
            page.evaluate("go('rv')")
            page.wait_for_timeout(2500)
            page.evaluate(CLOSE)
            tiles_c = _tiles(page)
            _shot(page, "knu_e2e2_01_review_C.png", "#page-rv")
            page.evaluate("go('cf')")
            page.wait_for_timeout(2000)
            page.evaluate(CLOSE)
            hud_c = _tiles(page)["hud"]
            cf_text = page.evaluate("document.getElementById('page-cf').innerText")
            _shot(page, "knu_e2e2_01_cashflow_C.png", "#page-cf")

            # Neuladen mit automatisch geoeffnetem Kunden A, dann B.
            _load(page, cid_a, "rv")
            page.reload()
            page.wait_for_timeout(2500)
            try:
                page.click("#intro-screen .intro-skip", timeout=3000)
            except sync_api.Error:
                pass
            page.evaluate("document.getElementById('intro-screen')&&document.getElementById('intro-screen').remove()")
            if page.is_visible("#login-username"):
                _login(page)
            page.wait_for_timeout(3500)
            page.evaluate(CLOSE)
            auto_client = page.evaluate("currentClientId")
            page.evaluate("go('rv')")
            page.wait_for_timeout(2000)
            _load(page, cid_b, "rv")
            page.wait_for_timeout(2500)
            tiles_b2 = _tiles(page)
            _shot(page, "knu_e2e2_01_review_B_nach_reload.png", "#page-rv")
            # Abmelden mit echtem Mausklick (letzter Schritt).
            page.locator("#btn-logout").click(timeout=8000)
            page.wait_for_timeout(1500)
            logged_out = page.is_visible("#login-username")
        finally:
            browser.close()

    assert banner["bTop"] >= banner["tBottom"] - 1, banner
    assert banner["layoutTop"] >= banner["bBottom"] - 1, banner
    assert admin_open is True and step_page, (admin_open, step_page)
    assert tiles_a["risk"] not in ("—", None) and tiles_a["wealth"] not in ("—", None), tiles_a
    a_values = {tiles_a["wealth"], tiles_a["goal"], tiles_a["proj"]} - {"—", "", None}
    assert new_mandate["ccy"] == "CHF" and new_mandate["birth"] == 1980, new_mandate
    assert "Keine Mandate erfasst" not in new_mandate["sidebar"], new_mandate
    assert tl_after_switch is False, "Dialog von A bleibt beim Wechsel offen"
    for tiles in (tiles_c, tiles_b, tiles_b2):
        assert not (a_values & {tiles["wealth"], tiles["goal"], tiles["proj"]}), (tiles, tiles_a)
        assert tiles["goal"] == "—" and tiles["proj"] == "—", tiles
        assert "m-tl" not in tiles["open"], tiles
    assert tiles_c["risk"] == "—" and tiles_c["wealth"] == "—", tiles_c
    assert tiles_b["wealth"] != tiles_a["wealth"] and tiles_b2["wealth"] == tiles_b["wealth"], (tiles_b, tiles_b2)
    assert hud_c == "", hud_c
    assert "Zuflusse" not in cf_text and "Abflusse" not in cf_text and "Vermogenszuflusse" not in cf_text, cf_text
    assert auto_client in (cid_a, cid_b, None)
    assert logged_out is True
    assert not errors, errors


def test_kn_u_stale_publication_cause_without_reload(server):
    """E2E2-05 (UI-Teil), E2E2-15 (Kurseditor), Annahme KN-B per Route."""
    sync_api = _sync_api()
    api = _Api(server).login()
    assert api("PUT", "/fx-rates", {"rates": [{"currency": "USD", "rate": 0.88, "source": "Manual", "confirm_current": True}]})[0] in (200, 201)
    cid, mid = _client(api, "Bea", [_chf_depot(40000000), {
        "label": "Depot USD (fiktiv)", "position_type": "Depot", "assignment": "Beratungsvermögen",
        "current_value_rappen": 10000000, "currency": "USD", "depot_bank": "Testbank Fiktiv",
        "alloc_equities_bps": 7000, "alloc_bonds_bps": 3000}], mandate_type="Vermögensverwaltung")
    cause = "Wechselkurs USD geändert"
    with sync_api.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        errors: list[str] = []
        try:
            page = browser.new_page(viewport={"width": 1500, "height": 950})
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            _open(page, server, sync_api)
            _login(page)
            _load(page, cid, "al")
            _compute(page)
            # Publikation per Route (Publizieren braucht Finalisierung + Freigabe; Status ist Serverwahrheit).
            ta = page.evaluate("strategyState.allocation.target_allocation.id")
            published = {"mandate_id": mid, "target_allocation_id": ta, "publication_status": "PUBLISHED",
                         "validation_status": "VALID", "blocker_codes": [], "can_publish": False,
                         "active_publication": {"status": "PUBLISHED", "approval_mode": "single_approver_attested",
                                                "approval_mode_label": "Einzelfreigabe"}}
            import json as _json
            page.route("**/allocation-publication", lambda route: route.fulfill(
                status=200, content_type="application/json", body=_json.dumps(published)))
            page.evaluate("()=>refreshAllocationPublication(true)")
            page.wait_for_timeout(1200)
            chip_before = page.evaluate("document.getElementById('aa-publication-status').textContent")
            # Kurs im Schnelleditor aendern (ohne Neuladen).
            page.evaluate("()=>{openFxQuickEditor(['USD']);}")
            page.wait_for_selector("#fxq-rate-USD", timeout=15000)
            page.fill("#fxq-rate-USD", "0.9")
            page.check("#fxq-grid .fxq-confirm[data-currency='USD']")
            page.click("#btn-fxq-save")
            page.wait_for_function("() => /Gespeichert/.test(document.getElementById('fxq-status').textContent)", timeout=30000)
            page.wait_for_function("() => /Veraltet/.test(document.getElementById('aa-publication-status').textContent)", timeout=60000)
            # KN3-U: der Editor laedt nach dem Neuladen der Betraege neu ("Lädt …"); erst den neuen Stand lesen.
            page.wait_for_function("() => { var t=document.getElementById('fxq-grid').innerText; return /manuell/.test(t) && !/Lädt/.test(t); }", timeout=30000)
            page.wait_for_timeout(1500)
            page.wait_for_function("() => { var t=document.getElementById('fxq-grid').innerText; return /manuell/.test(t) && !/Lädt/.test(t); }", timeout=30000)
            editor = page.evaluate("document.getElementById('fxq-grid').innerText")
            _shot(page, "knu_e2e2_15_kurseditor_nach_speichern.png", "#m-fx-quick .modal")
            page.evaluate("cm('m-fx-quick')")
            aa = page.evaluate("""({chip:document.getElementById('aa-publication-status').textContent,
              banner:document.getElementById('al-dirty-banner').style.display,
              body:document.getElementById('al-dirty-banner-body').textContent,
              hasAlloc:!!strategyState.allocation,
              pubBtn:(document.getElementById('btn-aa-publish')||{style:{}}).style.display})""")
            _shot(page, "knu_e2e2_05_aa_veraltet.png")
            page.evaluate("go('po')")
            page.wait_for_timeout(2500)
            page.evaluate(CLOSE)
            po = page.evaluate("(document.getElementById('po-status')||{textContent:''}).textContent")
            _shot(page, "knu_e2e2_05_portfolio_veraltet.png")
            page.evaluate("go('rv')")
            page.wait_for_timeout(2500)
            page.evaluate(CLOSE)
            rv = page.evaluate("(document.getElementById('rv-hero')||{innerText:''}).innerText")
            _shot(page, "knu_e2e2_05_review_veraltet.png", "#page-rv")
            # Nach Neuladen: dieselbe Ursache (aus dem 409 des Payload-Abrufs).
            page.unroute("**/allocation-publication")
            page.reload()
            page.wait_for_timeout(2500)
            try:
                page.click("#intro-screen .intro-skip", timeout=3000)
            except sync_api.Error:
                pass
            page.evaluate("document.getElementById('intro-screen')&&document.getElementById('intro-screen').remove()")
            if page.is_visible("#login-username"):
                _login(page)
            _load(page, cid, "al")
            page.wait_for_timeout(2500)
            after_reload = page.evaluate("""({body:document.getElementById('al-dirty-banner-body').textContent,
              shown:document.getElementById('al-dirty-banner').style.display,cause:aresStaleCause()})""")
            _shot(page, "knu_e2e2_05_aa_nach_reload.png")
        finally:
            browser.close()

    assert chip_before.startswith("Publiziert"), chip_before
    assert "Ersatzkurs – nicht belegt" not in editor and "manuell" in editor, editor
    assert aa["chip"] == "Veraltet · " + cause, aa
    assert aa["banner"] != "none" and aa["body"].startswith(cause), aa
    assert aa["hasAlloc"] is False and aa["pubBtn"] == "none", aa
    assert cause in po, po
    assert cause in rv and "STRATEGIE VERALTET" in rv.upper(), rv
    assert after_reload["cause"] == cause and after_reload["body"].startswith(cause), after_reload
    assert not errors, errors


def test_kn_u_fx_open_texts_and_typed_reasons(server):
    """E2E2-07, N-917-03, E2E2-08, N-917-08."""
    sync_api = _sync_api()
    api = _Api(server).login()
    # Beratung nur CHF, EUR nur im anderen Vermoegen (EUR-Kurs = Ersatzkurs, also nicht belegt).
    cid_eur, _ = _client(api, "Emma", [_chf_depot(15000000), {
        "label": "Ferienkonto EUR (fiktiv)", "position_type": "Liquidität", "assignment": "Anderes Vermögen",
        "current_value_rappen": 5000000, "currency": "EUR", "liquidity_instrument": "Sparkonto"}])
    # Beratung in GBP ohne bestaetigten Kurs (USD ist im Modul-Server ggf. schon bestaetigt).
    cid_usd, _ = _client(api, "Ulla", [_chf_depot(15000000), {
        "label": "Depot GBP (fiktiv)", "position_type": "Depot", "assignment": "Beratungsvermögen",
        "current_value_rappen": 10000000, "currency": "GBP", "depot_bank": "Testbank Fiktiv",
        "alloc_equities_bps": 10000}])
    # Hypothek ohne Zinssatz.
    cid_h, _ = _client(api, "Hanna", [_chf_depot(20000000)])
    status, home = api("POST", f"/clients/{cid_h}/wealth-positions", {
        "label": "Eigenheim (fiktiv)", "position_type": "Immobilien", "assignment": "Anderes Vermögen",
        "current_value_rappen": 80000000, "currency": "CHF", "valuation_date": "2026-11-18",
        "asset_valuation_method": "Fachgutachten", "property_usage": "Selbstgenutzt"})
    assert status in (200, 201), home
    status, mort = api("POST", f"/clients/{cid_h}/wealth-positions", {
        "label": "Hypothek ohne Satz (fiktiv)", "position_type": "Hypothek", "assignment": "Verbindlichkeit",
        "current_value_rappen": 50000000, "currency": "CHF", "mortgage_type": "Festhypothek",
        "mortgage_interest_rate_bps": None, "mortgage_maturity_date": "2032-03-31",
        "mortgage_amortization_type": "Indirekt (Säule 3a)", "mortgage_linked_property_id": home["id"]})
    assert status in (200, 201), mort
    with sync_api.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        errors: list[str] = []
        try:
            page = browser.new_page(viewport={"width": 1500, "height": 950})
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            _open(page, server, sync_api)
            _login(page)
            _load(page, cid_eur, "vg")
            page.wait_for_function("() => !/geprüft …/.test(document.getElementById('asset-view').innerText)", timeout=20000)
            page.wait_for_timeout(1000)
            eur_view = page.evaluate("document.getElementById('asset-view').innerText")
            eur_kpi = page.evaluate("(document.getElementById('kpi-beratungsvermoegen')||{textContent:''}).textContent")
            _shot(page, "knu_n917_03_vermoegen.png", "#asset-view")
            _load(page, cid_usd, "al")
            page.wait_for_timeout(2500)
            usd_aa = page.evaluate("(document.getElementById('page-al')||{innerText:''}).innerText")
            _shot(page, "knu_e2e2_07_aa_umrechnung_offen.png")
            _load(page, cid_h, "cf")
            page.wait_for_function("() => /Ist-Projektion nicht verfügbar/.test(document.getElementById('page-cf').innerText)", timeout=30000)
            h_cf = page.evaluate("document.getElementById('page-cf').innerText")
            _shot(page, "knu_e2e2_08_ist_projektion.png", "#page-cf")
        finally:
            browser.close()

    assert "CHF 150'000" in eur_view, eur_view  # Total Beratungsvermoegen belegt (nur CHF)
    assert "Umrechnung offen" in eur_view, eur_view  # Reinvermoegen bleibt offen
    assert "EUR" in eur_view, eur_view
    assert eur_kpi in ("", "CHF 150'000"), eur_kpi
    assert "Noch kein Beratungsvermögen erfasst" not in usd_aa and "Noch keine Advisory-Position" not in usd_aa, usd_aa
    assert "Umrechnung offen – Kurs GBP" in usd_aa, usd_aa
    assert "Zinssatz" in h_cf and "Kapitalmarktannahmen konnten nicht geladen" not in h_cf, h_cf
    assert not errors, errors


PAGES = ("sd", "vg", "cf", "rp", "al", "po", "rv")
A_MARKERS = ("777'700", "833'200", "55'500", "Quellwasser", "Seehaus", "131'313", "76'767")


def _rich_client_a(api):
    """A: eigene Betraege, Namen, Cashflows, Ziel und Risikoprofil (von B unterscheidbar)."""
    from tests.risk_fixture_helpers import standard_risk_payload

    advisor_id = api("GET", "/auth/me")[1]["id"]
    status, client = api("POST", "/clients", {
        "client_number": f"KNU-A-{time.time_ns()}", "first_name": "Annalena", "last_name": "Quellwasser-Fiktiv",
        "advisor_id": advisor_id, "household_type": "Einzelperson", "date_of_birth": "1966-04-01"})
    assert status == 201, client
    status, mandate = api("POST", f"/clients/{client['id']}/mandates",
                          {"mandate_number": f"M-KNU-A-{time.time_ns()}", "mandate_type": "Vermögensverwaltung"})
    assert status == 201, mandate
    assert api("POST", f"/mandates/{mandate['id']}/risk-assessments", standard_risk_payload(income=1, wealth=1))[0] == 201
    for pos in (
        {**_chf_depot(77770000), "label": "Depot Quellwasser (fiktiv)"},
        {"label": "Konto Quellwasser (fiktiv)", "position_type": "Liquidität", "assignment": "Beratungsvermögen",
         "current_value_rappen": 5550000, "currency": "CHF", "liquidity_instrument": "Sparkonto"},
    ):
        st, body = api("POST", f"/clients/{client['id']}/wealth-positions", pos)
        assert st in (200, 201), body
    for cf in ({"cashflow_type": "Income", "label": "Lohn Quellwasser (fiktiv)", "amount_rappen": 13131300},
               {"cashflow_type": "Expense", "label": "Haushalt Quellwasser (fiktiv)", "amount_rappen": 7676700}):
        st, body = api("POST", f"/clients/{client['id']}/cashflows", {
            **cf, "currency": "CHF", "frequency": "jaehrlich", "nature": "wiederkehrend",
            "valid_from": "2026-12-01", "valid_until": "2031-03-31", "is_inflation_linked": False})
        assert st in (200, 201), body
    st, body = api("POST", f"/mandates/{mandate['id']}/goals", {
        "goal_family": "Rendite", "goal_type": "Renditeziel", "label": "Ziel Quellwasser Seehaus",
        "rank": 1, "target_return_bps": 300, "hardness": "Primär"})
    assert st == 201, body
    return client["id"], mandate["id"]


def _empty_client_b(api):
    advisor_id = api("GET", "/auth/me")[1]["id"]
    status, client = api("POST", "/clients", {
        "client_number": f"KNU-B-{time.time_ns()}", "first_name": "Berta", "last_name": "Leerfeld-Fiktiv",
        "advisor_id": advisor_id, "household_type": "Einzelperson", "date_of_birth": "1990-09-09"})
    assert status == 201, client
    status, mandate = api("POST", f"/clients/{client['id']}/mandates",
                          {"mandate_number": f"M-KNU-B-{time.time_ns()}", "mandate_type": "Anlageberatung"})
    assert status == 201, mandate
    return client["id"], mandate["id"]


_LEAKS_JS = """(markers) => {
  var out = {};
  ['sd','vg','cf','rp','al','po','rv'].forEach(function(p){
    var el = document.getElementById('page-' + p); var t = el ? el.textContent : '';
    var hits = markers.filter(function(m){ return t.indexOf(m) >= 0; });
    if (hits.length) out['page-' + p] = hits;
  });
  Array.prototype.forEach.call(document.querySelectorAll('.overlay'), function(o){
    var hits = markers.filter(function(m){ return (o.textContent || '').indexOf(m) >= 0; });
    if (hits.length) out[o.id || 'overlay'] = hits;
  });
  return out;
}"""


def test_kn_u_no_previous_client_values_on_any_page(server):
    """N-918-01: A komplett (Strategie + Portfolio) -> B ganz ohne Daten: auf keiner der 7 Seiten
    (auch nicht im unsichtbaren DOM-Inhalt) und in keinem Dialog steht ein Wert von A."""
    sync_api = _sync_api()
    api = _Api(server).login()
    cid_a, _mid_a = _rich_client_a(api)
    cid_b, _mid_b = _empty_client_b(api)
    with sync_api.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        errors: list[str] = []
        try:
            page = browser.new_page(viewport={"width": 1500, "height": 950})
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            _open(page, server, sync_api)
            _login(page)
            _load(page, cid_a, "al")
            _compute(page)
            provision_database(server.database)  # C-COMP-02: synthetische Nachweise
            page.evaluate("go('po')")
            page.wait_for_timeout(1500)
            page.evaluate(CLOSE)
            page.evaluate("()=>{refreshPortfolioFromStoredState();}")
            page.wait_for_function("() => (document.getElementById('po-portfolio-sections')||{innerText:''}).innerText.indexOf('Musterprodukt')>=0", timeout=240000)
            page.wait_for_timeout(1000)
            page.evaluate(CLOSE)
            for pg in ("rv", "cf", "vg"):
                page.evaluate(f"go('{pg}')")
                page.wait_for_timeout(1500)
                page.evaluate(CLOSE)
            a_seen = page.evaluate(_LEAKS_JS, list(A_MARKERS))
            _shot(page, "knu_n918_01_A_vermoegen.png")
            # Wechsel zu B (wie Seitenleiste/Auto-Oeffnen), dann jede Seite mit echtem Klick.
            page.evaluate(f"loadClientById('{cid_b}')")
            page.wait_for_timeout(3500)
            page.evaluate(CLOSE)
            leaks = {"nach Wechsel": page.evaluate(_LEAKS_JS, list(A_MARKERS))}
            for i, pg in enumerate(PAGES):
                page.locator(".tnav .tstep").nth(i).click(timeout=8000)
                page.wait_for_timeout(1800)
                page.evaluate(CLOSE)
                hits = page.evaluate(_LEAKS_JS, list(A_MARKERS))
                if hits:
                    leaks[pg] = hits
                if pg in ("po", "al", "rv"):
                    _shot(page, f"knu_n918_01_B_{pg}.png")
            po_head = page.evaluate("""['po-advisory-wealth','po-position-count','po-average-ter','po-total-footer']
              .map(function(id){var e=document.getElementById(id);return e?e.textContent.trim():null;})""")
            # Schneller Doppelwechsel A -> B.
            page.evaluate(f"loadClientById('{cid_a}');loadClientById('{cid_b}')")
            page.wait_for_timeout(4000)
            page.evaluate(CLOSE)
            double = page.evaluate(_LEAKS_JS, list(A_MARKERS))
        finally:
            browser.close()

    # Positivkontrolle: A-Werte standen vorher wirklich im DOM (sonst prueft der Test nichts).
    seen = {m for hits in a_seen.values() for m in hits}
    assert {"833'200", "Quellwasser"} <= seen, a_seen
    assert "833'200" in a_seen.get("page-po", []), a_seen
    leaks = {k: v for k, v in leaks.items() if v}
    assert leaks == {}, leaks
    assert double == {}, double
    assert "833'200" not in " ".join(str(x) for x in po_head), po_head
    assert not errors, errors


def test_kn_u_header_steps_clickable_at_1024_and_1280(server):
    """N-918-03: alle sieben Schritte bei 1280 und 1024 px sichtbar und klickbar (echter Klick auf Schritt 7)."""
    sync_api = _sync_api()
    api = _Api(server).login()
    cid, _mid = _client(api, "Kopf", [_chf_depot()])
    results = {}
    with sync_api.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        errors: list[str] = []
        try:
            for width in (1280, 1024):
                page = browser.new_page(viewport={"width": width, "height": 800})
                page.on("pageerror", lambda exc: errors.append(str(exc)))
                _open(page, server, sync_api)
                _login(page)
                _load(page, cid, "sd")
                covered = page.evaluate("""Array.from(document.querySelectorAll('.tnav .tstep')).map(function(s,i){
                  var r=s.getBoundingClientRect();var x=r.left+r.width/2,y=r.top+r.height/2;
                  var hit=document.elementFromPoint(x,y);
                  return {i:i+1,visible:r.width>0&&x<window.innerWidth,own:!!(hit&&s.contains(hit))};
                }).filter(function(o){return !(o.visible&&o.own);})""")
                page.locator(".tnav .tstep").nth(6).click(timeout=8000)
                page.wait_for_timeout(1500)
                active = page.evaluate("document.querySelector('.page.active')&&document.querySelector('.page.active').id")
                _shot(page, f"knu_n918_03_kopfzeile_{width}.png", ".topbar")
                results[width] = {"covered": covered, "active": active}
                page.close()
        finally:
            browser.close()
    for width, res in results.items():
        assert res["covered"] == [], (width, res)
        assert res["active"] == "page-rv", (width, res)
    assert not errors, errors


def test_ci_runs_this_behaviour_test_with_playwright_required():
    workflow = (Path(__file__).resolve().parents[2] / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    job = workflow[workflow.index(chr(10) + "  vitest:"):]
    step = job[job.index("(KN-U, Playwright Pflicht)"):]
    assert 'ARES_REQUIRE_PLAYWRIGHT: "1"' in step[:400]
    assert "tests/test_livetest_kn_u_ui.py" in step[:900]
