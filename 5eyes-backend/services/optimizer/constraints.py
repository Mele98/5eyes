"""Constraints fuer den Optimizer.

Master-Spec: docs/planning/2026-05-05-stochastic-optimizer-spec.md (Sec 7)

8 Constraints (verbindliche Regeln):
1. Sum-to-One: Σ w_i = 1.0  (equality)
2. Risky-Fraction-Cap: Σ w_i · rf_i ≤ score_x10 / 10
3. House-Matrix-Bands: min_b ≤ w_b ≤ max_b  (box bounds)
4. Real-Estate-Cap: w_real_estate ≤ 0.20
5. Alts-Cap: w_alternatives ≤ 0.10
6. Liquidity-Floor: w_liquidity ≥ 0.02
7. Non-Negativity: w_i ≥ 0  (impliziert durch Bands wenn min_b ≥ 0)
8. (Bei Optimizer-Run: Reproduzierbarkeit via Seed - wird im Solver-Layer
   gehandelt, nicht hier)

Ausgabe-Format ist scipy.optimize.minimize-kompatibel:
- bounds: list of (min, max) tuples
- constraints: list of dicts {'type': 'eq'|'ineq', 'fun': callable}

Inequality-Convention (scipy):
  'ineq': fun(w) ≥ 0 ist feasible
  'eq':   fun(w) == 0 ist feasible
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .scenario_engine import BUCKET_ORDER, N_BUCKETS


# Mapping von BuildingBlock.asset_class (deutscher String) auf BUCKET_ORDER.
# Konsistent zur Logik in services.portfolio_engine._build_sub_allocations.
_ASSET_CLASS_TO_BUCKET = {
    "aktien": "equities",
    "obligationen": "bonds",
    "immobilien": "real_estate",
    "alternative": "alternatives",
    "alternativen": "alternatives",
    "liquiditaet": "liquidity",
    "liquidität": "liquidity",
    "liquidity": "liquidity",
}


# Risky-Fraction Defaults pro Bucket (3eyes-Slide 17, OWNER-DECISION OD-6
# bestaetigt). Diese sind Bucket-aggregierte Mittelwerte aus den Sub-Asset-
# Class Werten. Wenn der Caller spezifischere Werte aus BuildingBlock-Tabelle
# hat, kann er DEFAULT_BUCKET_RISKY_FRACTION ueberschreiben.
DEFAULT_BUCKET_RISKY_FRACTION = {
    "equities": 0.80,       # Mix CH-Large 70%, CH-SM 80%, World 80%, EM 100%
    "bonds": 0.25,          # Mix CH-IG 20%, Global Hedged 25%, HY 50%, EM 40%
    "real_estate": 0.60,    # Mix CH 50%, World 70%
    "alternatives": 0.60,   # Mix Gold 80%, Liquid Alts 40%, Hedge 60%
    "liquidity": 0.00,
}

# Globale Caps (3eyes-Slide 17, OWNER-DECISION OD-6)
MAX_REAL_ESTATE = 0.20
MAX_ALTERNATIVES = 0.10
MIN_LIQUIDITY = 0.02


@dataclass(frozen=True)
class HouseMatrixBands:
    """Bandbreiten pro Bucket aus aktiver House-Matrix-Zeile.

    Werte sind Anteile (0..1), nicht bps. Reihenfolge konsistent zu BUCKET_ORDER.
    """
    equities: tuple[float, float]
    bonds: tuple[float, float]
    real_estate: tuple[float, float]
    alternatives: tuple[float, float]
    liquidity: tuple[float, float]

    def to_bounds_list(self) -> list[tuple[float, float]]:
        """Bounds in der Reihenfolge BUCKET_ORDER fuer scipy.minimize."""
        return [
            self.equities,
            self.bonds,
            self.real_estate,
            self.alternatives,
            self.liquidity,
        ]


def bands_from_house_matrix_row(row) -> HouseMatrixBands:
    """Extrahiert HouseMatrixBands aus einer HouseMatrix-Zeile (oder Mock).

    Erwartet Felder *_min_bps, *_max_bps wie in models.allocation.HouseMatrix.
    """
    def _band(min_attr: str, max_attr: str) -> tuple[float, float]:
        lo = int(getattr(row, min_attr, 0) or 0) / 10000.0
        hi = int(getattr(row, max_attr, 10000) or 0) / 10000.0
        return (lo, hi)

    return HouseMatrixBands(
        equities=_band("equity_min_bps", "equity_max_bps"),
        bonds=_band("bonds_min_bps", "bonds_max_bps"),
        real_estate=_band("real_estate_min_bps", "real_estate_max_bps"),
        alternatives=_band("alt_min_bps", "alt_max_bps"),
        liquidity=_band("liq_min_bps", "liq_max_bps"),
    )


def build_bounds(bands: HouseMatrixBands) -> list[tuple[float, float]]:
    """House-Matrix-Bands + globale Caps. Liquidity-Floor und globale Caps
    werden direkt in die Bounds eingebaut, sodass der Solver sie automatisch
    respektiert.
    """
    base = bands.to_bounds_list()
    # Indices in BUCKET_ORDER: equities=0, bonds=1, real_estate=2, alternatives=3, liquidity=4
    re_idx = BUCKET_ORDER.index("real_estate")
    alt_idx = BUCKET_ORDER.index("alternatives")
    liq_idx = BUCKET_ORDER.index("liquidity")
    out = list(base)
    # RE-Cap
    re_lo, re_hi = out[re_idx]
    out[re_idx] = (re_lo, min(re_hi, MAX_REAL_ESTATE))
    # Alts-Cap
    alt_lo, alt_hi = out[alt_idx]
    out[alt_idx] = (alt_lo, min(alt_hi, MAX_ALTERNATIVES))
    # Liquidity-Floor
    liq_lo, liq_hi = out[liq_idx]
    out[liq_idx] = (max(liq_lo, MIN_LIQUIDITY), liq_hi)
    # Sicherheits-Sanity: lo darf nicht > hi sein (kann passieren wenn
    # House-Matrix komische Werte hat - dann kollabieren wir auf den Wert)
    out = [(min(lo, hi), hi) for (lo, hi) in out]
    return out


def build_sum_to_one_constraint() -> dict:
    """Equality-Constraint: Σ w_i = 1.0"""
    return {
        "type": "eq",
        "fun": lambda w: float(np.sum(w) - 1.0),
        "jac": lambda w: np.ones(N_BUCKETS),
    }


def build_risky_fraction_constraint(
    score_x10: int,
    risky_fraction_per_bucket: dict[str, float] | None = None,
) -> dict:
    """Inequality: score_x10/10 - Σ w_i · rf_i ≥ 0

    score_x10: 0..100 (Score×10). 70 -> max 70% risky.
    risky_fraction_per_bucket: optional override; default DEFAULT_BUCKET_RISKY_FRACTION
    """
    rf_map = risky_fraction_per_bucket or DEFAULT_BUCKET_RISKY_FRACTION
    rf_array = np.array([rf_map.get(b, 0.0) for b in BUCKET_ORDER], dtype=np.float64)
    cap = max(0.0, min(1.0, float(score_x10) / 100.0))
    return {
        "type": "ineq",
        "fun": lambda w: float(cap - float(np.dot(w, rf_array))),
        "jac": lambda w: -rf_array.copy(),
    }


def build_constraint_set(
    bands: HouseMatrixBands,
    score_x10: int,
    risky_fraction_per_bucket: dict[str, float] | None = None,
) -> tuple[list[tuple[float, float]], list[dict]]:
    """Komplettes scipy-kompatibles Constraint-Set.

    Returns:
        bounds: list of (lo, hi) per bucket in BUCKET_ORDER
        constraints: list of dicts (sum-to-one + risky-fraction)
    """
    bounds = build_bounds(bands)
    constraints = [
        build_sum_to_one_constraint(),
        build_risky_fraction_constraint(score_x10, risky_fraction_per_bucket),
    ]
    return bounds, constraints


def bucket_risky_fractions_from_building_blocks(
    building_block_rows: list,
) -> dict[str, float]:
    """Aggregiert pro Bucket den Mittelwert der Risky-Fractions aller aktiven
    BuildingBlock-Sub-Klassen.

    building_block_rows: Liste von BuildingBlock-Modell-Instanzen oder Mocks
        mit Attributen .asset_class (str) und .risky_fraction_bps (int).

    Wenn ein Bucket keine BuildingBlocks hat (z.B. Defaultsystem ohne Liquid
    Alternatives-Eintraege), wird auf DEFAULT_BUCKET_RISKY_FRACTION zurueckgefallen.

    Konsistent zu 3eyes-Slide 17: Pro Sub-Asset-Class ist eine eigene Risky-
    Fraction definiert. Das Bucket-Aggregat ist der Mittelwert dieser Werte
    (vereinfacht; eine sub-allocation-aware Gewichtung wuerde den User-Tilt
    beruecksichtigen, ist aber zweite-Ordnungs-Effekt fuer Phase 5.1).
    """
    by_bucket: dict[str, list[float]] = {b: [] for b in BUCKET_ORDER}
    for row in building_block_rows:
        ac_norm = str(getattr(row, "asset_class", "") or "").strip().lower()
        bucket = _ASSET_CLASS_TO_BUCKET.get(ac_norm)
        if bucket is None:
            continue
        rf = getattr(row, "risky_fraction_bps", None)
        if rf is None:
            continue
        by_bucket[bucket].append(int(rf) / 10000.0)

    out = {}
    for bucket in BUCKET_ORDER:
        vals = by_bucket[bucket]
        if vals:
            out[bucket] = float(sum(vals) / len(vals))
        else:
            out[bucket] = DEFAULT_BUCKET_RISKY_FRACTION[bucket]
    return out


def is_feasible(
    weights: np.ndarray,
    *,
    bounds: list[tuple[float, float]],
    constraints: list[dict],
    tolerance: float = 1e-6,
) -> tuple[bool, list[str]]:
    """Prueft ob weights alle Constraints erfuellen.

    Liefert (feasible, reasons). reasons ist Liste verletzter Constraints.
    """
    reasons = []
    weights = np.asarray(weights, dtype=np.float64)

    # Bounds
    for i, (lo, hi) in enumerate(bounds):
        if weights[i] < lo - tolerance:
            reasons.append(f"{BUCKET_ORDER[i]} below min {lo:.4f} (got {weights[i]:.4f})")
        if weights[i] > hi + tolerance:
            reasons.append(f"{BUCKET_ORDER[i]} above max {hi:.4f} (got {weights[i]:.4f})")

    # Sum-to-one (eq)
    s = float(np.sum(weights))
    if abs(s - 1.0) > tolerance:
        reasons.append(f"sum-to-one violated (sum={s:.6f})")

    # Inequality constraints
    for cons in constraints:
        if cons["type"] != "ineq":
            continue
        val = cons["fun"](weights)
        if val < -tolerance:
            reasons.append(f"ineq constraint violated (value={val:.6f})")

    return (len(reasons) == 0, reasons)
