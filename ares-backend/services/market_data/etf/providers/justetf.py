"""JustetfScraper — opt-in ETF-Master-Daten via justetf.com.

WICHTIG: justetf.com TOS verbieten Crawling. Dieser Scraper ist
default deaktiviert und nur aktivierbar via `enabled=True` im Konstruktor
oder env-Var. Bei FINIG-Lizenz spaeter durch SIX/Morningstar ersetzen.

URL-Pattern: https://www.justetf.com/en/etf-profile.html?isin={ISIN}
Defensive Selektoren mit Fallback (HTML kann sich aendern).
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

_JUSTETF_PROFILE_URL = "https://www.justetf.com/en/etf-profile.html"
_DEFAULT_TIMEOUT = 10
_DEFAULT_RATE_DELAY_SECONDS = 5  # konservatives Rate-Limit


class JustetfScraper(ETFProvider):
    """Web-Scraper fuer justetf.com — opt-in!"""

    name = "justetf"

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
        """Stellt Mindest-Pause zwischen Requests sicher."""
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
                "justetf scraper ist deaktiviert (TOS). Aktiviere via enabled=True."
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
                    _JUSTETF_PROFILE_URL, params=params, headers=headers, timeout=self._timeout,
                )
            else:
                resp = requests.get(
                    _JUSTETF_PROFILE_URL, params=params, headers=headers, timeout=self._timeout,
                )
        except requests.RequestException as exc:
            raise ProviderError(f"justetf network: {exc}") from exc
        if resp.status_code == 429:
            raise RateLimitError("justetf 429 Too Many Requests")
        if resp.status_code == 404:
            raise SymbolNotFound(f"justetf: keine Profilseite fuer {isin}")
        if resp.status_code != 200:
            raise ProviderError(f"justetf HTTP {resp.status_code}")
        return resp.text or ""

    @staticmethod
    def _parse_profile(html: str, isin: str) -> ETFInfo:
        """Parsed das Justetf-Profil zu ETFInfo.

        Defensive Selektoren: justetf bettet die meisten Daten in
        <div class="vallabel"><span class="val">...</span></div>-Strukturen,
        Labels in <div class="vallabel">. Wir suchen Schluessel-Labels
        und nehmen den naechstgelegenen `.val`-Wert.
        """
        try:
            from bs4 import BeautifulSoup  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ProviderError(f"BeautifulSoup nicht installiert: {exc}") from exc
        soup = BeautifulSoup(html, "html.parser")
        if not (soup.find("title") or soup.find("h1")):
            raise SymbolNotFound(f"justetf: HTML ohne Title fuer {isin}")

        def _label_value(*needles: str) -> str | None:
            for label_node in soup.find_all(string=True):
                txt = (str(label_node) or "").strip()
                if not txt:
                    continue
                for needle in needles:
                    if needle.lower() in txt.lower():
                        parent = label_node.parent
                        if parent is None:
                            continue
                        # versuch sibling .val
                        sibling = parent.find_next(class_="val")
                        if sibling is None:
                            sibling = parent.find_next("span")
                        if sibling is not None:
                            val = (sibling.get_text() or "").strip()
                            if val:
                                return val
            return None

        name = None
        h1 = soup.find("h1")
        if h1:
            name = (h1.get_text() or "").strip() or None

        ter_str = _label_value("Total expense ratio", "TER")
        ter_bps: int | None = None
        if ter_str:
            try:
                # e.g. "0.07% p.a." -> 7 bps
                num = ter_str.replace("%", "").replace("p.a.", "").strip().split()[0]
                ter_bps = int(round(float(num) * 100))
            except (ValueError, IndexError):
                ter_bps = None

        aum_str = _label_value("Fund size", "Assets under management")
        aum: Decimal | None = None
        if aum_str:
            try:
                cleaned = aum_str.replace(",", "").replace("'", "").strip()
                num = cleaned.split()[0]
                aum = Decimal(num)
            except (InvalidOperation, IndexError, ValueError):
                aum = None

        replication = _label_value("Replication method", "Replikation")
        if replication:
            r = replication.lower()
            if "physical" in r or "sampling" in r:
                replication = "physical" if "physical" in r else "sampling"
            elif "synthetic" in r:
                replication = "synthetic"

        distribution = _label_value("Distribution policy")
        if distribution:
            d = distribution.lower()
            distribution = "accumulating" if "accum" in d else ("distributing" if "distrib" in d else distribution)

        domicile = _label_value("Fund domicile", "Domicile")
        currency = _label_value("Fund currency")
        asset_class = _label_value("Asset class")

        return ETFInfo(
            isin=isin,
            ticker=None,
            name=name,
            ter_bps=ter_bps,
            aum_chf=aum,
            domicile=domicile,
            replication=replication,
            distribution=distribution,
            fund_currency=currency,
            asset_class=asset_class,
            region=None,
            source="justetf",
        )

    # ------------------------------------------------------------------ #
    def lookup_isin(self, isin: str) -> ETFInfo:
        if not isin or not isin.strip():
            raise SymbolNotFound("justetf: leere ISIN")
        html = self._http_get(isin.strip())
        return self._parse_profile(html, isin.strip())

    def is_healthy(self) -> bool:
        return self._enabled
