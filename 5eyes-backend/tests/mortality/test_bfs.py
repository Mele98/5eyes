"""BFSMortalityTable Tests — Plausibilitaet der Werte + Methoden."""
from __future__ import annotations

import numpy as np
import pytest

from services.mortality.bfs import BFS_2020_2022, BFSMortalityTable


def test_max_age_119():
    assert BFS_2020_2022.max_age == 119


def test_q_119_is_one():
    """Schluss-Tafel: q(119) = 1.0 fuer beide Geschlechter."""
    assert BFS_2020_2022.qx(119, "M") == 1.0
    assert BFS_2020_2022.qx(119, "F") == 1.0


def test_q_negative_age_raises():
    with pytest.raises(ValueError, match="age"):
        BFS_2020_2022.qx(-1, "M")


def test_q_invalid_sex_raises():
    with pytest.raises(ValueError, match="sex"):
        BFS_2020_2022.qx(50, "X")


def test_q_above_max_age_returns_one():
    assert BFS_2020_2022.qx(150, "M") == 1.0


def test_q_increases_with_age_above_30():
    """Mortalitaet steigt monoton ab Alter 30."""
    qs_m = [BFS_2020_2022.qx(age, "M") for age in range(30, 110)]
    for i in range(1, len(qs_m)):
        assert qs_m[i] >= qs_m[i - 1], f"q decreases at age {30+i}: {qs_m[i-1]} → {qs_m[i]}"


def test_female_lower_mortality_than_male_at_65():
    """Frauen leben statistisch laenger — q(65) sollte tiefer sein."""
    qm = BFS_2020_2022.qx(65, "M")
    qf = BFS_2020_2022.qx(65, "F")
    assert qf < qm


def test_life_expectancy_at_birth_male():
    """CH Maenner Lebenserwartung bei Geburt: ~81-82 Jahre (BFS 2020-2022)."""
    e0 = BFS_2020_2022.life_expectancy(0, "M")
    assert 79.0 < e0 < 84.0, f"e(0,M)={e0:.2f} sollte ~81.6 sein"


def test_life_expectancy_at_birth_female():
    """CH Frauen Lebenserwartung bei Geburt: ~85 Jahre."""
    e0 = BFS_2020_2022.life_expectancy(0, "F")
    assert 83.0 < e0 < 87.0, f"e(0,F)={e0:.2f} sollte ~85.4 sein"


def test_life_expectancy_at_65_male():
    """CH Maenner bei 65: noch ~19.5 Jahre Lebenserwartung → bis ~84.5."""
    e65 = BFS_2020_2022.life_expectancy(65, "M")
    assert 18.0 < e65 < 21.0, f"e(65,M)={e65:.2f} sollte ~19.5 sein"


def test_life_expectancy_at_65_female():
    """CH Frauen bei 65: noch ~22 Jahre."""
    e65 = BFS_2020_2022.life_expectancy(65, "F")
    assert 20.5 < e65 < 23.5, f"e(65,F)={e65:.2f} sollte ~22 sein"


def test_life_expectancy_at_80_decreases():
    """Lebenserwartung sinkt mit Alter — e(80) < e(65)."""
    assert BFS_2020_2022.life_expectancy(80, "M") < BFS_2020_2022.life_expectancy(65, "M")
    assert BFS_2020_2022.life_expectancy(80, "F") < BFS_2020_2022.life_expectancy(65, "F")


def test_survival_curve_starts_at_one():
    """S(0) = 1.0 (definitionsgemaess noch lebend bei t=0)."""
    s = BFS_2020_2022.survival_curve(65, "M")
    assert s[0] == 1.0


def test_survival_curve_ends_near_zero():
    """S(max_age - current_age) ist sehr klein (alle gestorben)."""
    s = BFS_2020_2022.survival_curve(65, "M")
    assert s[-1] < 0.001


def test_survival_curve_monotonic_decreasing():
    """S(t) ist monoton fallend."""
    s = BFS_2020_2022.survival_curve(65, "M")
    diffs = np.diff(s)
    assert (diffs <= 0).all(), "survival should be non-increasing"


def test_survival_curve_shape():
    """Shape = max_age - current_age + 1."""
    s = BFS_2020_2022.survival_curve(50, "M")
    assert s.shape == (BFS_2020_2022.max_age - 50 + 1,)


def test_survival_curve_invalid_current_age_raises():
    with pytest.raises(ValueError):
        BFS_2020_2022.survival_curve(-1, "M")
    with pytest.raises(ValueError):
        BFS_2020_2022.survival_curve(200, "M")


def test_survival_curve_invalid_sex_raises():
    with pytest.raises(ValueError):
        BFS_2020_2022.survival_curve(50, "Z")


def test_default_instance_matches_class_default():
    """BFS_2020_2022 Default-Instanz hat Standard-Werte."""
    fresh = BFSMortalityTable()
    assert fresh.name == BFS_2020_2022.name
    assert fresh.max_age == BFS_2020_2022.max_age


def test_q_at_infant_mortality_higher_than_at_10():
    """q(0) > q(10) (Saeuglingssterblichkeit)."""
    assert BFS_2020_2022.qx(0, "M") > BFS_2020_2022.qx(10, "M")
    assert BFS_2020_2022.qx(0, "F") > BFS_2020_2022.qx(10, "F")


def test_male_higher_mortality_than_female_at_80():
    """Maennliche Hochaltrige sterben schneller als weibliche."""
    qm = BFS_2020_2022.qx(80, "M")
    qf = BFS_2020_2022.qx(80, "F")
    assert qm > qf


def test_120_values_per_sex():
    """Q-Arrays haben genau 120 Werte (Alter 0..119)."""
    assert len(BFS_2020_2022._q_male) == 120
    assert len(BFS_2020_2022._q_female) == 120
