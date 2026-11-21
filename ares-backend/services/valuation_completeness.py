"""CCX-07: fehlender Preis oder Kurs bleibt UNKNOWN und blockiert.

Reine Klassifikation ohne DB (12er-Vertrag ``classify_valuation_completeness``):
ein unbekannter Bewertungsinput wird nie zu 0 oder COMPLETE. Die produktive
Abdeckungsentscheidung je Snapshot trifft ``services.holdings_valuation``
nach derselben Regel (``coverage_from_qualities``).
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

COMPLETE = "COMPLETE"
PARTIAL = "PARTIAL"
UNKNOWN = "UNKNOWN"


def _known(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return False
    text = str(value).strip()
    return bool(text) and text.lower() not in {"nan", "inf", "-inf", "none", "null"}


def classify_valuation_completeness(
    prices: Mapping[str, Any], fx: Mapping[str, Any],
) -> dict[str, Any]:
    """``COMPLETE`` nur, wenn jeder Preis und jeder benoetigte Kurs belegt ist."""
    values = [*prices.values(), *fx.values()]
    if values and all(_known(value) for value in values):
        return {"status": COMPLETE, "release_eligible": True}
    return {"status": UNKNOWN, "release_eligible": False}


def coverage_from_qualities(qualities: Iterable[str], *, value_unknown: Iterable[bool]) -> str:
    """Abdeckung aus der Datenqualitaet der Zeilen: jede unbekannte Bewertung
    -> UNKNOWN; bekannte Werte mit Befund (z. B. Doppelerfassung) -> PARTIAL;
    nur saubere Zeilen -> COMPLETE."""
    qualities = list(qualities)
    if any(value_unknown):
        return UNKNOWN
    if any(quality != "OK" for quality in qualities):
        return PARTIAL
    return COMPLETE
