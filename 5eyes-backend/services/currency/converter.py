"""Konvertierung von Rappen-Betraegen zwischen Waehrungen.

5eyes nutzt intern Rappen (CHF-Basis-Einheit, 1 CHF = 100 Rappen). Bei
Konvertierung gibt es zwei Optionen:
- 'rappen' bleibt das Wort fuer 'subunit' (1 EUR = 100 cents = 'rappen')
  in dieser Module-Konvention. Sprich: convert_rappen(100, 'EUR', 'CHF')
  konvertiert 1 EUR zu CHF (in Rappen).

Spec: docs/planning/2026-05-17-sprint-9-multi-currency.md
"""
from __future__ import annotations

from services.currency.fx_rates import DEFAULT_FX_RATES, FXRateSource


# Eine Default-Instanz fuer Convenience.
_DEFAULT_SOURCE = FXRateSource()


# Alle unterstuetzten Currency-Codes (fuer UI-Dropdowns etc.)
SUPPORTED_CURRENCIES: tuple[str, ...] = tuple(sorted(DEFAULT_FX_RATES.keys()))


def convert_rappen(
    amount_rappen: float,
    from_currency: str,
    to_currency: str,
    source: FXRateSource | None = None,
) -> float:
    """Konvertiert Rappen-Betrag von einer Waehrung in eine andere.

    Args:
        amount_rappen: Subunit-Betrag in from_currency (1 CHF = 100 Rappen)
        from_currency: ISO-Code (z.B. 'CHF', 'EUR', 'USD')
        to_currency: ISO-Code
        source: optionale FXRateSource (default: DEFAULT_FX_RATES)

    Returns:
        Subunit-Betrag in to_currency (gleicher Faktor 100)

    Beispiele:
        convert_rappen(10000, 'CHF', 'CHF') = 10000  (Identity)
        convert_rappen(100, 'EUR', 'CHF') ≈ 95       (1 EUR = 0.95 CHF)
        convert_rappen(95, 'CHF', 'EUR') ≈ 100       (Inverse)
    """
    if amount_rappen == 0:
        return 0.0
    src = source if source is not None else _DEFAULT_SOURCE
    from_ccy = from_currency.upper().strip()
    to_ccy = to_currency.upper().strip()
    if from_ccy == to_ccy:
        return float(amount_rappen)
    rate = src.cross_rate(from_ccy, to_ccy)
    return float(amount_rappen) * rate


def format_currency(
    amount_rappen: float,
    currency: str,
    *,
    decimals: int = 2,
    thousand_sep: str = "'",
) -> str:
    """Formatiert Subunit-Betrag als '<CCY> <X'XXX.XX>'.

    Args:
        amount_rappen: Subunit (Rappen / Cents)
        currency: ISO-Code (display in upper case)
        decimals: Nachkommastellen (default 2)
        thousand_sep: Tausender-Trenner (default Schweizer ')

    Beispiele:
        format_currency(12345678, 'CHF') → "CHF 123'456.78"
        format_currency(0, 'EUR')         → "EUR 0.00"
        format_currency(99, 'USD')        → "USD 0.99"

    Negative Werte: Minus-Zeichen vor Currency.
        format_currency(-100, 'CHF')      → "-CHF 1.00"
    """
    ccy = currency.upper().strip()
    units = float(amount_rappen) / 100.0
    is_neg = units < 0
    abs_units = abs(units)
    # Tausender-Trennung manuell (vermeidet Locale-Abhaengigkeit)
    if decimals > 0:
        # decimals=2: '123456.78' → integer + decimal
        rounded = round(abs_units, decimals)
        integer_part = int(rounded)
        decimal_part = rounded - integer_part
        integer_str = f"{integer_part:,}".replace(",", thousand_sep)
        decimal_str = f"{decimal_part:.{decimals}f}"[1:]  # strip leading 0
        formatted = f"{integer_str}{decimal_str}"
    else:
        # decimals=0: ganze Einheiten, korrekt gerundet
        integer_part = int(round(abs_units))
        formatted = f"{integer_part:,}".replace(",", thousand_sep)
    sign = "-" if is_neg else ""
    return f"{sign}{ccy} {formatted}"
