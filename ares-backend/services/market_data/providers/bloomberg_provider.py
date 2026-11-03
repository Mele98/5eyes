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

Fail-closed (BBG-1, Audit 2026-11/06): Ohne ``blpapi``, ohne Terminal bzw.
Session oder ohne Refdata-Service wirft jede Datenmethode
``ProviderUnavailableError`` mit eindeutigem ``code`` (nie ``SymbolNotFound``).
``is_healthy()`` versucht einen echten Session-Start mit kurzem Connect-
Timeout und cached das Ergebnis (TTL). Der Provider ist ``authoritative``:
faellt er aus, faellt die Aggregator-Kaskade NICHT still auf Gratisquellen
zurueck. Der echte Request-Aufbau (ReferenceData/HistoricalData) folgt in
BBG-3; bis dahin meldet eine stehende Session
``BLOOMBERG_REQUEST_NOT_IMPLEMENTED``.

Architektur-Hinweis: Der Backfill-Service (sub_asset_backfill.py) ruft
diesen Provider direkt mit dem aus symbol_catalog kommenden Bloomberg-
Symbol auf (z.B. "SMI Index", "SPXT Index"). Symbole sind in der
Bloomberg-Konvention (Ticker + Yellow-Key) gehalten.
"""
from __future__ import annotations

import logging
import time
from datetime import date as Date
from typing import Any

from ..base import Bar, MarketDataProvider, ProductInfo
from ..exceptions import ProviderUnavailableError

logger = logging.getLogger(__name__)


BLPAPI_INSTALL_HINT = (
    "BloombergProvider braucht das `blpapi`-Paket (Bloomberg-eigene Wheel). "
    "Installation: 'pip install --index-url=https://blpapi.bloomberg.com/repository/releases/python/simple/ blpapi'. "
    "Zusaetzlich braucht es einen laufenden Bloomberg-Terminal oder B-PIPE-Service. "
    "Siehe https://www.bloomberg.com/professional/support/api-library/"
)

# Maschinenlesbare Gruende (BBG-1). Der vollstaendige Fehlerkatalog mit
# HTTP-Mapping folgt in BBG-9.
BLOOMBERG_NOT_INSTALLED = "BLOOMBERG_NOT_INSTALLED"
BLOOMBERG_SESSION_UNAVAILABLE = "BLOOMBERG_SESSION_UNAVAILABLE"
BLOOMBERG_SERVICE_UNAVAILABLE = "BLOOMBERG_SERVICE_UNAVAILABLE"
BLOOMBERG_REQUEST_NOT_IMPLEMENTED = "BLOOMBERG_REQUEST_NOT_IMPLEMENTED"

DEFAULT_CONNECT_TIMEOUT_MS = 2000
DEFAULT_HEALTH_TTL_SECONDS = 60.0


class BloombergProvider(MarketDataProvider):
    """Bloomberg-API-Provider (Skelett, blpapi-Lazy-Import, fail-closed)."""

    name = "bloomberg"
    authoritative = True

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8194,
        *,
        connect_timeout_ms: int = DEFAULT_CONNECT_TIMEOUT_MS,
        health_ttl_seconds: float = DEFAULT_HEALTH_TTL_SECONDS,
    ) -> None:
        self._host = host
        self._port = port
        self._connect_timeout_ms = max(1, int(connect_timeout_ms))
        self._health_ttl_seconds = max(0.0, float(health_ttl_seconds))
        self._session: Any = None  # blpapi.Session-Instanz wenn aktiv
        self._blpapi: Any = None
        # (Ergebnis, monotone Ablaufzeit) des letzten Health-Checks
        self._health_cache: tuple[bool, float] | None = None
        # Letzter Verfuegbarkeitsfehler; der Aggregator reicht ihn mit Code
        # weiter, wenn er den Provider wegen is_healthy()=False nicht ruft.
        self.last_unavailable_error: ProviderUnavailableError | None = None

    def _unavailable(self, code: str, message: str) -> ProviderUnavailableError:
        return ProviderUnavailableError(f"[{code}] {message}", code=code, provider=self.name)

    def _blpapi_module(self) -> Any:
        """Lazy-Import von blpapi. ProviderUnavailableError wenn nicht installiert."""
        if self._blpapi is None:
            try:
                import blpapi  # type: ignore[import-not-found]
            except ImportError as exc:
                raise self._unavailable(
                    BLOOMBERG_NOT_INSTALLED,
                    f"blpapi nicht installiert: {exc}. {BLPAPI_INSTALL_HINT}",
                ) from exc
            self._blpapi = blpapi
        return self._blpapi

    @staticmethod
    def _stop_quietly(session: Any) -> None:
        try:
            session.stop()
        except Exception:  # noqa: BLE001
            pass

    def _session_obj(self) -> Any:
        """Lazy-Start einer blpapi-Session mit kurzem Connect-Timeout.

        Sessions sind teuer aufzubauen und werden pro Provider-Instanz
        gecacht. Jeder Fehler -> ProviderUnavailableError mit Code.
        """
        if self._session is not None:
            return self._session
        blpapi = self._blpapi_module()
        session: Any = None
        try:
            session_opts = blpapi.SessionOptions()
            session_opts.setServerHost(self._host)
            session_opts.setServerPort(self._port)
            if hasattr(session_opts, "setConnectTimeout"):
                session_opts.setConnectTimeout(self._connect_timeout_ms)
            session = blpapi.Session(session_opts)
            if not session.start():
                raise self._unavailable(
                    BLOOMBERG_SESSION_UNAVAILABLE,
                    f"Bloomberg-Session-Start fehlgeschlagen ({self._host}:{self._port}). "
                    "Terminal/B-PIPE laeuft?",
                )
            if not session.openService("//blp/refdata"):
                raise self._unavailable(
                    BLOOMBERG_SERVICE_UNAVAILABLE,
                    "Bloomberg-Refdata-Service nicht erreichbar.",
                )
            self._session = session
            return session
        except ProviderUnavailableError:
            if session is not None:
                self._stop_quietly(session)
            raise
        except Exception as exc:  # noqa: BLE001
            if session is not None:
                self._stop_quietly(session)
            raise self._unavailable(
                BLOOMBERG_SESSION_UNAVAILABLE,
                f"Bloomberg-Session konnte nicht gestartet werden: {exc}",
            ) from exc

    def _mark_unhealthy(self, exc: ProviderUnavailableError) -> None:
        """Nach einem Fehler: Session verwerfen, bis TTL-Ablauf ungesund."""
        self.last_unavailable_error = exc
        if self._session is not None:
            self._stop_quietly(self._session)
            self._session = None
        self._health_cache = (False, time.monotonic() + self._health_ttl_seconds)

    def _require_session(self) -> Any:
        try:
            return self._session_obj()
        except ProviderUnavailableError as exc:
            self._mark_unhealthy(exc)
            raise

    def _not_implemented(self, operation: str) -> ProviderUnavailableError:
        exc = self._unavailable(
            BLOOMBERG_REQUEST_NOT_IMPLEMENTED,
            f"Bloomberg {operation}: Request-Aufbau ist noch nicht implementiert (BBG-3). "
            "Keine Daten geliefert.",
        )
        self._mark_unhealthy(exc)
        return exc

    # ------------------------------------------------------------------ #
    # MarketDataProvider-Interface
    # ------------------------------------------------------------------ #

    def is_healthy(self) -> bool:
        """True nur, wenn eine Session mit Refdata-Service tatsaechlich steht.

        Versucht einen echten Session-Start (Connect-Timeout
        ``connect_timeout_ms``). Das Ergebnis wird ``health_ttl_seconds``
        gecacht, damit nicht jeder Aufruf eine Verbindung aufbaut.
        """
        now = time.monotonic()
        if self._health_cache is not None and now < self._health_cache[1]:
            return self._health_cache[0]
        try:
            self._session_obj()
            healthy = True
            self.last_unavailable_error = None
        except ProviderUnavailableError as exc:
            logger.info("Bloomberg nicht verfuegbar: %s", exc)
            healthy = False
            self.last_unavailable_error = exc
        self._health_cache = (healthy, now + self._health_ttl_seconds)
        return healthy

    def get_eod(self, symbol: str, on_date: Date) -> Bar:
        """End-of-Day Bar via Bloomberg ReferenceDataRequest (BBG-3).

        Bloomberg-Format: 'SMI Index', 'AAPL US Equity', 'CHFUSD Curncy'.
        """
        self._require_session()
        raise self._not_implemented(f"get_eod({symbol!r}, {on_date})")

    def get_history(self, symbol: str, start: Date, end: Date) -> list[Bar]:
        """Tagesserie via Bloomberg HistoricalDataRequest (BBG-3)."""
        self._require_session()
        raise self._not_implemented(f"get_history({symbol!r}, {start}..{end})")

    def lookup_isin(self, isin: str) -> ProductInfo:
        """Reverse-ISIN-Lookup via Bloomberg (BBG-3)."""
        self._require_session()
        raise self._not_implemented(f"lookup_isin({isin!r})")

    def __del__(self) -> None:
        """Bloomberg-Session sauber schliessen wenn Provider zerstoert wird."""
        if getattr(self, "_session", None) is not None:
            self._stop_quietly(self._session)
