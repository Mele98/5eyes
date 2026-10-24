"""Integrity contracts for persisted risk-assessment score derivation."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from main import app  # noqa: F401 - register the complete ORM model graph
from models.profiling import RiskAssessment
from services.risk_assessment_semantics import (
    RiskAssessmentInputError,
    validate_risk_assessment_model_input,
)
from services.risk_scoring import compute_scores, profile_for_score_x10


VALID_OVERRIDE_REASON = "Kundenwunsch ausdruecklich dokumentiert und begruendet"


def _derived_assessment(
    *,
    mandate_type: str = "Anlageberatung",
    q_income_points: int = 0,
    q_obligations_points: int = 0,
    q_savings_points: int = 0,
    q_wealth_points: int = 0,
    investment_horizon_label: str = "Mehr als 12 Jahre",
    q_investment_goal_points: int = 1,
    q_risk_preference_points: int = 1,
    q_risk_behavior_points: int = 1,
    **overrides,
):
    scores = compute_scores(
        q_income_points=q_income_points,
        q_obligations_points=q_obligations_points,
        q_savings_points=q_savings_points,
        q_wealth_points=q_wealth_points,
        investment_horizon_label=investment_horizon_label,
        q_investment_goal_points=q_investment_goal_points,
        q_risk_preference_points=q_risk_preference_points,
        q_risk_behavior_points=q_risk_behavior_points,
    )
    final_score = min(scores.final_score_x10, 75) if mandate_type == "FZK" else scores.final_score_x10
    values = {
        "q_income_points": q_income_points,
        "q_obligations_points": q_obligations_points,
        "q_savings_points": q_savings_points,
        "q_wealth_points": q_wealth_points,
        "investment_horizon_label": investment_horizon_label,
        "risk_capacity_total": scores.risk_capacity_total,
        "risk_capacity_profile": scores.risk_capacity_profile,
        "risk_capacity_score_x10": scores.risk_capacity_score_x10,
        "q_investment_goal_points": q_investment_goal_points,
        "q_risk_preference_points": q_risk_preference_points,
        "q_risk_behavior_points": q_risk_behavior_points,
        "risk_willingness_total": scores.risk_willingness_total,
        "risk_willingness_profile": scores.risk_willingness_profile,
        "risk_willingness_score_x10": scores.risk_willingness_score_x10,
        "final_score_x10": final_score,
        "final_profile": profile_for_score_x10(final_score),
        "is_overridden": 0,
        "override_score_x10": None,
        "override_profile": None,
        "override_reason": None,
        "override_client_confirmed": 0,
        "override_warning_delivered": 0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_rejects_high_final_score_derived_from_conservative_raw_points():
    assessment = _derived_assessment(
        final_score_x10=100,
        final_profile="Aktien",
    )

    with pytest.raises(RiskAssessmentInputError, match=r"final_score_x10.*Herleitung"):
        validate_risk_assessment_model_input(
            assessment,
            mandate_type="Anlageberatung",
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("risk_capacity_total", 31),
        ("risk_capacity_profile", "Dynamisch"),
        ("risk_capacity_score_x10", 100),
        ("risk_willingness_total", 12),
        ("risk_willingness_profile", "Aktien"),
        ("risk_willingness_score_x10", 100),
    ],
)
def test_rejects_tampered_persisted_intermediate_derivation(field, value):
    assessment = _derived_assessment(**{field: value})

    with pytest.raises(RiskAssessmentInputError, match=field):
        validate_risk_assessment_model_input(assessment)


def test_fzk_accepts_exactly_capped_derived_final_score():
    assessment = _derived_assessment(
        mandate_type="FZK",
        q_income_points=4,
        q_obligations_points=4,
        q_savings_points=12,
        q_wealth_points=12,
        q_investment_goal_points=4,
        q_risk_preference_points=4,
        q_risk_behavior_points=4,
    )

    assert validate_risk_assessment_model_input(
        assessment,
        mandate_type="FZK",
    ) == 75


def test_non_fzk_rejects_an_unexplained_fzk_style_cap():
    assessment = _derived_assessment(
        mandate_type="FZK",
        q_income_points=4,
        q_obligations_points=4,
        q_savings_points=12,
        q_wealth_points=12,
        q_investment_goal_points=4,
        q_risk_preference_points=4,
        q_risk_behavior_points=4,
    )

    with pytest.raises(RiskAssessmentInputError, match=r"final_score_x10.*Herleitung"):
        validate_risk_assessment_model_input(
            assessment,
            mandate_type="Anlageberatung",
        )


def test_valid_override_cannot_conceal_a_tampered_base_derivation():
    assessment = _derived_assessment(
        final_score_x10=100,
        final_profile="Aktien",
        is_overridden=1,
        override_score_x10=50,
        override_profile="Ausgewogen",
        override_reason=VALID_OVERRIDE_REASON,
    )

    with pytest.raises(RiskAssessmentInputError, match=r"final_score_x10.*Herleitung"):
        validate_risk_assessment_model_input(assessment)


def test_fzk_override_is_still_capped_after_derivation_validation():
    assessment = _derived_assessment(
        mandate_type="FZK",
        is_overridden=1,
        override_score_x10=80,
        override_profile="Wachstumsorientiert",
        override_reason=VALID_OVERRIDE_REASON,
    )

    with pytest.raises(RiskAssessmentInputError, match="FZK.*override_score_x10"):
        validate_risk_assessment_model_input(assessment, mandate_type="FZK")


def test_legacy_horizon_requires_reprofiling_fail_closed():
    assessment = SimpleNamespace(
        q_income_points=2,
        q_obligations_points=3,
        q_savings_points=8,
        q_wealth_points=8,
        investment_horizon_label="12 bis 17 Jahre",
        risk_capacity_total=21,
        risk_capacity_profile="Wachstumsorientiert",
        risk_capacity_score_x10=70,
        q_investment_goal_points=3,
        q_risk_preference_points=4,
        q_risk_behavior_points=3,
        risk_willingness_total=10,
        risk_willingness_profile="Wachstumsorientiert",
        risk_willingness_score_x10=70,
        final_score_x10=70,
        final_profile="Wachstumsorientiert",
        is_overridden=0,
        override_client_confirmed=0,
        override_warning_delivered=0,
    )

    with pytest.raises(
        RiskAssessmentInputError,
        match=r"Legacy- oder Fremd-Fachlogik|Risikoprofilierung",
    ):
        validate_risk_assessment_model_input(assessment)


def test_real_orm_assessment_with_legacy_horizon_fails_closed():
    values = vars(_derived_assessment()).copy()
    values["investment_horizon_label"] = "12 bis 17 Jahre"
    assessment = RiskAssessment(**values)
    assert "_sa_instance_state" in vars(assessment)

    with pytest.raises(
        RiskAssessmentInputError,
        match=r"Legacy- oder Fremd-Fachlogik|Risikoprofilierung",
    ):
        validate_risk_assessment_model_input(assessment)
