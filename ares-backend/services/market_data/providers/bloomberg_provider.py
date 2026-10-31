"""BloombergProvider — Skelett-Implementation fuer Bloomberg Server API (blpapi).

Phase 5 von SMI-1988 + Sub-Anlageklassen-Sprint (2026-06-09).

Bloomberg-Daten sind die fachliche Gold-Quelle fuer Sub-Anlageklassen, die
yfinance/Stooq nicht historisch tief abdecken (SMI ab 1988, MSCI EM Index
ab 1988, Bloomberg Global Aggregate ab 1990, etc.). Dieser Provider ist
heute ein STUB: er existiert damit der symbol_catalog Bloomberg-Symbole
dokumentiert auflisten kann und damit konkrete Aktivierung nur die
blpapi-Installation + Lizenz-Sitzung braucht.

Aktivierung (durch Berater oder Hosting-Betreiber):
  1. Bloomberg-Lizenz beschaffen (Terminal-User / Server-API)
  2. `pip install blpapi` (Bloomberg-eigene Wheel, nicht im PyPI-Index;
     siehe https://www.bloomberg.com/professional/support/api-library/)
  3. Bloomberg-Terminal oder B-PIPE-Connection laufen
  4. Provider in services/market_data/factory.py registrieren (oder via
     Entry-Point-Discovery in einem externen Paket)

Architektur-Hinweis: Der Backfill-Service (sub_asset_backfill.py) ruft
diesen Provider direkt mit dem aus symbol_catalog kommenden Bloomberg-
Symbol auf (z.B. "SMI Index", "SPXT Index"). Symbole sind in der
Bloomberg-Konvention (Ticker + Yellow-Key) gehalten.
"""
from __future__ import annotations

import logging
from datetime import date as Date
from decimal import Decimal
from typing import Any, Optional

from ..base import Bar, MarketDataProvider, ProductInfo
from ..exceptions import ProviderError, SymbolNotFound

logger = logging.getLogger(__name__)


BLPAPI_INSTALL_HINT = (
    "BloombergProvider braucht das `blpapi`-Paket (Bloomberg-eigene Wheel). "
    "Installation: 'pip install --index-url=https://blpapi.bloomberg.com/repository/releases/python/simple/ blpapi'. "
    "Zusaetzlich braucht es einen laufenden Bloomberg-Terminal oder B-PIPE-Service. "
    "Siehe https://www.bloomberg.com/professional/support/api-library/"
)


class BloombergProvider(MarketDataProvider):
    """Bloomberg-Server-API-Provider (Skelett, blpapi-Lazy-Import).

    Falls blpapi nicht installiert ist, wirft jeder Datenabruf einen
    klaren ProviderError mit Installations-Hinweis. is_healthy() liefert
    False, sodass der Aggregator den Provider in der Cascade automatisch
    ueberspringt — keine Crashes wenn Bloomberg nicht verfuegbar ist.
    """

    name = "bloomberg"

    def __init__(self, host: str = "localhost", port: int = 8194) -> None:
        self._host = host
        self._port = port
        self._session: Any = None  # blpapi.Session-Instanz wenn aktiv
        self._blpapi: Any = None

    def _blpapi_module(self) -> Any:
        """Lazy-Import von blpapi. ProviderError wenn nicht installiert."""
        if self._blpapi is None:
            try:
                import blpapi  # type: ignore[import-not-found]
            except ImportError as exc:
                raise ProviderError(
                    f"blpapi nicht installiert: {exc}. {BLPAPI_INSTALL_HINT}"
                ) from exc
            self._blpapi = blpapi
        return self._blpapi

    def _session_obj(self) -> Any:
        """Lazy-Start einer blpapi-Session.

        Sessions sind teuer aufzubauen — wir cachen einmalig pro Provider-
        Instanz. Bei Session-Fehler wirft ProviderError.
        """
        if self._session is not None:
            return self._session
        blpapi = self._blpapi_module()
        try:
            session_opts = blpapi.SessionOptions()
            session_opts.setServerHost(self._host)
            session_opts.setServerPort(self._port)
            session = blpapi.Session(session_opts)
            if not session.start():
                raise ProviderError(
                    f"Bloomberg-Session-Start fehlgeschlagen "
                    f"({self._host}:{self._port}). Terminal/B-PIPE laeuft?"
                )
            if not session.openService("//blp/refdata"):
                raise ProviderError("Bloomberg-Refdata-Service nicht erreichbar.")
            self._session = session
            return session
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(
                f"Bloomberg-Session konnte nicht gestartet werden: {exc}"
            ) from exc

    # ------------------------------------------------------------------ #
    # MarketDataProvider-Interface
    # ------------------------------------------------------------------ #

    def is_healthy(self) -> bool:
        """True nur wenn blpapi installiert UND Session start moeglich.

        Defensiv: blpapi-ImportError oder Session-Fehler -> False, damit
        Aggregator den Provider in der Cascade ueberspringt.
        """
        try:
            self._blpapi_module()
            # Session-Start NICHT in is_healthy ausloesen — zu teuer und
            # Bloomberg-Limit sind teuer. Nur Import-Check reicht als
            # 'verfuegbar'-Signal.
            return True
        except ProviderError:
            return False

    def get_eod(self, symbol: str, on_date: Date) -> Bar:
        """End-of-Day Bar via Bloomberg ReferenceDataRequest.

        Bloomberg-Format: 'SMI Index', 'AAPL US Equity', 'CHFUSD Curncy'.
        Fields: PX_LAST, PX_OPEN, PX_HIGH, PX_LOW, CRNCY.
        """
        # TODO Phase 5b: blpapi-Implementation. Heute Stub -> SymbolNotFound
        # falls der Provider gar nicht erreichbar ist, ProviderError sonst.
        raise SymbolNotFound(
            f"BloombergProvider get_eod ist Stub. Symbol={symbol!r}, date={on_date}. "
            f"Implementation folgt in Phase 5b nach blpapi-Aktivierung."
        )

    def get_history(self, symbol: str, start: Date, end: Date) -> list[Bar]:
        """Tagesserie via Bloomberg HistoricalDataRequest.

        Bloomberg liefert business-day-Reihen mit Fields PX_LAST + PX_VOLUME.
        Adjusted Close (TR) ueber CUST_TRR_RETURN_HOLDING_PER mit Override
        DAILY-Periodicity.
        """
        # TODO Phase 5b: blpapi-Implementation. Heute Stub.
        raise SymbolNotFound(
            f"BloombergProvider get_history ist Stub. Symbol={symbol!r}, "
            f"range={start}..{end}. Implementation folgt in Phase 5b."
        )

    def lookup_isin(self, isin: str) -> ProductInfo:
        """Reverse-ISIN-Lookup via Bloomberg ID-Search.

        Bloomberg unterstuetzt ID-Lookup via /isin/<ISIN>-Override.
        """
        # TODO Phase 5b: blpapi-Implementation. Heute Stub.
        raise SymbolNotFound(
            f"BloombergProvider lookup_isin ist Stub. ISIN={isin!r}. "
            f"Implementation folgt in Phase 5b."
        )

    def __del__(self) -> None:
        """Bloomberg-Session sauber schliessen wenn Provider zerstoert wird."""
        if self._session is not None:
            try:
                self._session.stop()
            except Exception:  # noqa: BLE001 - destructor swallow
                pass
