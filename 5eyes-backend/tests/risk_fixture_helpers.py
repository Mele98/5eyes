from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

from models.profiling import RiskAssessmentAnswer
from services.risk_scoring import HORIZON_YEARS, canonicalize_horizon_label, compute_scores


CURRENT_RISK_SCHEMA_MARKERS = {
    "knowledge_services_json": "{}",
    "knowledge_instruments_json": "{}",
    "income_sources_json": '["Berufliche Taetigkeit"]',
}


CURRENT_RISK_ANSWERS = [
    (1, "Finanzdienstleistungen: Beratung und Verwaltung", 0),
    (2, "Finanzinstrumente: Anlagefonds und ETFs", 0),
    (3, "CHF 12'000 bis 20'000", 3),
    (4, "Herkunft: Berufliche Taetigkeit", 0),
    (5, "CHF 3'000 bis 5'000", 3),
    (6, "CHF 1'000'000 bis 2'000'000", 9),
    (7, "25 bis 50 %", 9),
    (8, "Mehr als 12 Jahre - Matrix-Faktor", 0),
    (9, "Das investierte Kapital soll sich stetig vermehren.", 3),
    (10, "Ich strebe eine hoehere Rendite an und bin bereit, dafuer ein erhoehtes Risiko einzugehen.", 3),
    (11, "Ich kann den Verlust voruebergehend akzeptieren und halte an meinen Anlagen fest.", 3),
]


def derive_current_risk_fields(
    *,
    q_income_points: int,
    q_obligations_points: int,
    q_savings_points: int,
    q_wealth_points: int,
    investment_horizon_label: str,
    q_investment_goal_points: int,
    q_risk_preference_points: int,
    q_risk_behavior_points: int,
) -> dict[str, int | str]:
    """Build a self-consistent persisted risk fixture from source answers."""

    canonical_horizon = canonicalize_horizon_label(investment_horizon_label)
    if canonical_horizon not in HORIZON_YEARS:
        raise ValueError(
            f"Test-Fixture verwendet keinen kanonischen Horizon: {investment_horizon_label!r}"
        )
    source = {
        "q_income_points": q_income_points,
        "q_obligations_points": q_obligations_points,
        "q_savings_points": q_savings_points,
        "q_wealth_points": q_wealth_points,
        "investment_horizon_label": canonical_horizon,
        "q_investment_goal_points": q_investment_goal_points,
        "q_risk_preference_points": q_risk_preference_points,
        "q_risk_behavior_points": q_risk_behavior_points,
    }
    scores = compute_scores(**source)
    return {
        **source,
        "investment_horizon_years": HORIZON_YEARS[canonical_horizon],
        "risk_capacity_total": scores.risk_capacity_total,
        "risk_capacity_profile": scores.risk_capacity_profile,
        "risk_capacity_score_x10": scores.risk_capacity_score_x10,
        "risk_willingness_total": scores.risk_willingness_total,
        "risk_willingness_profile": scores.risk_willingness_profile,
        "risk_willingness_score_x10": scores.risk_willingness_score_x10,
        "final_score_x10": scores.final_score_x10,
        "final_profile": scores.final_profile,
    }


def add_current_risk_answers(session, assessment_id: str, created_at: str, *, section: str = "Risikoprofil") -> None:
    for question_number, label, points in CURRENT_RISK_ANSWERS:
        session.add(
            RiskAssessmentAnswer(
                id=str(uuid.uuid4()),
                assessment_id=assessment_id,
                question_number=question_number,
                question_section=section,
                answer_label=label,
                answer_points=points,
                created_at=created_at,
            )
        )


@asynccontextmanager
async def noop_lifespan(_app):
    yield
