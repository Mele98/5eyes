"""Deterministische Stress-Szenarien fuer Optimizer-Audit (Phase 5.2).

Master-Spec: docs/planning/2026-05-05-stochastic-optimizer-spec.md (Sec D #15)

Drei historisch kalibrierte Krisen-Pfade. Diese sind KEINE Constraints fuer
den Solver, sondern POST-OPTIMIZATION Audit-Tests:

Nach Solver-Konvergenz wird die Allocation in jedem Stress-Pfad simuliert
und in den OptimizerResult.stress_evaluations als dict[str, dict] geschrieben.
Der Berater sieht damit: "Im 2008-Crisis-Szenario erreicht dein Pension-
Goal noch 67% des Targets."

Werte sind multiplikative Jahres-Faktoren pro Bucket (in BUCKET_ORDER:
equities, bonds, real_estate, alternatives, liquidity). 1.0 = 0% Return,
0.55 = -45% Verlust, 1.20 = +20% Gewinn.

Quellen (vereinfacht aus historischen Index-Returns):
- Great Depression 1929: SP500 -89% peak-to-trough 1929-1932
- Financial Crisis 2008: SPX -38% 2008, +26% 2009 (V-shape)
- COVID + 2022 Inflation: -10% 2020 dip, +20% 2021 rally, -18% 2022 bear

Limitation: Diese Pfade sind starr. Ein vollwertiges Stress-Test-Framework
wuerde Faktor-Modelle nutzen (Inflation/Zins/Risk-Premia-Schocks). Diese
Phase 5.2 Implementation ist Audit-Anchor + Erklaerbarkeit, nicht
Stress-Test-Optimierung.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .scenario_engine import BUCKET_ORDER, N_BUCKETS, simulate_wealth_paths


# ============================================================================
# Stress-Szenarien (deterministische Faktor-Pfade)
# ============================================================================
# Pro Szenario: ndarray (n_years, 5) mit multiplikativen Faktoren.
# Reihenfolge: equities, bonds, real_estate, alternatives, liquidity


STRESS_SCENARIOS: dict[str, np.ndarray] = {
    # Great Depression 1929-1933: Aktien aufgezehrt ueber 4 Jahre, langsame
    # Recovery. Bonds CH waren sicherer Hafen, aber Deflation erschwert.
    "great_depression_1929": np.array([
        # Y1: -45% equities, +5% bonds (deflation), -15% RE, -25% alts, +1% liq
        [0.55, 1.05, 0.85, 0.75, 1.01],
        [0.75, 1.05, 0.90, 0.90, 1.01],
        [0.90, 1.03, 1.05, 1.05, 1.01],
        [1.05, 1.02, 1.08, 1.05, 1.01],
        [1.10, 1.02, 1.05, 1.05, 1.01],
    ], dtype=np.float64),
    # Financial Crisis 2008: V-shape mit starker Erholung 2009.
    "financial_crisis_2008": np.array([
        [0.62, 1.05, 0.75, 0.70, 1.02],   # 2008: -38% SP500
        [1.25, 1.05, 0.90, 1.15, 1.02],   # 2009: +26% recovery
        [1.10, 1.02, 1.00, 1.05, 1.02],
    ], dtype=np.float64),
    # COVID 2020 + Inflation/Zinsschock 2022. 4-Jahre-Stress mit Bonds
    # diesmal NICHT als sicherer Hafen (Zinsanstieg).
    "covid_inflation_2020_2022": np.array([
        [0.90, 1.00, 1.00, 0.95, 1.00],   # 2020: -10% Aktien
        [1.20, 1.01, 1.00, 1.10, 1.00],   # 2021: Erholung
        [0.82, 0.85, 0.95, 0.92, 1.00],   # 2022: -18% SP500, -15% Bonds
        [1.05, 1.01, 1.02, 1.02, 1.00],   # 2023: leichte Erholung
    ], dtype=np.float64),
}


# ============================================================================
# Result-DataClass
# ============================================================================


@dataclass(frozen=True)
class StressResult:
    """Eval-Ergebnis pro Stress-Szenario."""
    scenario_name: str
    end_wealth_rappen: int
    min_year_wealth_rappen: int  # tiefster Pfad-Wert (kann negativ sein = Lebensluecke)
    # STRESS-SEMANTICS-001: peak-to-trough des FLUSSFREIEN Portfolio-Indexes
    # (cumprod(weights @ factors)), immer in [0, 10000]. Frueher auf dem
    # flussbehafteten Vermoegens-Pfad gerechnet -> Werte > 100 % moeglich.
    max_drawdown_bps: int
    # Flussfreie kumulierte Portfolio-Rendite ueber die Krisenjahre.
    cumulative_return_bps: int = 0
    # Gleicher Vermoegens-Lauf (gleiche Flows, gleiches Padding) OHNE Krise.
    baseline_end_wealth_rappen: int = 0
    # end_wealth - baseline_end_wealth = was die Krise selbst kostet.
    crisis_impact_end_wealth_rappen: int = 0


# ============================================================================
# Pad-Funktion fuer Stress-Pfade kuerzer als Optimizer-Horizon
# ============================================================================


def _pad_stress_to_horizon(
    stress_path: np.ndarray,
    horizon_years: int,
    pad_factor: float = 1.0,
) -> np.ndarray:
    """Padded Stress-Pfad auf horizon_years mit pad_factor (Default 1.0 = 0%).

    Stress-Szenarien sind typischerweise 3-5 Jahre. Wenn der Optimizer-
    Horizon laenger ist (z.B. 20J fuer Pension-Mandant), padded mit nominalen
    Returns - der Stress passiert in den ersten Jahren und danach laeuft
    es flat weiter. Das Padding ist KEINE Renditeprognose: sein Effekt auf
    End-/Min-Vermoegen wird in evaluate_stress_scenarios ueber eine
    No-Crisis-Baseline mit identischem Padding herausgerechnet
    (STRESS-SEMANTICS-001).
    """
    stress_years, n_buckets = stress_path.shape
    if stress_years >= horizon_years:
        return stress_path[:horizon_years].copy()
    padded = np.full((horizon_years, n_buckets), pad_factor, dtype=np.float64)
    padded[:stress_years] = stress_path
    return padded


def _portfolio_index_metrics(
    weights: np.ndarray, crisis_path: np.ndarray
) -> tuple[int, int]:
    """Max-Drawdown + kumulierte Rendite des flussfreien Portfolio-Indexes.

    Index_t = prod_{s<=t}(weights @ factors_s), Start 1.0 (= Peak zu t=0).
    Ohne Cashflows/Ziel-Ausgaben: das ist die Standard-Definition des
    Drawdowns einer Strategie. Returns (max_drawdown_bps in [0, 10000],
    cumulative_return_bps).
    """
    growth = crisis_path @ weights
    index = np.concatenate(([1.0], np.cumprod(growth)))
    running_peak = np.maximum.accumulate(index)
    drawdowns = np.where(running_peak > 0, (running_peak - index) / running_peak, 0.0)
    max_dd_bps = int(round(float(np.max(drawdowns)) * 10000))
    max_dd_bps = min(10000, max(0, max_dd_bps))
    cumulative_bps = int(round((float(index[-1]) - 1.0) * 10000))
    return max_dd_bps, cumulative_bps


def evaluate_stress_scenarios(
    *,
    weights: np.ndarray,
    initial_wealth_rappen: int,
    cashflow_series_rappen: list[int],
    liability_path_rappen: list[int] | None,
    horizon_years: int,
    scenarios: dict[str, np.ndarray] | None = None,
) -> dict[str, StressResult]:
    """Simuliert die Allocation in jedem Stress-Szenario, deterministisch.

    Zwei getrennte Sichten (STRESS-SEMANTICS-001):

    1. Portfolio-Sicht (flussfrei): ``max_drawdown_bps`` und
       ``cumulative_return_bps`` aus dem Index cumprod(weights @ factors)
       ueber die Krisenjahre. Unabhaengig von Vermoegen und Cashflows,
       Drawdown immer in [0, 10000].

    2. Vermoegens-Sicht (mit Kunden-Cashflows und Ziel-Ausgaben):
       ``end_wealth_rappen`` / ``min_year_wealth_rappen`` (kann negativ
       werden = Lebensluecke). Padding: der 3-5-jaehrige Krisenpfad wird mit
       Faktor 1.0 (= 0 % nominal) auf ``horizon_years`` aufgefuellt -- es
       werden bewusst KEINE Renditeannahmen fuer die Jahre nach der Krise
       erfunden. Weil dieses Padding (zusammen mit den Entnahmen) End- und
       Min-Vermoegen dominiert, wird derselbe Lauf zusaetzlich unter einer
       Baseline OHNE Krise gerechnet (alle Jahre Faktor 1.0, gleiche Flows):
       ``baseline_end_wealth_rappen``; ``crisis_impact_end_wealth_rappen`` =
       end_wealth - baseline_end_wealth zeigt, was die Krise selbst kostet.

    Nutzt simulate_wealth_paths der Engine - ein einzelner Pfad pro
    Szenario, also (1, horizon, 5) shape.
    """
    weights = np.asarray(weights, dtype=np.float64).reshape(N_BUCKETS)
    horizon_years = max(1, int(horizon_years))
    if scenarios is None:
        scenarios = STRESS_SCENARIOS

    def _simulate_end_and_min(path: np.ndarray) -> tuple[int, int]:
        wealth = simulate_wealth_paths(
            initial_wealth_rappen=initial_wealth_rappen,
            weights=weights,
            return_paths=path.reshape(1, horizon_years, N_BUCKETS),
            cashflow_series_rappen=cashflow_series_rappen,
            liability_path_rappen=liability_path_rappen,
        )[0]  # nur 1 path
        return int(round(wealth[-1])), int(round(np.min(wealth)))

    # Baseline ohne Krise: identisches Padding (Faktor 1.0) ueber alle Jahre.
    baseline_path = np.ones((horizon_years, N_BUCKETS), dtype=np.float64)
    baseline_end, _baseline_min = _simulate_end_and_min(baseline_path)

    results: dict[str, StressResult] = {}
    for name, stress in scenarios.items():
        stress = np.asarray(stress, dtype=np.float64)
        path = _pad_stress_to_horizon(stress, horizon_years)
        end_wealth, min_wealth = _simulate_end_and_min(path)
        crisis_years = min(stress.shape[0], horizon_years)
        max_dd_bps, cumulative_bps = _portfolio_index_metrics(
            weights, path[:crisis_years]
        )
        results[name] = StressResult(
            scenario_name=name,
            end_wealth_rappen=end_wealth,
            min_year_wealth_rappen=min_wealth,
            max_drawdown_bps=max_dd_bps,
            cumulative_return_bps=cumulative_bps,
            baseline_end_wealth_rappen=baseline_end,
            crisis_impact_end_wealth_rappen=end_wealth - baseline_end,
        )
    return results


def stress_results_to_dict(results: dict[str, StressResult]) -> dict[str, dict]:
    """Konvertiert StressResult-dict in JSON-serialisierbares dict-of-dicts.

    Wird im OptimizerResult.reasoning eingebettet bzw. als JSON-Spalte
    persistiert (Phase 6: extra Audit-Spalte stress_evaluations_json).
    """
    return {
        name: {
            "scenario_name": r.scenario_name,
            "end_wealth_rappen": r.end_wealth_rappen,
            "min_year_wealth_rappen": r.min_year_wealth_rappen,
            "max_drawdown_bps": r.max_drawdown_bps,
            "cumulative_return_bps": r.cumulative_return_bps,
            "baseline_end_wealth_rappen": r.baseline_end_wealth_rappen,
            "crisis_impact_end_wealth_rappen": r.crisis_impact_end_wealth_rappen,
        }
        for name, r in results.items()
    }
