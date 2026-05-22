"""Sprint U-P19 (2026-05-22): Daily-Price-Backfill je Asset-Klasse.

Füllt `asset_class_price_history` mit täglichen EOD-Kursen aus dem
Marktdaten-Aggregator (yfinance / stooq als Fallback). Datenquelle für den
Daily-Strategie-Backtest (U-P17 → U-P19). Der Backtest liest danach NUR aus
der DB — kein Live-Netz auf dem Request-Pfad (offline-fähig).

Methodik:
- Pro Asset-Klasse ein Proxy-Symbol (siehe DEFAULT_SYMBOL_MAP aus dem
  Annual-Backfill — dieselben USD-Total-Return-ETFs).
- Aggregator liefert das History-Fenster [from_year-01-01, to_year-12-31].
- Pro Handelstag wird adjusted_close (Total Return) bevorzugt, sonst close;
  gespeichert als close_rappen = round(price * 100).

Idempotenz: existierende (asset_class, price_date, source) Rows werden bei
overwrite=True überschrieben, sonst übersprungen.

Read-only auf Marktdaten, write-only auf asset_class_price_history.
"""
from __future__ import annotations

import logging
from datetime import date as Date
from datetime import datetime
from decimal import Decimal
from typing import Mapping
from uuid import uuid4

from sqlalchemy.orm import Session

from models.snapshots import AssetClassFxHistory, AssetClassPriceHistory
from services.market_data.aggregator import MarketDataAggregator
from services.market_data.annual_returns_backfill import DEFAULT_SYMBOL_MAP
from services.market_data.exceptions import MarketDataError

# Basis-Währung des Backtests (5eyes-Standard). Assets in dieser Währung brauchen
# keine FX-Konvertierung.
BASE_CURRENCY = "CHF"


def _fx_symbol_for(currency: str) -> str:
    """Yahoo-FX-Symbol für <currency>→CHF. USD ist auf Yahoo implizite Basis
    ('CHF=X' == USD/CHF); andere Währungen via '<CCY>CHF=X'."""
    ccy = str(currency or "").upper()
    if ccy == "USD":
        return "CHF=X"
    return f"{ccy}CHF=X"

logger = logging.getLogger(__name__)


def _bar_close_rappen(bar) -> int | None:
    """adjusted_close (Total Return) bevorzugt, sonst close → Rappen-Integer."""
    price = bar.adjusted_close if getattr(bar, "adjusted_close", None) is not None else bar.close
    if price is None:
        return None
    try:
        return int(round(float(Decimal(price)) * 100))
    except (ArithmeticError, ValueError, TypeError):
        return None


def _upsert_price(
    db: Session,
    *,
    asset_class: str,
    price_date: str,
    close_rappen: int,
    currency: str | None,
    source: str,
    overwrite: bool,
) -> tuple[bool, str]:
    """Schreibt einen Daily-Price-Eintrag. Returns (was_written, action)
    mit action ∈ {'created', 'updated', 'skipped_exists'}."""
    now = datetime.utcnow().isoformat()
    existing = (
        db.query(AssetClassPriceHistory)
        .filter_by(asset_class=asset_class, price_date=price_date, source=source)
        .first()
    )
    if existing:
        if not overwrite:
            return (False, "skipped_exists")
        existing.close_rappen = close_rappen
        existing.currency = currency
        existing.updated_at = now
        return (True, "updated")
    db.add(AssetClassPriceHistory(
        id=str(uuid4()),
        asset_class=asset_class,
        price_date=price_date,
        close_rappen=close_rappen,
        currency=currency,
        source=source,
        created_at=now,
        updated_at=now,
    ))
    return (True, "created")


def _upsert_fx(
    db: Session,
    *,
    currency: str,
    price_date: str,
    rate_to_chf_x10000: int,
    source: str,
    overwrite: bool,
) -> bool:
    """Schreibt einen FX→CHF-Tageseintrag. Returns was_written."""
    now = datetime.utcnow().isoformat()
    existing = (
        db.query(AssetClassFxHistory)
        .filter_by(currency=currency, price_date=price_date, source=source)
        .first()
    )
    if existing:
        if not overwrite:
            return False
        existing.rate_to_chf_x10000 = rate_to_chf_x10000
        existing.updated_at = now
        return True
    db.add(AssetClassFxHistory(
        id=str(uuid4()),
        currency=currency,
        price_date=price_date,
        rate_to_chf_x10000=rate_to_chf_x10000,
        source=source,
        created_at=now,
        updated_at=now,
    ))
    return True


def _backfill_fx_series(
    db: Session,
    aggregator: MarketDataAggregator,
    *,
    currencies: set[str],
    fetch_start: Date,
    fetch_end: Date,
    overwrite: bool,
    errors: list[dict],
) -> dict:
    """Holt pro Nicht-CHF-Währung eine tägliche FX→CHF-Reihe. Graceful: ein
    Fehler je Währung wird gesammelt, bricht den Backfill nicht ab."""
    fx_coverage: dict[str, dict] = {}
    fx_rows_written = 0
    for ccy in sorted(c for c in currencies if c and c.upper() != BASE_CURRENCY):
        symbol = _fx_symbol_for(ccy)
        try:
            bars = aggregator.get_history(symbol, fetch_start, fetch_end)
        except Exception as exc:  # noqa: BLE001
            errors.append({"currency": ccy, "symbol": symbol,
                           "reason": f"FX-history-Fehler: {exc}"})
            continue
        if not bars:
            errors.append({"currency": ccy, "symbol": symbol,
                           "reason": "Provider lieferte keine FX-Bars."})
            continue
        dates: list[str] = []
        for bar in bars:
            price = bar.adjusted_close if getattr(bar, "adjusted_close", None) is not None else bar.close
            if price is None:
                continue
            try:
                rate_x = int(round(float(Decimal(price)) * 10000))
            except (ArithmeticError, ValueError, TypeError):
                continue
            if rate_x <= 0:
                continue
            if _upsert_fx(db, currency=ccy.upper(), price_date=bar.date.isoformat(),
                          rate_to_chf_x10000=rate_x, source=f"backfill:{symbol}", overwrite=overwrite):
                fx_rows_written += 1
            dates.append(bar.date.isoformat())
        if dates:
            fx_coverage[ccy.upper()] = {"symbol": symbol, "first": min(dates),
                                        "last": max(dates), "points": len(dates)}
    return {"fx_coverage": fx_coverage, "fx_rows_written": fx_rows_written}


def backfill_asset_class_prices(
    db: Session,
    aggregator: MarketDataAggregator,
    *,
    from_year: int,
    to_year: int,
    symbol_map: Mapping[str, str] | None = None,
    overwrite: bool = True,
) -> dict:
    """Backfillt asset_class_price_history für [from_year, to_year] täglich.

    Args:
        db: SQLAlchemy-Session (Transaktion bleibt offen, commit beim Aufrufer)
        aggregator: konfigurierter MarketDataAggregator
        from_year, to_year: Jahre inklusive
        symbol_map: optional, sonst DEFAULT_SYMBOL_MAP
        overwrite: True = bestehende Rows überschreiben

    Returns:
        {from_year, to_year, symbols_used, summary{rows_written, rows_skipped,
         error_count}, coverage{asset_class: {first, last, points}}, errors,
         started_at, finished_at, note}
    """
    if from_year > to_year:
        raise ValueError("from_year > to_year")
    if from_year < 1900 or to_year > 2100:
        raise ValueError("Unrealistischer Zeitraum (erwarte 1900-2100).")

    smap = dict(symbol_map or DEFAULT_SYMBOL_MAP)
    started_at = datetime.utcnow().isoformat()
    fetch_start = Date(from_year, 1, 1)
    fetch_end = Date(to_year, 12, 31)

    rows_written = 0
    rows_skipped = 0
    errors: list[dict] = []
    coverage: dict[str, dict] = {}
    currencies_seen: set[str] = set()

    for asset_class, symbol in smap.items():
        try:
            bars = aggregator.get_history(symbol, fetch_start, fetch_end)
        except MarketDataError as exc:
            errors.append({"asset_class": asset_class, "symbol": symbol,
                           "reason": f"history-Fehler: {exc}"})
            continue
        except Exception as exc:  # noqa: BLE001
            errors.append({"asset_class": asset_class, "symbol": symbol,
                           "reason": f"unerwarteter Fehler: {exc}"})
            continue

        if not bars:
            errors.append({"asset_class": asset_class, "symbol": symbol,
                           "reason": "Provider lieferte keine Bars für den Zeitraum."})
            continue

        source_label = f"backfill:{symbol}"
        dates_written: list[str] = []
        asset_currency: str | None = None
        for bar in bars:
            close_rappen = _bar_close_rappen(bar)
            if close_rappen is None or close_rappen <= 0:
                continue
            currency = (str(getattr(bar, "currency", "") or "").upper() or None)
            if currency:
                asset_currency = currency
                currencies_seen.add(currency)
            price_date = bar.date.isoformat()
            written, action = _upsert_price(
                db, asset_class=asset_class, price_date=price_date,
                close_rappen=close_rappen, currency=currency,
                source=source_label, overwrite=overwrite,
            )
            if written:
                rows_written += 1
            else:
                rows_skipped += 1
            dates_written.append(price_date)

        if dates_written:
            coverage[asset_class] = {
                "symbol": symbol,
                "currency": asset_currency,
                "first": min(dates_written),
                "last": max(dates_written),
                "points": len(dates_written),
            }

    # U-P19b: FX→CHF-Reihen für alle Nicht-CHF-Notierungswährungen holen.
    fx_result = _backfill_fx_series(
        db, aggregator, currencies=currencies_seen,
        fetch_start=fetch_start, fetch_end=fetch_end,
        overwrite=overwrite, errors=errors,
    )

    finished_at = datetime.utcnow().isoformat()
    return {
        "from_year": from_year,
        "to_year": to_year,
        "symbols_used": smap,
        "summary": {
            "rows_written": rows_written,
            "rows_skipped": rows_skipped,
            "fx_rows_written": fx_result["fx_rows_written"],
            "error_count": len(errors),
        },
        "coverage": coverage,
        "fx_coverage": fx_result["fx_coverage"],
        "errors": errors,
        "started_at": started_at,
        "finished_at": finished_at,
        "note": (
            "Proxy-ETF-Total-Returns in Notierungswährung; der Daily-Backtest rechnet "
            "sie währungskorrekt nach CHF um (asset_class_fx_history). Datenquelle für "
            "resolution=daily im Strategie-Backtest."
        ),
    }
