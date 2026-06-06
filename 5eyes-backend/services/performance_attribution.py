"""Sprint U-97 (2026-06-06): Brinson-Performance-Attribution.

Pure-Math-Modul ohne DB-/Modell-Abhaengigkeiten. Zerlegt die Excess-
Rendite eines Portfolios vs eines Benchmarks in 3 Effekte
(Brinson/Fachler/Hood 1986):

  - **Allocation Effect**: (w_P - w_B) * r_B
    Wirkung der Asset-Allocation-Tilts (Berater-Entscheidung
    'mehr/weniger Aktien als Benchmark')
  - **Selection Effect**: w_B * (r_P - r_B)
    Wirkung der Produkt-Auswahl innerhalb der Bucket
    (in 5eyes meist 0, da forward-looking CMA-Returns gleich)
  - **Interaction Effect**: (w_P - w_B) * (r_P - r_B)
    Restterm, oft klein wenn Selection klein ist

  Total Excess = Allocation + Selection + Interaction

Konventionen:
  - Inputs/Outputs in bps (1 bp = 0.01%)
  - Gewichte muessen NICHT zu 10000 bps summieren — wir normalisieren
    nicht, weil das die Berater-Sichtbarkeit (z.B. Cash-Differenz)
    verschleiern wuerde
  - Bei nicht-berechenbaren Faellen (leere Inputs) -> alle Effekte 0

Anwendung in 5eyes:
  - Portfolio = aktuelle TargetAllocation-Weights des Mandats
  - Benchmark = House-Matrix-Default fuer das Risikoprofil
  - Returns = CMA-Erwartungen pro Bucket (gleich fuer P+B, weil
    forward-looking)
  -> Selection und Interaction sind dann ~0, Allocation Effect zeigt
     den Wert der SAA-Tilts
"""
from __future__ import annotations

from dataclasses import dataclass


BUCKET_KEYS: tuple[str, ...] = (
    "equities",
    "bonds",
    "real_estate",
    "alternatives",
    "liquidity",
)


@dataclass(frozen=True)
class BucketAttribution:
    """Brinson-Effekte pro Bucket."""

    bucket: str
    weight_portfolio_bps: int
    weight_benchmark_bps: int
    return_portfolio_bps: int
    return_benchmark_bps: int
    allocation_effect_bps: int
    selection_effect_bps: int
    interaction_effect_bps: int

    def to_dict(self) -> dict:
        return {
            "bucket": self.bucket,
            "weight_portfolio_bps": self.weight_portfolio_bps,
            "weight_benchmark_bps": self.weight_benchmark_bps,
            "return_portfolio_bps": self.return_portfolio_bps,
            "return_benchmark_bps": self.return_benchmark_bps,
            "allocation_effect_bps": self.allocation_effect_bps,
            "selection_effect_bps": self.selection_effect_bps,
            "interaction_effect_bps": self.interaction_effect_bps,
        }


@dataclass(frozen=True)
class AttributionResult:
    """Konsolidiertes Ergebnis ueber alle Buckets + Totals."""

    buckets: tuple[BucketAttribution, ...]
    total_portfolio_return_bps: int
    total_benchmark_return_bps: int
    total_excess_return_bps: int
    total_allocation_effect_bps: int
    total_selection_effect_bps: int
    total_interaction_effect_bps: int

    def to_dict(self) -> dict:
        return {
            "buckets": [b.to_dict() for b in self.buckets],
            "total_portfolio_return_bps": self.total_portfolio_return_bps,
            "total_benchmark_return_bps": self.total_benchmark_return_bps,
            "total_excess_return_bps": self.total_excess_return_bps,
            "total_allocation_effect_bps": self.total_allocation_effect_bps,
            "total_selection_effect_bps": self.total_selection_effect_bps,
            "total_interaction_effect_bps": self.total_interaction_effect_bps,
        }


def _weighted_total_bps(weights_bps: dict[str, int], returns_bps: dict[str, int]) -> int:
    """Berechnet Σ w_i * r_i / 10000 (bps-konsistent).

    Beide Inputs in bps. Output in bps. Beispiel:
        w=5000 (50%), r=600 (6%) -> Beitrag = 5000*600/10000 = 300 bps (3%)
    """
    total = 0
    for key, w in weights_bps.items():
        if w is None:
            continue
        r = int(returns_bps.get(key, 0) or 0)
        total += int(w) * r
    return total // 10000


def compute_brinson_attribution(
    *,
    portfolio_weights_bps: dict[str, int],
    benchmark_weights_bps: dict[str, int],
    portfolio_returns_bps: dict[str, int],
    benchmark_returns_bps: dict[str, int] | None = None,
    bucket_keys: tuple[str, ...] = BUCKET_KEYS,
) -> AttributionResult:
    """Berechnet Brinson-Attribution mit 3 Effekten pro Bucket.

    Args:
        portfolio_weights_bps: aktuelle TA-Weights pro Bucket
        benchmark_weights_bps: Benchmark-Weights (House-Matrix-Default)
        portfolio_returns_bps: erwartete Returns pro Bucket im Portfolio
        benchmark_returns_bps: erwartete Returns im Benchmark.
            Default: gleich wie portfolio_returns_bps (forward-looking-Default
            in 5eyes — keine Selection-Differenz, nur Allocation).
        bucket_keys: zu betrachtende Buckets (Default 5 SAA-Buckets)

    Returns:
        AttributionResult mit per-Bucket-Aufschluesselung + Totals.
    """
    bench_returns = (
        benchmark_returns_bps if benchmark_returns_bps is not None
        else dict(portfolio_returns_bps)
    )

    buckets_out: list[BucketAttribution] = []
    total_alloc = 0
    total_select = 0
    total_inter = 0

    for key in bucket_keys:
        w_p = int(portfolio_weights_bps.get(key, 0) or 0)
        w_b = int(benchmark_weights_bps.get(key, 0) or 0)
        r_p = int(portfolio_returns_bps.get(key, 0) or 0)
        r_b = int(bench_returns.get(key, 0) or 0)

        # Brinson-Formeln, jeweils /10000 da Multiplikation zweier bps-Werte
        alloc = (w_p - w_b) * r_b // 10000
        select = w_b * (r_p - r_b) // 10000
        inter = (w_p - w_b) * (r_p - r_b) // 10000

        buckets_out.append(BucketAttribution(
            bucket=key,
            weight_portfolio_bps=w_p,
            weight_benchmark_bps=w_b,
            return_portfolio_bps=r_p,
            return_benchmark_bps=r_b,
            allocation_effect_bps=int(alloc),
            selection_effect_bps=int(select),
            interaction_effect_bps=int(inter),
        ))
        total_alloc += int(alloc)
        total_select += int(select)
        total_inter += int(inter)

    total_p = _weighted_total_bps(portfolio_weights_bps, portfolio_returns_bps)
    total_b = _weighted_total_bps(benchmark_weights_bps, bench_returns)
    total_excess = total_p - total_b

    return AttributionResult(
        buckets=tuple(buckets_out),
        total_portfolio_return_bps=total_p,
        total_benchmark_return_bps=total_b,
        total_excess_return_bps=total_excess,
        total_allocation_effect_bps=total_alloc,
        total_selection_effect_bps=total_select,
        total_interaction_effect_bps=total_inter,
    )
