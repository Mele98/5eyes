"""
Tests für:
1. _is_valid_cholesky / _identity_cholesky / _build_cholesky_from_cma
   (portfolio_engine.py) — Fallback-Kaskade bei nicht-positiv-definiter Matrix
2. Horizon-Matrix Default 0 für unbekannte Labels (risk_scoring.py)
"""
import json
import math
from types import SimpleNamespace

import pytest

from services.portfolio_engine import (
    _cholesky,
    _identity_cholesky,
    _is_valid_cholesky,
    _build_cholesky_from_cma,
)
from services.risk_scoring import (
    compute_scores,
    HORIZON_CAPACITY_MATRIX,
    HORIZON_YEARS,
)


# ── _is_valid_cholesky ────────────────────────────────────────────────────────

def test_is_valid_cholesky_identity():
    L = _identity_cholesky(3)
    assert _is_valid_cholesky(L) is True


def test_is_valid_cholesky_valid_2x2():
    # [[1,0],[0.5, sqrt(0.75)]] — decomp of [[1,0.5],[0.5,1]]
    L = [[1.0, 0.0], [0.5, math.sqrt(0.75)]]
    assert _is_valid_cholesky(L) is True


def test_is_valid_cholesky_singular_matrix():
    # Singular 2×2: [[1,1],[1,1]] — not positive-definite, Cholesky produces zero diagonal
    singular = [[1.0, 1.0], [1.0, 1.0]]
    L = _cholesky(singular)
    # Second diagonal entry should be 0 (or near 0)
    assert not _is_valid_cholesky(L)


def test_is_valid_cholesky_zero_diagonal_entry():
    L = [[1.0, 0.0], [0.0, 0.0]]  # manually degenerate
    assert not _is_valid_cholesky(L)


# ── _identity_cholesky ────────────────────────────────────────────────────────

def test_identity_cholesky_shape():
    for n in (1, 3, 5):
        L = _identity_cholesky(n)
        assert len(L) == n
        assert all(len(row) == n for row in L)


def test_identity_cholesky_values():
    L = _identity_cholesky(4)
    for i in range(4):
        for j in range(4):
            expected = 1.0 if i == j else 0.0
            assert L[i][j] == expected


# ── _build_cholesky_from_cma ──────────────────────────────────────────────────

def _make_cma(correlation_matrix_json=None):
    """Minimal CMA stub with only the field _build_cholesky_from_cma needs."""
    return SimpleNamespace(correlation_matrix_json=correlation_matrix_json)


def test_build_cholesky_no_custom_matrix_returns_valid():
    """Without a custom matrix, should use Swiss-market defaults — must be valid."""
    cma = _make_cma(correlation_matrix_json=None)
    L = _build_cholesky_from_cma(cma)
    assert _is_valid_cholesky(L)
    assert len(L) == 5


def test_build_cholesky_valid_custom_matrix_used():
    """A proper positive-definite 5×5 identity custom matrix should be accepted."""
    identity_5 = [[1.0 if i == j else 0.0 for j in range(5)] for i in range(5)]
    cma = _make_cma(correlation_matrix_json=json.dumps(identity_5))
    L = _build_cholesky_from_cma(cma)
    assert _is_valid_cholesky(L)
    # Identity matrix decomposes to itself
    for i in range(5):
        assert abs(L[i][i] - 1.0) < 1e-9


def test_build_cholesky_singular_custom_falls_back_to_default(caplog):
    """When custom matrix is not positive-definite, falls back to Swiss-market defaults."""
    import logging
    # All-ones 5×5: rank 1, not positive-definite
    singular = [[1.0] * 5 for _ in range(5)]
    cma = _make_cma(correlation_matrix_json=json.dumps(singular))
    with caplog.at_level(logging.WARNING, logger="services.portfolio_engine"):
        L = _build_cholesky_from_cma(cma)
    assert _is_valid_cholesky(L), "Fallback to default must produce a valid decomposition"
    assert len(L) == 5
    assert any("not positive-definite" in r.message for r in caplog.records)


def test_build_cholesky_invalid_json_falls_back_to_default():
    """Malformed JSON in correlation_matrix_json → silently use default matrix."""
    cma = _make_cma(correlation_matrix_json="not-valid-json{{{")
    L = _build_cholesky_from_cma(cma)
    assert _is_valid_cholesky(L)


def test_build_cholesky_wrong_size_json_ignored():
    """A 3×3 custom matrix (wrong size) must be ignored — default used instead."""
    small = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    cma = _make_cma(correlation_matrix_json=json.dumps(small))
    L = _build_cholesky_from_cma(cma)
    assert _is_valid_cholesky(L)
    assert len(L) == 5


# ── Horizon-matrix default = 0 ────────────────────────────────────────────────

def test_unknown_horizon_label_defaults_to_zero_capacity():
    """An unrecognised label falls back to horizon_years=1 → all (1,band) = 0."""
    result = compute_scores(
        q_income_points=4,
        q_obligations_points=4,
        q_savings_points=12,
        q_wealth_points=12,
        investment_horizon_label="UNBEKANNT_LABEL_XYZ",
        q_investment_goal_points=4,
        q_risk_preference_points=4,
        q_risk_behavior_points=4,
    )
    assert result.risk_capacity_score_x10 == 0
    assert result.final_score_x10 == 0


def test_horizon_matrix_default_value_is_conservative():
    """Direct dict lookup on a key not in the matrix must return 0, not 10."""
    # (3, 3) is NOT in the matrix (only 1,2,4,6,9,15 are valid years)
    assert HORIZON_CAPACITY_MATRIX.get((3, 3), 0) == 0
    assert HORIZON_CAPACITY_MATRIX.get((99, 5), 0) == 0


def test_all_known_horizon_labels_have_matrix_entries():
    """Every label in HORIZON_YEARS resolves to a row that exists in the matrix."""
    for label, years in HORIZON_YEARS.items():
        for band in range(1, 6):
            assert (years, band) in HORIZON_CAPACITY_MATRIX, (
                f"Label '{label}' maps to horizon_years={years}, "
                f"but ({years}, {band}) is missing from HORIZON_CAPACITY_MATRIX"
            )
