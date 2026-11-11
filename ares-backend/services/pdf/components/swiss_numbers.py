"""Sprint U-P26 — Helpers fuer Schweizer Zahlen-Formatierung.

Im Ares-PDF nutzen wir konsequent das Schweizer Tausenderzeichen
(Apostroph), nicht Komma oder Punkt. Plus: Rappen → CHF mit 0 Nachkomma
fuer Anzeige in Beratungs-PDFs.

G7 (2026-11-11): Alle Helfer delegieren an den gemeinsamen Rundungsformatter
``services.presentation_rounding`` (Policy ``ares-rounding/1``, Decimal
ROUND_HALF_UP, identisch zu Classic-App und React). Vorher rundeten sie mit
Float-``format`` (Banker's Rounding auf der Binaerexpansion: 2.5 -> "2",
12.25 -> "12.2", 12.35 -> "12.3").
"""
from __future__ import annotations

from typing import Mapping

from services.presentation_rounding import (
    CURRENCY_EXPONENTS,
    NO_VALUE,
    apportion_bucket_bps,
    apportion_sub_bps,
    format_decimal,
    format_money_minor,
    format_percent,
    format_percent_bps,
    to_decimal,
)


def _exponent(currency: str) -> int:
    return CURRENCY_EXPONENTS.get(str(currency or "").upper().strip(), 2)


def format_chf_rappen(rappen: int | None, *, with_unit: bool = True, currency: str = "CHF") -> str:
    """`1234500` → `CHF 12'345`. None → '—' falls with_unit, sonst '0'.

    `currency` (2026-08-07, CEO/CFO/CIO-Audit): Beträge sind intern immer
    Rappen/Cents der Mandats-Waehrung (nicht zwingend CHF) -- der Aufrufer
    muss `mandate.base_currency` durchreichen, sonst zeigt ein EUR-/USD-
    Mandat im FIDLEG-Pflichtdokument faelschlich "CHF" an.
    """
    if to_decimal(rappen) is None:
        return NO_VALUE if with_unit else "0"
    unit = str(currency or "CHF").upper().strip() or "CHF"
    text = format_money_minor(rappen, unit, _exponent(unit), 0)
    return text if with_unit else text[len(unit) + 1:]


def format_amount_minor(minor: int | None, currency: str = "CHF", *, decimals: int = 0) -> str:
    """Minor-Units der Waehrung -> ``CHF 12'345`` (ganze Einheiten, Half-up)."""
    unit = str(currency or "CHF").upper().strip() or "CHF"
    return format_money_minor(minor, unit, _exponent(unit), decimals)


def format_bps_as_pct(bps: int | None, *, decimals: int = 1) -> str:
    """`4250` → `42.5 %`. None → '—'."""
    return format_percent_bps(bps, decimals)


def format_bps_signed_pct(bps: int | None, *, decimals: int = 1) -> str:
    """`+450` → `+4.5 %`. Mit Vorzeichen, fuer Drift-Anzeigen (0 ohne Vorzeichen)."""
    return format_percent_bps(bps, decimals, signed=True)


def format_pct_value(value_pct, *, decimals: int = 1) -> str:
    """Wert bereits in Prozentpunkten -> ``12.3 %``."""
    return format_percent(value_pct, decimals)


def format_number(value, *, decimals: int = 0) -> str:
    return format_decimal(value, decimals)


def allocation_pct_texts(allocation_bps: Mapping[str, int], *, decimals: int = 1) -> dict[str, str]:
    """Anlageklassen-Gewichte -> apportionierte Anzeige (Summe exakt 100.0 %).

    Gleiche Regel wie die App (aa-chart.js): Largest Remainder, Gleichstand in
    kanonischer Klassenreihenfolge. Klassen mit 0 bps -> ``0.0 %``.
    """
    shown = apportion_bucket_bps(dict(allocation_bps or {}), decimals)
    return {
        key: format_percent(shown[key], decimals) if key in shown else format_percent_bps(0, decimals)
        for key in (allocation_bps or {})
    }


def sub_allocation_pct_texts(class_display_pct: str, subs: Mapping[str, int], class_bps: int,
                             *, decimals: int = 1) -> dict[str, str]:
    """Unterklassen -> Anzeige, summiert auf den angezeigten Klassenwert."""
    class_value = to_decimal(class_display_pct.replace("%", "").strip())
    shown = apportion_sub_bps(class_value, dict(subs or {}), class_bps, decimals)
    return {key: format_percent(value, decimals) for key, value in shown.items()}


def format_integer(value: int | float | None) -> str:
    """`49` → `49`, `None` → '—'."""
    if value is None:
        return "—"
    try:
        return f"{int(value):d}"
    except (TypeError, ValueError):
        return "—"


def format_minor_number(minor: int | None, *, exponent: int = 2, decimals: int = 0) -> str:
    """Minor-Units -> Zahl ohne Waehrung (``1234550 -> 12'346``), Half-up."""
    dec = to_decimal(minor)
    if dec is None:
        return NO_VALUE
    return format_decimal(dec.scaleb(-int(exponent)), decimals)
