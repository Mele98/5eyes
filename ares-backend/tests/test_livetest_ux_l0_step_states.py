"""UX-L0 / UX-CH-02 im echten Browser: kein "OK" ohne vollstaendigen Schritt.

Isoliertes Backend (Temp-DB/HOME/KEK, freier Port), echte App, echter Login.

* Unvollstaendige Stammdaten (Kanton und Zivilstand fehlen): Navigation zu
  Vermoegen bleibt moeglich, Stammdaten bleiben "besucht" und zeigen nie "OK".
* Bis zum Review: kein zurueckliegender Schritt ohne Vollstaendigkeitspruefung
  zeigt "OK".
* Vollstaendige Stammdaten: genau der Stammdaten-Schritt ist "vollstaendig".
* Intro (vor dem Login) zeigt keine Statusbehauptungen.

Pflichtlauf im CI-Job "Frontend Reporting Tests" (Playwright Pflicht).
"""
from __future__ import annotations

import time

import pytest

from tests.test_livetest_k2_kernkette_ui import CLOSE, _Api, _load, _login, _sync_api
from tests.test_livetest_kern_integration_r2 import _backend

STATES = """Array.from(document.querySelectorAll('.tnav .tstep')).map(function(s){
  return {page:s.dataset.page,state:s.dataset.stepState||'',sn:(s.querySelector('.sn')||{}).textContent||'',
          done:s.classList.contains('done'),visited:s.classList.contains('visited')};})"""


@pytest.fixture(scope="module")
def server():
    _sync_api()
    with _backend(frozen=False) as srv:
        yield srv


def _client(api, first, **extra):
    advisor_id = api("GET", "/auth/me")[1]["id"]
    stamp = f"{first}-{time.time_ns()}"
    st, client = api("POST", "/clients", {"client_number": f"UXL0-{stamp}", "first_name": first,
                                          "last_name": "Schrittprobe-Fiktiv", "advisor_id": advisor_id,
                                          "household_type": "Einzelperson", "date_of_birth": "1980-04-01", **extra})
    assert st == 201, client
    st, mandate = api("POST", f"/clients/{client['id']}/mandates",
                      {"mandate_number": f"M-{stamp}", "mandate_type": "Anlageberatung"})
    assert st == 201, mandate
    return client["id"]


def _go(page, pg):
    page.evaluate(CLOSE)
    page.evaluate(f"go('{pg}')")
    page.wait_for_timeout(1500)
    page.evaluate(CLOSE)


def _by_page(page):
    return {row["page"]: row for row in page.evaluate(STATES)}


def test_incomplete_step_is_never_ok_and_complete_step_is_marked_once(server):
    sync_api = _sync_api()
    api = _Api(server["base"]).login()
    incomplete = _client(api, "Ina")
    complete = _client(api, "Kai", canton="ZH", civil_status="Ledig")

    with sync_api.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        errors: list[str] = []
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.goto(server["base"] + "/app/ares.html")
            page.wait_for_selector("#intro-screen", timeout=20000)
            seen = [page.evaluate("document.getElementById('intro-screen').innerText")]
            page.wait_for_selector("#intro-screen .intro-skip:not([disabled])", timeout=20000)
            seen.append(page.evaluate("document.getElementById('intro-screen').innerText"))
            for intro in seen:
                for claim in ("ACTIVE", "MAPPED", "READY", "AWARE", "SYNC", "LIVE", "SECURE", "VALID"):
                    assert claim not in intro.upper(), (claim, intro)
            page.evaluate("document.getElementById('intro-screen')&&document.getElementById('intro-screen').remove()")
            _login(page)

            _load(page, incomplete, "sd")
            label = page.evaluate("(document.getElementById('sd-completeness-label')||{}).textContent||''")
            assert label.startswith("Stammdaten unvollständig"), label
            _go(page, "vg")
            states = _by_page(page)
            assert states["vg"]["state"] == "current", states
            assert states["sd"]["state"] == "visited" and states["sd"]["sn"] == "1", states["sd"]
            assert not states["sd"]["done"]
            for target in ("cf", "rp", "rv"):
                _go(page, target)
                rows = page.evaluate(STATES)
                active = next(i for i, r in enumerate(rows) if r["state"] == "current")
                assert all(r["sn"] != "OK" and not r["done"] for r in rows[:active]), (target, rows)

            _load(page, complete, "sd")
            label = page.evaluate("(document.getElementById('sd-completeness-label')||{}).textContent||''")
            assert label == "Stammdaten vollständig", label
            _go(page, "vg")
            rows = page.evaluate(STATES)
            ok = [r["page"] for r in rows if r["sn"] == "OK"]
            assert ok == ["sd"], rows
            assert rows[0]["state"] == "complete" and rows[0]["done"], rows[0]
            # Rueckweg auf die Seite selbst: aktueller Schritt zeigt seine Nummer
            _go(page, "sd")
            assert _by_page(page)["sd"]["state"] == "current"
            assert not errors, errors
        finally:
            browser.close()
