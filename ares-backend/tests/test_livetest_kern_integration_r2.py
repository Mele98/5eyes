"""Kern-Integration Runde 2 (H-167): KN-U gegen das echte integrierte KN-B-Backend.

Pflicht-Livetest ohne Route-Stub: isolierter Backend-Prozess (Temp-DB/HOME/
APPDATA/LOCALAPPDATA, Wegwerf-KEK, freier Port), echte App ``/app/ares.html``
in Chromium, echter Login. Die Publikation entsteht ueber die echte API
(Generate -> Produktlauf -> Finalisieren -> Publish-Gate als Ein-Personen-Firma),
die Vorbedingungen anderer Pakete (Retrozession, Kundeninformation/KYC) mit
denselben Testhelfern wie der E2b-Livetest.

* E2E2-04 (KN-B) mit KN-U: Berufsaenderung ueber die Stammdaten-Maske ->
  Server bleibt PUBLISHED/FRESH, und die UI zeigt weiter "Publiziert" (direkt
  nach dem Speichern und nach Mandatswechsel/Neuladen).
* E2E2-05 (KN-B-Vertrag ``freshness.status/causes``, ``PUBLICATION_INVALID``):
  GBP-Kurs aendern -> weiter publiziert; USD-Kurs im Schnelleditor aendern ->
  Server ``PUBLICATION_INVALID`` mit Ursache ``fx_rate``/USD, UI zeigt auf Asset
  Allokation, Portfolio und Review "Wechselkurs USD geändert"; ebenso in einer
  frischen Sitzung direkt auf Review (Statuspfad, ohne vorherigen Payload-Abruf).
* E2E2-10 (KN-B ``foundation_example_available``): Knopf "Foundation Case"
  im Dev-Modus sichtbar; in der gepackten Produktivinstallation (``sys.frozen``,
  das bestehende Merkmal der Desktop-EXE) meldet ``GET /`` false und der Knopf
  fehlt.

Pflichtlauf im CI-Job "Frontend Reporting Tests" (``ARES_REQUIRE_PLAYWRIGHT=1``).
"""
from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import pytest

from tests.test_livetest_e2b_strategy_blocks import _finalize_and_publish
from tests.test_livetest_k2_kernkette_ui import (
    CLOSE, _Api, _chf_depot, _client, _free_port, _load, _login, _open, _sync_api,
)

BACKEND = Path(__file__).resolve().parents[1]
CAUSE = "Wechselkurs USD geändert"


@contextlib.contextmanager
def _backend(frozen: bool):
    from cryptography.fernet import Fernet

    tmp = Path(tempfile.mkdtemp(prefix="kint_r2_"))
    for sub in ("home", "appdata", "localappdata"):
        (tmp / sub).mkdir()
    port = _free_port()
    db_path = tmp / "kint_r2.db"
    env = {
        **os.environ,
        "HOME": str(tmp / "home"), "USERPROFILE": str(tmp / "home"),
        "APPDATA": str(tmp / "appdata"), "LOCALAPPDATA": str(tmp / "localappdata"),
        "DB_PATH": str(db_path), "SECRET_KEY": "kint-r2-secret-key-0123456789abcdef-xyz",
        "SERVE_MAIN_FRONTEND": "1", "PRICE_SCHEDULER_ENABLED": "0", "BACKUP_SCHEDULER_ENABLED": "0",
        "MARKET_DATA_CACHE_PURGE_ENABLED": "0", "LOGIN_RATE_LIMIT_ENABLED": "0",
        "APP_ENV": "development", "TENANT_MASTER_KEK": Fernet.generate_key().decode(),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    # Gepackte Produktivinstallation: dasselbe Merkmal wie die PyInstaller-EXE
    # (sys.frozen), das config.foundation_example_available auswertet.
    launcher = ("import sys; sys.frozen = True; import uvicorn; "
                f"uvicorn.run('main:app', host='127.0.0.1', port={port})") if frozen else None
    cmd = ([sys.executable, "-c", launcher] if frozen else
           [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(port)])
    proc = subprocess.Popen(cmd, cwd=str(BACKEND), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
        yield {"base": base, "db": db_path}
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


@pytest.fixture(scope="module")
def server():
    _sync_api()
    with _backend(frozen=False) as srv:
        yield srv


def _published_mandate(api, db_path):
    from core import sustainability_preference as sp

    assert api("PUT", "/fx-rates", {"rates": [
        {"currency": "USD", "rate": 0.88, "source": "Manual", "confirm_current": True}]})[0] in (200, 201)
    cid, mid = _client(api, "Ursula", [_chf_depot(40_000_000), {
        "label": "Depot USD (fiktiv)", "position_type": "Depot", "assignment": "Beratungsvermögen",
        "current_value_rappen": 10_000_000, "currency": "USD", "depot_bank": "Testbank Fiktiv",
        "alloc_equities_bps": 7000, "alloc_bonds_bps": 3000}])
    status, body = api("POST", f"/mandates/{mid}/sustainability-preferences", {
        "questionnaire_version": sp.QUESTIONNAIRE_VERSION, "definition_hash": sp.definition_hash(),
        "response_status": "declined", "esg_relevance": None, "esg_characteristic": None,
        "exclusions": [], "information_acknowledged": False, "client_confirmed": True,
        "capture_channel": "in_person"})
    assert status == 201, body
    status, body = api("POST", f"/mandates/{mid}/target-allocation/generate", {"preferences": {}})
    assert status == 200, body
    status, body = api("POST", f"/mandates/{mid}/recommendations/generate", {})
    assert status == 200, body
    _finalize_and_publish(api, db_path, mid)
    return cid, mid


def _overview(api, mid):
    status, body = api("GET", f"/mandates/{mid}/allocation-publication")
    assert status == 200, body
    return body


def _chip(page):
    return page.evaluate("(document.getElementById('aa-publication-status')||{textContent:''}).textContent.trim()")


def _fresh_page(browser, srv, sync_api, errors):
    page = browser.new_page(viewport={"width": 1500, "height": 950})
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    _open(page, srv["base"], sync_api)
    _login(page)
    return page


def test_real_backend_profession_keeps_published_and_usd_change_names_cause(server):
    sync_api = _sync_api()
    api = _Api(server["base"]).login()
    cid, mid = _published_mandate(api, server["db"])
    start = _overview(api, mid)
    assert start["publication_status"] == "PUBLISHED", start
    assert (start.get("freshness") or {}).get("status") == "FRESH", start

    with sync_api.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        errors: list[str] = []
        try:
            page = _fresh_page(browser, server, sync_api, errors)
            _load(page, cid, "al")
            page.wait_for_function("() => /Publiziert/.test((document.getElementById('aa-publication-status')"
                                   "||{textContent:''}).textContent)", timeout=60000)
            chip_start = _chip(page)

            # E2E2-04: Beruf ueber die echte Stammdaten-Maske aendern.
            page.evaluate("()=>{openStammdatenModal();}")
            page.wait_for_selector("#es-profession", state="visible", timeout=15000)
            page.fill("#es-profession", "Architektin (fiktiv)")
            page.click("#btn-es-save")
            page.wait_for_function("() => /Gespeichert/.test((document.getElementById('es-error')||{textContent:''})"
                                   ".textContent)", timeout=30000)
            page.wait_for_timeout(2000)
            page.evaluate(CLOSE)
            after_profession_api = _overview(api, mid)
            page.evaluate("go('al')")
            page.wait_for_timeout(2500)
            page.evaluate(CLOSE)
            chip_after_profession = _chip(page)
            # KN-U-Reset (Mandatswechsel bzw. Neuladen): Serverwahrheit bleibt "Publiziert".
            _load(page, cid, "al")
            page.wait_for_timeout(2500)
            chip_after_reset = _chip(page)

            # E2E2-05 Gegenrichtung: Kurs einer nicht verwendeten Waehrung.
            assert api("PUT", "/fx-rates", {"rates": [
                {"currency": "GBP", "rate": 1.12, "source": "Manual", "confirm_current": True}]})[0] in (200, 201)
            after_gbp = _overview(api, mid)

            # E2E2-05: USD im Schnelleditor aendern (ohne Neuladen, ohne Route-Stub).
            page.evaluate("()=>{openFxQuickEditor(['USD']);}")
            page.wait_for_selector("#fxq-rate-USD", timeout=15000)
            page.fill("#fxq-rate-USD", "0.9")
            page.check("#fxq-grid .fxq-confirm[data-currency='USD']")
            page.click("#btn-fxq-save")
            page.wait_for_function("() => /Gespeichert/.test(document.getElementById('fxq-status').textContent)",
                                   timeout=30000)
            page.evaluate("cm('m-fx-quick')")
            after_usd = _overview(api, mid)
            page.wait_for_function("() => /Veraltet/.test((document.getElementById('aa-publication-status')"
                                   "||{textContent:''}).textContent)", timeout=60000)
            aa = page.evaluate("""({chip:document.getElementById('aa-publication-status').textContent.trim(),
              banner:document.getElementById('al-dirty-banner-body').textContent})""")
            page.evaluate("go('po')")
            page.wait_for_timeout(2500)
            page.evaluate(CLOSE)
            po = page.evaluate("(document.getElementById('po-status')||{textContent:''}).textContent")
            page.evaluate("go('rv')")
            page.wait_for_timeout(2500)
            page.evaluate(CLOSE)
            rv = page.evaluate("(document.getElementById('rv-hero')||{innerText:''}).innerText")
            page.close()

            # Frische Sitzung, direkt auf Review (Statuspfad aus freshness.causes).
            page = _fresh_page(browser, server, sync_api, errors)
            _load(page, cid, "rv")
            page.wait_for_timeout(3000)
            rv_fresh = page.evaluate("(document.getElementById('rv-hero')||{innerText:''}).innerText")
            cause_fresh = page.evaluate("typeof aresStaleCause==='function'?aresStaleCause():null")
        finally:
            browser.close()

    assert chip_start.startswith("Publiziert"), chip_start
    # E2E2-04
    assert after_profession_api["publication_status"] == "PUBLISHED", after_profession_api
    assert after_profession_api["freshness"]["status"] == "FRESH", after_profession_api
    assert chip_after_profession.startswith("Publiziert"), chip_after_profession
    assert chip_after_reset.startswith("Publiziert"), chip_after_reset
    # E2E2-05 Gegenrichtung
    assert after_gbp["publication_status"] == "PUBLISHED", after_gbp
    assert after_gbp["freshness"]["status"] == "FRESH", after_gbp
    # E2E2-05 KN-B-Vertrag
    assert after_usd["publication_status"] == "PUBLICATION_INVALID", after_usd
    assert after_usd["active_publication"]["status"] == "PUBLICATION_INVALID", after_usd
    assert after_usd["active_publication"]["reason_code"] == "CCX_INPUT_STALE", after_usd
    assert after_usd["freshness"]["status"] == "STALE", after_usd
    causes = after_usd["freshness"]["causes"]
    assert any(c["kind"] == "fx_rate" and c["currencies"] == ["USD"] and c["text"] == CAUSE for c in causes), causes
    # E2E2-05 UI (KN-U) auf allen drei Seiten
    assert aa["chip"] == "Veraltet · " + CAUSE, aa
    assert aa["banner"].startswith(CAUSE), aa
    assert CAUSE in po, po
    assert CAUSE in rv and "STRATEGIE VERALTET" in rv.upper(), rv
    assert CAUSE in rv_fresh, rv_fresh
    assert cause_fresh == CAUSE, cause_fresh
    assert not errors, errors


def _foundation_button(srv, sync_api):
    api = _Api(srv["base"]).login()
    status, root = api("GET", "/")
    assert status == 200, root
    with sync_api.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1500, "height": 950})
            _open(page, srv["base"], sync_api)
            _login(page)
            page.wait_for_timeout(2500)
            page.evaluate("()=>{ensureFoundationExampleButton();}")
            page.wait_for_timeout(2500)
            visible = page.evaluate("(function(){var b=document.getElementById('btn-foundation-example');"
                                    "return !!(b&&b.offsetParent!==null);})()")
        finally:
            browser.close()
    return root.get("foundation_example_available"), visible


def test_foundation_case_button_visible_in_dev_hidden_in_packaged_production(server):
    sync_api = _sync_api()
    dev_flag, dev_visible = _foundation_button(server, sync_api)
    with _backend(frozen=True) as packaged:
        prod_flag, prod_visible = _foundation_button(packaged, sync_api)
        api = _Api(packaged["base"]).login()
        status, _body = api("POST", "/admin/system/foundation-example", {})
    assert dev_flag is True and dev_visible is True, (dev_flag, dev_visible)
    assert prod_flag is False and prod_visible is False, (prod_flag, prod_visible)
    assert status == 403, status


def test_ci_runs_this_behaviour_test_with_playwright_required():
    workflow = (BACKEND.parent / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    assert "test_livetest_kern_integration_r2.py" in workflow
