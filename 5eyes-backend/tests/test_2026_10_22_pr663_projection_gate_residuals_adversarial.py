"""Residual publication checks for merged PR #663.

PR #663 propagates a stale/blocked projection verdict through most advisory-
report channels.  Two allocation-derived numbers remained outside that
contract:

* the aggregate goal-achievement score was coerced from unavailable to ``0``;
* the risk-profile section still published the old allocation's risky
  fraction beside a replacement current assessment.

Adopted from the audit reproducer (2026-10-22) as a regular test without
xfail: unavailable projection values must remain unavailable in the API and
every client-facing report consumer.

The backend directory is located by structure (the directory containing
``main.py`` and ``database.py``), not by name.
"""
from __future__ import annotations

import sys
from pathlib import Path


def _backend_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "main.py").is_file() and (candidate / "database.py").is_file():
            return candidate
    raise AssertionError("backend directory (main.py + database.py) not found")


if str(_backend_root()) not in sys.path:
    sys.path.insert(0, str(_backend_root()))

from models.mandates import Mandate  # noqa: E402
from models.profiling import RiskAssessment  # noqa: E402
from services.advisory_report import compute_advisory_report  # noqa: E402
import services.portfolio_engine as pe  # noqa: E402
from tests.test_report_mc_allocation_staleness import (  # noqa: E402
    _generate,
    _replace_current_assessment,
    _seed_mandate,
    advisor_user,  # noqa: F401 - pytest fixture re-export
    session_factory,  # noqa: F401 - pytest fixture re-export
)


def _report(session_factory, mandate_id: str) -> dict:
    with session_factory() as session:
        return compute_advisory_report(
            session,
            session.get(Mandate, mandate_id),
        )


def test_blocked_gate_does_not_publish_unavailable_goal_score_as_zero(
    session_factory,  # noqa: F811
    advisor_user,  # noqa: F811
    monkeypatch,
):
    """Blocked is unavailable evidence, not a measured zero-percent success."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")
    mandate_id = _seed_mandate(session_factory, advisor_user.id)
    _generate(session_factory, mandate_id, advisor_user.id)

    with session_factory() as session:
        current = (
            session.query(RiskAssessment)
            .filter(
                RiskAssessment.mandate_id == mandate_id,
                RiskAssessment.is_current == 1,
            )
            .one()
        )
        current.is_current = 0
        session.commit()

    report = _report(session_factory, mandate_id)
    assert report["projection_gate"]["status"] == "blocked"
    assert report["projection_gate"]["projections_hidden"] is True
    assert (
        report["goal_based_investing"]["goal_achievement_score_bps"] is None
    ), "an unavailable aggregate goal probability must not be published as 0%"


def test_stale_gate_hides_old_allocation_risk_budget_from_new_profile(
    session_factory,  # noqa: F811
    advisor_user,  # noqa: F811
    monkeypatch,
):
    """A replacement assessment must not be paired with the old TA risk budget."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "house_matrix")
    mandate_id = _seed_mandate(session_factory, advisor_user.id)
    allocation = _generate(session_factory, mandate_id, advisor_user.id)
    old_risky_fraction = int(allocation.risky_fraction_bps)
    assert old_risky_fraction > 0  # positive control: a visible leak is possible

    _replace_current_assessment(session_factory, mandate_id, advisor_user.id)
    report = _report(session_factory, mandate_id)

    assert report["projection_gate"]["status"] == "stale"
    assert report["projection_gate"]["projections_hidden"] is True
    assert report["risikoprofilierung"]["risky_fraction_bps"] is None, (
        "the risk-profile section combines the replacement assessment with "
        f"the old allocation's {old_risky_fraction}-bps risk budget"
    )
    assert (
        "risikoprofilierung.risky_fraction_bps"
        in report["projection_gate"]["hidden_channels"]
    )
