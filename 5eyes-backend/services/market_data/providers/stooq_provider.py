"""StooqProvider — End-of-Day Daten via stooq.com CSV.

Backup #1 fuer Tier 1 (gratis, robust, kein Auth, kein Rate-Limit). Stooq
liefert CSV via einfacher HTTP-URL — sehr stabil, da kein API-Versioning.

URL-Pattern:
- Tagesdaten: https://stooq.com/q/d/l/?s={symbol}&i=d
- Bereich:    https://stooq.com/q/d/l/?s={symbol}&i=d&d1=YYYYMMDD&d2=YYYYMMDD

CSV-Format: Date,Open,High,Low,Close,Volume

Risiken:
- HTML-404 statt CSV bei unbekanntem Symbol -> wir detektieren via Header
- Stooq liefert keine ISIN/Master-Daten -> lookup_isin: SymbolNotFound
"""
from __future__ import annotations

import logging
from datetime import date as Date
from datetime import datetime
from decimal import Decimal
from io import StringIO
from typing import Any
import csv

import requests

from ..base import Bar, MarketDataProvider, ProductInfo
from ..exceptions import ProviderError, SymbolNotFound
from ._stooq_symbols import stooq_currency, stooq_symbol

logger = logging.getLogger(__name__)

_STOOQ_BASE_URL = "https://stooq.com/q/d/l/"
_DEFAULT_TIMEOUT = 10  # Sekunden
_EXPECTED_HEADER = "Date,Open,High,Low,Close,Volume"


class StooqProvider(MarketDataProvider):
    """Provider auf Basis von stooq.com CSV-Downloads."""

    name = "stooq"

    def __init__(self, timeout: int = _DEFAULT_TIMEOUT, session: Any | None = None) -> None:
        self._timeout = timeout
        self._session = session  # erlaubt Tests mit Mock-Session

    # ------------------------------------------------------------------ #
    def _http_get(self, url: str, params: dict[str, str]) -> str:
        try:
            if self._session is not None:
                resp = self._session.get(url, params=params, timeout=self._timeout)
            else:
                resp = requests.get(url, params=params, timeout=self._timeout)
        except requests.RequestException as exc:
            raise ProviderError(f"stooq network error: {exc}") from exc
        if resp.status_code != 200:
            raise ProviderError(f"stooq HTTP {resp.status_code}")
        text = resp.text or ""
        # Stooq liefert bei Symbol-Not-Found oft HTML-Response statt CSV.
        # Detektieren via Content-Header oder erste Zeile.
        ct = (resp.headers.get("Content-Type") or "").lower()
        if "text/html" in ct:
            raise SymbolNotFound("stooq lieferte HTML statt CSV (Symbol unbekannt)")
        return text

    @staticmethod
    def _parse_csv(text: str, symbol: str) -> list[tuple[Date, Decimal, Decimal, Decimal, Decimal, int | None]]:
        """Parst Stooq-CSV in Liste von (date, O, H, L, C, V).

        SymbolNotFound wenn Header fehlt oder CSV leer (ohne Daten).
        """
        if not text or not text.strip():
            raise SymbolNotFound(f"stooq: leere Response fuer {symbol}")
        first_line = text.split("\n", 1)[0].strip()
        if not first_line.startswith("Date,"):
            raise SymbolNotFound(f"stooq: ungueltige CSV fuer {symbol}: {first_line[:80]!r}")
        rows: list[tuple[Date, Decimal, Decimal, Decimal, Decimal, int | None]] = []
        reader = csv.DictReader(StringIO(text))
        for row in reader:
            try:
                d = datetime.strptime(row["Date"], "%Y-%m-%d").date()
                o = Decimal(row["Open"])
                h = Decimal(row["High"])
                lo = Decimal(row["Low"])
                c = Decimal(row["Close"])
            except (KeyError, ValueError) as exc:
                # einzelne kaputte Zeile uebespringen, nicht ganzes Result killen
                logger.warning("stooq: malformed row skipped (%s): %s", symbol, exc)
                continue
            v: int | None = None
            try:
                if row.get("Volume") and row["Volume"].strip():
                    v = int(row["Volume"])
            except ValueError:
                v = None
            rows.append((d, o, h, lo, c, v))
        if not rows:
            raise SymbolNotFound(f"stooq: keine Datenzeilen fuer {symbol}")
        return rows

    @staticmethod
    def _to_bar(symbol: str, row: tuple, currency: str) -> Bar:
        d, o, h, lo, c, v = row
        return Bar(
            symbol=symbol, date=d,
            open=o, high=h, low=lo, close=c,
            currency=currency, volume=v,
            adjusted_close=None,  # Stooq liefert keinen Adj-Close direkt
            source="stooq",
        )

    # ------------------------------------------------------------------ #
    def get_eod(self, symbol: str, on_date: Date) -> Bar:
        """Letzter Handelstag <= on_date (Stooq liefert Range-CSV).

        Wir fragen [on_date-7d, on_date] und nehmen die letzte Zeile.
        """
        sym = stooq_symbol(symbol)
        params = {
            "s": sym,
            "i": "d",
            "d1": (on_date.replace(day=max(1, on_date.day))).strftime("%Y%m%d"),
            "d2": on_date.strftime("%Y%m%d"),
        }
        # 7 Tage Backoff fuer Wochenende/Feiertage:
        from datetime import timedelta
        params["d1"] = (on_date - timedelta(days=10)).strftime("%Y%m%d")
        text = self._http_get(_STOOQ_BASE_URL, params)
        rows = self._parse_csv(text, symbol)
        return self._to_bar(symbol, rows[-1], stooq_currency(sym))

    def get_history(self, symbol: str, start: Date, end: Date) -> list[Bar]:
        if end < start:
            return []
        sym = stooq_symbol(symbol)
        params = {
            "s": sym, "i": "d",
            "d1": start.strftime("%Y%m%d"),
            "d2": end.strftime("%Y%m%d"),
        }
        try:
            text = self._http_get(_STOOQ_BASE_URL, params)
        except SymbolNotFound:
            return []
        try:
            rows = self._parse_csv(text, symbol)
        except SymbolNotFound:
            return []
        currency = stooq_currency(sym)
        return [self._to_bar(symbol, r, currency) for r in rows]

    def lookup_isin(self, isin: str) -> ProductInfo:
        """Stooq liefert keine ISIN-Suche."""
        raise SymbolNotFound(
            f"stooq unterstuetzt keine ISIN-Suche; nutze OpenFIGIProvider fuer '{isin}'"
        )

    def is_healthy(self) -> bool:
        """Schneller Ping. Faellt zurueck auf True bei Netzwerk-Problemen,
        damit Aggregator den Provider zumindest versucht."""
        try:
            params = {"s": "spx", "i": "d"}
            session = self._session if self._session is not None else requests
            resp = session.get(_STOOQ_BASE_URL, params=params, timeout=3)
            return resp.status_code == 200
        except Exception:  # noqa: BLE001
            return True
