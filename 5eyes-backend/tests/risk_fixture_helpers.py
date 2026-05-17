from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

from models.profiling import RiskAssessmentAnswer


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
