"""Entry-Points-basierte Discovery externer Tax-Regimes.

# Konzept
Externe Pakete (pip-installiert) registrieren ein Entry-Point unter
der Group `5eyes.tax_regime`. Beim 5eyes-Boot wird `discover_external_
regimes()` aufgerufen — laedt jedes Plugin-Modul und triggert dessen
`@register_regime`-Decorators.

# Beispiel: Drittanbieter `5eyes-tax-vietnam`
    # In pyproject.toml des externen Pakets:
    # [project.entry-points."5eyes.tax_regime"]
    # vn = "tax_vietnam.regime"

    # In tax_vietnam/regime.py:
    from services.tax.sdk import register_regime
    @register_regime("VN")
    class VNTaxRegime: ...

# Sicherheits-Hinweis
Discovery laedt Code aus installierten Paketen — vertraue nur Paketen
aus deiner kontrollierten Quelle (privater Index, signierte Pakete).
Fuer Self-Hosted-Deployments mit unkontrollierter PyPI-Quelle koennen
externe Plugins via Config-Flag deaktiviert werden.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Iterable

logger = logging.getLogger(__name__)

EXTERNAL_REGIME_ENTRY_POINT_GROUP = "5eyes.tax_regime"
"""Entry-Point Group fuer externe Regime-Pakete. Drittanbieter
registrieren sich unter dieser Group in ihrer pyproject.toml/setup.cfg."""


@dataclass(frozen=True)
class DiscoveryResult:
    """Ergebnis eines discover_external_regimes()-Laufs.

    Audit-freundlich: alles was beim Plugin-Load passiert ist, ist in
    der Result-Struktur sichtbar. Errors werden NICHT propagiert —
    der Boot soll ueberleben auch wenn ein Plugin kaputt ist.
    """

    loaded_plugins: tuple[str, ...] = ()
    """Plugin-Namen die erfolgreich geladen wurden (Entry-Point.name)."""

    failed_plugins: tuple[tuple[str, str], ...] = ()
    """(Plugin-Name, Error-Message)-Tuples fuer fehlgeschlagene Loads.
    Fuer Audit + Operations-Visibility."""

    discovered_count: int = 0
    """Total Entry-Points unter der Group gefunden (geladen + failed)."""

    skipped_plugins: tuple[str, ...] = field(default_factory=tuple)
    """Plugins die per Config explizit skipped wurden."""

    @property
    def succeeded(self) -> bool:
        """True wenn alle gefundenen Plugins (sofern nicht skipped)
        erfolgreich geladen wurden. False bei mindestens einem Failure."""
        return not self.failed_plugins


def discover_external_regimes(
    *,
    skip_plugins: Iterable[str] = (),
    raise_on_error: bool = False,
) -> DiscoveryResult:
    """Sucht und laedt alle externen Tax-Regime-Plugins.

    Args:
        skip_plugins: Plugin-Namen die nicht geladen werden sollen
            (z.B. fuer Sandbox/Testing/Compliance-Disable).
        raise_on_error: Wenn True wirft die erste Load-Exception.
            Default False: failed plugins werden geloggt + im Result
            zurueckgegeben, der Boot bricht NICHT ab.

    Returns:
        DiscoveryResult mit allen geladenen/gefailten Plugin-Namen.

    Implementierungs-Detail:
    Nutzt `importlib.metadata.entry_points()` (Standard-Lib seit Py3.8).
    Bei import-Errors greift der erweiterte Try/Except — wir wollen den
    Boot nicht abbrechen weil EIN Plugin kaputt ist.
    """
    skip_set = set(skip_plugins)
    loaded: list[str] = []
    failed: list[tuple[str, str]] = []
    skipped: list[str] = []

    try:
        eps = _list_entry_points()
    except Exception as exc:  # noqa: BLE001 — wir wollen jeden Fehler abfangen
        logger.error("Tax-Plugin-Discovery: entry_points() failed: %s", exc)
        if raise_on_error:
            raise
        return DiscoveryResult(discovered_count=0)

    discovered = len(eps)
    for ep in eps:
        name = getattr(ep, "name", "<unknown>")
        if name in skip_set:
            skipped.append(name)
            logger.info("Tax-Plugin '%s' skipped per Config", name)
            continue
        try:
            ep.load()  # triggert das @register_regime-Decorator des Plugins
            loaded.append(name)
            logger.info("Tax-Plugin '%s' geladen", name)
        except Exception as exc:  # noqa: BLE001 — Plugin-Fehler nicht propagieren
            msg = f"{type(exc).__name__}: {exc}"
            failed.append((name, msg))
            logger.error("Tax-Plugin '%s' Load-Fehler: %s", name, msg)
            if raise_on_error:
                raise

    return DiscoveryResult(
        loaded_plugins=tuple(loaded),
        failed_plugins=tuple(failed),
        discovered_count=discovered,
        skipped_plugins=tuple(skipped),
    )


def _list_entry_points() -> list:
    """Abstrahiert die importlib.metadata-API ueber Python-Versionen.

    Py3.10+: entry_points(group=...) returnt direkt eine Liste.
    Py3.8/3.9: entry_points() returnt ein Mapping, das per Key indexiert wird.
    """
    from importlib import metadata

    try:
        # Py3.10+ Selectable-API
        eps = metadata.entry_points(group=EXTERNAL_REGIME_ENTRY_POINT_GROUP)
        return list(eps)
    except TypeError:
        # Py3.8/3.9 Legacy-API
        all_eps = metadata.entry_points()
        if hasattr(all_eps, "get"):
            return list(all_eps.get(EXTERNAL_REGIME_ENTRY_POINT_GROUP, []))
        return []
