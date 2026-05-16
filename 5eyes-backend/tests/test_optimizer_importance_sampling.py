"""Unit-Tests fuer Mean-Shift Importance Sampling.

Verifiziert die mathematischen Garantien von importance_sampling.py:
1. Likelihood-Weights summieren asymptotisch zu N (unverzerrt)
2. Weighted Mean-Estimator ist unverzerrt (innerhalb MC-Fehler)
3. Variance-Reduction im Tail (signifikant)
4. Deterministisch bei fixed seed
"""
from __future__ import annotations

import numpy as np
import pytest

from services.optimizer.importance_sampling import (
    DEFAULT_TAIL_SHIFT_STRENGTH,
    apply_mean_shift,
    build_shift_vector,
    compute_likelihood_weights,
    make_default_weights,
)


def test_default_weights_are_ones():
    w = make_default_weights(1000)
    assert w.shape == (1000,)
    assert np.allclose(w, 1.0)


def test_build_shift_vector_default_targets_equity_buckets():
    shift = build_shift_vector(5)
    assert shift.shape == (5,)
    assert shift[0] == 0.0  # liquidity
    assert shift[1] == 0.0  # bonds
    assert shift[2] == -DEFAULT_TAIL_SHIFT_STRENGTH  # equity_ch
    assert shift[3] == -DEFAULT_TAIL_SHIFT_STRENGTH  # equity_intl
    assert shift[4] == 0.0  # alternatives


def test_build_shift_vector_custom_indices():
    shift = build_shift_vector(5, target_indices=[0, 4], strength=0.3)
    assert shift[0] == -0.3
    assert shift[4] == -0.3
    assert shift[1] == shift[2] == shift[3] == 0.0


def test_build_shift_vector_handles_oob_indices():
    """OOB-Indices werden ignoriert, kein Crash."""
    shift = build_shift_vector(3, target_indices=[1, 5, 99])
    assert shift.shape == (3,)
    assert shift[1] < 0.0
    assert shift[0] == 0.0
    assert shift[2] == 0.0


def test_apply_mean_shift_shifts_correctly():
    rng = np.random.default_rng(42)
    z = rng.standard_normal(size=(100, 3, 5))
    shift = build_shift_vector(5)
    z_shifted = apply_mean_shift(z, shift)
    # Differenz ueber Path/Year-Achse mittelt sich zum Shift-Vector
    diff_mean = (z_shifted - z).mean(axis=(0, 1))
    assert np.allclose(diff_mean, shift)


def test_likelihood_weights_sum_to_n_asymptotically():
    """E[w] = 1.0 unter der proposal-distribution N(-mu, I).
    Bei n_paths gross sollte sum(w)/n -> 1.0 konvergieren."""
    rng = np.random.default_rng(123)
    n_paths = 50_000
    horizon = 5
    n_buckets = 5
    shift = build_shift_vector(n_buckets)
    # Sample aus proposal-distribution N(-mu, I) → wir generieren Z aus N(0,I)
    # und shiften, das gibt uns Stichproben aus N(shift, I) = N(-|shift_neg|, I).
    z_proposal = rng.standard_normal(size=(n_paths, horizon, n_buckets)) + shift
    weights = compute_likelihood_weights(z_proposal, shift)
    mean_weight = weights.mean()
    # MC-Fehler O(1/sqrt(n)) → 50k samples → ~0.005 Toleranz
    assert abs(mean_weight - 1.0) < 0.05, f"E[w] = {mean_weight:.4f}, sollte ~1.0"


def test_weighted_estimator_unbiased_for_symmetric_function():
    """E_target[f(Z)] = E_proposal[f(Z) * w(Z)] fuer alle integrable f.

    Test mit f(Z) = Z_0 (linear in erstem Bucket). Original-Mean = 0.
    Geshiftete Mean = shift[0] aber gewichteter Estimator sollte 0 sein.
    """
    rng = np.random.default_rng(456)
    n_paths = 50_000
    horizon = 1
    n_buckets = 5
    shift = build_shift_vector(n_buckets)  # shift[2] = shift[3] = -0.5

    z_proposal = rng.standard_normal(size=(n_paths, horizon, n_buckets)) + shift
    weights = compute_likelihood_weights(z_proposal, shift)

    # Test fuer Bucket 2 (equity_ch, geshifted) — unweighted mean ist shift[2] = -0.5
    raw_mean_b2 = z_proposal[:, 0, 2].mean()
    assert abs(raw_mean_b2 - shift[2]) < 0.02, "unweighted mean sollte shift sein"

    # Weighted mean sollte ~0 sein (Target-Distribution)
    weighted_mean_b2 = (z_proposal[:, 0, 2] * weights).sum() / weights.sum()
    assert abs(weighted_mean_b2 - 0.0) < 0.1, f"weighted mean = {weighted_mean_b2:.4f}, sollte ~0"


def test_zero_shift_gives_trivial_weights():
    """Wenn shift = 0, sind alle Likelihood-Weights = 1.0."""
    rng = np.random.default_rng(789)
    z = rng.standard_normal(size=(100, 3, 5))
    zero_shift = np.zeros(5)
    weights = compute_likelihood_weights(z, zero_shift)
    assert np.allclose(weights, 1.0)


def test_deterministic_with_fixed_seed():
    """Gleicher Seed + gleicher Shift → identische Weights."""
    rng1 = np.random.default_rng(42)
    z1 = rng1.standard_normal(size=(50, 3, 5))
    rng2 = np.random.default_rng(42)
    z2 = rng2.standard_normal(size=(50, 3, 5))
    shift = build_shift_vector(5)
    w1 = compute_likelihood_weights(z1, shift)
    w2 = compute_likelihood_weights(z2, shift)
    assert np.array_equal(w1, w2)


def test_importance_sampling_reduces_tail_variance():
    """Schluesseltest: bei Tail-Statistik (z.B. P(Z[bucket] < -2)) muss IS
    eine niedrigere Stichprobenvarianz liefern als Standard-MC."""
    rng = np.random.default_rng(2024)
    n_paths = 2_000
    n_buckets = 5
    bucket_idx = 2  # equity_ch
    shift = build_shift_vector(n_buckets)  # shift bucket 2 nach negativ

    # Indikator-Fkt: 1 wenn Z[bucket] < -2 (Tail-Event)
    threshold = -2.0

    # Repeat 100x um Estimator-Varianz zu messen
    standard_estimates = []
    is_estimates = []
    for trial in range(100):
        # Standard-MC: N(0, I)
        z_std = rng.standard_normal(size=(n_paths, 1, n_buckets))
        std_est = float((z_std[:, 0, bucket_idx] < threshold).mean())
        standard_estimates.append(std_est)

        # IS: N(-|shift|, I) + reweighting
        z_is = rng.standard_normal(size=(n_paths, 1, n_buckets)) + shift
        weights = compute_likelihood_weights(z_is, shift)
        indicator = (z_is[:, 0, bucket_idx] < threshold).astype(np.float64)
        is_est = float((indicator * weights).mean())
        is_estimates.append(is_est)

    var_std = float(np.var(standard_estimates))
    var_is = float(np.var(is_estimates))
    # IS sollte mindestens 2x niedriger Variance haben (typisch 5-10x bei tail-shift=0.5)
    assert var_is < var_std / 2.0, (
        f"IS-Var {var_is:.6f} sollte deutlich kleiner als Std-Var {var_std:.6f} sein"
    )
    # Mean-Estimates muessen ungefaehr gleich sein (beides unverzerrt)
    mean_std = float(np.mean(standard_estimates))
    mean_is = float(np.mean(is_estimates))
    assert abs(mean_std - mean_is) < max(0.01, 3 * np.sqrt(var_std + var_is))


def test_is_flag_default_false():
    """Feature-Flag default OFF: Phase 5 ist opt-in."""
    from services.optimizer.importance_sampling import is_importance_sampling_enabled
    # Ohne env-var sollte False kommen
    assert is_importance_sampling_enabled() is False
