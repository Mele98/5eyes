"""Live-Rebalancing Payload-Bau — extrahiert aus ``services/portfolio_engine.py``.

ADR-014 (`docs/adr/ADR-014-engine-module-split-plan.md`), Schritt 2 von 8
("Payload-Bau Phase A — Live-Rebalancing"). Dieses Modul ist eine
**byte-fuer-byte Extraktion** der 17 Funktionen, die im Original-Modul die
Live-Rebalancing-Payload aufgebaut haben (Referenzpreis-/Holdings-Snapshots,
Buy/Sell/Hold-Klassifikation, Bucket-/Positions-Drift, Handlungsempfehlungen).

**0 Zeilen Fachlogik-Aenderung** — nur die Datei-Grenze wurde verschoben.
Jede Funktion wurde unveraendert aus `services/portfolio_engine.py` kopiert
(vormals Zeilen 723-1256, Stand vor dieser Extraktion; die Zeilen davor
wurden durch die vorherige Extraktion des Gesamtvermoegen-Clusters nicht
verschoben, da jener Cluster physisch spaeter im File stand).

Abhaengigkeiten: nur CORE-Helfer aus `services.portfolio_engine`
(`StoredReferencePrice`, `BUCKET_LABELS`, `_bucket_key`, `_bps`,
`_amount_from_weight_bps`) sowie externe Preis-/Produkt-Services
(`price_updater`, `services.product_market_data`). Keine Abhaengigkeit auf
CMA/House-Matrix/Reserve/Monte-Carlo.

**Zirkular-Import-Hinweis (Lektion aus Schritt 1):** die CORE-Namen aus
`services.portfolio_engine` werden hier bewusst NICHT auf Modul-Ebene
importiert, sondern lazy (funktionslokal) innerhalb jeder Funktion, die sie
tatsaechlich zur Laufzeit braucht. Grund: `portfolio_engine.py` re-exportiert
am Dateiende die Namen aus diesem Modul; wuerde dieses Modul umgekehrt CORE-
Namen auf Modul-Ebene aus `portfolio_engine.py` importieren, koennte ein
Import-Einstieg ueber DIESES Modul (statt ueber `portfolio_engine.py`) zu
einem ImportError auf einem partiell initialisierten Modul fuehren. Reine
Typ-Hinweise (kein Laufzeit-Gebrauch) laufen stattdessen ueber
`from __future__ import annotations` + `TYPE_CHECKING`.

Public entry point: `build_live_rebalancing_payload` (3 interne Call-Sites
in `portfolio_engine.py`, alle in Orchestratoren: `generate_target_allocation`,
`build_target_payload_from_allocation`, `generate_recommendation_run`).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from models.allocation import TargetAllocation
from models.review import (
    PriceHistory,
    Product,
    RecommendationHolding,
    RecommendationPosition,
    RecommendationRun,
)
from price_updater import latest_price_snapshot, parse_iso_date, summarize_price_quality
from services.product_market_data import resolve_market_profile

if TYPE_CHECKING:
    from services.portfolio_engine import StoredReferencePrice


def _reference_price_snapshot_for_run(
    db: Session,
    product_ids: list[str],
    run_created_at: str | None,
) -> dict[str, PriceHistory]:
    if not product_ids:
        return {}
    run_anchor = str(run_created_at or "")[:10]
    rows = db.query(PriceHistory).filter(
        PriceHistory.product_id.in_(product_ids),
    ).order_by(
        PriceHistory.product_id.asc(),
        PriceHistory.price_date.desc(),
        PriceHistory.fetched_at.desc(),
    ).all()
    snapshots: dict[str, PriceHistory] = {}
    for row in rows:
        if row.product_id in snapshots:
            continue
        if not run_anchor:
            snapshots[row.product_id] = row
            continue
        if str(row.price_date or "") > run_anchor:
            continue
        snapshots[row.product_id] = row
    return snapshots


def _stored_reference_price_for_position(position: RecommendationPosition) -> StoredReferencePrice | None:
    from services.portfolio_engine import StoredReferencePrice

    price_rappen = getattr(position, "reference_price_rappen", None)
    if price_rappen is None:
        return None
    try:
        price_rappen_int = int(price_rappen or 0)
    except (TypeError, ValueError):
        return None
    if price_rappen_int <= 0:
        return None
    return StoredReferencePrice(
        price_date=getattr(position, "reference_price_date", None),
        price_rappen=price_rappen_int,
        source=getattr(position, "reference_price_source", None),
        fetched_at=getattr(position, "reference_price_fetched_at", None),
    )


def _holdings_snapshot_for_run(
    db: Session,
    run_id: str,
    position_ids: list[str],
) -> dict[str, RecommendationHolding]:
    if not position_ids:
        return {}
    rows = db.query(RecommendationHolding).filter(
        RecommendationHolding.run_id == run_id,
        RecommendationHolding.recommendation_position_id.in_(position_ids),
    ).order_by(
        RecommendationHolding.recommendation_position_id.asc(),
        RecommendationHolding.updated_at.desc(),
    ).all()
    holdings: dict[str, RecommendationHolding] = {}
    seen: set[str] = set()
    for row in rows:
        if row.recommendation_position_id in seen:
            continue
        seen.add(row.recommendation_position_id)
        if row.deleted_at is None:
            holdings[row.recommendation_position_id] = row
    return holdings


def _latest_holdings_by_product_for_mandate(
    db: Session,
    mandate_id: str,
) -> dict[str, RecommendationHolding]:
    rows = db.query(RecommendationHolding).join(
        RecommendationRun,
        RecommendationRun.id == RecommendationHolding.run_id,
    ).filter(
        RecommendationRun.mandate_id == mandate_id,
    ).order_by(
        RecommendationHolding.product_id.asc(),
        RecommendationHolding.updated_at.desc(),
    ).all()
    holdings: dict[str, RecommendationHolding] = {}
    seen: set[str] = set()
    for row in rows:
        if row.product_id in seen:
            continue
        seen.add(row.product_id)
        if row.deleted_at is None:
            holdings[row.product_id] = row
    return holdings


def _units_milli_from_amount(amount_rappen: int, reference_price_rappen: int | None) -> int | None:
    if amount_rappen <= 0 or not reference_price_rappen or reference_price_rappen <= 0:
        return None
    return int(round(amount_rappen * 1000 / reference_price_rappen))


def _value_from_units_milli(units_milli: int | None, price_rappen: int | None, fallback_amount_rappen: int = 0) -> int:
    if not units_milli or not price_rappen or price_rappen <= 0:
        return max(0, int(fallback_amount_rappen or 0))
    return max(0, int(round(units_milli * price_rappen / 1000)))


def _canonical_asset_class_label(value: str | None) -> str:
    from services.portfolio_engine import BUCKET_LABELS, _bucket_key

    key = _bucket_key(value)
    return BUCKET_LABELS.get(key or "", str(value or "Unbekannt"))


def _rebalancing_action(delta_weight_bps: int, rebalance_amount_rappen: int, price_available: bool) -> str:
    return _rebalancing_action_meta(delta_weight_bps, rebalance_amount_rappen, price_available)[1]


def _rebalancing_action_meta(delta_weight_bps: int, rebalance_amount_rappen: int, price_available: bool) -> tuple[str, str]:
    if not price_available:
        return "MISSING_PRICE", "Preis fehlt"
    if abs(delta_weight_bps) < 25 and abs(rebalance_amount_rappen) < 5000:
        return "HOLD", "Im Soll"
    if rebalance_amount_rappen > 0:
        return "BUY", "Aufbauen"
    if rebalance_amount_rappen < 0:
        return "SELL", "Reduzieren"
    return "CHECK", "Beobachten"


def _aligned_reference_price(
    reference_price: PriceHistory | StoredReferencePrice | None,
    latest_price: PriceHistory | None,
    lookup_mode: str | None,
) -> tuple[PriceHistory | StoredReferencePrice | None, bool]:
    if not latest_price:
        return reference_price, False
    if not reference_price:
        return latest_price, latest_price is not None

    reference_rappen = int(reference_price.price_rappen or 0)
    latest_rappen = int(latest_price.price_rappen or 0)
    if reference_rappen <= 0 or latest_rappen <= 0:
        return latest_price, True

    ratio = max(reference_rappen, latest_rappen) / max(1, min(reference_rappen, latest_rappen))
    recalibration_threshold = 1.5 if str(lookup_mode or "").strip() in {"proxy", "synthetic_par"} else 3
    if ratio < recalibration_threshold:
        return reference_price, False

    reference_source = str(reference_price.source or "").strip()
    latest_source = str(latest_price.source or "").strip()
    if str(lookup_mode or "").strip() in {"proxy", "synthetic_par"}:
        return latest_price, True
    if reference_source and latest_source and reference_source != latest_source:
        return latest_price, True
    return reference_price, False


def _load_live_rebalancing_sources(
    db: Session,
    run: RecommendationRun,
    recommendation_positions: list[RecommendationPosition],
) -> dict:
    product_ids = [position.product_id for position in recommendation_positions if position.product_id]
    position_ids = [position.id for position in recommendation_positions if position.id]
    if not product_ids:
        return {}
    market_data_quality = summarize_price_quality(db, product_ids)
    return {
        "product_ids": product_ids,
        "position_ids": position_ids,
        "products_by_id": {
            product.id: product
            for product in db.query(Product).filter(Product.id.in_(product_ids)).all()
        },
        "latest_prices": latest_price_snapshot(db, product_ids),
        "reference_prices": _reference_price_snapshot_for_run(db, product_ids, run.created_at),
        "holdings_by_position_id": _holdings_snapshot_for_run(db, run.id, position_ids),
        "holdings_by_product_id": _latest_holdings_by_product_for_mandate(db, run.mandate_id),
        "market_data_quality": market_data_quality,
        "stale_after_days": int(market_data_quality.get("stale_after_days") or 5),
        "today": date.today(),
    }


def _build_live_rebalancing_entry(
    position: RecommendationPosition,
    product: Product,
    holding: RecommendationHolding | None,
    latest_price: PriceHistory | None,
    reference_price: PriceHistory | StoredReferencePrice | None,
    reference_recalibrated: bool,
    target_amount_rappen: int,
    target_weight_bps: int,
    stale_after_days: int,
    today: date,
) -> tuple[dict, dict]:
    latest_price_rappen = int(latest_price.price_rappen or 0) if latest_price else None
    reference_price_date = reference_price.price_date if reference_price else None
    reference_price_rappen = int(reference_price.price_rappen or 0) if reference_price else None
    reference_price_source = getattr(reference_price, "source", None) if reference_price else None
    reference_price_fetched_at = getattr(reference_price, "fetched_at", None) if reference_price else None

    holding_present = False
    holding_source = None
    holding_as_of_date = None
    holding_units_milli = None
    holding_market_value_rappen = None
    holding_avg_cost_price_rappen = None
    holding_depot_bank = None
    holding_custody_account_number = None
    holding_notes = None
    valuation_basis = "implied_from_target"
    current_units_milli = None

    if holding:
        raw_units = int(holding.units_milli or 0)
        raw_market_value = int(holding.market_value_rappen or 0)
        holding_present = raw_units > 0 or raw_market_value > 0
        if holding_present:
            holding_source = str(holding.source or "").strip() or "manual"
            holding_as_of_date = str(holding.as_of_date or "").strip() or None
            holding_units_milli = raw_units if raw_units > 0 else None
            holding_market_value_rappen = raw_market_value if raw_market_value > 0 else None
            holding_avg_cost_price_rappen = int(holding.avg_cost_price_rappen or 0) or None
            holding_depot_bank = str(holding.depot_bank or "").strip() or None
            holding_custody_account_number = str(holding.custody_account_number or "").strip() or None
            holding_notes = str(holding.notes or "").strip() or None
            if holding_avg_cost_price_rappen:
                reference_price_rappen = holding_avg_cost_price_rappen
                reference_price_date = holding_as_of_date or reference_price_date
                reference_recalibrated = False
            if holding_units_milli:
                current_units_milli = holding_units_milli
                valuation_basis = "actual_holding_units"
            else:
                current_units_milli = _units_milli_from_amount(
                    holding_market_value_rappen or 0,
                    latest_price_rappen or reference_price_rappen,
                )
                # rp-ueberarbeitung: semantisch klarer — die units sind IMPLIED
                # vom market_value (nicht direkt vom Holding), daher 'implied_'.
                valuation_basis = "implied_from_holding_market_value"

    implied_units_milli = _units_milli_from_amount(target_amount_rappen, reference_price_rappen)
    if not current_units_milli:
        current_units_milli = implied_units_milli
        if not holding_present:
            valuation_basis = "implied_from_target"

    reference_value_rappen = _value_from_units_milli(current_units_milli, reference_price_rappen, target_amount_rappen)
    current_market_value_rappen = _value_from_units_milli(
        current_units_milli,
        latest_price_rappen or reference_price_rappen,
        holding_market_value_rappen or reference_value_rappen or target_amount_rappen,
    )

    price_date = parse_iso_date(latest_price.price_date) if latest_price else None
    price_age_days = (today - price_date).days if price_date else None
    price_is_fresh = bool(price_age_days is not None and price_age_days <= stale_after_days)
    price_change_bps = None
    if latest_price_rappen and reference_price_rappen and reference_price_rappen > 0:
        price_change_bps = int(round((latest_price_rappen / reference_price_rappen - 1) * 10000))

    entry = {
        "id": position.id,
        "product_id": product.id,
        "product_name": product.product_name,
        "asset_class": _canonical_asset_class_label(product.asset_class),
        "sub_asset_class": product.sub_asset_class,
        "target_weight_bps": target_weight_bps,
        "target_amount_rappen": target_amount_rappen,
        "reference_price_date": reference_price_date,
        "reference_price_rappen": reference_price_rappen,
        "reference_price_source": reference_price_source,
        "reference_lookup_mode": getattr(position, "reference_lookup_mode", None),
        "reference_price_fetched_at": reference_price_fetched_at,
        "reference_recalibrated": reference_recalibrated,
        "latest_price_date": latest_price.price_date if latest_price else None,
        "latest_price_rappen": latest_price_rappen,
        "price_age_days": price_age_days,
        "price_is_fresh": price_is_fresh if latest_price else None,
        "holding_present": holding_present,
        "holding_source": holding_source,
        "holding_as_of_date": holding_as_of_date,
        "holding_units_milli": holding_units_milli,
        "current_units_milli": current_units_milli,
        "holding_market_value_rappen": holding_market_value_rappen,
        "holding_avg_cost_price_rappen": holding_avg_cost_price_rappen,
        "holding_depot_bank": holding_depot_bank,
        "holding_custody_account_number": holding_custody_account_number,
        "holding_notes": holding_notes,
        "valuation_basis": valuation_basis,
        "implied_units_milli": implied_units_milli,
        "current_market_value_rappen": current_market_value_rappen,
        "price_change_bps": price_change_bps,
    }
    stats = {
        "current_total_value_rappen": current_market_value_rappen,
        "missing_prices_count": 0 if latest_price else 1,
        "stale_positions_count": 1 if latest_price and not price_is_fresh else 0,
        "priced_positions_count": 1 if latest_price else 0,
        "as_of_dates": [latest_price.price_date] if latest_price and latest_price.price_date else [],
        "recalibrated_positions_count": 1 if reference_recalibrated else 0,
        "holding_positions_count": 1 if holding_present else 0,
        "implied_positions_count": 0 if holding_present else 1,
    }
    return entry, stats


def _build_live_bucket_targets(allocation: TargetAllocation) -> dict[str, dict[str, int]]:
    return {
        "Aktien": {
            "target_weight_bps": int(allocation.target_equities_bps or 0),
            "band_min_bps": int(allocation.band_equities_min_bps or 0),
            "band_max_bps": int(allocation.band_equities_max_bps or 0),
        },
        "Obligationen": {
            "target_weight_bps": int(allocation.target_bonds_bps or 0),
            "band_min_bps": int(allocation.band_bonds_min_bps or 0),
            "band_max_bps": int(allocation.band_bonds_max_bps or 0),
        },
        "Immobilien": {
            "target_weight_bps": int(allocation.target_real_estate_bps or 0),
            "band_min_bps": int(allocation.band_real_estate_min_bps or 0),
            "band_max_bps": int(allocation.band_real_estate_max_bps or 0),
        },
        "Alternative": {
            "target_weight_bps": int(allocation.target_alternatives_bps or 0),
            "band_min_bps": int(allocation.band_alternatives_min_bps or 0),
            "band_max_bps": int(allocation.band_alternatives_max_bps or 0),
        },
        "Liquiditaet": {
            "target_weight_bps": int(allocation.target_liquidity_bps or 0),
            "band_min_bps": int(allocation.band_liquidity_min_bps or 0),
            "band_max_bps": int(allocation.band_liquidity_max_bps or 0),
        },
    }


def _build_live_bucket_drifts(
    allocation: TargetAllocation,
    entries: list[dict],
    live_total_value_rappen: int,
) -> tuple[list[dict], list[str], int]:
    from services.portfolio_engine import _amount_from_weight_bps, _bps

    bucket_targets = _build_live_bucket_targets(allocation)
    bucket_current_values: defaultdict[str, int] = defaultdict(int)
    for entry in entries:
        bucket_current_values[str(entry["asset_class"])] += int(entry["current_market_value_rappen"] or 0)

    bucket_drifts = []
    breached_asset_classes = []
    total_rebalance_abs_rappen = 0
    for asset_class in ("Aktien", "Obligationen", "Immobilien", "Alternative", "Liquiditaet"):
        config = bucket_targets[asset_class]
        current_value_rappen = int(bucket_current_values.get(asset_class) or 0)
        current_weight_bps = _bps(current_value_rappen, live_total_value_rappen)
        target_weight_bps = int(config["target_weight_bps"])
        target_market_value_rappen = _amount_from_weight_bps(live_total_value_rappen, target_weight_bps)
        rebalance_amount_rappen = target_market_value_rappen - current_value_rappen
        delta_weight_bps = current_weight_bps - target_weight_bps
        min_weight = int(config["band_min_bps"])
        max_weight = int(config["band_max_bps"])
        breach_bps = 0
        # Zero bands = "no constraint" (Bucket nicht aktiv konfiguriert).
        if min_weight == 0 and max_weight == 0:
            breach_bps = 0
        elif current_weight_bps < min_weight:
            breach_bps = min_weight - current_weight_bps
        elif current_weight_bps > max_weight:
            breach_bps = current_weight_bps - max_weight
        breached = breach_bps > 0
        if breached:
            breached_asset_classes.append(asset_class)
        total_rebalance_abs_rappen += abs(rebalance_amount_rappen)
        bucket_drifts.append(
            {
                "asset_class": asset_class,
                "current_weight_bps": current_weight_bps,
                "target_weight_bps": target_weight_bps,
                "band_min_bps": min_weight,
                "band_max_bps": max_weight,
                "current_market_value_rappen": current_value_rappen,
                "target_market_value_rappen": target_market_value_rappen,
                "delta_weight_bps": delta_weight_bps,
                "rebalance_amount_rappen": rebalance_amount_rappen,
                "breached": breached,
                "breach_bps": breach_bps,
            }
        )
    return bucket_drifts, breached_asset_classes, total_rebalance_abs_rappen


def _build_live_position_drifts(entries: list[dict], live_total_value_rappen: int) -> list[dict]:
    from services.portfolio_engine import _amount_from_weight_bps, _bps

    position_drifts = []
    for entry in entries:
        current_weight_bps = _bps(int(entry["current_market_value_rappen"] or 0), live_total_value_rappen)
        rebalance_amount_rappen = _amount_from_weight_bps(live_total_value_rappen, int(entry["target_weight_bps"] or 0)) - int(entry["current_market_value_rappen"] or 0)
        delta_weight_bps = current_weight_bps - int(entry["target_weight_bps"] or 0)
        latest_price_available = entry["latest_price_rappen"] is not None or entry["reference_price_rappen"] is not None
        action_code, action_label = _rebalancing_action_meta(delta_weight_bps, rebalance_amount_rappen, latest_price_available)
        position_drifts.append(
            {
                **entry,
                "current_weight_bps": current_weight_bps,
                "delta_weight_bps": delta_weight_bps,
                "rebalance_amount_rappen": rebalance_amount_rappen,
                "rebalance_action": action_label,
                "rebalance_action_code": action_code,
                "rebalance_action_label": action_label,
            }
        )
    return sorted(position_drifts, key=lambda item: abs(int(item["rebalance_amount_rappen"] or 0)), reverse=True)


def _build_live_action_summary(bucket_drifts: list[dict]) -> list[str]:
    action_summary = []
    for bucket in sorted(bucket_drifts, key=lambda item: abs(int(item["rebalance_amount_rappen"] or 0)), reverse=True):
        if abs(int(bucket["rebalance_amount_rappen"] or 0)) < 5000:
            continue
        direction = "aufbauen" if int(bucket["rebalance_amount_rappen"]) > 0 else "reduzieren"
        amount_chf = int(round(abs(int(bucket["rebalance_amount_rappen"])) / 100))
        band_note = " / Band verletzt" if bucket["breached"] else ""
        action_summary.append(
            f"{bucket['asset_class']} {direction}: ca. CHF {amount_chf:,.0f}{band_note}".replace(",", "'")
        )
    if not action_summary:
        action_summary.append("Live-Bewertung liegt aktuell innerhalb der strategischen Zielbandbreiten.")
    return action_summary


def build_live_rebalancing_payload(
    db: Session,
    allocation: TargetAllocation,
    run: RecommendationRun,
    advisory_wealth_rappen: int,
    positions: list[RecommendationPosition] | None = None,
) -> dict | None:
    from services.portfolio_engine import _amount_from_weight_bps

    recommendation_positions = positions or db.query(RecommendationPosition).filter(
        RecommendationPosition.run_id == run.id,
    ).order_by(RecommendationPosition.target_weight_bps.desc()).all()
    if not recommendation_positions:
        return None

    sources = _load_live_rebalancing_sources(db, run, recommendation_positions)
    if not sources:
        return None

    entries: list[dict] = []
    aggregate = {
        "current_total_value_rappen": 0,
        "missing_prices_count": 0,
        "stale_positions_count": 0,
        "priced_positions_count": 0,
        "as_of_dates": [],
        "recalibrated_positions_count": 0,
        "holding_positions_count": 0,
        "implied_positions_count": 0,
    }

    for position in recommendation_positions:
        product = sources["products_by_id"].get(position.product_id)
        if not product:
            continue
        market_profile = resolve_market_profile(product)
        target_weight_bps = int(position.target_weight_bps or 0)
        target_amount_rappen = int(position.target_amount_rappen or 0)
        if target_amount_rappen <= 0:
            target_amount_rappen = _amount_from_weight_bps(advisory_wealth_rappen, target_weight_bps)
        holding = sources["holdings_by_position_id"].get(position.id) or sources["holdings_by_product_id"].get(position.product_id)
        latest_price = sources["latest_prices"].get(product.id)
        reference_price, reference_recalibrated = _aligned_reference_price(
            _stored_reference_price_for_position(position) or sources["reference_prices"].get(product.id),
            latest_price,
            market_profile.get("lookup_mode"),
        )
        entry, stats = _build_live_rebalancing_entry(
            position=position,
            product=product,
            holding=holding,
            latest_price=latest_price,
            reference_price=reference_price,
            reference_recalibrated=reference_recalibrated,
            target_amount_rappen=target_amount_rappen,
            target_weight_bps=target_weight_bps,
            stale_after_days=sources["stale_after_days"],
            today=sources["today"],
        )
        entries.append(entry)
        aggregate["current_total_value_rappen"] += stats["current_total_value_rappen"]
        aggregate["missing_prices_count"] += stats["missing_prices_count"]
        aggregate["stale_positions_count"] += stats["stale_positions_count"]
        aggregate["priced_positions_count"] += stats["priced_positions_count"]
        aggregate["as_of_dates"].extend(stats["as_of_dates"])
        aggregate["recalibrated_positions_count"] += stats["recalibrated_positions_count"]
        aggregate["holding_positions_count"] += stats["holding_positions_count"]
        aggregate["implied_positions_count"] += stats["implied_positions_count"]

    live_total_value_rappen = aggregate["current_total_value_rappen"] or max(
        advisory_wealth_rappen,
        sum(int(item["target_amount_rappen"] or 0) for item in entries),
    )
    if live_total_value_rappen <= 0:
        return None

    bucket_drifts, breached_asset_classes, total_rebalance_abs_rappen = _build_live_bucket_drifts(
        allocation=allocation,
        entries=entries,
        live_total_value_rappen=live_total_value_rappen,
    )
    position_drifts = _build_live_position_drifts(entries, live_total_value_rappen)
    action_summary = _build_live_action_summary(bucket_drifts)

    return {
        "as_of_date": max(aggregate["as_of_dates"]) if aggregate["as_of_dates"] else None,
        "reference_anchor_date": str(run.created_at or "")[:10] or None,
        "methodology": (
            f"Echte Bestandsbasis fuer {aggregate['holding_positions_count']} Position(en); "
            f"{aggregate['implied_positions_count']} Position(en) weiterhin implizit aus Zielbetrag und Referenzpreis zum Run-Zeitpunkt. "
            "Live-Werte aus dem letzten verfuegbaren Preis-Snapshot."
        ) + (" Referenzanker wurden fuer einzelne Proxy-/Synthetic-Positionen auf das aktuelle Preisregime rekalibriert." if aggregate["recalibrated_positions_count"] else ""),
        "live_total_value_rappen": live_total_value_rappen,
        "priced_positions_count": aggregate["priced_positions_count"],
        "stale_positions_count": aggregate["stale_positions_count"],
        "missing_prices_count": aggregate["missing_prices_count"],
        "holding_positions_count": aggregate["holding_positions_count"],
        "implied_positions_count": aggregate["implied_positions_count"],
        "turnover_required_rappen": int(round(total_rebalance_abs_rappen / 2)),
        "breached_asset_classes": breached_asset_classes,
        "action_summary": action_summary,
        "market_data_quality": sources["market_data_quality"],
        "recalibrated_positions_count": aggregate["recalibrated_positions_count"],
        "bucket_drifts": bucket_drifts,
        "position_drifts": position_drifts,
    }
