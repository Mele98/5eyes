"""OpenFIGIProvider — ISIN/Ticker/FIGI-Mapping via openfigi.com.

OpenFIGI ist der Bloomberg-betriebene Mapping-Service. Free-Tier:
25 requests/min, 50 ISINs pro Request (Batch). Mit Premium-Key 250/min.

API-Pattern:
  POST https://api.openfigi.com/v3/mapping
  Headers: X-OPENFIGI-APIKEY (optional)
  Body: [{"idType":"ID_ISIN","idValue":"CH0244767585"}, ...]
  Response: [[{"figi":"BBG...","ticker":"UBSG SW","name":"UBS",
              "exchCode":"SW","securityType":"...","compositeFIGI":"..."}], ...]
              oder [{"warning":"..."}]

Wird primaer fuer ISIN-Lookup genutzt; get_eod/get_history wirft
SymbolNotFound (OpenFIGI liefert keine Preisdaten).
"""
from __future__ import annotations

import logging
from datetime import date as Date
from typing import Any

import requests

from ..base import Bar, MarketDataProvider, ProductInfo
from ..exceptions import ProviderError, RateLimitError, SymbolNotFound

logger = logging.getLogger(__name__)

_OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"
_DEFAULT_TIMEOUT = 10
_BATCH_SIZE = 50


class OpenFIGIProvider(MarketDataProvider):
    """ISIN-Mapping-Provider auf Basis OpenFIGI.

    `api_key` ist optional. Ohne Key: Free-Tier (25/min, 5 ids/req in
    Praxis stabil). Mit Key: schneller (Premium).
    """

    name = "openfigi"

    def __init__(
        self,
        api_key: str | None = None,
        timeout: int = _DEFAULT_TIMEOUT,
        session: Any | None = None,
    ) -> None:
        self._api_key = (api_key or "").strip() or None
        self._timeout = timeout
        self._session = session

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["X-OPENFIGI-APIKEY"] = self._api_key
        return headers

    def _http_post(self, payload: list[dict]) -> list:
        try:
            if self._session is not None:
                resp = self._session.post(
                    _OPENFIGI_URL, json=payload, headers=self._headers(), timeout=self._timeout,
                )
            else:
                resp = requests.post(
                    _OPENFIGI_URL, json=payload, headers=self._headers(), timeout=self._timeout,
                )
        except requests.RequestException as exc:
            raise ProviderError(f"openfigi network: {exc}") from exc
        if resp.status_code == 429:
            raise RateLimitError("openfigi 429 Too Many Requests")
        if resp.status_code != 200:
            raise ProviderError(f"openfigi HTTP {resp.status_code}")
        try:
            data = resp.json()
        except ValueError as exc:
            raise ProviderError(f"openfigi non-JSON: {exc}") from exc
        if not isinstance(data, list):
            raise ProviderError("openfigi unexpected response shape")
        return data

    @staticmethod
    def _entry_to_product(entry: dict, isin: str) -> ProductInfo:
        ticker = (entry.get("ticker") or "").strip() or None
        # OpenFIGI liefert ticker als "UBSG SW" — wir mappen das auf
        # Yahoo-Style 'UBSG.SW' fuer cross-Provider-Konsistenz.
        if ticker and " " in ticker:
            base, sep, suffix = ticker.rpartition(" ")
            ticker = f"{base}.{suffix}"
        return ProductInfo(
            isin=isin,
            ticker=ticker,
            name=(entry.get("name") or "").strip() or None,
            exchange=(entry.get("exchCode") or "").strip() or None,
            currency=None,  # OpenFIGI liefert keine Currency direkt
            asset_class=(entry.get("securityType") or "").strip() or None,
            country=None,
            figi=(entry.get("figi") or "").strip() or None,
            source="openfigi",
        )

    # ------------------------------------------------------------------ #
    def get_eod(self, symbol: str, on_date: Date) -> Bar:
        raise SymbolNotFound("openfigi liefert keine Preisdaten — nutze yfinance/stooq")

    def get_history(self, symbol: str, start: Date, end: Date) -> list[Bar]:
        return []

    def lookup_isin(self, isin: str) -> ProductInfo:
        if not isin or not isin.strip():
            raise SymbolNotFound("openfigi: leere ISIN")
        results = self.lookup_isins([isin.strip()])
        info = results.get(isin.strip())
        if info is None:
            raise SymbolNotFound(f"openfigi: keine Daten fuer ISIN {isin}")
        return info

    # ------------------------------------------------------------------ #
    def lookup_isins(self, isins: list[str]) -> dict[str, ProductInfo]:
        """Batch-Lookup mehrerer ISINs in einem POST-Request.

        Returns dict {isin: ProductInfo} — fehlende ISINs sind nicht im Dict.
        """
        cleaned = [s.strip() for s in isins if s and s.strip()]
        if not cleaned:
            return {}
        # OpenFIGI erlaubt 50 IDs pro Request; bei > 50 batchen.
        out: dict[str, ProductInfo] = {}
        for i in range(0, len(cleaned), _BATCH_SIZE):
            batch = cleaned[i : i + _BATCH_SIZE]
            payload = [{"idType": "ID_ISIN", "idValue": isin} for isin in batch]
            data = self._http_post(payload)
            if len(data) != len(batch):
                logger.warning(
                    "openfigi: response length mismatch (%d != %d)",
                    len(data), len(batch),
                )
            for isin, item in zip(batch, data):
                # Item ist entweder {"data": [...]} (Treffer) oder
                # {"warning": "..."} oder {"error": "..."}
                if not isinstance(item, dict):
                    continue
                hits = item.get("data")
                if not hits or not isinstance(hits, list):
                    continue
                # Bevorzuge "common stock" / Aktien-Eintrag, sonst erstes Item
                preferred = None
                for h in hits:
                    if (h.get("securityType") or "").lower() in {
                        "common stock", "etp", "etf", "fund", "preferred"
                    }:
                        preferred = h
                        break
                entry = preferred or hits[0]
                out[isin] = self._entry_to_product(entry, isin)
        return out

    def is_healthy(self) -> bool:
        return True
