"""Sprint U-34 (Roadmap-Punkt 34, 2026-06-04): BFS-Mortality Stale-Audit
+ Plausibilitaets-Tests.

Pre-U-34
--------
services/mortality/bfs.py hatte BFS-2020-2022-Period hartcoded, aber
keinen Stale-Detection-Helper. Berater hatte keine Sichtbarkeit ob die
Tafel veraltet ist (BFS publiziert alle ~3 Jahre eine neue Period-Tafel).

Post-U-34
---------
- BFS_VINTAGE_START_YEAR / BFS_VINTAGE_END_YEAR / BFS_STALE_THRESHOLD_YEARS
- is_stale_for_year(ref_year) -> bool
- BFSMortalityTable.is_stale(ref_year) Convenience
- Plausibilitaets-Tests fuer Life-Expectancy gegen BFS-Werte
- Update-Strategie im Modul-Docstring
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.mortality.bfs import (  # noqa: E402
    BFS_2020_2022,
    BFS_STALE_THRESHOLD_YEARS,
    BFS_VINTAGE_END_YEAR,
    BFS_VINTAGE_START_YEAR,
    BFSMortalityTable,
    is_stale_for_year,
)


# ---------------------------------------------------------------------------
# Vintage-Konstanten
# ---------------------------------------------------------------------------

def test_vintage_constants_2020_2022():
    assert BFS_VINTAGE_START_YEAR == 2020
    assert BFS_VINTAGE_END_YEAR == 2022


def test_stale_threshold_5_years():
    """BFS-Update-Rhythmus ~3 Jahre + 2 Jahre Puffer."""
    assert BFS_STALE_THRESHOLD_YEARS == 5


def test_table_carries_vintage():
    """Tafel selbst muss Vintage-Info tragen fuer Audit-Trail."""
    assert BFS_2020_2022.vintage_start_year == 2020
    assert BFS_2020_2022.vintage_end_year == 2022


# ---------------------------------------------------------------------------
# is_stale_for_year — Stale-Logik
# ---------------------------------------------------------------------------

def test_not_stale_within_threshold():
    """2023 = 1 Jahr nach Vintage-Ende, nicht stale."""
    assert is_stale_for_year(2023) is False
    assert is_stale_for_year(2025) is False
    assert is_stale_for_year(2027) is False  # genau 5 Jahre = noch nicht stale


def test_stale_after_threshold():
    """2028 = 6 Jahre nach Vintage-Ende -> stale."""
    assert is_stale_for_year(2028) is True
    assert is_stale_for_year(2030) is True


def test_not_stale_for_reference_before_vintage():
    """Pre-vintage Reference (z.B. historischer Audit) -> nicht stale."""
    assert is_stale_for_year(2020) is False
    assert is_stale_for_year(2010) is False


def test_not_stale_at_vintage_end():
    assert is_stale_for_year(2022) is False


def test_stale_with_custom_threshold():
    """Mit threshold=2 ist 2025 schon stale (3 Jahre Differenz)."""
    assert is_stale_for_year(2025, threshold_years=2) is True
    assert is_stale_for_year(2024, threshold_years=2) is False


def test_stale_with_custom_vintage_year():
    """Wenn neue Tafel publiziert wird (z.B. 2024), kann threshold neu gesetzt."""
    assert is_stale_for_year(2030, vintage_end_year=2024) is True
    assert is_stale_for_year(2028, vintage_end_year=2024) is False


def test_table_is_stale_convenience_method():
    """BFSMortalityTable.is_stale() Wrapper."""
    assert BFS_2020_2022.is_stale(2030) is True
    assert BFS_2020_2022.is_stale(2025) is False


# ---------------------------------------------------------------------------
# Plausibilitaets-Tests fuer Life-Expectancy
# (siehe Docstring: M~81.6, F~85.4 @ Geburt; M~19.5, F~22.0 @ 65)
# ---------------------------------------------------------------------------

def test_life_expectancy_male_at_birth_plausible():
    """LE Maenner bei Geburt ~81-82 (BFS-Spec)."""
    le = BFS_2020_2022.life_expectancy(0, "M")
    assert 80.0 <= le <= 83.0, f"LE Maenner Geburt {le:.2f} ausserhalb [80, 83]"


def test_life_expectancy_female_at_birth_plausible():
    """LE Frauen bei Geburt ~85 (BFS-Spec)."""
    le = BFS_2020_2022.life_expectancy(0, "F")
    assert 84.0 <= le <= 87.0, f"LE Frauen Geburt {le:.2f} ausserhalb [84, 87]"


def test_life_expectancy_male_at_65_plausible():
    """Remaining Years Maenner @ 65 ~19.5 + 65 = 84.5 LE-Total."""
    remaining = BFS_2020_2022.life_expectancy(65, "M")
    assert 18.0 <= remaining <= 21.0, f"Remaining @65 M {remaining:.2f}"


def test_life_expectancy_female_at_65_plausible():
    """Remaining Years Frauen @ 65 ~22.0."""
    remaining = BFS_2020_2022.life_expectancy(65, "F")
    assert 20.0 <= remaining <= 24.0, f"Remaining @65 F {remaining:.2f}"


def test_female_outlives_male_at_every_age():
    """Gender-Gap: Frauen leben laenger als Maenner in jedem
    Standard-Alter (5, 30, 65, 80)."""
    for age in (5, 30, 65, 80):
        m = BFS_2020_2022.life_expectancy(age, "M")
        f = BFS_2020_2022.life_expectancy(age, "F")
        assert f > m, f"At age {age}: F={f:.2f} <= M={m:.2f}"


# ---------------------------------------------------------------------------
# qx-Properties (Sanity gegen Daten-Korruption)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("sex", ["M", "F"])
@pytest.mark.parametrize("age", [0, 25, 50, 75, 100, 118])
def test_qx_in_valid_probability_range(age, sex):
    """q(x) muss in [0, 1] sein."""
    q = BFS_2020_2022.qx(age, sex)
    assert 0.0 <= q <= 1.0, f"q({age}, {sex}) = {q} outside [0, 1]"


def test_qx_terminal_age_is_one():
    """Bei max_age = 119: q = 1.0 (Schluss-Tafel)."""
    assert BFS_2020_2022.qx(119, "M") == 1.0
    assert BFS_2020_2022.qx(119, "F") == 1.0


def test_qx_monotonically_increases_in_adult_age():
    """Ab Alter 30 muss q(x) monoton steigen (Gompertz-typisch)."""
    prev_q_m = BFS_2020_2022.qx(30, "M")
    prev_q_f = BFS_2020_2022.qx(30, "F")
    for age in range(31, 100):
        q_m = BFS_2020_2022.qx(age, "M")
        q_f = BFS_2020_2022.qx(age, "F")
        assert q_m >= prev_q_m, f"q monotonicity break M @ age {age}"
        assert q_f >= prev_q_f, f"q monotonicity break F @ age {age}"
        prev_q_m, prev_q_f = q_m, q_f


def test_qx_raises_for_invalid_sex():
    with pytest.raises(ValueError, match="sex"):
        BFS_2020_2022.qx(40, "X")


def test_qx_raises_for_negative_age():
    with pytest.raises(ValueError, match="age"):
        BFS_2020_2022.qx(-1, "M")


# ---------------------------------------------------------------------------
# Survival-Curve Properties
# ---------------------------------------------------------------------------

def test_survival_curve_starts_at_one():
    s = BFS_2020_2022.survival_curve(40, "M")
    assert s[0] == 1.0


def test_survival_curve_monotonically_decreasing():
    s = BFS_2020_2022.survival_curve(40, "F")
    for i in range(1, len(s)):
        assert s[i] <= s[i - 1], f"Survival increases at idx {i}"


def test_survival_curve_at_max_age_terminal():
    """S(t) am Ende ist sehr klein (kein 1.0)."""
    s = BFS_2020_2022.survival_curve(40, "M")
    assert s[-1] < 0.01, f"S terminal = {s[-1]} zu hoch"
