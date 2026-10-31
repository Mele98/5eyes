"""AlphaVantageProvider — End-of-Day Daten via alphavantage.co.

Backup #2 fuer Tier 1. Free-Tier hat striktes Rate-Limit (heute 25 calls/Tag,
5 calls/min). Daher: nur als Fallback einsetzen, nicht als Primary.

API-Pattern: GET https://www.alphavantage.co/query?function=TIME_SERIES_DAILY
            &symbol={sym}&apikey={key}&outputsize={compact|full}

Response-JSON:
{
  "Meta Data": {...},
  "Time Series (Daily)": {
    "2026-05-08": {
      "1. open": "28.50", "2. high": "28.90", "3. low": "28.30",
      "4. close": "28.75", "5. volume": "1500000"
    }, ...
  }
}

Bei Limit: {"Information": "Thank you for using ..."} oder {"Note": "..."}.
Bei Symbol-Not-Found: {"Error Message": "..."} oder leeres Time Series.
"""
from __future__ import annotations

import logging
from datetime import date as Date
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import requests

from ..base import Bar, MarketDataProvider, ProductInfo
from ..exceptions import ProviderError, RateLimitError, SymbolNotFound
from ._stooq_symbols import stooq_currency  # Suffix-zu-Currency Logik wiederverwendet

logger = logging.getLogger(__name__)

_AV_BASE_URL = "https://www.alphavantage.co/query"
_DEFAULT_TIMEOUT = 10
_DEFAULT_DAILY_LIMIT = 25  # Free-Tier 2024-2026


class AlphaVantageProvider(MarketDataProvider):
    """HTTP-Client fuer alphavantage.co mit in-memory Rate-Limit-Tracker.

    Aktiviert nur, wenn `api_key` gesetzt ist. Ohne Key liefert is_healthy()
    False — Aggregator skipped den Provider in der Fallback-Chain.
    """

    name = "alphavantage"

    def __init__(
        self,
        api_key: str | None = None,
        timeout: int = _DEFAULT_TIMEOUT,
        session: Any | None = None,
        daily_limit: int = _DEFAULT_DAILY_LIMIT,
    ) -> None:
        self._api_key = (api_key or "").strip() or None
        self._timeout = timeout
        self._session = session
        self._daily_limit = max(1, int(daily_limit))
        # Rate-Limit-Tracker: dict[YYYY-MM-DD UTC] -> count
        self._call_log: dict[str, int] = {}

    # ------------------------------------------------------------------ #
    @property
    def has_key(self) -> bool:
        return self._api_key is not None

    def _today_key(self) -> str:
        return datetime.now(timezone.utc).date().isoformat()

    def _check_rate_limit(self) -> None:
        if not self.has_key:
            raise ProviderError("alphavantage: kein API-Key konfiguriert")
        today = self._today_key()
        used = self._call_log.get(today, 0)
        if used >= self._daily_limit:
            raise RateLimitError(
                f"alphavantage daily limit reached ({used}/{self._daily_limit})"
            )

    def _record_call(self) -> None:
        today = self._today_key()
        self._call_log[today] = self._call_log.get(today, 0) + 1

    def _http_get(self, params: dict[str, str]) -> dict:
        params = {**params, "apikey": self._api_key or ""}
        try:
            if self._session is not None:
                resp = self._session.get(_AV_BASE_URL, params=params, timeout=self._timeout)
            else:
                resp = requests.get(_AV_BASE_URL, params=params, timeout=self._timeout)
        except requests.RequestException as exc:
            raise ProviderError(f"alphavantage network: {exc}") from exc
        if resp.status_code != 200:
            raise ProviderError(f"alphavantage HTTP {resp.status_code}")
        try:
            data = resp.json()
        except ValueError as exc:
            raise ProviderError(f"alphavantage non-JSON response: {exc}") from exc
        if not isinstance(data, dict):
            raise ProviderError("alphavantage unexpected response type")
        # Rate-Limit / Info-Hinweise erkennen
        for limit_key in ("Information", "Note"):
            msg = data.get(limit_key)
            if msg and "limit" in str(msg).lower():
                raise RateLimitError(f"alphavantage: {msg}")
        if "Error Message" in data:
            raise SymbolNotFound(str(data["Error Message"]))
        return data

    @staticmethod
    def _parse_time_series(data: dict, symbol: str) -> list[tuple[Date, Decimal, Decimal, Decimal, Decimal, int | None]]:
        ts = data.get("Time Series (Daily)") or {}
        if not isinstance(ts, dict) or not ts:
            raise SymbolNotFound(f"alphavantage: keine Time-Series fuer {symbol}")
        rows: list[tuple[Date, Decimal, Decimal, Decimal, Decimal, int | None]] = []
        for key, value in ts.items():
            try:
                d = datetime.strptime(key, "%Y-%m-%d").date()
                o = Decimal(str(value["1. open"]))
                h = Decimal(str(value["2. high"]))
                lo = Decimal(str(value["3. low"]))
                c = Decimal(str(value["4. close"]))
            except (KeyError, ValueError, TypeError) as exc:
                logger.warning("alphavantage: malformed entry skipped (%s): %s", symbol, exc)
                continue
            v: int | None = None
            try:
                if "5. volume" in value and value["5. volume"]:
                    v = int(value["5. volume"])
            except (ValueError, TypeError):
                v = None
            rows.append((d, o, h, lo, c, v))
        if not rows:
            raise SymbolNotFound(f"alphavantage: keine validen Zeilen fuer {symbol}")
        # Aufsteigend sortieren (AV liefert absteigend)
        rows.sort(key=lambda r: r[0])
        return rows

    @staticmethod
    def _to_bar(symbol: str, row: tuple, currency: str) -> Bar:
        d, o, h, lo, c, v = row
        return Bar(
            symbol=symbol, date=d,
            open=o, high=h, low=lo, close=c,
            currency=currency, volume=v,
            adjusted_close=None,
            source="alphavantage",
        )

    # ------------------------------------------------------------------ #
    def get_eod(self, symbol: str, on_date: Date) -> Bar:
        self._check_rate_limit()
        params = {
            "function": "TIME_SERIES_DAILY",
            "symbol": symbol,
            "outputsize": "compact",
        }
        data = self._http_get(params)
        self._record_call()
        rows = self._parse_time_series(data, symbol)
        # Letzter Eintrag <= on_date
        candidates = [r for r in rows if r[0] <= on_date]
        if not candidates:
            raise SymbolNotFound(f"alphavantage: keine Zeile <= {on_date} fuer {symbol}")
        return self._to_bar(symbol, candidates[-1], stooq_currency(symbol))

    def get_history(self, symbol: str, start: Date, end: Date) -> list[Bar]:
        if end < start:
            return []
        self._check_rate_limit()
        params = {
            "function": "TIME_SERIES_DAILY",
            "symbol": symbol,
            "outputsize": "full",
        }
        try:
            data = self._http_get(params)
        except SymbolNotFound:
            return []
        self._record_call()
        try:
            rows = self._parse_time_series(data, symbol)
        except SymbolNotFound:
            return []
        currency = stooq_currency(symbol)
        return [self._to_bar(symbol, r, currency) for r in rows if start <= r[0] <= end]

    def lookup_isin(self, isin: str) -> ProductInfo:
        raise SymbolNotFound(
            f"alphavantage unterstuetzt keine ISIN-Suche; Phase 8 OpenFIGI fuer '{isin}'"
        )

    def is_healthy(self) -> bool:
        if not self.has_key:
            return False
        try:
            self._check_rate_limit()
            return True
        except RateLimitError:
            return False
