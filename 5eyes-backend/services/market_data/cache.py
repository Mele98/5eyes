"""Smart Cache fuer den MarketDataAggregator (Phase 6).

Wrappt einen MarketDataAggregator und cached jede Antwort in der
SQLite-Tabelle `market_data_cache`. TTL pro Datentyp:
  - EOD-Preise:  24h
  - History:     7 Tage
  - ID-Mapping:  180 Tage (ISIN-Mapping aendert sich praktisch nie)

Aufrufe:
    cached = CachedAggregator(base_aggregator, session_factory)
    bar = cached.get_eod("UBSG.SW", date(2026, 5, 8))   # 1. Call -> Provider
    bar = cached.get_eod("UBSG.SW", date(2026, 5, 8))   # 2. Call -> Cache

Defensive: bei korruptem JSON oder DB-Fehler wird der Cache umgangen
(kein Crash). Worst-case ist ein Provider-Roundtrip extra.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import date as Date
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, ContextManager

from .aggregator import MarketDataAggregator
from .base import Bar, ProductInfo

logger = logging.getLogger(__name__)


# TTL-Defaults pro cache_kind. Wird via __init__ ueberschreibbar.
DEFAULT_TTL_SECONDS: dict[str, int] = {
    "eod": 24 * 3600,
    "history": 7 * 24 * 3600,
    "isin": 180 * 24 * 3600,
}


# --------------------------------------------------------------------------- #
# JSON-Serialisierung fuer Bar / ProductInfo
# --------------------------------------------------------------------------- #
def _bar_to_dict(bar: Bar) -> dict:
    return {
        "symbol": bar.symbol,
        "date": bar.date.isoformat(),
        "open": str(bar.open),
        "high": str(bar.high),
        "low": str(bar.low),
        "close": str(bar.close),
        "currency": bar.currency,
        "volume": bar.volume,
        "adjusted_close": str(bar.adjusted_close) if bar.adjusted_close is not None else None,
        "source": bar.source,
    }


def _dict_to_bar(d: dict) -> Bar:
    return Bar(
        symbol=str(d["symbol"]),
        date=Date.fromisoformat(d["date"]),
        open=Decimal(d["open"]),
        high=Decimal(d["high"]),
        low=Decimal(d["low"]),
        close=Decimal(d["close"]),
        currency=str(d["currency"]),
        volume=int(d["volume"]) if d.get("volume") is not None else None,
        adjusted_close=Decimal(d["adjusted_close"]) if d.get("adjusted_close") is not None else None,
        source=str(d.get("source") or "unknown"),
    )


def _product_to_dict(p: ProductInfo) -> dict:
    return {
        "isin": p.isin,
        "ticker": p.ticker,
        "name": p.name,
        "exchange": p.exchange,
        "currency": p.currency,
        "asset_class": p.asset_class,
        "country": p.country,
        "figi": p.figi,
        "source": p.source,
    }


def _dict_to_product(d: dict) -> ProductInfo:
    return ProductInfo(
        isin=d.get("isin"),
        ticker=d.get("ticker"),
        name=d.get("name"),
        exchange=d.get("exchange"),
        currency=d.get("currency"),
        asset_class=d.get("asset_class"),
        country=d.get("country"),
        figi=d.get("figi"),
        source=str(d.get("source") or "unknown"),
    )


# --------------------------------------------------------------------------- #
# Cache-Key
# --------------------------------------------------------------------------- #
def _hash_args(args: dict) -> str:
    """Stabiler SHA-256 ueber JSON-Args (sortierte Keys)."""
    payload = json.dumps(args, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_expired(expires_at_iso: str) -> bool:
    try:
        expires = datetime.fromisoformat(expires_at_iso)
    except ValueError:
        return True
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires <= datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# CachedAggregator
# --------------------------------------------------------------------------- #
class CachedAggregator:
    """SQLite-basierte Cache-Schicht ueber einem MarketDataAggregator.

    `session_factory` ist ein Callable, das einen Sessions-ContextManager
    liefert (z.B. `lambda: SessionLocal()`). Der Cache eroeffnet pro
    Operation eine eigene Session, comitted und schliesst sie.
    """

    def __init__(
        self,
        base: MarketDataAggregator,
        session_factory: Callable[[], ContextManager[Any]] | Callable[[], Any],
        ttl_seconds: dict[str, int] | None = None,
    ) -> None:
        self._base = base
        self._session_factory = session_factory
        merged = dict(DEFAULT_TTL_SECONDS)
        if ttl_seconds:
            merged.update(ttl_seconds)
        self._ttl = merged

    @property
    def base(self) -> MarketDataAggregator:
        return self._base

    @property
    def ttl_seconds(self) -> dict[str, int]:
        return dict(self._ttl)

    # ------------------------------------------------------------------ #
    def _open_session(self):
        """Bekommt entweder einen Generator oder ein Session-Objekt."""
        return self._session_factory()

    def _read_cache(self, kind: str, key: str) -> Any | None:
        """Liefert das deserialisierte value oder None bei Miss/expired."""
        from models.market_data_cache import MarketDataCacheEntry  # lazy
        try:
            session = self._open_session()
        except Exception as exc:  # noqa: BLE001
            logger.warning("cache: session_factory failed (%s)", exc)
            return None
        try:
            entry = (
                session.query(MarketDataCacheEntry)
                .filter(
                    MarketDataCacheEntry.cache_kind == kind,
                    MarketDataCacheEntry.cache_key == key,
                )
                .first()
            )
            if entry is None:
                return None
            if _is_expired(entry.expires_at):
                return None
            try:
                return json.loads(entry.value_json)
            except (ValueError, TypeError) as exc:
                logger.warning("cache: corrupt JSON for kind=%s (%s)", kind, exc)
                return None
        finally:
            try:
                session.close()
            except Exception:  # noqa: BLE001
                pass

    def _write_cache(self, kind: str, key: str, value: Any) -> None:
        """Upsert in market_data_cache. Defensive: schlucke alle DB-Fehler."""
        from models.market_data_cache import MarketDataCacheEntry  # lazy
        ttl = int(self._ttl.get(kind, 0) or 0)
        if ttl <= 0:
            return
        try:
            payload = json.dumps(value, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            logger.warning("cache: cannot serialize kind=%s (%s)", kind, exc)
            return
        now_iso = _now_utc_iso()
        expires_iso = (datetime.now(timezone.utc) + timedelta(seconds=ttl)).isoformat()
        try:
            session = self._open_session()
        except Exception as exc:  # noqa: BLE001
            logger.warning("cache: session_factory failed on write (%s)", exc)
            return
        try:
            entry = (
                session.query(MarketDataCacheEntry)
                .filter(
                    MarketDataCacheEntry.cache_kind == kind,
                    MarketDataCacheEntry.cache_key == key,
                )
                .first()
            )
            if entry is None:
                entry = MarketDataCacheEntry(
                    cache_kind=kind, cache_key=key,
                    value_json=payload,
                    fetched_at=now_iso, expires_at=expires_iso,
                )
                session.add(entry)
            else:
                entry.value_json = payload
                entry.fetched_at = now_iso
                entry.expires_at = expires_iso
            session.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("cache: write failed (%s)", exc)
            try:
                session.rollback()
            except Exception:  # noqa: BLE001
                pass
        finally:
            try:
                session.close()
            except Exception:  # noqa: BLE001
                pass

    def invalidate(self, kind: str | None = None) -> int:
        """Loescht Cache-Eintraege. None = alle. Liefert Anzahl geloeschter."""
        from models.market_data_cache import MarketDataCacheEntry  # lazy
        try:
            session = self._open_session()
        except Exception:  # noqa: BLE001
            return 0
        try:
            q = session.query(MarketDataCacheEntry)
            if kind is not None:
                q = q.filter(MarketDataCacheEntry.cache_kind == kind)
            count = q.count()
            q.delete(synchronize_session=False)
            session.commit()
            return int(count)
        except Exception as exc:  # noqa: BLE001
            logger.warning("cache invalidate failed (%s)", exc)
            try:
                session.rollback()
            except Exception:  # noqa: BLE001
                pass
            return 0
        finally:
            try:
                session.close()
            except Exception:  # noqa: BLE001
                pass

    def purge_expired(self) -> int:
        """Entfernt abgelaufene Eintraege; ruft idealerweise ein Cron auf."""
        from models.market_data_cache import MarketDataCacheEntry  # lazy
        try:
            session = self._open_session()
        except Exception:  # noqa: BLE001
            return 0
        try:
            now_iso = _now_utc_iso()
            q = session.query(MarketDataCacheEntry).filter(
                MarketDataCacheEntry.expires_at <= now_iso
            )
            count = q.count()
            q.delete(synchronize_session=False)
            session.commit()
            return int(count)
        except Exception as exc:  # noqa: BLE001
            logger.warning("cache purge failed (%s)", exc)
            return 0
        finally:
            try:
                session.close()
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------ #
    def get_eod(self, symbol: str, on_date: Date) -> Bar:
        key = _hash_args({"op": "eod", "symbol": symbol, "date": on_date.isoformat()})
        cached = self._read_cache("eod", key)
        if cached is not None:
            try:
                return _dict_to_bar(cached)
            except (KeyError, ValueError, TypeError) as exc:
                logger.warning("cache: corrupt eod entry (%s)", exc)
        bar = self._base.get_eod(symbol, on_date)
        self._write_cache("eod", key, _bar_to_dict(bar))
        return bar

    def get_history(self, symbol: str, start: Date, end: Date) -> list[Bar]:
        key = _hash_args({
            "op": "history", "symbol": symbol,
            "start": start.isoformat(), "end": end.isoformat(),
        })
        cached = self._read_cache("history", key)
        if isinstance(cached, list):
            try:
                return [_dict_to_bar(item) for item in cached]
            except (KeyError, ValueError, TypeError) as exc:
                logger.warning("cache: corrupt history entry (%s)", exc)
        bars = self._base.get_history(symbol, start, end)
        self._write_cache("history", key, [_bar_to_dict(b) for b in bars])
        return bars

    def lookup_isin(self, isin: str) -> ProductInfo:
        key = _hash_args({"op": "isin", "isin": isin})
        cached = self._read_cache("isin", key)
        if cached is not None:
            try:
                return _dict_to_product(cached)
            except (KeyError, ValueError, TypeError) as exc:
                logger.warning("cache: corrupt isin entry (%s)", exc)
        info = self._base.lookup_isin(isin)
        self._write_cache("isin", key, _product_to_dict(info))
        return info
