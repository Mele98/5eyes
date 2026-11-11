"""Sprint U-P26 — Helpers fuer Schweizer Zahlen-Formatierung.

Im Ares-PDF nutzen wir konsequent das Schweizer Tausenderzeichen
(Apostroph), nicht Komma oder Punkt. Plus: Rappen → CHF mit 0 Nachkomma
fuer Anzeige in Beratungs-PDFs.

G7 (2026-11-11): Alle Helfer delegieren an den gemeinsamen Rundungsformatter
``core.presentation_rounding`` (Policy ``ares-rounding/1``, Decimal
ROUND_HALF_UP, identisch zu Classic-App und React). Vorher rundeten sie mit
Float-``format`` (Banker's Rounding auf der Binaerexpansion: 2.5 -> "2",
12.25 -> "12.2", 12.35 -> "12.3").
"""
from __future__ import annotations

from typing import Mapping

from core.presentation_rounding import (  # noqa: F401  (Re-Export fuer bestehende Aufrufer)
    CURRENCY_EXPONENTS,
    NO_VALUE,
    allocation_pct_texts,
    format_amount_minor,
    format_bps_as_pct,
    format_bps_signed_pct,
    format_minor_number,
    format_money_minor,
    format_number,
    format_pct_value,
    sub_allocation_pct_texts,
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


def format_integer(value: int | float | None) -> str:
    """`49` → `49`, `None` → '—'."""
    if value is None:
        return "—"
    try:
        return f"{int(value):d}"
    except (TypeError, ValueError):
        return "—"
