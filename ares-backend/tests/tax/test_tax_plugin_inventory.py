"""W2-804-01: SDK-2-Kompatibilitaet und erwarteter Tax-Plugin-Bestand.

Synthetischer Plugin-Bestand via Monkey-Patching von
``discovery._list_entry_points`` (kein echtes Drittpaket noetig).
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.tax import discovery, plugin_inventory, registry  # noqa: E402
from services.tax.plugin_inventory import (  # noqa: E402
    TaxPluginInventoryError,
    load_external_tax_plugins,
)


def _plugin(name: str, sdk: object = "2.0.0", *, dist_version: str = "1.0.0", pattern: str | None = None):
    """Synthetischer Entry-Point; load() registriert ein Regime wie ein echtes Plugin."""
    calls = {"n": 0}

    def load():
        calls["n"] += 1

        @registry.register_regime(pattern or f"ZZ-{name.upper()}")
        class _Regime:
            id = pattern or f"ZZ-{name.upper()}"

        obj = SimpleNamespace(regime=_Regime)
        if sdk is not None:
            obj.TAX_SDK_TARGET_VERSION = sdk
        return obj

    ep = SimpleNamespace(name=name, load=load, dist=SimpleNamespace(version=dist_version))
    return ep, calls


@pytest.fixture(autouse=True)
def _isolated_registry():
    regimes = dict(registry.REGIME_REGISTRY)
    jurisdictions = dict(registry.JURISDICTION_REGISTRY)
    yield
    registry.REGIME_REGISTRY.clear()
    registry.REGIME_REGISTRY.update(regimes)
    registry.JURISDICTION_REGISTRY.clear()
    registry.JURISDICTION_REGISTRY.update(jurisdictions)


def _install(monkeypatch, *eps):
    monkeypatch.setattr(discovery, "_list_entry_points", lambda: list(eps))


def _manifest(tmp_path: Path, plugins: list[dict]) -> Path:
    path = tmp_path / "expected-tax-plugins.json"
    path.write_text(json.dumps({"schema_version": 1, "plugins": plugins}), encoding="utf-8")
    return path


# --- SDK-Kompatibilitaet (ohne Manifest) ----------------------------------

def test_compatible_plugin_is_loaded_and_registered(monkeypatch):
    ep, _ = _plugin("vn", "2.0.0")
    _install(monkeypatch, ep)
    result = load_external_tax_plugins(None)
    assert result.loaded_plugins == ("vn",)
    assert "ZZ-VN" in registry.REGIME_REGISTRY


@pytest.mark.parametrize("declared", ["1.1.0", "1.0.0", "0.9.0", "3.0.0", "2.1.0", None, "2", 2])
def test_incompatible_or_undeclared_sdk_is_rejected_and_rolled_back(monkeypatch, declared):
    ep, _ = _plugin("old", declared)
    _install(monkeypatch, ep)
    result = load_external_tax_plugins("")
    assert result.loaded_plugins == ()
    assert [n for n, _ in result.failed_plugins] == ["old"]
    assert "IncompatibleTaxPluginError" in result.failed_plugins[0][1]
    assert "ZZ-OLD" not in registry.REGIME_REGISTRY


def test_rejected_plugin_cannot_override_builtin_pattern(monkeypatch):
    builtin = registry.REGIME_REGISTRY.get("*")
    ep, _ = _plugin("hijack", "1.1.0", pattern="*")
    _install(monkeypatch, ep)
    load_external_tax_plugins(None)
    assert registry.REGIME_REGISTRY.get("*") is builtin


def test_zero_plugins_without_manifest_is_allowed_but_logged(monkeypatch, caplog):
    _install(monkeypatch)
    with caplog.at_level(logging.WARNING, logger=plugin_inventory.__name__):
        result = load_external_tax_plugins(None)
    assert result.discovered_count == 0 and result.succeeded
    assert any("0 externe Plugins" in r.getMessage() for r in caplog.records)


# --- Erwartungs-Manifest ----------------------------------------------------

def test_manifest_matching_inventory_loads(monkeypatch, tmp_path):
    vn, _ = _plugin("vn", dist_version="2026.1.0")
    sg, _ = _plugin("sg")
    _install(monkeypatch, vn, sg)
    path = _manifest(tmp_path, [{"name": "vn", "version": "2026.1.0"}, {"name": "sg"}])
    result = load_external_tax_plugins(str(path))
    assert sorted(result.loaded_plugins) == ["sg", "vn"]


def test_manifest_with_zero_installed_plugins_is_a_failed_cutover(monkeypatch, tmp_path):
    _install(monkeypatch)
    path = _manifest(tmp_path, [{"name": "vn"}])
    with pytest.raises(TaxPluginInventoryError, match="fehlend: 'vn'"):
        load_external_tax_plugins(str(path))


def test_manifest_empty_list_allows_explicit_zero(monkeypatch, tmp_path):
    _install(monkeypatch)
    result = load_external_tax_plugins(str(_manifest(tmp_path, [])))
    assert result.discovered_count == 0


def test_manifest_missing_plugin_is_hard_error(monkeypatch, tmp_path):
    vn, _ = _plugin("vn")
    _install(monkeypatch, vn)
    path = _manifest(tmp_path, [{"name": "vn"}, {"name": "sg"}])
    with pytest.raises(TaxPluginInventoryError, match="fehlend: 'sg'"):
        load_external_tax_plugins(str(path))


def test_manifest_duplicate_installed_plugin_is_hard_error_before_any_load(monkeypatch, tmp_path):
    a, calls_a = _plugin("vn")
    b, calls_b = _plugin("vn")
    _install(monkeypatch, a, b)
    with pytest.raises(TaxPluginInventoryError, match="doppelt installiert: 'vn'"):
        load_external_tax_plugins(str(_manifest(tmp_path, [{"name": "vn"}])))
    assert calls_a["n"] == 0 and calls_b["n"] == 0


def test_manifest_duplicate_entry_is_hard_error(monkeypatch, tmp_path):
    vn, _ = _plugin("vn")
    _install(monkeypatch, vn)
    with pytest.raises(TaxPluginInventoryError, match="doppelt eingetragen"):
        load_external_tax_plugins(str(_manifest(tmp_path, [{"name": "vn"}, {"name": "vn"}])))


def test_manifest_incompatible_expected_plugin_is_hard_error(monkeypatch, tmp_path):
    vn, _ = _plugin("vn", "1.1.0")
    _install(monkeypatch, vn)
    with pytest.raises(TaxPluginInventoryError, match="SDK-inkompatibel"):
        load_external_tax_plugins(str(_manifest(tmp_path, [{"name": "vn"}])))
    assert "ZZ-VN" not in registry.REGIME_REGISTRY


def test_manifest_version_mismatch_is_hard_error(monkeypatch, tmp_path):
    vn, calls = _plugin("vn", dist_version="2025.9.0")
    _install(monkeypatch, vn)
    with pytest.raises(TaxPluginInventoryError, match="erwartet 2026.1.0"):
        load_external_tax_plugins(str(_manifest(tmp_path, [{"name": "vn", "version": "2026.1.0"}])))
    assert calls["n"] == 0


def test_manifest_unexpected_plugin_is_hard_error_before_any_load(monkeypatch, tmp_path):
    vn, _ = _plugin("vn")
    rogue, calls = _plugin("rogue")
    _install(monkeypatch, vn, rogue)
    with pytest.raises(TaxPluginInventoryError, match="unerwartet .*'rogue'"):
        load_external_tax_plugins(str(_manifest(tmp_path, [{"name": "vn"}])))
    assert calls["n"] == 0


def test_manifest_broken_plugin_load_is_hard_error(monkeypatch, tmp_path):
    def boom():
        raise ImportError("kaputt")

    _install(monkeypatch, SimpleNamespace(name="vn", load=boom, dist=None))
    with pytest.raises(TaxPluginInventoryError, match="ImportError"):
        load_external_tax_plugins(str(_manifest(tmp_path, [{"name": "vn"}])))


@pytest.mark.parametrize(
    "content",
    ["not json", json.dumps({"plugins": []}), json.dumps({"schema_version": 1, "plugins": {}}),
     json.dumps({"schema_version": 1, "plugins": [{"version": "1"}]})],
)
def test_invalid_manifest_is_hard_error(monkeypatch, tmp_path, content):
    _install(monkeypatch)
    path = tmp_path / "m.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(TaxPluginInventoryError):
        load_external_tax_plugins(str(path))


def test_unreadable_manifest_path_is_hard_error(monkeypatch, tmp_path):
    _install(monkeypatch)
    with pytest.raises(TaxPluginInventoryError, match="nicht lesbar"):
        load_external_tax_plugins(str(tmp_path / "missing.json"))


def test_manifest_entry_points_api_failure_is_hard_error(monkeypatch, tmp_path):
    def explode():
        raise OSError("metadata kaputt")

    monkeypatch.setattr(discovery, "_list_entry_points", explode)
    with pytest.raises(TaxPluginInventoryError, match="metadata kaputt"):
        load_external_tax_plugins(str(_manifest(tmp_path, [])))


def test_setting_is_declared_in_config_with_empty_default():
    from config import Settings

    assert Settings.model_fields["tax_plugin_expected_manifest"].default == ""
