"""Sprint U-P10 (2026-05-20): Diversifikations-Tiefe pro Produkt.

Wenn ein Produkt keine eigenen country_exposure_json/sector_exposure_json/
currency_exposure_json-Werte hat, liefert dieses Modul Default-Proxys
abgeleitet aus der `sub_asset_class`-Bezeichnung. Damit ist der Depot-Check
sofort sinnvoll auswertbar, ohne dass der Berater jede einzelne Position
manuell taggen muss.

Werte basieren auf:
- MSCI ACWI Country-Gewichtung (Stand 2025)
- GICS-Sektoren-Gewichtung in den grossen ETF-Universen
- SARON/Euribor/Treasury-Currency-Splits

Berater kann Defaults via PUT /admin/products/{id} ueberschreiben — dann
greifen die explizit gepflegten JSON-Strings statt der Proxys.
"""
from __future__ import annotations

import json
import logging
from typing import Mapping

logger = logging.getLogger(__name__)

# ===== COUNTRY EXPOSURE (bps, sum = 10000) =====

_COUNTRY_PROXIES_BY_SUB_CLASS: dict[str, dict[str, int]] = {
    # Aktien
    "Aktien Schweiz": {"CH": 10000},
    "Aktien Schweiz Small/Mid": {"CH": 10000},
    "Aktien Global": {
        "US": 6500, "CH": 300, "GB": 400, "JP": 600,
        "DE": 250, "FR": 350, "NL": 150, "RoW": 1450,
    },
    "Aktien Europa": {
        "GB": 1800, "FR": 1700, "DE": 1500, "CH": 1300,
        "NL": 800, "SE": 500, "ES": 400, "IT": 400, "RoW": 1600,
    },
    "Aktien Schwellenlaender": {
        "CN": 2800, "IN": 1900, "TW": 1700, "KR": 1200,
        "BR": 500, "ZA": 300, "MX": 300, "RoW": 1300,
    },
    # Themes (alle approx global Mix)
    "Thema Verteidigung": {"US": 6000, "EU": 2500, "RoW": 1500},
    "Thema Fossile Energie": {"US": 4000, "EU": 1500, "MidEast": 2000, "RoW": 2500},
    "Thema Tabak": {"US": 5000, "GB": 2500, "RoW": 2500},
    "Thema Alkohol": {"FR": 2500, "US": 3000, "GB": 1500, "RoW": 3000},
    "Thema Gluecksspiel": {"US": 5000, "AU": 1500, "RoW": 3500},
    "Thema Kernenergie": {"US": 3500, "FR": 1500, "JP": 1000, "RoW": 4000},
    # Bonds
    "Obligationen CHF IG": {"CH": 10000},
    "Obligationen Global Hedged": {
        "US": 4500, "EU": 2500, "JP": 1500, "GB": 800, "RoW": 700,
    },
    "Obligationen High Yield": {
        "US": 7000, "EU": 1800, "GB": 600, "RoW": 600,
    },
    "Obligationen Emerging": {
        "CN": 2000, "BR": 1500, "MX": 1300, "ID": 800,
        "TR": 700, "ZA": 600, "RoW": 3100,
    },
    # Real Estate
    "Immobilien Schweiz": {"CH": 10000},
    "Immobilien Global": {
        "US": 6000, "JP": 1200, "GB": 700, "AU": 600,
        "DE": 400, "RoW": 1100,
    },
    # Alternatives
    "Gold / Rohstoffe": {"Global": 10000},  # ungeografisch
    "Liquid Alternatives": {"US": 7000, "EU": 2000, "RoW": 1000},
    "Hedge Funds": {"US": 6500, "EU": 2000, "RoW": 1500},
    "Private Equity": {"US": 6500, "EU": 2500, "RoW": 1000},
    "Krypto": {"Global": 10000},
    # Liquidity
    "Geldmarktfonds": {"CH": 10000},
    "Festgeld": {"CH": 10000},
    "Cash CHF": {"CH": 10000},
    "Kontoguthaben": {"CH": 10000},
}


# ===== SECTOR EXPOSURE (GICS, bps) =====
# Quelle: MSCI ACWI / MSCI World Sektor-Gewichtungen 2025
_SECTOR_PROXIES_BY_SUB_CLASS: dict[str, dict[str, int]] = {
    # Aktien Global / Diversifiziert (MSCI ACWI nahe Verteilung)
    "Aktien Global": {
        "Information Technology": 2400, "Financials": 1600, "Health Care": 1100,
        "Consumer Discretionary": 1100, "Industrials": 1000, "Communication Services": 800,
        "Consumer Staples": 600, "Energy": 450, "Materials": 400,
        "Utilities": 300, "Real Estate": 240,
    },
    "Aktien Schweiz": {
        # SPI ~ 30% Healthcare, 25% Cons.Staples (Nestle), 18% Financials
        "Health Care": 3000, "Consumer Staples": 2500, "Financials": 1800,
        "Industrials": 800, "Materials": 600, "Information Technology": 400,
        "Real Estate": 300, "Consumer Discretionary": 300, "Communication Services": 200,
        "Energy": 50, "Utilities": 50,
    },
    "Aktien Europa": {
        "Financials": 1800, "Industrials": 1500, "Health Care": 1400,
        "Consumer Staples": 1100, "Consumer Discretionary": 900,
        "Materials": 800, "Information Technology": 700, "Energy": 600,
        "Communication Services": 500, "Utilities": 400, "Real Estate": 300,
    },
    "Aktien Schwellenlaender": {
        "Information Technology": 2300, "Financials": 2000, "Consumer Discretionary": 1400,
        "Communication Services": 900, "Industrials": 700, "Materials": 700,
        "Energy": 600, "Health Care": 400, "Consumer Staples": 400,
        "Utilities": 300, "Real Estate": 300,
    },
    # Themes — Single-Sektor-Konzentration
    "Thema Verteidigung": {"Industrials": 9500, "Information Technology": 500},
    "Thema Fossile Energie": {"Energy": 10000},
    "Thema Tabak": {"Consumer Staples": 10000},
    "Thema Alkohol": {"Consumer Staples": 10000},
    "Thema Gluecksspiel": {"Consumer Discretionary": 10000},
    "Thema Kernenergie": {"Utilities": 5000, "Energy": 3000, "Industrials": 2000},
    # Bonds (kein GICS-Sektor — wir markieren als "Bonds")
    "Obligationen CHF IG": {"Bonds Govt+Corp IG": 10000},
    "Obligationen Global Hedged": {"Bonds Govt+Corp IG": 10000},
    "Obligationen High Yield": {"Bonds High Yield": 10000},
    "Obligationen Emerging": {"Bonds Emerging Markets": 10000},
    # RE/Alts
    "Immobilien Schweiz": {"Real Estate": 10000},
    "Immobilien Global": {"Real Estate": 10000},
    "Gold / Rohstoffe": {"Commodities": 10000},
    "Liquid Alternatives": {"Alternatives": 10000},
    "Hedge Funds": {"Alternatives": 10000},
    "Private Equity": {"Private Equity": 10000},
    "Krypto": {"Digital Assets": 10000},
    "Geldmarktfonds": {"Cash & Equivalents": 10000},
    "Festgeld": {"Cash & Equivalents": 10000},
}


# ===== CURRENCY EXPOSURE (bps) =====
# Tatsaechliche Waehrungs-Exposure (NACH Hedging fuer "Hedged"-Produkte).
_CURRENCY_PROXIES_BY_SUB_CLASS: dict[str, dict[str, int]] = {
    "Aktien Schweiz": {"CHF": 10000},
    "Aktien Schweiz Small/Mid": {"CHF": 10000},
    "Aktien Global": {
        "USD": 6500, "EUR": 1300, "JPY": 600, "GBP": 400, "CHF": 300, "RoW": 900,
    },
    "Aktien Europa": {"EUR": 5500, "GBP": 1800, "CHF": 1300, "SEK": 400, "RoW": 1000},
    "Aktien Schwellenlaender": {
        "USD": 3500, "CNY": 1800, "INR": 1200, "TWD": 800, "KRW": 700, "RoW": 2000,
    },
    "Thema Verteidigung": {"USD": 6500, "EUR": 2000, "RoW": 1500},
    "Thema Fossile Energie": {"USD": 5500, "EUR": 1500, "RoW": 3000},
    "Thema Tabak": {"USD": 6500, "GBP": 2500, "RoW": 1000},
    "Thema Alkohol": {"EUR": 3500, "USD": 3000, "GBP": 1500, "RoW": 2000},
    "Thema Gluecksspiel": {"USD": 6500, "AUD": 1500, "RoW": 2000},
    "Thema Kernenergie": {"USD": 4500, "EUR": 2500, "JPY": 1000, "RoW": 2000},
    "Obligationen CHF IG": {"CHF": 10000},
    "Obligationen Global Hedged": {"CHF": 10000},  # hedged → CHF
    "Obligationen High Yield": {"USD": 7500, "EUR": 2000, "RoW": 500},
    "Obligationen Emerging": {"USD": 5500, "Local FX EM": 4500},
    "Immobilien Schweiz": {"CHF": 10000},
    "Immobilien Global": {"USD": 6000, "JPY": 1200, "EUR": 800, "GBP": 700, "RoW": 1300},
    "Gold / Rohstoffe": {"USD": 10000},
    "Liquid Alternatives": {"USD": 7000, "EUR": 2000, "RoW": 1000},
    "Hedge Funds": {"USD": 7000, "EUR": 2000, "RoW": 1000},
    "Private Equity": {"USD": 7000, "EUR": 2500, "RoW": 500},
    "Krypto": {"USD": 10000},
    "Geldmarktfonds": {"CHF": 10000},
    "Festgeld": {"CHF": 10000},
    "Cash CHF": {"CHF": 10000},
    "Kontoguthaben": {"CHF": 10000},
}


def _parse_or_proxy(
    raw_json: str | None,
    proxy_map: dict[str, dict[str, int]],
    sub_asset_class: str | None,
) -> dict[str, int]:
    """Wenn raw_json gesetzt + parsable: nutze diesen Wert. Sonst Proxy aus
    sub_asset_class. Fallback: leerer Dict.

    2026-09-05 (Codex-Audit PROD-DOMAIN-001): schemas/review.py::ProductCreate/
    ProductUpdate validieren jetzt am API-Rand, sodass NEUE Daten nie mehr
    kaputtes/unparsebares JSON in die DB schreiben koennen. Diese Funktion
    liest aber weiterhin JEDEN bestehenden Product-Datensatz -- inkl. evtl.
    schon vor dem Fix gespeicherter, kaputter Legacy-Werte -- und darf dafuer
    nicht crashen. Frueher wurde ein explizit gesetzter, aber kaputter Wert
    (raw_json truthy, aber nicht parsebares JSON / kein dict) STILLSCHWEIGEND
    wie "gar nicht gepflegt" behandelt und lautlos durch den Proxy ersetzt --
    nicht von einem echten "Feld ist leer" zu unterscheiden. Jetzt wird dieser
    Fall laut geloggt (er bedeutet: es gibt echte, aber verunreinigte Daten,
    die ein Admin bereinigen sollte), auch wenn der Proxy-Fallback aus
    Konsumenten-Sicht weiterhin greift, um Depot-Check/Kostenausweis nicht
    crashen zu lassen."""
    if raw_json:
        try:
            parsed = json.loads(raw_json)
            if not isinstance(parsed, dict):
                raise ValueError(f"erwartetes JSON-Objekt, erhalten {type(parsed).__name__}")
            return {str(k): int(v) for k, v in parsed.items() if v is not None}
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            # Explizit gesetzt, aber kaputt/falsch geformt -- KEIN "nicht
            # angegeben". Laut flaggen statt lautlos wie leer zu behandeln,
            # bevor auf den Proxy zurueckgefallen wird.
            logger.warning(
                "product_exposures: gespeichertes Exposure-JSON ist explizit "
                "gesetzt, aber ungueltig (%s) -- falle auf Proxy fuer "
                "sub_asset_class=%r zurueck. Legacy-Daten bereinigen.",
                exc, sub_asset_class,
            )
    if not sub_asset_class:
        return {}
    return dict(proxy_map.get(str(sub_asset_class), {}))


def country_exposure_for_product(
    country_exposure_json: str | None,
    sub_asset_class: str | None,
) -> dict[str, int]:
    """Returns {country_iso: bps} mit Σ ≈ 10000. Wenn weder explizit gepflegt
    noch Sub-Class-Proxy bekannt: leerer Dict (Depot-Check zeigt 'unbekannt')."""
    return _parse_or_proxy(country_exposure_json, _COUNTRY_PROXIES_BY_SUB_CLASS, sub_asset_class)


def sector_exposure_for_product(
    sector_exposure_json: str | None,
    sub_asset_class: str | None,
) -> dict[str, int]:
    """Returns {gics_sector: bps} mit Σ ≈ 10000."""
    return _parse_or_proxy(sector_exposure_json, _SECTOR_PROXIES_BY_SUB_CLASS, sub_asset_class)


def currency_exposure_for_product(
    currency_exposure_json: str | None,
    sub_asset_class: str | None,
    fallback_currency: str | None = None,
) -> dict[str, int]:
    """Returns {currency_iso: bps} mit Σ ≈ 10000. Fallback: 100% in
    fallback_currency (= product.currency) wenn weder explizit noch Sub-Class-
    Proxy verfügbar."""
    result = _parse_or_proxy(currency_exposure_json, _CURRENCY_PROXIES_BY_SUB_CLASS, sub_asset_class)
    if not result and fallback_currency:
        result = {str(fallback_currency).upper(): 10000}
    return result


def aggregate_exposures(
    position_weights_bps: Mapping[str, int],
    exposure_per_position: Mapping[str, dict[str, int]],
) -> dict[str, int]:
    """Aggregiert Position-Level-Exposures auf Portfolio-Level.

    position_weights_bps: {position_id: target_weight_bps}, Σ ≈ 10000
    exposure_per_position: {position_id: {country/sector/currency: sub_bps}}

    Returns: {country/sector/currency: portfolio_bps} (Σ ≈ 10000)
    """
    total_weight = sum(max(0, int(w or 0)) for w in position_weights_bps.values())
    if total_weight <= 0:
        return {}
    aggregated: dict[str, float] = {}
    for pos_id, weight in position_weights_bps.items():
        w = max(0, int(weight or 0))
        if w <= 0:
            continue
        exp = exposure_per_position.get(pos_id) or {}
        exp_total = sum(max(0, int(v or 0)) for v in exp.values())
        if exp_total <= 0:
            continue
        for key, sub_bps in exp.items():
            contribution = (w / total_weight) * (int(sub_bps or 0) / exp_total)
            aggregated[key] = aggregated.get(key, 0.0) + contribution
    # Skaliere auf 10000 bps
    sum_agg = sum(aggregated.values())
    if sum_agg <= 0:
        return {}
    return {k: int(round(v / sum_agg * 10000)) for k, v in aggregated.items()}


def herfindahl_hirschman_index(weights_bps: Mapping[str, int]) -> int:
    """HHI-Konzentrationsindex in bps. 10000 = perfekt konzentriert (1 Position),
    < 1500 = wenig konzentriert (US-Antitrust-Grenze).

    Standardformel: HHI = Σ (w_i in %)^2  → 0..10000.
    Bei bps-Input: konvertiert intern.
    """
    total = sum(max(0, int(w or 0)) for w in weights_bps.values())
    if total <= 0:
        return 0
    hhi = 0.0
    for w in weights_bps.values():
        share_pct = max(0, int(w or 0)) / total * 100.0
        hhi += share_pct * share_pct
    return int(round(hhi))
