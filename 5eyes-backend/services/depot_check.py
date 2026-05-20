"""Sprint U-P12 (2026-05-20): Depot-Check-Engine.

Analysiert das aktuelle IST-Depot eines Mandanten und liefert eine
strukturierte Diversifikations-Analyse:
- Asset-Klassen-Allokation (IST vs SOLL aus TargetAllocation)
- Sub-Asset-Class-Breakdown
- Country-, Sector-, Currency-Exposure (aggregiert aus Produkt-Exposures
  via services.product_exposures)
- Konzentrations-Scoring (HHI pro Dimension)
- Top-Positionen-Tabelle
- Fonds-Charakteristika: gewichtete TER, Duration (Bonds), ESG-Score
- Drift-zu-Soll (pro Bucket: aktuell vs target_bps + Toleranzband-Verstoß)
- Liquiditätsprofil (% Cash, % daily-liquide, % illiquide)

KEINE Datenmodell-Änderungen. Nur Service-Layer auf existierenden
WealthPosition + RecommendationPosition + Product-Tabellen.
"""
from __future__ import annotations

from typing import Iterable, Mapping

from sqlalchemy.orm import Session

from models.allocation import TargetAllocation
from models.mandates import Mandate
from models.review import Product, RecommendationPosition, RecommendationRun
from models.wealth import WealthPosition
from services.product_exposures import (
    aggregate_exposures,
    country_exposure_for_product,
    currency_exposure_for_product,
    herfindahl_hirschman_index,
    sector_exposure_for_product,
)


BUCKET_LABELS = {
    "equities": "Aktien",
    "bonds": "Obligationen",
    "real_estate": "Immobilien",
    "alternatives": "Alternative Anlagen",
    "liquidity": "Liquidität",
}


def _bucket_key_from_product(product: Product) -> str:
    """Mappt Product.asset_class auf den Bucket-Key (englisch)."""
    raw = str(product.asset_class or "").strip().lower()
    aliases = {
        "aktien": "equities", "equities": "equities",
        "obligationen": "bonds", "anleihen": "bonds", "bonds": "bonds",
        "immobilien": "real_estate", "real estate": "real_estate", "real_estate": "real_estate",
        "alternative": "alternatives", "alternativen": "alternatives", "alternatives": "alternatives",
        "liquidität": "liquidity", "liquiditaet": "liquidity",
        "liquides vermoegen": "liquidity", "liquides vermögen": "liquidity",
        "cash": "liquidity", "liquidity": "liquidity",
    }
    return aliases.get(raw, "alternatives")


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def _bucket_from_position_type(position_type: str | None) -> str:
    """Fallback wenn eine WealthPosition kein Produkt referenziert."""
    raw = str(position_type or "").strip().lower()
    aliases = {
        "depot": "equities",
        "aktien": "equities",
        "obligationen": "bonds",
        "anleihen": "bonds",
        "immobilien": "real_estate",
        "alternative": "alternatives",
        "alternativen": "alternatives",
        "vorsorge": "alternatives",
        "kontoguthaben": "liquidity",
        "konto": "liquidity",
        "cash": "liquidity",
        "geldmarktfonds": "liquidity",
    }
    return aliases.get(raw, "liquidity")


def compute_depot_check(db: Session, mandate: Mandate) -> dict:
    """Liefert eine vollständige Depot-Check-Analyse für einen Mandanten.

    Verwendet primär RecommendationPositions (aktuelle Holdings mit
    konkreten Produkten) und fällt zurück auf WealthPositions (allgemeine
    Beratungs-Positionen ohne ISIN/Produkt-Mapping).
    """
    result: dict = {
        "mandate_id": str(getattr(mandate, "id", "") or ""),
        "total_advisory_wealth_rappen": 0,
        "buckets": {},  # bucket → {ist_bps, soll_bps, ist_rappen, drift_bps, in_band, band}
        "country_exposure_bps": {},
        "sector_exposure_bps": {},
        "currency_exposure_bps": {},
        "concentration_hhi": {
            "country": 0,
            "sector": 0,
            "currency": 0,
            "top_positions": 0,
        },
        "top_positions": [],
        "fund_characteristics": {
            "weighted_ter_bps": 0,
            "weighted_duration_years_x10": 0,
            "weighted_esg_score_x10": 0,
            "covered_share_bps": 0,  # % der Positionen mit gepflegtem TER/Duration/ESG
        },
        "liquidity_profile": {
            "daily_bps": 0,
            "weekly_bps": 0,
            "monthly_bps": 0,
            "illiquid_bps": 0,
            "unknown_bps": 0,
        },
        "warnings": [],
    }

    # 1. Aktuelle Holdings laden (RecommendationRun-basiert)
    latest_run = (
        db.query(RecommendationRun)
        .filter(RecommendationRun.mandate_id == mandate.id)
        .order_by(RecommendationRun.created_at.desc())
        .first()
    )
    positions_with_products: list[tuple[RecommendationPosition, Product]] = []
    total_rappen = 0
    if latest_run is not None:
        rec_positions = (
            db.query(RecommendationPosition)
            .filter(RecommendationPosition.run_id == latest_run.id)
            .all()
        )
        product_ids = [p.product_id for p in rec_positions if p.product_id]
        products_map = {}
        if product_ids:
            rows = db.query(Product).filter(Product.id.in_(product_ids)).all()
            products_map = {p.id: p for p in rows}
        for rec_pos in rec_positions:
            prod = products_map.get(rec_pos.product_id)
            if prod is None:
                continue
            current_amount = _safe_int(getattr(rec_pos, "current_amount_rappen", 0))
            if current_amount <= 0:
                # Fallback auf target_amount wenn current_amount nicht gepflegt
                current_amount = _safe_int(getattr(rec_pos, "target_amount_rappen", 0))
            if current_amount > 0:
                positions_with_products.append((rec_pos, prod))
                total_rappen += current_amount

    # 2. Falls keine RecommendationPositions: WealthPositions als Fallback
    wealth_only_positions: list[tuple[WealthPosition, str]] = []
    if not positions_with_products:
        client_id = getattr(mandate, "client_id", None)
        if client_id:
            wp_rows = (
                db.query(WealthPosition)
                .filter(
                    WealthPosition.client_id == client_id,
                    WealthPosition.is_active == 1,
                    WealthPosition.deleted_at.is_(None),
                    WealthPosition.assignment == "Beratungsvermögen",
                )
                .all()
            )
            for wp in wp_rows:
                amount = _safe_int(getattr(wp, "current_value_rappen", 0))
                if amount > 0:
                    wealth_only_positions.append((wp, _bucket_from_position_type(getattr(wp, "position_type", ""))))
                    total_rappen += amount

    result["total_advisory_wealth_rappen"] = total_rappen
    if total_rappen <= 0:
        result["warnings"].append("Kein Beratungsvermögen erfasst. Bitte WealthPositions oder RecommendationRun anlegen.")
        return result

    # 3. Bucket-Aggregation (IST)
    bucket_amounts_rappen: dict[str, int] = {b: 0 for b in BUCKET_LABELS}
    # Plus position_weights für aggregate_exposures (key=position_id)
    position_weights_bps: dict[str, int] = {}
    position_country_exp: dict[str, dict[str, int]] = {}
    position_sector_exp: dict[str, dict[str, int]] = {}
    position_currency_exp: dict[str, dict[str, int]] = {}
    position_records_for_top: list[dict] = []
    ter_weighted_sum = 0
    duration_weighted_sum = 0
    esg_weighted_sum = 0
    covered_amount = 0
    duration_covered_amount = 0
    esg_covered_amount = 0
    liquidity_buckets = {"daily": 0, "weekly": 0, "monthly": 0, "illiquid": 0, "unknown": 0}

    for rec_pos, prod in positions_with_products:
        amount = _safe_int(getattr(rec_pos, "current_amount_rappen", 0)) or _safe_int(getattr(rec_pos, "target_amount_rappen", 0))
        if amount <= 0:
            continue
        bucket = _bucket_key_from_product(prod)
        bucket_amounts_rappen[bucket] = bucket_amounts_rappen.get(bucket, 0) + amount
        weight_bps = int(round(amount / total_rappen * 10000))
        position_weights_bps[rec_pos.id] = weight_bps
        position_country_exp[rec_pos.id] = country_exposure_for_product(
            getattr(prod, "country_exposure_json", None),
            getattr(prod, "sub_asset_class", None),
        )
        position_sector_exp[rec_pos.id] = sector_exposure_for_product(
            getattr(prod, "sector_exposure_json", None),
            getattr(prod, "sub_asset_class", None),
        )
        position_currency_exp[rec_pos.id] = currency_exposure_for_product(
            getattr(prod, "currency_exposure_json", None),
            getattr(prod, "sub_asset_class", None),
            fallback_currency=getattr(prod, "currency", None),
        )
        position_records_for_top.append({
            "position_id": rec_pos.id,
            "product_name": str(getattr(prod, "product_name", "—") or "—"),
            "isin": str(getattr(prod, "isin", "") or ""),
            "asset_class": str(getattr(prod, "asset_class", "") or ""),
            "sub_asset_class": str(getattr(prod, "sub_asset_class", "") or ""),
            "currency": str(getattr(prod, "currency", "") or ""),
            "amount_rappen": amount,
            "weight_bps": weight_bps,
            "ter_bps": _safe_int(getattr(prod, "ter_bps", 0)),
        })
        # Fund-Characteristics gewichtet
        ter = _safe_int(getattr(prod, "ter_bps", 0))
        if ter > 0:
            ter_weighted_sum += ter * amount
            covered_amount += amount
        duration = _safe_int(getattr(prod, "duration_years_x10", 0))
        if duration > 0:
            duration_weighted_sum += duration * amount
            duration_covered_amount += amount
        esg = _safe_int(getattr(prod, "esg_score_x10", 0))
        if esg > 0:
            esg_weighted_sum += esg * amount
            esg_covered_amount += amount
        # Liquidity-Tier
        tier = str(getattr(prod, "liquidity_tier", "") or "").strip().lower()
        if tier in liquidity_buckets:
            liquidity_buckets[tier] += amount
        elif bucket == "liquidity":
            liquidity_buckets["daily"] += amount
        elif bucket in ("equities", "bonds") and (getattr(prod, "product_type", "") in ("ETF", "Fonds")):
            liquidity_buckets["daily"] += amount
        elif bucket == "real_estate" and "fonds" in str(getattr(prod, "product_type", "")).lower():
            liquidity_buckets["weekly"] += amount
        elif bucket == "alternatives":
            liquidity_buckets["monthly"] += amount
        else:
            liquidity_buckets["unknown"] += amount

    # Fallback aus WealthPositions (kein Produkt → keine Exposure-Tiefe)
    for wp, bucket in wealth_only_positions:
        amount = _safe_int(getattr(wp, "current_value_rappen", 0))
        bucket_amounts_rappen[bucket] = bucket_amounts_rappen.get(bucket, 0) + amount
        weight_bps = int(round(amount / total_rappen * 10000))
        position_records_for_top.append({
            "position_id": wp.id,
            "product_name": str(getattr(wp, "label", "—") or "—"),
            "isin": "",
            "asset_class": BUCKET_LABELS.get(bucket, bucket),
            "sub_asset_class": "",
            "currency": str(getattr(wp, "currency", "") or "CHF"),
            "amount_rappen": amount,
            "weight_bps": weight_bps,
            "ter_bps": 0,
        })
        liquidity_buckets["unknown"] += amount

    # 4. Bucket-Drift gegen TargetAllocation (Soll)
    ta = (
        db.query(TargetAllocation)
        .filter(
            TargetAllocation.mandate_id == mandate.id,
            TargetAllocation.is_current == 1,
            TargetAllocation.deleted_at.is_(None),
        )
        .first()
    )
    for bucket in BUCKET_LABELS:
        amount_rappen = bucket_amounts_rappen.get(bucket, 0)
        ist_bps = int(round(amount_rappen / total_rappen * 10000)) if total_rappen > 0 else 0
        soll_bps = 0
        band_min_bps = 0
        band_max_bps = 0
        if ta is not None:
            soll_bps = _safe_int(getattr(ta, f"target_{bucket}_bps", 0))
            band_min_bps = _safe_int(getattr(ta, f"band_{bucket}_min_bps", 0))
            band_max_bps = _safe_int(getattr(ta, f"band_{bucket}_max_bps", 0))
        in_band = (band_min_bps <= ist_bps <= band_max_bps) if (band_min_bps or band_max_bps) else None
        result["buckets"][bucket] = {
            "label": BUCKET_LABELS[bucket],
            "ist_bps": ist_bps,
            "soll_bps": soll_bps,
            "ist_rappen": amount_rappen,
            "drift_bps": ist_bps - soll_bps,
            "band_min_bps": band_min_bps,
            "band_max_bps": band_max_bps,
            "in_band": in_band,
        }

    # 5. Aggregierte Country/Sector/Currency-Exposures
    if position_weights_bps:
        result["country_exposure_bps"] = aggregate_exposures(position_weights_bps, position_country_exp)
        result["sector_exposure_bps"] = aggregate_exposures(position_weights_bps, position_sector_exp)
        result["currency_exposure_bps"] = aggregate_exposures(position_weights_bps, position_currency_exp)

    # 6. Konzentrations-HHI pro Dimension
    result["concentration_hhi"]["country"] = herfindahl_hirschman_index(result["country_exposure_bps"])
    result["concentration_hhi"]["sector"] = herfindahl_hirschman_index(result["sector_exposure_bps"])
    result["concentration_hhi"]["currency"] = herfindahl_hirschman_index(result["currency_exposure_bps"])
    # Top-Positionen-HHI: über alle Position-Weights
    pos_weight_dict = {rec["position_id"]: rec["weight_bps"] for rec in position_records_for_top}
    result["concentration_hhi"]["top_positions"] = herfindahl_hirschman_index(pos_weight_dict)

    # 7. Top-Positionen (sortiert nach amount, top 10)
    position_records_for_top.sort(key=lambda p: -p["amount_rappen"])
    result["top_positions"] = position_records_for_top[:10]

    # 8. Fund-Characteristics
    if covered_amount > 0:
        result["fund_characteristics"]["weighted_ter_bps"] = int(round(ter_weighted_sum / covered_amount))
        result["fund_characteristics"]["covered_share_bps"] = int(round(covered_amount / total_rappen * 10000))
    if duration_covered_amount > 0:
        result["fund_characteristics"]["weighted_duration_years_x10"] = int(round(duration_weighted_sum / duration_covered_amount))
    if esg_covered_amount > 0:
        result["fund_characteristics"]["weighted_esg_score_x10"] = int(round(esg_weighted_sum / esg_covered_amount))

    # 9. Liquidity-Profil als bps
    for tier, amount in liquidity_buckets.items():
        result["liquidity_profile"][f"{tier}_bps"] = int(round(amount / total_rappen * 10000)) if total_rappen > 0 else 0

    # 10. Warnings: Concentration-Risiken
    if result["concentration_hhi"]["country"] > 5000:
        result["warnings"].append(
            f"Hohe Länder-Konzentration (HHI={result['concentration_hhi']['country']}, >5000 = Single-Country-dominiert)"
        )
    if result["concentration_hhi"]["sector"] > 2500:
        result["warnings"].append(
            f"Hohe Sektor-Konzentration (HHI={result['concentration_hhi']['sector']}, >2500 = wenig diversifiziert)"
        )
    if result["concentration_hhi"]["top_positions"] > 1500:
        top_3_weight = sum(p["weight_bps"] for p in result["top_positions"][:3])
        result["warnings"].append(
            f"Top-3-Positionen = {top_3_weight/100:.1f}% des Depots (Konzentrations-Risiko)"
        )
    if result["liquidity_profile"]["illiquid_bps"] > 3000:
        result["warnings"].append(
            f"Illiquider Anteil = {result['liquidity_profile']['illiquid_bps']/100:.1f}% (>30%)"
        )
    # Bandbreiten-Verstöße
    for bucket_key, bucket_info in result["buckets"].items():
        if bucket_info.get("in_band") is False:
            ist_pct = bucket_info["ist_bps"] / 100
            band_text = f"{bucket_info['band_min_bps']/100:.1f}%-{bucket_info['band_max_bps']/100:.1f}%"
            result["warnings"].append(
                f"{bucket_info['label']} außerhalb Toleranzband: {ist_pct:.1f}% (Band: {band_text})"
            )

    return result
