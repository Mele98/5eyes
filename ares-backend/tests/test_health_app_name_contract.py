"""Vertrag der ``app_name``-Kette (Health-Handshake Backend <-> Desktop).

Das Backend meldet ``settings.app_name`` im ``app``-Feld von ``/health``,
``/health/ready`` und ``/``. Die Desktop-Shell uebernimmt ein laufendes
Backend nur, wenn dieser Wert exakt ihrer Erwartung entspricht; sonst
startet sie ein eigenes Backend und bricht nach 60 s ab. Default,
Beispielkonfiguration und Desktop-Erwartung muessen deshalb denselben
Wert tragen (Spec §3: ``Ares API``).

Eine ausgerollte ``.env`` mit einem abweichenden ``APP_NAME`` blockiert den
Start; die Bereinigung bestehender Installationen uebernimmt der
Migrationsschritt fuer die Konfiguration.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DESKTOP_ROOT = BACKEND_ROOT.parent / "ares-desktop"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

EXPECTED_APP = "Ares API"


class _FakeBind:
    url = "sqlite:///:memory:"


class _FakeOKSession:
    def execute(self, *args, **kwargs):
        result = MagicMock()
        result.scalar.return_value = 1
        return result

    def get_bind(self):
        return _FakeBind()

    def close(self):
        pass


def test_settings_default_app_name(monkeypatch):
    from config import Settings

    monkeypatch.delenv("APP_NAME", raising=False)
    assert Settings(_env_file=None).app_name == EXPECTED_APP
    assert Settings.model_fields["app_name"].default == EXPECTED_APP


def _default_app_name() -> str:
    from config import Settings

    return Settings.model_fields["app_name"].default


@pytest.fixture
def client(monkeypatch):
    from config import settings
    from database import get_db
    from main import app

    # Unabhaengig von einer lokalen .env: geprueft wird der Default.
    monkeypatch.setattr(settings, "app_name", _default_app_name())

    def _override():
        yield _FakeOKSession()

    app.dependency_overrides[get_db] = _override
    try:
        # Ohne Lifespan: kein init_db, keine Hintergrunddienste.
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.parametrize("path", ["/health", "/health/live", "/health/ready", "/"])
def test_health_payloads_report_product_app_name(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert response.json()["app"] == EXPECTED_APP


def test_env_example_matches_default():
    text = (BACKEND_ROOT / ".env.example").read_text(encoding="utf-8")
    values = [
        line.split("=", 1)[1].strip()
        for line in text.splitlines()
        if line.strip().upper().startswith("APP_NAME=")
    ]
    assert values == [EXPECTED_APP]


def test_desktop_probe_expects_exactly_the_product_app_name():
    src = (DESKTOP_ROOT / "main.js").read_text(encoding="utf-8")
    match = re.search(r"^const EXPECTED_BACKEND_APP = (.+);$", src, re.MULTILINE)
    assert match, "EXPECTED_BACKEND_APP-Definition nicht gefunden"
    # Fester Wert, kein Umgebungs-Override: eine Alt-Variable darf die
    # Erwartung nicht verschieben.
    assert match.group(1) == f"'{EXPECTED_APP}'"
    assert "BACKEND_APP_NAME" not in src
    assert "result.json.app : null" in src
    assert "appName === EXPECTED_BACKEND_APP" in src
