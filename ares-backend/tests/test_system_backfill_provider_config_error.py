"""Admin-Backfill-Endpunkte: Marktdaten-Provider-Konfigurationsfehler.

Seit der fail-closed-Factory wirft ``build_default_aggregator()`` bei einer
nicht erfuellbaren ``MARKET_DATA_PROVIDERS``-Konfiguration einen
``ProviderConfigurationError`` (Unterklasse von ``RuntimeError``, NICHT von
``ValueError``). Die Backfill-Endpunkte fingen nur ``ValueError`` -> der
Konfigurationsfehler endete als unbehandelter 500.

Erwartet: 503 (Repo-Konvention fuer "Dienst wegen Konfiguration nicht
verfuegbar", vgl. 2FA-Schluesselkonfiguration in routers/auth.py) mit einer
festen Meldung ohne interne Details; der Originaltext landet nur im Log.
Kein Audit-Eintrag, da nichts geschrieben wurde.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, get_db
from main import app
from models.review import AuditLog
from services.auth import get_current_user
from services.market_data import factory as md_factory
from services.market_data.provider_registry import ProviderConfigurationError

_SECRET_MARKER = "licensed-feed-internal-detail-xyz"

_BACKFILL_PATHS = [
    "/admin/system/annual-returns/backfill",
    "/admin/system/asset-class-prices/backfill",
]


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'backfill_cfg_err.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def client(session_factory):
    def override_db():
        with session_factory() as s:
            yield s

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id="admin-backfill-cfg", full_name="Admin BackfillCfg",
        email="admin@test.local", role="admin",
    )
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


def _raise_config_error():
    raise ProviderConfigurationError(
        f"Explizit konfigurierte Marktdaten-Provider sind nicht verfuegbar: {_SECRET_MARKER}"
    )


@pytest.mark.parametrize("path", _BACKFILL_PATHS)
def test_provider_config_error_is_503_without_internal_details(
    client, session_factory, monkeypatch, caplog, path,
):
    monkeypatch.setattr(md_factory, "build_default_aggregator", _raise_config_error)
    with caplog.at_level(logging.ERROR):
        resp = client.post(path)

    assert resp.status_code == 503, resp.text
    detail = resp.json()["detail"]
    assert "Marktdaten" in detail
    assert _SECRET_MARKER not in resp.text
    # Logging bleibt: Originalursache steht im Server-Log.
    assert _SECRET_MARKER in caplog.text
    with session_factory() as s:
        assert s.query(AuditLog).count() == 0


@pytest.mark.parametrize("path", _BACKFILL_PATHS)
def test_value_error_still_maps_to_400(client, monkeypatch, path):
    """Zero-Regression: Parameterfehler (ValueError) bleiben 400."""
    def _raise_value_error():
        raise ValueError("from_year > to_year")

    monkeypatch.setattr(md_factory, "build_default_aggregator", _raise_value_error)
    resp = client.post(path)
    assert resp.status_code == 400, resp.text
