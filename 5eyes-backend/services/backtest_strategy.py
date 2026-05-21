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
from typing import Iterable, Mapping

from sqlalchemy.orm import Session

from models.allocation import TargetAllocation
from models.mandates import Mandate
from models.snapshots import AssetClassAnnualReturn
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
) -> dict:
    """Master-Service: führt den SOLL-Strategie-Backtest für das Mandat aus.

    Liefert beide Varianten (mit / ohne Rebal) für SOLL und optional für
    einen Benchmark-Mix. Keine DB-Mutation. Falls keine TargetAllocation
    oder keine Annual-Returns vorhanden: leeres Ergebnis + Warning.
    """
    warnings: list[str] = []

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
        }

    soll_weights = _soll_weights_bps_from_target_allocation(ta)
    if sum(soll_weights.values()) <= 0:
        return {
            "mandate_id": str(mandate.id),
            "warnings": ["SOLL-Strategie ist leer (alle Bucket-Gewichte 0)."],
            "available_years": [],
            "soll": None,
            "benchmark": None,
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
        }

    years_data: list[tuple[int, dict[str, int]]] = [(y, matrix[y]) for y in years_in_range]
    risk_free_bps = 80  # konservative CHF-Geldmarkt-Annahme; aktuelle CMA wird nicht herangezogen

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
        "note": (
            "Annual-MVP — historische Jahresrenditen pro Asset-Klasse aus admin/system/annual-returns. "
            "Daily-Auflösung pro Sub-Asset-Class kommt mit U-P11 (Marktdaten-Pipeline)."
        ),
    }
