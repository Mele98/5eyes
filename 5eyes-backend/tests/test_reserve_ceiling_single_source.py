"""RESERVE-CEILING-001 (Assetallocation-Audit 2026-10-14).

The client needs a liquidity reserve R. The engine splits it into an external
part E (carved out of advisory wealth A, recommended outside the mandate) and
an internal part held as SAA liquidity on the investable base I = A - E.
Whatever the split, the CHF actually reserved must be R -- never more:

    E + I * reserve_floor_bps / 10000  ==  R   (up to a 1-bp ceiling on I)

Defect: E was computed with the SAA ceiling c = min(House liquidity max,
300 bps), but the stochastic hard floor used the fixed 300 bps. For every
profile whose House liquidity max is 200 bps (score buckets 7-10) the client
reserved R + 1 % of A: on the foundation example (A = 2.7 Mio, R = 600k)
CHF 627'206 instead of 600'000.

The payload rebuild then derived its ceiling from the *persisted* liquidity
band, which the floor had already lifted on the I-denominator (377 bps), and
showed a second, different external reserve (519k vs 546k at generation).

Expected values are computed from first principles in each test; the score-4
case (House liquidity max 500 -> c = 300) is the contrast where both paths
already agreed.
"""
from __future__ import annotations

import json

import pytest

from models.mandates import Mandate
from models.wealth import Goal, WealthPosition
from routers.allocation import get_current_allocation_payload
from routers.profiling import create_risk_assessment
from schemas.profiling import RiskAssessmentCreate
from services.portfolio_engine import generate_target_allocation
from test_runtime_contracts import (  # noqa: F401
    _FakeSignRequest,
    advisor_user,
    complete_risk_questionnaire_answers,
    seed_client_and_mandate,
    session_factory,
)

CHF = 100
A_CHF = 600_000
GOAL_CHF = 150_000  # one-off spending goal in 2 years -> fully reserve-relevant


def _generate(session_factory, advisor_user, willingness_points: int):
    client_id, mandate_id = seed_client_and_mandate(session_factory, advisor_user)
    payload = RiskAssessmentCreate(
        q_income_points=4, q_obligations_points=4, q_savings_points=12, q_wealth_points=12,
        investment_horizon_label="Mehr als 12 Jahre", investment_horizon_years=15,
        q_investment_goal_points=willingness_points,
        q_risk_preference_points=willingness_points,
        q_risk_behavior_points=willingness_points,
        answers=complete_risk_questionnaire_answers(willingness_points=willingness_points),
    )
    with session_factory() as session:
        create_risk_assessment(request=_FakeSignRequest(), mandate_id=mandate_id, body=payload,
                               db=session, current_user=advisor_user)
        session.add_all([
            WealthPosition(
                id="depot-1", client_id=client_id, label="Depot", position_type="Depot",
                assignment="Beratungsvermögen", current_value_rappen=A_CHF * CHF, currency="CHF",
                alloc_equities_bps=6000, alloc_bonds_bps=3000, alloc_real_estate_bps=0,
                alloc_liquidity_bps=500, alloc_alternatives_bps=500, is_active=1,
                created_at="2026-03-27T00:00:00.000Z", updated_at="2026-03-27T00:00:00.000Z",
            ),
            Goal(
                id="goal-1", mandate_id=mandate_id, client_id=client_id, goal_family="Cashflow",
                goal_type="Einmalige_Ausgabe", label="Eigenmittel Kauf", rank=1,
                goal_scope="Beratungsvermögen", value_mode="nominal",
                target_amount_rappen=GOAL_CHF * CHF, horizon_years=2, hardness="Hart", is_active=1,
                created_at="2026-03-27T00:00:00.000Z", updated_at="2026-03-27T00:00:00.000Z",
            ),
        ])
        session.commit()
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        result = generate_target_allocation(db=session, mandate=mandate, user_id=advisor_user.id,
                                            preferences=None)
        session.commit()
    return mandate_id, result


@pytest.mark.parametrize(
    "willingness_points,expected_house_liq_max",
    [(4, 200), (2, 500)],
    ids=["score-bucket-with-house-liq-max-200", "contrast-score-4-house-liq-max-500"],
)
def test_reserved_chf_equals_reserve_need(session_factory, advisor_user, willingness_points,
                                          expected_house_liq_max):
    _mid, result = _generate(session_factory, advisor_user, willingness_points)
    ta = result["target_allocation"]
    assert ta.optimization_method == "stochastic"
    constraints = json.loads(ta.effective_constraints_json)
    R = int(result["reserve_needed_rappen"])
    E = int(result["external_reserve_rappen"])
    I = int(result["investable_advisory_wealth_rappen"])
    A = A_CHF * CHF
    assert R == GOAL_CHF * CHF

    # First principles: c = min(House liquidity max, 300); internal = c * A.
    c = min(expected_house_liq_max, 300)
    expected_internal = A * c // 10000
    assert E == R - expected_internal
    assert I == A - E
    expected_floor = -(-expected_internal * 10000 // I)  # ceil
    assert int(constraints["reserve_floor_bps"]) == expected_floor

    held = E + I * int(constraints["reserve_floor_bps"]) // 10000
    one_bp_of_i = I // 10000 + 1
    assert R <= held <= R + one_bp_of_i, (
        f"reserved CHF {held / CHF:,.0f} != need CHF {R / CHF:,.0f} "
        f"(excess CHF {(held - R) / CHF:,.0f})"
    )


def test_payload_rebuild_shows_the_external_reserve_of_the_generation(session_factory, advisor_user):
    mandate_id, result = _generate(session_factory, advisor_user, 4)
    generated_external = int(result["external_reserve_rappen"])
    generated_investable = int(result["investable_advisory_wealth_rappen"])
    with session_factory() as session:
        payload = get_current_allocation_payload(mandate_id, db=session, current_user=advisor_user)
    payload = payload if isinstance(payload, dict) else payload.model_dump()
    assert int(payload["external_reserve_rappen"]) == generated_external
    assert int(payload["investable_advisory_wealth_rappen"]) == generated_investable
    ta = payload["target_allocation"]
    stored = ta["external_reserve_at_generation_rappen"] if isinstance(ta, dict) else ta.external_reserve_at_generation_rappen
    assert int(stored) == generated_external
