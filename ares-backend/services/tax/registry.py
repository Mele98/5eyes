"""Tax-Regime-Registry — Plugin-Lookup nach Jurisdiction-ID.

Spec: docs/planning/2026-05-17-sprint-3-tax-plugin-system.md §4

Konzept:
- Jedes Regime registriert sich beim Import per @register_regime Decorator.
- ID-Patterns koennen exakt ('DE') oder Glob ('CH-*', 'US-*') sein.
- resolve_regime_class(jid) macht Pattern-Matching mit Specifity:
  exakte Treffer schlagen Glob-Treffer.
- Fallback: GenericFlatRateRegime (fuer noch-nicht-implementierte Laender).
"""
from __future__ import annotations

import fnmatch
import importlib
import pkgutil
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.tax.base import TaxJurisdiction, TaxRegime


REGIME_REGISTRY: dict[str, type["TaxRegime"]] = {}
"""Globale Registry. Key = id_pattern, Value = Regime-Klasse.
Wird zur Laufzeit gefuellt durch @register_regime."""

JURISDICTION_REGISTRY: dict[str, "TaxJurisdiction"] = {}
"""Country-level tax estimate plugins keyed by ISO country code."""


class TaxJurisdictionNotFound(KeyError):
    """Raised when no country-level tax plugin is registered."""


def register_regime(id_pattern: str):
    """Decorator: registriert eine TaxRegime-Klasse fuer einen ID-Pattern.

    Pattern kann sein:
    - Exakt: 'DE', 'JP', 'SG'
    - Glob: 'CH-*' (alle CH-Kantone), 'US-*' (alle US-States)
    - Catchall: '*' (nur fuer GenericFlatRateRegime!)

    Doppelregistrierung mit gleichem Pattern ueberschreibt — Last-Wins.
    Im Production-Setup darf das nicht passieren; Test kann es bewusst tun.
    """
    def wrapper(cls):
        REGIME_REGISTRY[id_pattern] = cls
        return cls
    return wrapper


def resolve_regime_class(jurisdiction_id: str) -> type["TaxRegime"]:
    """Lookup einer Regime-Klasse fuer eine Jurisdiction-ID.

    Resolution-Order:
    1. Exakte Treffer (jurisdiction_id == pattern)
    2. Glob-Treffer (fnmatch), spezifischere Patterns zuerst
       (Pattern-Laenge als Heuristik — 'US-NY' > 'US-*' > '*')
    3. Fallback: GenericFlatRateRegime (immer als '*' registriert)

    Wirft KeyError nur wenn KEIN '*'-Catchall registriert ist (sollte
    nicht passieren wenn GenericFlatRateRegime importiert wurde).
    """
    if jurisdiction_id in REGIME_REGISTRY:
        return REGIME_REGISTRY[jurisdiction_id]

    candidates = [
        (pattern, cls)
        for pattern, cls in REGIME_REGISTRY.items()
        if fnmatch.fnmatchcase(jurisdiction_id, pattern)
    ]
    if not candidates:
        raise KeyError(
            f"No TaxRegime registered for '{jurisdiction_id}'. "
            "Ensure GenericFlatRateRegime is registered as fallback ('*')."
        )

    candidates.sort(key=lambda kv: (-len(kv[0]), kv[0]))
    return candidates[0][1]


def list_registered_patterns() -> list[str]:
    """Debug-Helper: alle registrierten Patterns."""
    return sorted(REGIME_REGISTRY.keys())


def clear_registry() -> None:
    """TEST-ONLY: leert die Registry. Nutze niemals in Production-Code."""
    REGIME_REGISTRY.clear()


def _normalize_country_code(country_code: str) -> str:
    return country_code.upper().strip()


def register_jurisdiction(plugin):
    """Register a country-level TaxJurisdiction plugin.

    Accepts either an instance or a zero-argument class. Last registration for
    the same country wins, which keeps tests and hot-reload deterministic.
    """
    instance = plugin() if isinstance(plugin, type) else plugin
    country_code = _normalize_country_code(instance.metadata.country_code)
    JURISDICTION_REGISTRY[country_code] = instance
    return plugin


def get_jurisdiction(country_code: str) -> "TaxJurisdiction":
    """Return the registered country-level plugin for an ISO country code."""
    normalized = _normalize_country_code(country_code)
    try:
        return JURISDICTION_REGISTRY[normalized]
    except KeyError as exc:
        raise TaxJurisdictionNotFound(
            f"No TaxJurisdiction registered for country '{normalized}'."
        ) from exc


def list_jurisdictions() -> list["TaxJurisdiction"]:
    """Return registered country-level plugins sorted by country code."""
    return [JURISDICTION_REGISTRY[key] for key in sorted(JURISDICTION_REGISTRY)]


def clear_jurisdiction_registry() -> None:
    """TEST-ONLY: clear country-level plugins."""
    JURISDICTION_REGISTRY.clear()


def discover_builtin_jurisdictions(
    package_name: str = "services.tax.jurisdictions",
) -> list[str]:
    """Import built-in jurisdiction modules so they can register themselves."""
    package = importlib.import_module(package_name)
    imported: list[str] = []
    package_path = getattr(package, "__path__", None)
    if package_path is None:
        return imported
    for module_info in pkgutil.iter_modules(package_path):
        if module_info.name.startswith("_"):
            continue
        module_name = f"{package_name}.{module_info.name}"
        importlib.import_module(module_name)
        imported.append(module_name)
    return imported
