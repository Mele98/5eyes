"""Tests fuer services/optimizer/goal_liabilities.py.

Pro Goal-Typ einzelne Tests, plus Aggregation. Liability-Pfade muessen
konsistent zur Convention sein:
  liability_path_rappen[0] = Outflow im naechsten Jahr (Jahr 1)
  liability_path_rappen[T-1] = Outflow im Jahr T (= horizon_years)

Inflation greift nur wenn value_mode='real'. Hardness und Weight haben
sinnvolle Defaults.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy.orm import configure_mappers
from database import Base
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
configure_mappers()

from services.optimizer.goal_liabilities import (
    GoalLiability,
    aggregate_liability_path,
    goal_to_liability,
    goals_to_liabilities,
)


def _make_goal(
    *,
    goal_id: str = "g1",
    label: str = "Test",
    goal_type: str = "Vermoegensziel",
    target_amount_rappen: int | None = None,
    target_wealth_rappen: int | None = None,
    target_return_bps: int | None = None,
    horizon_years: int | None = None,
    target_date: str | None = None,
    start_date: str | None = None,
    is_ongoing: int = 0,
    frequency: str | None = None,
    hardness: str = "Primaer",
    rank: int = 2,
    weight_bps: int | None = None,
    value_mode: str = "nominal",
):
    """Mock-Goal als SimpleNamespace (kein DB-Objekt noetig)."""
    return SimpleNamespace(
        id=goal_id,
        label=label,
        goal_type=goal_type,
        target_amount_rappen=target_amount_rappen,
        target_wealth_rappen=target_wealth_rappen,
        target_return_bps=target_return_bps,
        horizon_years=horizon_years,
        target_date=target_date,
        start_date=start_date,
        is_ongoing=is_ongoing,
        frequency=frequency,
        hardness=hardness,
        rank=rank,
        weight_bps=weight_bps,
        value_mode=value_mode,
    )


# ============================================================================
# Renditeziel: kein Outflow, target ist bps
# ============================================================================


def test_renditeziel_returns_zero_path_and_bps_target():
    goal = _make_goal(goal_type="Renditeziel", target_return_bps=450, horizon_years=10)
    liab = goal_to_liability(goal, horizon_years=10)
    assert liab.target_kind == "return_rate"
    assert liab.target_amount_rappen == 450  # ist bps in diesem Feld
    assert liab.liability_path_rappen == [0] * 10
    assert liab.target_year_index == 10


def test_renditeziel_with_zero_target_clamped():
    goal = _make_goal(goal_type="Renditeziel", target_return_bps=None, horizon_years=5)
    liab = goal_to_liability(goal, horizon_years=5)
    assert liab.target_amount_rappen == 0


# ============================================================================
# Vermoegensziel / Kapitalerhalt: Wealth-Schwelle in Zieljahr
# ============================================================================


def test_vermoegensziel_nominal_no_inflation_applied():
    goal = _make_goal(
        goal_type="Vermoegensziel",
        target_wealth_rappen=1_000_000_00,
        horizon_years=10,
        value_mode="nominal",
    )
    liab = goal_to_liability(goal, horizon_years=10, inflation_series_bps=[200] * 10)
    assert liab.target_kind == "wealth_at_t"
    assert liab.target_amount_rappen == 1_000_000_00
    assert liab.liability_path_rappen == [0] * 10


def test_vermoegensziel_real_applies_compound_inflation():
    """value_mode='real' -> target wird mit kumulativer Inflation hochgerechnet."""
    goal = _make_goal(
        goal_type="Vermoegensziel",
        target_wealth_rappen=1_000_000_00,
        horizon_years=5,
        value_mode="real",
    )
    liab = goal_to_liability(goal, horizon_years=5, inflation_series_bps=[200] * 5)
    # Ziel: 1M heute -> 1M * 1.02^5 = 1'104'080.80 in 5 Jahren
    expected = int(round(1_000_000_00 * (1.02 ** 5)))
    assert liab.target_amount_rappen == pytest.approx(expected, abs=10)


def test_kapitalerhalt_uses_wealth_target():
    goal = _make_goal(
        goal_type="Kapitalerhalt",
        target_wealth_rappen=500_000_00,
        horizon_years=3,
    )
    liab = goal_to_liability(goal, horizon_years=3)
    assert liab.target_kind == "wealth_at_t"
    assert liab.target_amount_rappen == 500_000_00


def test_vermoegensziel_target_year_clamped_to_horizon():
    """Wenn horizon_years=10 aber goal.horizon_years=20 -> auf 10 geclamped."""
    goal = _make_goal(
        goal_type="Vermoegensziel",
        target_wealth_rappen=1_000_000_00,
        horizon_years=20,
    )
    liab = goal_to_liability(goal, horizon_years=10)
    assert liab.target_year_index == 10


# ============================================================================
# Einmalige_Ausgabe: Outflow in Zieljahr
# ============================================================================


def test_einmalige_ausgabe_places_outflow_in_correct_year():
    """Goal in 4 Jahren -> liability_path[3] = amount, alles andere 0."""
    today = date.today()
    target = (today + timedelta(days=365 * 4)).isoformat()
    goal = _make_goal(
        goal_type="Einmalige_Ausgabe",
        target_amount_rappen=100_000_00,
        target_date=target,
    )
    liab = goal_to_liability(goal, horizon_years=10)
    assert liab.target_kind == "cashflow_in_year"
    assert liab.target_amount_rappen == 100_000_00
    assert liab.target_year_index == 4
    expected_path = [0] * 10
    expected_path[3] = 100_000_00
    assert liab.liability_path_rappen == expected_path


def test_einmalige_ausgabe_real_value_mode_inflated():
    today = date.today()
    target = (today + timedelta(days=365 * 5)).isoformat()
    goal = _make_goal(
        goal_type="Einmalige_Ausgabe",
        target_amount_rappen=50_000_00,
        target_date=target,
        value_mode="real",
    )
    liab = goal_to_liability(goal, horizon_years=10, inflation_series_bps=[200] * 10)
    expected = int(round(50_000_00 * (1.02 ** 5)))
    assert liab.liability_path_rappen[4] == pytest.approx(expected, abs=10)
    assert liab.target_amount_rappen == pytest.approx(expected, abs=10)


def test_einmalige_ausgabe_beyond_horizon_clamped():
    """Goal in 15J aber horizon=10 -> auf horizon=10 geclamped."""
    today = date.today()
    target = (today + timedelta(days=365 * 15)).isoformat()
    goal = _make_goal(
        goal_type="Einmalige_Ausgabe",
        target_amount_rappen=100_000_00,
        target_date=target,
    )
    liab = goal_to_liability(goal, horizon_years=10)
    assert liab.target_year_index == 10
    assert liab.liability_path_rappen[9] == 100_000_00


# ============================================================================
# Wiederkehrende_Ausgabe / Pensionsausgabe: jaehrlich Outflow ab Start
# ============================================================================


def test_pensionsausgabe_yearly_outflow_for_duration():
    """Pension 36k/J ab Jahr 5 fuer 5 Jahre, horizon=15 -> Outflow Jahre 5-9."""
    today = date.today()
    start = (today + timedelta(days=365 * 5)).isoformat()
    end = (today + timedelta(days=365 * 9)).isoformat()
    goal = _make_goal(
        goal_type="Pensionsausgabe",
        target_amount_rappen=3_000_00,  # monatlich 3000 CHF
        frequency="monatlich",
        start_date=start,
        target_date=end,
    )
    liab = goal_to_liability(goal, horizon_years=15)
    assert liab.target_kind == "outflow_stream"
    assert liab.target_year_index == 5
    annual = 3_000_00 * 12  # 36'000 CHF
    # liability_path_rappen[4..8] (Jahr 5..9) sollten = annual sein
    for offset in range(5):
        assert liab.liability_path_rappen[4 + offset] == annual
    # Vor und nach den Jahren = 0
    for i in (0, 1, 2, 3, 9, 10, 14):
        assert liab.liability_path_rappen[i] == 0


def test_pensionsausgabe_real_compounds_inflation_per_year():
    """Pension mit value_mode='real' wird PRO JAHR mit kum. Inflation hochgerechnet."""
    today = date.today()
    start = (today + timedelta(days=365 * 3)).isoformat()
    end = (today + timedelta(days=365 * 5)).isoformat()
    goal = _make_goal(
        goal_type="Pensionsausgabe",
        target_amount_rappen=12_000_00,  # 12k jaehrlich
        frequency="jährlich",
        start_date=start,
        target_date=end,
        value_mode="real",
    )
    liab = goal_to_liability(goal, horizon_years=10, inflation_series_bps=[200] * 10)
    # Jahr 3: 12'000 * 1.02^3
    expected_y3 = int(round(12_000_00 * (1.02 ** 3)))
    expected_y4 = int(round(12_000_00 * (1.02 ** 4)))
    expected_y5 = int(round(12_000_00 * (1.02 ** 5)))
    assert liab.liability_path_rappen[2] == pytest.approx(expected_y3, abs=10)
    assert liab.liability_path_rappen[3] == pytest.approx(expected_y4, abs=10)
    assert liab.liability_path_rappen[4] == pytest.approx(expected_y5, abs=10)


def test_pensionsausgabe_ongoing_runs_until_horizon():
    """is_ongoing=1 -> Outflow von Start bis horizon_years."""
    today = date.today()
    start = (today + timedelta(days=365 * 4)).isoformat()
    goal = _make_goal(
        goal_type="Pensionsausgabe",
        target_amount_rappen=24_000_00,
        frequency="jährlich",
        start_date=start,
        is_ongoing=1,
    )
    liab = goal_to_liability(goal, horizon_years=10)
    # Jahre 4..10 (Index 3..9) muessen Outflows haben
    for i in range(3, 10):
        assert liab.liability_path_rappen[i] == 24_000_00
    # Jahre 1..3 (Index 0..2) keine
    for i in range(3):
        assert liab.liability_path_rappen[i] == 0


def test_pensionsausgabe_truncated_horizon_adds_evaluation_note():
    """Goal laeuft 30 Jahre aber horizon=10 -> note erwaehnt Truncation."""
    today = date.today()
    start = (today + timedelta(days=365 * 5)).isoformat()
    end = (today + timedelta(days=365 * 35)).isoformat()
    goal = _make_goal(
        goal_type="Pensionsausgabe",
        target_amount_rappen=24_000_00,
        frequency="jährlich",
        start_date=start,
        target_date=end,
    )
    liab = goal_to_liability(goal, horizon_years=10)
    assert liab.evaluation_note is not None
    assert "Horizont" in liab.evaluation_note


def test_wiederkehrende_ausgabe_quarterly_annualizes_to_4x():
    """quartalsweise -> annual = 4x amount."""
    today = date.today()
    start = (today + timedelta(days=365)).isoformat()
    end = (today + timedelta(days=365 * 3)).isoformat()
    goal = _make_goal(
        goal_type="Wiederkehrende_Ausgabe",
        target_amount_rappen=2_500_00,
        frequency="quartalsweise",
        start_date=start,
        target_date=end,
    )
    liab = goal_to_liability(goal, horizon_years=10)
    annual = 2_500_00 * 4  # 10k pro Jahr
    assert liab.liability_path_rappen[0] == annual


# ============================================================================
# Maximierung
# ============================================================================


def test_maximierung_has_zero_path_and_zero_target():
    goal = _make_goal(goal_type="Maximierung", horizon_years=10)
    liab = goal_to_liability(goal, horizon_years=10)
    assert liab.target_kind == "maximize"
    assert liab.target_amount_rappen == 0
    assert all(v == 0 for v in liab.liability_path_rappen)


# ============================================================================
# Hardness + Weight
# ============================================================================


def test_hardness_hart_normalized():
    goal = _make_goal(hardness="Hart", horizon_years=5)
    liab = goal_to_liability(goal, horizon_years=5)
    assert liab.hardness_key == "hart"


def test_hardness_primaer_with_german_umlaut():
    goal = _make_goal(hardness="Primär", horizon_years=5)
    liab = goal_to_liability(goal, horizon_years=5)
    assert liab.hardness_key == "primaer"


def test_hardness_unknown_falls_back_to_primaer():
    goal = _make_goal(hardness="Quantum", horizon_years=5)
    liab = goal_to_liability(goal, horizon_years=5)
    assert liab.hardness_key == "primaer"


def test_weight_uses_explicit_when_set():
    goal = _make_goal(weight_bps=2500, horizon_years=5)
    liab = goal_to_liability(goal, horizon_years=5)
    assert liab.weight_bps == 2500


def test_weight_falls_back_to_rank_default():
    goal = _make_goal(weight_bps=None, rank=1, horizon_years=5)
    liab = goal_to_liability(goal, horizon_years=5)
    assert liab.weight_bps == 1875  # Rank 1 default


# ============================================================================
# Aggregation
# ============================================================================


def test_aggregate_sums_outflows_per_year():
    today = date.today()
    target_a = (today + timedelta(days=365 * 3)).isoformat()
    target_b = (today + timedelta(days=365 * 3)).isoformat()
    goal_a = _make_goal(
        goal_id="a", goal_type="Einmalige_Ausgabe",
        target_amount_rappen=50_000_00, target_date=target_a,
    )
    goal_b = _make_goal(
        goal_id="b", goal_type="Einmalige_Ausgabe",
        target_amount_rappen=30_000_00, target_date=target_b,
    )
    liabs = goals_to_liabilities([goal_a, goal_b], horizon_years=10)
    aggregated = aggregate_liability_path(liabs, 10)
    # Jahr 3 (Index 2) sollte 80'000 CHF Total-Outflow haben
    assert aggregated[2] == 80_000_00
    # Andere Jahre = 0
    for i in (0, 1, 3, 4, 5, 6, 7, 8, 9):
        assert aggregated[i] == 0


def test_aggregate_combines_recurring_and_einmalig():
    today = date.today()
    pension_start = (today + timedelta(days=365 * 5)).isoformat()
    pension_end = (today + timedelta(days=365 * 9)).isoformat()
    bullet_target = (today + timedelta(days=365 * 7)).isoformat()
    pension = _make_goal(
        goal_id="p", goal_type="Pensionsausgabe",
        target_amount_rappen=24_000_00, frequency="jährlich",
        start_date=pension_start, target_date=pension_end,
    )
    bullet = _make_goal(
        goal_id="b", goal_type="Einmalige_Ausgabe",
        target_amount_rappen=100_000_00, target_date=bullet_target,
    )
    liabs = goals_to_liabilities([pension, bullet], horizon_years=12)
    aggregated = aggregate_liability_path(liabs, 12)
    # Jahr 5..9 (Index 4..8) Pension 24k
    # Jahr 7 (Index 6) zusaetzlich 100k Bullet
    assert aggregated[4] == 24_000_00
    assert aggregated[5] == 24_000_00
    assert aggregated[6] == 24_000_00 + 100_000_00
    assert aggregated[7] == 24_000_00
    assert aggregated[8] == 24_000_00
    # Vor 5 und nach 9: 0
    assert aggregated[3] == 0
    assert aggregated[9] == 0


def test_goals_to_liabilities_empty_list_returns_empty():
    assert goals_to_liabilities([], horizon_years=10) == []
    assert aggregate_liability_path([], 10) == [0] * 10
