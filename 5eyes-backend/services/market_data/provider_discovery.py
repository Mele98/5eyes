"""Provider-Discovery via Python Entry-Points (ADR-010).

Phase 5 von SMI-Sub-Asset-Sprint (2026-06-09).

Erlaubt es externen pip-Paketen, weitere MarketDataProvider zur Laufzeit
anzubieten — analog dem Tax-SDK-Pattern aus ADR-006.

Externe Pakete deklarieren in ihrer pyproject.toml:

    [project.entry-points."5eyes.market_data_provider"]
    bloomberg = "fivee_eyes_bloomberg:BloombergProvider"
    refinitiv = "fivee_eyes_refinitiv:RefinitivProvider"

Beim Boot scannt 5eyes diese Entry-Group, instanziiert jeden Provider und
fuegt ihn in die Aggregator-Cascade ein. Konformanz-Check (vor Aufnahme):
- Provider hat einen `name` (str, nicht leer, kollisionsfrei)
- Provider erbt von MarketDataProvider
- Provider liefert ein lookup_isin / get_history / get_eod via Method-
  Existenz-Pruefung

Provider die nicht-konform sind werden mit logger.warning skipped, NICHT
geraised — damit ein kaputtes Drittpaket nicht den Boot abbricht.
"""
from __future__ import annotations

import logging
from importlib.metadata import entry_points
from typing import Any

from .base import MarketDataProvider

logger = logging.getLogger(__name__)


# Entry-Point-Group fuer externe Provider. Konvention analog Tax-SDK.
ENTRY_POINT_GROUP = "5eyes.market_data_provider"


def _is_valid_provider_class(cls: Any) -> bool:
    """Prueft ob die Class das MarketDataProvider-Interface erfuellt."""
    if not isinstance(cls, type):
        return False
    if not issubclass(cls, MarketDataProvider):
        return False
    # Pflicht-Methoden vorhanden
    for method in ("get_eod", "get_history", "lookup_isin"):
        if not hasattr(cls, method):
            return False
    return True


def discover_external_providers() -> list[MarketDataProvider]:
    """Scannt Entry-Point-Group und liefert instanziiere externe Provider.

    Fehler beim Laden einzelner Pakete werden geloggt aber nicht
    weitergereicht — defensiv damit ein kaputtes Drittpaket den Boot
    nicht abbricht.

    Returns:
        Liste von MarketDataProvider-Instanzen, default-konstruiert.
        Kollidierende Provider-Names (mehrere mit `name='bloomberg'`)
        werden nach First-Wins behandelt + warning geloggt.
    """
    found: list[MarketDataProvider] = []
    seen_names: set[str] = set()

    try:
        eps = entry_points(group=ENTRY_POINT_GROUP)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Provider-Discovery: entry_points-Lookup fehlgeschlagen (%s). "
            "Keine externen Provider geladen.",
            exc,
        )
        return found

    for ep in eps:
        try:
            cls = ep.load()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Provider-Discovery: Konnte Entry-Point %r nicht laden (%s).",
                ep.name, exc,
            )
            continue
        if not _is_valid_provider_class(cls):
            logger.warning(
                "Provider-Discovery: Entry-Point %r liefert keine valide "
                "MarketDataProvider-Subclass (Class=%r). Skipped.",
                ep.name, cls,
            )
            continue
        try:
            instance = cls()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Provider-Discovery: Default-Construct von %r fehlgeschlagen (%s). "
                "Externer Provider braucht Zero-Arg-Constructor.",
                ep.name, exc,
            )
            continue
        provider_name = getattr(instance, "name", None)
        if not isinstance(provider_name, str) or not provider_name:
            logger.warning(
                "Provider-Discovery: %r hat keinen gueltigen .name-String. Skipped.",
                ep.name,
            )
            continue
        if provider_name in seen_names:
            logger.warning(
                "Provider-Discovery: Provider-Name %r bereits vergeben "
                "(Entry-Point %r). First-Wins, second skipped.",
                provider_name, ep.name,
            )
            continue
        seen_names.add(provider_name)
        found.append(instance)
        logger.info(
            "Provider-Discovery: externer Provider %r geladen (Entry-Point %r).",
            provider_name, ep.name,
        )

    return found


def discover_all_provider_names() -> list[str]:
    """Liefert nur die Provider-Names ohne Instanziierung.

    Nuetzlich fuer Admin-Endpoints / Health-Reports, um zu zeigen welche
    Provider via Entry-Points registriert sind ohne Side-Effects beim
    Construct (z.B. blpapi-Session-Start) auszuloesen.
    """
    names: list[str] = []
    try:
        eps = entry_points(group=ENTRY_POINT_GROUP)
    except Exception:  # noqa: BLE001
        return names
    for ep in eps:
        try:
            cls = ep.load()
        except Exception:  # noqa: BLE001
            continue
        if not _is_valid_provider_class(cls):
            continue
        # name ist Class-Attribut, kein Instanz-Construct noetig
        name = getattr(cls, "name", None)
        if isinstance(name, str) and name:
            names.append(name)
    return names
