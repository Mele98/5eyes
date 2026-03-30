from __future__ import annotations

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
    "iShares Core SPI ETF": {
        "lookup_mode": "proxy",
        "lookup_symbol": "EWL",
        "pricing_note": "Proxy via iShares MSCI Switzerland ETF, bis exakte SIX-Titelkurse kuratiert sind.",
    },
    "SPDR Swiss Small Cap ETF": {
        "lookup_mode": "proxy",
        "lookup_symbol": "IJR",
        "pricing_note": "Small-cap Proxy bis ein dedizierter Schweiz Small/Mid Lookup gepflegt ist.",
    },
    "iShares Core MSCI World UCITS ETF": {
        "lookup_mode": "proxy",
        "lookup_symbol": "URTH",
        "pricing_note": "World-Equity Proxy fuer die UCITS Share Class.",
    },
    "Vanguard FTSE Developed Europe ETF": {
        "lookup_mode": "proxy",
        "lookup_symbol": "VGK",
        "pricing_note": "Europa-Proxy ueber die liquide Vanguard Developed Europe Line.",
    },
    "iShares Core MSCI EM IMI ETF": {
        "lookup_mode": "proxy",
        "lookup_symbol": "IEMG",
        "pricing_note": "Emerging-Markets IMI Proxy fuer die UCITS Share Class.",
    },
    "VanEck Defense UCITS ETF": {
        "lookup_mode": "proxy",
        "lookup_symbol": "ITA",
        "pricing_note": "Defense-Proxy bis exakte UCITS-Symbole final kuratiert sind.",
    },
    "Energy Select Sector ETF": {
        "lookup_mode": "direct",
        "lookup_symbol": "XLE",
        "pricing_note": "Direkter Marktpreis ueber das gelistete Produkt.",
    },
    "Consumer Staples Tobacco Tilt ETF": {
        "lookup_mode": "proxy",
        "lookup_symbol": "PM",
        "pricing_note": "Tobacco-Tilt Proxy ueber Philip Morris als Themen-Stellvertreter.",
    },
    "Global Beverage Leaders ETF": {
        "lookup_mode": "proxy",
        "lookup_symbol": "STZ",
        "pricing_note": "Beverage-Proxy ueber Constellation Brands bis ein ETF-Lookup gepflegt ist.",
    },
    "Roundhill Sports Betting ETF": {
        "lookup_mode": "direct",
        "lookup_symbol": "BETZ",
        "pricing_note": "Direkter Marktpreis ueber das gelistete Produkt.",
    },
    "VanEck Uranium and Nuclear ETF": {
        "lookup_mode": "proxy",
        "lookup_symbol": "NLR",
        "pricing_note": "Nuclear-Proxy bis exakte UCITS-Symbole final kuratiert sind.",
    },
    "Swisscanto Bond CHF": {
        "lookup_mode": "proxy",
        "lookup_symbol": "BND",
        "pricing_note": "IG-Bond Proxy bis eine saubere CHF-Anleihen-Linie integriert ist.",
    },
    "iShares Global Aggregate Bond CHF Hedged": {
        "lookup_mode": "proxy",
        "lookup_symbol": "IAGG",
        "pricing_note": "Global Aggregate Bond Proxy fuer die CHF-hedged Share Class.",
    },
    "PIMCO High Yield Fund": {
        "lookup_mode": "proxy",
        "lookup_symbol": "HYG",
        "pricing_note": "High-Yield Proxy ueber den liquiden ETF-Markt.",
    },
    "EM Local Bond Opportunities": {
        "lookup_mode": "proxy",
        "lookup_symbol": "EMLC",
        "pricing_note": "EM Local Bond Proxy ueber den liquiden ETF-Markt.",
    },
    "Swisscanto Real Estate Fund": {
        "lookup_mode": "proxy",
        "lookup_symbol": "RWO",
        "pricing_note": "Immobilien-Proxy bis der exakte CHF-RE-Fund-Feed gepflegt ist.",
    },
    "iShares Developed Markets Property Yield": {
        "lookup_mode": "proxy",
        "lookup_symbol": "REET",
        "pricing_note": "Property-Yield Proxy ueber den liquiden REIT-Markt.",
    },
    "ZKB Gold ETF": {
        "lookup_mode": "proxy",
        "lookup_symbol": "GLD",
        "pricing_note": "Gold-Proxy bis der exakte ZKB-Lookup finalisiert ist.",
    },
    "JPM Global Macro Opportunities": {
        "lookup_mode": "proxy",
        "lookup_symbol": "QAI",
        "pricing_note": "Multi-Strategy Proxy fuer makrobasierten Alternatives-Exposure.",
    },
    "Man AHL TargetRisk": {
        "lookup_mode": "proxy",
        "lookup_symbol": "KMLM",
        "pricing_note": "Managed-Futures Proxy fuer die AHL-Strategieklasse.",
    },
    "Partners Group Listed PE": {
        "lookup_mode": "proxy",
        "lookup_symbol": "PSP",
        "pricing_note": "Listed-Private-Equity Proxy ueber den liquiden ETF-Markt.",
    },
    "21Shares Core Bitcoin ETP": {
        "lookup_mode": "proxy",
        "lookup_symbol": "IBIT",
        "pricing_note": "Bitcoin-Proxy ueber den liquiden Spot-ETF-Markt.",
    },
    "UBS Geldmarktfonds CHF": {
        "lookup_mode": "synthetic_par",
        "synthetic_price_rappen": 100,
        "pricing_note": "Synthetischer Par-Wert bis ein CHF-Geldmarkt-Feed angebunden ist.",
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
        return symbol.lower() if provider == "stooq" else symbol

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


def default_market_entry(product_name: str | None) -> dict[str, Any] | None:
    key = str(product_name or "").strip()
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
