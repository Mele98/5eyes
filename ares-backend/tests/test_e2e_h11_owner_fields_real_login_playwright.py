"""H11 (Hygiene-Folgepunkt H10, N-899-20): "Angaben ergänzen" mit Ladehinweis,
E2E ueber den echten Login der echten App.

Befund: In der echten App erreichte "Angaben ergänzen" das Feld erst nach etwa
4-6 s (die Administration laedt), ohne Rueckmeldung. Die bisherige Fokus-E2E
lief mit einer schlanken API-Bruecke und vorgegebenem Status.

Jetzt: Der Knopf zeigt sofort "Wird geladen …" und ist gesperrt, bis die Maske
bereit ist; danach steht der Fokus im Feld und der Knopf ist wieder normal.
Ablauf: frische Instanz (Wegwerf-DB/-HOME, Wegwerf-KEK, SMTP aktiv ohne
Owner-Angaben), Manifest per API freigegeben, echter Login ueber die Maske von
``/app/ares.html``, echter Status vom Server, externe Ressourcen blockiert.
Pflichtlauf im CI-Job "Frontend Reporting Tests" (ARES_REQUIRE_PLAYWRIGHT=1).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests.test_e2e_h10_egress_banner_playwright import _call, _free_port, _sync_api

BACKEND = Path(__file__).resolve().parents[1]
USER, PWD = "e2eh11", "E2E-H11-Passwort-2026!x"
FIELD = "egress.mail.smtp.destination_country"


@pytest.fixture(scope="module")
def mail_app(tmp_path_factory):
    from cryptography.fernet import Fernet

    root = tmp_path_factory.mktemp("h11ownerfields")
    for name in ("home", "appdata", "localappdata"):
        (root / name).mkdir()
    port = int(os.environ.get("ARES_E2_PORT") or _free_port())
    env = {**os.environ, "HOME": str(root / "home"), "USERPROFILE": str(root / "home"),
           "APPDATA": str(root / "appdata"), "LOCALAPPDATA": str(root / "localappdata"),
           "DB_PATH": str(root / "ares-h11.db"), "TENANT_MASTER_KEK": Fernet.generate_key().decode(),
           "SECRET_KEY": "h11-e2e-owner-fields-wegwerf-key-0123456789", "PRICE_SCHEDULER_ENABLED": "false",
           "BACKUP_SCHEDULER_ENABLED": "false", "DATABASE_URL": "", "SERVE_MAIN_FRONTEND": "true",
           "SMTP_ENABLED": "true", "SMTP_HOST": "smtp.a.example"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(port),
         "--log-level", "warning"], cwd=str(BACKEND), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(120):
            try:
                if _call(base, "GET", "/health")[0] == 200:
                    break
            except OSError:
                pass
            time.sleep(1)
        else:
            pytest.fail("Backend startet nicht")
        status, raw = _call(base, "POST", "/auth/bootstrap-admin", {"username": USER, "password": PWD,
                                                                     "full_name": "E2E H11 Admin"})
        assert status == 201, raw
        token = json.loads(raw)["access_token"]
        assert _call(base, "POST", "/privacy/egress-manifest/approve", {}, token)[0] == 200
        status, raw = _call(base, "GET", "/privacy/egress-status", token=token)
        assert json.loads(raw)["action"] == {"label": "Angaben ergänzen", "field": FIELD}, raw
        yield base
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()


OBSERVE = """() => { window.__h11Seen = []; const b = document.getElementById('pg-egress-banner');
  new MutationObserver(() => { const k = b.querySelector('button');
    if (k) window.__h11Seen.push([k.textContent, k.disabled]); })
  .observe(b, {subtree: true, childList: true, characterData: true, attributes: true}); }"""
FOCUSED = ("() => !!(document.activeElement && document.activeElement.closest"
           "('[data-owner-field=\"" + FIELD + "\"]'))")


def _wait_until(page, js: str, timeout_s: float = 30) -> None:
    """Polling ueber evaluate (wait_for_function scheitert an der CSP ohne unsafe-eval)."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if page.evaluate(js):
            return
        page.wait_for_timeout(100)
    raise AssertionError(f"Zustand nicht erreicht: {js}")


def test_add_details_shows_loading_hint_then_focuses_the_field_after_real_login(mail_app):
    sync_api = _sync_api()
    with sync_api.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        errors: list[str] = []
        try:
            page = browser.new_page()
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.route("**/*", lambda route: route.continue_() if route.request.url.startswith(mail_app)
                       else route.abort())
            page.goto(f"{mail_app}/app/ares.html")
            page.locator("#login-username").wait_for(state="visible", timeout=30000)
            page.fill("#login-username", USER)
            page.fill("#login-password", PWD)
            page.press("#login-password", "Enter")
            banner = page.locator("#pg-egress-banner")
            banner.wait_for(state="visible", timeout=15000)
            assert "Für E-Mail fehlen noch Angaben (Land/Garantie des Anbieters)." in banner.inner_text()
            button = banner.get_by_role("button", name="Angaben ergänzen")
            page.evaluate(OBSERVE)
            # Sticky Banner: Klick per DOM (wie im H10-Realtest), danach sofort Ladehinweis.
            button.evaluate("b => b.click()")
            immediate = page.evaluate("() => { const k = document.querySelector('#pg-egress-banner button');"
                                      " return k ? [k.textContent, k.disabled] : null; }")
            _wait_until(page, FOCUSED)
            seen = page.evaluate("() => window.__h11Seen")
            final = page.evaluate("() => { const k = document.querySelector('#pg-egress-banner button');"
                                  " return k ? [k.textContent, k.disabled] : null; }")
        finally:
            browser.close()
    assert immediate == ["Wird geladen …", True], immediate
    assert ["Wird geladen …", True] in seen, seen
    assert final in (["Angaben ergänzen", False], None), final  # danach wieder bedienbar (oder Banner neu)
    assert not errors, errors


def test_ci_runs_this_test_with_playwright_required():
    workflow = (BACKEND.parent / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    job = workflow[workflow.index("\n  vitest:"):]
    assert "tests/test_e2e_h11_owner_fields_real_login_playwright.py" in job
