"""Sprint 4 Phase 3: Integration build_optimizer_context + Mortality.

Verifiziert, dass die Mortalitaets-Felder durch die ganze Kette wandern:
Mandate → build_optimizer_context → OptimizerContext.mortality_death_year_index_per_path
→ evaluate_weights → simulate_wealth_paths

Was hier NICHT getestet wird: full SLSQP-Solver-Run (zu teuer fuer Unit-Test).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest


class _MockCMA:
    """Minimal CMA Stub fuer build_optimizer_context."""
    id = "test-cma"
    correlation_matrix_json = ""
    # Returns + Vols pro Bucket
    equity_ch_return_bps = 600
    equity_intl_return_bps = 700
    bonds_chf_ig_return_bps = 200
    bonds_fx_hedged_return_bps = 250
    real_estate_ch_return_bps = 400
    alternatives_gold_return_bps = 300
    liquidity_return_bps = 50
    equity_ch_vol_bps = 1500
    equity_intl_vol_bps = 1700
    bonds_chf_ig_vol_bps = 400
    bonds_fx_hedged_vol_bps = 500
    real_estate_ch_vol_bps = 800
    alternatives_gold_vol_bps = 1200
    liquidity_vol_bps = 50
    # Skew/Kurt nicht gesetzt = 0


class _MockHouseMatrixRow:
    """House-Matrix mit weiten Bandbreiten."""
    equities_min_bps = 0
    equities_target_bps = 4000
    equities_max_bps = 10000
    bonds_min_bps = 0
    bonds_target_bps = 3000
    bonds_max_bps = 10000
    real_estate_min_bps = 0
    real_estate_target_bps = 1500
    real_estate_max_bps = 10000
    alternatives_min_bps = 0
    alternatives_target_bps = 1000
    alternatives_max_bps = 10000
    liquidity_min_bps = 0
    liquidity_target_bps = 500
    liquidity_max_bps = 10000


def test_no_mortality_params_returns_none_field():
    """build_optimizer_context ohne Mortality-Params → death_indices=None."""
    from services.optimizer.solver import build_optimizer_context

    ctx = build_optimizer_context(
        cma=_MockCMA(),
        goals=[],
        house_matrix_row=_MockHouseMatrixRow(),
        score_x10=50,
        advisory_wealth_rappen=1_000_000_00,
        cashflow_series_rappen=[0] * 10,
        horizon_years=10,
        n_paths=100,
        seed=42,
    )
    assert ctx.mortality_death_year_index_per_path is None


def test_mortality_off_returns_none_field():
    """use_mortality_simulation=False → death_indices=None auch wenn andere Felder gesetzt."""
    from services.optimizer.solver import build_optimizer_context

    ctx = build_optimizer_context(
        cma=_MockCMA(),
        goals=[],
        house_matrix_row=_MockHouseMatrixRow(),
        score_x10=50,
        advisory_wealth_rappen=1_000_000_00,
        cashflow_series_rappen=[0] * 10,
        horizon_years=10,
        n_paths=100,
        seed=42,
        client_birth_year=1965,
        client_sex="M",
        use_mortality_simulation=False,
    )
    assert ctx.mortality_death_year_index_per_path is None


def test_mortality_active_produces_death_indices_array():
    """Vollstaendige Mortality-Setup -> death_indices ist ndarray shape
    (n_paths,), seit Kontrollrunde 2026-09-19 deterministisch (fuer alle
    Pfade identisch), nicht mehr pro Pfad stochastisch gesampelt."""
    from services.optimizer.solver import build_optimizer_context

    ctx = build_optimizer_context(
        cma=_MockCMA(),
        goals=[],
        house_matrix_row=_MockHouseMatrixRow(),
        score_x10=50,
        advisory_wealth_rappen=1_000_000_00,
        cashflow_series_rappen=[0] * 20,
        horizon_years=20,
        n_paths=500,
        seed=42,
        client_birth_year=1960,  # ~65 Jahre alt 2026
        client_sex="M",
        use_mortality_simulation=True,
        mortality_fixed_offset_years=15,
    )
    assert ctx.mortality_death_year_index_per_path is not None
    assert ctx.mortality_death_year_index_per_path.shape == (500,)
    # Deterministisch: JEDER Pfad bekommt denselben Cutoff.
    assert (ctx.mortality_death_year_index_per_path == 15).all()


def test_mortality_offset_clipped_to_horizon():
    """Ein Offset > horizon_years wird auf den Horizont geklemmt (Person
    lebt ueber den simulierten Zeitraum hinaus -> kein Cutoff innerhalb)."""
    from services.optimizer.solver import build_optimizer_context

    ctx = build_optimizer_context(
        cma=_MockCMA(),
        goals=[],
        house_matrix_row=_MockHouseMatrixRow(),
        score_x10=50,
        advisory_wealth_rappen=1_000_000_00,
        cashflow_series_rappen=[0] * 10,
        horizon_years=10,
        n_paths=50,
        seed=42,
        client_birth_year=1980,
        client_sex="F",
        use_mortality_simulation=True,
        mortality_fixed_offset_years=999,
    )
    assert (ctx.mortality_death_year_index_per_path == 10).all()


def test_mortality_active_without_fixed_offset_yields_no_cutoff():
    """use_mortality_simulation=True aber mortality_fixed_offset_years=None
    (z.B. weil der Aufrufer keinen Offset ermitteln konnte) -> konservativ
    kein Cutoff, NICHT stillschweigend ein geratener Wert."""
    from services.optimizer.solver import build_optimizer_context

    ctx = build_optimizer_context(
        cma=_MockCMA(),
        goals=[],
        house_matrix_row=_MockHouseMatrixRow(),
        score_x10=50,
        advisory_wealth_rappen=1_000_000_00,
        cashflow_series_rappen=[0] * 10,
        horizon_years=10,
        n_paths=50,
        seed=42,
        client_birth_year=1960,
        client_sex="M",
        use_mortality_simulation=True,
        mortality_fixed_offset_years=None,
    )
    assert ctx.mortality_death_year_index_per_path is None


def test_mortality_missing_sex_fails_closed():
    """Aktivierte Mortalitaet ohne Geschlecht ist unvollstaendiger Modellinput."""
    from services.optimizer.constraints import OptimizerInputError
    from services.optimizer.solver import build_optimizer_context

    with pytest.raises(OptimizerInputError, match="requires client_birth_year"):
        build_optimizer_context(
            cma=_MockCMA(),
            goals=[],
            house_matrix_row=_MockHouseMatrixRow(),
            score_x10=50,
            advisory_wealth_rappen=1_000_000_00,
            cashflow_series_rappen=[0] * 10,
            horizon_years=10,
            n_paths=100,
            seed=42,
            client_birth_year=1965,
            client_sex=None,
            use_mortality_simulation=True,
        )


def test_mortality_invalid_sex_fails_closed():
    """Aktivierte Mortalitaet akzeptiert ausschliesslich M/F."""
    from services.optimizer.constraints import OptimizerInputError
    from services.optimizer.solver import build_optimizer_context

    with pytest.raises(OptimizerInputError, match="requires client_birth_year"):
        build_optimizer_context(
            cma=_MockCMA(),
            goals=[],
            house_matrix_row=_MockHouseMatrixRow(),
            score_x10=50,
            advisory_wealth_rappen=1_000_000_00,
            cashflow_series_rappen=[0] * 10,
            horizon_years=10,
            n_paths=100,
            seed=42,
            client_birth_year=1965,
            client_sex="X",  # invalid
            use_mortality_simulation=True,
        )


# Hinweis (Kontrollrunde 2026-09-19): der fruehere Test hier ("ein defekter
# Sampler darf nicht unbemerkt Mortalitaet deaktivieren") pruefte build_
# optimizer_context's eigenes Sampling. build_optimizer_context sampelt seit
# dem Deterministik-Fix nicht mehr selbst -- das Ermitteln des Offsets (und
# dessen Fail-Closed-Verhalten bei einem Fehler) passiert jetzt VORGELAGERT
# in mandate_model_inputs.mortality_solver_kwargs_from_mandate. Siehe
# tests/mortality/test_mortality_solver_kwargs.py fuer den aequivalenten Fall.


def test_evaluate_weights_with_mortality_returns_different_terminal_wealth():
    """evaluate_weights mit Mortality-Context produziert anderes End-Wealth
    als ohne (weil cashflow zu 0 nach Tod fuehrt zu anderem Wealth-Pfad).
    Wir nutzen goals=[] und vergleichen terminal_wealth_p50.
    """
    from services.optimizer.solver import build_optimizer_context, evaluate_weights

    weights_bps = {
        "equities": 4000, "bonds": 3000, "real_estate": 1500,
        "alternatives": 1000, "liquidity": 500,
    }

    ctx_no_mort = build_optimizer_context(
        cma=_MockCMA(),
        goals=[],  # keine Goals — Liability ist trivial
        house_matrix_row=_MockHouseMatrixRow(),
        score_x10=50,
        advisory_wealth_rappen=1_000_000_00,
        cashflow_series_rappen=[-30_000_00] * 30,  # 30 Jahre Auszahlung
        horizon_years=30,
        n_paths=500,
        seed=42,
    )
    ctx_with_mort = build_optimizer_context(
        cma=_MockCMA(),
        goals=[],
        house_matrix_row=_MockHouseMatrixRow(),
        score_x10=50,
        advisory_wealth_rappen=1_000_000_00,
        cashflow_series_rappen=[-30_000_00] * 30,
        horizon_years=30,
        n_paths=500,
        seed=42,
        client_birth_year=1960,  # ~65 Jahre alt
        client_sex="M",
        use_mortality_simulation=True,
        mortality_fixed_offset_years=15,  # deterministischer Cutoff bei Jahr 15
    )

    eval_no = evaluate_weights(ctx_no_mort, weights_bps)
    eval_mort = evaluate_weights(ctx_with_mort, weights_bps)

    # End-Wealth muss sich unterscheiden:
    # Ohne Mortality: alle Pfade ziehen 30 Jahre lang -30k ab → niedriger
    # Mit Mortality: ALLE Pfade stoppen die Auszahlung einheitlich bei Jahr 15
    # (deterministisch, kein Pfad "stirbt zufaellig frueher/spaeter") → hoeher
    assert eval_no.terminal_wealth_p50_rappen != eval_mort.terminal_wealth_p50_rappen
    assert eval_mort.terminal_wealth_p50_rappen > eval_no.terminal_wealth_p50_rappen
