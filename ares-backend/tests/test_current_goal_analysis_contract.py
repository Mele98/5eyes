"""PAR-3: Zielerreichung muss fuer SOLL und IST symmetrisch vorliegen."""

from __future__ import annotations

from main import app  # noqa: F401 - registriert alle SQLAlchemy-Modelle
from models.mandates import Mandate
import services.portfolio_engine as pe
from test_optimizer_shadow_mode import _seed_realistic_mandate, session_factory  # noqa: F401


_REQUIRED_PARITY_KEYS = {
    "goal_id",
    "label",
    "success_rate_pct",
    "median_achievement_pct",
    "pessimistic_shortfall_rappen",
}


def _generate(session_factory, mandate_id: str, advisor_id: str) -> dict:
    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        return pe.generate_target_allocation(
            session,
            mandate,
            advisor_id,
            preferences={
                "policy": {},
                "tilts": {},
                "product": {},
                "limits": {},
                "geo": {},
                "assetClasses": {},
                "simulation": {"monteCarloRuns": 250},
            },
        )


def test_target_and_current_goal_analysis_are_symmetric_and_deterministic(
    session_factory,
):
    advisor_id, _client_id, mandate_id, _assessment_id, _goal_id = (
        _seed_realistic_mandate(session_factory, suffix="current-goals")
    )

    first = _generate(session_factory, mandate_id, advisor_id)
    second = _generate(session_factory, mandate_id, advisor_id)

    target = first["goal_analysis"]
    current = first["current_goal_analysis"]
    assert target
    assert len(current) == len(target)
    assert [item["goal_id"] for item in current] == [item["goal_id"] for item in target]

    for target_item, current_item in zip(target, current):
        assert set(current_item) == set(target_item)
        assert _REQUIRED_PARITY_KEYS <= set(target_item)
        for item in (target_item, current_item):
            assert 0 <= item["success_rate_pct"] <= 100
            assert 0 <= item["median_achievement_pct"] <= 100
            assert item["pessimistic_shortfall_rappen"] >= 0

    monte_carlo = first["monte_carlo"]
    assert len(monte_carlo["goal_summaries"]) == len(target)
    assert len(monte_carlo["current_goal_summaries"]) == len(current)

    assert second["goal_analysis"] == target
    assert second["current_goal_analysis"] == current
    assert second["monte_carlo"]["current_goal_summaries"] == monte_carlo["current_goal_summaries"]
