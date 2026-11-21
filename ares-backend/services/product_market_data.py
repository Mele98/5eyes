from __future__ import annotations

import hashlib

from typing import Any


US_EXCHANGE_CODES = {
    "US", "NYSE", "NASDAQ", "NYSEARCA", "ARCA", "AMEX", "BATS", "IEX", "OTC",
}

EXCHANGE_CODE_ALIASES = {
    "XSWX": "SW",
    "SWX": "SW",
    "SIX": "SW",
    "XVTX": "VX",
    "TSX": "TO",
    "XTSX": "V",
    "LON": "L",
    "XLON": "L",
    "XETRA": "DE",
    "XFRA": "F",
    "XPAR": "PA",
    "EPA": "PA",
    "XAMS": "AS",
    "XBRU": "BR",
    "XMAD": "MC",
    "XMIL": "MI",
    "XHEL": "HE",
    "XSTO": "ST",
    "XOSL": "OL",
    "XCSE": "CO",
    "XDUB": "IR",
    "XWBO": "VI",
    "XHKG": "HK",
    "XTKS": "T",
    "XASX": "AX",
    "XNZE": "NZ",
}

YFINANCE_SUFFIX_BY_EXCHANGE = {
    "SW": "SW",
    "VX": "SW",
    "TO": "TO",
    "V": "V",
    "L": "L",
    "DE": "DE",
    "F": "F",
    "PA": "PA",
    "AS": "AS",
    "BR": "BR",
    "MC": "MC",
    "MI": "MI",
    "HE": "HE",
    "ST": "ST",
    "OL": "OL",
    "CO": "CO",
    "IR": "IR",
    "VI": "VI",
    "HK": "HK",
    "T": "T",
    "AX": "AX",
    "NZ": "NZ",
}

STOOQ_SUFFIX_BY_EXCHANGE = {
    "SW": "sw",
    "VX": "sw",
    "TO": "to",
    "V": "v",
    "L": "uk",
    "DE": "de",
    "F": "de",
    "PA": "fr",
    "AS": "nl",
    "BR": "be",
    "MC": "es",
    "MI": "it",
    "HE": "fi",
    "ST": "se",
    "OL": "no",
    "CO": "dk",
    "IR": "ie",
    "VI": "at",
    "HK": "hk",
    "T": "jp",
    "AX": "au",
    "NZ": "nz",
}

TWELVEDATA_EXCHANGE_NAME_BY_CODE = {
    "SW": "SIX",
    "VX": "SIX",
    "TO": "TSX",
    "V": "TSXV",
    "L": "LSE",
    "DE": "XETRA",
    "F": "FRA",
    "PA": "EPA",
    "AS": "EAM",
    "BR": "BRU",
    "MC": "BME",
    "MI": "MIL",
    "HE": "HEL",
    "ST": "STO",
    "OL": "OSE",
    "CO": "CPH",
    "IR": "ISE",
    "VI": "VIE",
    "HK": "HKEX",
    "T": "TYO",
    "AX": "ASX",
    "NZ": "NZE",
}


DEFAULT_PRODUCT_MARKET_CATALOG: dict[str, dict[str, Any]] = {
    "Musterprodukt Aktien Schweiz": {
        "lookup_mode": "proxy",
        "lookup_symbol": "EWL",
        "pricing_note": "Musterprodukt ohne belegte Stammdaten: Preis nur ueber ein Stellvertreter-Symbol.",
    },
    "Musterprodukt Aktien Schweiz Small/Mid": {
        "lookup_mode": "proxy",
        "lookup_symbol": "IJR",
        "pricing_note": "Musterprodukt ohne belegte Stammdaten: Preis nur ueber ein Stellvertreter-Symbol.",
    },
    "Musterprodukt Aktien Global": {
        "lookup_mode": "proxy",
        "lookup_symbol": "URTH",
        "pricing_note": "Musterprodukt ohne belegte Stammdaten: Preis nur ueber ein Stellvertreter-Symbol.",
    },
    "Musterprodukt Aktien Europa": {
        "lookup_mode": "proxy",
        "lookup_symbol": "VGK",
        "pricing_note": "Musterprodukt ohne belegte Stammdaten: Preis nur ueber ein Stellvertreter-Symbol.",
    },
    "Musterprodukt Aktien Schwellenlaender": {
        "lookup_mode": "proxy",
        "lookup_symbol": "IEMG",
        "pricing_note": "Musterprodukt ohne belegte Stammdaten: Preis nur ueber ein Stellvertreter-Symbol.",
    },
    "Musterprodukt Thema Verteidigung": {
        "lookup_mode": "proxy",
        "lookup_symbol": "ITA",
        "pricing_note": "Musterprodukt ohne belegte Stammdaten: Preis nur ueber ein Stellvertreter-Symbol.",
    },
    "Musterprodukt Thema Fossile Energie": {
        "lookup_mode": "direct",
        "lookup_symbol": "XLE",
        "pricing_note": "Musterprodukt ohne belegte Stammdaten: Preis ueber das hinterlegte Symbol.",
    },
    "Musterprodukt Thema Tabak": {
        "lookup_mode": "proxy",
        "lookup_symbol": "PM",
        "pricing_note": "Musterprodukt ohne belegte Stammdaten: Preis nur ueber ein Stellvertreter-Symbol.",
    },
    "Musterprodukt Thema Alkohol": {
        "lookup_mode": "proxy",
        "lookup_symbol": "STZ",
        "pricing_note": "Musterprodukt ohne belegte Stammdaten: Preis nur ueber ein Stellvertreter-Symbol.",
    },
    "Musterprodukt Thema Gluecksspiel": {
        "lookup_mode": "direct",
        "lookup_symbol": "BETZ",
        "pricing_note": "Musterprodukt ohne belegte Stammdaten: Preis ueber das hinterlegte Symbol.",
    },
    "Musterprodukt Thema Kernenergie": {
        "lookup_mode": "proxy",
        "lookup_symbol": "NLR",
        "pricing_note": "Musterprodukt ohne belegte Stammdaten: Preis nur ueber ein Stellvertreter-Symbol.",
    },
    "Musterprodukt Obligationen CHF IG": {
        "lookup_mode": "proxy",
        "lookup_symbol": "BND",
        "pricing_note": "Musterprodukt ohne belegte Stammdaten: Preis nur ueber ein Stellvertreter-Symbol.",
    },
    "Musterprodukt Obligationen Global CHF-abgesichert": {
        "lookup_mode": "proxy",
        "lookup_symbol": "IAGG",
        "pricing_note": "Musterprodukt ohne belegte Stammdaten: Preis nur ueber ein Stellvertreter-Symbol.",
    },
    "Musterprodukt Obligationen High Yield": {
        "lookup_mode": "proxy",
        "lookup_symbol": "HYG",
        "pricing_note": "Musterprodukt ohne belegte Stammdaten: Preis nur ueber ein Stellvertreter-Symbol.",
    },
    "Musterprodukt Obligationen Emerging": {
        "lookup_mode": "proxy",
        "lookup_symbol": "EMLC",
        "pricing_note": "Musterprodukt ohne belegte Stammdaten: Preis nur ueber ein Stellvertreter-Symbol.",
    },
    "Musterprodukt Immobilien Schweiz": {
        "lookup_mode": "proxy",
        "lookup_symbol": "RWO",
        "pricing_note": "Musterprodukt ohne belegte Stammdaten: Preis nur ueber ein Stellvertreter-Symbol.",
    },
    "Musterprodukt Immobilien Global": {
        "lookup_mode": "proxy",
        "lookup_symbol": "REET",
        "pricing_note": "Musterprodukt ohne belegte Stammdaten: Preis nur ueber ein Stellvertreter-Symbol.",
    },
    "Musterprodukt Gold / Rohstoffe": {
        "lookup_mode": "proxy",
        "lookup_symbol": "GLD",
        "pricing_note": "Musterprodukt ohne belegte Stammdaten: Preis nur ueber ein Stellvertreter-Symbol.",
    },
    "Musterprodukt Liquid Alternatives": {
        "lookup_mode": "proxy",
        "lookup_symbol": "QAI",
        "pricing_note": "Musterprodukt ohne belegte Stammdaten: Preis nur ueber ein Stellvertreter-Symbol.",
    },
    "Musterprodukt Hedge Funds": {
        "lookup_mode": "proxy",
        "lookup_symbol": "KMLM",
        "pricing_note": "Musterprodukt ohne belegte Stammdaten: Preis nur ueber ein Stellvertreter-Symbol.",
    },
    "Musterprodukt Private Equity": {
        "lookup_mode": "proxy",
        "lookup_symbol": "PSP",
        "pricing_note": "Musterprodukt ohne belegte Stammdaten: Preis nur ueber ein Stellvertreter-Symbol.",
    },
    "Musterprodukt Krypto": {
        "lookup_mode": "proxy",
        "lookup_symbol": "IBIT",
        "pricing_note": "Musterprodukt ohne belegte Stammdaten: Preis nur ueber ein Stellvertreter-Symbol.",
    },
    # 2026-08-22 (hedgingRequired-Katalogluecke, siehe portfolio_engine.py::
    # ensure_default_products): CHF-gehedgte Pendants teilen sich denselben
    # Basiswert/Index wie ihr unhedged Original -- reiner Waehrungs-Hedge,
    # daher gleicher Proxy-Lookup wie das Original (die Kursverlaufsform ist
    # praktisch identisch, nur die Basiswaehrung unterscheidet sich).
    "Musterprodukt Aktien Global CHF-abgesichert": {
        "lookup_mode": "proxy",
        "lookup_symbol": "URTH",
        "pricing_note": "Musterprodukt ohne belegte Stammdaten: Preis nur ueber ein Stellvertreter-Symbol.",
    },
    "Musterprodukt Aktien Europa CHF-abgesichert": {
        "lookup_mode": "proxy",
        "lookup_symbol": "VGK",
        "pricing_note": "Musterprodukt ohne belegte Stammdaten: Preis nur ueber ein Stellvertreter-Symbol.",
    },
    "Musterprodukt Aktien Schwellenlaender CHF-abgesichert": {
        "lookup_mode": "proxy",
        "lookup_symbol": "IEMG",
        "pricing_note": "Musterprodukt ohne belegte Stammdaten: Preis nur ueber ein Stellvertreter-Symbol.",
    },
    "Musterprodukt Thema Verteidigung CHF-abgesichert": {
        "lookup_mode": "proxy",
        "lookup_symbol": "ITA",
        "pricing_note": "Musterprodukt ohne belegte Stammdaten: Preis nur ueber ein Stellvertreter-Symbol.",
    },
    "Musterprodukt Thema Fossile Energie CHF-abgesichert": {
        "lookup_mode": "direct",
        "lookup_symbol": "XLE",
        "pricing_note": "Musterprodukt ohne belegte Stammdaten: Preis ueber das hinterlegte Symbol.",
    },
    "Musterprodukt Thema Tabak CHF-abgesichert": {
        "lookup_mode": "proxy",
        "lookup_symbol": "PM",
        "pricing_note": "Musterprodukt ohne belegte Stammdaten: Preis nur ueber ein Stellvertreter-Symbol.",
    },
    "Musterprodukt Thema Gluecksspiel CHF-abgesichert": {
        "lookup_mode": "direct",
        "lookup_symbol": "BETZ",
        "pricing_note": "Musterprodukt ohne belegte Stammdaten: Preis ueber das hinterlegte Symbol.",
    },
    "Musterprodukt Thema Kernenergie CHF-abgesichert": {
        "lookup_mode": "proxy",
        "lookup_symbol": "NLR",
        "pricing_note": "Musterprodukt ohne belegte Stammdaten: Preis nur ueber ein Stellvertreter-Symbol.",
    },
    "Musterprodukt Obligationen Emerging CHF-abgesichert": {
        "lookup_mode": "proxy",
        "lookup_symbol": "EMLC",
        "pricing_note": "Musterprodukt ohne belegte Stammdaten: Preis nur ueber ein Stellvertreter-Symbol.",
    },
    "Musterprodukt Immobilien Global CHF-abgesichert": {
        "lookup_mode": "proxy",
        "lookup_symbol": "REET",
        "pricing_note": "Musterprodukt ohne belegte Stammdaten: Preis nur ueber ein Stellvertreter-Symbol.",
    },
    "Musterprodukt Geldmarktfonds": {
        "lookup_mode": "synthetic_par",
        "synthetic_price_rappen": 100,
        "pricing_note": "Musterprodukt ohne belegte Stammdaten: synthetischer Nennwert.",
    },
    "Kontoguthaben CHF": {
        "lookup_mode": "synthetic_par",
        "synthetic_price_rappen": 100,
        "pricing_note": "Synthetischer Par-Wert fuer Cash-Bestaende.",
    },
    "Festgeld CHF 12M": {
        "lookup_mode": "synthetic_par",
        "synthetic_price_rappen": 100,
        "pricing_note": "Synthetischer Par-Wert bis Festgeld-Konditionsfeeds integriert sind.",
    },
}


def normalize_exchange_code(value: Any) -> str | None:
    raw = str(value or "").strip().upper()
    if not raw:
        return None
    return EXCHANGE_CODE_ALIASES.get(raw, raw)


def _has_explicit_market_suffix(symbol: str | None) -> bool:
    raw = str(symbol or "").strip()
    return any(token in raw for token in (".", ":", "/", "="))


def provider_lookup_symbol(raw_symbol: str | None, exchange_code: Any, provider_name: str) -> str | None:
    symbol = str(raw_symbol or "").strip()
    if not symbol:
        return None
    provider = str(provider_name or "").strip().lower()
    normalized_exchange = normalize_exchange_code(exchange_code)
    if _has_explicit_market_suffix(symbol):
        return symbol

    if provider == "yfinance":
        if not normalized_exchange or normalized_exchange in US_EXCHANGE_CODES:
            return symbol
        suffix = YFINANCE_SUFFIX_BY_EXCHANGE.get(normalized_exchange)
        return f"{symbol}.{suffix}" if suffix else symbol

    if provider == "stooq":
        if not normalized_exchange or normalized_exchange in US_EXCHANGE_CODES:
            return symbol
        suffix = STOOQ_SUFFIX_BY_EXCHANGE.get(normalized_exchange)
        return f"{symbol.lower()}.{suffix}" if suffix else symbol

    if provider == "twelvedata":
        if not normalized_exchange or normalized_exchange in US_EXCHANGE_CODES:
            return symbol
        exchange_name = TWELVEDATA_EXCHANGE_NAME_BY_CODE.get(normalized_exchange)
        return f"{symbol}:{exchange_name}" if exchange_name else symbol

    return symbol


def lookup_symbol_for_provider(profile: dict[str, Any] | None, provider_name: str) -> str | None:
    payload = profile or {}
    mode = str(payload.get("lookup_mode") or "").strip()
    lookup_symbols = payload.get("lookup_symbols")
    if isinstance(lookup_symbols, dict):
        candidate = str(lookup_symbols.get(str(provider_name or "").strip().lower()) or "").strip()
        if candidate:
            return candidate
    raw_lookup = str(payload.get("lookup_symbol") or "").strip() or None
    if mode != "direct":
        return raw_lookup
    raw_symbol = str(payload.get("symbol") or "").strip() or None
    exchange_code = payload.get("exchange_code")
    return provider_lookup_symbol(raw_symbol or raw_lookup, exchange_code, provider_name) or raw_lookup


# Bugfix 2026-08-07 (CEO/CFO/CIO-Audit, MD-01): price_updater.py uebernahm den
# vom Provider tatsaechlich gemeldeten Kurs immer unter product.currency
# (Stammdaten), OHNE jemals gegen die Boerse zu pruefen, an der das Produkt
# laut exchange_code notiert ist -- bei einem Stammdaten-Tippfehler (z.B.
# "CHF" fuer einen an der XETRA (DE) notierten Titel) waere der Kurs silent
# falsch bewertet/etikettiert. Sicherer Fix OHNE zusaetzlichen Netzwerk-Call
# (kein Rate-Limit-Risiko fuer den Batch-Refresh-Job): rein lokaler Abgleich
# exchange_code -> erwartete Waehrung, als Datenqualitaets-Warnung im
# read-only Admin-Status-Endpoint (_collect_product_market_data_status) --
# NICHT in der Live-Preis-Pipeline selbst, um deren Verhalten unveraendert
# zu lassen. Nur fuer lookup_mode="direct" mit aufgeloestem exchange_code
# sinnvoll -- bei "proxy"-Lookups (siehe DEFAULT_PRODUCT_MARKET_CATALOG) ist
# der Kurs bewusst von einem andersartigen Stellvertreter-Wertpapier, ein
# Waehrungs-Abgleich dort waere irrefuehrend.
EXCHANGE_CURRENCY_BY_CODE: dict[str, str] = {
    "SW": "CHF", "VX": "CHF",
    "TO": "CAD", "V": "CAD",
    "L": "GBP",
    "DE": "EUR", "F": "EUR", "PA": "EUR", "AS": "EUR", "BR": "EUR",
    "MC": "EUR", "MI": "EUR", "IR": "EUR", "VI": "EUR", "HE": "EUR",
    "ST": "SEK",
    "OL": "NOK",
    "CO": "DKK",
    "HK": "HKD",
    "T": "JPY",
    "AX": "AUD",
    "NZ": "NZD",
}


def expected_currency_for_exchange(exchange_code: Any) -> str | None:
    normalized = normalize_exchange_code(exchange_code)
    if not normalized:
        return None
    if normalized in US_EXCHANGE_CODES:
        return "USD"
    return EXCHANGE_CURRENCY_BY_CODE.get(normalized)


def currency_mismatch_warning(product: Any) -> str | None:
    """None wenn kein Mismatch (oder nicht pruefbar -- z.B. proxy/synthetic/
    kein exchange_code). Sonst eine Berater-lesbare Warnung."""
    profile = resolve_market_profile(product)
    if str(profile.get("lookup_mode") or "") != "direct":
        return None
    exchange_code = profile.get("exchange_code")
    expected = expected_currency_for_exchange(exchange_code)
    if not expected:
        return None
    actual = str(profile.get("currency") or "").strip().upper()
    if not actual or actual == expected:
        return None
    return (
        f"Stammdaten-Waehrung '{actual}' passt nicht zur Boerse "
        f"'{normalize_exchange_code(exchange_code)}' (dort ueblich: '{expected}'). "
        "Bitte Produkt-Stammdaten pruefen."
    )


def provider_market_warning(provider_name: str, exchange_code: Any) -> str | None:
    provider = str(provider_name or "").strip().lower()
    normalized_exchange = normalize_exchange_code(exchange_code)
    if provider == "stooq":
        if not normalized_exchange or normalized_exchange in US_EXCHANGE_CODES:
            return None
        if normalized_exchange in {"SW", "VX"}:
            return "Stooq fuer SIX/Schweiz ist nur Best-Effort und liefert haeufig keine belastbaren EOD-Daten."
        return f"Stooq fuer Boerse {normalized_exchange} ist nur Best-Effort und kann lueckenhafte EOD-Daten liefern."
    if provider == "yfinance" and normalized_exchange in {"SW", "VX"}:
        return "Yahoo Finance kann fuer SIX/Schweiz-Titel rate-limitiert oder unvollstaendig sein."
    return None


# K2 / N-915-03: Seed-Katalog mit neutralen Musterbezeichnungen.
#
# Der automatische CH-Katalog (services/portfolio_engine.py::DEFAULT_CATALOG_PRODUCTS)
# traegt keine Emittenten- oder Produktnamen mehr: TER und Ratings des Seeds sind
# nicht belegt, reale Namen waeren irrefuehrend. Echte Produkte kommen nur ueber den
# Product-Evidence-Pfad bzw. das Fonds-Universum.
#
# Bestehende Installationen behalten ihre frueher geseedeten Zeilen unveraendert (keine
# stille Datenmigration: Produktnamen gehen in versiegelte Empfehlungsstaende ein).
# Damit Marktprofil, ESG-Seed-Status und der Backfill der abgesicherten Varianten sie
# weiter erkennen, ordnet diese Tabelle den SHA-256 des frueheren Seed-Namens dem
# neuen Musternamen zu -- ohne die Altnamen im Klartext zu fuehren.
LEGACY_SEED_NAME_SHA256: dict[str, str] = {
    "28c190a5dfbf19dd88d8ec101288100506ca5f6a34160db5507c4d9006ce012b": "Musterprodukt Aktien Europa",
    "2428033322364eafd3da03db9d177715eb06d198e93865f282dd2b36aac00624": "Musterprodukt Aktien Europa CHF-abgesichert",
    "ca1350d9fb820af9229c1ecc4fa23dbbbe2e3e8613cb5e15da2e9d1d76f17d02": "Musterprodukt Aktien Global",
    "4eff628c3ab0e2fae7866418f3b83eed48988db6a6088c998f50561a02cd04ae": "Musterprodukt Aktien Global CHF-abgesichert",
    "9083e820d2d48e0d562c16fd6ff7d2aa10ccbe0278f49beac125d03f2ad2151f": "Musterprodukt Aktien Schweiz",
    "2b949cf28d7fb4f28078e0b349aa0f50fdb319e6188a2ee5d2298c526acb54cc": "Musterprodukt Aktien Schweiz Small/Mid",
    "592aa7d474b22c513a46073014abc6c2a94d5d9a0e761845a7b47b1254d200b6": "Musterprodukt Aktien Schwellenlaender",
    "d3a7dd826b60e7f328d1e934dc27aa17eb25f64db6f61a089ffbeeab71639c26": "Musterprodukt Aktien Schwellenlaender CHF-abgesichert",
    "2a49fcffecd90d798c74ce03e1da29dc3e693b27597e58ae44273463832e2b4e": "Musterprodukt Geldmarktfonds",
    "e4026fbff4081e1f7695e26f75136d146bf8c7fe348a5e29a924aba9d45aaab1": "Musterprodukt Gold / Rohstoffe",
    "61d8d02b4592a41e8fcae25515325babecfdca82484488d510181378196f2a65": "Musterprodukt Hedge Funds",
    "c5a75675860739208327f88b6ed2961b2e144dbc5fbf3d8f4acc46720ecf031e": "Musterprodukt Immobilien Global",
    "3c7463f63f7192d062075b9ad1ebeabe539d3cb7edba583d44250fec298dbcb0": "Musterprodukt Immobilien Global CHF-abgesichert",
    "b08ff1c460378330261c79a097dd2951794b58217daa455a754c0f34003bef44": "Musterprodukt Immobilien Schweiz",
    "844199e38d67860c53e42176da09211a408f42ca663f563d4b87e3b1f3d0441c": "Musterprodukt Krypto",
    "347e3ba47f84346e26dfdf74cc198e9c19e08716d37fe2469ae2affafaaba3ec": "Musterprodukt Liquid Alternatives",
    "73b8bdc8418a25bf482b426aebf6188df644ab816f1a58914261c8f0e12c767c": "Musterprodukt Obligationen CHF IG",
    "e1838174501a812fd7fc8db22d477dd2df52d9cd4db9f983bdc9c717e54b7bae": "Musterprodukt Obligationen Emerging",
    "365d63ec31ece07c78b24101e60a204877e45ccf47093b296bfce0629f330107": "Musterprodukt Obligationen Emerging CHF-abgesichert",
    "e6179a149822100a6473c9a952197413ba1a6bad499fb49832e87506b4631b97": "Musterprodukt Obligationen Global CHF-abgesichert",
    "ad700ff0be05ea47ec35d3e98cd5a20c88109aac68d870de535d5af5dc6b1fc2": "Musterprodukt Obligationen High Yield",
    "54ab75731953b0e0e6619a55e80a714b9100b79fe368f79719edde29b23cdd39": "Musterprodukt Private Equity",
    "65ea5074a703d4cf4ad88758e082f72d3ba877f743de56310a76aa3e4b792112": "Musterprodukt Thema Alkohol",
    "9cac90e64d061ac95abd615d6dfd6576fca024c32cc6a1f0620de4960de4acfd": "Musterprodukt Thema Fossile Energie",
    "b04a7b354b5923fdf9877dc807c6670fd6ed8dc4bfaf673b891f4e79a4e157ed": "Musterprodukt Thema Fossile Energie CHF-abgesichert",
    "6b10fbfe622d5b8ab44275b9609704db350b122cf3d9f2425aa5599fd02f2527": "Musterprodukt Thema Gluecksspiel",
    "5c7872cb538349fb596a419e6184114899cdbc8fd90100f0d20dc75548c71007": "Musterprodukt Thema Gluecksspiel CHF-abgesichert",
    "27e50be894174b8f5727045faa6a265de9273b7ddc07458dd61e5bbaa93e1e73": "Musterprodukt Thema Kernenergie",
    "04c9425f2774942730d198d610925062f4be86b11ac012496400482608b53a6a": "Musterprodukt Thema Kernenergie CHF-abgesichert",
    "ff605ee8ef29c9dfac6edab5de65701e264f86db674d8f85741c99280d6bbee1": "Musterprodukt Thema Tabak",
    "2ad138efc7fb402a6fe1e08fc03f638093195522e80bcf63897e17c9a4ec0e01": "Musterprodukt Thema Tabak CHF-abgesichert",
    "080a8ea3a4b7bf8b93b8236e9f2a92b48fc4d3378767c37ff08bbcb415f4b782": "Musterprodukt Thema Verteidigung",
    "490256717fd6e9407e8bb75acc8823194f8f1e4cc57ba33057b30b664abb7dff": "Musterprodukt Thema Verteidigung CHF-abgesichert",
}


def canonical_seed_name(name: object) -> str:
    """Musterbezeichnung eines (auch frueher geseedeten) Katalognamens; sonst unveraendert."""
    key = str(name or "").strip()
    return LEGACY_SEED_NAME_SHA256.get(hashlib.sha256(key.encode("utf-8")).hexdigest(), key)


def default_market_entry(product_name: str | None) -> dict[str, Any] | None:
    # K2/N-915-03: frueher geseedete Katalognamen (Bestandsinstallationen) -> Musterbezeichnung.
    key = canonical_seed_name(product_name)
    entry = DEFAULT_PRODUCT_MARKET_CATALOG.get(key)
    if not entry:
        return None
    return dict(entry)


def resolve_market_profile(product: Any) -> dict[str, Any]:
    product_name = str(getattr(product, "product_name", "") or "").strip()
    raw_symbol = str(getattr(product, "symbol", "") or "").strip() or None
    raw_isin = str(getattr(product, "isin", "") or "").strip() or None
    raw_currency = str(getattr(product, "currency", "") or "").strip() or None
    raw_exchange_code = normalize_exchange_code(getattr(product, "exchange_code", None))

    mode_override = str(getattr(product, "lookup_mode_override", "") or "").strip() or None
    symbol_override = str(getattr(product, "lookup_symbol_override", "") or "").strip() or None
    if mode_override or symbol_override:
        if mode_override == "synthetic_par":
            return {
                "product_name": product_name,
                "symbol": symbol_override or raw_symbol,
                "isin": raw_isin,
                "currency": raw_currency,
                "exchange_code": raw_exchange_code,
                "lookup_mode": "synthetic_par",
                "lookup_symbol": None,
                "lookup_symbols": {},
                "synthetic_price_rappen": 100,
                "identifier_basis": "override",
                "pricing_note": "Synthetischer Par-Wert (manueller Override).",
            }
        effective_symbol = symbol_override or raw_symbol
        effective_mode = mode_override or ("direct" if effective_symbol else "unmapped")
        lookup_symbols = {
            "yfinance": provider_lookup_symbol(effective_symbol, raw_exchange_code, "yfinance") if effective_symbol else None,
            "stooq": provider_lookup_symbol(effective_symbol, raw_exchange_code, "stooq") if effective_symbol else None,
            "twelvedata": provider_lookup_symbol(effective_symbol, raw_exchange_code, "twelvedata") if effective_symbol else None,
        }
        return {
            "product_name": product_name,
            "symbol": effective_symbol,
            "isin": raw_isin,
            "currency": raw_currency,
            "exchange_code": raw_exchange_code,
            "lookup_mode": effective_mode,
            "lookup_symbol": effective_symbol,
            "lookup_symbols": lookup_symbols,
            "synthetic_price_rappen": None,
            "identifier_basis": "override",
            "pricing_note": f"Manueller Override: Modus={effective_mode}, Symbol={effective_symbol or '-'}",
        }

    catalog = default_market_entry(product_name)

    if raw_symbol or raw_isin:
        identifier_basis = "symbol" if raw_symbol else "isin"
        lookup_symbols = {
            "yfinance": provider_lookup_symbol(raw_symbol, raw_exchange_code, "yfinance") if raw_symbol else None,
            "stooq": provider_lookup_symbol(raw_symbol, raw_exchange_code, "stooq") if raw_symbol else None,
            "twelvedata": provider_lookup_symbol(raw_symbol, raw_exchange_code, "twelvedata") if raw_symbol else None,
        }
        return {
            "product_name": product_name,
            "symbol": raw_symbol,
            "isin": raw_isin,
            "currency": raw_currency,
            "exchange_code": raw_exchange_code,
            "lookup_mode": "direct",
            "lookup_symbol": raw_symbol or raw_isin,
            "lookup_symbols": lookup_symbols,
            "synthetic_price_rappen": None,
            "identifier_basis": identifier_basis,
            "pricing_note": (
                "Kurspflege ueber gepflegtes Handelssymbol."
                if identifier_basis == "symbol"
                else "ISIN vorhanden, aber fuer externe Preisfeeds ist meist noch ein Handelssymbol noetig."
            ),
        }

    if catalog:
        return {
            "product_name": product_name,
            "symbol": catalog.get("lookup_symbol"),
            "isin": catalog.get("isin"),
            "currency": raw_currency,
            "exchange_code": raw_exchange_code,
            "lookup_mode": str(catalog.get("lookup_mode") or "unmapped"),
            "lookup_symbol": catalog.get("lookup_symbol"),
            "synthetic_price_rappen": catalog.get("synthetic_price_rappen"),
            "identifier_basis": "catalog",
            "pricing_note": catalog.get("pricing_note"),
        }

    return {
        "product_name": product_name,
        "symbol": raw_symbol,
        "isin": raw_isin,
        "currency": raw_currency,
        "exchange_code": raw_exchange_code,
        "lookup_mode": "unmapped",
        "lookup_symbol": None,
        "synthetic_price_rappen": None,
        "identifier_basis": None,
        "pricing_note": None,
    }


def is_market_mapped(profile: dict[str, Any] | None) -> bool:
    return str((profile or {}).get("lookup_mode") or "").strip() not in {"", "unmapped"}


def validate_default_product_market_coverage(product_names: list[str]) -> None:
    missing = [
        name
        for name in product_names
        if not is_market_mapped(default_market_entry(name) or {"lookup_mode": "unmapped"})
    ]
    if missing:
        raise ValueError(f"Default-Produktkatalog ohne Marktprofil: {', '.join(sorted(missing))}")
