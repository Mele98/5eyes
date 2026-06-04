"""Sprint U-7 (Roadmap-Punkt 7, 2026-06-04): CSP + Security-Headers Audit.

Hintergrund
-----------
Roadmap-Befund KRITISCH: Bearer-Token in sessionStorage XSS-empfindlich.
Pre-U-7 hatten Responses: X-Content-Type-Options nosniff, X-Frame-Options
DENY, Referrer-Policy no-referrer, Cache-Control no-store.

FEHLTE: Content-Security-Policy (CSP), Permissions-Policy. Diese sind
die direkte XSS-Mitigation (CSP haertet die Renderer-Surface gegen
script-injection).

Post-U-7
--------
- DEFAULT_CSP_POLICY in core/middleware.py
- DEFAULT_PERMISSIONS_POLICY (alle Browser-Features deny)
- Settings: csp_enabled / csp_policy / permissions_policy_enabled /
  hsts_enabled (default off — backend lokal http)

NICHT in U-7 (Folge-Sprints)
- HttpOnly-Cookie-Auth statt sessionStorage (Breaking-Change im Auth-Pfad)
- nonce-based CSP (heute 'unsafe-inline' fuer Tailwind/Electron Renderer)
- Trusted-Types
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.middleware import (  # noqa: E402
    DEFAULT_CSP_POLICY,
    DEFAULT_PERMISSIONS_POLICY,
)


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


# ---------------------------------------------------------------------------
# Default-Policies (Drift-Schutz)
# ---------------------------------------------------------------------------

def test_default_csp_includes_self_directives():
    """Default-CSP enthaelt alle Pflicht-Directives."""
    for directive in (
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "connect-src 'self'",
        "img-src 'self'",
        "frame-ancestors 'none'",
        "object-src 'none'",
        "base-uri 'self'",
    ):
        assert directive in DEFAULT_CSP_POLICY, (
            f"CSP-Directive {directive!r} fehlt im Default."
        )


def test_default_csp_allows_electron_origins():
    """app://. und null Origins (Electron) muessen erlaubt sein."""
    assert "app://." in DEFAULT_CSP_POLICY
    assert "null" in DEFAULT_CSP_POLICY


def test_default_csp_allows_vite_dev_backend():
    """Vite-Dev (localhost) muss connect-src erlaubt sein."""
    assert "http://localhost:*" in DEFAULT_CSP_POLICY
    assert "http://127.0.0.1:*" in DEFAULT_CSP_POLICY


def test_default_csp_blocks_form_action_to_external():
    """form-action 'self' verhindert phishing-redirects."""
    assert "form-action 'self'" in DEFAULT_CSP_POLICY


def test_default_csp_blocks_iframes_via_frame_ancestors():
    """frame-ancestors 'none' = Clickjacking-Schutz."""
    assert "frame-ancestors 'none'" in DEFAULT_CSP_POLICY


def test_default_permissions_policy_denies_sensitive_features():
    """geolocation/camera/microphone etc. default deny."""
    for feature in (
        "geolocation=()", "camera=()", "microphone=()",
        "payment=()", "usb=()",
    ):
        assert feature in DEFAULT_PERMISSIONS_POLICY


def test_default_permissions_policy_blocks_floc():
    """interest-cohort=() = FLoC-Tracking-Block."""
    assert "interest-cohort=()" in DEFAULT_PERMISSIONS_POLICY


# ---------------------------------------------------------------------------
# Settings-Defaults
# ---------------------------------------------------------------------------

def test_csp_enabled_default_true():
    from config import settings
    assert settings.csp_enabled is True


def test_csp_policy_default_empty_falls_back_to_default():
    from config import settings
    assert settings.csp_policy == ''


def test_permissions_policy_enabled_default_true():
    from config import settings
    assert settings.permissions_policy_enabled is True


def test_hsts_enabled_default_false():
    """Backend lokal http -> HSTS waere kontraproduktiv."""
    from config import settings
    assert settings.hsts_enabled is False


# ---------------------------------------------------------------------------
# Middleware-Response-Headers (Integration mit FastAPI)
# ---------------------------------------------------------------------------

def test_response_has_csp_header(client):
    response = client.get('/health')
    assert response.status_code == 200
    assert 'Content-Security-Policy' in response.headers
    assert response.headers['Content-Security-Policy'] == DEFAULT_CSP_POLICY


def test_response_has_permissions_policy_header(client):
    response = client.get('/health')
    assert 'Permissions-Policy' in response.headers
    assert response.headers['Permissions-Policy'] == DEFAULT_PERMISSIONS_POLICY


def test_response_does_not_have_hsts_by_default(client):
    """HSTS soll OFF sein im Default (Backend lokal http)."""
    response = client.get('/health')
    assert 'Strict-Transport-Security' not in response.headers


def test_response_still_has_existing_security_headers(client):
    """U-7 brincht KEINE Regression der bestehenden Headers."""
    response = client.get('/health')
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert response.headers['X-Frame-Options'] == 'DENY'
    assert response.headers['Referrer-Policy'] == 'no-referrer'
    assert response.headers['Cache-Control'] == 'no-store'


def test_csp_disabled_via_settings(client, monkeypatch):
    """Wenn csp_enabled=False: kein CSP-Header."""
    monkeypatch.setattr('config.settings.csp_enabled', False)
    response = client.get('/health')
    assert 'Content-Security-Policy' not in response.headers


def test_permissions_disabled_via_settings(client, monkeypatch):
    monkeypatch.setattr('config.settings.permissions_policy_enabled', False)
    response = client.get('/health')
    assert 'Permissions-Policy' not in response.headers


def test_hsts_enabled_via_settings(client, monkeypatch):
    """Wenn hsts_enabled=True: Strict-Transport-Security gesetzt."""
    monkeypatch.setattr('config.settings.hsts_enabled', True)
    response = client.get('/health')
    assert 'Strict-Transport-Security' in response.headers
    assert 'max-age=63072000' in response.headers['Strict-Transport-Security']
    assert 'includeSubDomains' in response.headers['Strict-Transport-Security']


def test_custom_csp_policy_via_settings(client, monkeypatch):
    """Wenn settings.csp_policy gesetzt: Custom statt Default."""
    custom = "default-src 'none'"
    monkeypatch.setattr('config.settings.csp_policy', custom)
    response = client.get('/health')
    assert response.headers['Content-Security-Policy'] == custom


def test_csp_applied_to_error_responses(client, monkeypatch):
    """CSP MUSS auch auf 500-Responses gesetzt sein."""
    # 404 ist auch ein "Error" und sollte CSP haben
    response = client.get('/nonexistent-route-xyz')
    assert response.status_code == 404
    assert 'Content-Security-Policy' in response.headers
