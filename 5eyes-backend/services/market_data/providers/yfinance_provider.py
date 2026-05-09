"""YFinanceProvider — Yahoo Finance via `yfinance` Library.

Primary-Provider fuer Tier 1 (Solo-Berater). Gratis, breite Coverage,
Tagesdaten + Intraday.

Ueberlegen:
- yfinance liefert DataFrames; wir konvertieren zu Bar/ProductInfo
- Yahoo erwartet Boersen-Suffixe (UBSG.SW fuer SIX); siehe _ticker_suffix
- 404/leeres Resultat -> SymbolNotFound
- Netzwerk/Parse-Fehler -> ProviderError
- Reverse-ISIN-Lookup gibt's bei yfinance nicht direkt -> Phase 8 (OpenFIGI)
- yfinance ruft im Hintergrund eigene Caches auf — wir cachen nicht doppelt

Risiko (Plan §10):
- Yahoo TOS verbietet kommerzielle Nutzung. Praktisch null Risiko fuer
  einen Einzel-Berater. Fallback in P3+ falls API blockt.
"""
from __future__ import annotations

import logging
from datetime import date as Date
from datetime import timedelta
from decimal import Decimal
from typing import Any

from ..base import Bar, MarketDataProvider, ProductInfo
from ..exceptions import ProviderError, RateLimitError, SymbolNotFound
from ._ticker_suffix import yahoo_ticker

logger = logging.getLogger(__name__)


class YFinanceProvider(MarketDataProvider):
    """Provider auf Basis der yfinance-Library."""

    name = "yfinance"

    def __init__(self) -> None:
        # yfinance importieren wir lazy, damit Tests ohne yfinance laufen
        # koennen (mocked).
        self._yf = None

    def _yfinance(self) -> Any:
        """Lazy-Import von yfinance. Wirft ProviderError wenn nicht installiert."""
        if self._yf is None:
            try:
                import yfinance as yf  # type: ignore[import-not-found]
            except ImportError as exc:
                raise ProviderError(f"yfinance nicht installiert: {exc}") from exc
            self._yf = yf
        return self._yf

    # ------------------------------------------------------------------ #
    def _ticker_obj(self, symbol: str, exchange: str | None = None):
        yf = self._yfinance()
        sym = yahoo_ticker(symbol, exchange)
        return yf.Ticker(sym)

    @staticmethod
    def _is_rate_limit_exc(exc: BaseException) -> bool:
        """Heuristik fuer yfinance-Rate-Limit-Fehler (verschiedene Klassen-Namen
        je yfinance-Version).
        """
        cls_name = exc.__class__.__name__
        msg = str(exc).lower()
        return (
            "ratelimit" in cls_name.lower()
            or "rate limit" in msg
            or "too many requests" in msg
        )

    @staticmethod
    def _row_to_bar(symbol: str, on_date: Date, row: Any, currency: str) -> Bar:
        """Pandas-Row -> Bar. Defensive gegen NaN."""
        # yfinance liefert Spalten 'Open','High','Low','Close','Adj Close','Volume'
        try:
            open_ = Decimal(str(float(row["Open"])))
            high = Decimal(str(float(row["High"])))
            low = Decimal(str(float(row["Low"])))
            close = Decimal(str(float(row["Close"])))
        except (KeyError, ValueError, TypeError) as exc:
            raise ProviderError(f"yfinance row malformed for {symbol}: {exc}") from exc
        adj = None
        if "Adj Close" in row and row["Adj Close"] == row["Adj Close"]:  # NaN check
            try:
                adj = Decimal(str(float(row["Adj Close"])))
            except (ValueError, TypeError):
                adj = None
        vol = None
        if "Volume" in row and row["Volume"] == row["Volume"]:
            try:
                vol = int(row["Volume"])
            except (ValueError, TypeError):
                vol = None
        return Bar(
            symbol=symbol, date=on_date,
            open=open_, high=high, low=low, close=close,
            currency=currency or "USD",
            volume=vol, adjusted_close=adj,
            source="yfinance",
        )

    # ------------------------------------------------------------------ #
    def get_eod(self, symbol: str, on_date: Date) -> Bar:
        """Letzter Handelstag <= on_date.

        yfinance.history(start, end) ist exklusiv bezueglich `end`. Daher
        end = on_date + 1 Tag, damit on_date inkludiert ist. Wenn Sonntag,
        liefert yfinance den vorhergehenden Freitag (yfinance fuellt nicht).
        Fallback: bis zu 7 Tage zurueckschauen.
        """
        ticker = self._ticker_obj(symbol)
        try:
            df = ticker.history(
                start=on_date - timedelta(days=7),
                end=on_date + timedelta(days=1),
                auto_adjust=False,
                actions=False,
            )
        except Exception as exc:  # noqa: BLE001
            if self._is_rate_limit_exc(exc):
                raise RateLimitError(f"yfinance rate-limited: {exc}") from exc
            raise ProviderError(f"yfinance.history failed for {symbol}: {exc}") from exc
        if df is None or df.empty:
            raise SymbolNotFound(f"yfinance: keine Daten fuer {symbol} (Datum {on_date})")
        # Letzte Zeile = letzter Handelstag <= on_date
        last_row = df.iloc[-1]
        last_date = df.index[-1].date() if hasattr(df.index[-1], "date") else on_date
        currency = self._currency_from_ticker(ticker)
        return self._row_to_bar(symbol, last_date, last_row, currency)

    def get_history(self, symbol: str, start: Date, end: Date) -> list[Bar]:
        """Bars im Bereich [start, end] inklusive."""
        if end < start:
            return []
        ticker = self._ticker_obj(symbol)
        try:
            df = ticker.history(
                start=start, end=end + timedelta(days=1),
                auto_adjust=False, actions=False,
            )
        except Exception as exc:  # noqa: BLE001
            if self._is_rate_limit_exc(exc):
                raise RateLimitError(f"yfinance rate-limited: {exc}") from exc
            raise ProviderError(f"yfinance.history failed for {symbol}: {exc}") from exc
        if df is None or df.empty:
            return []
        currency = self._currency_from_ticker(ticker)
        bars: list[Bar] = []
        for idx, row in df.iterrows():
            d = idx.date() if hasattr(idx, "date") else start
            bars.append(self._row_to_bar(symbol, d, row, currency))
        return bars

    def lookup_isin(self, isin: str) -> ProductInfo:
        """yfinance kann ISIN -> Ticker NICHT direkt — Reverse-Lookup ist
        nicht Teil dieser API. Phase 8 (OpenFIGI) liefert das.

        Wir koennten via yfinance.Search / yf.utils.get_isin auf Ticker
        kommen, aber das ist undokumentiert und brueckchig. Saubere
        Trennung: yfinance liefert Bars, OpenFIGI liefert ID-Mapping.
        """
        raise SymbolNotFound(
            f"yfinance unterstuetzt keine ISIN-Suche; "
            f"nutze OpenFIGIProvider fuer ISIN '{isin}'"
        )

    # ------------------------------------------------------------------ #
    @staticmethod
    def _currency_from_ticker(ticker: Any) -> str:
        """Best-effort Waehrung aus ticker.info / ticker.fast_info."""
        try:
            fast = getattr(ticker, "fast_info", None)
            if fast is not None:
                cur = getattr(fast, "currency", None)
                if cur:
                    return str(cur).upper()
        except Exception:  # noqa: BLE001
            pass
        try:
            info = getattr(ticker, "info", None) or {}
            cur = info.get("currency") if isinstance(info, dict) else None
            if cur:
                return str(cur).upper()
        except Exception:  # noqa: BLE001
            pass
        return "USD"  # konservativer Default

    def get_product_info_by_ticker(self, ticker_symbol: str, exchange: str | None = None) -> ProductInfo:
        """Bonus-Methode: liefert ProductInfo via Ticker (nicht im Interface).

        Wird vom OpenFIGI-Provider in Phase 8 als Anreicherung genutzt.
        """
        t = self._ticker_obj(ticker_symbol, exchange)
        try:
            info = getattr(t, "info", None) or {}
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"yfinance ticker info failed for {ticker_symbol}: {exc}") from exc
        if not isinstance(info, dict) or not info:
            raise SymbolNotFound(f"yfinance: kein info fuer {ticker_symbol}")
        return ProductInfo(
            isin=info.get("isin") or None,
            ticker=info.get("symbol") or ticker_symbol,
            name=info.get("longName") or info.get("shortName") or None,
            exchange=info.get("exchange") or None,
            currency=(info.get("currency") or "").upper() or None,
            asset_class=info.get("quoteType") or None,
            country=info.get("country") or None,
            source="yfinance",
        )
