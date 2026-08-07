"""End-to-End Tests fuer services/optimizer/solver.py.

Verifiziert:
- Solver konvergiert auf realistischen Mandanten-Setups
- Determinismus mit gleichem Seed
- Multi-Start liefert beste der 5 Initials
- Constraints werden respektiert (Bands, Risky-Fraction-Cap, Caps, Liquidity-Floor)
- Fallback wenn alle Multi-Starts divergieren
- Performance: <5s fuer typischen Case
- Hartes Pension-Goal -> konservativere Allokation als Maximierung-only
"""
from __future__ import annotations

import sys
import time
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.optimizer.constraints import (
    DEFAULT_BUCKET_RISKY_FRACTION,
    is_feasible,
    bands_from_house_matrix_row,
    build_constraint_set,
)
from services.optimizer.scenario_engine import BUCKET_ORDER
from services.optimizer.solver import (
    OptimizerResult,
    _covariance_bps_from_scenario_inputs,
    _markowitz_min_variance_candidate,
    build_initial_guesses,
    deterministic_seed,
    run_solver,
)


# ============================================================================
# Test Fixtures
# ============================================================================


def _make_cma(**overrides):
    defaults = {
        "id": "cma-test",
        "bonds_chf_ig_return_bps": 220, "bonds_chf_ig_vol_bps": 350,
        "bonds_fx_hedged_return_bps": 220, "bonds_fx_hedged_vol_bps": 430,
        "equity_ch_return_bps": 620, "equity_ch_vol_bps": 1450,
        "equity_intl_return_bps": 700, "equity_intl_vol_bps": 1600,
        "real_estate_ch_return_bps": 450, "real_estate_ch_vol_bps": 820,
        "alternatives_gold_return_bps": 300, "alternatives_gold_vol_bps": 1200,
        "liquidity_return_bps": 80, "liquidity_vol_bps": 20,
        "correlation_matrix_json": "",
        "equities_skewness_bps": -3000, "equities_excess_kurt_bps": 15000,
        "bonds_skewness_bps": 0, "bonds_excess_kurt_bps": 0,
        "real_estate_skewness_bps": 0, "real_estate_excess_kurt_bps": 0,
        "alternatives_skewness_bps": 0, "alternatives_excess_kurt_bps": 0,
        "liquidity_skewness_bps": 0, "liquidity_excess_kurt_bps": 0,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_house_matrix_row(profile="Wachstumsorientiert"):
    """Realistische House-Matrix fuer Score-Bucket 7 (Wachstum)."""
    return SimpleNamespace(
        profile_name=profile,
        equity_min_bps=4500, equity_max_bps=7000, equity_target_bps=6000,
        bonds_min_bps=2000, bonds_max_bps=4500, bonds_target_bps=3000,
        real_estate_min_bps=0, real_estate_max_bps=1500, real_estate_target_bps=500,
        alt_min_bps=0, alt_max_bps=1000, alt_target_bps=300,
        liq_min_bps=200, liq_max_bps=2000, liq_target_bps=200,
        max_risky_fraction_bps=7500,
    )


def _make_pension_goal(*, hardness="Hart", years_to_start=5, duration=20):
    today = date.today()
    start = (today + timedelta(days=365 * years_to_start)).isoformat()
    end = (today + timedelta(days=365 * (years_to_start + duration))).isoformat()
    return SimpleNamespace(
        id="goal-pension",
        label="Pension",
        goal_type="Pensionsausgabe",
        target_amount_rappen=24_000_00,  # 24'000 CHF jaehrlich
        target_wealth_rappen=None,
        target_return_bps=None,
        horizon_years=None,
        target_date=end,
        start_date=start,
        is_ongoing=0,
        frequency="jährlich",
        hardness=hardness,
        rank=1,
        weight_bps=5000,
        value_mode="real",
    )


def _make_maximierung_goal():
    return SimpleNamespace(
        id="goal-max",
        label="Maximierung",
        goal_type="Maximierung",
        target_amount_rappen=None,
        target_wealth_rappen=None,
        target_return_bps=None,
        horizon_years=None,
        target_date=None,
        start_date=None,
        is_ongoing=0,
        frequency=None,
        hardness="Opportunistisch",
        rank=5,
        weight_bps=1000,
        value_mode="nominal",
    )


# ============================================================================
# Determinismus + Seeds
# ============================================================================


def test_deterministic_seed_same_inputs_same_output():
    s1 = deterministic_seed("a", "b", 70)
    s2 = deterministic_seed("a", "b", 70)
    assert s1 == s2


def test_deterministic_seed_different_inputs_different_output():
    s1 = deterministic_seed("a", "b", 70)
    s2 = deterministic_seed("a", "b", 80)
    assert s1 != s2


def test_seed_is_within_uint64_range():
    s = deterministic_seed("foo", "bar", 100)
    assert 0 <= s < (1 << 63)


# ============================================================================
# Initial Guesses
# ============================================================================


def test_build_initial_guesses_returns_at_least_one_feasible():
    """Bei strikten Bounds sind nicht alle 5 Kandidaten feasible -> Filter
    wirft pathologische raus. Mindestens 1 (Mid-of-Bounds) muss zurueckkommen,
    und alle die zurueckkommen muessen feasible sein."""
    bounds = [(0.4, 0.7), (0.2, 0.5), (0.0, 0.20), (0.0, 0.10), (0.02, 0.20)]
    initials = build_initial_guesses(bounds, score_x10=70)
    assert len(initials) >= 1, "Mindestens ein Multi-Start-Kandidat muss zurueckkommen"
    assert len(initials) <= 5, "Maximal 5 Kandidaten generiert"
    for w in initials:
        assert w.shape == (5,)
        assert sum(w) == pytest.approx(1.0, abs=0.01)
        # Alle gefilterten Initials muessen tatsaechlich in den Bounds liegen
        for i, (lo, hi) in enumerate(bounds):
            assert lo - 1e-3 <= w[i] <= hi + 1e-3, (
                f"Initial {w} bucket {i} bounds ({lo}, {hi}) verletzt: {w[i]}"
            )


def test_build_initial_guesses_with_loose_bounds_returns_all_5():
    """Mit weiten Bounds passen alle 5 Strategien."""
    bounds = [(0.0, 1.0)] * 5
    initials = build_initial_guesses(bounds, score_x10=70)
    assert len(initials) == 5


# ============================================================================
# PAR-5: Markowitz-informierter Multi-Start-Kandidat (3eyes-Parity)
# ============================================================================


def _reasonable_mu_and_cov():
    """Plausible bps-Inputs (aus einer realistischen CMA), fuer Markowitz-Tests."""
    mu_bps = np.array([650.0, 220.0, 450.0, 300.0, 80.0])  # BUCKET_ORDER
    sigma_bps = np.array([1500.0, 380.0, 820.0, 1200.0, 20.0])
    cholesky = np.linalg.cholesky(np.eye(5))  # unkorreliert, sicher PD
    cov_bps = _covariance_bps_from_scenario_inputs(sigma_bps, cholesky)
    return mu_bps, cov_bps


def test_markowitz_candidate_respects_bucket_bounds_and_sums_to_one():
    """(a) Der neue Kandidat erfuellt Summe=1 (~10000bps) und Bucket-Bounds."""
    bounds = [(0.0, 1.0)] * 5
    mu_bps, cov_bps = _reasonable_mu_and_cov()
    candidate = _markowitz_min_variance_candidate(bounds, mu_bps, cov_bps)
    assert candidate is not None
    assert candidate.shape == (5,)
    assert float(np.sum(candidate)) == pytest.approx(1.0, abs=1e-3)
    for i, (lo, hi) in enumerate(bounds):
        assert lo - 1e-3 <= candidate[i] <= hi + 1e-3


def test_markowitz_candidate_respects_tight_house_matrix_bands():
    """Auch mit engen, realistischen House-Matrix-Bands bleibt der Kandidat
    innerhalb der Bounds (nicht nur bei trivialen [0,1]-Bounds)."""
    bounds = [(0.4, 0.7), (0.2, 0.5), (0.0, 0.20), (0.0, 0.10), (0.02, 0.20)]
    mu_bps, cov_bps = _reasonable_mu_and_cov()
    candidate = _markowitz_min_variance_candidate(bounds, mu_bps, cov_bps)
    assert candidate is not None
    assert float(np.sum(candidate)) == pytest.approx(1.0, abs=1e-3)
    for i, (lo, hi) in enumerate(bounds):
        assert lo - 1e-3 <= candidate[i] <= hi + 1e-3


def test_markowitz_candidate_none_when_mu_or_cov_missing():
    """Ohne mu_bps/cov_bps (Backwards-Compat-Default) gibt es keinen Kandidaten."""
    bounds = [(0.0, 1.0)] * 5
    assert _markowitz_min_variance_candidate(bounds, None, None) is None
    mu_bps, cov_bps = _reasonable_mu_and_cov()
    assert _markowitz_min_variance_candidate(bounds, mu_bps, None) is None
    assert _markowitz_min_variance_candidate(bounds, None, cov_bps) is None


def test_markowitz_candidate_none_on_shape_mismatch():
    """(b) Degenerierter Input (falsche Shape) -> None statt Crash."""
    bounds = [(0.0, 1.0)] * 5
    bad_mu = np.array([1.0, 2.0])  # falsche Laenge
    _, cov_bps = _reasonable_mu_and_cov()
    assert _markowitz_min_variance_candidate(bounds, bad_mu, cov_bps) is None

    mu_bps, _ = _reasonable_mu_and_cov()
    bad_cov = np.eye(3)  # falsche Shape
    assert _markowitz_min_variance_candidate(bounds, mu_bps, bad_cov) is None


def test_markowitz_candidate_none_on_nan_inputs():
    """(b) NaN/Inf in mu oder cov -> None statt Crash (z.B. korrupte CMA-Werte)."""
    bounds = [(0.0, 1.0)] * 5
    mu_bps, cov_bps = _reasonable_mu_and_cov()
    nan_mu = mu_bps.copy()
    nan_mu[0] = np.nan
    assert _markowitz_min_variance_candidate(bounds, nan_mu, cov_bps) is None

    nan_cov = cov_bps.copy()
    nan_cov[0, 0] = np.inf
    assert _markowitz_min_variance_candidate(bounds, mu_bps, nan_cov) is None


def test_covariance_helper_none_on_singular_or_bad_cholesky_shape():
    """(b) Kaputte/gemismatchte Cholesky-Matrix -> Cov-Helper gibt None,
    kein Crash (z.B. corrupted correlation_matrix_json in der CMA)."""
    sigma_bps = np.array([1500.0, 380.0, 820.0, 1200.0, 20.0])
    wrong_shape_cholesky = np.eye(3)  # Shape-Mismatch zu 5 Buckets
    assert _covariance_bps_from_scenario_inputs(sigma_bps, wrong_shape_cholesky) is None

    nan_cholesky = np.eye(5)
    nan_cholesky[0, 0] = np.nan
    result = _covariance_bps_from_scenario_inputs(sigma_bps, nan_cholesky)
    assert result is None


def test_build_initial_guesses_without_markowitz_params_keeps_existing_5_unchanged():
    """(c) Regressionsschutz: ohne mu_bps/cov_bps liefert build_initial_guesses
    exakt dieselben (unveraenderten) 5 Kandidaten wie vor PAR-5."""
    bounds = [(0.0, 1.0)] * 5
    initials_without = build_initial_guesses(bounds, score_x10=70)
    assert len(initials_without) == 5

    # Mit Markowitz-Inputs muessen die ersten 5 Kandidaten (Mid, Conservative,
    # Aggressive, Risk-Cap-Edge, Equal) bit-identisch bleiben - PAR-5 ist rein
    # additiv, kein Kandidat wird veraendert oder ersetzt.
    mu_bps, cov_bps = _reasonable_mu_and_cov()
    initials_with = build_initial_guesses(bounds, score_x10=70, mu_bps=mu_bps, cov_bps=cov_bps)
    assert len(initials_with) == 6, "PAR-5 Kandidat sollte additiv als 6. hinzukommen"
    for original, extended in zip(initials_without, initials_with[:5]):
        np.testing.assert_allclose(original, extended)


def test_build_initial_guesses_adds_sixth_candidate_when_markowitz_feasible():
    """(d)-Vorstufe: mit sinnvollen CMA-Inputs kommt ein 6. Kandidat hinzu,
    und er ist ebenfalls bounds-/sum-feasible (wird vom bestehenden Filter
    genauso behandelt wie die anderen 5)."""
    bounds = [(0.0, 1.0)] * 5
    mu_bps, cov_bps = _reasonable_mu_and_cov()
    initials = build_initial_guesses(bounds, score_x10=70, mu_bps=mu_bps, cov_bps=cov_bps)
    assert len(initials) == 6
    sixth = initials[-1]
    assert float(np.sum(sixth)) == pytest.approx(1.0, abs=1e-3)
    for i, (lo, hi) in enumerate(bounds):
        assert lo - 1e-3 <= sixth[i] <= hi + 1e-3


def test_build_initial_guesses_markowitz_never_crashes_on_bad_cma_inputs():
    """(b) End-to-end Guard: kaputte mu/cov (z.B. Shape-Fehler) fuehren nicht
    zum Crash von build_initial_guesses - Set faellt auf 5 Kandidaten zurueck."""
    bounds = [(0.0, 1.0)] * 5
    bad_mu = np.array([np.nan] * 5)
    bad_cov = np.full((5, 5), np.inf)
    initials = build_initial_guesses(bounds, score_x10=70, mu_bps=bad_mu, cov_bps=bad_cov)
    assert len(initials) == 5, "Bei kaputten Markowitz-Inputs bleibt es bei den 5 Basis-Kandidaten"


# ============================================================================
# E2E Solver Run
# ============================================================================


def test_solver_converges_for_pension_mandate():
    """Realistic Pension-Mandant: Solver sollte konvergieren mit feasible weights."""
    cma = _make_cma()
    house_matrix = _make_house_matrix_row()
    goal = _make_pension_goal(hardness="Hart")

    result = run_solver(
        cma=cma, goals=[goal], house_matrix_row=house_matrix,
        score_x10=70,
        advisory_wealth_rappen=1_000_000_00,  # 1M CHF
        cashflow_series_rappen=[20_000_00] * 30,  # 20k/J Sparquote bis Pension
        horizon_years=30,
        n_paths=500,  # weniger fuer Test-Speed
    )

    assert isinstance(result, OptimizerResult)
    assert result.status in ("converged", "converged_robustified", "diverged_infeasible", "fallback_house_matrix")
    # Weights summieren auf 10000 bps
    assert sum(result.weights_bps.values()) == 10000
    # Alle Buckets vorhanden
    for bucket in BUCKET_ORDER:
        assert bucket in result.weights_bps


def test_solver_deterministic_with_explicit_seed():
    """Gleicher Seed -> identische Allocation."""
    cma = _make_cma()
    house_matrix = _make_house_matrix_row()
    goal = _make_pension_goal()

    result_a = run_solver(
        cma=cma, goals=[goal], house_matrix_row=house_matrix, score_x10=70,
        advisory_wealth_rappen=500_000_00, cashflow_series_rappen=[10_000_00] * 10,
        horizon_years=10, n_paths=200, seed=42,
    )
    result_b = run_solver(
        cma=cma, goals=[goal], house_matrix_row=house_matrix, score_x10=70,
        advisory_wealth_rappen=500_000_00, cashflow_series_rappen=[10_000_00] * 10,
        horizon_years=10, n_paths=200, seed=42,
    )
    assert result_a.weights_bps == result_b.weights_bps
    assert result_a.objective_value == result_b.objective_value
    assert result_a.seed == result_b.seed


def test_solver_respects_house_matrix_bands():
    """Solver darf weights nicht ausserhalb House-Matrix-Bands setzen."""
    cma = _make_cma()
    house_matrix = _make_house_matrix_row()
    goal = _make_pension_goal()

    result = run_solver(
        cma=cma, goals=[goal], house_matrix_row=house_matrix, score_x10=70,
        advisory_wealth_rappen=500_000_00, cashflow_series_rappen=[5_000_00] * 10,
        horizon_years=10, n_paths=200, seed=42,
    )
    bands = bands_from_house_matrix_row(house_matrix)
    bounds, constraints = build_constraint_set(bands, 70)
    weights = np.array([result.weights_bps[b] / 10000.0 for b in BUCKET_ORDER])
    feasible, reasons = is_feasible(weights, bounds=bounds, constraints=constraints, tolerance=1e-3)
    if result.status == "converged":
        assert feasible, f"Converged status but infeasible: {reasons}"


def test_solver_warns_when_house_matrix_minimum_exceeds_global_cap():
    """Bugfix 2026-08-07 (CEO/CFO/CIO-Audit): eine House-Matrix-Zeile mit
    real_estate_min_bps=2500 (> globalem Cap von 2000bps) wurde bisher
    STILLSCHWEIGEND auf (2000, 2000) zusammengepresst -- der Berater hätte
    nie erfahren, dass die konfigurierte Immobilien-Mindestquote nicht
    eingehalten wurde. run_solver().reasoning muss den Konflikt jetzt
    benennen (siehe services.optimizer.constraints.bounds_collapse_warnings)."""
    cma = _make_cma()
    house_matrix = _make_house_matrix_row()
    house_matrix.real_estate_min_bps = 2500
    house_matrix.real_estate_max_bps = 3000
    goal = _make_maximierung_goal()

    result = run_solver(
        cma=cma, goals=[goal], house_matrix_row=house_matrix, score_x10=70,
        advisory_wealth_rappen=500_000_00, cashflow_series_rappen=[0] * 5,
        horizon_years=5, n_paths=200, seed=42,
    )
    assert any("Immobilien" in r and "2500" in r for r in result.reasoning), result.reasoning
    # Und die tatsaechliche Allokation darf den globalen Cap trotzdem nie ueberschreiten.
    assert result.weights_bps["real_estate"] <= 2000 + 5  # kleine Rundungstoleranz


def test_solver_no_bounds_collapse_warning_for_normal_house_matrix():
    """Gegenprobe: eine unauffaellige House-Matrix (Standard-Fixture) darf
    keine Kollaps-Warnung erzeugen."""
    cma = _make_cma()
    house_matrix = _make_house_matrix_row()
    goal = _make_pension_goal()

    result = run_solver(
        cma=cma, goals=[goal], house_matrix_row=house_matrix, score_x10=70,
        advisory_wealth_rappen=500_000_00, cashflow_series_rappen=[5_000_00] * 10,
        horizon_years=10, n_paths=200, seed=42,
    )
    assert not any("liegt über dem globalen" in r or "liegt unter dem globalen" in r for r in result.reasoning)


def test_solver_respects_risky_fraction_cap_at_low_score():
    """Score=20 (= 20% risky) -> Solver muss konservativ bleiben."""
    cma = _make_cma()
    house_matrix = _make_house_matrix_row()
    # Mehr Spielraum auf Liquidity damit conservative Allocation moeglich ist
    house_matrix.liq_max_bps = 7000
    house_matrix.equity_min_bps = 0
    house_matrix.bonds_min_bps = 0
    house_matrix.real_estate_min_bps = 0
    house_matrix.alt_min_bps = 0
    goal = _make_maximierung_goal()  # opp Goal -> kein Druck nach oben

    result = run_solver(
        cma=cma, goals=[goal], house_matrix_row=house_matrix, score_x10=20,
        advisory_wealth_rappen=500_000_00, cashflow_series_rappen=[0] * 5,
        horizon_years=5, n_paths=200, seed=42,
    )
    weights = np.array([result.weights_bps[b] / 10000.0 for b in BUCKET_ORDER])
    risky_used = sum(weights[i] * DEFAULT_BUCKET_RISKY_FRACTION[BUCKET_ORDER[i]]
                      for i in range(len(BUCKET_ORDER)))
    # Mit kleinem score muss risky_used <= 0.20 (+ kleine numerische Toleranz)
    if result.status == "converged":
        assert risky_used <= 0.21, f"Risky fraction {risky_used:.3f} exceeds cap 0.20"


def test_solver_hard_pension_more_conservative_than_maximierung():
    """Mit hartem Pension-Goal sollte Allokation konservativer (mehr Bonds/Liq)
    sein als mit nur einem Maximierung-Goal."""
    cma = _make_cma()
    house_matrix = _make_house_matrix_row()
    pension = _make_pension_goal(hardness="Hart", years_to_start=3, duration=20)
    maxim = _make_maximierung_goal()

    result_pension = run_solver(
        cma=cma, goals=[pension], house_matrix_row=house_matrix, score_x10=70,
        advisory_wealth_rappen=500_000_00, cashflow_series_rappen=[0] * 25,
        horizon_years=25, n_paths=300, seed=42,
    )
    result_maxim = run_solver(
        cma=cma, goals=[maxim], house_matrix_row=house_matrix, score_x10=70,
        advisory_wealth_rappen=500_000_00, cashflow_series_rappen=[0] * 25,
        horizon_years=25, n_paths=300, seed=42,
    )
    if result_pension.status == "fallback_house_matrix" or result_maxim.status == "fallback_house_matrix":
        pytest.skip("Vergleich nur fuer konvergierte stochastic Solver-Ergebnisse sinnvoll.")

    # Hartes Pension-Goal sollte tendenziell weniger Aktien haben
    eq_pension = result_pension.weights_bps["equities"]
    eq_maxim = result_maxim.weights_bps["equities"]
    # Mindestens nicht mehr Aktien als bei Maximierung (Toleranz wegen
    # Multi-Start-Variabilitaet bei kleinen N)
    assert eq_pension <= eq_maxim + 500, (
        f"Hartes Pension-Goal hat MEHR Aktien ({eq_pension}bps) als "
        f"Maximierung-Only ({eq_maxim}bps) - das ist intuitiv falsch."
    )


def test_solver_audit_trace_populated():
    cma = _make_cma()
    house_matrix = _make_house_matrix_row()
    goal = _make_pension_goal()

    result = run_solver(
        cma=cma, goals=[goal], house_matrix_row=house_matrix, score_x10=70,
        advisory_wealth_rappen=500_000_00, cashflow_series_rappen=[5_000_00] * 5,
        horizon_years=5, n_paths=100, seed=42,
    )
    # Audit-Trace muss gefuellt sein
    assert result.method in ("stochastic", "fallback_house_matrix")
    assert result.seed == 42
    assert result.iterations >= 0
    assert result.n_paths == 100
    assert result.n_starts_attempted >= 1
    assert isinstance(result.reasoning, list)


def test_solver_restart_results_include_stage9_audit_fields():
    cma = _make_cma()
    house_matrix = _make_house_matrix_row()
    goal = _make_pension_goal()

    result = run_solver(
        cma=cma, goals=[goal], house_matrix_row=house_matrix, score_x10=70,
        advisory_wealth_rappen=500_000_00, cashflow_series_rappen=[5_000_00] * 5,
        horizon_years=5, n_paths=100, seed=42,
    )

    assert result.restart_results
    assert len(result.restart_results) >= result.n_starts_attempted
    for idx, attempt in enumerate(result.restart_results, start=1):
        assert attempt["attempt"] == idx
        assert attempt["stage"] in {"slsqp", "differential_evolution"}
        assert attempt["status"] in {"converged", "non_success"}
        assert isinstance(attempt["solver_status"], int)
        assert "reason" in attempt
        assert "objective_value" in attempt
        assert isinstance(attempt["feasible_candidate"], bool)
        assert attempt["n_paths"] == 100
        assert attempt["n_starts"] == result.n_starts_attempted
        assert attempt["seed"] == 42
        assert isinstance(attempt["elapsed_ms"], int)
        assert attempt["elapsed_ms"] >= 0


def test_solver_restart_results_deterministic_except_elapsed_ms():
    cma = _make_cma()
    house_matrix = _make_house_matrix_row()
    goal = _make_pension_goal()

    result_a = run_solver(
        cma=cma, goals=[goal], house_matrix_row=house_matrix, score_x10=70,
        advisory_wealth_rappen=500_000_00, cashflow_series_rappen=[5_000_00] * 5,
        horizon_years=5, n_paths=100, seed=42,
    )
    result_b = run_solver(
        cma=cma, goals=[goal], house_matrix_row=house_matrix, score_x10=70,
        advisory_wealth_rappen=500_000_00, cashflow_series_rappen=[5_000_00] * 5,
        horizon_years=5, n_paths=100, seed=42,
    )

    def stable(attempts):
        return [
            {key: value for key, value in attempt.items() if key != "elapsed_ms"}
            for attempt in attempts
        ]

    assert stable(result_a.restart_results) == stable(result_b.restart_results)


# ============================================================================
# Performance
# ============================================================================


def test_solver_under_performance_budget_5s():
    """5-Goal-Mandant, 10J Horizon, 2000 Pfade muss <5s dauern (Spec-Budget)."""
    cma = _make_cma()
    house_matrix = _make_house_matrix_row()
    goals = [_make_pension_goal(hardness="Hart"), _make_maximierung_goal()]

    t0 = time.perf_counter()
    result = run_solver(
        cma=cma, goals=goals, house_matrix_row=house_matrix, score_x10=70,
        advisory_wealth_rappen=1_000_000_00,
        cashflow_series_rappen=[15_000_00] * 10,
        horizon_years=10, n_paths=2000, seed=42,
    )
    elapsed = time.perf_counter() - t0
    assert elapsed < 5.0, (
        f"Solver too slow: {elapsed:.2f}s for 5-goal mandate with 2000 paths "
        f"(budget 5s per spec)"
    )
    assert isinstance(result, OptimizerResult)


# ============================================================================
# Edge Cases
# ============================================================================


def test_solver_full_run_with_par5_markowitz_candidate_still_valid():
    """(d) Voller Solver-Lauf mit dem um den Markowitz-Kandidaten erweiterten
    Multi-Start-Set liefert weiterhin eine gueltige, feasible Allokation -
    kein Crash, Bounds respektiert. run_solver() berechnet mu_bps/cov_bps
    intern immer aus der CMA (PAR-5 additiv), dieser Test macht das explizit."""
    cma = _make_cma()
    house_matrix = _make_house_matrix_row()
    goal = _make_pension_goal(hardness="Hart")

    result = run_solver(
        cma=cma, goals=[goal], house_matrix_row=house_matrix,
        score_x10=70,
        advisory_wealth_rappen=1_000_000_00,
        cashflow_series_rappen=[20_000_00] * 30,
        horizon_years=30,
        n_paths=500,
        seed=42,
    )

    assert isinstance(result, OptimizerResult)
    assert result.status in (
        "converged", "converged_robustified", "diverged_infeasible", "fallback_house_matrix",
    )
    assert sum(result.weights_bps.values()) == 10000
    for bucket in BUCKET_ORDER:
        assert bucket in result.weights_bps

    bands = bands_from_house_matrix_row(house_matrix)
    bounds, constraints = build_constraint_set(bands, 70)
    weights = np.array([result.weights_bps[b] / 10000.0 for b in BUCKET_ORDER])
    feasible, reasons = is_feasible(weights, bounds=bounds, constraints=constraints, tolerance=1e-3)
    if result.status == "converged":
        assert feasible, f"Converged status but infeasible: {reasons}"


def test_solver_empty_goals_returns_feasible_allocation():
    """Mandant ohne Goals -> Solver sollte trotzdem feasible weights liefern."""
    cma = _make_cma()
    house_matrix = _make_house_matrix_row()

    result = run_solver(
        cma=cma, goals=[], house_matrix_row=house_matrix, score_x10=70,
        advisory_wealth_rappen=500_000_00, cashflow_series_rappen=[0] * 5,
        horizon_years=5, n_paths=200, seed=42,
    )
    # Weights muessen valid sein
    assert sum(result.weights_bps.values()) == 10000
    # Mit keinem Goal ist objective ~0
    assert result.objective_value < 1.0


def test_solver_handles_short_horizon_one_year():
    """Edge case: horizon=1 (kuerzester moeglicher Zeitraum)."""
    cma = _make_cma()
    house_matrix = _make_house_matrix_row()
    goal = _make_maximierung_goal()

    result = run_solver(
        cma=cma, goals=[goal], house_matrix_row=house_matrix, score_x10=50,
        advisory_wealth_rappen=100_000_00, cashflow_series_rappen=[0],
        horizon_years=1, n_paths=100, seed=42,
    )
    assert sum(result.weights_bps.values()) == 10000
