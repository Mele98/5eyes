"""SwissfunddataScraper — opt-in Master-Daten via swissfunddata.ch.

Schweizer Fonds-Database. TOS-Status unklar; opt-in default deaktiviert.

URL-Pattern: https://www.swissfunddata.ch/sfdpub/en/funds/{ISIN}
(Pfad variiert; wir nutzen Suche per ISIN als Query-Param).
"""
from __future__ import annotations

import logging
import time
from decimal import Decimal, InvalidOperation
from typing import Any

import requests

from ...exceptions import ProviderError, RateLimitError, SymbolNotFound
from ..base import ETFInfo, ETFProvider

logger = logging.getLogger(__name__)

_SFD_SEARCH_URL = "https://www.swissfunddata.ch/sfdpub/en/funds"
_DEFAULT_TIMEOUT = 10
_DEFAULT_RATE_DELAY_SECONDS = 5


class SwissfunddataScraper(ETFProvider):
    """Web-Scraper fuer swissfunddata.ch — opt-in."""

    name = "swissfunddata"

    def __init__(
        self,
        enabled: bool = False,
        rate_delay_seconds: int = _DEFAULT_RATE_DELAY_SECONDS,
        timeout: int = _DEFAULT_TIMEOUT,
        session: Any | None = None,
        sleeper: Any = time.sleep,
    ) -> None:
        self._enabled = bool(enabled)
        self._rate_delay = max(0, int(rate_delay_seconds))
        self._timeout = timeout
        self._session = session
        self._sleep = sleeper
        self._last_request_epoch: float = 0.0

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _respect_rate_limit(self) -> None:
        if self._rate_delay <= 0:
            return
        now = time.monotonic()
        delta = now - self._last_request_epoch
        if delta < self._rate_delay and self._last_request_epoch > 0:
            self._sleep(self._rate_delay - delta)
        self._last_request_epoch = time.monotonic()

    def _http_get(self, isin: str) -> str:
        if not self._enabled:
            raise ProviderError(
                "swissfunddata scraper deaktiviert. Aktiviere via enabled=True."
            )
        self._respect_rate_limit()
        headers = {
            "User-Agent": "Mozilla/5.0 (5eyes-inhouse-research)",
            "Accept": "text/html,application/xhtml+xml",
        }
        params = {"isin": isin}
        try:
            if self._session is not None:
                resp = self._session.get(
                    _SFD_SEARCH_URL, params=params, headers=headers, timeout=self._timeout,
                )
            else:
                resp = requests.get(
                    _SFD_SEARCH_URL, params=params, headers=headers, timeout=self._timeout,
                )
        except requests.RequestException as exc:
            raise ProviderError(f"swissfunddata network: {exc}") from exc
        if resp.status_code == 429:
            raise RateLimitError("swissfunddata 429")
        if resp.status_code == 404:
            raise SymbolNotFound(f"swissfunddata: {isin} nicht gefunden")
        if resp.status_code != 200:
            raise ProviderError(f"swissfunddata HTTP {resp.status_code}")
        return resp.text or ""

    @staticmethod
    def _parse_profile(html: str, isin: str) -> ETFInfo:
        try:
            from bs4 import BeautifulSoup  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ProviderError(f"BeautifulSoup nicht installiert: {exc}") from exc
        soup = BeautifulSoup(html, "html.parser")

        # Heuristik: swissfunddata listet Felder oft in <dt>/<dd> Paaren oder
        # <th>/<td> tabellen.
        def _label_value(*needles: str) -> str | None:
            for tag in soup.find_all(["dt", "th", "td", "span", "div"]):
                txt = (tag.get_text() or "").strip()
                if not txt:
                    continue
                for needle in needles:
                    if needle.lower() in txt.lower():
                        # naechstes Element
                        nxt = tag.find_next_sibling()
                        if nxt is None:
                            nxt = tag.find_next(["dd", "td"])
                        if nxt is not None:
                            val = (nxt.get_text() or "").strip()
                            if val and val != txt:
                                return val
            return None

        name = None
        h1 = soup.find("h1") or soup.find("h2")
        if h1:
            name = (h1.get_text() or "").strip() or None
        if not name:
            t = soup.find("title")
            if t:
                name = (t.get_text() or "").strip() or None

        ter_str = _label_value("TER", "Total Expense Ratio", "Gesamtkostenquote")
        ter_bps: int | None = None
        if ter_str:
            try:
                num = ter_str.replace("%", "").replace(",", ".").strip().split()[0]
                ter_bps = int(round(float(num) * 100))
            except (ValueError, IndexError):
                ter_bps = None

        domicile = _label_value("Domicile", "Domizil")
        currency = _label_value("Fund currency", "Fondswaehrung", "Currency")
        asset_class = _label_value("Asset class", "Anlageklasse")
        replication = _label_value("Replication", "Replikation")

        return ETFInfo(
            isin=isin, ticker=None, name=name,
            ter_bps=ter_bps,
            aum_chf=None,
            domicile=domicile,
            replication=replication,
            distribution=None,
            fund_currency=currency,
            asset_class=asset_class,
            region=None,
            source="swissfunddata",
        )

    def lookup_isin(self, isin: str) -> ETFInfo:
        if not isin or not isin.strip():
            raise SymbolNotFound("swissfunddata: leere ISIN")
        html = self._http_get(isin.strip())
        return self._parse_profile(html, isin.strip())

    def is_healthy(self) -> bool:
        return self._enabled
