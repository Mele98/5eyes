"""Contracts for total-wealth goals against the canonical total paths.

The visible total paths already contain the complete external foundation:
direct-property value plus pledged assets minus liabilities.  Goal reporting
must consume those paths directly; rebuilding an external amount from the
initial wealth and CPI would both lose mortgage semantics and risk counting
the foundation twice.
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from models import (  # noqa: F401
    allocation,
    clients,
    mandates,
    profiling,
    review,
    snapshots,
    tenant,
    users,
    wealth,
)
from models.wealth import Goal
from services.portfolio_engine import (
    _build_goal_analysis,
    _monte_carlo_goal_summary,
)
from sqlalchemy.orm import configure_mappers

configure_mappers()


ADVISORY_START = 50_000_000
PROPERTY_SERIES = [100_000_000, 105_000_000, 110_000_000]
LIABILITY_SERIES = [40_000_000, 30_000_000, 20_000_000]
PLEDGED_ASSET_SERIES = [0, 4_000_000, 8_000_000]
INFLATION_BPS = [2500, 2500]
HORIZON = 2


def _goal() -> Goal:
    return Goal(
        id="total-path-goal",
        label="Gesamtvermoegensziel",
        goal_type="Vermoegensziel",
        goal_scope="Gesamtvermögen",
        target_wealth_rappen=150_000_000,
        value_mode="nominal",
        rank=1,
        horizon_years=HORIZON,
        is_ongoing=0,
        probability_pct=100,
    )


def _total_series(advisory_series: list[int]) -> list[int]:
    return [
        advisory
        + PROPERTY_SERIES[year]
        + PLEDGED_ASSET_SERIES[year]
        - LIABILITY_SERIES[year]
        for year, advisory in enumerate(advisory_series)
    ]


def _total_path_matrix(advisory_paths: list[list[int]]) -> list[list[int]]:
    return [
        [
            advisory
            + PROPERTY_SERIES[year]
            + PLEDGED_ASSET_SERIES[year]
            - LIABILITY_SERIES[year]
            for advisory in advisory_samples
        ]
        for year, advisory_samples in enumerate(advisory_paths)
    ]


def test_deterministic_total_goal_uses_exact_visible_total_path_once():
    advisory_path = [ADVISORY_START, ADVISORY_START, ADVISORY_START]
    total_path = _total_series(advisory_path)

    result = _build_goal_analysis(
        [_goal()],
        ADVISORY_START,
        total_path[0],
        [0] * HORIZON,
        INFLATION_BPS,
        0,
        0,
        None,
        advisory_path_series_rappen=advisory_path,
        total_path_series_rappen=total_path,
    )[0]

    # Year 2 = advisory 50m + property 110m + pledged 8m - debt 20m.
    assert total_path[HORIZON] == 148_000_000
    assert result["projected_value_rappen"] == total_path[HORIZON]
    # Legacy CPI reconstruction would be 50m + (110m - 50m) * 1.25^2.
    assert result["projected_value_rappen"] != 143_750_000


def test_mc_total_goal_uses_corresponding_target_and_current_total_paths_once():
    target_advisory = [
        [50_000_000] * 4,
        [45_000_000, 55_000_000, 65_000_000, 75_000_000],
        [40_000_000, 50_000_000, 60_000_000, 70_000_000],
    ]
    current_advisory = [
        [50_000_000] * 4,
        [30_000_000, 40_000_000, 50_000_000, 60_000_000],
        [20_000_000, 30_000_000, 40_000_000, 50_000_000],
    ]
    target_total = _total_path_matrix(target_advisory)
    current_total = _total_path_matrix(current_advisory)

    common = dict(
        goal=_goal(),
        annualized_return_samples_bps=[0] * 4,
        inflation_series_bps=INFLATION_BPS,
        advisory_wealth_rappen=ADVISORY_START,
        total_wealth_rappen=110_000_000,
        start_year=2026,
        horizon_years=HORIZON,
        policy=None,
    )
    target_result = _monte_carlo_goal_summary(
        path_values_by_year=target_advisory,
        total_path_values_by_year=target_total,
        **common,
    )
    current_result = _monte_carlo_goal_summary(
        path_values_by_year=current_advisory,
        total_path_values_by_year=current_total,
        **common,
    )

    # At year 2 the foundation contributes 110m + 8m - 20m = 98m to
    # every sample.  The reported percentiles must therefore be those of the
    # already-computed total matrices, with no additional CPI-grown scalar.
    assert target_total[HORIZON] == [138_000_000, 148_000_000, 158_000_000, 168_000_000]
    assert current_total[HORIZON] == [118_000_000, 128_000_000, 138_000_000, 148_000_000]
    assert {
        "p10": target_result["projected_value_p10_rappen"],
        "p25": target_result["projected_value_p25_rappen"],
        "p50": target_result["projected_value_p50_rappen"],
        "p90": target_result["projected_value_p90_rappen"],
        "success": target_result["success_rate_pct"],
    } == {
        "p10": 141_000_000,
        "p25": 145_500_000,
        "p50": 153_000_000,
        "p90": 165_000_000,
        "success": 50,
    }
    assert {
        "p10": current_result["projected_value_p10_rappen"],
        "p25": current_result["projected_value_p25_rappen"],
        "p50": current_result["projected_value_p50_rappen"],
        "p90": current_result["projected_value_p90_rappen"],
        "success": current_result["success_rate_pct"],
    } == {
        "p10": 121_000_000,
        "p25": 125_500_000,
        "p50": 133_000_000,
        "p90": 145_000_000,
        "success": 0,
    }

