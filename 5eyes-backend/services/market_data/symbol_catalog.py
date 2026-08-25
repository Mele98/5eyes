"""Sub-Asset-Catalog (Phase 1 von SMI-1988 + Sub-Anlageklassen-Sprint).

Mappt 18 Berater-relevante Sub-Anlageklassen auf konkrete Index-/ETF-Symbole
pro Provider. Pro Sub-Asset eine Cascade-Order: Provider mit fruehestem
Daten-Start gewinnt fuer historische Jahre, taegliche Aktualisierungen
laufen dann ueber den schnellsten Provider.

Convention:
- Top-Level-Anlageklassen bleiben unveraendert (Aktien, Obligationen,
  Immobilien, Alternative, Liquiditaet). Das aktuelle Schema (NULL =
  Top-Level-Aggregat) bleibt funktional.
- Sub-Asset-Schluessel sind <TopLevel>_<Region>_<Detail> auf Deutsch
  (z.B. "Aktien_CH_Large"). Konsistent mit bestehenden Top-Level-Keys.
- Provider-Names matchen `MarketDataProvider.name` aus services/market_data.

Bloomberg-Marker: BloombergProvider ist heute KEIN aktiver Provider (siehe
Phase 5 fuer Discovery-Pattern). Symbole sind dokumentiert damit ein
externes Paket den Catalog direkt nutzen kann.

Daten-Vorbehalt: pre_tr_dividend_yield_bps ist die historische Dividenden-
Schaetzung fuer Perioden mit nur Price-Index (z.B. SMI 1988-1998). Wird in
Phase 2 (Backfill) zur Total-Return-Approximation addiert. Quelle der
Schaetzungen ist im docstring jedes Sub-Assets verlinkt.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional


@dataclass(frozen=True)
class ProviderSymbol:
    """Konkrete Ticker-Konvention eines Sub-Assets pro Provider.

    `data_starts` ist das Jahr ab dem dieser Provider Daten fuer dieses
    Symbol liefert. None heisst unbekannt / Placeholder (z.B. Bloomberg
    bevor BloombergProvider implementiert ist).

    `is_total_return` = True wenn das Symbol Total-Return (inkl.
    Dividenden) liefert. False = nur Price-Index, dann braucht der
    Backfill-Service den pre_tr_dividend_yield_bps aus der SubAssetClass.
    """
    provider: str  # "yfinance" | "stooq" | "alphavantage" | "twelvedata" | "bloomberg"
    symbol: str
    data_starts: Optional[int] = None
    is_total_return: bool = True


@dataclass(frozen=True)
class SubAssetClass:
    """Berater-relevante Sub-Anlageklasse mit Provider-Cascade."""
    key: str
    display_name: str
    top_level: str
    currency: str  # ISO-3, native Notierungswaehrung des Index
    index_start_year: int  # ab wann der zugrundeliegende Index existiert
    tr_start_year: int  # ab wann Total-Return-Index existiert (>= index_start_year)
    pre_tr_dividend_yield_bps: int  # Annahme fuer Perioden index_start..tr_start-1
    provider_symbols: tuple[ProviderSymbol, ...]
    notes: str = ""

    def cascade(self) -> tuple[ProviderSymbol, ...]:
        """Provider-Order fuer Backfill: fruehester Daten-Start zuerst."""
        return tuple(sorted(
            self.provider_symbols,
            key=lambda s: (s.data_starts or 9999, s.provider),
        ))


# Top-Level-Set MUSS mit _VALID_ASSET_CLASSES in routers/system.py +
# DEFAULT_SYMBOL_MAP in annual_returns_backfill.py konsistent sein.
TOP_LEVEL_ASSET_CLASSES: frozenset[str] = frozenset({
    "Aktien", "Obligationen", "Immobilien", "Alternative", "Liquiditaet",
})


SUB_ASSET_CATALOG: Mapping[str, SubAssetClass] = {
    # ============================================================
    # AKTIEN (7 Sub-Assets)
    # ============================================================
    "Aktien_CH_Large": SubAssetClass(
        key="Aktien_CH_Large",
        display_name="Aktien CH Large Cap",
        top_level="Aktien",
        currency="CHF",
        index_start_year=1988,  # SMI-Einfuehrung
        tr_start_year=1999,  # SMIC (SMI Total Return) ab 1999
        pre_tr_dividend_yield_bps=250,  # 2.5% p.a. CH-Dividendenrendite historisch
        provider_symbols=(
            ProviderSymbol("yfinance", "^SSMI", data_starts=1990, is_total_return=False),
            ProviderSymbol("stooq", "^smi", data_starts=1988, is_total_return=False),
            ProviderSymbol("bloomberg", "SMI Index", data_starts=1988, is_total_return=False),
            ProviderSymbol("bloomberg", "SMIC Index", data_starts=1999, is_total_return=True),
        ),
        notes="SMI Price-Index ab 1988. SMIC (Total Return) erst ab 1999. "
              "Fuer 1988-1998 wird pre_tr_dividend_yield_bps addiert.",
    ),
    "Aktien_CH_SmallMid": SubAssetClass(
        key="Aktien_CH_SmallMid",
        display_name="Aktien CH Small/Mid Cap",
        top_level="Aktien",
        currency="CHF",
        index_start_year=2004,  # SPI Extra Launch
        tr_start_year=2004,
        pre_tr_dividend_yield_bps=200,
        provider_symbols=(
            ProviderSymbol("yfinance", "^SPIEX", data_starts=2004, is_total_return=True),
            ProviderSymbol("bloomberg", "SPIEX Index", data_starts=2004, is_total_return=True),
        ),
    ),
    "Aktien_EU_Large": SubAssetClass(
        key="Aktien_EU_Large",
        display_name="Aktien EU Large Cap",
        top_level="Aktien",
        currency="EUR",
        index_start_year=1991,  # Stoxx 600 Backfill seit 1986 verfuegbar bei Bloomberg
        tr_start_year=1991,
        pre_tr_dividend_yield_bps=300,
        provider_symbols=(
            ProviderSymbol("yfinance", "^STOXX", data_starts=2000, is_total_return=False),
            ProviderSymbol("stooq", "^stoxx", data_starts=1991, is_total_return=False),
            ProviderSymbol("bloomberg", "SXXP Index", data_starts=1986, is_total_return=False),
            ProviderSymbol("bloomberg", "SXXR Index", data_starts=1991, is_total_return=True),
        ),
    ),
    "Aktien_US_Large": SubAssetClass(
        key="Aktien_US_Large",
        display_name="Aktien US Large Cap",
        top_level="Aktien",
        currency="USD",
        index_start_year=1950,
        tr_start_year=1988,  # SPXT (S&P 500 TR) tracked ab 1988
        pre_tr_dividend_yield_bps=200,
        provider_symbols=(
            ProviderSymbol("yfinance", "^GSPC", data_starts=1950, is_total_return=False),
            ProviderSymbol("yfinance", "^SP500TR", data_starts=1988, is_total_return=True),
            ProviderSymbol("stooq", "^spx", data_starts=1950, is_total_return=False),
            ProviderSymbol("bloomberg", "SPX Index", data_starts=1950, is_total_return=False),
            ProviderSymbol("bloomberg", "SPXT Index", data_starts=1988, is_total_return=True),
        ),
    ),
    "Aktien_US_Small": SubAssetClass(
        key="Aktien_US_Small",
        display_name="Aktien US Small Cap",
        top_level="Aktien",
        currency="USD",
        index_start_year=1987,  # Russell 2000 Launch
        tr_start_year=1987,
        pre_tr_dividend_yield_bps=150,
        provider_symbols=(
            ProviderSymbol("yfinance", "^RUT", data_starts=1987, is_total_return=False),
            ProviderSymbol("yfinance", "IWM", data_starts=2000, is_total_return=True),
            ProviderSymbol("bloomberg", "RTY Index", data_starts=1987, is_total_return=False),
            ProviderSymbol("bloomberg", "RU20INTR Index", data_starts=1987, is_total_return=True),
        ),
    ),
    "Aktien_EM": SubAssetClass(
        key="Aktien_EM",
        display_name="Aktien Emerging Markets",
        top_level="Aktien",
        currency="USD",
        index_start_year=1988,  # MSCI EM Index Launch
        tr_start_year=1988,  # MSCI Standard Indizes als NTR/GTR verfuegbar
        pre_tr_dividend_yield_bps=0,
        provider_symbols=(
            ProviderSymbol("yfinance", "EEM", data_starts=2003, is_total_return=True),
            ProviderSymbol("bloomberg", "MXEF Index", data_starts=1988, is_total_return=True),
        ),
        notes="ETF (EEM) erst ab 2003. MSCI-EM-Index existiert seit 1988, "
              "aber yfinance hat keine direkten Index-Daten — Bloomberg "
              "noetig fuer Vor-2003-Daten.",
    ),
    "Aktien_Welt": SubAssetClass(
        key="Aktien_Welt",
        display_name="Aktien Welt (Developed Markets)",
        top_level="Aktien",
        currency="USD",
        index_start_year=1969,  # MSCI World Launch
        tr_start_year=1969,
        pre_tr_dividend_yield_bps=0,
        provider_symbols=(
            ProviderSymbol("yfinance", "URTH", data_starts=2012, is_total_return=True),
            ProviderSymbol("bloomberg", "MXWO Index", data_starts=1969, is_total_return=True),
        ),
        notes="iShares MSCI World (URTH) erst ab 2012. MSCI-World-Index "
              "existiert seit 1969 (Bloomberg).",
    ),

    # ============================================================
    # OBLIGATIONEN (4 Sub-Assets)
    # ============================================================
    "Obligationen_CH_IG": SubAssetClass(
        key="Obligationen_CH_IG",
        display_name="Obligationen CH Investment Grade",
        top_level="Obligationen",
        currency="CHF",
        index_start_year=2007,
        tr_start_year=2007,
        pre_tr_dividend_yield_bps=0,
        provider_symbols=(
            ProviderSymbol("yfinance", "CSBGC.SW", data_starts=2007, is_total_return=True),
            ProviderSymbol("bloomberg", "SBR14T Index", data_starts=2007, is_total_return=True),
        ),
        notes="SBI AAA-BBB Total Return Index. Pre-2007 Daten waeren nur "
              "ueber synthetische Yield-zu-Return-Konversion verfuegbar.",
    ),
    "Obligationen_Welt_IG_HedgedCHF": SubAssetClass(
        key="Obligationen_Welt_IG_HedgedCHF",
        display_name="Obligationen Welt Investment Grade (CHF gehedgt)",
        top_level="Obligationen",
        currency="CHF",
        index_start_year=2009,
        tr_start_year=2009,
        pre_tr_dividend_yield_bps=0,
        provider_symbols=(
            ProviderSymbol("yfinance", "AGGG.L", data_starts=2009, is_total_return=True),
            ProviderSymbol("bloomberg", "LEGATRCH Index", data_starts=2009, is_total_return=True),
        ),
        notes="Bloomberg Global Aggregate CHF Hedged. Vorher Welt IG USD "
              "+ FX-Hedge synthetisch.",
    ),
    "Obligationen_Welt_HY": SubAssetClass(
        key="Obligationen_Welt_HY",
        display_name="Obligationen Welt High Yield",
        top_level="Obligationen",
        currency="USD",
        index_start_year=1995,
        tr_start_year=1995,
        pre_tr_dividend_yield_bps=0,
        provider_symbols=(
            ProviderSymbol("yfinance", "HYG", data_starts=2007, is_total_return=True),
            ProviderSymbol("bloomberg", "LF98TRUU Index", data_starts=1995, is_total_return=True),
        ),
    ),
    "Obligationen_EM": SubAssetClass(
        key="Obligationen_EM",
        display_name="Obligationen Emerging Markets (USD)",
        top_level="Obligationen",
        currency="USD",
        index_start_year=1993,
        tr_start_year=1993,
        pre_tr_dividend_yield_bps=0,
        provider_symbols=(
            ProviderSymbol("yfinance", "EMB", data_starts=2007, is_total_return=True),
            ProviderSymbol("bloomberg", "JPEIDIVR Index", data_starts=1993, is_total_return=True),
        ),
        notes="JPMorgan EMBI Diversified. Vor-2007 Bloomberg.",
    ),

    # ============================================================
    # IMMOBILIEN (2 Sub-Assets)
    # ============================================================
    "Immobilien_CH": SubAssetClass(
        key="Immobilien_CH",
        display_name="Immobilien Schweiz (Fonds + AG)",
        top_level="Immobilien",
        currency="CHF",
        index_start_year=1995,
        tr_start_year=1995,
        pre_tr_dividend_yield_bps=0,
        provider_symbols=(
            ProviderSymbol("yfinance", "SRECHA.SW", data_starts=2010, is_total_return=True),
            ProviderSymbol("bloomberg", "REAL Index", data_starts=1995, is_total_return=True),
        ),
        notes="SXI Real Estate Funds TR. ETF (SRECHA) erst ab 2010 — "
              "Bloomberg REAL Index seit 1995.",
    ),
    "Immobilien_Welt": SubAssetClass(
        key="Immobilien_Welt",
        display_name="Immobilien Welt (Listed REITs)",
        top_level="Immobilien",
        currency="USD",
        index_start_year=1990,
        tr_start_year=1990,
        pre_tr_dividend_yield_bps=0,
        provider_symbols=(
            ProviderSymbol("yfinance", "VNQ", data_starts=2004, is_total_return=True),
            ProviderSymbol("yfinance", "IFGL", data_starts=2007, is_total_return=True),
            ProviderSymbol("bloomberg", "FNERTR Index", data_starts=1990, is_total_return=True),
        ),
    ),

    # ============================================================
    # ALTERNATIVE (3 Sub-Assets)
    # ============================================================
    "Alternative_Gold": SubAssetClass(
        key="Alternative_Gold",
        display_name="Gold (Spot)",
        top_level="Alternative",
        currency="USD",
        index_start_year=1968,  # LBMA Gold Fix
        tr_start_year=1968,  # Spot ist per Definition Total Return
        pre_tr_dividend_yield_bps=0,
        provider_symbols=(
            ProviderSymbol("yfinance", "GLD", data_starts=2004, is_total_return=True),
            ProviderSymbol("yfinance", "GC=F", data_starts=2000, is_total_return=True),
            ProviderSymbol("stooq", "xauusd", data_starts=1985, is_total_return=True),
            ProviderSymbol("bloomberg", "XAU Curncy", data_starts=1968, is_total_return=True),
        ),
    ),
    "Alternative_Krypto": SubAssetClass(
        key="Alternative_Krypto",
        display_name="Krypto (Bitcoin Proxy)",
        top_level="Alternative",
        currency="USD",
        index_start_year=2010,  # Erster Bitcoin-Preis 2010
        tr_start_year=2010,
        pre_tr_dividend_yield_bps=0,
        provider_symbols=(
            ProviderSymbol("yfinance", "BTC-USD", data_starts=2014, is_total_return=True),
            ProviderSymbol("bloomberg", "XBT Curncy", data_starts=2014, is_total_return=True),
        ),
        notes="BTC-USD erst ab 2014 zuverlaessig. Pre-2014 Daten waeren "
              "rein historische Marker.",
    ),
    "Alternative_PrivateEquity": SubAssetClass(
        key="Alternative_PrivateEquity",
        display_name="Private Equity (Listed)",
        top_level="Alternative",
        currency="USD",
        index_start_year=1998,  # LPX 50 Launch
        tr_start_year=1998,
        pre_tr_dividend_yield_bps=0,
        provider_symbols=(
            ProviderSymbol("yfinance", "PSP", data_starts=2006, is_total_return=True),
            ProviderSymbol("bloomberg", "LPX50TR Index", data_starts=1998, is_total_return=True),
        ),
        notes="Listed Private Equity als Proxy fuer echte PE. ETF (PSP) "
              "ab 2006, LPX-Index seit 1998 (Bloomberg).",
    ),

    # ============================================================
    # LIQUIDITAET (2 Sub-Assets)
    # ============================================================
    "Liquiditaet_CHF": SubAssetClass(
        key="Liquiditaet_CHF",
        display_name="Liquiditaet CHF (SARON / Money Market)",
        top_level="Liquiditaet",
        currency="CHF",
        index_start_year=1999,  # SAR-LIBOR Vorgaenger
        tr_start_year=1999,
        pre_tr_dividend_yield_bps=0,
        provider_symbols=(
            ProviderSymbol("bloomberg", "SSARON Index", data_starts=2017, is_total_return=True),
            ProviderSymbol("bloomberg", "SF0001M Index", data_starts=1989, is_total_return=True),
        ),
        notes="SARON ab 2017. Vor-2017 SAR-LIBOR (Bloomberg SF0001M). "
              "yfinance hat keine direkte CHF-Money-Market-Serie.",
    ),
    "Liquiditaet_USD": SubAssetClass(
        key="Liquiditaet_USD",
        display_name="Liquiditaet USD (T-Bill 1-3M)",
        top_level="Liquiditaet",
        currency="USD",
        index_start_year=1954,
        tr_start_year=1954,
        pre_tr_dividend_yield_bps=0,
        provider_symbols=(
            ProviderSymbol("yfinance", "BIL", data_starts=2007, is_total_return=True),
            ProviderSymbol("yfinance", "^IRX", data_starts=1960, is_total_return=False),
            ProviderSymbol("bloomberg", "USGG3M Index", data_starts=1954, is_total_return=False),
        ),
    ),
}


# ---------- Helper-API ----------

def get_sub_asset(key: str) -> SubAssetClass:
    """Hebt SubAssetClass nach Schluessel heraus. KeyError wenn unbekannt."""
    try:
        return SUB_ASSET_CATALOG[key]
    except KeyError as exc:
        raise KeyError(
            f"Unbekannter Sub-Asset-Schluessel: {key!r}. "
            f"Bekannt: {sorted(SUB_ASSET_CATALOG.keys())}"
        ) from exc


def sub_assets_for_top_level(top_level: str) -> tuple[SubAssetClass, ...]:
    """Alle Sub-Assets eines Top-Level (in deterministischer Reihenfolge)."""
    return tuple(sorted(
        (sa for sa in SUB_ASSET_CATALOG.values() if sa.top_level == top_level),
        key=lambda sa: sa.key,
    ))


def all_sub_asset_keys() -> tuple[str, ...]:
    """Alle Sub-Asset-Schluessel in deterministischer Reihenfolge."""
    return tuple(sorted(SUB_ASSET_CATALOG.keys()))


def provider_cascade(key: str) -> tuple[ProviderSymbol, ...]:
    """Cascade-Order eines Sub-Assets (fruehester Daten-Start zuerst)."""
    return get_sub_asset(key).cascade()


def total_return_symbols(key: str) -> tuple[ProviderSymbol, ...]:
    """Nur die Total-Return-Symbole in Cascade-Order."""
    return tuple(s for s in provider_cascade(key) if s.is_total_return)


def price_only_symbols(key: str) -> tuple[ProviderSymbol, ...]:
    """Nur die Price-Index-Symbole (brauchen pre_tr_dividend_yield_bps)."""
    return tuple(s for s in provider_cascade(key) if not s.is_total_return)
