"""Stooq-Symbol-Mapping pro Boerse + Currency-Inferenz.

Stooq nutzt kleinbuchstabige Ticker mit Boersen-Suffix:
- .us  (NYSE/NASDAQ)
- .uk  (LSE)
- .de  (XETRA)
- .ch  (SIX)
- .fr  (Paris)
- .it  (Milan)
- .nl  (Amsterdam)
- .es  (Madrid)
- ...

Da Stooq keine Currency in der CSV liefert, leiten wir sie aus dem Suffix ab.
"""
from __future__ import annotations

# 5eyes-Boersen-Code -> Stooq-Suffix.
EXCHANGE_TO_STOOQ_SUFFIX: dict[str, str] = {
    "SIX": ".ch", "VTX": ".ch", "BRN": ".ch", "SW": ".ch", "CH": ".ch",
    "FRA": ".de", "XETRA": ".de", "DE": ".de", "MUN": ".de", "BER": ".de", "STU": ".de",
    "VIE": ".at", "AT": ".at",
    "LON": ".uk", "LSE": ".uk", "UK": ".uk", "GB": ".uk",
    "PAR": ".fr", "FR": ".fr",
    "MIL": ".it", "IT": ".it",
    "AMS": ".nl", "NL": ".nl",
    "MAD": ".es", "ES": ".es",
    "STO": ".se", "SE": ".se",
    "OSL": ".no", "NO": ".no",
    "CPH": ".dk", "DK": ".dk",
    "HEL": ".fi", "FI": ".fi",
    "NYSE": ".us", "NASDAQ": ".us", "AMEX": ".us", "ARCA": ".us", "US": ".us",
}

# Stooq-Suffix -> Currency (ISO 4217).
STOOQ_SUFFIX_TO_CURRENCY: dict[str, str] = {
    ".ch": "CHF", ".de": "EUR", ".at": "EUR", ".uk": "GBP",
    ".fr": "EUR", ".it": "EUR", ".nl": "EUR", ".es": "EUR",
    ".se": "SEK", ".no": "NOK", ".dk": "DKK", ".fi": "EUR",
    ".us": "USD",
}

# Yahoo-Suffix -> Stooq-Suffix Mapping (haeufige Faelle, damit der
# Aggregator durchgaengig Yahoo-Style-Symbole reichen kann ohne dass
# jeder Provider extra parametriert werden muss).
_YAHOO_TO_STOOQ_SUFFIX: dict[str, str] = {
    ".SW": ".ch", ".DE": ".de", ".F": ".de", ".MU": ".de", ".BE": ".de", ".SG": ".de",
    ".VI": ".at", ".L": ".uk", ".PA": ".fr", ".MI": ".it", ".AS": ".nl",
    ".MC": ".es", ".ST": ".se", ".OL": ".no", ".CO": ".dk", ".HE": ".fi",
}


def stooq_symbol(ticker: str, exchange: str | None = None) -> str:
    """Liefert das Stooq-Symbol (kleinbuchstabig + Suffix).

    Drei Pfade:
    1) Ticker hat bereits Stooq-Suffix (z.B. 'ubsg.ch') -> nur lower-case
    2) Ticker hat Yahoo-Style-Suffix (z.B. 'UBSG.SW') -> nach Stooq-Suffix mappen
    3) Ticker ohne Suffix -> Suffix aus `exchange` ableiten
    """
    raw = (ticker or "").strip()
    if not raw:
        return raw
    # 1) Bereits Stooq-Suffix?
    lowered = raw.lower()
    for suffix in STOOQ_SUFFIX_TO_CURRENCY:
        if lowered.endswith(suffix):
            return lowered
    # 2) Yahoo-Style-Suffix (case-sensitive auf Suffix)?
    if "." in raw:
        base, dot, tail = raw.rpartition(".")
        yahoo_suffix = "." + tail
        stooq_suffix_from_yahoo = _YAHOO_TO_STOOQ_SUFFIX.get(yahoo_suffix.upper())
        if stooq_suffix_from_yahoo is not None:
            return f"{base.lower()}{stooq_suffix_from_yahoo}"
        # Punkt vorhanden aber unbekanntes Suffix -> als-ist (lower)
        return lowered
    # 3) Suffix aus exchange ableiten
    if exchange is None:
        return lowered
    suffix = EXCHANGE_TO_STOOQ_SUFFIX.get(exchange.upper().strip())
    if suffix is None:
        return lowered
    return f"{lowered}{suffix}"


def stooq_currency(symbol: str) -> str:
    """Currency aus Stooq-Suffix ableiten. Default 'USD'."""
    s = (symbol or "").strip().lower()
    for suffix, currency in STOOQ_SUFFIX_TO_CURRENCY.items():
        if s.endswith(suffix):
            return currency
    return "USD"
