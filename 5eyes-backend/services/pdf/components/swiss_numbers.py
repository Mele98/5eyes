"""Sprint U-P26 — Helpers fuer Schweizer Zahlen-Formatierung.

Im 5eyes-PDF nutzen wir konsequent das Schweizer Tausenderzeichen
(Apostroph), nicht Komma oder Punkt. Plus: Rappen → CHF mit 0 Nachkomma
fuer Anzeige in Beratungs-PDFs.
"""
from __future__ import annotations


def format_chf_rappen(rappen: int | None, *, with_unit: bool = True) -> str:
    """`1234500` → `CHF 12'345`. None / 0 → '—' falls with_unit, sonst '0'."""
    if rappen is None:
        return "—" if with_unit else "0"
    try:
        value = int(rappen) / 100
    except (TypeError, ValueError):
        return "—" if with_unit else "0"
    formatted = f"{value:,.0f}".replace(",", "'")
    return f"CHF {formatted}" if with_unit else formatted


def format_bps_as_pct(bps: int | None, *, decimals: int = 1) -> str:
    """`4250` → `42.5 %`. None → '—'."""
    if bps is None:
        return "—"
    try:
        pct = int(bps) / 100
    except (TypeError, ValueError):
        return "—"
    return f"{pct:.{decimals}f} %"


def format_bps_signed_pct(bps: int | None, *, decimals: int = 1) -> str:
    """`+450` → `+4.5 %`. Mit Vorzeichen, fuer Drift-Anzeigen."""
    if bps is None:
        return "—"
    try:
        pct = int(bps) / 100
    except (TypeError, ValueError):
        return "—"
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.{decimals}f} %"


def format_integer(value: int | float | None) -> str:
    """`49` → `49`, `None` → '—'."""
    if value is None:
        return "—"
    try:
        return f"{int(value):d}"
    except (TypeError, ValueError):
        return "—"
