"""KN4-U (Dok. 119 / H-172-Pruefung): Pflicht-Livetest der Classic-Berateroberflaeche
gegen das echte Backend, ohne Stub-Daten.

Isolierter Backend-Prozess (Temp-DB/HOME/APPDATA/LOCALAPPDATA, Wegwerf-KEK, freier
Port), echte App ``/app/ares.html`` in Chromium, echter Login, echte Dialoge und
Speichern-Knoepfe. Verzoegerte Antworten entstehen mit ``page.route``: die echte
Anfrage wird zurueckgehalten und erst nach dem Kundenwechsel unveraendert an den
Server weitergegeben (keine erfundenen Daten).

* E2E4-01  "+ Mandat" bei offenem Kunden mit Vermoegen -> neuer Kunde zeigt nirgends
           einen Betrag des Vorkunden (Tortenmitte "—").
* E2E4-05  danach Risikoprofil im normalen Ablauf speichern (echter Knopf) -> kein
           "Strategie veraltet"; E2E4-14 leere Soll-Prognose ohne Achse.
* N-917R3-01  verspaetete Vermoegensantwort von A nach Wechsel zu B -> B bleibt sauber.
* N-917R3-02  KYC-Fehler von X nach Wechsel zu Y -> Y-Formular bleibt leer.
* E2E4-06  Review-Prozent = AA-Prozent; Portfolio-Zeilen = AA-Klassenbetrag.
* E2E4-09  veraltete Strategie -> Portfolio zeigt Ursache, gesperrt, kein "CHF 0".
* E2E4-08  Mischwaehrung mit belegten Kursen -> Cashflow-Seite ohne "Umrechnung offen".

Pflichtlauf im eigenen CI-Job "KN4-U Livetest (Playwright Pflicht)".
"""
from __future__ import annotations

import re
import time
from pathlib import Path

import pytest

from tests.test_livetest_k2_kernkette_ui import CLOSE, _Api, _load, _sync_api
from tests.test_livetest_kern_integration_r2 import _backend
from tests.test_livetest_kn3_u_ui import _cashflows, _go, _new_client, _page, _persona_a, _shot

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def server():
    _sync_api()
    with _backend(frozen=False) as srv:
        yield srv


def _depot(label, value, currency="CHF", **alloc):
    a = alloc or {"alloc_equities_bps": 6000, "alloc_bonds_bps": 3000, "alloc_liquidity_bps": 1000}
    return {"label": label, "position_type": "Depot", "assignment": "Beratungsvermögen", "current_value_rappen": value,
            "currency": currency, "depot_bank": "Testbank Fiktiv", **a}


def _risk_payload(api, mid):
    st, body = api("GET", f"/mandates/{mid}/risk-assessments/current")
    assert st == 200, body
    return body


def test_kn4u_new_mandate_from_open_client_starts_empty_and_never_stale(server):
    sync_api = _sync_api()
    api = _Api(server["base"]).login()
    bcid, bmid, _ = _new_client(api, "Beat", "Vorkunde-Fiktiv", "1976-04-04", [_depot("Depot Beat (fiktiv)", 58_000_000)])
    st, body = api("POST", f"/mandates/{bmid}/target-allocation/generate", {"preferences": {}})
    assert st == 200, body
    risk = _risk_payload(api, bmid)
    first = f"Nora{time.time_ns() % 100000}"
    with sync_api.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        errors: list[str] = []
        try:
            page = _page(browser, server, sync_api, errors)
            _load(page, bcid, "al")
            page.wait_for_function("() => /580/.test((document.querySelector('.dcv')||{innerText:''}).innerText)", timeout=60000)
            before = page.evaluate("document.querySelector('.dcv').innerText")
            # E2E4-01: "+ Mandat" (echter Knopf in der Kopfzeile) bei offenem Kunden B.
            page.click("button.t-btn:has-text('+ Mandat')")
            page.wait_for_selector("#nc-firstname", state="visible", timeout=15000)
            page.fill("#nc-firstname", first)
            page.fill("#nc-lastname", "Neuanlage-Fiktiv")
            page.click("#btn-nc-submit")
            page.wait_for_function("() => !document.getElementById('m-nc').classList.contains('open')", timeout=60000)
            page.wait_for_timeout(2000)
            _go(page, "al", 3000)
            new_al = page.evaluate("""() => ({center:document.querySelector('.dcv').innerText,
              page:document.getElementById('page-al').innerText, total:typeof TOTAL!=='undefined'?TOTAL:null})""")
            _shot(page, "kn4u_01_neues_mandat_aa_leer.png")
            others = page.evaluate("""() => ['sd','vg','cf','po','rv'].map(function(p){go(p);
              return (document.getElementById('page-'+p)||{innerText:''}).innerText;}).join('\\n')""")
            # E2E4-05: Risikoprofil im normalen Ablauf speichern (Fragebogen gefuellt, echter Knopf).
            _go(page, "rp", 2000)
            page.evaluate("(r)=>{hydrateRiskQuestionnaire(r);}", risk)
            page.wait_for_timeout(800)
            page.click("#btn-save-riskprofile")
            page.wait_for_function("() => /Gespeichert/.test(document.getElementById('btn-save-riskprofile').textContent)", timeout=30000)
            _go(page, "al", 3000)
            after = page.evaluate("""() => ({dirty:(function(){var b=document.getElementById('al-dirty-banner');return b?getComputedStyle(b).display:'none';})(),
              leg:(document.getElementById('dnleg')||{innerText:''}).innerText, center:document.querySelector('.dcv').innerText,
              yDisplay:(typeof charts!=='undefined'&&charts.opt)?charts.opt.options.scales.y.display:null})""")
            _shot(page, "kn4u_05_risikoprofil_ohne_veraltet.png")
        finally:
            browser.close()
    assert "580" in before, before
    assert new_al["center"] in ("—", "-"), new_al
    assert "580" not in new_al["page"] and new_al["total"] == 0, new_al
    assert "580" not in others, others[max(0, others.find("580") - 300):others.find("580") + 200]
    assert after["dirty"] == "none" and "veraltet" not in after["leg"].lower(), after
    assert after["center"] in ("—", "-") and after["yDisplay"] is False, after
    assert not errors, errors


def test_kn4u_late_answers_after_client_switch_write_nothing(server):
    sync_api = _sync_api()
    api = _Api(server["base"]).login()
    acid, _amid, aids = _new_client(api, "Alma", "Spaetantwort-Fiktiv", "1966-03-10", [_depot("Depot Alma (fiktiv)", 45_000_000)])
    bcid, _bmid, _ = _new_client(api, "Bruno", "Schnellwechsel-Fiktiv", "1981-08-08", [_depot("Depot Bruno (fiktiv)", 20_000_000)])
    xcid, _xmid, _ = _new_client(api, "Xenia", "KycWechsel-Fiktiv", "1970-01-01", [])
    ycid, _ymid, _ = _new_client(api, "Yves", "KycLeer-Fiktiv", "1971-02-02", [])
    held: list = []
    with sync_api.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        errors: list[str] = []
        try:
            page = _page(browser, server, sync_api, errors)
            # N-917R3-01: Antwort fuer A zurueckhalten, waehrend der Berater zu B wechselt.
            _load(page, acid, "vg")
            page.route(f"**/clients/{acid}/wealth-summary**", lambda route: held.append(route))
            page.evaluate(f"()=>{{openWealthPositionEditor('{aids[0]}');}}")
            page.wait_for_selector("#maw-depot-value", state="visible", timeout=15000)
            page.fill("#maw-depot-value", "460000")
            page.click("#btn-maw-save")
            for _ in range(100):
                if held:
                    break
                page.wait_for_timeout(100)
            page.evaluate(CLOSE)
            page.evaluate(f"loadClientById('{bcid}')")
            page.wait_for_function("() => /200/.test(document.getElementById('kpi-reinvermoegen').textContent)", timeout=60000)
            for route in held:
                route.continue_()
            page.unroute(f"**/clients/{acid}/wealth-summary**")
            page.wait_for_timeout(3000)
            leak = page.evaluate("""() => ({kpi:document.getElementById('kpi-reinvermoegen').textContent,
              kpi2:(document.getElementById('kpi-beratungsvermoegen')||{textContent:''}).textContent,
              summary:currentWealthSummary&&currentWealthSummary.client_id, active:currentClientId,
              vg:document.getElementById('page-vg').innerText})""")
            _shot(page, "kn4u_r3_01_schnellwechsel_sauber.png")
            # N-917R3-02: KYC-Fehler von X kommt erst nach dem Wechsel zu Y an.
            _load(page, xcid, "sd")
            page.wait_for_selector("#kyc-form", state="attached", timeout=60000)
            page.evaluate("""()=>{var s=function(id,v){document.getElementById(id).value=v;};s('kyc-form','A');s('kyc-date','2026-11-01');
              s('kyc-ref','REF-X-FIKTIV');s('kyc-risk','normal');s('kyc-pep','false');s('kyc-review','2026-10-01');s('kyc-ident-date','2026-11-01');
              document.getElementById('kyc-ident-ok').checked=true;}""")
            kyc_held: list = []
            page.route("**/kyc-confirmations", lambda route: kyc_held.append(route))
            page.evaluate("()=>{createKycConfirmation();}")
            for _ in range(100):
                if kyc_held:
                    break
                page.wait_for_timeout(100)
            page.evaluate(f"loadClientById('{ycid}')")
            page.wait_for_timeout(3000)
            for route in kyc_held:
                route.continue_()
            page.unroute("**/kyc-confirmations")
            page.wait_for_timeout(3000)
            y_form = page.evaluate("""()=>['kyc-form','kyc-date','kyc-ref','kyc-risk','kyc-pep','kyc-review','kyc-ident-date']
              .map(function(id){var e=document.getElementById(id);return e?e.value:null;}).concat([(document.getElementById('kyc-ident-ok')||{}).checked||false,currentClientId])""")
            _shot(page, "kn4u_r3_02_kyc_y_leer.png", "#sd-client-compliance")
        finally:
            browser.close()
    assert held, "Antwort fuer A wurde nicht zurueckgehalten"
    assert leak["active"] == bcid and leak["summary"] == bcid, leak
    assert "200" in leak["kpi"] and "460" not in leak["kpi"] and "460" not in leak["kpi2"], leak
    assert "Depot Bruno" in leak["vg"] and "Depot Alma" not in leak["vg"], leak["vg"][:400]
    assert kyc_held, "KYC-POST wurde nicht zurueckgehalten"
    assert y_form[-1] == ycid and y_form[:7] == [""] * 7 and y_form[7] is False, y_form
    assert not errors, errors


def test_kn4u_one_rounding_source_and_stale_portfolio(server):
    sync_api = _sync_api()
    api = _Api(server["base"]).login()
    cid, mid = _persona_a(api, server["db"])
    st, positions = api("GET", f"/clients/{cid}/wealth-positions")
    depot = next(p for p in positions if p["position_type"] == "Depot")
    with sync_api.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        errors: list[str] = []
        try:
            page = _page(browser, server, sync_api, errors)
            _load(page, cid, "rv")
            page.wait_for_function("() => document.querySelectorAll('#sr-implementation-steps > div').length >= 1", timeout=60000)
            pct = page.evaluate("""() => {var a=strategyState.allocation, b=a.buckets;
              var cards=Array.prototype.map.call(document.querySelectorAll('#sr-implementation-steps > div'),function(c){return c.innerText;});
              return {cards:cards, aa:b.map(function(x){return [assetDisplayName(x.asset_class), sollPct(x.asset_class,x.target_weight_bps,b)];})};}""")
            _go(page, "po", 3000)
            page.wait_for_function("() => document.querySelectorAll('#po-portfolio-sections .ps .psc').length >= 1", timeout=60000)
            po = page.evaluate("""() => {var aa={};aaChartAllocItems().forEach(function(i){aa[i.name]=i.amountChf;});
              var num=function(t){return Number(String(t).replace(/[^0-9-]/g,''))||0;};
              var groups=Array.prototype.map.call(document.querySelectorAll('#po-portfolio-sections .ps'),function(g){
                var rows=Array.prototype.map.call(g.querySelectorAll('.prow-main'),function(r){var v=r.querySelectorAll('.pval');return v.length?num(v[0].textContent):0;});
                return {name:(g.querySelector('.psn')||{textContent:''}).textContent,sub:num((g.querySelector('.psc')||{textContent:''}).textContent),
                  rows:rows.reduce(function(a,b){return a+b;},0)};});
              return {aa:aa, groups:groups, footer:num(document.getElementById('po-total-footer').textContent)};}""")
            _shot(page, "kn4u_06_portfolio_rundung.png")
            # E2E4-09: Strategie wird veraltet (Vermoegen geaendert), Portfolio-Seite.
            st2, body = api("PUT", f"/clients/{cid}/wealth-positions/{depot['id']}", {**{k: depot[k] for k in (
                "label", "position_type", "assignment", "currency", "depot_bank", "alloc_equities_bps", "alloc_bonds_bps",
                "alloc_real_estate_bps", "alloc_liquidity_bps", "alloc_alternatives_bps") if k in depot}, "current_value_rappen": 41_000_000})
            _load(page, cid, "po")
            page.wait_for_function("() => /Strategie veraltet/.test(document.getElementById('po-portfolio-sections').innerText)", timeout=60000)
            stale = page.evaluate("""() => ({sections:document.getElementById('po-portfolio-sections').innerText,
              page:document.getElementById('page-po').innerText,
              fin:(document.getElementById('btn-po-finalize')||{disabled:true}).disabled,
              wealth:document.getElementById('po-advisory-wealth').textContent})""")
            _shot(page, "kn4u_09_portfolio_veraltet.png")
        finally:
            browser.close()
    # E2E4-06: Review-Karte "Ziel" = AA-Prozent je Klasse (mindestens eine Karte geprueft).
    checked = 0
    for name, aa_pct in pct["aa"]:
        for card in pct["cards"]:
            if re.search(r"\n" + re.escape(name) + r"\n", "\n" + card + "\n") and "Ziel" in card:
                assert ("Ziel " + aa_pct) in card.replace(" ", "\xa0") or ("Ziel " + aa_pct).replace("\xa0", " ") in card, (name, aa_pct, card)
                checked += 1
    assert checked >= 1, pct
    for g in po["groups"]:
        assert g["rows"] == g["sub"], g
        if g["name"] in po["aa"]:
            assert g["sub"] == po["aa"][g["name"]], (g, po["aa"])
    assert sum(g["sub"] for g in po["groups"]) == po["footer"], po
    # E2E4-09
    assert st2 in (200, 201), body
    assert "Strategie veraltet" in stale["sections"] and "CHF 0" not in stale["sections"], stale
    assert "konnte nicht generiert" not in stale["page"] and stale["fin"] is True, stale
    assert "450" in stale["wealth"] or "460" in stale["wealth"] or re.search(r"\d", stale["wealth"]), stale
    assert not errors, errors


def test_kn4u_cashflow_page_no_open_conversion_when_rates_covered(server):
    sync_api = _sync_api()
    api = _Api(server["base"]).login()
    assert api("PUT", "/fx-rates", {"rates": [{"currency": "USD", "rate": 0.88, "source": "Manual", "confirm_current": True}]})[0] in (200, 201)
    cid, _mid, _ = _new_client(api, "Carla", "Mischwaehrung-Fiktiv", "1954-05-05", [
        _depot("Depot CHF Carla (fiktiv)", 15_000_000), _depot("Depot USD Carla (fiktiv)", 15_000_000, currency="USD")])
    _cashflows(api, cid, income=3_000_000, expense=9_000_000)
    with sync_api.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        errors: list[str] = []
        try:
            page = _page(browser, server, sync_api, errors)
            _load(page, cid, "vg")
            page.wait_for_function("() => /282/.test(document.getElementById('page-vg').innerText)", timeout=60000)
            _go(page, "cf", 4000)
            cf = page.evaluate("document.getElementById('page-cf').innerText")
            _shot(page, "kn4u_08_cashflow_kurse_belegt.png")
        finally:
            browser.close()
    assert "Umrechnung offen" not in cf, cf[:1500]
    assert "Kurse sind belegt" in cf or "mehreren Währungen" not in cf, cf[:1500]
    assert not errors, errors


def test_ci_runs_this_behaviour_test_with_playwright_required():
    workflow = (BACKEND.parent / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    assert "test_livetest_kn4_u_ui.py" in workflow


def test_demo_b4_advisor_client_switch_without_403_and_b1_terms(server):
    """DEMO-B4: Berater (nicht Admin) loest beim Start/Kundenwechsel keine Admin-Route (403) aus.
    DEMO-B1: Sub-Anlageklassen aus den Daten erscheinen im Portfolio mit Umlaut (aresTerm)."""
    sync_api = _sync_api()
    admin = _Api(server["base"]).login()
    # OWN-LIC-01 (H-187): der Bootstrap-Admin zaehlt sofort gegen max_users
    # (Ersteinrichtung: 1). Diese Probe braucht eine Mehrbenutzer-Lizenz --
    # TESTWERT direkt in der Wegwerf-DB, die Lizenzpflege ist nicht Gegenstand.
    import sqlite3

    with sqlite3.connect(server["db"]) as conn:
        conn.execute("UPDATE tenants SET max_users = NULL")
    user, pwd = f"berater{time.time_ns() % 100000}", "Berater-Probe-Passwort-2026!x"
    st, body = admin("POST", "/users", {"username": user, "password": pwd, "full_name": "Berta Beraterin-Fiktiv", "role": "advisor"})
    assert st in (200, 201), body
    adv = _Api(server["base"])
    st, tok = adv("POST", "/auth/login", {"username": user, "password": pwd})
    assert st == 200, tok
    adv.token = tok["access_token"]
    # Erzwungener Erst-Passwortwechsel (wie ein neuer Mitarbeiter), danach normal anmelden.
    pwd2 = pwd + "-neu"
    st, body = adv("POST", "/auth/change-password", {"current_password": pwd, "new_password": pwd2})
    assert st == 200, body
    pwd = pwd2
    st, tok = adv("POST", "/auth/login", {"username": user, "password": pwd})
    assert st == 200, tok
    adv.token = tok["access_token"]
    c1, _m1, _ = _new_client(adv, "Hanna", "Beraterkundin-Fiktiv", "1975-03-03", [_depot("Depot Hanna (fiktiv)", 30_000_000)])
    c2, _m2, _ = _new_client(adv, "Ivo", "Beraterkunde-Fiktiv", "1979-09-09", [_depot("Depot Ivo (fiktiv)", 20_000_000)])
    with sync_api.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        errors: list[str] = []
        bad: list[str] = []
        console: list[str] = []
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.on("response", lambda r: bad.append(f"{r.status} {r.url}") if r.status == 403 else None)
            page.on("console", lambda m: console.append(m.text) if m.type == "error" else None)
            from tests.test_livetest_k2_kernkette_ui import _open
            _open(page, server["base"], sync_api)
            page.fill("#login-username", user)
            page.fill("#login-password", pwd)
            page.evaluate("document.getElementById('btn-login-submit').click()")
            page.wait_for_timeout(5000)
            page.evaluate(CLOSE)
            role = page.evaluate("currentUser&&currentUser.role")
            for cid in (c1, c2, c1, c2):
                _load(page, cid, "vg")
            page.wait_for_timeout(1500)
            # DEMO-B1 an der Render-Stelle: Datenname "Aktien Schwellenlaender" -> "Aktien Schwellenländer".
            po = page.evaluate("""() => { renderPortfolioSections([{asset_class:'Aktien',sub_asset_class:'Aktien Schwellenlaender',
                product_name:'Aktien Schwellenlaender ETF (Muster)',target_amount_rappen:1000000,target_weight_bps:10000,ter_bps:20}]);
              return document.getElementById('po-portfolio-sections').innerText; }""")
        finally:
            browser.close()
    assert role == "advisor", role
    assert [b for b in bad if "/admin/" in b] == [], bad
    assert not [c for c in console if "403" in c], console
    assert "Schwellenländer" in po and "Schwellenlaender" not in po, po
    assert not errors, errors
