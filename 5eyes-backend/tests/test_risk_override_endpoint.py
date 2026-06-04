from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base
from models.clients import Client
from models.mandates import Mandate
from models.users import User
from routers.profiling import create_risk_assessment, override_risk_assessment
from schemas.profiling import RiskAssessmentCreate, RiskAssessmentOverride
from services.portfolio_engine import risk_assessment_ready_for_strategy
from services.risk_scoring import profile_for_score_x10
from tests.risk_fixture_helpers import CURRENT_RISK_ANSWERS


VALID_OVERRIDE_REASON = "Kundenwunsch ausdruecklich dokumentiert"


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'risk_override_endpoint.db'}",
        connect_args={"check_same_thread": False},
    )
    sf = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield sf
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _answers() -> list[dict]:
    return [
        {
            "question_number": question_number,
            "question_section": "Risikoprofil",
            "answer_label": label,
            "answer_points": points,
        }
        for question_number, label, points in CURRENT_RISK_ANSWERS
    ]


def test_risk_override_endpoint_persists_and_keeps_assessment_strategy_ready(session_factory):
    now = "2026-05-17T00:00:00.000Z"
    advisor = User(
        id="advisor-override",
        username="advisor-override",
        password_hash="hash",
        full_name="Advisor Override",
        role="advisor",
        is_active=1,
        created_at=now,
        updated_at=now,
    )
    with session_factory() as session:
        session.add(advisor)
        session.add(
            Client(
                id="client-override",
                client_number="C-OVERRIDE",
                first_name="Max",
                last_name="Muster",
                country_of_residence="CH",
                language="DE",
                household_type="Einzelperson",
                client_classification="Privatkunde",
                is_professional_opt_out=0,
                is_qualified_investor=0,
                advisor_id=advisor.id,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            Mandate(
                id="mandate-override",
                client_id="client-override",
                mandate_number="M-OVERRIDE",
                mandate_type="Anlageberatung",
                status="Aktiv",
                base_currency="CHF",
                advisory_language="DE",
                opened_at="2026-05-17",
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()

        assessment = create_risk_assessment(
            mandate_id="mandate-override",
            body=RiskAssessmentCreate(
                q_income_points=3,
                q_obligations_points=3,
                q_savings_points=9,
                q_wealth_points=9,
                investment_horizon_label="Mehr als 12 Jahre",
                investment_horizon_years=15,
                q_investment_goal_points=3,
                q_risk_preference_points=3,
                q_risk_behavior_points=3,
                answers=_answers(),
                knowledge_services_json="{}",
                knowledge_instruments_json="{}",
                income_sources_json='["Berufliche Taetigkeit"]',
            ),
            db=session,
            current_user=advisor,
        )

        saved = override_risk_assessment(
            mandate_id="mandate-override",
            ra_id=assessment.id,
            body=RiskAssessmentOverride(
                override_score_x10=70,
                override_profile=profile_for_score_x10(70),
                override_reason=VALID_OVERRIDE_REASON,
            ),
            db=session,
            current_user=advisor,
        )

        assert saved.is_overridden == 1
        assert saved.override_score_x10 == 70
        assert saved.override_profile == "Wachstumsorientiert"
        assert saved.override_reason == VALID_OVERRIDE_REASON
        assert risk_assessment_ready_for_strategy(saved) is True
