"""Regressions-Sperre: Frontend-Masken fuer Passwort-Reset (#27) und 2FA-Recovery-
Codes (#25) sind verdrahtet (Login-Link, ?reset-Boot-Handler, Reset-Modal,
Recovery-Code-Anzeige nach 2FA-Enable + Regenerate).
"""
from pathlib import Path


HTML_PATH = Path(__file__).resolve().parents[2] / "5eyes-electron" / "frontend" / "5eyes_v2.html"


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def test_password_reset_link_and_modal():
    html = _html()
    assert "Passwort vergessen?" in html
    assert 'id="m-reset"' in html
    assert "function openResetRequest()" in html


def test_reset_request_and_confirm_call_backend():
    html = _html()
    assert "'/auth/password-reset/request'" in html
    assert "'/auth/password-reset/confirm'" in html
    assert "new_password:pw" in html  # korrektes Feld fuer den Confirm-Endpoint


def test_reset_token_boot_handler():
    html = _html()
    assert "function checkResetParam()" in html
    assert "_getQueryParam('reset')" in html
    assert "if (await checkResetParam()) return;" in html


def test_2fa_enable_shows_recovery_codes():
    html = _html()
    assert "function render2faRecoveryCodes(" in html
    assert "res.recovery_codes" in html
    assert "'/auth/2fa/recovery/regenerate'" in html
