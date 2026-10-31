"""Sprint U-P11a (2026-05-22): Annual-Returns-Backfill via Aggregator.

Füllt die Tabelle `asset_class_annual_returns` automatisch aus historischen
EOD-Bars eines Marktdaten-Providers (yfinance / stooq als Fallback). Dadurch
muss niemand die Tabelle manuell pflegen, und U-P17 (Strategie-Backtest) hat
sofort 10-20 Jahre Daten zum Arbeiten.

Methodik:
- Pro Asset-Klasse ein Proxy-Symbol (USD-denominierte ETFs als robuste
  Standard-Defaults; siehe DEFAULT_SYMBOL_MAP).
- Aggregator liefert das History-Fenster (from_year-1, to_year).
- Pro Jahr wird die letzte verfügbare Bar (= Year-End) genommen, mit
  adjusted_close wenn vorhanden (Total Return inkl. Dividenden), sonst
  close.
- Annual Return = (price_y / price_{y-1}) - 1, persistiert als bps.

Idempotenz: existierende (year, asset_class) Rows werden überschrieben
wenn overwrite=True (Default). Bei overwrite=False werden bestehende
Rows übersprungen — nützlich um Lücken zu füllen ohne manuell gepflegte
Werte zu überschreiben.

Read-only auf Marktdaten, write-only auf asset_class_annual_returns.
"""
from __future__ import annotations

import logging
from datetime import date as Date
from datetime import datetime
from decimal import Decimal
from typing import Mapping
from uuid import uuid4

from sqlalchemy.orm import Session

from models.snapshots import AssetClassAnnualReturn
from services.market_data.aggregator import MarketDataAggregator
from services.market_data.exceptions import MarketDataError

logger = logging.getLogger(__name__)


# Default-Symbol-Map: USD-Total-Return-ETFs, robust verfügbar via
# yfinance + stooq. Berater können den Map per Endpoint-Body überschreiben.
# Asset-Class-Schlüssel müssen exakt mit _VALID_ASSET_CLASSES in
# routers/system.py übereinstimmen.
DEFAULT_SYMBOL_MAP: dict[str, str] = {
    "Aktien": "URTH",          # iShares MSCI World (Developed Equity TR)
    "Obligationen": "AGG",     # iShares Core US Aggregate Bond
    "Immobilien": "VNQ",       # Vanguard Real Estate
    "Alternative": "GLD",      # SPDR Gold
    "Liquiditaet": "BIL",      # SPDR 1-3M T-Bill
}


def _year_end_prices(
    bars: list,
    years: list[int],
) -> dict[int, Decimal]:
    """Extrahiert pro Jahr die letzte verfügbare Bar (= Year-End-Close).

    Bevorzugt adjusted_close (Total Return inkl. Dividenden) wenn vorhanden,
    sonst close. Years die keine Bar im Datensatz haben fehlen im Output.
    """
    # Sortiere bars by date aufsteigend — yfinance liefert i.d.R. sortiert,
    # aber defensiv.
    sorted_bars = sorted(bars, key=lambda b: b.date)
    result: dict[int, Decimal] = {}
    for year in years:
        # Letzte Bar mit date.year == year
        last_bar = None
        for bar in sorted_bars:
            if bar.date.year == year:
                last_bar = bar
        if last_bar is None:
            continue
        price = last_bar.adjusted_close if last_bar.adjusted_close is not None else last_bar.close
        if price is None:
            continue
        result[year] = Decimal(price)
    return result


def _compute_annual_return_bps(price_curr: Decimal, price_prev: Decimal) -> int | None:
    """(curr/prev - 1) als bps. None wenn prev <= 0 oder ungültig."""
    if price_prev <= 0:
        return None
    try:
        ratio = (price_curr / price_prev) - Decimal("1")
        return int(round(float(ratio) * 10000))
    except (ArithmeticError, ValueError, TypeError):
        return None


def _upsert_annual_return(
    db: Session,
    *,
    year: int,
    asset_class: str,
    return_bps: int,
    source: str,
    overwrite: bool,
) -> tuple[bool, str]:
    """Schreibt einen Annual-Return-Eintrag. Returns (was_written, action)
    wobei action ∈ {'created', 'updated', 'skipped_exists'}.
    """
    now = datetime.utcnow().isoformat()
    existing = (
        db.query(AssetClassAnnualReturn)
        .filter_by(year=year, asset_class=asset_class)
        .first()
    )
    if existing:
        if not overwrite:
            return (False, "skipped_exists")
        existing.return_bps = return_bps
        existing.source = source
        existing.updated_at = now
        return (True, "updated")
    db.add(AssetClassAnnualReturn(
        id=str(uuid4()),
        year=year,
        asset_class=asset_class,
        return_bps=return_bps,
        source=source,
        created_at=now,
        updated_at=now,
    ))
    return (True, "created")


def backfill_annual_returns(
    db: Session,
    aggregator: MarketDataAggregator,
    *,
    from_year: int,
    to_year: int,
    symbol_map: Mapping[str, str] | None = None,
    overwrite: bool = True,
) -> dict:
    """Backfillt asset_class_annual_returns für [from_year, to_year].

    Args:
        db: SQLAlchemy-Session (Transaktion bleibt offen, commit beim Aufrufer)
        aggregator: konfigurierter MarketDataAggregator
        from_year, to_year: Jahre inklusive
        symbol_map: optional, sonst DEFAULT_SYMBOL_MAP
        overwrite: True = bestehende Rows überschreiben

    Returns:
        {
            "from_year", "to_year",
            "symbols_used": dict,
            "processed": [{year, asset_class, return_bps, source, action}],
            "errors": [{year?, asset_class, reason}],
            "started_at", "finished_at",
        }
    """
    if from_year > to_year:
        raise ValueError("from_year > to_year")
    if from_year < 1900 or to_year > 2100:
        raise ValueError("Unrealistischer Zeitraum (erwarte 1900-2100).")

    smap = dict(symbol_map or DEFAULT_SYMBOL_MAP)
    started_at = datetime.utcnow().isoformat()
    processed: list[dict] = []
    errors: list[dict] = []

    # Wir brauchen einen Anchor-Tag VOR from_year, um den from_year-Return
    # berechnen zu können: nimm letzten Trading-Day von (from_year-1).
    fetch_start = Date(from_year - 1, 12, 1)
    fetch_end = Date(to_year, 12, 31)
    years_to_fetch = list(range(from_year - 1, to_year + 1))

    for asset_class, symbol in smap.items():
        try:
            bars = aggregator.get_history(symbol, fetch_start, fetch_end)
        except MarketDataError as exc:
            errors.append({
                "asset_class": asset_class,
                "symbol": symbol,
                "reason": f"history-Fehler: {exc}",
            })
            continue
        except Exception as exc:  # noqa: BLE001
            errors.append({
                "asset_class": asset_class,
                "symbol": symbol,
                "reason": f"unerwarteter Fehler: {exc}",
            })
            continue

        if not bars:
            errors.append({
                "asset_class": asset_class,
                "symbol": symbol,
                "reason": "Provider lieferte keine Bars für den Zeitraum.",
            })
            continue

        year_end_prices = _year_end_prices(bars, years_to_fetch)
        source_label = f"backfill:{symbol}"

        for year in range(from_year, to_year + 1):
            price_curr = year_end_prices.get(year)
            price_prev = year_end_prices.get(year - 1)
            if price_curr is None:
                errors.append({
                    "year": year,
                    "asset_class": asset_class,
                    "reason": f"Keine Bar für Jahresende {year} verfügbar.",
                })
                continue
            if price_prev is None:
                errors.append({
                    "year": year,
                    "asset_class": asset_class,
                    "reason": f"Keine Bar für Jahresende {year-1} (Anchor) verfügbar.",
                })
                continue
            return_bps = _compute_annual_return_bps(price_curr, price_prev)
            if return_bps is None:
                errors.append({
                    "year": year,
                    "asset_class": asset_class,
                    "reason": "Annual-Return-Berechnung lieferte None.",
                })
                continue
            written, action = _upsert_annual_return(
                db,
                year=year,
                asset_class=asset_class,
                return_bps=return_bps,
                source=source_label,
                overwrite=overwrite,
            )
            processed.append({
                "year": year,
                "asset_class": asset_class,
                "return_bps": return_bps,
                "source": source_label,
                "action": action,
                "written": written,
            })

    finished_at = datetime.utcnow().isoformat()
    return {
        "from_year": from_year,
        "to_year": to_year,
        "symbols_used": smap,
        "processed": processed,
        "errors": errors,
        "started_at": started_at,
        "finished_at": finished_at,
        "summary": {
            "rows_written": sum(1 for p in processed if p["written"]),
            "rows_skipped": sum(1 for p in processed if not p["written"]),
            "error_count": len(errors),
        },
        "note": (
            "USD-Total-Return-Approximation. Beratungssicht in CHF ist eine "
            "Vereinfachung — gemessen an den Default-Indices ohne FX-Hedge. "
            "Für präzise CHF-Strategie-Bewertung Override-Symbole nutzen oder "
            "Werte manuell überschreiben."
        ),
    }
