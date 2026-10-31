"""TwelveDataProvider — End-of-Day Daten via twelvedata.com.

Tier 2 Primary (~CHF 80/Monat USD 79). Sehr breite Coverage inkl. SIX,
gute API-Stabilitaet. Bestehender Inhouse-Helper services/twelvedata_client.py
bleibt unberuehrt (Backwards-Compat fuer andere Aufrufer); dieser Adapter
ist neu und fuellt das MarketDataProvider-Interface.

API: https://api.twelvedata.com/time_series?symbol={sym}&interval=1day
     &start_date=...&end_date=...&apikey={key}

Response: {"values": [{"datetime":"2026-05-08","open":...,"high":...,
                       "low":...,"close":...,"volume":...}, ...],
           "meta": {"currency":"CHF",...}}
Bei Fehler: {"status":"error","message":"...","code":404}
"""
from __future__ import annotations

import logging
from datetime import date as Date
from decimal import Decimal
from typing import Any

import requests

from ..base import Bar, MarketDataProvider, ProductInfo
from ..exceptions import ProviderError, RateLimitError, SymbolNotFound

logger = logging.getLogger(__name__)

_TD_URL = "https://api.twelvedata.com/time_series"
_DEFAULT_TIMEOUT = 10


class TwelveDataProvider(MarketDataProvider):
    """HTTP-Client fuer twelvedata.com mit kostenlosem Free-Tier (800/Tag)."""

    name = "twelvedata"

    def __init__(
        self,
        api_key: str | None = None,
        timeout: int = _DEFAULT_TIMEOUT,
        session: Any | None = None,
    ) -> None:
        self._api_key = (api_key or "").strip() or None
        self._timeout = timeout
        self._session = session

    @property
    def has_key(self) -> bool:
        return self._api_key is not None

    def _http_get(self, params: dict[str, str]) -> dict:
        if not self.has_key:
            raise ProviderError("twelvedata: kein API-Key konfiguriert")
        params = {**params, "apikey": self._api_key or ""}
        try:
            if self._session is not None:
                resp = self._session.get(_TD_URL, params=params, timeout=self._timeout)
            else:
                resp = requests.get(_TD_URL, params=params, timeout=self._timeout)
        except requests.RequestException as exc:
            raise ProviderError(f"twelvedata network: {exc}") from exc
        if resp.status_code == 429:
            raise RateLimitError("twelvedata 429")
        if resp.status_code != 200:
            raise ProviderError(f"twelvedata HTTP {resp.status_code}")
        try:
            data = resp.json()
        except ValueError as exc:
            raise ProviderError(f"twelvedata non-JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ProviderError("twelvedata unexpected response shape")
        # Error-Pattern: {"status":"error","message":"...","code":404}
        if data.get("status") == "error":
            code = int(data.get("code") or 0)
            message = str(data.get("message") or "twelvedata error")
            if code == 429 or "rate" in message.lower():
                raise RateLimitError(f"twelvedata: {message}")
            if code == 404 or "not found" in message.lower() or "symbol" in message.lower():
                raise SymbolNotFound(f"twelvedata: {message}")
            raise ProviderError(f"twelvedata: {message}")
        return data

    @staticmethod
    def _to_bar(symbol: str, row: dict, currency: str) -> Bar:
        try:
            d = Date.fromisoformat(str(row["datetime"]))
            o = Decimal(str(row["open"]))
            h = Decimal(str(row["high"]))
            lo = Decimal(str(row["low"]))
            c = Decimal(str(row["close"]))
        except (KeyError, ValueError, TypeError) as exc:
            raise ProviderError(f"twelvedata row malformed for {symbol}: {exc}") from exc
        v: int | None = None
        try:
            if "volume" in row and row["volume"] not in (None, ""):
                v = int(float(row["volume"]))
        except (ValueError, TypeError):
            v = None
        return Bar(
            symbol=symbol, date=d,
            open=o, high=h, low=lo, close=c,
            currency=currency or "USD",
            volume=v, source="twelvedata",
        )

    # ------------------------------------------------------------------ #
    def get_eod(self, symbol: str, on_date: Date) -> Bar:
        params = {
            "symbol": symbol,
            "interval": "1day",
            "outputsize": "10",  # 10 Tage Backoff fuer Wochenenden
            "end_date": on_date.isoformat(),
        }
        data = self._http_get(params)
        currency = (data.get("meta") or {}).get("currency") or "USD"
        values = data.get("values") or []
        if not isinstance(values, list) or not values:
            raise SymbolNotFound(f"twelvedata: keine Werte fuer {symbol}")
        # TwelveData liefert absteigend (neueste zuerst). Filter <= on_date.
        candidates = []
        for v in values:
            try:
                d = Date.fromisoformat(str(v.get("datetime")))
            except (ValueError, TypeError):
                continue
            if d <= on_date:
                candidates.append((d, v))
        if not candidates:
            raise SymbolNotFound(f"twelvedata: keine Zeile <= {on_date} fuer {symbol}")
        # neueste zuerst -> nimm das erste
        candidates.sort(key=lambda t: t[0], reverse=True)
        return self._to_bar(symbol, candidates[0][1], str(currency))

    def get_history(self, symbol: str, start: Date, end: Date) -> list[Bar]:
        if end < start:
            return []
        params = {
            "symbol": symbol,
            "interval": "1day",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "outputsize": "5000",
        }
        try:
            data = self._http_get(params)
        except SymbolNotFound:
            return []
        currency = (data.get("meta") or {}).get("currency") or "USD"
        values = data.get("values") or []
        if not isinstance(values, list):
            return []
        bars: list[Bar] = []
        for v in values:
            try:
                bars.append(self._to_bar(symbol, v, str(currency)))
            except ProviderError:
                continue
        bars.sort(key=lambda b: b.date)
        return bars

    def lookup_isin(self, isin: str) -> ProductInfo:
        # TwelveData Symbol-Search ist Premium; wir nutzen OpenFIGI (P8).
        raise SymbolNotFound(
            f"twelvedata unterstuetzt keine ISIN-Suche im Free-Tier; "
            f"nutze OpenFIGIProvider fuer '{isin}'"
        )

    def is_healthy(self) -> bool:
        return self.has_key
