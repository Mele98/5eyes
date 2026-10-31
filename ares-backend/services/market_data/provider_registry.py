"""Kontrollierte Provider-Aufloesung fuer die Marktdaten-Factory (W2-804-02).

Vereinigt die eingebauten Provider mit den per Entry-Point entdeckten
externen Providern (``provider_discovery``) zu EINER deterministischen,
kollisionsgeprueften Map und loest daraus die konfigurierte Reihenfolge auf.

Invarianten (Datenherkunft):

- Externe Provider werden pro Aufloesung genau einmal geladen.
- Namenskollisionen (extern vs. eingebaut oder extern vs. extern,
  Gross-/Kleinschreibung ignoriert) sind ein harter Fehler — es gibt kein
  "First-Wins", weil sonst unklar ist, welche Quelle Kurse liefert.
- Ein explizit konfigurierter Provider, der weder eingebaut ist noch von
  einem externen Paket gueltig geladen wurde (fehlt, Ladefehler, ungueltige
  Klasse, kaputter Konstruktor), ist ein harter Fehler. Es gibt KEINEN
  stillen Rueckfall auf andere Quellen.
- Nur wenn gar keine Konfiguration vorliegt, gelten die Default-Provider
  (``DEFAULT_PROVIDER_NAMES``); in diesem Fall wird keine Discovery
  ausgefuehrt, das Verhalten fuer Default-Installationen bleibt unveraendert.
"""
from __future__ import annotations

from typing import Callable

from . import provider_discovery
from .base import MarketDataProvider
from .providers import (
    AlphaVantageProvider,
    StooqProvider,
    TwelveDataProvider,
    YFinanceProvider,
)

DEFAULT_PROVIDER_NAMES: tuple[str, ...] = ("yfinance", "stooq")

# Eingebaute Provider: Name -> Konstruktor(settings). Nur konfigurierte
# Provider werden instanziiert.
BUILTIN_PROVIDERS: dict[str, Callable[[object], MarketDataProvider]] = {
    "yfinance": lambda settings: YFinanceProvider(),
    "stooq": lambda settings: StooqProvider(),
    "alphavantage": lambda settings: AlphaVantageProvider(
        api_key=getattr(settings, "alphavantage_api_key", None),
    ),
    "twelvedata": lambda settings: TwelveDataProvider(
        api_key=getattr(settings, "twelvedata_api_key", None),
    ),
}


class ProviderConfigurationError(RuntimeError):
    """Marktdaten-Provider-Konfiguration ist nicht eindeutig erfuellbar."""


def parse_provider_names(raw: object) -> list[str]:
    """Zerlegt ``MARKET_DATA_PROVIDERS`` in normalisierte Namen."""
    text = str(raw or "")
    return [p.lower() for p in (s.strip() for s in text.split(",")) if p]


def _external_provider_map() -> dict[str, MarketDataProvider]:
    """Laedt externe Provider einmal und prueft sie gegen Built-ins."""
    external: dict[str, MarketDataProvider] = {}
    for provider in provider_discovery.discover_external_providers():
        if not isinstance(provider, MarketDataProvider):
            raise ProviderConfigurationError(
                f"Externer Marktdaten-Provider {provider!r} ist keine "
                "MarketDataProvider-Instanz."
            )
        raw_name = getattr(provider, "name", None)
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise ProviderConfigurationError(
                f"Externer Marktdaten-Provider {provider!r} hat keinen gueltigen Namen."
            )
        key = raw_name.strip().lower()
        if key in BUILTIN_PROVIDERS:
            raise ProviderConfigurationError(
                f"Namenskollision: externer Marktdaten-Provider {raw_name!r} "
                "ueberschneidet sich mit einem eingebauten Provider."
            )
        if key in external:
            raise ProviderConfigurationError(
                f"Namenskollision: mehrere externe Marktdaten-Provider heissen {raw_name!r}."
            )
        external[key] = provider
    return dict(sorted(external.items()))


def resolve_providers(settings: object) -> list[MarketDataProvider]:
    """Liefert die Provider in konfigurierter Reihenfolge (fail-closed)."""
    names = parse_provider_names(getattr(settings, "market_data_providers", ""))
    if not names:
        return [BUILTIN_PROVIDERS[n](settings) for n in DEFAULT_PROVIDER_NAMES]

    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        raise ProviderConfigurationError(
            f"MARKET_DATA_PROVIDERS nennt Provider mehrfach: {', '.join(duplicates)}."
        )

    external = _external_provider_map()
    missing = [n for n in names if n not in BUILTIN_PROVIDERS and n not in external]
    if missing:
        known = sorted(BUILTIN_PROVIDERS) + list(external)
        raise ProviderConfigurationError(
            "Explizit konfigurierte Marktdaten-Provider sind nicht verfuegbar "
            f"(fehlen, nicht ladbar oder ungueltige Klasse): {', '.join(missing)}. "
            f"Verfuegbar: {', '.join(known)}. Ladefehler externer Pakete "
            f"(Entry-Point-Gruppe {provider_discovery.ENTRY_POINT_GROUP!r}) "
            "stehen im Log. Kein Rueckfall auf andere Quellen."
        )
    return [
        external[n] if n in external else BUILTIN_PROVIDERS[n](settings)
        for n in names
    ]
