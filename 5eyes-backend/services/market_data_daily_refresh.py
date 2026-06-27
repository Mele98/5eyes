"""Daily market-data refresh for advisory positions and strategy proxies.

The job updates data sources only. It does not create recommendations,
trigger rebalancing, or change target allocations.
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterable

from sqlalchemy.orm import Session

from config import settings
from models.review import Product, RecommendationPosition
from services.market_data.asset_class_price_backfill import (
    DEFAULT_SYMBOL_MAP,
    _bar_close_rappen,
    _fx_symbol_for,
    _upsert_fx,
    _upsert_price,
)

logger = logging.getLogger(__name__)

DAILY_PRICE_SOURCE_PREFIX = "daily"
DEFAULT_FX_CURRENCIES = ("USD", "EUR", "JPY", "GBP")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _decimal_to_x10000(value: Any) -> int | None:
    if value is None:
        return None
    try:
        scaled = int(round(float(Decimal(value)) * 10000))
    except (ArithmeticError, ValueError, TypeError):
        return None
    return scaled if scaled > 0 else None


def _bar_rate_to_chf_x10000(bar: Any) -> int | None:
    price = (
        bar.adjusted_close
        if getattr(bar, "adjusted_close", None) is not None
        else getattr(bar, "close", None)
    )
    return _decimal_to_x10000(price)


def _active_position_products(db: Session, *, max_symbols: int) -> list[Product]:
    """Products currently used by client holdings in recommendation positions."""
    if max_symbols <= 0:
        return []
    return (
        db.query(Product)
        .join(RecommendationPosition, RecommendationPosition.product_id == Product.id)
        .filter(
            RecommendationPosition.current_amount_rappen.isnot(None),
            Product.is_active == 1,
            Product.deleted_at.is_(None),
        )
        .distinct()
        .order_by(Product.product_name.asc())
        .limit(max_symbols)
        .all()
    )


def _update_live_reference_positions(
    db: Session,
    *,
    product_id: str,
    price_point: Any,
) -> int:
    rows = (
        db.query(RecommendationPosition)
        .filter(
            RecommendationPosition.product_id == product_id,
            RecommendationPosition.current_amount_rappen.isnot(None),
        )
        .all()
    )
    fetched_at = _utc_now_iso()
    for row in rows:
        row.reference_price_rappen = int(price_point.price_rappen)
        row.reference_price_date = str(price_point.price_date)
        row.reference_price_source = str(price_point.source or "market_data")
        row.reference_price_fetched_at = fetched_at
        row.updated_at = fetched_at
    return len(rows)


def _refresh_product_prices(db: Session, products: Iterable[Product], errors: list[dict]) -> dict[str, int]:
    from price_updater import fetch_latest_prices_batch, upsert_price_history

    product_list = list(products)
    if not product_list:
        return {
            "products_refreshed": 0,
            "product_positions_updated": 0,
            "product_price_inserted": 0,
            "product_price_updated": 0,
            "product_price_unchanged": 0,
            "product_failures": 0,
        }

    points, failures = fetch_latest_prices_batch(product_list)
    counts = {
        "products_refreshed": 0,
        "product_positions_updated": 0,
        "product_price_inserted": 0,
        "product_price_updated": 0,
        "product_price_unchanged": 0,
        "product_failures": 0,
    }

    for product in product_list:
        price_point = points.get(product.id)
        if price_point is None:
            failure = failures.get(product.id) or {}
            errors.append({
                "scope": "product",
                "product_id": product.id,
                "product_name": product.product_name,
                "lookup_symbol": failure.get("lookup_symbol"),
                "reason": failure.get("error") or "Kein Preis vom Provider erhalten.",
            })
            counts["product_failures"] += 1
            continue
        try:
            with db.begin_nested():
                _, outcome = upsert_price_history(db, product, price_point)
                updated_positions = _update_live_reference_positions(
                    db,
                    product_id=product.id,
                    price_point=price_point,
                )
        except Exception as exc:  # noqa: BLE001
            errors.append({
                "scope": "product",
                "product_id": product.id,
                "product_name": product.product_name,
                "reason": f"Persistenzfehler: {exc}",
            })
            counts["product_failures"] += 1
            continue

        counts["products_refreshed"] += 1
        counts["product_positions_updated"] += updated_positions
        if outcome == "inserted":
            counts["product_price_inserted"] += 1
        elif outcome == "updated":
            counts["product_price_updated"] += 1
        else:
            counts["product_price_unchanged"] += 1

    return counts


def _most_recent_business_day(d: date) -> date:
    """MD-06: jüngster Werktag <= d (Sa -> Fr, So -> Fr).

    An Wochenenden gibt es keinen Handelstag; eine Anfrage mit dem Wochenend-Datum
    als kanonischem Ziel ist irreführend. Feiertage werden nicht modelliert — der
    Provider-Contract (get_eod liefert letzten Handelstag <= on_date, MD-04) deckt
    die verbleibende Rückschau ab.
    """
    weekday = d.weekday()  # Mo=0 .. So=6
    if weekday == 5:       # Samstag
        return d - timedelta(days=1)
    if weekday == 6:       # Sonntag
        return d - timedelta(days=2)
    return d


def _refresh_asset_class_prices(db: Session, aggregator: Any, errors: list[dict]) -> int:
    target_date = _most_recent_business_day(date.today())
    rows_written = 0
    for asset_class, symbol in dict(DEFAULT_SYMBOL_MAP).items():
        try:
            bar = aggregator.get_eod(symbol, target_date)
            close_rappen = _bar_close_rappen(bar)
            if close_rappen is None or close_rappen <= 0:
                raise ValueError("Provider lieferte keinen gueltigen Schlusskurs.")
            written, _action = _upsert_price(
                db,
                asset_class=asset_class,
                price_date=bar.date.isoformat(),
                close_rappen=close_rappen,
                currency=(str(getattr(bar, "currency", "") or "").upper() or None),
                source=f"{DAILY_PRICE_SOURCE_PREFIX}:{symbol}",
                overwrite=True,
            )
            if written:
                rows_written += 1
        except Exception as exc:  # noqa: BLE001
            errors.append({
                "scope": "asset_class",
                "asset_class": asset_class,
                "symbol": symbol,
                "reason": str(exc),
            })
    return rows_written


def _refresh_fx_rates(
    db: Session,
    aggregator: Any,
    errors: list[dict],
    *,
    currencies: Iterable[str] = DEFAULT_FX_CURRENCIES,
) -> int:
    target_date = _most_recent_business_day(date.today())
    rows_written = 0
    for currency in sorted({str(c or "").upper() for c in currencies if str(c or "").strip()}):
        if currency == "CHF":
            continue
        symbol = _fx_symbol_for(currency)
        try:
            bar = aggregator.get_eod(symbol, target_date)
            rate = _bar_rate_to_chf_x10000(bar)
            if rate is None:
                raise ValueError("Provider lieferte keinen gueltigen FX-Schlusskurs.")
            if _upsert_fx(
                db,
                currency=currency,
                price_date=bar.date.isoformat(),
                rate_to_chf_x10000=rate,
                source=f"{DAILY_PRICE_SOURCE_PREFIX}:{symbol}",
                overwrite=True,
            ):
                rows_written += 1
        except Exception as exc:  # noqa: BLE001
            errors.append({
                "scope": "fx",
                "currency": currency,
                "symbol": symbol,
                "reason": str(exc),
            })
    return rows_written


def run_daily_market_data_refresh(db: Session) -> dict[str, Any]:
    """Refresh product prices, asset-class proxy prices and FX rates.

    Provider/data errors are collected in the returned summary. A partial
    refresh commits successful rows so advisors can recover manually later.
    """
    started_at = _utc_now_iso()
    started_perf = time.perf_counter()
    errors: list[dict] = []
    max_symbols = int(getattr(settings, "market_data_daily_refresh_max_symbols", 500) or 500)

    from services.market_data.factory import build_default_aggregator

    products = _active_position_products(db, max_symbols=max_symbols)
    product_counts = _refresh_product_prices(db, products, errors)

    aggregator = build_default_aggregator()
    prices_added = _refresh_asset_class_prices(db, aggregator, errors)
    fx_added = _refresh_fx_rates(db, aggregator, errors)

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    finished_at = _utc_now_iso()
    duration_seconds = max(time.perf_counter() - started_perf, 0.000001)
    summary: dict[str, Any] = {
        "status": "ok" if not errors else "degraded",
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": round(duration_seconds, 6),
        "products_considered": len(products),
        "products_refreshed": product_counts["products_refreshed"],
        "product_positions_updated": product_counts["product_positions_updated"],
        "product_price_inserted": product_counts["product_price_inserted"],
        "product_price_updated": product_counts["product_price_updated"],
        "product_price_unchanged": product_counts["product_price_unchanged"],
        "product_failures": product_counts["product_failures"],
        "prices_added": prices_added,
        "fx_added": fx_added,
        "errors": errors,
        "max_symbols": max_symbols,
    }
    logger.info(
        "Daily market-data refresh complete: products=%s prices_added=%s fx_added=%s errors=%s",
        summary["products_refreshed"],
        summary["prices_added"],
        summary["fx_added"],
        len(errors),
    )
    return summary
