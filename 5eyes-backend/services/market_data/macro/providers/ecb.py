"""ECB Statistical Data Warehouse Macro-Provider.

API: https://data-api.ecb.europa.eu/service/data/{dataflow}/{seriesKey}
Format: ?format=jsondata&startPeriod=YYYY-MM-DD&endPeriod=YYYY-MM-DD

series_code Format: 'DATAFLOW.SERIES_KEY' z.B. 'EXR.D.USD.EUR.SP00.A'
(Daily USD/EUR Reference Rate). Wir splitten am ersten Punkt.

Response: SDMX-JSON mit dataSets[0].series[seriesKey].observations[idx]=[val,...]
und structure.dimensions.observation[0].values[idx].id = ISO-Datum.

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

_ECB_BASE = "https://data-api.ecb.europa.eu/service/data"
_DEFAULT_TIMEOUT = 10


class ECBMacroProvider(MacroProvider):
    """ECB SDW. Gratis, kein Key. series_code = 'DATAFLOW.SERIES_KEY'."""

    name = "ecb"

    def __init__(
        self,
        timeout: int = _DEFAULT_TIMEOUT,
        session: Any | None = None,
    ) -> None:
        self._timeout = timeout
        self._session = session

    @staticmethod
    def _split_series_code(series_code: str) -> tuple[str, str]:
        sc = (series_code or "").strip()
        if "." not in sc:
            raise ProviderError(f"ECB series_code muss Format 'DATAFLOW.SERIES_KEY' haben: {sc}")
        dataflow, _, key = sc.partition(".")
        if not dataflow or not key:
            raise ProviderError(f"ECB series_code unvollstaendig: {sc}")
        return dataflow, key

    def _http_get(self, dataflow: str, series_key: str, params: dict[str, str]) -> dict:
        url = f"{_ECB_BASE}/{dataflow}/{series_key}"
        headers = {"Accept": "application/json"}
        params = {**params, "format": "jsondata"}
        try:
            if self._session is not None:
                resp = self._session.get(url, params=params, headers=headers, timeout=self._timeout)
            else:
                resp = requests.get(url, params=params, headers=headers, timeout=self._timeout)
        except requests.RequestException as exc:
            raise ProviderError(f"ECB network: {exc}") from exc
        if resp.status_code == 429:
            raise RateLimitError("ECB 429")
        if resp.status_code == 404:
            return {}
        if resp.status_code != 200:
            raise ProviderError(f"ECB HTTP {resp.status_code}")
        try:
            return resp.json() or {}
        except ValueError as exc:
            raise ProviderError(f"ECB non-JSON: {exc}") from exc

    def get_series(
        self,
        series_code: str,
        start: Date,
        end: Date,
    ) -> list[MacroPoint]:
        if end < start:
            return []
        dataflow, series_key = self._split_series_code(series_code)
        data = self._http_get(dataflow, series_key, {
            "startPeriod": start.isoformat(),
            "endPeriod": end.isoformat(),
        })
        if not data:
            return []
        try:
            datasets = data.get("dataSets") or []
            if not datasets:
                return []
            series_dict = datasets[0].get("series") or {}
            # Es gibt typischerweise nur einen series-Key (z.B. "0:0:0:0:0:0")
            first_key = next(iter(series_dict), None)
            if first_key is None:
                return []
            observations = series_dict[first_key].get("observations") or {}
            # Datums-Map: structure.dimensions.observation[0].values[idx].id
            structure = data.get("structure") or {}
            dim_obs = (
                ((structure.get("dimensions") or {}).get("observation") or [{}])
            )
            time_dim = dim_obs[0] if dim_obs else {}
            time_values = time_dim.get("values") or []
            date_map: dict[int, str] = {
                idx: (v.get("id") or "") for idx, v in enumerate(time_values)
            }
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"ECB SDMX-Struktur unerwartet: {exc}") from exc

        points: list[MacroPoint] = []
        for idx_str, obs_arr in observations.items():
            try:
                idx = int(idx_str)
                date_str = date_map.get(idx) or ""
                if not date_str or not isinstance(obs_arr, list) or not obs_arr:
                    continue
                # ECB-Daten kommen oft im Format "YYYY-MM-DD" oder "YYYY-MM"
                # oder "YYYY". Wir nehmen den 1. eines Monats fuer M, 1. Januar
                # fuer A.
                d = _parse_ecb_date(date_str)
                if d is None:
                    continue
                value = obs_arr[0]
                if value is None:
                    continue
                v = Decimal(str(value))
            except (ValueError, TypeError) as exc:
                logger.warning("ECB: skip malformed obs %s (%s)", idx_str, exc)
                continue
            points.append(MacroPoint(date=d, value=v, series_code=series_code, source="ecb"))
        points.sort(key=lambda p: p.date)
        return points


def _parse_ecb_date(date_str: str) -> Date | None:
    """Akzeptiert YYYY, YYYY-MM, YYYY-MM-DD, YYYY-QN (Quartal)."""
    s = (date_str or "").strip()
    if not s:
        return None
    try:
        if len(s) == 4:
            return Date(int(s), 1, 1)
        if len(s) == 7 and "-Q" in s.upper():
            year_str, _, q = s.upper().partition("-Q")
            year = int(year_str)
            month = {"1": 1, "2": 4, "3": 7, "4": 10}.get(q)
            if month is None:
                return None
            return Date(year, month, 1)
        if len(s) == 7:
            return Date.fromisoformat(s + "-01")
        return Date.fromisoformat(s)
    except (ValueError, TypeError):
        return None
