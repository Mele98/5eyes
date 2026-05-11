from __future__ import annotations

import logging
import time
from io import StringIO
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from urllib.parse import quote
from urllib.request import urlopen

import csv

from sqlalchemy.orm import Session

from config import settings
from database import SessionLocal, new_uuid
from models.review import PriceHistory, Product
from services.market_data_stack import get_market_data_provider_roles, get_market_data_setup_status
from services.product_market_data import (
    is_market_mapped,
    lookup_symbol_for_provider,
    provider_market_warning,
    resolve_market_profile,
)
from services.twelvedata_client import fetch_twelvedata_latest_prices
from services.market_data.legacy_compat import fetch_latest_prices_via_aggregator

try:
    import yfinance as yf
except ImportError:  # pragma: no cover
    yf = None

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
except ImportError:  # pragma: no cover
    BackgroundScheduler = None
    CronTrigger = None


logger = logging.getLogger(__name__)
PRICE_SOURCE = settings.price_refresh_primary_provider
FALLBACK_PRICE_SOURCE = settings.price_refresh_fallback_provider
scheduler = None
_last_refresh_summary: dict[str, Any] | None = None


@dataclass(slots=True)
class PricePoint:
    price_date: str
    price_rappen: int
    currency: str
    source: str = PRICE_SOURCE


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def parse_iso_date(value: str | None) -> date | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def resolve_lookup_symbol(product: Product) -> str | None:
    return resolve_market_profile(product).get("lookup_symbol")


def to_rappen(amount: Any) -> int:
    value = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return int(value * 100)


def fetch_latest_price(product: Product) -> PricePoint:
    market_profile = resolve_market_profile(product)
    if market_profile.get("lookup_mode") == "synthetic_par":
        return PricePoint(
            price_date=date.today().isoformat(),
            price_rappen=int(market_profile.get("synthetic_price_rappen") or 100),
            currency=(market_profile.get("currency") or product.currency or "CHF"),
            source="synthetic_par",
        )

    if yf is None:
        raise RuntimeError("yfinance ist nicht installiert. Bitte requirements.txt installieren.")

    lookup_symbol = str(market_profile.get("lookup_symbol") or "").strip() or None
    if not lookup_symbol:
        raise ValueError("Produkt hat weder Symbol noch ISIN")

    last_error: Exception | None = None
    for attempt in range(1, settings.price_refresh_max_attempts + 1):
        try:
            ticker = yf.Ticker(lookup_symbol)
            history = ticker.history(period="5d", interval="1d", auto_adjust=False, actions=False)
            if history is None or history.empty or "Close" not in history:
                raise ValueError(f"Keine Kursdaten für {lookup_symbol} gefunden")

            closes = history["Close"].dropna()
            if closes.empty:
                raise ValueError(f"Keine gültigen Schlusskurse für {lookup_symbol} gefunden")

            last_index = closes.index[-1]
            raw_price = closes.iloc[-1]
            if raw_price is None:
                raise ValueError(f"Ungültiger Schlusskurs für {lookup_symbol}")

            return PricePoint(
                price_date=getattr(last_index, "strftime", lambda x: str(last_index))("%Y-%m-%d"),
                price_rappen=to_rappen(raw_price),
                currency=(product.currency or "CHF"),
            )
        except Exception as exc:
            last_error = exc
            logger.warning(
                "Price fetch attempt %s/%s failed for %s: %s",
                attempt,
                settings.price_refresh_max_attempts,
                lookup_symbol,
                exc,
            )
            if attempt < settings.price_refresh_max_attempts:
                time.sleep(settings.price_refresh_retry_delay_seconds)

    raise RuntimeError(f"Preisabruf für {lookup_symbol} fehlgeschlagen: {last_error}") from last_error


def _download_frame_for_symbol(history: Any, symbol: str) -> Any:
    if history is None or getattr(history, "empty", False):
        raise ValueError(f"Keine Kursdaten fuer {symbol} gefunden")
    columns = getattr(history, "columns", None)
    if columns is None:
        raise ValueError(f"Download-Payload fuer {symbol} enthaelt keine Spalten")
    nlevels = int(getattr(columns, "nlevels", 1) or 1)
    if nlevels <= 1:
        return history
    try:
        if symbol in set(columns.get_level_values(0)):
            return history[symbol]
    except Exception:
        pass
    try:
        if symbol in set(columns.get_level_values(nlevels - 1)):
            return history.xs(symbol, axis=1, level=nlevels - 1)
    except Exception:
        pass
    raise ValueError(f"Ticker {symbol} nicht im Batch-Download enthalten")


def _latest_close_point_from_frame(frame: Any, symbol: str) -> tuple[str, int]:
    closes = frame["Close"].dropna()
    if closes is None or closes.empty:
        raise ValueError(f"Keine gueltigen Schlusskurse fuer {symbol} gefunden")
    last_index = closes.index[-1]
    raw_price = closes.iloc[-1]
    if raw_price is None:
        raise ValueError(f"Ungueltiger Schlusskurs fuer {symbol}")
    return (
        getattr(last_index, "strftime", lambda x: str(last_index))("%Y-%m-%d"),
        to_rappen(raw_price),
    )


def _stooq_symbol(symbol: str) -> str:
    raw = str(symbol or "").strip().lower()
    if not raw:
        raise ValueError("Leeres Symbol fuer Stooq-Fallback")
    if "." in raw or "=" in raw:
        return raw
    return raw + ".us"


def fetch_stooq_price(symbol: str, *, currency: str | None = None) -> PricePoint:
    stooq_symbol = _stooq_symbol(symbol)
    url = f"https://stooq.com/q/l/?s={quote(stooq_symbol, safe='')}&f=sd2t2ohlcvn&e=csv"
    with urlopen(url, timeout=10) as response:
        payload = response.read().decode("utf-8", errors="replace")
    rows = [row for row in csv.reader(StringIO(payload)) if row]
    if not rows or len(rows[-1]) < 6:
        raise ValueError(f"Keine Stooq-Kursdaten fuer {symbol} gefunden")
    last = rows[-1]
    price_date = str(last[1] or "").strip()
    close_value = str(last[5] or "").strip()
    if not price_date or not close_value or close_value == "N/D":
        raise ValueError(f"Keine gueltigen Stooq-Kursdaten fuer {symbol} gefunden")
    return PricePoint(
        price_date=price_date,
        price_rappen=to_rappen(close_value),
        currency=(currency or "CHF"),
        source=FALLBACK_PRICE_SOURCE,
    )


def _fetch_yfinance_symbol_points(symbols: list[str]) -> tuple[dict[str, tuple[str, int, str]], dict[str, str]]:
    if yf is None:
        return {}, {symbol: "yfinance ist nicht installiert. Bitte requirements.txt installieren." for symbol in symbols}
    try:
        history = yf.download(
            tickers=" ".join(symbols),
            period="5d",
            interval="1d",
            auto_adjust=False,
            actions=False,
            threads=False,
            group_by="ticker",
            progress=False,
        )
        symbol_points: dict[str, tuple[str, int, str]] = {}
        symbol_errors: dict[str, str] = {}
        for symbol in symbols:
            try:
                frame = _download_frame_for_symbol(history, symbol)
                price_date, price_rappen = _latest_close_point_from_frame(frame, symbol)
                symbol_points[symbol] = (price_date, price_rappen, "yfinance")
            except Exception as exc:
                symbol_errors[symbol] = str(exc)
        return symbol_points, symbol_errors
    except Exception as exc:
        return {}, {symbol: str(exc) for symbol in symbols}


def _fetch_stooq_symbol_points(
    symbols: list[str],
    *,
    product_by_symbol: dict[str, list[Product]],
) -> tuple[dict[str, tuple[str, int, str]], dict[str, str]]:
    symbol_points: dict[str, tuple[str, int, str]] = {}
    symbol_errors: dict[str, str] = {}
    for symbol in symbols:
        try:
            currency = None
            products = product_by_symbol.get(symbol) or []
            if products:
                currency = products[0].currency
            stooq_point = fetch_stooq_price(symbol, currency=currency)
            symbol_points[symbol] = (stooq_point.price_date, stooq_point.price_rappen, stooq_point.source)
        except Exception as exc:
            symbol_errors[symbol] = str(exc)
    return symbol_points, symbol_errors


def _fetch_twelvedata_symbol_points(symbols: list[str]) -> tuple[dict[str, tuple[str, int, str]], dict[str, str]]:
    try:
        resolved, failures = fetch_twelvedata_latest_prices(symbols)
    except Exception as exc:
        return {}, {symbol: str(exc) for symbol in symbols}
    symbol_points = {
        symbol: (
            str(payload.get("price_date") or ""),
            int(payload.get("price_rappen") or 0),
            str(payload.get("source") or "twelvedata"),
        )
        for symbol, payload in resolved.items()
    }
    symbol_errors = {symbol: str(message) for symbol, message in failures.items()}
    return symbol_points, symbol_errors


def _fetch_aggregator_symbol_points(symbols: list[str]) -> tuple[dict[str, tuple[str, int, str]], dict[str, str]]:
    """P14: Multi-Source-Aggregator-Pfad (yfinance + stooq + alphavantage + ...).

    Drop-in fuer die direkten Provider-Pfade. Wird gewaehlt wenn
    PRICE_REFRESH_PRIMARY_PROVIDER (oder _FALLBACK_) = "aggregator".
    """
    try:
        resolved, failures = fetch_latest_prices_via_aggregator(symbols)
    except Exception as exc:  # noqa: BLE001
        return {}, {symbol: str(exc) for symbol in symbols}
    symbol_points = {
        symbol: (
            str(payload.get("price_date") or ""),
            int(payload.get("price_rappen") or 0),
            str(payload.get("source") or "aggregator"),
        )
        for symbol, payload in resolved.items()
    }
    symbol_errors = {symbol: str(message) for symbol, message in failures.items()}
    return symbol_points, symbol_errors


def _append_market_warning(message: str | None, *warnings: str | None) -> str:
    base = str(message or "").strip() or "Unbekannter Preisfehler"
    seen = {base}
    parts = [base]
    for warning in warnings:
        hint = str(warning or "").strip()
        if not hint or hint in seen:
            continue
        seen.add(hint)
        parts.append(f"Hinweis: {hint}")
    return " ".join(parts)


def _fetch_primary_symbol_points(
    symbols: list[str],
    *,
    product_by_symbol: dict[str, list[Product]],
) -> tuple[dict[str, tuple[str, int, str]], dict[str, str]]:
    provider = str(PRICE_SOURCE or "").strip().lower()
    if provider == "yfinance":
        return _fetch_yfinance_symbol_points(symbols)
    if provider == "twelvedata":
        return _fetch_twelvedata_symbol_points(symbols)
    if provider == "stooq":
        return _fetch_stooq_symbol_points(symbols, product_by_symbol=product_by_symbol)
    if provider == "aggregator":
        return _fetch_aggregator_symbol_points(symbols)
    return {}, {symbol: f"Preisprovider {provider or 'unbekannt'} ist nicht implementiert." for symbol in symbols}


def _fetch_fallback_symbol_points(
    symbols: list[str],
    *,
    product_by_symbol: dict[str, list[Product]],
) -> tuple[dict[str, tuple[str, int, str]], dict[str, str]]:
    provider = str(FALLBACK_PRICE_SOURCE or "").strip().lower()
    if not provider or provider == str(PRICE_SOURCE or "").strip().lower():
        return {}, {}
    if provider == "stooq":
        return _fetch_stooq_symbol_points(symbols, product_by_symbol=product_by_symbol)
    if provider == "yfinance":
        return _fetch_yfinance_symbol_points(symbols)
    if provider == "twelvedata":
        return _fetch_twelvedata_symbol_points(symbols)
    if provider == "aggregator":
        return _fetch_aggregator_symbol_points(symbols)
    return {}, {symbol: f"Fallback-Provider {provider} ist nicht implementiert." for symbol in symbols}


def fetch_latest_prices_batch(products: list[Product]) -> tuple[dict[str, PricePoint], dict[str, dict[str, Any]]]:
    resolved_points: dict[str, PricePoint] = {}
    failures: dict[str, dict[str, Any]] = {}
    primary_symbols: dict[str, list[Product]] = {}
    fallback_symbol_by_product_id: dict[str, str | None] = {}

    for product in products:
        market_profile = resolve_market_profile(product)
        lookup_mode = str(market_profile.get("lookup_mode") or "unmapped")
        identifier_basis = str(market_profile.get("identifier_basis") or "").strip().lower()
        if lookup_mode == "synthetic_par":
            resolved_points[product.id] = PricePoint(
                price_date=date.today().isoformat(),
                price_rappen=int(market_profile.get("synthetic_price_rappen") or 100),
                currency=(product.currency or "CHF"),
                source="synthetic_par",
            )
            continue

        primary_lookup_symbol = lookup_symbol_for_provider(market_profile, PRICE_SOURCE)
        fallback_lookup_symbol = lookup_symbol_for_provider(market_profile, FALLBACK_PRICE_SOURCE)
        fallback_symbol_by_product_id[product.id] = fallback_lookup_symbol
        if primary_lookup_symbol and identifier_basis == "isin":
            failures[product.id] = {
                "product": product,
                "lookup_mode": "direct_isin",
                "lookup_symbol": primary_lookup_symbol,
                "error": "Produkt hat nur ISIN. Fuer Preisfeeds wird ein handelbares Symbol oder explizites externes Mapping benoetigt.",
            }
            continue
        if not primary_lookup_symbol:
            failures[product.id] = {
                "product": product,
                "lookup_mode": lookup_mode,
                "lookup_symbol": None,
                "error": "Produkt hat kein Marktprofil fuer den Preisabruf.",
            }
            continue
        primary_symbols.setdefault(primary_lookup_symbol, []).append(product)

    if not primary_symbols:
        return resolved_points, failures

    symbols = sorted(primary_symbols.keys())
    symbol_points, symbol_errors = _fetch_primary_symbol_points(symbols, product_by_symbol=primary_symbols)

    unresolved_products: list[tuple[Product, str]] = []
    for primary_symbol, mapped_products in primary_symbols.items():
        if primary_symbol in symbol_points:
            continue
        for product in mapped_products:
            unresolved_products.append((product, primary_symbol))

    fallback_symbols: dict[str, list[Product]] = {}
    if unresolved_products:
        for product, _primary_symbol in unresolved_products:
            fallback_lookup_symbol = str(fallback_symbol_by_product_id.get(product.id) or "").strip() or None
            if not fallback_lookup_symbol:
                continue
            fallback_symbols.setdefault(fallback_lookup_symbol, []).append(product)

    fallback_points: dict[str, tuple[str, int, str]] = {}
    fallback_errors: dict[str, str] = {}
    if fallback_symbols:
        fallback_points, fallback_errors = _fetch_fallback_symbol_points(sorted(fallback_symbols.keys()), product_by_symbol=fallback_symbols)
        for symbol, payload in fallback_points.items():
            symbol_points[symbol] = payload
            symbol_errors.pop(symbol, None)
        for symbol, message in fallback_errors.items():
            symbol_errors[symbol] = symbol_errors.get(symbol) or message

    for primary_symbol, mapped_products in primary_symbols.items():
        if primary_symbol in symbol_points:
            price_date, price_rappen, price_source = symbol_points[primary_symbol]
            for product in mapped_products:
                resolved_points[product.id] = PricePoint(
                    price_date=price_date,
                    price_rappen=price_rappen,
                    currency=(product.currency or "CHF"),
                    source=price_source,
                )
            continue

        for product in mapped_products:
            fallback_lookup_symbol = str(fallback_symbol_by_product_id.get(product.id) or "").strip() or None
            if fallback_lookup_symbol and fallback_lookup_symbol in fallback_points:
                price_date, price_rappen, price_source = fallback_points[fallback_lookup_symbol]
                resolved_points[product.id] = PricePoint(
                    price_date=price_date,
                    price_rappen=price_rappen,
                    currency=(product.currency or "CHF"),
                    source=price_source,
                )
                continue

            error = symbol_errors.get(primary_symbol)
            if fallback_lookup_symbol:
                error = error or fallback_errors.get(fallback_lookup_symbol)
            error = _append_market_warning(
                error or f"Kein Batch-Ergebnis fuer {primary_symbol}",
                provider_market_warning(PRICE_SOURCE, getattr(product, "exchange_code", None)),
                provider_market_warning(FALLBACK_PRICE_SOURCE, getattr(product, "exchange_code", None)),
            )
            failures[product.id] = {
                "product": product,
                "lookup_mode": resolve_market_profile(product).get("lookup_mode"),
                "lookup_symbol": fallback_lookup_symbol or primary_symbol,
                "error": error,
            }

    return resolved_points, failures


def upsert_price_history(db: Session, product: Product, price_point: PricePoint) -> tuple[PriceHistory, str]:
    existing = (
        db.query(PriceHistory)
        .filter(
            PriceHistory.product_id == product.id,
            PriceHistory.price_date == price_point.price_date,
            PriceHistory.source == price_point.source,
        )
        .first()
    )

    if existing:
        current_values = (existing.price_rappen, existing.currency)
        new_values = (price_point.price_rappen, price_point.currency)
        existing.fetched_at = utc_now_iso()
        if current_values == new_values:
            return existing, "unchanged"
        existing.price_rappen = price_point.price_rappen
        existing.currency = price_point.currency
        return existing, "updated"

    row = PriceHistory(
        id=new_uuid(),
        product_id=product.id,
        price_date=price_point.price_date,
        price_rappen=price_point.price_rappen,
        currency=price_point.currency,
        source=price_point.source,
        fetched_at=utc_now_iso(),
    )
    db.add(row)
    return row, "inserted"


def list_price_mapping_gaps(db: Session) -> list[dict[str, Any]]:
    rows = (
        db.query(Product)
        .filter(Product.is_active == 1, Product.deleted_at.is_(None))
        .order_by(Product.product_name.asc())
        .all()
    )
    return [
        {
            "product_id": row.id,
            "product_name": row.product_name,
            "isin": row.isin,
            "lookup_symbol": profile.get("lookup_symbol"),
            "lookup_mode": profile.get("lookup_mode"),
            "pricing_note": profile.get("pricing_note"),
            "currency": row.currency,
        }
        for row in rows
        for profile in [resolve_market_profile(row)]
        if not is_market_mapped(profile)
    ]


def latest_price_snapshot(db: Session, product_ids: list[str] | None = None) -> dict[str, PriceHistory]:
    query = db.query(PriceHistory)
    if product_ids is not None:
        if not product_ids:
            return {}
        query = query.filter(PriceHistory.product_id.in_(product_ids))
    rows = query.order_by(
        PriceHistory.product_id.asc(),
        PriceHistory.price_date.desc(),
        PriceHistory.fetched_at.desc(),
    ).all()
    latest: dict[str, PriceHistory] = {}
    for row in rows:
        if row.product_id not in latest:
            latest[row.product_id] = row
    return latest


def summarize_price_quality(
    db: Session,
    product_ids: list[str] | None = None,
    *,
    stale_after_days: int = 5,
) -> dict[str, Any]:
    product_query = db.query(Product).filter(Product.is_active == 1, Product.deleted_at.is_(None))
    if product_ids is not None:
        if not product_ids:
            return {
                "scope": "selection",
                "stale_after_days": stale_after_days,
                "active_products_count": 0,
                "mapped_products_count": 0,
                "mapping_gap_count": 0,
                "direct_lookup_products_count": 0,
                "direct_symbol_lookup_products_count": 0,
                "direct_isin_lookup_products_count": 0,
                "proxy_lookup_products_count": 0,
                "synthetic_lookup_products_count": 0,
                "priced_products_count": 0,
                "fresh_products_count": 0,
                "stale_products_count": 0,
                "missing_price_count": 0,
                "coverage_pct": 0,
                "fresh_coverage_pct": 0,
                "latest_price_date": None,
            }
        product_query = product_query.filter(Product.id.in_(product_ids))
    products = product_query.order_by(Product.product_name.asc()).all()
    latest_prices = latest_price_snapshot(db, [product.id for product in products])
    today = date.today()

    mapped_count = 0
    direct_count = 0
    symbol_direct_count = 0
    isin_direct_count = 0
    proxy_count = 0
    synthetic_count = 0
    priced_count = 0
    fresh_count = 0
    stale_count = 0
    latest_dates: list[str] = []
    for product in products:
        profile = resolve_market_profile(product)
        lookup_mode = str(profile.get("lookup_mode") or "unmapped")
        identifier_basis = str(profile.get("identifier_basis") or "").strip().lower()
        if is_market_mapped(profile):
            mapped_count += 1
        if lookup_mode == "direct":
            direct_count += 1
            if identifier_basis == "symbol":
                symbol_direct_count += 1
            elif identifier_basis == "isin":
                isin_direct_count += 1
        elif lookup_mode == "proxy":
            proxy_count += 1
        elif lookup_mode == "synthetic_par":
            synthetic_count += 1
        latest = latest_prices.get(product.id)
        if not latest:
            continue
        priced_count += 1
        latest_dates.append(latest.price_date)
        price_date = parse_iso_date(latest.price_date)
        age_days = (today - price_date).days if price_date else stale_after_days + 1
        if age_days <= stale_after_days:
            fresh_count += 1
        else:
            stale_count += 1

    active_count = len(products)
    return {
        "scope": "selection" if product_ids is not None else "universe",
        "stale_after_days": stale_after_days,
        "active_products_count": active_count,
        "mapped_products_count": mapped_count,
        "direct_lookup_products_count": direct_count,
        "direct_symbol_lookup_products_count": symbol_direct_count,
        "direct_isin_lookup_products_count": isin_direct_count,
        "proxy_lookup_products_count": proxy_count,
        "synthetic_lookup_products_count": synthetic_count,
        "mapping_gap_count": max(0, active_count - mapped_count),
        "priced_products_count": priced_count,
        "fresh_products_count": fresh_count,
        "stale_products_count": stale_count,
        "missing_price_count": max(0, active_count - priced_count),
        "coverage_pct": int(round(priced_count / active_count * 100)) if active_count else 0,
        "fresh_coverage_pct": int(round(fresh_count / active_count * 100)) if active_count else 0,
        "latest_price_date": max(latest_dates) if latest_dates else None,
    }


def refresh_all_prices(db: Session) -> dict[str, Any]:
    global _last_refresh_summary

    products = (
        db.query(Product)
        .filter(Product.is_active == 1, Product.deleted_at.is_(None))
        .order_by(Product.product_name.asc())
        .all()
    )

    summary: dict[str, Any] = {
        "processed": 0,
        "inserted": 0,
        "updated": 0,
        "unchanged": 0,
        "reused_fresh": 0,
        "failed": 0,
        "failures": [],
        "started_at": utc_now_iso(),
        "provider": PRICE_SOURCE,
        "fallback_provider": FALLBACK_PRICE_SOURCE,
    }

    summary["processed"] = len(products)
    existing_latest = latest_price_snapshot(db, [product.id for product in products])
    today = date.today()
    stale_after_days = 5
    points, failures = fetch_latest_prices_batch(products)

    for product in products:
        price_point = points.get(product.id)
        if price_point is None:
            latest_existing = existing_latest.get(product.id)
            latest_date = parse_iso_date(latest_existing.price_date) if latest_existing else None
            latest_age_days = (today - latest_date).days if latest_date else None
            if latest_existing and latest_age_days is not None and latest_age_days <= stale_after_days:
                summary["reused_fresh"] += 1
                summary["unchanged"] += 1
                continue
            failure = failures.get(product.id) or {
                "lookup_symbol": resolve_lookup_symbol(product),
                "lookup_mode": resolve_market_profile(product).get("lookup_mode"),
                "error": "Unbekannter Preisfehler",
            }
            logger.warning("Price refresh failed for product %s: %s", product.id, failure["error"])
            summary["failed"] += 1
            summary["failures"].append(
                {
                    "product_id": product.id,
                    "product_name": product.product_name,
                    "lookup_symbol": failure.get("lookup_symbol"),
                    "lookup_mode": failure.get("lookup_mode"),
                    "error": failure.get("error"),
                }
            )
            continue

        with db.begin_nested():
            _, outcome = upsert_price_history(db, product, price_point)

        if outcome == "inserted":
            summary["inserted"] += 1
        elif outcome == "updated":
            summary["updated"] += 1
        else:
            summary["unchanged"] += 1

    db.commit()
    summary["finished_at"] = utc_now_iso()
    summary["setup"] = get_market_data_setup_status()
    _last_refresh_summary = summary
    return summary


def scheduler_job() -> dict[str, Any]:
    logger.info("Starting scheduled price refresh job")
    with SessionLocal() as db:
        return refresh_all_prices(db)


def get_price_runtime_status(db: Session | None = None) -> dict[str, Any]:
    next_run_at = None
    is_running = bool(scheduler and scheduler.running)
    provider_roles = get_market_data_provider_roles()
    if is_running:
        job = scheduler.get_job("daily_price_refresh")
        if job and job.next_run_time is not None:
            next_run_at = job.next_run_time.isoformat()
    payload = {
        "scheduler_enabled": settings.price_scheduler_enabled,
        "scheduler_running": is_running,
        "provider": PRICE_SOURCE,
        "provider_roles": provider_roles,
        "setup": get_market_data_setup_status(provider_roles),
        "client_library_available": yf is not None,
        "timezone": settings.price_scheduler_timezone,
        "cron": {
            "hour": settings.price_scheduler_hour,
            "minute": settings.price_scheduler_minute,
        },
        "next_run_at": next_run_at,
        "last_refresh_summary": _last_refresh_summary,
    }
    if db is not None:
        payload["quality"] = summarize_price_quality(db)
        payload["mapping_gaps_count"] = int(payload["quality"]["mapping_gap_count"])
    return payload


def start_price_scheduler() -> None:
    global scheduler

    if not settings.price_scheduler_enabled:
        logger.info("Price scheduler disabled by configuration")
        return

    if BackgroundScheduler is None or CronTrigger is None:
        logger.warning("APScheduler ist nicht installiert. Preis-Scheduler bleibt deaktiviert.")
        return

    if scheduler and scheduler.running:
        return

    scheduler = BackgroundScheduler(
        timezone=settings.price_scheduler_timezone,
        job_defaults={"coalesce": True, "max_instances": 1},
    )
    scheduler.add_job(
        scheduler_job,
        trigger=CronTrigger(
            hour=settings.price_scheduler_hour,
            minute=settings.price_scheduler_minute,
            timezone=settings.price_scheduler_timezone,
        ),
        id="daily_price_refresh",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        "Price scheduler started for %02d:%02d %s",
        settings.price_scheduler_hour,
        settings.price_scheduler_minute,
        settings.price_scheduler_timezone,
    )


def stop_price_scheduler() -> None:
    global scheduler

    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
    scheduler = None
