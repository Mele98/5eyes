"""Red test for GOAL-PAST-DATE-LIFECYCLE-001 (round 38 audit, Repro 3).

See docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md

A recurring/pension outflow goal that is only PARTIALLY in the past must only
charge the portfolio for the occurrences that are still genuinely in the
future relative to today. Today a `start_date` anchored in the past is
clamped via ``max(1, calendar_years_until(...))`` to target_year_index=1, and
the goal's FULL historical duration (``target_date.year - start_date.year +
1``) is then replayed starting from year 1 -- resurrecting already-elapsed
payments as brand-new future liabilities.

Audit's exact numbers for a monthly CHF 100 stream running 2020-01-01 ..
2028-12-31, evaluated "today" (2026-10-03, matching this environment's real
clock so no as_of injection point is needed -- the production code has none):

    current (buggy) optimizer target   CHF 10'800  (9 new full years, 1..9)
    audit-documented correct target    CHF  3'600  (only the 3 remaining
                                                      years 2026..2028)

This test intentionally fails against the current implementation and is
marked xfail(strict=True) so it turns into a hard failure (not a silent
skip) the moment someone "fixes" it without actually closing the finding.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy.orm import configure_mappers
from database import Base  # noqa: F401
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
configure_mappers()

from services.optimizer.goal_liabilities import goal_to_liability


def _make_goal(
    *,
    goal_id: str = "g1",
    label: str = "Test",
    goal_type: str = "Wiederkehrende_Ausgabe",
    target_amount_rappen: int | None = None,
    horizon_years: int | None = None,
    target_date: str | None = None,
    start_date: str | None = None,
    is_ongoing: int = 0,
    frequency: str | None = "monatlich",
    hardness: str = "Primaer",
    rank: int = 2,
    weight_bps: int | None = None,
    value_mode: str = "nominal",
    goal_scope: str = "Beratungsvermoegen",
    pension_pillar: str | None = None,
):
    """Minimal mock-Goal (SimpleNamespace), mirrors tests/test_optimizer_goal_liabilities.py::_make_goal."""
    return SimpleNamespace(
        id=goal_id,
        label=label,
        goal_type=goal_type,
        target_amount_rappen=target_amount_rappen,
        target_wealth_rappen=None,
        target_return_bps=None,
        horizon_years=horizon_years,
        target_date=target_date,
        start_date=start_date,
        is_ongoing=is_ongoing,
        frequency=frequency,
        hardness=hardness,
        rank=rank,
        weight_bps=weight_bps,
        value_mode=value_mode,
        goal_scope=goal_scope,
        pension_pillar=pension_pillar,
        probability_pct=None,
        success_probability_min_x100=None,
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "GOAL-PAST-DATE-LIFECYCLE-001 -- round 38 red test, see "
        "docs/audits/2026-10-03-recurring-goal-lifecycle-calendar-and-mc-validation-audit.md "
        "(Repro 3, part-past monthly stream 2020-01-01..2028-12-31)"
    ),
)
def test_partially_past_monthly_stream_charges_only_remaining_future_years():
    today = date.today()
    assert today >= date(2026, 10, 3), (
        "Repro assumes 'today' is on/after 2026-10-03 as documented in the "
        "audit; adjust dates if this test is run from an earlier clock."
    )

    goal = _make_goal(
        goal_type="Wiederkehrende_Ausgabe",
        target_amount_rappen=100 * 100,  # CHF 100 in Rappen, monthly
        frequency="monatlich",
        start_date="2020-01-01",
        target_date="2028-12-31",
        is_ongoing=0,
    )

    horizon_years = 10
    liability = goal_to_liability(goal, horizon_years=horizon_years)

    remaining_years = date(2028, 12, 31).year - today.year + 1  # 2026..2028 inclusive = 3
    annual_amount_rappen = 100 * 100 * 12  # CHF 1'200/year in Rappen
    expected_total = annual_amount_rappen * remaining_years

    # Documented current (buggy) behaviour: 9 brand-new full years from
    # target_year_index=1, totalling CHF 10'800 instead of CHF 3'600.
    assert liability.target_amount_rappen == expected_total, (
        f"expected only the {remaining_years} genuinely remaining years "
        f"({expected_total} Rappen) to be charged, got "
        f"{liability.target_amount_rappen} Rappen -- a fully-elapsed portion "
        "of the stream was resurrected as a future liability"
    )

    # No occurrence may land before "today's" simulation year 1, and the
    # path must not contain more non-zero buckets than genuinely remain.
    nonzero_buckets = [amount for amount in liability.liability_path_rappen if amount]
    assert len(nonzero_buckets) == remaining_years, (
        f"expected exactly {remaining_years} funded buckets for the "
        f"remaining occurrences, got {len(nonzero_buckets)}: "
        f"{liability.liability_path_rappen}"
    )
