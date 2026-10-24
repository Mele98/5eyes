"""SNB Daten-Portal Macro-Provider.

API: https://data.snb.ch/api/cube/{cube_id}/data/json/{lang}
oder POST mit dimensions als Body.

Einfacher Endpunkt fuer ganze Cubes:
  GET https://data.snb.ch/api/cube/{cube_id}/data/json
  Response: {"timeseries":[{"values":[{"date":"2024-12","value":"1.5"}, ...]}, ...]}

series_code = 'cube_id' (z.B. 'cube_id=plkopr' fuer Konsumentenpreise).

Kein API-Key noetig.
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

_SNB_BASE = "https://data.snb.ch/api/cube"
_DEFAULT_TIMEOUT = 10


class SNBMacroProvider(MacroProvider):
    """SNB Daten-Portal. Gratis, kein Key. series_code = cube_id."""

    name = "snb"

    def __init__(
        self,
        timeout: int = _DEFAULT_TIMEOUT,
        session: Any | None = None,
    ) -> None:
        self._timeout = timeout
        self._session = session

    def _http_get(self, cube_id: str) -> dict:
        url = f"{_SNB_BASE}/{cube_id}/data/json"
        headers = {"Accept": "application/json"}
        try:
            if self._session is not None:
                resp = self._session.get(url, headers=headers, timeout=self._timeout)
            else:
                resp = requests.get(url, headers=headers, timeout=self._timeout)
        except requests.RequestException as exc:
            raise ProviderError(f"SNB network: {exc}") from exc
        if resp.status_code == 429:
            raise RateLimitError("SNB 429")
        if resp.status_code == 404:
            return {}
        if resp.status_code != 200:
            raise ProviderError(f"SNB HTTP {resp.status_code}")
        try:
            return resp.json() or {}
        except ValueError as exc:
            raise ProviderError(f"SNB non-JSON: {exc}") from exc

    def get_series(
        self,
        series_code: str,
        start: Date,
        end: Date,
    ) -> list[MacroPoint]:
        if end < start:
            return []
        cube_id = (series_code or "").strip()
        if not cube_id:
            raise ProviderError("SNB series_code (cube_id) leer")
        data = self._http_get(cube_id)
        if not data:
            return []
        timeseries = data.get("timeseries") or []
        if not isinstance(timeseries, list) or not timeseries:
            return []
        # SNB-Cubes haben oft mehrere series; wir flatten alle Werte.
        # Wenn ein Cube nur eine series hat, ist der Default-Pfad.
        points: list[MacroPoint] = []
        for series in timeseries:
            if not isinstance(series, dict):
                continue
            values = series.get("values") or []
            if not isinstance(values, list):
                continue
            for v in values:
                if not isinstance(v, dict):
                    continue
                date_str = v.get("date") or ""
                value_raw = v.get("value")
                if value_raw in (None, "", "."):
                    continue
                d = _parse_snb_date(date_str)
                if d is None:
                    continue
                if d < start or d > end:
                    continue
                try:
                    val = Decimal(str(value_raw))
                except (ValueError, TypeError) as exc:
                    logger.warning("SNB: skip malformed value %s (%s)", value_raw, exc)
                    continue
                points.append(MacroPoint(date=d, value=val, series_code=series_code, source="snb"))
        points.sort(key=lambda p: p.date)
        return points


def _parse_snb_date(date_str: str) -> Date | None:
    """SNB liefert oft 'YYYY-MM' fuer Monatswerte und 'YYYY' fuer Jahre."""
    s = (date_str or "").strip()
    if not s:
        return None
    try:
        if len(s) == 4:
            return Date(int(s), 1, 1)
        if len(s) == 7:
            return Date.fromisoformat(s + "-01")
        return Date.fromisoformat(s)
    except (ValueError, TypeError):
        return None
