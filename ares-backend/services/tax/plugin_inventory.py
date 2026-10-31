"""Tax-Plugin-Bestand: SDK-Kompatibilitaet und erwartetes Inventar (W2-804-01).

# Warum
Die Entry-Point-Gruppe wurde mit SDK 2.0.0 ohne Alias gewechselt. Null
gefundene Plugins konnte bisher sowohl den erlaubten Nullfall als auch
einen komplett misslungenen Cutover bedeuten. Dieses Modul macht beides
unterscheidbar:

1. **SDK-Kompatibilitaet (immer aktiv, fail-closed):** Jedes geladene
   Plugin-Objekt (Modul oder Klasse des Entry-Points) muss
   ``TAX_SDK_TARGET_VERSION`` deklarieren. Fehlt die Deklaration, ist
   sie kein Semver, hat sie einen anderen Major als der Host oder ist sie
   neuer als der Host, wird das Plugin abgelehnt und seine Registrierungen
   werden zurueckgerollt.
2. **Erwartungs-Manifest (optional):** Ist ``tax_plugin_expected_manifest``
   gesetzt (Pfad ausserhalb des Repos, ueber ``config.Settings``), gilt:
   fehlende, doppelte, unerwartete, versionsabweichende oder
   SDK-inkompatible Plugins sind ein harter Fehler
   (``TaxPluginInventoryError``), der den Boot stoppt.
   Ohne Manifest ist der Nullfall erlaubt, wird aber geloggt.

# Manifest-Format (JSON)
    {
      "schema_version": 1,
      "plugins": [
        {"name": "vn", "version": "2026.1.0"},
        {"name": "sg"}
      ]
    }

``name`` = Entry-Point-Name (Pflicht, eindeutig); ``version`` = exakte
Version der installierten Distribution (optional).

Signaturpruefung ist hier bewusst NICHT umgesetzt: das Repo hat keine
Paket-Signatur-Infrastruktur (offener Owner-Punkt).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from services.tax import discovery, registry
from services.tax.sdk import TAX_SDK_VERSION

logger = logging.getLogger(__name__)

PLUGIN_SDK_DECLARATION_ATTR = "TAX_SDK_TARGET_VERSION"
"""Attribut, mit dem ein Plugin die SDK-Version deklariert, gegen die es
gebaut wurde. Bewusst NICHT ``TAX_SDK_VERSION``: ein Re-Export der
Host-Konstante wuerde jede Pruefung trivial bestehen."""

MANIFEST_SCHEMA_VERSION = 1


class TaxPluginInventoryError(RuntimeError):
    """Harter Fehler: der installierte Tax-Plugin-Bestand weicht vom
    erwarteten Manifest ab oder das Manifest ist ungueltig."""


class IncompatibleTaxPluginError(RuntimeError):
    """Ein Plugin deklariert keine oder eine inkompatible SDK-Version."""


@dataclass(frozen=True)
class ExpectedPlugin:
    name: str
    version: str | None = None


def _parse_semver(raw: Any) -> tuple[int, int, int] | None:
    if not isinstance(raw, str):
        return None
    parts = raw.strip().split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        return None
    return int(parts[0]), int(parts[1]), int(parts[2])


def check_sdk_compatibility(name: str, loaded: Any) -> None:
    """Wirft ``IncompatibleTaxPluginError`` wenn ``loaded`` keine zum Host
    kompatible SDK-Version deklariert (gleicher Major, nicht neuer)."""
    host = _parse_semver(TAX_SDK_VERSION)
    assert host is not None  # Drift-Test pinnt Semver
    declared_raw = getattr(loaded, PLUGIN_SDK_DECLARATION_ATTR, None)
    declared = _parse_semver(declared_raw)
    if declared is None:
        raise IncompatibleTaxPluginError(
            f"Tax-Plugin '{name}' deklariert kein gueltiges "
            f"{PLUGIN_SDK_DECLARATION_ATTR} (gefunden: {declared_raw!r}); "
            f"Host-SDK ist {TAX_SDK_VERSION}"
        )
    if declared[0] != host[0] or declared > host:
        raise IncompatibleTaxPluginError(
            f"Tax-Plugin '{name}' ist fuer SDK {declared_raw} gebaut; "
            f"Host-SDK {TAX_SDK_VERSION} akzeptiert nur {host[0]}.x <= Host"
        )


def _guarded_load(ep: Any) -> Any:
    """Laedt ein Plugin; bei Fehler oder Inkompatibilitaet werden alle
    Registrierungen, die der Import vorgenommen hat, zurueckgerollt."""
    name = getattr(ep, "name", "<unknown>")
    regimes = dict(registry.REGIME_REGISTRY)
    jurisdictions = dict(registry.JURISDICTION_REGISTRY)
    try:
        loaded = ep.load()
        check_sdk_compatibility(name, loaded)
    except BaseException:
        registry.REGIME_REGISTRY.clear()
        registry.REGIME_REGISTRY.update(regimes)
        registry.JURISDICTION_REGISTRY.clear()
        registry.JURISDICTION_REGISTRY.update(jurisdictions)
        raise
    return loaded


def load_expected_manifest(path: str | Path) -> tuple[ExpectedPlugin, ...]:
    """Liest und validiert das Erwartungs-Manifest. Jeder Formfehler ist
    ein ``TaxPluginInventoryError`` (fail-closed)."""
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise TaxPluginInventoryError(
            f"Tax-Plugin-Manifest '{p}' nicht lesbar: {type(exc).__name__}: {exc}"
        ) from exc
    if not isinstance(data, dict) or data.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise TaxPluginInventoryError(
            f"Tax-Plugin-Manifest '{p}': schema_version {MANIFEST_SCHEMA_VERSION} erwartet"
        )
    entries = data.get("plugins")
    if not isinstance(entries, list):
        raise TaxPluginInventoryError(f"Tax-Plugin-Manifest '{p}': 'plugins' muss eine Liste sein")
    expected: list[ExpectedPlugin] = []
    seen: set[str] = set()
    for entry in entries:
        name = entry.get("name") if isinstance(entry, dict) else None
        version = entry.get("version") if isinstance(entry, dict) else None
        if not isinstance(name, str) or not name.strip():
            raise TaxPluginInventoryError(f"Tax-Plugin-Manifest '{p}': Eintrag ohne 'name': {entry!r}")
        if version is not None and not isinstance(version, str):
            raise TaxPluginInventoryError(f"Tax-Plugin-Manifest '{p}': 'version' von '{name}' ist kein String")
        if name in seen:
            raise TaxPluginInventoryError(f"Tax-Plugin-Manifest '{p}': '{name}' doppelt eingetragen")
        seen.add(name)
        expected.append(ExpectedPlugin(name=name, version=version))
    return tuple(expected)


def _dist_version(ep: Any) -> str | None:
    dist = getattr(ep, "dist", None)
    return getattr(dist, "version", None) if dist is not None else None


def _check_inventory(expected: tuple[ExpectedPlugin, ...], eps: list[Any]) -> None:
    """Vorpruefung VOR jeder Code-Ausfuehrung eines Plugins."""
    by_name: dict[str, list[Any]] = {}
    for ep in eps:
        by_name.setdefault(getattr(ep, "name", "<unknown>"), []).append(ep)
    expected_names = {e.name for e in expected}
    problems: list[str] = []
    for exp in expected:
        found = by_name.get(exp.name, [])
        if not found:
            problems.append(f"fehlend: '{exp.name}'")
            continue
        if len(found) > 1:
            problems.append(f"doppelt installiert: '{exp.name}' ({len(found)} Entry-Points)")
            continue
        if exp.version is not None and _dist_version(found[0]) != exp.version:
            problems.append(
                f"Version: '{exp.name}' erwartet {exp.version}, installiert {_dist_version(found[0])!r}"
            )
    for name in sorted(set(by_name) - expected_names):
        problems.append(f"unerwartet (nicht im Manifest): '{name}'")
    if problems:
        raise TaxPluginInventoryError(
            "Tax-Plugin-Bestand weicht vom Erwartungs-Manifest ab: " + "; ".join(problems)
        )


def load_external_tax_plugins(
    expected_manifest_path: str | Path | None = None,
) -> discovery.DiscoveryResult:
    """Boot-Einstieg: Discovery mit SDK-Pruefung und optionalem Manifest.

    Ohne Manifest: inkompatible/kaputte Plugins landen in
    ``failed_plugins`` (Boot laeuft weiter); der Nullfall wird geloggt.
    Mit Manifest: jede Abweichung wirft ``TaxPluginInventoryError``.
    """
    manifest = str(expected_manifest_path or "").strip()
    if not manifest:
        result = discovery.discover_external_regimes(loader=_guarded_load)
        if result.discovered_count == 0:
            logger.warning(
                "Tax-Plugin-Discovery: 0 externe Plugins in Gruppe '%s' gefunden; "
                "kein Erwartungs-Manifest gesetzt (tax_plugin_expected_manifest) - "
                "Nullfall erlaubt, ein misslungener Cutover waere so nicht erkennbar",
                discovery.EXTERNAL_REGIME_ENTRY_POINT_GROUP,
            )
        _log_result(result)
        return result

    expected = load_expected_manifest(manifest)
    try:
        eps = list(discovery._list_entry_points())
    except Exception as exc:  # noqa: BLE001 - mit Manifest fail-closed
        raise TaxPluginInventoryError(f"Tax-Plugin-Discovery fehlgeschlagen: {exc}") from exc
    _check_inventory(expected, eps)
    result = discovery.discover_external_regimes(entry_points=eps, loader=_guarded_load)
    if result.failed_plugins or result.skipped_plugins:
        details = "; ".join(f"{n}: {m}" for n, m in result.failed_plugins)
        raise TaxPluginInventoryError(
            "Erwartete Tax-Plugins nicht ladbar oder SDK-inkompatibel: "
            f"{details or ', '.join(result.skipped_plugins)}"
        )
    _log_result(result)
    logger.info(
        "Tax-Plugin-Bestand entspricht Manifest '%s' (%d Plugins, SDK %s)",
        manifest, len(expected), TAX_SDK_VERSION,
    )
    return result


def _log_result(result: discovery.DiscoveryResult) -> None:
    logger.info(
        "Tax-Plugin-Discovery | discovered=%d loaded=%d failed=%d skipped=%d",
        result.discovered_count,
        len(result.loaded_plugins),
        len(result.failed_plugins),
        len(result.skipped_plugins),
    )
