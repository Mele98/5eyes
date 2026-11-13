"""C-890-01 Nachtrag 1: Maske "KYC-Wiedervorlage" im echten Browser.

Ablauf gegen ein echtes, isoliertes Backend (Wegwerf-DB, Wegwerf-KEK, eigenes
HOME/APPDATA, freier Port) und die echte ares.html:

1. Firmen-Admin (Owner) sieht "Keine wirksame Frist – Kundenfreigaben gesperrt",
   erfasst eine Version (alle Fristfelder leer vorbelegt) -> Status Entwurf.
2. Selbstfreigabe: der Owner sieht keinen Freigabe-Knopf, nur den Hinweis auf
   die zweite Person; ein direkter API-Aufruf wird mit 403 verweigert.
3. Externe Compliance-Person (Rolle compliance_reviewer) meldet sich an, sieht
   NUR die Freigabe-Ansicht, gibt mit Pruefwert und Referenz frei -> wirksam.

In der CI laeuft die Datei im Job "Frontend Reporting Tests" mit
``ARES_REQUIRE_PLAYWRIGHT=1`` (fehlendes Playwright = rot); in den
Backend-Shards ist sie ein sichtbarer Skip. Alle Fristen sind TESTWERTE.
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PW = "Testpasswort-C890-1"
PW2 = "Testpasswort-C890-2"


def _playwright_sync_api():
    if os.environ.get("ARES_REQUIRE_PLAYWRIGHT") == "1":
        import playwright.sync_api as sync_api  # Pflicht: ImportError ist rot

        return sync_api
    return pytest.importorskip(
        "playwright.sync_api",
        reason="Playwright fehlt; Pflichtlauf im CI-Job 'Frontend Reporting Tests'",
    )


def test_ci_runs_this_ui_test_with_playwright_required():
    workflow = (BACKEND_ROOT.parent / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    job = workflow[workflow.index("\n  vitest:"):]
    assert "tests/test_livetest_c890_kyc_review_policy_ui.py" in job
    assert 'ARES_REQUIRE_PLAYWRIGHT: "1"' in job


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def server():
    _playwright_sync_api()
    import httpx
    from cryptography.fernet import Fernet

    tmp = Path(tempfile.mkdtemp(prefix="c890_ui_"))
    port = _free_port()
    env = dict(os.environ)
    for key in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA"):
        (tmp / key).mkdir()
        env[key] = str(tmp / key)
    env.update({
        "DB_PATH": str(tmp / "ares_c890_ui.db"), "SECRET_KEY": "c890-ui-" + "x" * 40,
        "TENANT_MASTER_KEK": Fernet.generate_key().decode(), "SERVE_MAIN_FRONTEND": "1",
        "PRICE_SCHEDULER_ENABLED": "0", "BACKUP_SCHEDULER_ENABLED": "0", "APP_ENV": "development",
        "PYTHONUNBUFFERED": "1",
    })
    env.pop("DATABASE_URL", None)
    log = open(tmp / "server.log", "wb")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(BACKEND_ROOT), env=env, stdout=log, stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(240):
            if proc.poll() is not None:
                break
            try:
                if httpx.get(base + "/auth/bootstrap-status", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        else:
            raise AssertionError("Backend nicht gestartet")
        assert proc.poll() is None, (tmp / "server.log").read_text(errors="ignore")[-3000:]
        yield base, httpx
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()
        for _ in range(40):
            shutil.rmtree(tmp, ignore_errors=True)
            if not tmp.exists():
                break
            time.sleep(0.5)


def _seed(base, httpx) -> None:
    r = httpx.post(base + "/auth/bootstrap-admin", json={
        "full_name": "Owner Test", "username": "owner", "password": PW, "email": None,
        "company_name": "TEST-C890 Firma (Testwert)", "home_jurisdiction": "CH"}, timeout=30)
    assert r.status_code == 201, r.text
    admin = {"Authorization": "Bearer " + r.json()["access_token"]}
    r = httpx.put(base + "/compliance/legal-profile", headers=admin, timeout=30, json={
        "legal_name": "TEST-C890 Firma (Testwert)", "address_street": "Teststrasse 1",
        "address_postal_code": "0000", "address_city": "Testort", "address_country": "CH",
        "business_activity": "Anlageberatung (Testwert)", "supervision_type": "anlageberater_ohne_prudenzielle_aufsicht",
        "license_reference": "Testregister", "ombudsman_name": "Ombudsstelle (Testwert)",
        "ombudsman_address": "Testadresse", "contact_email": "test@example.invalid"})
    assert r.status_code == 200, r.text
    return admin


def _invite_api(base, httpx, admin) -> str:
    r = httpx.post(base + "/users/invite", headers=admin, timeout=30, json={
        "username": "extern", "full_name": "Externe Compliance (Test)", "email": "extern@testfirma.ch",
        "role": "compliance_reviewer", "reviewer_organisation": "TEST-C890 Revision AG",
        "reviewer_reference": "TEST-C890 Mandat 1"})
    assert r.status_code == 201, r.text
    return r.json()["invite_token"]


def _activate_reviewer(base, httpx, token):
    """Die externe Person nimmt die Einladung an (Passwort selbst) und richtet
    2FA selbst ein (N-897-02). Rueckgabe: (API-Header, TOTP-Secret)."""
    from services import totp

    r = httpx.post(base + "/auth/invite/accept", json={"token": token, "password": PW2}, timeout=30)
    assert r.status_code == 200, r.text
    rev = {"Authorization": "Bearer " + r.json()["access_token"]}
    secret = httpx.post(base + "/auth/2fa/setup", headers=rev, timeout=30).json()["secret"]
    r = httpx.post(base + "/auth/2fa/enable", headers=rev, timeout=30,
                   json={"code": totp.totp_at(secret, time.time())})
    assert r.status_code == 200, r.text
    return rev, secret


def _login(page, base, user, password, totp_secret=None):
    page.goto(base + "/app/ares.html")
    page.evaluate("document.getElementById('intro-screen') && document.getElementById('intro-screen').remove()")
    page.fill("#login-username", user)
    page.fill("#login-password", password)
    page.evaluate("doLogin()")
    if totp_secret:
        from services import totp

        page.wait_for_function("(document.getElementById('login-error')||{}).textContent.indexOf('2FA') >= 0")
        # naechstes Zeitfenster (Drift-Toleranz): der Code der Aktivierung ist verbraucht.
        page.fill("#login-totp", totp.totp_at(totp_secret, time.time() + 30))
        page.evaluate("doLogin()")


def test_capture_self_approval_refused_reviewer_approves_effective(server):
    base, httpx = server
    _seed(base, httpx)
    sync_api = _playwright_sync_api()
    today = datetime.now(timezone.utc).date().isoformat()
    with sync_api.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            _login(page, base, "owner", PW)
            page.wait_for_function("typeof currentUser !== 'undefined' && currentUser && currentUser.role === 'admin'")
            page.evaluate("openAdminModal()")
            page.wait_for_selector("#asec-kyc-review-policy", state="attached")
            page.evaluate("document.getElementById('asec-kyc-review-policy').click()")
            page.wait_for_selector("#krp-banner")
            assert "Keine wirksame Frist – Kundenfreigaben gesperrt" in page.inner_text("#krp-banner")
            for field in ("#krp-normal", "#krp-elevated", "#krp-valid-from", "#krp-policy-id", "#krp-source"):
                assert page.input_value(field) == "", field
            page.fill("#krp-policy-id", "TEST-C890-UI")
            page.fill("#krp-normal", "23")
            page.fill("#krp-elevated", "11")
            page.fill("#krp-valid-from", today)
            page.fill("#krp-source", "TEST-C890 Testwert (keine Owner-Frist)")
            page.evaluate("createKycReviewPolicy()")
            page.wait_for_selector("tr[data-policy-status='entwurf']")
            row_text = page.inner_text("tr[data-policy-status='entwurf']")
            assert "Entwurf" in row_text and "23 Monate" in row_text
            assert page.locator(".krp-self").count() == 1
            assert page.locator("[id^='krp-approve-']").count() == 0
            refused = page.evaluate("""async () => {
              const o = await API.get('/compliance/kyc-review-policies');
              const p = o.policies[0];
              try { await API.post('/compliance/kyc-review-policies/' + p.id + '/activate',
                                   {policy_hash: p.policy_hash, approval_reference: 'Selbst'}); return 'ok'; }
              catch (e) { return String(e.status || '') + ' ' + JSON.stringify(e.detail || ''); }
            }""")
            assert refused.startswith("403") and "KYC_REVIEW_POLICY_SAME_PERSON" in refused, refused
            # Einladung der externen Person ueber die Maske (Identitaet, kein Passwort).
            page.fill("#krp-inv-name", "Externe Compliance (Test)")
            page.fill("#krp-inv-username", "extern")
            page.fill("#krp-inv-email", "extern@testfirma.ch")
            page.fill("#krp-inv-org", "TEST-C890 Revision AG")
            page.fill("#krp-inv-ref", "TEST-C890 Mandat 1")
            page.evaluate("inviteKycReviewer()")
            page.wait_for_selector("#krp-inv-token")
            token = page.inner_text("#krp-inv-token").split("invite=")[-1].strip()
            page.evaluate("doLogout()")
            _rev, secret = _activate_reviewer(base, httpx, token)

            _login(page, base, "extern", PW2, secret)
            page.wait_for_selector("#krp-reviewer-view #krp-banner")
            assert "Compliance-Freigabe" in page.inner_text("#krp-reviewer-view")
            assert page.locator("#krp-reviewer-view #btn-krp-create").count() == 0
            hash_text = page.inner_text("[id^='krp-hash-']").strip()
            assert len(hash_text) == 64
            row_id = page.get_attribute("[id^='krp-hash-']", "id").replace("krp-hash-", "")
            page.fill(f"#krp-ref-{row_id}", "TEST-C890 Freigabe externe Compliance")
            page.check(f"#krp-ok-{row_id}")
            page.evaluate(f"activateKycReviewPolicy('{row_id}')")
            page.wait_for_selector("#krp-banner[data-status='effective']")
            assert "Wirksame Frist: Policy TEST-C890-UI Version 1" in page.inner_text("#krp-banner")
            assert page.locator("tr[data-policy-status='wirksam']").count() == 1
            blocked = page.evaluate("""async () => {
              try { await API.get('/clients'); return 'ok'; } catch (e) { return String(e.status); }
            }""")
            assert blocked == "403"
        finally:
            browser.close()


def test_reviewer_decides_open_kyc_second_approval_in_browser(server):
    """Nachtrag 2: PEP-Bestaetigung -> die externe Compliance-Person sieht sie
    datenminimiert unter "Offene KYC-Freigaben" und gibt frei -> wirksam."""
    base, httpx = server
    _seed(base, httpx)
    owner = {"Authorization": "Bearer " + httpx.post(base + "/auth/login", json={
        "username": "owner", "password": PW}, timeout=30).json()["access_token"]}
    rev, secret = _activate_reviewer(base, httpx, _invite_api(base, httpx, owner))
    today = datetime.now(timezone.utc).date()
    row = httpx.post(base + "/compliance/kyc-review-policies", headers=owner, timeout=30, json={
        "jurisdiction": "CH", "policy_id": "TEST-C890-UI", "normal_max_months": 23, "elevated_max_months": 11,
        "valid_from": today.isoformat(), "source_reference": "TEST-C890 Testwert"}).json()
    r = httpx.post(base + f"/compliance/kyc-review-policies/{row['id']}/activate", headers=rev, timeout=30,
                   json={"policy_hash": row["policy_hash"], "approval_reference": "TEST-C890"})
    assert r.status_code == 200, r.text
    me = httpx.get(base + "/auth/me", headers=owner, timeout=30).json()
    c = httpx.post(base + "/clients", headers=owner, timeout=30, json={
        "client_number": "K-UI-1", "first_name": "Vorname", "last_name": "Geheim", "advisor_id": me["id"]})
    assert c.status_code in (200, 201), c.text
    cid = c.json()["id"]
    httpx.put(base + f"/clients/{cid}/due-diligence", headers=owner, timeout=30,
              json={"acting_for_own_account": True, "pep_status": True})
    from datetime import timedelta

    k = httpx.post(base + f"/clients/{cid}/kyc-confirmations", headers=owner, timeout=30, json={
        "form_type": "A", "form_completed_on": (today - timedelta(days=2)).isoformat(),
        "external_reference": "SRO-UI-1", "risk_category": "normal", "is_pep": True,
        "identification_confirmed": True, "identification_date": (today - timedelta(days=2)).isoformat(),
        "next_review_due": (today + timedelta(days=60)).isoformat()})
    assert k.status_code == 201, k.text
    kid = k.json()["id"]
    sync_api = _playwright_sync_api()
    with sync_api.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            _login(page, base, "extern", PW2, secret)
            page.wait_for_selector(f"#krp-reviewer-view .krp-approval[data-confirmation-id='{kid}']")
            card = page.inner_text(f".krp-approval[data-confirmation-id='{kid}']")
            assert "Kunde K-UI-1" in card and "PEP" in card and "SRO-UI-1" in card
            assert "Geheim" not in card and "Vorname" not in card
            page.fill(f"#krp-reason-{kid}", "PEP-Abklaerung im SRO-Dossier geprueft (Test)")
            page.check(f"#krp-cok-{kid}")
            page.evaluate(f"decideKycApproval('{kid}', 'approve')")
            page.wait_for_selector("#krp-approvals-empty")
        finally:
            browser.close()
    confs = httpx.get(base + f"/clients/{cid}/kyc-confirmations", headers=owner, timeout=30).json()
    assert confs[0]["approval"]["approved_by"] != me["id"]
    assert confs[0]["approval"]["note"].startswith("PEP-Abklaerung")
