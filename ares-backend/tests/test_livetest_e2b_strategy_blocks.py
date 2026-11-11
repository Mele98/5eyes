"""E2b Pflicht-Livetest: Uebernahme der Kundenausschluesse in die
Strategiebausteine und Veraltet-Status je Mandat (N-888-11/14/16 uebernommen).

Echter Ablauf: isolierter Backend-Prozess (Temp-DB/HOME/APPDATA/
LOCALAPPDATA, Wegwerf-KEK, freier Port), echte App, echter Login, echter
Mandatswechsel A -> B -> A in Chromium. Synthetischer Ausschlussnachweis
(freigegeben, Quelle Prospekt, Stichtag heute) direkt in der Wegwerf-DB, damit
der Ausschluss "Tabak" fuer Mandat A belegt erfuellbar und damit waehlbar ist.

* Mandat A: Strategie VOR der Erfassung mit ``tobacco=overweight``, danach
  Ausschluss Tabak erfasst -> Banner "veraltet", "Portfolio umsetzen"
  ausgeblendet und deaktiviert; im Block Nachhaltigkeit ist Tabak
  "Ausschliessen", deaktiviert, mit Hinweis "aus Kundenpraeferenz".
* Mandat B (sauber, keine Erfassung): Button sichtbar und aktiv, Tilt frei.
* Zurueck auf A: wieder veraltet und read-only.

Pflichtlauf im CI-Job "Frontend Reporting Tests" (``ARES_REQUIRE_PLAYWRIGHT=1``).
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest

from tests.test_livetest_e2a_sustainability_flow import _Api, _free_port, _playwright_sync_api

BACKEND = Path(__file__).resolve().parents[1]
USER, PWD = "e2b.admin", "E2b-Probe-Passwort-2026!x"


@pytest.fixture(scope="module")
def server():
    _playwright_sync_api()
    from cryptography.fernet import Fernet

    tmp = Path(tempfile.mkdtemp(prefix="e2b_blocks_"))
    for sub in ("home", "appdata", "localappdata"):
        (tmp / sub).mkdir()
    port = _free_port()
    db_path = tmp / "e2b.db"
    env = {
        **os.environ,
        "HOME": str(tmp / "home"), "USERPROFILE": str(tmp / "home"),
        "APPDATA": str(tmp / "appdata"), "LOCALAPPDATA": str(tmp / "localappdata"),
        "DB_PATH": str(db_path), "SECRET_KEY": "e2b-blocks-secret-key-0123456789abcdef",
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


def _seed_mandate(api, advisor_id: str, label: str, tilts: dict) -> tuple[str, str]:
    from tests.risk_fixture_helpers import standard_risk_payload

    stamp = f"{label}-{int(time.time() * 1000)}"
    status, client = api("POST", "/clients", {
        "client_number": f"E2B-{stamp}", "first_name": label, "last_name": "Probe",
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
    status, body = api("POST", f"/mandates/{mid}/target-allocation/generate", {"preferences": {"tilts": tilts}})
    assert status == 200, body
    # Produktlauf (legt u. a. den Standard-Produktkatalog an).
    status, body = api("POST", f"/mandates/{mid}/recommendations/generate", {})
    assert status == 200, body
    return cid, mid


def _seed_tobacco_evidence(db_path: Path, needed: list[str], advisor_id: str) -> int:
    """Je benoetigter Sub-Anlageklasse ein freigegebener Ausschlussnachweis
    (synthetisch; gleiche Kandidatenregel wie die Abdeckungspruefung)."""
    today = date.today()
    now = today.isoformat() + "T00:00:00.000Z"
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT id, sub_asset_class, asset_class FROM products WHERE is_active = 1 AND deleted_at IS NULL"
        ).fetchall()
        seeded = set()
        for sub in needed:
            exact = [r for r in rows if (r[1] or "").strip() == sub]
            if not exact:
                continue
            for product_id, _sub, _asset in exact[:1]:
                if product_id in seeded:
                    continue
                seeded.add(product_id)
                conn.execute(
                    "INSERT INTO product_sustainability_attributes (id, product_id, tenant_id, category, kind, "
                    "revenue_threshold_bps, source_type, source_reference, as_of, valid_until, status, "
                    "created_by, created_at, approved_by, approved_at, approval_mode, updated_at) VALUES "
                    "(?, ?, NULL, 'tobacco', 'exclusion_policy', 0, 'prospectus', 'Synthetischer Prospekt', "
                    "?, ?, 'approved', ?, ?, ?, ?, 'single_approver_attested', ?)",
                    (str(uuid.uuid4()), product_id, (today - timedelta(days=1)).isoformat(),
                     (today + timedelta(days=300)).isoformat(), advisor_id, now, advisor_id, now, now),
                )
        conn.commit()
        return len(seeded)
    finally:
        conn.close()


def test_strategy_blocks_follow_customer_exclusion_per_real_mandate(server):
    from core import sustainability_preference as sp

    sync_api = _playwright_sync_api()
    shots = os.environ.get("ARES_E2_SCREENSHOT_DIR")
    api = _Api(server["base"])
    api("POST", "/auth/bootstrap-admin", {"username": USER, "password": PWD, "full_name": "E2b Admin",
                                          "company_name": "Probe AG", "home_jurisdiction": "CH"})
    status, login = api("POST", "/auth/login", {"username": USER, "password": PWD})
    assert status == 200, login
    api.token = login["access_token"]
    advisor_id = api("GET", "/auth/me")[1]["id"]
    cid_a, mid_a = _seed_mandate(api, advisor_id, "Verletzt", {"tobacco": "overweight"})
    cid_b, _mid_b = _seed_mandate(api, advisor_id, "Sauber", {})
    coverage = api("GET", f"/mandates/{mid_a}/strategy-option-coverage")[1]
    assert not {o["key"]: o for o in coverage["options"]}["exclusion:tobacco"]["available"]
    seeded = _seed_tobacco_evidence(server["db"], coverage["needed_sub_asset_classes"], advisor_id)
    assert seeded > 0, coverage["needed_sub_asset_classes"]
    coverage = api("GET", f"/mandates/{mid_a}/strategy-option-coverage")[1]
    tobacco = {o["key"]: o for o in coverage["options"]}["exclusion:tobacco"]
    if not tobacco["available"]:
        pytest.fail(f"Abdeckung Tabak nicht belegt: {tobacco}")
    status, body = api("POST", f"/mandates/{mid_a}/sustainability-preferences", {
        "questionnaire_version": sp.QUESTIONNAIRE_VERSION, "definition_hash": sp.definition_hash(),
        "response_status": "answered", "esg_relevance": "yes", "esg_characteristic": "esg_factors",
        "exclusions": ["tobacco"], "information_acknowledged": True, "client_confirmed": True,
        "capture_channel": "in_person"})
    assert status == 201 and body["allocation_floor_status"] == "violated", body

    close = "document.querySelectorAll('.overlay.open').forEach(function(o){o.classList.remove('open');})"
    state = ("() => {const u=document.getElementById('btn-portfolio-umsetzen');"
             "const b=document.getElementById('al-dirty-banner');"
             "const t=document.getElementById('aa-tilt-tobacco');"
             "const n=document.getElementById('sust-floor-tobacco');"
             "return {button: getComputedStyle(u).display, disabled: u.disabled,"
             " banner: getComputedStyle(b).display, tilt: t ? t.value : null, tiltDisabled: t ? t.disabled : null,"
             " note: n ? n.textContent : null, described: t ? t.getAttribute('aria-describedby') : null};}")
    with sync_api.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        errors: list[str] = []
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
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

            def open_mandate(cid: str, name: str) -> dict:
                page.evaluate(close)
                page.evaluate(f"loadClientById('{cid}')")
                page.wait_for_timeout(3000)
                page.evaluate(close)
                page.evaluate("go('al')")
                page.wait_for_timeout(3000)
                page.evaluate(close)
                page.evaluate("openAllocationPreferencesModal()")
                page.wait_for_timeout(2000)
                if shots:
                    Path(shots).mkdir(parents=True, exist_ok=True)
                    panel = page.locator("#sbb-sec-esg")
                    if panel.count():
                        panel.screenshot(path=str(Path(shots) / name))
                return page.evaluate(state)

            bad = open_mandate(cid_a, "e2b_1_mandat_a_aus_kundenpraeferenz.png")
            ok = open_mandate(cid_b, "e2b_2_mandat_b_frei.png")
            bad_again = open_mandate(cid_a, "e2b_3_mandat_a_wieder.png")
        finally:
            browser.close()
    assert bad["button"] == "none" and bad["disabled"] is True and bad["banner"] == "flex", bad
    assert bad["tilt"] == "exclude" and bad["tiltDisabled"] is True, bad
    assert "aus Kundenpräferenz" in (bad["note"] or "") and bad["described"] == "sust-floor-tobacco"
    assert ok["button"] != "none" and ok["disabled"] is False, ok
    assert ok["tiltDisabled"] is False and not ok["note"], ok
    assert bad_again["button"] == "none" and bad_again["tiltDisabled"] is True, bad_again
    assert not errors, errors


def test_ci_runs_this_behaviour_test_with_playwright_required():
    workflow = (BACKEND.parent / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    job = workflow[workflow.index("\n  vitest:"):]
    assert 'ARES_REQUIRE_PLAYWRIGHT: "1"' in job
    assert "tests/test_livetest_e2b_strategy_blocks.py" in job
