"""TEN-COMP-002 Teil 2 (Codex-Audit 2026-08-27, Folgefund zu PR #388 /
docs/audits/2026-08-27-tenant-and-compliance-reference-integrity-audit.md).

routers/profiling.py::create_suitability_check() nahm bisher
recommendation_run_id, advisory_log_id, knowledge_assessment_id,
risk_assessment_id und document_id ungeprueft entgegen -- ein Berater mit
Zugriff auf >=2 Mandate konnte eine Geeignetheitspruefung anlegen, die
Evidence-Datensaetze eines FREMDEN Mandats referenziert. Reproduzierbar
bereits auf einer einzelnen SQLite-Installation ohne Tenant-Konzept.

Diese Tests decken je einen negativen Fall (Evidence gehoert zu einem
anderen Mandat/Client -> 404) und einen positiven Regressionsfall (Evidence
gehoert zum selben Mandat/Client -> 201/Erfolg) fuer alle 5 Felder ab.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base  # noqa: E402
from models import (  # noqa: E402,F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
configure_mappers()

from models.allocation import OptimizerPolicy  # noqa: E402
from models.clients import Client  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from models.profiling import ClientKnowledge, RiskAssessment  # noqa: E402
from models.review import AdvisoryLog, ContractDocument, RecommendationRun  # noqa: E402
from models.users import User  # noqa: E402
from routers.profiling import create_suitability_check  # noqa: E402
from schemas.profiling import SuitabilityCheckCreate  # noqa: E402

_NOW = "2026-08-27T09:00:00.000Z"


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'suitability_check_evidence_binding.db'}",
        connect_args={"check_same_thread": False},
    )
    sf = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield sf
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


class _FakeClient:
    def __init__(self, host="127.0.0.1"):
        self.host = host


class _FakeRequest:
    def __init__(self, host="127.0.0.1"):
        self.headers = {}
        self.client = _FakeClient(host)


def _make_advisor(session) -> User:
    advisor = User(
        id=str(uuid.uuid4()),
        username=f"adv-{uuid.uuid4().hex[:6]}",
        password_hash="h",
        full_name="Anna Beispiel",
        role="advisor",
        is_active=1,
        created_at=_NOW,
        updated_at=_NOW,
    )
    session.add(advisor)
    session.commit()
    return advisor


def _make_mandate(session, advisor: User, *, label: str) -> Mandate:
    client = Client(
        id=str(uuid.uuid4()),
        client_number=f"C-{uuid.uuid4().hex[:6]}",
        first_name=label,
        last_name="Mandant",
        advisor_id=advisor.id,
        country_of_residence="CH",
        created_at=_NOW,
        updated_at=_NOW,
    )
    mandate = Mandate(
        id=str(uuid.uuid4()),
        client_id=client.id,
        mandate_number=f"M-{uuid.uuid4().hex[:6]}",
        mandate_type="Anlageberatung",
        opened_at=_NOW,
        created_at=_NOW,
        updated_at=_NOW,
    )
    session.add_all([client, mandate])
    session.commit()
    return mandate


def _make_optimizer_policy(session, advisor: User) -> OptimizerPolicy:
    policy = OptimizerPolicy(
        id=str(uuid.uuid4()),
        policy_name="Testpolicy",
        version=1,
        is_current=0,
        valid_from="2026-01-01",
        created_by=advisor.id,
        created_at=_NOW,
        updated_at=_NOW,
    )
    session.add(policy)
    session.commit()
    return policy


def _make_recommendation_run(session, mandate: Mandate, advisor: User, policy: OptimizerPolicy) -> RecommendationRun:
    run = RecommendationRun(
        id=str(uuid.uuid4()),
        mandate_id=mandate.id,
        client_id=mandate.client_id,
        policy_id=policy.id,
        run_type="Manuell",
        result_status="Draft",
        created_by=advisor.id,
        created_at=_NOW,
        updated_at=_NOW,
    )
    session.add(run)
    session.commit()
    return run


def _make_advisory_log(session, mandate: Mandate, advisor: User) -> AdvisoryLog:
    entry = AdvisoryLog(
        id=str(uuid.uuid4()),
        mandate_id=mandate.id,
        entry_type="Beratung",
        title="Jahresgespraech",
        advisor_id=advisor.id,
        entry_date=_NOW[:10],
        created_at=_NOW,
        updated_at=_NOW,
    )
    session.add(entry)
    session.commit()
    return entry


def _make_risk_assessment(session, mandate: Mandate, advisor: User) -> RiskAssessment:
    assessment = RiskAssessment(
        id=str(uuid.uuid4()),
        mandate_id=mandate.id,
        version=1,
        is_current=1,
        valid_from=_NOW[:10],
        q_income_points=3,
        q_obligations_points=3,
        q_savings_points=9,
        q_wealth_points=9,
        risk_capacity_total=24,
        risk_capacity_profile="Wachstumsorientiert",
        investment_horizon_years=15,
        investment_horizon_label="Mehr als 12 Jahre",
        risk_capacity_score_x10=70,
        q_investment_goal_points=3,
        q_risk_preference_points=3,
        q_risk_behavior_points=3,
        risk_willingness_total=9,
        risk_willingness_profile="Wachstumsorientiert",
        risk_willingness_score_x10=70,
        final_score_x10=70,
        final_profile="Wachstumsorientiert",
        assessed_at=_NOW,
        assessed_by=advisor.id,
        created_at=_NOW,
        updated_at=_NOW,
    )
    session.add(assessment)
    session.commit()
    return assessment


def _make_document(session, mandate: Mandate, advisor: User) -> ContractDocument:
    document = ContractDocument(
        id=str(uuid.uuid4()),
        mandate_id=mandate.id,
        document_type="Vertrag",
        title="Beratungsvertrag",
        created_by=advisor.id,
        created_at=_NOW,
        updated_at=_NOW,
    )
    session.add(document)
    session.commit()
    return document


def _make_knowledge(session, mandate: Mandate, advisor: User) -> ClientKnowledge:
    knowledge = ClientKnowledge(
        id=str(uuid.uuid4()),
        client_id=mandate.client_id,
        version=1,
        is_current=1,
        valid_from=_NOW[:10],
        knowledge_level="Mittel",
        confirmed_at=_NOW,
        confirmed_by=advisor.id,
        created_at=_NOW,
        updated_at=_NOW,
    )
    session.add(knowledge)
    session.commit()
    return knowledge


def _valid_body(**overrides) -> SuitabilityCheckCreate:
    payload = {
        "duty_type": "Eignungsprüfung",
        "result": "Geeignet",
    }
    payload.update(overrides)
    return SuitabilityCheckCreate(**payload)


# ── recommendation_run_id ────────────────────────────────────────────────────

def test_rejects_recommendation_run_id_from_other_mandate(session_factory):
    with session_factory() as session:
        advisor = _make_advisor(session)
        mandate = _make_mandate(session, advisor, label="Eigen")
        other_mandate = _make_mandate(session, advisor, label="Fremd")
        policy = _make_optimizer_policy(session, advisor)
        foreign_run = _make_recommendation_run(session, other_mandate, advisor, policy)

        with pytest.raises(HTTPException) as exc_info:
            create_suitability_check(
                mandate_id=mandate.id,
                body=_valid_body(recommendation_run_id=foreign_run.id),
                request=_FakeRequest(),
                db=session,
                current_user=advisor,
            )
        assert exc_info.value.status_code == 404


def test_accepts_recommendation_run_id_from_same_mandate(session_factory):
    with session_factory() as session:
        advisor = _make_advisor(session)
        mandate = _make_mandate(session, advisor, label="Eigen")
        policy = _make_optimizer_policy(session, advisor)
        run = _make_recommendation_run(session, mandate, advisor, policy)

        check = create_suitability_check(
            mandate_id=mandate.id,
            body=_valid_body(recommendation_run_id=run.id),
            request=_FakeRequest(),
            db=session,
            current_user=advisor,
        )
        assert check.recommendation_run_id == run.id


# ── advisory_log_id ───────────────────────────────────────────────────────────

def test_rejects_advisory_log_id_from_other_mandate(session_factory):
    with session_factory() as session:
        advisor = _make_advisor(session)
        mandate = _make_mandate(session, advisor, label="Eigen")
        other_mandate = _make_mandate(session, advisor, label="Fremd")
        foreign_entry = _make_advisory_log(session, other_mandate, advisor)

        with pytest.raises(HTTPException) as exc_info:
            create_suitability_check(
                mandate_id=mandate.id,
                body=_valid_body(advisory_log_id=foreign_entry.id),
                request=_FakeRequest(),
                db=session,
                current_user=advisor,
            )
        assert exc_info.value.status_code == 404


def test_accepts_advisory_log_id_from_same_mandate(session_factory):
    with session_factory() as session:
        advisor = _make_advisor(session)
        mandate = _make_mandate(session, advisor, label="Eigen")
        entry = _make_advisory_log(session, mandate, advisor)

        check = create_suitability_check(
            mandate_id=mandate.id,
            body=_valid_body(advisory_log_id=entry.id),
            request=_FakeRequest(),
            db=session,
            current_user=advisor,
        )
        assert check.advisory_log_id == entry.id


# ── risk_assessment_id ────────────────────────────────────────────────────────

def test_rejects_risk_assessment_id_from_other_mandate(session_factory):
    with session_factory() as session:
        advisor = _make_advisor(session)
        mandate = _make_mandate(session, advisor, label="Eigen")
        other_mandate = _make_mandate(session, advisor, label="Fremd")
        foreign_assessment = _make_risk_assessment(session, other_mandate, advisor)

        with pytest.raises(HTTPException) as exc_info:
            create_suitability_check(
                mandate_id=mandate.id,
                body=_valid_body(risk_assessment_id=foreign_assessment.id),
                request=_FakeRequest(),
                db=session,
                current_user=advisor,
            )
        assert exc_info.value.status_code == 404


def test_accepts_risk_assessment_id_from_same_mandate(session_factory):
    with session_factory() as session:
        advisor = _make_advisor(session)
        mandate = _make_mandate(session, advisor, label="Eigen")
        assessment = _make_risk_assessment(session, mandate, advisor)

        check = create_suitability_check(
            mandate_id=mandate.id,
            body=_valid_body(risk_assessment_id=assessment.id),
            request=_FakeRequest(),
            db=session,
            current_user=advisor,
        )
        assert check.risk_assessment_id == assessment.id


# ── document_id ───────────────────────────────────────────────────────────────

def test_rejects_document_id_from_other_mandate(session_factory):
    with session_factory() as session:
        advisor = _make_advisor(session)
        mandate = _make_mandate(session, advisor, label="Eigen")
        other_mandate = _make_mandate(session, advisor, label="Fremd")
        foreign_document = _make_document(session, other_mandate, advisor)

        with pytest.raises(HTTPException) as exc_info:
            create_suitability_check(
                mandate_id=mandate.id,
                body=_valid_body(document_id=foreign_document.id),
                request=_FakeRequest(),
                db=session,
                current_user=advisor,
            )
        assert exc_info.value.status_code == 404


def test_accepts_document_id_from_same_mandate(session_factory):
    with session_factory() as session:
        advisor = _make_advisor(session)
        mandate = _make_mandate(session, advisor, label="Eigen")
        document = _make_document(session, mandate, advisor)

        check = create_suitability_check(
            mandate_id=mandate.id,
            body=_valid_body(document_id=document.id),
            request=_FakeRequest(),
            db=session,
            current_user=advisor,
        )
        assert check.document_id == document.id


# ── knowledge_assessment_id (scoped by Client, nicht Mandat) ─────────────────

def test_rejects_knowledge_assessment_id_from_other_client(session_factory):
    with session_factory() as session:
        advisor = _make_advisor(session)
        mandate = _make_mandate(session, advisor, label="Eigen")
        other_mandate = _make_mandate(session, advisor, label="Fremd")
        foreign_knowledge = _make_knowledge(session, other_mandate, advisor)

        with pytest.raises(HTTPException) as exc_info:
            create_suitability_check(
                mandate_id=mandate.id,
                body=_valid_body(knowledge_assessment_id=foreign_knowledge.id),
                request=_FakeRequest(),
                db=session,
                current_user=advisor,
            )
        assert exc_info.value.status_code == 404


def test_accepts_knowledge_assessment_id_from_same_client(session_factory):
    with session_factory() as session:
        advisor = _make_advisor(session)
        mandate = _make_mandate(session, advisor, label="Eigen")
        knowledge = _make_knowledge(session, mandate, advisor)

        check = create_suitability_check(
            mandate_id=mandate.id,
            body=_valid_body(knowledge_assessment_id=knowledge.id),
            request=_FakeRequest(),
            db=session,
            current_user=advisor,
        )
        assert check.knowledge_assessment_id == knowledge.id
