"""Sub-Asset-Annual-Returns-Backfill (Phase 2 von SMI-1988 + Sub-Anlageklassen).

Erweitert annual_returns_backfill.py auf Sub-Anlageklassen via symbol_catalog.
Pro Sub-Asset:
  1. Provider-Cascade aus catalog.cascade() (fruehester data_starts zuerst)
  2. Pro Jahr: erster Provider mit data_starts <= year wird versucht
  3. Bei Misserfolg naechster Provider in der Liste
  4. Total-Return-Approximation: wenn das gewinnende Symbol Price-Only ist
     UND year < tr_start_year, wird pre_tr_dividend_yield_bps addiert
     (z.B. SMI 1988-1998 + 250bps fuer CH-Dividendenrendite)

Sanity-Verification:
- annual_return_bps muss in [-9000, +20000] liegen (= -90% bis +200%)
- Provider liefert chronologisch sortierte Bars
- Year-Spruenge > 1 Jahr fuehren zu Skip + Error-Entry

Persistenz:
- asset_class_annual_returns mit sub_asset_class != NULL
- source-Format: 'backfill:<provider>:<symbol>' bzw.
  'backfill:<provider>:<symbol>+div_estimate_<bps>bps' bei TR-Approximation
"""
from __future__ import annotations

from datetime import date as Date, datetime
from decimal import Decimal
from typing import Iterable, Mapping, Optional
from uuid import uuid4

from sqlalchemy.orm import Session

from models.snapshots import AssetClassAnnualReturn
from services.market_data.aggregator import MarketDataAggregator
from services.market_data.annual_returns_backfill import _year_end_prices, _compute_annual_return_bps
from services.market_data.base import MarketDataProvider
from services.market_data.exceptions import MarketDataError
from services.market_data.symbol_catalog import (
    SUB_ASSET_CATALOG,
    ProviderSymbol,
    SubAssetClass,
    get_sub_asset,
)


def _provider_by_name(
    aggregator: MarketDataAggregator,
    provider_name: str,
) -> Optional[MarketDataProvider]:
    """Direkter Provider-Zugriff per Name.

    Der Aggregator macht eigene Symbol-Cascade ueber ALLE Provider mit dem
    gleichen Symbol — fuer Sub-Asset-Backfill brauchen wir aber das
    konkrete Provider-Symbol-Paar (^smi geht nur an Stooq, nicht an
    yfinance). Daher umgehen wir den Aggregator-Loop hier bewusst und
    holen den genannten Provider direkt.
    """
    for p in aggregator.providers:
        if p.name == provider_name:
            return p
    return None


# Plausibilitaets-Range fuer Annual-Returns: -90% bis +200%.
# Werte ausserhalb sind mit hoher Wahrscheinlichkeit Daten-Bugs.
SANITY_MIN_RETURN_BPS = -9000
SANITY_MAX_RETURN_BPS = 20000


def _provider_available_for_year(
    cascade: tuple[ProviderSymbol, ...],
    year: int,
    active_providers: frozenset[str],
) -> Optional[ProviderSymbol]:
    """Liefert das beste aktive Provider-Symbol mit data_starts <= year.

    Prioritaet:
      1. Total-Return-Symbol mit data_starts <= year (kein Dividenden-
         Schaetzfehler).
      2. Price-Only-Symbol mit data_starts <= year (TR-Approximation via
         pre_tr_dividend_yield_bps kommt dann zum Tragen).

    Innerhalb jeder Tier-Stufe gewinnt der fruehere Daten-Start. Dadurch
    wird z.B. fuer SMI Year 2000 das Bloomberg-SMIC-Index (TR, 1999)
    bevorzugt vor dem SMI-Price-Index (1988, Price-Only) — und fuer
    1990 wird Stooq-SMI (Price-Only, 1988) verwendet mit
    Dividenden-Approximation.

    None wenn weder TR- noch Price-Symbol fuer year verfuegbar.
    """
    # Tier 1: TR-Symbole
    for ps in cascade:
        if ps.provider not in active_providers:
            continue
        if ps.data_starts is None:
            continue
        if not ps.is_total_return:
            continue
        if ps.data_starts <= year:
            return ps
    # Tier 2: Price-Only-Symbole
    for ps in cascade:
        if ps.provider not in active_providers:
            continue
        if ps.data_starts is None:
            continue
        if ps.is_total_return:
            continue
        if ps.data_starts <= year:
            return ps
    return None


def _upsert_sub_asset_return(
    db: Session,
    *,
    year: int,
    asset_class: str,
    sub_asset_class: str,
    return_bps: int,
    source: str,
    overwrite: bool,
) -> tuple[bool, str]:
    """Schreibt Sub-Asset-Annual-Return-Row.

    UniqueKey logisch: (year, asset_class, sub_asset_class). Top-Level-
    Rows (sub_asset_class NULL) bleiben unberuehrt.

    Returns (was_written, action) mit action ∈ {'created','updated','skipped_exists'}.
    """
    now = datetime.utcnow().isoformat()
    existing = (
        db.query(AssetClassAnnualReturn)
        .filter_by(
            year=year,
            asset_class=asset_class,
            sub_asset_class=sub_asset_class,
        )
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
        sub_asset_class=sub_asset_class,
    ))
    return (True, "created")


def _is_sanity_ok(return_bps: int) -> bool:
    return SANITY_MIN_RETURN_BPS <= return_bps <= SANITY_MAX_RETURN_BPS


def _adjust_for_total_return(
    return_bps: int,
    sub_asset: SubAssetClass,
    year: int,
    provider_symbol: ProviderSymbol,
) -> tuple[int, bool]:
    """Wenn Price-Only-Symbol UND year < tr_start_year: addiere
    pre_tr_dividend_yield_bps. Returns (adjusted_bps, was_adjusted).
    """
    if provider_symbol.is_total_return:
        return (return_bps, False)
    if year >= sub_asset.tr_start_year:
        return (return_bps, False)
    if sub_asset.pre_tr_dividend_yield_bps <= 0:
        return (return_bps, False)
    return (return_bps + sub_asset.pre_tr_dividend_yield_bps, True)


def backfill_sub_asset_annual_returns(
    db: Session,
    aggregator: MarketDataAggregator,
    *,
    from_year: int,
    to_year: int,
    sub_asset_keys: Optional[Iterable[str]] = None,
    overwrite: bool = True,
    dry_run: bool = False,
) -> dict:
    """Backfillt asset_class_annual_returns fuer Sub-Anlageklassen.

    Args:
        db: SQLAlchemy-Session (Transaktion bleibt offen, commit beim Aufrufer)
        aggregator: konfigurierter MarketDataAggregator
        from_year, to_year: Jahre inklusive
        sub_asset_keys: Optionale Whitelist; None = alle 18 Sub-Assets
        overwrite: True = bestehende Sub-Asset-Rows ueberschreiben
        dry_run: True = nichts persistieren, nur planen + verifizieren

    Returns:
        {
            "from_year", "to_year",
            "active_providers": [...],
            "sub_assets_requested": [...],
            "processed": [{year, sub_asset_class, asset_class, provider, symbol,
                           return_bps, tr_adjusted, source, action, written}],
            "errors": [{year?, sub_asset_class, reason}],
            "summary": {...},
            "started_at", "finished_at",
            "dry_run": bool
        }
    """
    if from_year > to_year:
        raise ValueError("from_year > to_year")
    if from_year < 1900 or to_year > 2100:
        raise ValueError("Unrealistischer Zeitraum (erwarte 1900-2100).")

    requested_keys = (
        list(sub_asset_keys) if sub_asset_keys is not None
        else list(SUB_ASSET_CATALOG.keys())
    )
    # Validate vor irgendeiner Aktion
    for key in requested_keys:
        if key not in SUB_ASSET_CATALOG:
            raise ValueError(f"Unbekannter Sub-Asset-Schluessel: {key!r}")

    active_providers = frozenset(p.name for p in aggregator.providers)
    started_at = datetime.utcnow().isoformat()
    processed: list[dict] = []
    errors: list[dict] = []

    # Wir brauchen einen Anchor-Tag VOR from_year fuer den from_year-Return
    fetch_start = Date(from_year - 1, 12, 1)
    fetch_end = Date(to_year, 12, 31)
    years_to_fetch = list(range(from_year - 1, to_year + 1))

    for key in requested_keys:
        sub_asset = get_sub_asset(key)
        cascade = sub_asset.cascade()

        # Pro Jahr den fruehesten verfuegbaren Provider waehlen.
        # Wir gruppieren: pro Provider-Symbol einen einzigen fetch-Call,
        # dann fuer die abgedeckten Jahre auswerten.
        # Erste Pass: pro Jahr -> gewinnender Provider-Symbol bestimmen.
        provider_choice_per_year: dict[int, Optional[ProviderSymbol]] = {}
        for year in years_to_fetch:
            provider_choice_per_year[year] = _provider_available_for_year(
                cascade, year, active_providers
            )

        # Zweite Pass: pro einzigartigem Provider-Symbol einen fetch
        used_symbols = {
            ps for ps in provider_choice_per_year.values() if ps is not None
        }
        if not used_symbols:
            errors.append({
                "sub_asset_class": key,
                "reason": (
                    f"Kein Provider aus Cascade aktiv im Aggregator. "
                    f"Cascade-Provider: {[ps.provider for ps in cascade]}. "
                    f"Aktive Provider: {sorted(active_providers)}."
                ),
            })
            continue

        # Bar-Cache pro Provider-Symbol (vermeidet doppel-fetches).
        # Direkter Provider-Aufruf statt Aggregator-Cascade — siehe
        # _provider_by_name-Docstring.
        bars_cache: dict[ProviderSymbol, list] = {}
        for ps in used_symbols:
            provider = _provider_by_name(aggregator, ps.provider)
            if provider is None:
                errors.append({
                    "sub_asset_class": key,
                    "provider": ps.provider,
                    "symbol": ps.symbol,
                    "reason": f"Provider {ps.provider!r} nicht im Aggregator.",
                })
                bars_cache[ps] = []
                continue
            try:
                bars = provider.get_history(ps.symbol, fetch_start, fetch_end)
                bars_cache[ps] = list(bars or [])
            except MarketDataError as exc:
                errors.append({
                    "sub_asset_class": key,
                    "provider": ps.provider,
                    "symbol": ps.symbol,
                    "reason": f"history-Fehler: {exc}",
                })
                bars_cache[ps] = []
            except Exception as exc:  # noqa: BLE001
                errors.append({
                    "sub_asset_class": key,
                    "provider": ps.provider,
                    "symbol": ps.symbol,
                    "reason": f"unerwarteter Fehler: {exc}",
                })
                bars_cache[ps] = []

        # Year-End-Prices pro Provider-Symbol vor-berechnen
        year_end_per_symbol: dict[ProviderSymbol, dict[int, Decimal]] = {
            ps: _year_end_prices(bars, years_to_fetch)
            for ps, bars in bars_cache.items()
        }

        # Dritte Pass: pro Jahr Return berechnen
        for year in range(from_year, to_year + 1):
            chosen = provider_choice_per_year.get(year)
            chosen_prev = provider_choice_per_year.get(year - 1)
            if chosen is None:
                errors.append({
                    "year": year,
                    "sub_asset_class": key,
                    "reason": f"Kein Provider abdeckt Jahr {year} (Sub-Asset "
                              f"index_start={sub_asset.index_start_year}).",
                })
                continue
            # Wenn Vorjahr von anderem Provider abgedeckt, koennen wir nicht
            # ueber Provider-Grenzen hinweg Returns berechnen — Price-Niveaus
            # sind nicht vergleichbar.
            if chosen_prev != chosen:
                errors.append({
                    "year": year,
                    "sub_asset_class": key,
                    "reason": (
                        f"Provider-Wechsel zwischen Jahresende {year-1} und {year} "
                        f"erlaubt keine Return-Berechnung."
                    ),
                })
                continue
            year_ends = year_end_per_symbol.get(chosen, {})
            price_curr = year_ends.get(year)
            price_prev = year_ends.get(year - 1)
            if price_curr is None:
                errors.append({
                    "year": year,
                    "sub_asset_class": key,
                    "reason": f"Keine Bar fuer Jahresende {year} (Provider "
                              f"{chosen.provider}, Symbol {chosen.symbol}).",
                })
                continue
            if price_prev is None:
                errors.append({
                    "year": year,
                    "sub_asset_class": key,
                    "reason": f"Keine Bar fuer Anker {year-1} (Provider "
                              f"{chosen.provider}, Symbol {chosen.symbol}).",
                })
                continue
            return_bps = _compute_annual_return_bps(price_curr, price_prev)
            if return_bps is None:
                errors.append({
                    "year": year,
                    "sub_asset_class": key,
                    "reason": "Annual-Return-Berechnung lieferte None.",
                })
                continue
            adjusted_bps, tr_adjusted = _adjust_for_total_return(
                return_bps, sub_asset, year, chosen
            )
            if not _is_sanity_ok(adjusted_bps):
                errors.append({
                    "year": year,
                    "sub_asset_class": key,
                    "reason": (
                        f"Return {adjusted_bps}bps ausserhalb Sanity-Range "
                        f"[{SANITY_MIN_RETURN_BPS}, {SANITY_MAX_RETURN_BPS}] "
                        f"(Provider {chosen.provider}, Symbol {chosen.symbol})."
                    ),
                })
                continue
            source_label = f"backfill:{chosen.provider}:{chosen.symbol}"
            if tr_adjusted:
                source_label += f"+div_estimate_{sub_asset.pre_tr_dividend_yield_bps}bps"
            if dry_run:
                processed.append({
                    "year": year,
                    "sub_asset_class": key,
                    "asset_class": sub_asset.top_level,
                    "provider": chosen.provider,
                    "symbol": chosen.symbol,
                    "return_bps": adjusted_bps,
                    "tr_adjusted": tr_adjusted,
                    "source": source_label,
                    "action": "dry_run",
                    "written": False,
                })
            else:
                written, action = _upsert_sub_asset_return(
                    db,
                    year=year,
                    asset_class=sub_asset.top_level,
                    sub_asset_class=key,
                    return_bps=adjusted_bps,
                    source=source_label,
                    overwrite=overwrite,
                )
                processed.append({
                    "year": year,
                    "sub_asset_class": key,
                    "asset_class": sub_asset.top_level,
                    "provider": chosen.provider,
                    "symbol": chosen.symbol,
                    "return_bps": adjusted_bps,
                    "tr_adjusted": tr_adjusted,
                    "source": source_label,
                    "action": action,
                    "written": written,
                })

    finished_at = datetime.utcnow().isoformat()
    return {
        "from_year": from_year,
        "to_year": to_year,
        "active_providers": sorted(active_providers),
        "sub_assets_requested": requested_keys,
        "processed": processed,
        "errors": errors,
        "summary": {
            "rows_written": sum(1 for p in processed if p["written"]),
            "rows_skipped": sum(1 for p in processed if not p["written"]),
            "tr_adjusted_count": sum(1 for p in processed if p.get("tr_adjusted")),
            "error_count": len(errors),
        },
        "started_at": started_at,
        "finished_at": finished_at,
        "dry_run": dry_run,
    }
