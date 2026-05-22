"""Sprint U-P17 (2026-05-21): Strategie-Backtest auf Annual-Returns.

Wendet die SOLL-Strategie (TargetAllocation Bucket-Gewichte) eines Mandates
auf die historischen Jahresrenditen pro Asset-Klasse an
(asset_class_annual_returns) und liefert einen Asset-Manager-Backtest:
Wealth-Index-Pfad, CAGR, Volatilität, Sharpe, Max-Drawdown, Best/Worst-Year
und Win-Rate.

Zwei Modi werden parallel geliefert:
1. Mit jährlichem Rebalancing zur SOLL-Quote (klassischer Asset-Manager-
   Backtest: Jahresende → zurück zu Soll-Gewichten).
2. Buy-and-Hold ohne Rebalancing — Initial-Allokation einmal investiert,
   die Bucket-Werte driften mit ihren individuellen Renditen.

Optional zusätzlich ein Benchmark-Mix (z.B. 100% Aktien oder 60/40) mit
identischer Methode und Zeitraum.

KEINE Cashflows, KEINE Spar-/Bezugspläne — der Backtest zeigt die reine
Strategie-Performance auf einem fixen Initial-Kapital. Der Initial-Wert
ist `advisory_wealth_at_generation_rappen` aus der aktiven
TargetAllocation; Fallback: aktuelle Beratungsvermögen-Summe.

Wechselwirkungen:
- U-P14 admin/system/annual-returns als Datenquelle.
- U-P10 TargetAllocation als SOLL-Quelle.
- Read-only Service: keine DB-Mutation, kein Audit-Log.

Granularität: jährlich. Daily-Auflösung kommt mit U-P11 (Marktdaten-
Pipeline) — dieselbe Endpoint-Signatur, dann nur intern andere Datenquelle.
"""
from __future__ import annotations

import math
from bisect import bisect_right
from typing import Iterable, Mapping

from sqlalchemy.orm import Session

from datetime import date as Date

from models.allocation import CapitalMarketAssumption, TargetAllocation
from models.mandates import Mandate
from models.snapshots import AssetClassAnnualReturn, AssetClassFxHistory, AssetClassPriceHistory
from models.wealth import WealthPosition


BUCKETS = ("equities", "bonds", "real_estate", "alternatives", "liquidity")

# Annual-Returns-Tabelle nutzt deutsche Asset-Klassen-Namen; Engine + UI
# verwenden englische Bucket-Keys.
ASSET_CLASS_DE_TO_EN: dict[str, str] = {
    "Aktien": "equities",
    "Obligationen": "bonds",
    "Immobilien": "real_estate",
    "Alternative": "alternatives",
    "Liquiditaet": "liquidity",
}
ASSET_CLASS_EN_TO_DE: dict[str, str] = {v: k for k, v in ASSET_CLASS_DE_TO_EN.items()}

BUCKET_LABELS_DE = {
    "equities": "Aktien",
    "bonds": "Obligationen",
    "real_estate": "Immobilien",
    "alternatives": "Alternative Anlagen",
    "liquidity": "Liquidität",
}


# ---------------------------------------------------------------------------
# Datenquelle
# ---------------------------------------------------------------------------


def load_annual_returns_matrix(db: Session) -> dict[int, dict[str, int]]:
    """Lädt die annual_returns-Tabelle und liefert {year: {bucket_en: bps}}.

    Nur Jahre, in denen ALLE 5 Asset-Klassen gepflegt sind, werden
    zurückgegeben. Unvollständige Jahre würden Phantom-Returns auf 0
    bedeuten und das Bild verzerren.
    """
    rows = (
        db.query(AssetClassAnnualReturn)
        .order_by(AssetClassAnnualReturn.year, AssetClassAnnualReturn.asset_class)
        .all()
    )
    by_year: dict[int, dict[str, int]] = {}
    for row in rows:
        bucket_en = ASSET_CLASS_DE_TO_EN.get(str(row.asset_class or "").strip())
        if not bucket_en:
            continue
        try:
            year = int(row.year)
            bps = int(row.return_bps)
        except (TypeError, ValueError):
            continue
        by_year.setdefault(year, {})[bucket_en] = bps
    # Filter: nur vollständige Jahre (alle 5 Buckets vorhanden)
    return {
        y: m
        for y, m in by_year.items()
        if all(b in m for b in BUCKETS)
    }


def _years_in_range(
    matrix: Mapping[int, Mapping[str, int]],
    start_year: int | None,
    end_year: int | None,
) -> list[int]:
    if not matrix:
        return []
    years = sorted(matrix.keys())
    if start_year is not None:
        years = [y for y in years if y >= int(start_year)]
    if end_year is not None:
        years = [y for y in years if y <= int(end_year)]
    return years


# ---------------------------------------------------------------------------
# Berechnung der Pfade
# ---------------------------------------------------------------------------


def compound_wealth_path(
    initial_value_rappen: int,
    weights_bps: Mapping[str, int],
    years_returns: list[tuple[int, Mapping[str, int]]],
    *,
    rebalance: bool,
) -> dict:
    """Berechnet Wealth-Index-Pfad + jährliche Portfolio-Renditen.

    Args:
        initial_value_rappen: Startkapital in Rappen (Beratungsvermögen)
        weights_bps: Soll-Gewichte (must sum to 10000)
        years_returns: aufsteigend sortiert [(year, {bucket: bps}), ...]
        rebalance: True = jährlich auf Soll-Gewichte zurücksetzen.
            False = passive Drift, Bucket-Werte werden einzeln aufgezinst.

    Returns:
        {
            "start_year_label": int | None — z.B. years[0]-1 (Jahr VOR
                erster Performance), oder years[0] wenn keine Jahre da
            "wealth_path_rappen": [(year, total_rappen), ...] inkl. Start
            "annual_returns_bps": [bps, ...] pro Jahr
            "bucket_path_rappen": [{year, bucket: value}, ...] inkl. Start
        }
    """
    initial_value_rappen = int(initial_value_rappen)
    total_weight = sum(int(weights_bps.get(b, 0) or 0) for b in BUCKETS)
    if total_weight <= 0:
        raise ValueError("Bucket-Gewichte summieren auf 0 — Backtest unmöglich.")

    # Initial-Bucket-Werte (gerundet auf Rappen). Round-Off geht auf liquidity.
    bucket_values: dict[str, float] = {}
    allocated = 0
    for b in BUCKETS:
        share = (int(weights_bps.get(b, 0) or 0) / total_weight)
        amount = int(round(initial_value_rappen * share))
        bucket_values[b] = float(amount)
        allocated += amount
    # Korrigiere Rundungsdifferenz
    bucket_values["liquidity"] += float(initial_value_rappen - allocated)

    wealth_path: list[tuple[int, int]] = []
    annual_returns_bps: list[int] = []
    bucket_path: list[dict] = []

    start_label = (years_returns[0][0] - 1) if years_returns else None
    initial_total = int(round(sum(bucket_values.values())))
    wealth_path.append((start_label if start_label is not None else 0, initial_total))
    bucket_path.append({"year": start_label, **{b: int(round(bucket_values[b])) for b in BUCKETS}})

    for year, ret_map in years_returns:
        prev_total = sum(bucket_values.values())
        if prev_total <= 0:
            # Totalverlust-Pfad: alle Werte 0
            annual_returns_bps.append(0)
            wealth_path.append((year, 0))
            bucket_path.append({"year": year, **{b: 0 for b in BUCKETS}})
            continue

        # Anwenden der Bucket-Returns
        new_values = {
            b: bucket_values[b] * (1.0 + float(ret_map.get(b, 0) or 0) / 10000.0)
            for b in BUCKETS
        }
        new_total = sum(new_values.values())
        portfolio_ret = (new_total - prev_total) / prev_total
        annual_returns_bps.append(int(round(portfolio_ret * 10000)))

        if rebalance:
            # Reset Bucket-Werte auf Soll-Gewichte des neuen Total-Wealth
            bucket_values = {}
            allocated_f = 0.0
            for b in BUCKETS:
                share = int(weights_bps.get(b, 0) or 0) / total_weight
                bucket_values[b] = new_total * share
                allocated_f += bucket_values[b]
            # mini-Korrektur für float-drift auf liquidity
            bucket_values["liquidity"] += new_total - allocated_f
        else:
            bucket_values = new_values

        total_int = int(round(sum(bucket_values.values())))
        wealth_path.append((year, total_int))
        bucket_path.append({"year": year, **{b: int(round(bucket_values[b])) for b in BUCKETS}})

    return {
        "start_year_label": start_label,
        "wealth_path_rappen": wealth_path,
        "annual_returns_bps": annual_returns_bps,
        "bucket_path_rappen": bucket_path,
    }


# ---------------------------------------------------------------------------
# Metriken
# ---------------------------------------------------------------------------


def compute_metrics(
    wealth_path_rappen: list[tuple[int, int]],
    annual_returns_bps: list[int],
    *,
    risk_free_bps: int = 80,
) -> dict:
    """Klassische Asset-Manager-Backtest-Metriken.

    Args:
        wealth_path_rappen: [(year, total_rappen), ...] inkl. Startwert
            (also len == n_years + 1)
        annual_returns_bps: jährliche Portfolio-Returns in bps
            (len == n_years)
        risk_free_bps: Annualisierte risikolose Rate für Sharpe (default 80)

    Returns:
        Alle Werte als Integer (bps oder x100 wo dezimale Präzision nötig):
        cagr_bps, vol_bps, sharpe_x100, max_drawdown_bps, best_year_bps,
        best_year_label, worst_year_bps, worst_year_label, win_rate_x100,
        total_return_bps, start_value_rappen, end_value_rappen,
        years_count, positive_years, negative_years
    """
    if not wealth_path_rappen or not annual_returns_bps:
        return {
            "cagr_bps": 0, "vol_bps": 0, "sharpe_x100": 0,
            "max_drawdown_bps": 0, "best_year_bps": 0,
            "best_year_label": None, "worst_year_bps": 0, "worst_year_label": None,
            "win_rate_x100": 0, "total_return_bps": 0,
            "start_value_rappen": 0, "end_value_rappen": 0,
            "years_count": 0, "positive_years": 0, "negative_years": 0,
        }

    start_value = int(wealth_path_rappen[0][1])
    end_value = int(wealth_path_rappen[-1][1])
    n_years = len(annual_returns_bps)

    # CAGR — Compound Annual Growth Rate
    if start_value > 0 and end_value > 0 and n_years > 0:
        cagr = (end_value / start_value) ** (1.0 / n_years) - 1.0
        cagr_bps = int(round(cagr * 10000))
    else:
        cagr_bps = 0

    # Annualisierte Volatilität — Stichproben-StdDev der jährlichen Returns
    if n_years >= 2:
        mean = sum(annual_returns_bps) / n_years
        var = sum((r - mean) ** 2 for r in annual_returns_bps) / (n_years - 1)
        vol = math.sqrt(var)
        vol_bps = int(round(vol))
    else:
        vol_bps = 0

    # Sharpe (annualisiert)
    if vol_bps > 0:
        sharpe = (cagr_bps - int(risk_free_bps)) / vol_bps
        sharpe_x100 = int(round(sharpe * 100))
    else:
        sharpe_x100 = 0

    # Max-Drawdown über den Wealth-Pfad
    peak = 0
    max_dd = 0.0
    for _yr, value in wealth_path_rappen:
        peak = max(peak, int(value))
        if peak > 0:
            dd = (peak - int(value)) / peak
            if dd > max_dd:
                max_dd = dd
    max_dd_bps = int(round(max_dd * 10000))

    # Best/Worst Year
    best_idx = max(range(n_years), key=lambda i: annual_returns_bps[i])
    worst_idx = min(range(n_years), key=lambda i: annual_returns_bps[i])
    # Year-Labels stammen aus wealth_path[1:] (path[0] ist Initialjahr)
    year_labels = [int(yr) for yr, _val in wealth_path_rappen[1:]]
    best_year_label = year_labels[best_idx] if best_idx < len(year_labels) else None
    worst_year_label = year_labels[worst_idx] if worst_idx < len(year_labels) else None

    # Win-Rate
    positive = sum(1 for r in annual_returns_bps if r > 0)
    negative = sum(1 for r in annual_returns_bps if r < 0)
    win_rate_x100 = int(round(positive / n_years * 10000)) if n_years > 0 else 0

    # Total Return
    if start_value > 0:
        total_return_bps = int(round((end_value - start_value) / start_value * 10000))
    else:
        total_return_bps = 0

    return {
        "cagr_bps": cagr_bps,
        "vol_bps": vol_bps,
        "sharpe_x100": sharpe_x100,
        "max_drawdown_bps": max_dd_bps,
        "best_year_bps": int(annual_returns_bps[best_idx]),
        "best_year_label": best_year_label,
        "worst_year_bps": int(annual_returns_bps[worst_idx]),
        "worst_year_label": worst_year_label,
        "win_rate_x100": win_rate_x100,
        "total_return_bps": total_return_bps,
        "start_value_rappen": start_value,
        "end_value_rappen": end_value,
        "years_count": n_years,
        "positive_years": positive,
        "negative_years": negative,
    }


def compute_drawdown_path_bps(wealth_path_rappen: list[tuple[int, int]]) -> list[dict]:
    """Drawdown-Pfad als bps pro Year (negativ = unter Peak).

    Returns: [{"year": int, "drawdown_bps": int}, ...]
        drawdown_bps <= 0; 0 = auf Peak.
    """
    out: list[dict] = []
    peak = 0
    for yr, value in wealth_path_rappen:
        peak = max(peak, int(value))
        dd_bps = 0
        if peak > 0:
            dd_bps = int(round((int(value) - peak) / peak * 10000))
        out.append({"year": int(yr) if yr is not None else 0, "drawdown_bps": dd_bps})
    return out


# ---------------------------------------------------------------------------
# Daily-Resolution (U-P19): Datenquelle, Pfad, Metriken
# ---------------------------------------------------------------------------

DAILY_PERIODS_PER_YEAR = 252  # Handelstage p.a. für Vol-Annualisierung
MAX_PATH_POINTS = 260  # Downsampling-Grenze für Charts (Metriken nutzen Vollpfad)


def _float_year_label(d: Date) -> float:
    """Kalenderdatum → kontinuierliches Jahr-Label (z.B. 2020-07-02 ≈ 2020.5).

    Erlaubt zeit-proportionale X-Achse in denselben Charts, die für den
    Annual-Modus ganzzahlige Jahre nutzen.
    """
    year_start = Date(d.year, 1, 1)
    days_in_year = (Date(d.year + 1, 1, 1) - year_start).days
    return d.year + (d.toordinal() - year_start.toordinal()) / days_in_year


CHF = "CHF"


def _load_fx_to_chf(db: Session, currencies: set[str]) -> dict[str, tuple[list[str], dict[str, float]]]:
    """Lädt pro Währung die tägliche FX→CHF-Reihe. Returns
    {ccy: (sorted_iso_dates, {iso_date: rate_to_chf})}. ISO-Datumsstrings
    sortieren lexikografisch korrekt → bisect-tauglich für Forward-Fill."""
    out: dict[str, tuple[list[str], dict[str, float]]] = {}
    for ccy in currencies:
        rows = (
            db.query(AssetClassFxHistory)
            .filter(AssetClassFxHistory.currency == ccy)
            .order_by(AssetClassFxHistory.price_date)
            .all()
        )
        rate_by_date: dict[str, float] = {}
        for row in rows:
            try:
                rate = int(row.rate_to_chf_x10000) / 10000.0
            except (TypeError, ValueError):
                continue
            if rate > 0:
                rate_by_date[str(row.price_date)] = rate
        if rate_by_date:
            out[ccy] = (sorted(rate_by_date.keys()), rate_by_date)
    return out


def load_daily_returns_series(
    db: Session,
    start_year: int | None = None,
    end_year: int | None = None,
) -> tuple[Date | None, list[tuple[Date, dict[str, int]]], dict]:
    """Lädt die tägliche EOD-Serie je Asset-Klasse, rechnet die Tagesrenditen
    WÄHRUNGSKORREKT nach CHF um und liefert sie als bps.

    Nur Handelstage, an denen ALLE 5 Asset-Klassen einen Kurs haben
    (Kalender-Schnittmenge), gehen in den Pfad. CHF-Tagesrendite je Asset:
        r_chf = (p_t/p_{t-1}) · (fx_t/fx_{t-1}) − 1
    wobei fx der native→CHF-Kurs der Asset-Währung ist (Forward-Fill bei
    FX-Lücken). CHF-Assets (oder ohne FX-Daten) laufen mit fx-Ratio 1.

    Returns:
        (anchor_date, series, fx_meta). fx_meta = {"converted": {bucket: ccy},
        "unconverted": [ccy,...]} (Nicht-CHF-Währungen ohne FX-Daten — als CHF
        approximiert). Leer (None, [], {}) wenn Daten unvollständig oder < 2 Tage.
    """
    rows = (
        db.query(AssetClassPriceHistory)
        .order_by(AssetClassPriceHistory.price_date)
        .all()
    )
    by_class: dict[str, dict[str, int]] = {}
    bucket_currency: dict[str, str] = {}
    for row in rows:
        bucket_en = ASSET_CLASS_DE_TO_EN.get(str(row.asset_class or "").strip())
        if not bucket_en:
            continue
        try:
            close = int(row.close_rappen)
        except (TypeError, ValueError):
            continue
        if close <= 0:
            continue
        by_class.setdefault(bucket_en, {})[str(row.price_date)] = close
        ccy = str(getattr(row, "currency", "") or "").upper()
        if ccy:
            bucket_currency[bucket_en] = ccy

    if not all(b in by_class and by_class[b] for b in BUCKETS):
        return (None, [], {})

    common = set(by_class[BUCKETS[0]].keys())
    for b in BUCKETS[1:]:
        common &= set(by_class[b].keys())

    dated: list[Date] = []
    for ds in sorted(common):
        try:
            d = Date.fromisoformat(ds)
        except ValueError:
            continue
        if start_year is not None and d.year < int(start_year):
            continue
        if end_year is not None and d.year > int(end_year):
            continue
        dated.append(d)

    if len(dated) < 2:
        return (None, [], {})

    # FX-Reihen für alle benötigten Nicht-CHF-Währungen laden
    needed_ccys = {c for c in bucket_currency.values() if c and c != CHF}
    fx_series = _load_fx_to_chf(db, needed_ccys)
    converted: dict[str, str] = {}
    unconverted: set[str] = set()
    for b in BUCKETS:
        ccy = bucket_currency.get(b)
        if ccy and ccy != CHF:
            if ccy in fx_series:
                converted[b] = ccy
            else:
                unconverted.add(ccy)

    def _fx_at(ccy: str, d_iso: str) -> float | None:
        dates, rate_by_date = fx_series[ccy]
        idx = bisect_right(dates, d_iso) - 1  # letzter FX-Tag <= d_iso (Forward-Fill)
        if idx < 0:
            return None
        return rate_by_date[dates[idx]]

    anchor = dated[0]
    series: list[tuple[Date, dict[str, int]]] = []
    for i in range(1, len(dated)):
        d_prev = dated[i - 1].isoformat()
        d_cur = dated[i].isoformat()
        ret_map: dict[str, int] = {}
        for b in BUCKETS:
            p_prev = by_class[b][d_prev]
            p_cur = by_class[b][d_cur]
            if p_prev <= 0:
                ret_map[b] = 0
                continue
            fx_ratio = 1.0
            ccy = converted.get(b)
            if ccy:
                fx_prev = _fx_at(ccy, d_prev)
                fx_cur = _fx_at(ccy, d_cur)
                if fx_prev and fx_cur and fx_prev > 0:
                    fx_ratio = fx_cur / fx_prev
            ret_map[b] = int(round(((p_cur / p_prev) * fx_ratio - 1.0) * 10000))
        series.append((dated[i], ret_map))

    fx_meta = {"converted": converted, "unconverted": sorted(unconverted)}
    return (anchor, series, fx_meta)


def compound_daily_path(
    initial_value_rappen: int,
    weights_bps: Mapping[str, int],
    anchor_date: Date,
    series: list[tuple[Date, Mapping[str, int]]],
    *,
    rebalance: bool,
) -> dict:
    """Wie compound_wealth_path, aber täglich + Rebalancing nur am Jahreswechsel.

    Args:
        rebalance: True = beim ersten Handelstag eines neuen Kalenderjahres
            zurück auf Soll-Gewichte (Compounding bleibt täglich).
            False = passive Drift (Buy-and-Hold) über den ganzen Zeitraum.

    Returns:
        {
            "wealth_path_rappen": [(float_year_label, total_rappen), ...] inkl. Start,
            "annual_returns_bps": [bps, ...] — hier TAGES-Returns (Key-Parität
                zum Annual-Modus; von der Vol-Berechnung genutzt),
        }
    """
    initial_value_rappen = int(initial_value_rappen)
    total_weight = sum(int(weights_bps.get(b, 0) or 0) for b in BUCKETS)
    if total_weight <= 0:
        raise ValueError("Bucket-Gewichte summieren auf 0 — Backtest unmöglich.")

    def _alloc_to_weights(total: float) -> dict[str, float]:
        values: dict[str, float] = {}
        allocated = 0.0
        for b in BUCKETS:
            values[b] = total * (int(weights_bps.get(b, 0) or 0) / total_weight)
            allocated += values[b]
        values["liquidity"] += total - allocated  # float-drift-Korrektur
        return values

    bucket_values = _alloc_to_weights(float(initial_value_rappen))
    wealth_path: list[tuple[float, int]] = [
        (_float_year_label(anchor_date), int(round(sum(bucket_values.values()))))
    ]
    period_returns_bps: list[int] = []
    prev_year = anchor_date.year

    for d, ret_map in series:
        if rebalance and d.year != prev_year:
            bucket_values = _alloc_to_weights(sum(bucket_values.values()))
        prev_total = sum(bucket_values.values())
        if prev_total <= 0:
            period_returns_bps.append(0)
            wealth_path.append((_float_year_label(d), 0))
            prev_year = d.year
            continue
        bucket_values = {
            b: bucket_values[b] * (1.0 + float(ret_map.get(b, 0) or 0) / 10000.0)
            for b in BUCKETS
        }
        new_total = sum(bucket_values.values())
        period_returns_bps.append(int(round((new_total - prev_total) / prev_total * 10000)))
        wealth_path.append((_float_year_label(d), int(round(new_total))))
        prev_year = d.year

    return {
        "wealth_path_rappen": wealth_path,
        "annual_returns_bps": period_returns_bps,
    }


def compute_metrics_daily(
    wealth_path_rappen: list[tuple[float, int]],
    period_returns_bps: list[int],
    *,
    risk_free_bps: int = 80,
    periods_per_year: int = DAILY_PERIODS_PER_YEAR,
) -> dict:
    """Asset-Manager-Metriken für den täglichen Pfad.

    Output-Keys identisch zu compute_metrics. Unterschiede zur Annual-Variante:
    - CAGR aus echtem Datums-Span (float-Jahr-Differenz der Endpunkte).
    - Volatilität aus TAGES-Returns × √periods_per_year (Annualisierung).
    - Max-Drawdown über den vollen täglichen Pfad.
    - Best/Worst-JAHR + Win-Rate aus Year-End-Aggregation (Asset-Manager-Konvention).
    """
    empty = {
        "cagr_bps": 0, "vol_bps": 0, "sharpe_x100": 0, "max_drawdown_bps": 0,
        "best_year_bps": 0, "best_year_label": None, "worst_year_bps": 0,
        "worst_year_label": None, "win_rate_x100": 0, "total_return_bps": 0,
        "start_value_rappen": 0, "end_value_rappen": 0, "years_count": 0,
        "positive_years": 0, "negative_years": 0,
    }
    if not wealth_path_rappen or not period_returns_bps:
        return empty

    start_value = int(wealth_path_rappen[0][1])
    end_value = int(wealth_path_rappen[-1][1])
    span_years = float(wealth_path_rappen[-1][0]) - float(wealth_path_rappen[0][0])

    # CAGR aus Datums-Span
    if start_value > 0 and end_value > 0 and span_years > 0:
        cagr = (end_value / start_value) ** (1.0 / span_years) - 1.0
        cagr_bps = int(round(cagr * 10000))
    else:
        cagr_bps = 0

    # Annualisierte Volatilität aus Tages-Returns
    n = len(period_returns_bps)
    if n >= 2:
        mean = sum(period_returns_bps) / n
        var = sum((r - mean) ** 2 for r in period_returns_bps) / (n - 1)
        vol_bps = int(round(math.sqrt(var) * math.sqrt(periods_per_year)))
    else:
        vol_bps = 0

    sharpe_x100 = int(round((cagr_bps - int(risk_free_bps)) / vol_bps * 100)) if vol_bps > 0 else 0

    # Max-Drawdown über täglichen Pfad
    peak = 0
    max_dd = 0.0
    for _label, value in wealth_path_rappen:
        peak = max(peak, int(value))
        if peak > 0:
            max_dd = max(max_dd, (peak - int(value)) / peak)
    max_dd_bps = int(round(max_dd * 10000))

    # Year-End-Aggregation für Jahres-Returns
    year_end: dict[int, int] = {}
    for label, value in wealth_path_rappen:
        year_end[int(label)] = int(value)
    yearly: list[tuple[int, int]] = []  # (year, return_bps)
    prev_val = start_value
    for yr in sorted(year_end.keys()):
        ye = year_end[yr]
        if prev_val > 0:
            yearly.append((yr, int(round((ye - prev_val) / prev_val * 10000))))
        prev_val = ye

    if yearly:
        best = max(yearly, key=lambda t: t[1])
        worst = min(yearly, key=lambda t: t[1])
        positive = sum(1 for _y, r in yearly if r > 0)
        negative = sum(1 for _y, r in yearly if r < 0)
        years_count = len(yearly)
        win_rate_x100 = int(round(positive / years_count * 10000)) if years_count else 0
        best_year_bps, best_year_label = best[1], best[0]
        worst_year_bps, worst_year_label = worst[1], worst[0]
    else:
        positive = negative = years_count = win_rate_x100 = 0
        best_year_bps = worst_year_bps = 0
        best_year_label = worst_year_label = None

    total_return_bps = int(round((end_value - start_value) / start_value * 10000)) if start_value > 0 else 0

    return {
        "cagr_bps": cagr_bps,
        "vol_bps": vol_bps,
        "sharpe_x100": sharpe_x100,
        "max_drawdown_bps": max_dd_bps,
        "best_year_bps": best_year_bps,
        "best_year_label": best_year_label,
        "worst_year_bps": worst_year_bps,
        "worst_year_label": worst_year_label,
        "win_rate_x100": win_rate_x100,
        "total_return_bps": total_return_bps,
        "start_value_rappen": start_value,
        "end_value_rappen": end_value,
        "years_count": years_count,
        "positive_years": positive,
        "negative_years": negative,
    }


def compute_drawdown_path_float(wealth_path_rappen: list[tuple[float, int]]) -> list[dict]:
    """Drawdown-Pfad mit float-Jahr-Label (Daily). {"year": float, "drawdown_bps": int}."""
    out: list[dict] = []
    peak = 0
    for label, value in wealth_path_rappen:
        peak = max(peak, int(value))
        dd_bps = int(round((int(value) - peak) / peak * 10000)) if peak > 0 else 0
        out.append({"year": float(label), "drawdown_bps": dd_bps})
    return out


def _downsample_points(points: list, max_points: int, value_index_or_key) -> list:
    """Dünnt einen Pfad auf max_points aus; behält Start, Ende und globales
    Min/Max (Peak/Trough), damit Drawdown-Extreme im Chart erhalten bleiben.

    value_index_or_key: int (Tuple-Index) oder str (Dict-Key) für den Wert.
    """
    if len(points) <= max_points:
        return points

    def val(pt):
        return pt[value_index_or_key] if isinstance(value_index_or_key, int) else pt[value_index_or_key]

    n = len(points)
    keep_idx = {0, n - 1}
    keep_idx.add(max(range(n), key=lambda i: val(points[i])))
    keep_idx.add(min(range(n), key=lambda i: val(points[i])))
    # ceil-Division, damit das Sampling-Raster garantiert <= max_points Punkte
    # liefert (n//max_points kann 1 sein und nichts ausduennen).
    stride = max(2, -(-n // max_points))
    keep_idx.update(range(0, n, stride))
    return [points[i] for i in sorted(keep_idx)]


def _build_daily_path_views(
    initial_value_rappen: int,
    weights_bps: Mapping[str, int],
    anchor_date: Date,
    series: list[tuple[Date, Mapping[str, int]]],
    risk_free_bps: int,
) -> dict:
    """Rebal- + No-Rebal-Pfad für den Daily-Modus inkl. Metriken (Vollpfad)
    und downgesampelten Chart-Pfaden."""
    out = {"weights_bps": dict(weights_bps)}
    for key, rebal in (("rebalanced", True), ("no_rebalance", False)):
        path = compound_daily_path(initial_value_rappen, weights_bps, anchor_date, series, rebalance=rebal)
        full_wealth = path["wealth_path_rappen"]
        metrics = compute_metrics_daily(full_wealth, path["annual_returns_bps"], risk_free_bps=risk_free_bps)
        drawdown_full = compute_drawdown_path_float(full_wealth)
        out[key] = {
            "wealth_path_rappen": _downsample_points(full_wealth, MAX_PATH_POINTS, 1),
            "annual_returns_bps": path["annual_returns_bps"],
            "drawdown_path_bps": _downsample_points(drawdown_full, MAX_PATH_POINTS, "drawdown_bps"),
            "metrics": metrics,
        }
    return out


# ---------------------------------------------------------------------------
# Master-Service
# ---------------------------------------------------------------------------


def _soll_weights_bps_from_target_allocation(ta: TargetAllocation) -> dict[str, int]:
    return {
        "equities": int(getattr(ta, "target_equities_bps", 0) or 0),
        "bonds": int(getattr(ta, "target_bonds_bps", 0) or 0),
        "real_estate": int(getattr(ta, "target_real_estate_bps", 0) or 0),
        "alternatives": int(getattr(ta, "target_alternatives_bps", 0) or 0),
        "liquidity": int(getattr(ta, "target_liquidity_bps", 0) or 0),
    }


def _resolve_initial_value_rappen(db: Session, mandate: Mandate, ta: TargetAllocation) -> int:
    """Beratungsvermögen-Startwert für den Backtest.

    Bevorzugt advisory_wealth_at_generation_rappen aus der TA (Snapshot
    zum Strategie-Zeitpunkt). Fallback: aktuelle WealthPosition-Summe
    mit assignment='Beratungsvermögen'.
    """
    snapshot = int(getattr(ta, "advisory_wealth_at_generation_rappen", 0) or 0)
    if snapshot > 0:
        return snapshot
    client_id = getattr(mandate, "client_id", None)
    if not client_id:
        return 0
    rows = (
        db.query(WealthPosition)
        .filter(
            WealthPosition.client_id == client_id,
            WealthPosition.is_active == 1,
            WealthPosition.deleted_at.is_(None),
            WealthPosition.assignment == "Beratungsvermögen",
        )
        .all()
    )
    return sum(int(getattr(r, "current_value_rappen", 0) or 0) for r in rows)


def _resolve_risk_free_bps(db: Session, default_bps: int = 80) -> int:
    """Risk-free-Rate für Sharpe aus der aktuellen CMA (Geldmarkt-Rendite
    `liquidity_return_bps`). Fallback: konservative 80 bps, wenn keine CMA
    oder kein Wert gepflegt ist."""
    cma = (
        db.query(CapitalMarketAssumption)
        .filter(
            CapitalMarketAssumption.is_current == 1,
            CapitalMarketAssumption.deleted_at.is_(None),
        )
        .first()
    )
    if cma is not None:
        rf = getattr(cma, "liquidity_return_bps", None)
        if rf is not None and int(rf) >= 0:
            return int(rf)
    return default_bps


def _normalize_benchmark_weights(weights: Mapping[str, int] | None) -> dict[str, int] | None:
    """Konvertiert Benchmark-Mix in normalisierte Gewichte (Summe 10000).

    None wenn weights leer ist oder Summe 0. Rest-bps gehen auf liquidity.
    """
    if not weights:
        return None
    raw = {b: max(0, int(weights.get(b, 0) or 0)) for b in BUCKETS}
    total = sum(raw.values())
    if total <= 0:
        return None
    # Normalisieren auf 10000 (User-Input kann 9999 oder 10001 sein)
    scaled: dict[str, int] = {}
    allocated = 0
    for b in BUCKETS:
        share = raw[b] / total
        scaled[b] = int(round(share * 10000))
        allocated += scaled[b]
    # Korrekturbps auf liquidity, damit Summe exakt 10000
    scaled["liquidity"] += 10000 - allocated
    return scaled


def _build_path_views(
    initial_value_rappen: int,
    weights_bps: Mapping[str, int],
    years_data: list[tuple[int, Mapping[str, int]]],
    risk_free_bps: int,
) -> dict:
    """Erzeugt sowohl Rebal als auch No-Rebal Pfad + Metriken + Drawdown-Pfad."""
    rebal = compound_wealth_path(initial_value_rappen, weights_bps, years_data, rebalance=True)
    norebal = compound_wealth_path(initial_value_rappen, weights_bps, years_data, rebalance=False)
    return {
        "weights_bps": dict(weights_bps),
        "rebalanced": {
            "wealth_path_rappen": rebal["wealth_path_rappen"],
            "annual_returns_bps": rebal["annual_returns_bps"],
            "drawdown_path_bps": compute_drawdown_path_bps(rebal["wealth_path_rappen"]),
            "metrics": compute_metrics(rebal["wealth_path_rappen"], rebal["annual_returns_bps"], risk_free_bps=risk_free_bps),
        },
        "no_rebalance": {
            "wealth_path_rappen": norebal["wealth_path_rappen"],
            "annual_returns_bps": norebal["annual_returns_bps"],
            "drawdown_path_bps": compute_drawdown_path_bps(norebal["wealth_path_rappen"]),
            "metrics": compute_metrics(norebal["wealth_path_rappen"], norebal["annual_returns_bps"], risk_free_bps=risk_free_bps),
        },
    }


def run_strategy_backtest(
    db: Session,
    mandate: Mandate,
    *,
    start_year: int | None = None,
    end_year: int | None = None,
    benchmark_weights_bps: Mapping[str, int] | None = None,
    resolution: str = "annual",
) -> dict:
    """Master-Service: führt den SOLL-Strategie-Backtest für das Mandat aus.

    Liefert beide Varianten (mit / ohne Rebal) für SOLL und optional für
    einen Benchmark-Mix. Keine DB-Mutation. Falls keine TargetAllocation
    oder keine Annual-Returns vorhanden: leeres Ergebnis + Warning.

    resolution: "annual" (default, Jahresrenditen) oder "daily" (tägliche
        EOD-Serie aus asset_class_price_history). Fehlen tägliche Daten,
        fällt der Backtest automatisch auf "annual" zurück (resolution_used).
    """
    warnings: list[str] = []
    requested_resolution = "daily" if str(resolution).lower() == "daily" else "annual"

    ta = (
        db.query(TargetAllocation)
        .filter(
            TargetAllocation.mandate_id == mandate.id,
            TargetAllocation.is_current == 1,
            TargetAllocation.deleted_at.is_(None),
        )
        .first()
    )
    if ta is None:
        return {
            "mandate_id": str(mandate.id),
            "warnings": ["Keine aktive Target-Allocation gefunden — bitte erst Anlagestrategie berechnen."],
            "available_years": [],
            "soll": None,
            "benchmark": None,
            "resolution_used": "annual",
        }

    soll_weights = _soll_weights_bps_from_target_allocation(ta)
    if sum(soll_weights.values()) <= 0:
        return {
            "mandate_id": str(mandate.id),
            "warnings": ["SOLL-Strategie ist leer (alle Bucket-Gewichte 0)."],
            "available_years": [],
            "soll": None,
            "benchmark": None,
            "resolution_used": "annual",
        }

    initial_value = _resolve_initial_value_rappen(db, mandate, ta)
    if initial_value <= 0:
        # Backtest auf einem Standard-Initial-Kapital (100k CHF in Rappen),
        # damit relative Renditen zumindest sichtbar sind. Warning explizit.
        initial_value = 100_000_00
        warnings.append(
            "Beratungsvermögen-Startwert konnte nicht ermittelt werden — Backtest läuft auf "
            "Standard-Initial-Kapital von CHF 100'000 für indikative Darstellung."
        )

    # U-P19b: Risk-free für Sharpe aus aktueller CMA (Geldmarkt-Rendite), nicht fix.
    risk_free_bps = _resolve_risk_free_bps(db)

    # --- Daily-Modus (U-P19): persistierte tägliche Serie, sonst Fallback ---
    if requested_resolution == "daily":
        anchor, daily_series, fx_meta = load_daily_returns_series(db, start_year, end_year)
        if anchor is not None and daily_series:
            daily_years = sorted({anchor.year, *(d.year for d, _r in daily_series)})
            benchmark_norm = _normalize_benchmark_weights(benchmark_weights_bps)
            if fx_meta.get("unconverted"):
                warnings.append(
                    "Für folgende Notierungswährungen fehlen FX-Daten, sie wurden "
                    "näherungsweise als CHF behandelt: " + ", ".join(fx_meta["unconverted"])
                    + ". Bitte Tageskurs-Backfill erneut ausführen."
                )
            return {
                "mandate_id": str(mandate.id),
                "initial_value_rappen": initial_value,
                "soll_weights_bps": soll_weights,
                "available_years": daily_years,
                "start_year": daily_years[0],
                "end_year": daily_years[-1],
                "risk_free_bps": risk_free_bps,
                "soll": _build_daily_path_views(initial_value, soll_weights, anchor, daily_series, risk_free_bps),
                "benchmark": (
                    _build_daily_path_views(initial_value, benchmark_norm, anchor, daily_series, risk_free_bps)
                    if benchmark_norm is not None else None
                ),
                "warnings": warnings,
                "resolution_used": "daily",
                "fx_converted": fx_meta.get("converted", {}),
                "note": (
                    "Daily-Auflösung — tägliche EOD-Serie je Asset-Klasse aus "
                    "asset_class_price_history. Compounding täglich, Rebalancing jährlich. "
                    "Renditen währungskorrekt nach CHF umgerechnet (asset_class_fx_history)."
                ),
            }
        warnings.append(
            "Keine ausreichenden täglichen Kursdaten gepflegt — Backtest fällt auf jährliche "
            "Auflösung zurück (Admin > Asset-Class-Prices befüllen)."
        )

    matrix = load_annual_returns_matrix(db)
    available_years_all = sorted(matrix.keys())
    if not available_years_all:
        return {
            "mandate_id": str(mandate.id),
            "warnings": warnings + [
                "Keine vollständigen Jahresrenditen gepflegt — bitte Admin > Annual-Returns ausfüllen."
            ],
            "available_years": [],
            "soll": None,
            "benchmark": None,
            "resolution_used": "annual",
        }

    years_in_range = _years_in_range(matrix, start_year, end_year)
    if not years_in_range:
        return {
            "mandate_id": str(mandate.id),
            "warnings": warnings + [
                "Im gewählten Zeitraum sind keine vollständigen Jahresrenditen verfügbar."
            ],
            "available_years": available_years_all,
            "soll": None,
            "benchmark": None,
            "resolution_used": "annual",
        }

    years_data: list[tuple[int, dict[str, int]]] = [(y, matrix[y]) for y in years_in_range]

    soll_view = _build_path_views(initial_value, soll_weights, years_data, risk_free_bps)

    benchmark_view = None
    benchmark_norm = _normalize_benchmark_weights(benchmark_weights_bps)
    if benchmark_norm is not None:
        benchmark_view = _build_path_views(initial_value, benchmark_norm, years_data, risk_free_bps)

    return {
        "mandate_id": str(mandate.id),
        "initial_value_rappen": initial_value,
        "soll_weights_bps": soll_weights,
        "available_years": available_years_all,
        "start_year": years_in_range[0],
        "end_year": years_in_range[-1],
        "risk_free_bps": risk_free_bps,
        "soll": soll_view,
        "benchmark": benchmark_view,
        "warnings": warnings,
        "resolution_used": "annual",
        "note": (
            "Jahres-Auflösung — historische Jahresrenditen pro Asset-Klasse aus "
            "admin/system/annual-returns. Für tägliche Auflösung (Intra-Jahr-Drawdown) "
            "asset_class_price_history befüllen und resolution=daily wählen."
        ),
    }
