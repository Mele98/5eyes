"""CHF-AMOUNT-THOUSANDS-001 (Assetallocation-Audit 2026-10-14).

Free-text CHF amounts (Mindestreserve, Liquiditaetsreserve-Ziel) were parsed by
replacing "," with "." and calling ``float()``. A thousands grouping therefore
became a decimal point: "50.000" and "50,000" were read as CHF 50 instead of
CHF 50'000 -- a silent factor of 1000 on the client's reserve.

CHF amounts never carry three decimals, so a separator followed by groups of
exactly three digits is unambiguously a thousands separator. Anything that is
neither a plain number nor a clean grouping is rejected (returns None), never
guessed.
"""
from __future__ import annotations

import re

_GROUPED = re.compile(r"^\d{1,3}(?P<sep>[.,])\d{3}(?:(?P=sep)\d{3})*(?:(?P<dec>[.,])\d{1,2})?$")
_PLAIN = re.compile(r"^\d+(?:[.,]\d{1,2})?$")


def normalize_chf_amount_text(value) -> str | None:
    """Return a ``float()``-parsable string for a CHF amount, or None.

    Accepts "50000", "50'000", "50 000", "CHF 50'000.50", "50.000",
    "50,000", "1.250.000", "50.000,50", "1,250,000.50". Rejects
    "50.0000", "5.00.000", "50.000.5" and other ambiguous shapes.
    """
    if value is None:
        return None
    raw = str(value).replace("CHF", "").replace("'", "").replace("’", "")
    raw = raw.replace(" ", "").replace(" ", "").strip()
    if not raw:
        return None
    grouped = _GROUPED.match(raw)
    if grouped:
        sep, dec = grouped.group("sep"), grouped.group("dec")
        if dec is not None and dec == sep:
            return None  # "50.000.50": separator used for both roles
        integer_part, _, decimals = (raw.rpartition(dec) if dec else (raw, "", ""))
        digits = integer_part.replace(sep, "")
        return f"{digits}.{decimals}" if dec else digits
    if _PLAIN.match(raw):
        return raw.replace(",", ".")
    return None
