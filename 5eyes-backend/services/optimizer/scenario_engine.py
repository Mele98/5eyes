"""Vektorisierte Szenario-Engine fuer den Optimizer.

Master-Spec: docs/planning/2026-05-05-stochastic-optimizer-spec.md (Sec 7,9)

Kontrast zur bestehenden services.portfolio_engine._run_allocation_monte_carlo:
diese ist eine *isolierte* NumPy-Implementierung speziell fuer den Optimizer.
Die existing MC-Engine bleibt unangetastet (Audit-konsistent, alle Z/B/W2.5
Tests gruen). Der Optimizer ruft AUSSCHLIESSLICH diese Engine, nicht die
existing.

Vorteile dieser Engine:
1. NumPy-vektorisiert -> 50-100x schneller als python-loop
2. Cornish-Fisher fat-tail Sampling pro Bucket
3. Antithetic Variates fuer Variance Reduction
4. Deterministischer Seed via numpy Generator
5. Liability-Pfad als zusaetzlicher Outflow-Subtrahierter

Convention:
- bucket order: ('equities', 'bonds', 'real_estate', 'alternatives', 'liquidity')
- weights[i] = Anteil von bucket i (summe = 1.0)
- horizon_years = Anzahl Jahre simuliert
- return_paths shape: (n_paths, horizon_years, 5) - multiplikative Faktoren
  (1.05 = +5% Jahres-Return)
- wealth_paths shape: (n_paths, horizon_years + 1) - in Rappen (kann negativ
  werden = Lebensluecke)

Lebensluecke: konsistent zur existing W2.5-Logik. Wenn wealth nach Cashflow
& Liability negativ wird, wachst es NICHT (kein Zins-auf-Schuld) sondern
bleibt nominal stehen bis Cashflow positiv wird.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np

from .distributions import _MAX_EXCESS_KURT, _MAX_SKEW


# Konsistent zu services.portfolio_engine.BUCKET_FIELDS
BUCKET_ORDER = ("equities", "bonds", "real_estate", "alternatives", "liquidity")
N_BUCKETS = len(BUCKET_ORDER)


@dataclass(frozen=True)
class ScenarioInputs:
    """Compactes Input-Tupel fuer die Engine.

    Vermeidet Abhaengigkeit von SQLAlchemy Models in der Engine selbst -
    der Caller extrahiert die Werte aus CapitalMarketAssumption.

    Alle bps-Werte sind integer, Cholesky-Matrix ist (5,5) ndarray.
    skew/kurt sind in bps (z.B. -5000 = -0.5 skew). Wenn None, fallback 0.
    """
    mu_bps: np.ndarray  # shape (5,)
    sigma_bps: np.ndarray  # shape (5,)
    skew_bps: np.ndarray  # shape (5,) - 0 wenn nicht gesetzt
    excess_kurt_bps: np.ndarray  # shape (5,) - 0 wenn nicht gesetzt
    cholesky: np.ndarray  # shape (5, 5) lower-triangular


# ============================================================================
# Cornish-Fisher in NumPy (Vektor-Variante der distributions.py)
# ============================================================================


def cornish_fisher_array(
    z: np.ndarray,
    skew: np.ndarray,
    excess_kurt: np.ndarray,
) -> np.ndarray:
    """NumPy-Variante von distributions.cornish_fisher_quantile.

    z: shape (...) standard-normal Stichproben
    skew, excess_kurt: shape (n_assets,) oder broadcastable

    Clamping konsistent zu distributions._clamp_skew/_clamp_kurt:
    s in [-1, 1], k in [0, 8].
    """
    s = np.clip(skew, -_MAX_SKEW, _MAX_SKEW)
    k = np.clip(excess_kurt, 0.0, _MAX_EXCESS_KURT)
    z2 = z * z
    z3 = z2 * z
    return (
        z
        + (z2 - 1.0) * s / 6.0
        + (z3 - 3.0 * z) * k / 24.0
        - (2.0 * z3 - 5.0 * z) * (s * s) / 36.0
    )


# ============================================================================
# Build Scenario Paths
# ============================================================================


def _safe_cholesky(corr_matrix: np.ndarray) -> np.ndarray:
    """Cholesky mit Fallback auf Identity wenn Matrix nicht positiv-definit.

    Konsistent zu services.portfolio_engine._build_cholesky_from_cma.
    """
    try:
        return np.linalg.cholesky(corr_matrix)
    except np.linalg.LinAlgError:
        return np.eye(corr_matrix.shape[0])


def build_default_correlation_matrix() -> np.ndarray:
    """Default 5x5 Korrelationsmatrix (CH-Markt, konservativ).

    Werte konsistent zu services.portfolio_engine._DEFAULT_CORRELATION_MATRIX.
    Reihenfolge: equities, bonds, real_estate, alternatives, liquidity.
    """
    # Konservative Default-Korrelationen aus CH-Markt 1990-2024
    return np.array([
        [1.00, -0.10, 0.45, 0.30, 0.05],
        [-0.10, 1.00, 0.10, -0.05, 0.20],
        [0.45, 0.10, 1.00, 0.25, 0.05],
        [0.30, -0.05, 0.25, 1.00, 0.05],
        [0.05, 0.20, 0.05, 0.05, 1.00],
    ])


def build_scenario_paths(
    inputs: ScenarioInputs,
    *,
    horizon_years: int,
    n_paths: int,
    seed: int,
    antithetic: bool = True,
) -> np.ndarray:
    """Liefert (n_paths, horizon_years, 5) array von log-normal Returns.

    Pro Pfad pro Jahr pro Asset wird ein multiplikativer Faktor
    R = exp(mu - 0.5 * sigma^2 + sigma * Z_correlated_cf) erzeugt.

    Antithetic Variates: wenn True, wird die zweite Haelfte der Pfade als
    -Z gespiegelt. Das reduziert Varianz fuer symmetrische Statistiken
    (Mean, Median) und ist Standard in Mulvey/Ziemba-MC.

    Determinismus: gleicher seed + gleiche inputs -> identische Output-Array.
    Wir nutzen np.random.default_rng(seed) (PCG64), nicht legacy RandomState.
    """
    horizon_years = int(max(1, horizon_years))
    n_paths = int(max(1, n_paths))

    if antithetic:
        half = (n_paths + 1) // 2  # round up; antithetic ergaenzt zur Gesamtzahl
    else:
        half = n_paths

    rng = np.random.default_rng(np.uint64(seed))
    # Independent standard normals: shape (half, horizon, n_buckets)
    Z = rng.standard_normal(size=(half, horizon_years, N_BUCKETS))

    # Apply Cholesky correlation per (path, year) - shape stays (half, horizon, n_buckets)
    # Z @ chol.T (broadcasted): np.einsum is most explicit
    Z_corr = np.einsum("phb,kb->phk", Z, inputs.cholesky)

    # Cornish-Fisher per asset (broadcasting)
    skew = inputs.skew_bps / 10_000.0  # bps -> decimal
    kurt = inputs.excess_kurt_bps / 10_000.0
    Z_cf = cornish_fisher_array(Z_corr, skew, kurt)

    if antithetic:
        # Antithetic: -Z (auch durch Cholesky, sollte gleich sein)
        Z_anti_corr = -Z_corr
        Z_anti_cf = cornish_fisher_array(Z_anti_corr, skew, kurt)
        Z_combined = np.concatenate([Z_cf, Z_anti_cf], axis=0)[:n_paths]
    else:
        Z_combined = Z_cf

    # Itô-Korrektur + log-normal
    mu = inputs.mu_bps / 10_000.0
    sigma = inputs.sigma_bps / 10_000.0
    log_returns = (mu - 0.5 * sigma * sigma) + sigma * Z_combined  # broadcasting
    return_factors = np.exp(log_returns)
    return return_factors


# ============================================================================
# Simulate Wealth Paths
# ============================================================================


def simulate_wealth_paths(
    *,
    initial_wealth_rappen: int,
    weights: np.ndarray,
    return_paths: np.ndarray,
    cashflow_series_rappen: Iterable[int],
    liability_path_rappen: Iterable[int] | None = None,
) -> np.ndarray:
    """Simuliert Wealth-Pfad ueber alle Szenarien.

    weights: shape (5,), summe ~ 1.0 (Toleranz: keine Constraint hier)
    return_paths: shape (n_paths, horizon, 5) aus build_scenario_paths
    cashflow_series_rappen: shape (horizon,) - Netto-Cashflow pro Jahr
        (positiv = Income > Expense)
    liability_path_rappen: shape (horizon,) - Goal-Outflows pro Jahr
        (positiv = Outflow). Wird vom Cashflow subtrahiert (also wealth wird
        kleiner). None = kein Goal-Outflow.

    Returns: (n_paths, horizon + 1) wealth array. wealth[:, 0] = initial,
    wealth[:, t+1] = wealth nach Wachstum + Cashflow - Liability im Jahr t.

    Lebensluecke (W2.5-konsistent): wealth kann negativ werden. Bei
    negativem wealth wird KEIN Zins-Effekt angewendet (deficit waechst nicht
    durch Schuldzinsen - nur durch weitere negative Cashflows).
    """
    return_paths = np.asarray(return_paths, dtype=np.float64)
    weights = np.asarray(weights, dtype=np.float64).reshape(N_BUCKETS)
    n_paths, horizon, n_buckets = return_paths.shape
    if n_buckets != N_BUCKETS:
        raise ValueError(f"return_paths last dim must be {N_BUCKETS}, got {n_buckets}")

    cashflow = np.asarray(list(cashflow_series_rappen), dtype=np.float64)
    if cashflow.shape != (horizon,):
        # Pad/trim auf horizon
        padded = np.zeros(horizon, dtype=np.float64)
        copy_len = min(horizon, cashflow.size)
        padded[:copy_len] = cashflow[:copy_len]
        cashflow = padded

    if liability_path_rappen is None:
        liability = np.zeros(horizon, dtype=np.float64)
    else:
        liability = np.asarray(list(liability_path_rappen), dtype=np.float64)
        if liability.shape != (horizon,):
            padded = np.zeros(horizon, dtype=np.float64)
            copy_len = min(horizon, liability.size)
            padded[:copy_len] = liability[:copy_len]
            liability = padded

    wealth = np.empty((n_paths, horizon + 1), dtype=np.float64)
    wealth[:, 0] = float(initial_wealth_rappen)

    for t in range(horizon):
        # Portfolio-Faktor pro Pfad: gewichtete Summe der Asset-Returns
        portfolio_factor = np.einsum("pb,b->p", return_paths[:, t, :], weights)
        prev = wealth[:, t]
        # Wachstum nur fuer positive Wealth; negative bleibt nominal (W2.5)
        grown = np.where(prev > 0, prev * portfolio_factor, prev)
        wealth[:, t + 1] = grown + cashflow[t] - liability[t]

    return wealth


# ============================================================================
# Helper: Inputs aus CMA-like Object (loose duck-typing)
# ============================================================================


def scenario_inputs_from_cma(cma) -> ScenarioInputs:
    """Extrahiert ScenarioInputs aus einem CMA-Objekt (oder Mock mit gleichen Attributen).

    Aggregiert Sub-Asset-Class Returns/Vols zu Bucket-Level. Diese Phase 1
    Implementation ist absichtlich grob: simpler Mittelwert der relevanten
    Sub-Klassen pro Bucket. Phase 2 (Sub-Allocation-Aware Bucket Metrics)
    wird das verfeinern - aktuell konsistent zu portfolio_engine
    `_asset_class_expected_metrics`.

    Korrelation: nutzt cma.correlation_matrix_json wenn 5x5 vorhanden,
    sonst default Swiss-market Matrix.
    """
    import json

    # Returns/Vols pro Bucket (aggregiert grob aus Sub-Klassen)
    # Konsistent zur Aggregation in portfolio_engine._asset_class_expected_metrics
    bucket_returns = {
        "equities": _avg_or_zero([cma.equity_ch_return_bps, cma.equity_intl_return_bps]),
        "bonds": _avg_or_zero([
            cma.bonds_chf_ig_return_bps, cma.bonds_fx_hedged_return_bps,
        ]),
        "real_estate": _avg_or_zero([cma.real_estate_ch_return_bps]),
        "alternatives": _avg_or_zero([cma.alternatives_gold_return_bps]),
        "liquidity": _avg_or_zero([cma.liquidity_return_bps]),
    }
    bucket_vols = {
        "equities": _avg_or_zero([cma.equity_ch_vol_bps, cma.equity_intl_vol_bps]),
        "bonds": _avg_or_zero([
            cma.bonds_chf_ig_vol_bps, cma.bonds_fx_hedged_vol_bps,
        ]),
        "real_estate": _avg_or_zero([cma.real_estate_ch_vol_bps]),
        "alternatives": _avg_or_zero([cma.alternatives_gold_vol_bps]),
        "liquidity": _avg_or_zero([cma.liquidity_vol_bps]),
    }

    mu_bps = np.array([bucket_returns[b] for b in BUCKET_ORDER], dtype=np.float64)
    sigma_bps = np.array([bucket_vols[b] for b in BUCKET_ORDER], dtype=np.float64)

    # Skew + Kurt: Phase 1 Felder pro Bucket aus CMA
    skew_bps = np.array([
        int(getattr(cma, f"{b}_skewness_bps", 0) or 0)
        for b in BUCKET_ORDER
    ], dtype=np.float64)
    excess_kurt_bps = np.array([
        int(getattr(cma, f"{b}_excess_kurt_bps", 0) or 0)
        for b in BUCKET_ORDER
    ], dtype=np.float64)

    # Korrelations-Matrix
    correlation_json = getattr(cma, "correlation_matrix_json", None) or ""
    correlation = build_default_correlation_matrix()
    if correlation_json:
        try:
            parsed = json.loads(correlation_json)
            if isinstance(parsed, list) and len(parsed) == N_BUCKETS:
                arr = np.array(parsed, dtype=np.float64)
                if arr.shape == (N_BUCKETS, N_BUCKETS):
                    correlation = arr
        except (ValueError, TypeError):
            pass  # fall back to default
    cholesky = _safe_cholesky(correlation)

    return ScenarioInputs(
        mu_bps=mu_bps,
        sigma_bps=sigma_bps,
        skew_bps=skew_bps,
        excess_kurt_bps=excess_kurt_bps,
        cholesky=cholesky,
    )


def _avg_or_zero(values: list) -> float:
    """Mittelwert der nicht-None-Werte; 0 wenn alle None."""
    valid = [int(v) for v in values if v is not None]
    if not valid:
        return 0.0
    return float(sum(valid) / len(valid))
