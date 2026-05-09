"""Yahoo-Ticker-Suffix-Mapping pro Boerse.

Yahoo erwartet Boersen-Suffixe an Ticker (z.B. UBSG.SW fuer SIX). Diese
Helper-Funktion mappt einen unsuffixierten Ticker + Boersen-Code auf den
Yahoo-erwarteten String.

Quellen:
- https://help.yahoo.com/kb/SLN2310.html (offizielle Yahoo-Liste)
- 5eyes braucht primaer CH (.SW), DACH (.DE/.VI), UK (.L), US (kein Suffix).
"""
from __future__ import annotations

# Boersen-Code (5eyes-intern) -> Yahoo-Suffix.
# US-Boersen haben kein Suffix in Yahoo.
EXCHANGE_TO_YAHOO_SUFFIX: dict[str, str] = {
    # Schweiz
    "SIX": ".SW",
    "VTX": ".SW",     # SIX/Virt-X
    "BRN": ".SW",     # BX Swiss
    "SW": ".SW",      # Kurzform
    "CH": ".SW",      # ISO-CH-Default

    # Deutschland
    "FRA": ".F",      # Frankfurt
    "XETRA": ".DE",   # XETRA
    "DE": ".DE",
    "MUN": ".MU",
    "BER": ".BE",
    "STU": ".SG",

    # Oesterreich
    "VIE": ".VI",
    "AT": ".VI",

    # United Kingdom
    "LON": ".L",
    "LSE": ".L",
    "UK": ".L",
    "GB": ".L",

    # Frankreich
    "PAR": ".PA",
    "FR": ".PA",

    # Italien
    "MIL": ".MI",
    "IT": ".MI",

    # Niederlande
    "AMS": ".AS",
    "NL": ".AS",

    # Spanien
    "MAD": ".MC",
    "ES": ".MC",

    # Skandinavien
    "STO": ".ST",
    "SE": ".ST",
    "OSL": ".OL",
    "NO": ".OL",
    "CPH": ".CO",
    "DK": ".CO",
    "HEL": ".HE",
    "FI": ".HE",

    # USA: kein Suffix
    "NYSE": "",
    "NASDAQ": "",
    "AMEX": "",
    "ARCA": "",
    "US": "",
}


def yahoo_ticker(ticker: str, exchange: str | None = None) -> str:
    """Liefert den Yahoo-erwarteten Ticker (mit Suffix wenn noetig).

    Wenn der Ticker bereits ein Suffix enthaelt (z.B. 'UBSG.SW'), wird er
    unveraendert zurueckgegeben. Wenn `exchange` None oder unbekannt ist,
    wird der Ticker auch unveraendert zurueckgegeben (Annahme: Caller
    weiss was er tut).
    """
    raw = (ticker or "").strip()
    if not raw:
        return raw
    # Bereits suffixiert? "." am Ende eines bekannten Suffix
    if "." in raw:
        return raw
    if exchange is None:
        return raw
    suffix = EXCHANGE_TO_YAHOO_SUFFIX.get(exchange.upper().strip())
    if suffix is None:
        return raw  # unbekannte Boerse, Caller bekommt unveraenderten Ticker
    return f"{raw}{suffix}"
