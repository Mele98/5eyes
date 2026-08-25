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

from collections.abc import Mapping
from dataclasses import dataclass
from numbers import Integral, Real

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


# Risky-Fraction Defaults pro Bucket (Advisory-Methodik-Slide 17, OWNER-DECISION OD-6
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

# Globale Caps (Advisory-Methodik-Slide 17, OWNER-DECISION OD-6)
MAX_REAL_ESTATE = 0.20
MAX_ALTERNATIVES = 0.10
MIN_LIQUIDITY = 0.02


class OptimizerInputError(ValueError):
    """Hard optimizer input/domain error that must not become a silent fallback."""


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
        # OPT-2: fehlenden/None-Wert vom EXPLIZITEN Wert unterscheiden. Vorher kippte
        # `int(getattr(..., 10000) or 0)` eine vorhandene None-Obergrenze (oder den
        # via `or` falsch behandelten Fall) auf 0 -> die Anlageklasse wäre im Solver
        # auf ~0 gezwungen. Jetzt: fehlend -> Default (min=0 kein Floor, max=10000
        # keine Cap); ein EXPLIZITES 0 bleibt 0 (legitime "diese Klasse nicht halten").
        raw_lo = getattr(row, min_attr, None)
        raw_hi = getattr(row, max_attr, None)
        lo = (int(raw_lo) if raw_lo is not None else 0) / 10000.0
        hi = (int(raw_hi) if raw_hi is not None else 10000) / 10000.0
        return (lo, hi)

    equities_lo, equities_hi = _band("equity_min_bps", "equity_max_bps")
    # 2026-07-24 (Formel-Audit): der deterministische Pfad rechnet die
    # Aktien-Untergrenze aus max(equity_min_bps, equity_minimum_bps) ein
    # (portfolio_engine.py, minimums["equities"] = max(equity_min_bps,
    # equity_minimum_bps or 0) -- z.B. eine haertere, ziel-/goal-getriebene
    # Mindestquote). Der Optimizer-Constraint-Aufbau hier nutzte bisher NUR
    # equity_min_bps -- bei einer House-Matrix-Konfiguration mit
    # equity_minimum_bps > equity_min_bps wuerde der Solver eine niedrigere
    # Aktienquote zulassen als der deterministische Pfad vorsieht (aktuell
    # mit den geladenen House-Matrix-Defaults nie der Fall, da equity_minimum_
    # bps dort nie ueber equity_min_bps liegt -- aber ein latenter Bug bei
    # zukuenftigen Profil-Edits). Fix spiegelt exakt dieselbe max()-Formel.
    equity_minimum_bps = getattr(row, "equity_minimum_bps", None)
    if equity_minimum_bps is not None:
        equities_lo = max(equities_lo, int(equity_minimum_bps) / 10000.0)

    return HouseMatrixBands(
        equities=(equities_lo, equities_hi),
        bonds=_band("bonds_min_bps", "bonds_max_bps"),
        real_estate=_band("real_estate_min_bps", "real_estate_max_bps"),
        alternatives=_band("alt_min_bps", "alt_max_bps"),
        liquidity=_band("liq_min_bps", "liq_max_bps"),
    )


def bands_from_effective_bounds_bps(
    effective_bounds_bps: Mapping[str, tuple[int, int]],
) -> HouseMatrixBands:
    """Build strict solver bands from the caller's effective mandate bounds.

    This is deliberately stricter than :func:`bands_from_house_matrix_row`.
    The legacy House-Matrix path remains fail-soft for backwards compatibility,
    while an explicitly supplied mandate constraint set must never be repaired
    silently. Values are integer basis points and every optimizer bucket must be
    present exactly once.

    ``effective`` means final: the caller must already have applied the global
    real-estate/alternatives caps and liquidity floor.  This function never
    rewrites an explicit mandate bound.  Any deviation from those immutable
    guardrails, or a box that cannot sum to 100%, raises
    ``OptimizerInputError`` before scenario generation.
    """
    if not isinstance(effective_bounds_bps, Mapping):
        raise OptimizerInputError(
            "effective_bounds_bps must be a mapping of bucket -> (min_bps, max_bps)."
        )

    expected = set(BUCKET_ORDER)
    actual = set(effective_bounds_bps.keys())
    missing = sorted(expected - actual)
    extra = sorted(actual - expected, key=str)
    if missing or extra:
        details = []
        if missing:
            details.append(f"missing={missing}")
        if extra:
            details.append(f"unknown={extra}")
        raise OptimizerInputError(
            "effective_bounds_bps must contain exactly the optimizer buckets ("
            + ", ".join(details)
            + ")."
        )

    parsed: dict[str, tuple[int, int]] = {}
    for bucket in BUCKET_ORDER:
        pair = effective_bounds_bps[bucket]
        if not isinstance(pair, (tuple, list)) or len(pair) != 2:
            raise OptimizerInputError(
                f"effective_bounds_bps[{bucket!r}] must be a (min_bps, max_bps) pair."
            )
        raw_lo, raw_hi = pair
        if (
            isinstance(raw_lo, bool)
            or isinstance(raw_hi, bool)
            or not isinstance(raw_lo, Integral)
            or not isinstance(raw_hi, Integral)
        ):
            raise OptimizerInputError(
                f"effective_bounds_bps[{bucket!r}] values must be integer basis points."
            )
        lo = int(raw_lo)
        hi = int(raw_hi)
        if not (0 <= lo <= 10000) or not (0 <= hi <= 10000):
            raise OptimizerInputError(
                f"effective_bounds_bps[{bucket!r}] must stay within 0..10000 bps "
                f"(got {lo}..{hi})."
            )
        if lo > hi:
            raise OptimizerInputError(
                f"effective_bounds_bps[{bucket!r}] has min_bps > max_bps "
                f"({lo} > {hi})."
            )
        parsed[bucket] = (lo, hi)

    # Explicit effective bounds are already the final domain contract.  The
    # legacy House-Matrix path may still clamp in build_bounds(), but doing the
    # same here would make the solver optimise different bounds than the caller
    # supplied and audited.
    re_lo, re_hi = parsed["real_estate"]
    global_re_cap_bps = int(round(MAX_REAL_ESTATE * 10000))
    if re_hi > global_re_cap_bps:
        raise OptimizerInputError(
            "effective real_estate maximum exceeds the global cap "
            f"({re_hi} > {global_re_cap_bps} bps)."
        )

    alt_lo, alt_hi = parsed["alternatives"]
    global_alt_cap_bps = int(round(MAX_ALTERNATIVES * 10000))
    if alt_hi > global_alt_cap_bps:
        raise OptimizerInputError(
            "effective alternatives maximum exceeds the global cap "
            f"({alt_hi} > {global_alt_cap_bps} bps)."
        )

    liq_lo, liq_hi = parsed["liquidity"]
    global_liq_floor_bps = int(round(MIN_LIQUIDITY * 10000))
    if liq_lo < global_liq_floor_bps:
        raise OptimizerInputError(
            "effective liquidity minimum is below the global floor "
            f"({liq_lo} < {global_liq_floor_bps} bps)."
        )

    minimum_sum = sum(lo for lo, _hi in parsed.values())
    maximum_sum = sum(hi for _lo, hi in parsed.values())
    if minimum_sum > 10000 or maximum_sum < 10000:
        raise OptimizerInputError(
            "effective_bounds_bps cannot satisfy sum-to-10000 "
            f"(sum(min)={minimum_sum}, sum(max)={maximum_sum})."
        )

    def _fraction_pair(bucket: str) -> tuple[float, float]:
        lo, hi = parsed[bucket]
        return (lo / 10000.0, hi / 10000.0)

    return HouseMatrixBands(
        equities=_fraction_pair("equities"),
        bonds=_fraction_pair("bonds"),
        real_estate=_fraction_pair("real_estate"),
        alternatives=_fraction_pair("alternatives"),
        liquidity=_fraction_pair("liquidity"),
    )


def validate_risky_fraction_per_bucket(
    risky_fraction_per_bucket: Mapping[str, float],
) -> dict[str, float]:
    """Validate and own an exact risky-fraction map.

    A supplied map is a hard model input, not a sparse override.  Every
    optimizer bucket must be represented by one finite fraction in ``[0, 1]``;
    otherwise a missing/NaN value could silently weaken the mandate risk cap.
    """
    if not isinstance(risky_fraction_per_bucket, Mapping):
        raise OptimizerInputError(
            "risky_fraction_per_bucket must be a mapping of bucket -> fraction."
        )

    expected = set(BUCKET_ORDER)
    actual = set(risky_fraction_per_bucket.keys())
    missing = sorted(expected - actual)
    extra = sorted(actual - expected, key=str)
    if missing or extra:
        details = []
        if missing:
            details.append(f"missing={missing}")
        if extra:
            details.append(f"unknown={extra}")
        raise OptimizerInputError(
            "risky_fraction_per_bucket must contain exactly the optimizer buckets ("
            + ", ".join(details)
            + ")."
        )

    validated: dict[str, float] = {}
    for bucket in BUCKET_ORDER:
        raw = risky_fraction_per_bucket[bucket]
        if isinstance(raw, bool) or not isinstance(raw, Real):
            raise OptimizerInputError(
                f"risky_fraction_per_bucket[{bucket!r}] must be numeric."
            )
        value = float(raw)
        if not np.isfinite(value):
            raise OptimizerInputError(
                f"risky_fraction_per_bucket[{bucket!r}] must be finite."
            )
        if not 0.0 <= value <= 1.0:
            raise OptimizerInputError(
                f"risky_fraction_per_bucket[{bucket!r}] must be within 0..1 "
                f"(got {value})."
            )
        validated[bucket] = value
    return validated


def _validated_risky_cap_fraction(
    score_x10: int,
    max_risky_fraction_bps: int | None,
) -> float:
    if max_risky_fraction_bps is not None:
        if (
            isinstance(max_risky_fraction_bps, bool)
            or not isinstance(max_risky_fraction_bps, Integral)
        ):
            raise OptimizerInputError(
                "max_risky_fraction_bps must be integer basis points."
            )
        cap_bps = int(max_risky_fraction_bps)
        if not 0 <= cap_bps <= 10000:
            raise OptimizerInputError(
                "max_risky_fraction_bps must stay within 0..10000 bps."
            )
        return cap_bps / 10000.0

    if isinstance(score_x10, bool) or not isinstance(score_x10, Real):
        raise OptimizerInputError("score_x10 must be numeric within 0..100.")
    score = float(score_x10)
    if not np.isfinite(score) or not 0.0 <= score <= 100.0:
        raise OptimizerInputError("score_x10 must be finite and within 0..100.")
    return score / 100.0


def minimum_achievable_risky_fraction(
    bounds: list[tuple[float, float]],
    risky_fraction_per_bucket: Mapping[str, float],
) -> float:
    """Analytic minimum of ``sum(w_i * rf_i)`` under box + sum-to-one.

    Start at every lower bound, then assign the remaining weight greedily to
    buckets ordered by increasing risky fraction.  The objective is linear, so
    this is the exact box-constrained simplex optimum (fractional knapsack).
    """
    if len(bounds) != N_BUCKETS:
        raise OptimizerInputError(
            f"bounds must contain exactly {N_BUCKETS} optimizer buckets."
        )
    rf_map = validate_risky_fraction_per_bucket(risky_fraction_per_bucket)
    lows = np.array([float(pair[0]) for pair in bounds], dtype=np.float64)
    highs = np.array([float(pair[1]) for pair in bounds], dtype=np.float64)
    if (
        not np.all(np.isfinite(lows))
        or not np.all(np.isfinite(highs))
        or np.any(lows < 0.0)
        or np.any(highs > 1.0)
        or np.any(lows > highs)
    ):
        raise OptimizerInputError("bounds contain an invalid or non-finite interval.")

    remaining = 1.0 - float(np.sum(lows))
    if remaining < -1e-12 or float(np.sum(highs)) < 1.0 - 1e-12:
        raise OptimizerInputError(
            "optimizer bounds cannot satisfy the sum-to-one constraint."
        )

    weights = lows.copy()
    rf = np.array([rf_map[bucket] for bucket in BUCKET_ORDER], dtype=np.float64)
    for idx in sorted(range(N_BUCKETS), key=lambda item: (rf[item], item)):
        if remaining <= 1e-12:
            break
        addition = min(remaining, float(highs[idx] - weights[idx]))
        if addition > 0.0:
            weights[idx] += addition
            remaining -= addition
    if remaining > 1e-10:
        raise OptimizerInputError(
            "optimizer bounds cannot satisfy the sum-to-one constraint."
        )
    return float(np.dot(weights, rf))


def validate_risky_constraint_feasibility(
    *,
    bounds: list[tuple[float, float]],
    score_x10: int,
    risky_fraction_per_bucket: Mapping[str, float] | None,
    max_risky_fraction_bps: int | None,
) -> None:
    """Reject a structurally impossible risk cap before scenario generation."""
    rf_map = (
        dict(DEFAULT_BUCKET_RISKY_FRACTION)
        if risky_fraction_per_bucket is None
        else validate_risky_fraction_per_bucket(risky_fraction_per_bucket)
    )
    cap = _validated_risky_cap_fraction(score_x10, max_risky_fraction_bps)
    minimum = minimum_achievable_risky_fraction(bounds, rf_map)
    if minimum > cap + 1e-12:
        raise OptimizerInputError(
            "risky-fraction cap is infeasible under the effective bounds "
            f"(minimum achievable={minimum * 10000:.2f} bps, "
            f"cap={cap * 10000:.2f} bps)."
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


def bounds_collapse_warnings(bands: HouseMatrixBands) -> list[str]:
    """Erkennt House-Matrix-Bandbreiten, die von build_bounds() wegen eines
    globalen Caps/Floors auf einen einzelnen Punkt zusammengepresst wuerden.

    Bugfix 2026-08-07 (CEO/CFO/CIO-Audit): build_bounds() wendet MAX_REAL_ESTATE/
    MAX_ALTERNATIVES/MIN_LIQUIDITY an und faengt ein daraus resultierendes
    lo > hi mit `min(lo, hi)` ab -- STILLSCHWEIGEND, ohne dass der Aufrufer
    je erfaehrt, dass eine explizit in der House-Matrix konfigurierte
    Bandbreite (z.B. ein hoeheres Immobilien-Minimum fuer ein bestimmtes
    Risikoprofil) dabei ueberschrieben wurde. Dieselbe Bugklasse wie RES-1
    (Risikobudget-Fallback verwarf manuelle Bandbreiten-Restriktionen
    stillschweigend) -- hier zusaetzlich reproduzierbar, weil die DB (siehe
    5eyes_schema_v4.0_FINAL.sql) real_estate_min_bps/alt_min_bps nur auf
    0..10000 prueft, NICHT auf die niedrigeren globalen Caps (2000/1000bps).
    Ein Admin kann ueber POST .../house-matrix-rows also durchaus eine Zeile
    mit real_estate_min_bps=2500 speichern, die der Solver dann klanglos auf
    exakt 2000bps zusammendrueckt. Diese Funktion macht den Konflikt sichtbar
    (Aufrufer haengt die Warnungen in OptimizerResult.reasoning), aendert
    aber NICHT das (konservative, absichtlich harte) Cap-Verhalten selbst.
    """
    warnings: list[str] = []
    re_lo, _re_hi = bands.real_estate
    if re_lo > MAX_REAL_ESTATE:
        warnings.append(
            f"House-Matrix-Minimum Immobilien ({re_lo * 10000:.0f}bps) liegt über dem "
            f"globalen Cap ({int(MAX_REAL_ESTATE * 10000)}bps) — Solver wurde auf den "
            "Cap-Wert begrenzt, das konfigurierte Minimum wurde NICHT eingehalten."
        )
    alt_lo, _alt_hi = bands.alternatives
    if alt_lo > MAX_ALTERNATIVES:
        warnings.append(
            f"House-Matrix-Minimum Alternative Anlagen ({alt_lo * 10000:.0f}bps) liegt über "
            f"dem globalen Cap ({int(MAX_ALTERNATIVES * 10000)}bps) — Solver wurde auf den "
            "Cap-Wert begrenzt, das konfigurierte Minimum wurde NICHT eingehalten."
        )
    _liq_lo, liq_hi = bands.liquidity
    if liq_hi < MIN_LIQUIDITY:
        warnings.append(
            f"House-Matrix-Maximum Liquidität ({liq_hi * 10000:.0f}bps) liegt unter dem "
            f"globalen Floor ({int(MIN_LIQUIDITY * 10000)}bps) — Solver wurde auf den "
            "House-Matrix-Wert begrenzt, der globale Liquiditäts-Floor wurde NICHT eingehalten."
        )
    return warnings


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
    max_risky_fraction_bps: int | None = None,
) -> dict:
    """Inequality: score_x10/10 - Σ w_i · rf_i ≥ 0

    score_x10: 0..100 (Score×10). 70 -> max 70% risky.
    risky_fraction_per_bucket: optional override; default DEFAULT_BUCKET_RISKY_FRACTION
    """
    rf_map = (
        dict(DEFAULT_BUCKET_RISKY_FRACTION)
        if risky_fraction_per_bucket is None
        else validate_risky_fraction_per_bucket(risky_fraction_per_bucket)
    )
    rf_array = np.array([rf_map.get(b, 0.0) for b in BUCKET_ORDER], dtype=np.float64)
    cap = _validated_risky_cap_fraction(score_x10, max_risky_fraction_bps)
    return {
        "type": "ineq",
        "fun": lambda w: float(cap - float(np.dot(w, rf_array))),
        "jac": lambda w: -rf_array.copy(),
    }


def build_constraint_set(
    bands: HouseMatrixBands,
    score_x10: int,
    risky_fraction_per_bucket: dict[str, float] | None = None,
    max_risky_fraction_bps: int | None = None,
) -> tuple[list[tuple[float, float]], list[dict]]:
    """Komplettes scipy-kompatibles Constraint-Set.

    Returns:
        bounds: list of (lo, hi) per bucket in BUCKET_ORDER
        constraints: list of dicts (sum-to-one + risky-fraction)
    """
    bounds = build_bounds(bands)
    validate_risky_constraint_feasibility(
        bounds=bounds,
        score_x10=score_x10,
        risky_fraction_per_bucket=risky_fraction_per_bucket,
        max_risky_fraction_bps=max_risky_fraction_bps,
    )
    constraints = [
        build_sum_to_one_constraint(),
        build_risky_fraction_constraint(
            score_x10,
            risky_fraction_per_bucket,
            max_risky_fraction_bps=max_risky_fraction_bps,
        ),
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

    Konsistent zu Advisory-Methodik-Slide 17: Pro Sub-Asset-Class ist eine eigene Risky-
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


# ============================================================================
# V3 Sprint 1d (Plan §5.3): Constraint Slacks (Berater-Erklaerbarkeit)
# ============================================================================


@dataclass(frozen=True)
class ConstraintSlack:
    """Strukturierter Slack einer einzelnen Constraint gegen eine Allocation.

    code:           stabiler ID-String fuer FE-Mapping
                    (z.B. 'risky_fraction_cap', 'equities_min', 'bonds_max').
    label:          menschen-lesbares Label fuer Berater (DE).
    value_bps:      aktueller Wert der Constraint-Variable in bps.
                    Bei Min-Bounds: aktueller Bucket-Anteil.
                    Bei Max-Bounds: aktueller Bucket-Anteil.
                    Bei Risky-Fraction-Cap: gewichteter Risky-Anteil.
    limit_bps:      die Constraint-Grenze in bps.
    slack_bps:      Distanz zur Grenze (hi - val) bzw. (val - lo).
                    Negative Werte zeigen eine Verletzung.
    is_binding:     True wenn 0 <= slack_bps <= binding_threshold_bps.
                    Vom Berater interpretiert als 'praktisch ausgereizt'.
    is_violated:    True wenn slack_bps < 0.
    """
    code: str
    label: str
    value_bps: int
    limit_bps: int
    slack_bps: int
    is_binding: bool
    is_violated: bool


_BUCKET_LABEL_DE = {
    "equities": "Aktien",
    "bonds": "Obligationen",
    "real_estate": "Immobilien",
    "alternatives": "Alternative",
    "liquidity": "Liquiditaet",
}


def constraint_slacks(
    weights_bps: dict[str, int],
    *,
    bounds: list[tuple[float, float]],
    score_x10: int,
    risky_fraction_per_bucket: dict[str, float] | None = None,
    max_risky_fraction_bps: int | None = None,
    binding_threshold_bps: int = 25,
) -> list[ConstraintSlack]:
    """Berechnet pro Constraint einen ConstraintSlack gegen eine Allocation.

    Plan §5.3: Advisor-tauglicher Output, der zeigt 'welche Leitplanke wirklich
    begrenzt' (statt nur 'feasible' / 'not feasible').

    Liefert eine Liste in dieser Reihenfolge:
    1. Risky-Fraction-Cap
    2. Pro Bucket (BUCKET_ORDER): {bucket}_min, {bucket}_max

    binding_threshold_bps: Slack-Schwelle in bps, ab der eine Constraint als
        'bindend' gilt (default 25 bps = 0.25 Prozentpunkte).
    """
    rf_map = (
        dict(DEFAULT_BUCKET_RISKY_FRACTION)
        if risky_fraction_per_bucket is None
        else validate_risky_fraction_per_bucket(risky_fraction_per_bucket)
    )
    w = np.array(
        [int((weights_bps or {}).get(bucket, 0) or 0) / 10000.0 for bucket in BUCKET_ORDER],
        dtype=np.float64,
    )
    rf = np.array([float(rf_map.get(b, 0.0)) for b in BUCKET_ORDER], dtype=np.float64)
    risk_used_bps = int(round(float(np.dot(w, rf)) * 10000))
    risk_limit_bps = int(round(
        _validated_risky_cap_fraction(score_x10, max_risky_fraction_bps) * 10000
    ))
    risk_slack_bps = risk_limit_bps - risk_used_bps

    rows: list[ConstraintSlack] = [
        ConstraintSlack(
            code="risky_fraction_cap",
            label="Risky Fraction Cap",
            value_bps=risk_used_bps,
            limit_bps=risk_limit_bps,
            slack_bps=risk_slack_bps,
            is_binding=(0 <= risk_slack_bps <= binding_threshold_bps),
            is_violated=risk_slack_bps < 0,
        )
    ]

    for idx, bucket in enumerate(BUCKET_ORDER):
        if idx >= len(bounds):
            continue
        lo, hi = bounds[idx]
        val_bps = int(round(w[idx] * 10000))
        lo_bps = int(round(float(lo) * 10000))
        hi_bps = int(round(float(hi) * 10000))
        bucket_label = _BUCKET_LABEL_DE.get(bucket, bucket)
        # Min-Slack: val - lo. Negative = unter Floor.
        min_slack_bps = val_bps - lo_bps
        rows.append(ConstraintSlack(
            code=f"{bucket}_min",
            label=f"{bucket_label} Minimum",
            value_bps=val_bps,
            limit_bps=lo_bps,
            slack_bps=min_slack_bps,
            is_binding=(0 <= min_slack_bps <= binding_threshold_bps),
            is_violated=min_slack_bps < 0,
        ))
        # Max-Slack: hi - val. Negative = ueber Cap.
        max_slack_bps = hi_bps - val_bps
        rows.append(ConstraintSlack(
            code=f"{bucket}_max",
            label=f"{bucket_label} Maximum",
            value_bps=val_bps,
            limit_bps=hi_bps,
            slack_bps=max_slack_bps,
            is_binding=(0 <= max_slack_bps <= binding_threshold_bps),
            is_violated=max_slack_bps < 0,
        ))
    return rows


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

    if weights.shape != (N_BUCKETS,):
        return False, [
            f"weights shape invalid (expected {(N_BUCKETS,)}, got {weights.shape})"
        ]
    if not np.all(np.isfinite(weights)):
        return False, ["weights contain NaN or infinite values"]

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
