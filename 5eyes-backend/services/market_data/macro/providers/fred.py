"""FRED-Macro-Provider (St. Louis Fed).

API: https://api.stlouisfed.org/fred/series/observations
Format: ?series_id=CPIAUCSL&api_key={key}&file_type=json
        &observation_start=YYYY-MM-DD&observation_end=YYYY-MM-DD
Response:
  {"observations": [{"date": "2025-01-01", "value": "315.605"}, ...]}

Beispiel-Series-Codes:
- CPIAUCSL          : US Inflation (CPI)
- DGS10             : US Treasury 10Y Yield
- DFF               : Federal Funds Effective Rate
- DEXSZUS           : USD/CHF FX (taeglich)

Free API-Key: registrieren auf fred.stlouisfed.org/docs/api/api_key.html
"""
from __future__ import annotations

import logging
from datetime import date as Date
from decimal import Decimal
from typing import Any

import requests

from ...exceptions import ProviderError, RateLimitError
from ..base import MacroPoint, MacroProvider

logger = logging.getLogger(__name__)

_FRED_URL = "https://api.stlouisfed.org/fred/series/observations"
_DEFAULT_TIMEOUT = 10


class FREDMacroProvider(MacroProvider):
    """HTTP-Client fuer FRED API. Braucht einen API-Key (gratis)."""

    name = "fred"

    def __init__(
        self,
        api_key: str | None = None,
        timeout: int = _DEFAULT_TIMEOUT,
        session: Any | None = None,
    ) -> None:
        self._api_key = (api_key or "").strip() or None
        self._timeout = timeout
        self._session = session

    def _http_get(self, params: dict[str, str]) -> dict:
        if not self._api_key:
            raise ProviderError("FRED: kein API-Key konfiguriert")
        params = {**params, "api_key": self._api_key, "file_type": "json"}
        try:
            if self._session is not None:
                resp = self._session.get(_FRED_URL, params=params, timeout=self._timeout)
            else:
                resp = requests.get(_FRED_URL, params=params, timeout=self._timeout)
        except requests.RequestException as exc:
            raise ProviderError(f"FRED network: {exc}") from exc
        if resp.status_code == 429:
            raise RateLimitError("FRED 429 Too Many Requests")
        if resp.status_code != 200:
            raise ProviderError(f"FRED HTTP {resp.status_code}")
        try:
            data = resp.json()
        except ValueError as exc:
            raise ProviderError(f"FRED non-JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ProviderError("FRED unexpected response shape")
        return data

    def get_series(
        self,
        series_code: str,
        start: Date,
        end: Date,
    ) -> list[MacroPoint]:
        if end < start:
            return []
        params = {
            "series_id": series_code,
            "observation_start": start.isoformat(),
            "observation_end": end.isoformat(),
        }
        data = self._http_get(params)
        observations = data.get("observations") or []
        if not isinstance(observations, list):
            return []
        points: list[MacroPoint] = []
        for obs in observations:
            if not isinstance(obs, dict):
                continue
            date_str = obs.get("date")
            value_str = obs.get("value")
            if not date_str or value_str in (None, "", "."):
                # FRED markiert fehlende Werte als "."
                continue
            try:
                d = Date.fromisoformat(date_str)
                v = Decimal(str(value_str))
            except (ValueError, TypeError) as exc:
                logger.warning("FRED: skip malformed obs %s (%s)", obs, exc)
                continue
            points.append(MacroPoint(date=d, value=v, series_code=series_code, source="fred"))
        points.sort(key=lambda p: p.date)
        return points

    def is_healthy(self) -> bool:
        return bool(self._api_key)
