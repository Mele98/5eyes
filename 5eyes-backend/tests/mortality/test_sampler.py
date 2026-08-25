"""Sampler-Tests: Inverse-CDF-Sampling Plausibilitaet + Determinismus."""
from __future__ import annotations

import numpy as np
import pytest

from services.mortality.bfs import BFS_2020_2022
from services.mortality.sampler import (
    death_year_index_from_age,
    sample_age_at_death,
)


def test_sample_shape():
    samples = sample_age_at_death(
        n_paths=1000, current_age=65, sex="M", table=BFS_2020_2022, seed=42
    )
    assert samples.shape == (1000,)


def test_sample_dtype_integer():
    samples = sample_age_at_death(
        n_paths=100, current_age=65, sex="M", table=BFS_2020_2022, seed=1
    )
    assert np.issubdtype(samples.dtype, np.integer)


def test_sample_ages_all_above_current_age():
    """Niemand stirbt vor dem aktuellen Alter."""
    samples = sample_age_at_death(
        n_paths=1000, current_age=65, sex="M", table=BFS_2020_2022, seed=1
    )
    assert (samples > 65).all()


def test_sample_ages_within_max_age():
    samples = sample_age_at_death(
        n_paths=1000, current_age=65, sex="M", table=BFS_2020_2022, seed=1
    )
    assert (samples <= BFS_2020_2022.max_age + 1).all()


def test_sample_mean_matches_life_expectancy_male_65():
    """10k Samples: Mittel der Sterbe-Alter sollte life_expectancy(65,M) + 65 ergeben."""
    samples = sample_age_at_death(
        n_paths=10000, current_age=65, sex="M", table=BFS_2020_2022, seed=42
    )
    expected_mean = 65 + BFS_2020_2022.life_expectancy(65, "M")
    actual_mean = samples.mean()
    assert abs(actual_mean - expected_mean) < 0.5, (
        f"actual mean={actual_mean:.2f}, expected ~{expected_mean:.2f}"
    )


def test_sample_mean_matches_life_expectancy_female_65():
    samples = sample_age_at_death(
        n_paths=10000, current_age=65, sex="F", table=BFS_2020_2022, seed=42
    )
    expected_mean = 65 + BFS_2020_2022.life_expectancy(65, "F")
    actual_mean = samples.mean()
    assert abs(actual_mean - expected_mean) < 0.5


def test_female_samples_higher_mean_than_male():
    """Frauen leben statistisch laenger."""
    samples_m = sample_age_at_death(
        n_paths=10000, current_age=65, sex="M", table=BFS_2020_2022, seed=42
    )
    samples_f = sample_age_at_death(
        n_paths=10000, current_age=65, sex="F", table=BFS_2020_2022, seed=42
    )
    assert samples_f.mean() > samples_m.mean()


def test_sample_with_seed_deterministic():
    """Gleicher Seed → gleiche Samples."""
    a = sample_age_at_death(n_paths=100, current_age=65, sex="M", table=BFS_2020_2022, seed=7)
    b = sample_age_at_death(n_paths=100, current_age=65, sex="M", table=BFS_2020_2022, seed=7)
    np.testing.assert_array_equal(a, b)


def test_sample_different_seed_differs():
    """Verschiedene Seeds → unterschiedliche Samples."""
    a = sample_age_at_death(n_paths=100, current_age=65, sex="M", table=BFS_2020_2022, seed=1)
    b = sample_age_at_death(n_paths=100, current_age=65, sex="M", table=BFS_2020_2022, seed=2)
    assert not np.array_equal(a, b)


def test_sample_p10_and_p90_plausible_male_65():
    """P10 + P90 von Maennern bei 65: ~72 + ~95."""
    samples = sample_age_at_death(
        n_paths=20000, current_age=65, sex="M", table=BFS_2020_2022, seed=42
    )
    p10, p50, p90 = np.percentile(samples, [10, 50, 90])
    # Realistische Bereiche basierend auf BFS-Statistik
    assert 68 < p10 < 76, f"p10={p10}"
    assert 82 < p50 < 88, f"p50={p50}"
    assert 91 < p90 < 100, f"p90={p90}"


def test_sample_zero_paths_raises():
    with pytest.raises(ValueError, match="n_paths"):
        sample_age_at_death(n_paths=0, current_age=65, sex="M", table=BFS_2020_2022)


def test_sample_at_age_zero_mean_close_to_birth_life_expectancy():
    """Sample bei current_age=0 → Mittel sollte ~e(0) sein."""
    samples = sample_age_at_death(
        n_paths=10000, current_age=0, sex="M", table=BFS_2020_2022, seed=42
    )
    expected_mean = BFS_2020_2022.life_expectancy(0, "M")
    actual_mean = samples.mean()
    assert abs(actual_mean - expected_mean) < 1.0


def test_sample_at_high_age_short_lifespan():
    """Sample bei current_age=95 → die meisten sterben bald (mittlere Restdauer < 5)."""
    samples = sample_age_at_death(
        n_paths=10000, current_age=95, sex="M", table=BFS_2020_2022, seed=42
    )
    mean_remaining = samples.mean() - 95
    assert mean_remaining < 6.0


def test_death_year_index_clamps_to_horizon():
    """Wenn Person ueber Horizont hinaus lebt, Index = horizon."""
    death_ages = np.array([95, 100, 105], dtype=np.int32)
    indices = death_year_index_from_age(death_ages, current_age=65, horizon_years=20)
    # Alle Sterbe-Alter > 85 → muss auf 20 geclamped werden
    assert indices.tolist() == [20, 20, 20]


def test_death_year_index_within_horizon():
    """Sterbe-Alter innerhalb Horizont → korrekter Index."""
    death_ages = np.array([70, 80, 84], dtype=np.int32)
    indices = death_year_index_from_age(death_ages, current_age=65, horizon_years=25)
    assert indices.tolist() == [5, 15, 19]


def test_death_year_index_minimum_one():
    """Wenn Sterbe-Alter == current_age, Index = 1 (minimal)."""
    death_ages = np.array([65], dtype=np.int32)
    indices = death_year_index_from_age(death_ages, current_age=65, horizon_years=30)
    assert indices[0] == 1
