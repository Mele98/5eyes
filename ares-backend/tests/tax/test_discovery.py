"""Tests fuer Entry-Point-basierte Discovery externer Tax-Regimes.

Wir koennen kein echtes Drittpaket installieren, simulieren aber das
Entry-Point-Loading via Monkey-Patching von importlib.metadata.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def test_discovery_result_empty_when_no_entry_points(monkeypatch):
    """Ohne registrierte Entry-Points: leeres Ergebnis, succeeded=True."""
    from services.tax import discovery

    monkeypatch.setattr(discovery, "_list_entry_points", lambda: [])
    result = discovery.discover_external_regimes()
    assert result.discovered_count == 0
    assert result.loaded_plugins == ()
    assert result.failed_plugins == ()
    assert result.succeeded is True


def test_discovery_loads_successful_plugin(monkeypatch):
    """Erfolgreiches ep.load() landet in loaded_plugins."""
    from services.tax import discovery

    loaded_marker = {"called": False}

    def fake_load():
        loaded_marker["called"] = True
        return "dummy-regime-class"

    fake_ep = SimpleNamespace(name="vn", load=fake_load)
    monkeypatch.setattr(discovery, "_list_entry_points", lambda: [fake_ep])

    result = discovery.discover_external_regimes()
    assert result.discovered_count == 1
    assert result.loaded_plugins == ("vn",)
    assert result.failed_plugins == ()
    assert result.succeeded is True
    assert loaded_marker["called"]


def test_discovery_swallows_plugin_load_error(monkeypatch):
    """Kaputtes Plugin landet in failed_plugins, NICHT in loaded.
    Boot-Recovery: keine Exception nach aussen."""
    from services.tax import discovery

    def boom():
        raise ImportError("module nicht vorhanden")

    fake_ep = SimpleNamespace(name="broken", load=boom)
    monkeypatch.setattr(discovery, "_list_entry_points", lambda: [fake_ep])

    result = discovery.discover_external_regimes()
    assert result.discovered_count == 1
    assert result.loaded_plugins == ()
    assert len(result.failed_plugins) == 1
    failed_name, failed_msg = result.failed_plugins[0]
    assert failed_name == "broken"
    assert "ImportError" in failed_msg
    assert result.succeeded is False


def test_discovery_raise_on_error_propagates(monkeypatch):
    """raise_on_error=True propagiert die Plugin-Exception."""
    from services.tax import discovery

    def boom():
        raise RuntimeError("kaputt")

    fake_ep = SimpleNamespace(name="x", load=boom)
    monkeypatch.setattr(discovery, "_list_entry_points", lambda: [fake_ep])

    try:
        discovery.discover_external_regimes(raise_on_error=True)
    except RuntimeError as exc:
        assert "kaputt" in str(exc)
    else:
        raise AssertionError("Erwartete RuntimeError wurde nicht geworfen")


def test_discovery_skip_plugins_filter(monkeypatch):
    """skip_plugins blockiert das Load, aber nicht den Boot."""
    from services.tax import discovery

    fake_eps = [
        SimpleNamespace(name="vn", load=lambda: "vn-class"),
        SimpleNamespace(name="dont_load_me", load=lambda: 1 / 0),
    ]
    monkeypatch.setattr(discovery, "_list_entry_points", lambda: fake_eps)

    result = discovery.discover_external_regimes(skip_plugins=["dont_load_me"])
    assert result.loaded_plugins == ("vn",)
    assert result.skipped_plugins == ("dont_load_me",)
    assert result.failed_plugins == ()


def test_discovery_entry_point_group_constant():
    """Group-Konstante muss stabil bleiben — Drittanbieter pinnen sie."""
    from services.tax.discovery import EXTERNAL_REGIME_ENTRY_POINT_GROUP
    assert EXTERNAL_REGIME_ENTRY_POINT_GROUP == "5eyes.tax_regime"


def test_discovery_handles_entry_points_api_failure(monkeypatch):
    """Wenn die metadata-API selbst crashed, Boot ueberlebt."""
    from services.tax import discovery

    def explode():
        raise OSError("kaputt OS")

    monkeypatch.setattr(discovery, "_list_entry_points", explode)
    result = discovery.discover_external_regimes()
    assert result.discovered_count == 0
    assert result.loaded_plugins == ()
