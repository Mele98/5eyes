"""KN-B / E2E2-10: "Foundation Case laden" nur im Entwicklungs-/Demo-Modus.

Befund (Dok. 117): Auf jeder frischen Installation stand fuer Admins
"Foundation Case laden"; ein Klick legte ohne Rueckfrage einen Systemfall als
Kunde an. Der Endpoint sperrte bisher nur bei ``app_env=production``; die
gepackte Desktop-Installation laeuft aber mit dem Default ``development``.

Jetzt gilt ``settings.foundation_example_available``: gesperrt bei
``app_env=production`` und in der gepackten Produktivinstallation
(PyInstaller-EXE, ``sys.frozen``). Bestehende Merkmale, kein neuer Schalter.
GET / meldet ``foundation_example_available`` (fuer KN-U: Knopf ausblenden).

Gegenprobe: Property auf ``True`` -> die Sperr-Tests werden rot.
"""
from __future__ import annotations

import sys

from tests.test_system_admin_audit_trail import _client, app, system_router
from test_optimizer_shadow_mode import session_factory  # noqa: F401


def test_available_only_outside_production_and_packaged(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert settings.foundation_example_available is True
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert settings.foundation_example_available is False
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(settings, "app_env", "production")
    assert settings.foundation_example_available is False


def test_packaged_install_blocks_endpoint_and_creates_nothing(session_factory, monkeypatch):
    calls = []
    monkeypatch.setattr(system_router, "upsert_foundation_example_case",
                        lambda db, user: calls.append(1) or {"status": "created"})
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    try:
        with _client(session_factory) as client:
            response = client.post("/admin/system/foundation-example")
            health = client.get("/").json()
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 403, response.text
    assert "Produktivinstallation" in response.json()["detail"]
    assert calls == []
    assert health["foundation_example_available"] is False


def test_development_still_allows_endpoint(session_factory, monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(system_router, "upsert_foundation_example_case",
                        lambda db, user: {"mandate_id": "m-dev", "status": "created"})
    try:
        with _client(session_factory) as client:
            response = client.post("/admin/system/foundation-example")
            health = client.get("/").json()
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200, response.text
    assert health["foundation_example_available"] is True
