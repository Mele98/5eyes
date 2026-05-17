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
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.tax.base import TaxRegime


REGIME_REGISTRY: dict[str, type["TaxRegime"]] = {}
"""Globale Registry. Key = id_pattern, Value = Regime-Klasse.
Wird zur Laufzeit gefuellt durch @register_regime."""


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
