"""ESG-SEED-PROVENANCE-001 (CIO-Entscheid 2026-10-18, ESG-Review C5 / F P0-4).

Die ESG-Werte des Seed-Katalogs (``DEFAULT_CATALOG_PRODUCTS`` in
services/portfolio_engine.py: SFDR-Klasse, ESG-Rating, daraus abgeleitete
Themen-Tags; Score und Klima-Benchmark setzt der Seed nicht) wurden ohne
Quelle und ohne Stichtag gesetzt. Sie gelten als UNBELEGT.

Bewusst OHNE Schemaaenderung: der Status wird aus bestehenden Feldern
abgeleitet -- ein globales Katalogprodukt (``tenant_id IS NULL``) mit dem
Namen eines Seed-Eintrags, dessen ESG-Feld noch exakt den Seed-Wert traegt,
ist fuer dieses Feld ``seed_unverified``. Ein gleichlautend erneut erfasster
Wert ist davon nicht unterscheidbar und bleibt konservativ unbelegt. Es
werden keine Werte veraendert oder erfunden.

Status (Produktebene):
* ``seed_unverified``      -- mindestens ein ESG-Feld traegt den Seed-Wert.
* ``maintained_no_source`` -- ESG-Felder gepflegt, aber nicht aus dem Seed;
  eine Quelle/ein Stichtag wird im Katalog (noch) nicht erfasst.
* ``not_maintained``       -- keine ESG-Angaben.

Wirkung: Berater sehen den Status (Produktkatalog, Run-Warnung
``ESG_DATA_SEED_UNVERIFIED``); Kundendokumente behaupten auf unbelegten
Seed-Daten nicht, dass ein ESG-Kriterium erfuellt sei
(:func:`customer_esg_data_caveat`). Der Produktfilter bleibt unveraendert
(ob Seed-Daten in produktiven Tenants einen ESG-Modus erfuellen duerfen, ist
ein offener Data-Owner-Entscheid, Review H6).
"""
from __future__ import annotations

from functools import lru_cache

ESG_DATA_STATUS_SEED_UNVERIFIED = "seed_unverified"
ESG_DATA_STATUS_MAINTAINED_NO_SOURCE = "maintained_no_source"
ESG_DATA_STATUS_NOT_MAINTAINED = "not_maintained"
ESG_DATA_SEED_UNVERIFIED = "ESG_DATA_SEED_UNVERIFIED"

ESG_DATA_FIELDS: tuple[str, ...] = (
    "sfdr_class", "esg_rating", "esg_score_x10", "climate_benchmark", "theme_tags",
)


@lru_cache(maxsize=1)
def _seed_esg_values() -> dict[str, dict]:
    from services.portfolio_engine import DEFAULT_CATALOG_PRODUCTS
    from services.portfolio_engine_payload import default_catalog_theme_tags, parse_theme_tags

    values: dict[str, dict] = {}
    for name, _provider, _ptype, _ac, sub_asset_class, _cur, _ter, sfdr, rating in DEFAULT_CATALOG_PRODUCTS:
        values[name] = {
            "sfdr_class": sfdr,
            "esg_rating": rating,
            "esg_score_x10": None,
            "climate_benchmark": None,
            "theme_tags": parse_theme_tags(default_catalog_theme_tags(sub_asset_class)) or None,
        }
    return values


def _field_value(product, field: str):
    from services.portfolio_engine_payload import parse_theme_tags

    raw = getattr(product, field, None)
    if field == "theme_tags":
        return parse_theme_tags(raw) or None
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    return raw.strip().upper() if field == "esg_rating" and isinstance(raw, str) else raw


def seed_unverified_esg_fields(product) -> tuple[str, ...]:
    """ESG-Felder des Produkts, die noch den unbelegten Seed-Wert tragen."""
    if str(getattr(product, "tenant_id", None) or "").strip():
        return ()
    seed = _seed_esg_values().get(str(getattr(product, "product_name", None) or ""))
    if not seed:
        return ()
    return tuple(
        field for field in ESG_DATA_FIELDS
        if seed[field] is not None and _field_value(product, field) == seed[field]
    )


def product_esg_data_status(product) -> str:
    if seed_unverified_esg_fields(product):
        return ESG_DATA_STATUS_SEED_UNVERIFIED
    if any(_field_value(product, field) is not None for field in ESG_DATA_FIELDS):
        return ESG_DATA_STATUS_MAINTAINED_NO_SOURCE
    return ESG_DATA_STATUS_NOT_MAINTAINED


def _active_esg_criterion(prefs) -> str | None:
    from services.portfolio_engine_payload import ESG_POLICY_CRITERIA

    policy = ((prefs or {}).get("policy") or {}).get("esg") if isinstance(prefs, dict) else None
    return policy if policy in ESG_POLICY_CRITERIA else None


def seed_unverified_run_warning(prefs, products) -> str | None:
    """Berater-Warnung: das ESG-Kriterium des Runs stuetzt sich auf
    unbelegte Seed-Werte (ausgenommene Liquiditaet zaehlt nicht)."""
    from services.portfolio_engine import _norm_text
    from services.portfolio_engine_payload import ESG_POLICY_EXEMPT_ASSET_CLASS

    if not _active_esg_criterion(prefs):
        return None
    names = sorted({
        str(product.product_name) for product in products
        if _norm_text(getattr(product, "asset_class", None)) != ESG_POLICY_EXEMPT_ASSET_CLASS
        and product_esg_data_status(product) == ESG_DATA_STATUS_SEED_UNVERIFIED
    })
    if not names:
        return None
    return (
        f"{ESG_DATA_SEED_UNVERIFIED}: Die ESG-Angaben folgender Produkte sind "
        "unbelegte Ausgangswerte des Standardkatalogs (keine Quelle, kein "
        f"Stichtag): {', '.join(names)}. Die Erfuellung des ESG-Kriteriums ist "
        "fuer diese Produkte nicht belegt; das Kundendokument weist dies aus. "
        "Bitte die Angaben mit Quelle im Produktkatalog pflegen."
    )


# Kunden-Asset-Klassen-Keys (routers/pdf_reports._bucket_key) der Ausnahme.
_EXEMPT_BUCKET_KEYS = frozenset({"liquidity"})


def customer_esg_data_caveat(prefs, products) -> str | None:
    """Kundentext (ohne Claim-Begriffe): bei aktivem ESG-Kriterium und
    Produkten mit unbelegten Seed-Werten wird die Erfuellung ausdruecklich
    NICHT bestaetigt. ``products`` = PDF-Produkt-Dicts (name, asset_class,
    esg_data_status)."""
    if not _active_esg_criterion(prefs):
        return None
    names = sorted({
        str(item.get("name") or "")
        for item in (products or [])
        if isinstance(item, dict)
        and item.get("esg_data_status") == ESG_DATA_STATUS_SEED_UNVERIFIED
        and str(item.get("asset_class") or "").strip().lower() not in _EXEMPT_BUCKET_KEYS
    } - {""})
    if not names:
        return None
    return (
        "Die ESG-Angaben (SFDR-Klassifikation bzw. ESG-Rating) der Produkte "
        f"{', '.join(names)} sind nicht durch eine Quelle belegt "
        "(Ausgangswerte des Standardkatalogs). Ob diese Produkte das genannte "
        "Kriterium erfuellen, ist daher nicht bestaetigt."
    )
