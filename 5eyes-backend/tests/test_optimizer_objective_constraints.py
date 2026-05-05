"""Tests fuer services/optimizer/objective.py und constraints.py.

Verifiziert:
- Shortfall pro Goal-Typ matcht erwarteter Logik
- Hardness-Multiplier (10/1/0.2) wirkt korrekt in Aggregation
- Volatility-Objective berechnet Var(end_wealth)
- HouseMatrixBands extrahiert aus DB-Row
- Globale Caps (RE 20%, Alts 10%, Liq 2%) ueberschreiben House-Matrix-Bands
- Risky-Fraction-Constraint korrekt
- is_feasible erkennt alle Verletzungen
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.optimizer.constraints import (
    DEFAULT_BUCKET_RISKY_FRACTION,
    HouseMatrixBands,
    MAX_ALTERNATIVES,
    MAX_REAL_ESTATE,
    MIN_LIQUIDITY,
    bands_from_house_matrix_row,
    build_bounds,
    build_constraint_set,
    build_risky_fraction_constraint,
    build_sum_to_one_constraint,
    is_feasible,
)
from services.optimizer.goal_liabilities import GoalLiability
from services.optimizer.objective import (
    HARDNESS_WEIGHT,
    combined_objective_two_phase,
    shortfall_objective,
    shortfall_squared_per_path,
    volatility_objective,
)
from services.optimizer.scenario_engine import BUCKET_ORDER, N_BUCKETS


# ============================================================================
# Helpers
# ============================================================================


def _make_liab(
    *,
    goal_id: str = "g1",
    target_kind: str = "wealth_at_t",
    target_amount_rappen: int = 1_000_000_00,
    target_year_index: int = 5,
    hardness: str = "primaer",
    weight_bps: int = 1000,
    horizon_years: int = 10,
) -> GoalLiability:
    return GoalLiability(
        goal_id=goal_id,
        label=f"Test {goal_id}",
        goal_type="Vermoegensziel",
        target_kind=target_kind,
        target_amount_rappen=target_amount_rappen,
        target_year_index=target_year_index,
        liability_path_rappen=[0] * horizon_years,
        hardness_key=hardness,
        weight_bps=weight_bps,
    )


# ============================================================================
# shortfall_squared_per_path
# ============================================================================


def test_shortfall_wealth_at_t_zero_when_target_met():
    liab = _make_liab(target_kind="wealth_at_t", target_amount_rappen=500_000_00, target_year_index=5)
    # 3 paths, alle erreichen >= 500k in Jahr 5
    wealth = np.array([
        [100_000_00] * 5 + [500_000_00] + [600_000_00] * 5,
        [100_000_00] * 5 + [550_000_00] + [600_000_00] * 5,
        [100_000_00] * 5 + [600_000_00] + [600_000_00] * 5,
    ], dtype=np.float64)
    out = shortfall_squared_per_path(liab, wealth, initial_wealth_rappen=100_000_00, horizon_years=10)
    assert np.allclose(out, 0)


def test_shortfall_wealth_at_t_positive_when_target_missed():
    liab = _make_liab(target_kind="wealth_at_t", target_amount_rappen=500_000_00, target_year_index=5)
    wealth = np.array([
        [100_000_00] * 5 + [400_000_00] + [400_000_00] * 5,  # missed by 100k
        [100_000_00] * 5 + [500_000_00] + [500_000_00] * 5,  # exact
        [100_000_00] * 5 + [600_000_00] + [600_000_00] * 5,  # over
    ], dtype=np.float64)
    out = shortfall_squared_per_path(liab, wealth, initial_wealth_rappen=100_000_00, horizon_years=10)
    expected_first = 100_000_00 ** 2  # squared shortfall
    assert out[0] == pytest.approx(expected_first)
    assert out[1] == 0
    assert out[2] == 0


def test_shortfall_outflow_stream_uses_end_wealth():
    """outflow_stream: Lebensluecke = abs(end_wealth) wenn negativ."""
    liab = _make_liab(target_kind="outflow_stream", target_amount_rappen=240_000_00, target_year_index=5)
    wealth = np.array([
        [100_000_00] * 5 + [-50_000_00] + [-50_000_00] * 5,  # Luecke 50k am Ende
        [100_000_00] * 11,                                     # alle erfuellt
        [100_000_00] * 10 + [-100_000_00],                     # Luecke 100k am Ende
    ], dtype=np.float64)
    out = shortfall_squared_per_path(liab, wealth, initial_wealth_rappen=100_000_00, horizon_years=10)
    assert out[0] == pytest.approx(50_000_00 ** 2)
    assert out[1] == 0
    assert out[2] == pytest.approx(100_000_00 ** 2)


def test_shortfall_return_rate_compares_annualized_bps():
    """Return-Goal: target_bps - actual_bps shortfall."""
    liab = _make_liab(target_kind="return_rate", target_amount_rappen=500, target_year_index=10)  # 5% Ziel
    # Path 1: ratio 1.5 ueber 10 Jahre -> ~4.14% annualized -> shortfall ~86 bps
    # Path 2: ratio 2.0 ueber 10 Jahre -> ~7.18% annualized -> shortfall 0
    # Path 3: end_wealth negativ -> shortfall = full 500 bps
    wealth = np.array([
        [100_000_00] * 10 + [150_000_00],
        [100_000_00] * 10 + [200_000_00],
        [100_000_00] * 10 + [-10_000_00],
    ], dtype=np.float64)
    out = shortfall_squared_per_path(liab, wealth, initial_wealth_rappen=100_000_00, horizon_years=10)
    assert out[1] == 0  # ueber dem Ziel
    assert out[0] > 0  # leicht unter Ziel
    # Path 3: shortfall = 500 - (-10000) = 10500 bps -> sqrt(out) = 10500
    assert np.sqrt(out[2]) == pytest.approx(10500, abs=10)


def test_shortfall_maximize_always_zero():
    liab = _make_liab(target_kind="maximize")
    wealth = np.array([[100, 200, 300, 400, 500, 600, 700, 800, 900, 1000, 1100]], dtype=np.float64)
    out = shortfall_squared_per_path(liab, wealth, initial_wealth_rappen=100, horizon_years=10)
    assert np.allclose(out, 0)


def test_shortfall_unknown_kind_returns_zero():
    liab = _make_liab(target_kind="weltraum_goal")
    wealth = np.zeros((3, 11))
    out = shortfall_squared_per_path(liab, wealth, initial_wealth_rappen=100, horizon_years=10)
    assert np.allclose(out, 0)


# ============================================================================
# shortfall_objective Aggregation
# ============================================================================


def test_objective_sums_hardness_weighted_shortfalls():
    """Goal hart vs goal opportunistisch: hart wird 50x staerker bestraft."""
    hart = _make_liab(goal_id="h", hardness="hart", weight_bps=10000,
                       target_kind="wealth_at_t", target_amount_rappen=1_000_000,
                       target_year_index=5)
    opp = _make_liab(goal_id="o", hardness="opportunistisch", weight_bps=10000,
                      target_kind="wealth_at_t", target_amount_rappen=1_000_000,
                      target_year_index=5)
    # Beide Goals werden um 1000 verfehlt (Wealth=999000 in Jahr 5)
    wealth = np.full((10, 11), 999_000, dtype=np.float64)
    obj_hart = shortfall_objective([hart], wealth, initial_wealth_rappen=500_000, horizon_years=10)
    obj_opp = shortfall_objective([opp], wealth, initial_wealth_rappen=500_000, horizon_years=10)
    # hart soll 50x staerker bestraft sein (10 / 0.2 = 50)
    assert obj_hart == pytest.approx(50 * obj_opp)


def test_objective_zero_when_all_goals_met():
    liab = _make_liab(target_kind="wealth_at_t", target_amount_rappen=500_000, target_year_index=3)
    wealth = np.full((5, 11), 600_000, dtype=np.float64)  # alle ueber Ziel
    obj = shortfall_objective([liab], wealth, initial_wealth_rappen=100_000, horizon_years=10)
    assert obj == 0.0


def test_objective_empty_liabilities_returns_zero():
    wealth = np.full((5, 11), 100_000, dtype=np.float64)
    assert shortfall_objective([], wealth, initial_wealth_rappen=100_000, horizon_years=10) == 0.0


def test_objective_proportional_to_squared_shortfall():
    liab = _make_liab(hardness="primaer", weight_bps=10000,
                       target_kind="wealth_at_t", target_amount_rappen=1_000_000,
                       target_year_index=5)
    # Path 1: shortfall 1000^2 = 1M
    # Path 2: shortfall 2000^2 = 4M  -> 4x
    wealth_a = np.full((1, 11), 999_000, dtype=np.float64)
    wealth_b = np.full((1, 11), 998_000, dtype=np.float64)
    obj_a = shortfall_objective([liab], wealth_a, initial_wealth_rappen=500_000, horizon_years=10)
    obj_b = shortfall_objective([liab], wealth_b, initial_wealth_rappen=500_000, horizon_years=10)
    assert obj_b == pytest.approx(4 * obj_a)


# ============================================================================
# Volatility-Objective
# ============================================================================


def test_volatility_objective_zero_for_constant_paths():
    wealth = np.full((10, 11), 500_000, dtype=np.float64)
    assert volatility_objective(wealth) == 0.0


def test_volatility_objective_matches_numpy_var():
    wealth = np.array([
        [0] * 10 + [100],
        [0] * 10 + [200],
        [0] * 10 + [300],
    ], dtype=np.float64)
    expected = np.var([100, 200, 300])
    assert volatility_objective(wealth) == pytest.approx(expected)


def test_combined_objective_includes_both_terms():
    liab = _make_liab(hardness="primaer", weight_bps=10000,
                       target_kind="wealth_at_t", target_amount_rappen=1_000_000_00,
                       target_year_index=5)
    wealth = np.array([
        [100_000_00] * 11,
        [200_000_00] * 11,
        [300_000_00] * 11,
    ], dtype=np.float64)
    primary = shortfall_objective([liab], wealth, initial_wealth_rappen=100_000_00, horizon_years=10)
    vol = volatility_objective(wealth)
    combined = combined_objective_two_phase(
        [liab], wealth, initial_wealth_rappen=100_000_00, horizon_years=10,
        primary_weight=2.0, volatility_weight=0.5,
    )
    assert combined == pytest.approx(2.0 * primary + 0.5 * vol)


# ============================================================================
# HARDNESS_WEIGHT Konsistenz mit Spec
# ============================================================================


def test_hardness_weights_match_owner_decision_od_1():
    """OD-1 vom User bestaetigt: hart=10, primaer=1, opportunistisch=0.2."""
    assert HARDNESS_WEIGHT["hart"] == 10.0
    assert HARDNESS_WEIGHT["primaer"] == 1.0
    assert HARDNESS_WEIGHT["opportunistisch"] == 0.2


# ============================================================================
# HouseMatrixBands extraction
# ============================================================================


def test_bands_from_house_matrix_row_extracts_correctly():
    row = SimpleNamespace(
        equity_min_bps=4000, equity_max_bps=7000,
        bonds_min_bps=2000, bonds_max_bps=5000,
        real_estate_min_bps=0, real_estate_max_bps=2000,
        alt_min_bps=0, alt_max_bps=1000,
        liq_min_bps=200, liq_max_bps=2000,
    )
    bands = bands_from_house_matrix_row(row)
    assert bands.equities == (0.40, 0.70)
    assert bands.bonds == (0.20, 0.50)
    assert bands.real_estate == (0.0, 0.20)
    assert bands.alternatives == (0.0, 0.10)
    assert bands.liquidity == (0.02, 0.20)


# ============================================================================
# build_bounds: globale Caps ueberschreiben House-Matrix
# ============================================================================


def test_build_bounds_re_cap_applied_to_more_aggressive_house_matrix():
    """Wenn House-Matrix RE max=30%, globaler Cap 20% wins."""
    bands = HouseMatrixBands(
        equities=(0.4, 0.7), bonds=(0.2, 0.5),
        real_estate=(0.0, 0.30),  # House-Matrix erlaubt 30%
        alternatives=(0.0, 0.05), liquidity=(0.02, 0.10),
    )
    bounds = build_bounds(bands)
    re_idx = BUCKET_ORDER.index("real_estate")
    assert bounds[re_idx] == (0.0, MAX_REAL_ESTATE)


def test_build_bounds_alts_cap_applied():
    bands = HouseMatrixBands(
        equities=(0.0, 1.0), bonds=(0.0, 1.0),
        real_estate=(0.0, 0.20),
        alternatives=(0.0, 0.30),  # 30% wuerde Cap 10% verletzen
        liquidity=(0.02, 1.0),
    )
    bounds = build_bounds(bands)
    alt_idx = BUCKET_ORDER.index("alternatives")
    assert bounds[alt_idx] == (0.0, MAX_ALTERNATIVES)


def test_build_bounds_liquidity_floor_applied():
    """Wenn House-Matrix Liq min=0%, globaler Floor 2% wins."""
    bands = HouseMatrixBands(
        equities=(0.4, 0.7), bonds=(0.2, 0.5),
        real_estate=(0.0, 0.10), alternatives=(0.0, 0.05),
        liquidity=(0.0, 0.20),  # 0% min wuerde Floor 2% verletzen
    )
    bounds = build_bounds(bands)
    liq_idx = BUCKET_ORDER.index("liquidity")
    assert bounds[liq_idx] == (MIN_LIQUIDITY, 0.20)


def test_build_bounds_lo_clamped_to_hi_when_inverted():
    """Bei kaputter House-Matrix lo>hi: lo wird auf hi geclamped, kein Crash."""
    bands = HouseMatrixBands(
        equities=(0.8, 0.6),  # lo>hi (kaputt)
        bonds=(0.0, 0.5), real_estate=(0.0, 0.10),
        alternatives=(0.0, 0.05), liquidity=(0.02, 0.20),
    )
    bounds = build_bounds(bands)
    eq_idx = BUCKET_ORDER.index("equities")
    lo, hi = bounds[eq_idx]
    assert lo <= hi


# ============================================================================
# Sum-to-one + Risky-Fraction Constraints
# ============================================================================


def test_sum_to_one_constraint_zero_at_unit_sum():
    cons = build_sum_to_one_constraint()
    w = np.array([0.5, 0.3, 0.05, 0.05, 0.10])
    assert cons["fun"](w) == pytest.approx(0.0)


def test_sum_to_one_constraint_violates_when_sum_off():
    cons = build_sum_to_one_constraint()
    w = np.array([0.5, 0.3, 0.10, 0.05, 0.10])  # sum = 1.05
    assert cons["fun"](w) == pytest.approx(0.05)


def test_risky_fraction_constraint_feasible_at_low_score():
    """score=70 (max 70% risky), w mit 50% equities (rf=0.8) + 30% bonds (rf=0.25)
    = 0.50*0.8 + 0.30*0.25 + 0*... = 0.475. Cap 0.70 -> feasible (cap-actual = 0.225)."""
    cons = build_risky_fraction_constraint(score_x10=70)
    w = np.array([0.5, 0.3, 0.05, 0.05, 0.10])
    val = cons["fun"](w)
    assert val > 0  # feasible (ineq: f(w) >= 0)


def test_risky_fraction_constraint_violates_at_high_risky():
    """score=30 (nur 30% risky erlaubt), w mit 70% equities -> Verletzung."""
    cons = build_risky_fraction_constraint(score_x10=30)
    w = np.array([0.7, 0.1, 0.0, 0.0, 0.2])
    val = cons["fun"](w)
    # Equities 0.7 * 0.8 = 0.56 risky, Cap 0.30 -> verletzt um -0.26
    assert val < 0


# ============================================================================
# is_feasible
# ============================================================================


def test_is_feasible_passes_for_valid_allocation():
    bands = HouseMatrixBands(
        equities=(0.4, 0.7), bonds=(0.2, 0.5),
        real_estate=(0.0, 0.20), alternatives=(0.0, 0.10),
        liquidity=(0.02, 0.20),
    )
    bounds, constraints = build_constraint_set(bands, score_x10=70)
    w = np.array([0.5, 0.3, 0.05, 0.05, 0.10])
    feasible, reasons = is_feasible(w, bounds=bounds, constraints=constraints)
    assert feasible
    assert reasons == []


def test_is_feasible_catches_band_violation():
    bands = HouseMatrixBands(
        equities=(0.4, 0.7), bonds=(0.2, 0.5),
        real_estate=(0.0, 0.20), alternatives=(0.0, 0.10),
        liquidity=(0.02, 0.20),
    )
    bounds, constraints = build_constraint_set(bands, score_x10=70)
    w = np.array([0.8, 0.1, 0.0, 0.0, 0.10])  # Equities ueber max
    feasible, reasons = is_feasible(w, bounds=bounds, constraints=constraints)
    assert not feasible
    assert any("equities above max" in r for r in reasons)


def test_is_feasible_catches_sum_violation():
    bands = HouseMatrixBands(
        equities=(0.4, 0.7), bonds=(0.2, 0.5),
        real_estate=(0.0, 0.20), alternatives=(0.0, 0.10),
        liquidity=(0.02, 0.20),
    )
    bounds, constraints = build_constraint_set(bands, score_x10=70)
    w = np.array([0.5, 0.3, 0.10, 0.05, 0.10])  # sum = 1.05
    feasible, reasons = is_feasible(w, bounds=bounds, constraints=constraints)
    assert not feasible
    assert any("sum-to-one" in r for r in reasons)


def test_is_feasible_catches_risky_fraction_violation():
    bands = HouseMatrixBands(
        equities=(0.0, 1.0), bonds=(0.0, 1.0),
        real_estate=(0.0, 0.20), alternatives=(0.0, 0.10),
        liquidity=(0.02, 0.20),
    )
    bounds, constraints = build_constraint_set(bands, score_x10=20)  # nur 20% risky
    w = np.array([0.7, 0.1, 0.0, 0.0, 0.20])  # zu viel equities
    feasible, reasons = is_feasible(w, bounds=bounds, constraints=constraints)
    assert not feasible
    assert any("ineq constraint" in r for r in reasons)


def test_default_risky_fractions_match_3eyes_slide_17():
    """OD-6: Werte aus 3eyes-Slide 17."""
    assert DEFAULT_BUCKET_RISKY_FRACTION["equities"] == 0.80
    assert DEFAULT_BUCKET_RISKY_FRACTION["bonds"] == 0.25
    assert DEFAULT_BUCKET_RISKY_FRACTION["real_estate"] == 0.60
    assert DEFAULT_BUCKET_RISKY_FRACTION["alternatives"] == 0.60
    assert DEFAULT_BUCKET_RISKY_FRACTION["liquidity"] == 0.0
