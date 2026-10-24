"""Integritaet des Risikoprofil-Fragebogens (O-1, O-2).

O-1: Antworten, die nicht aus dem Standard-Fragebogen stammen (gesperrter
Beta-Editor: pauschale Platzhalter, fremde Optionstexte, vertauschte Fragen),
werden beim Speichern abgelehnt; gespeicherte Profile mit Nachweis dieser
Herkunft sind nicht strategiefaehig. Altprofile aus dem Standard-Fragebogen
bleiben strategiefaehig.

O-2: Der Server leitet die Punkte aus den gewaehlten Antworten ab. Weichen die
vom Client gesendeten Punkte ab, antwortet er mit 422 und reason_code statt
still zu korrigieren.
"""
from __future__ import annotations

import copy
import datetime
import json
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, get_db
from main import app
from models.clients import Client
from models.mandates import Mandate
from models.profiling import RiskAssessment, RiskAssessmentAnswer
from models.users import User
from services.auth import get_current_user
from services.portfolio_engine import require_strategy_ready_assessment
from tests.risk_fixture_helpers import (
    CURRENT_RISK_ANSWERS,
    CURRENT_RISK_SCHEMA_MARKERS,
    derive_current_risk_fields,
    noop_lifespan,
    standard_risk_payload,
)

NOT_STANDARD = "RISK_QUESTIONNAIRE_NOT_STANDARD"


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'rq_integrity.db'}",
        connect_args={"check_same_thread": False},
    )
    sf = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield sf
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def advisor_user():
    return User(
        id="user-rq-integrity", username="advisor-rq", password_hash="h",
        full_name="Advisor RQ", role="advisor", is_active=1,
        created_at=_now(), updated_at=_now(),
    )


@pytest.fixture()
def client(session_factory, advisor_user, monkeypatch):
    def override_db():
        with session_factory() as session:
            yield session

    monkeypatch.setattr(app.router, "lifespan_context", noop_lifespan)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: advisor_user
    with TestClient(app) as tc:
        yield tc
    app.dependency_overrides.clear()


@pytest.fixture()
def mandate_id(client, advisor_user) -> str:
    cr = client.post("/clients", json={
        "client_number": "RQI-001", "first_name": "Rq", "last_name": "Integrity",
        "advisor_id": advisor_user.id, "household_type": "Einzelperson",
    })
    assert cr.status_code == 201, cr.text
    mr = client.post(f"/clients/{cr.json()['id']}/mandates",
                     json={"mandate_number": "RQI-M-001", "mandate_type": "Anlageberatung"})
    assert mr.status_code == 201, mr.text
    return mr.json()["id"]


def _post(client, mandate_id, payload):
    return client.post(f"/mandates/{mandate_id}/risk-assessments", json=payload)


def _reason(resp) -> str | None:
    detail = resp.json().get("detail")
    return detail.get("reason_code") if isinstance(detail, dict) else None


def _answer(payload, number):
    return next(a for a in payload["answers"] if a["question_number"] == number)


def beta_editor_payload() -> dict:
    """Wortgleich zu buildRiskAssessmentPayload() des gesperrten Beta-Editors."""
    state = {
        "q_income_points": 2, "q_obligations_points": 2, "q_savings_points": 6,
        "q_wealth_points": 6, "investment_horizon_label": "6 bis 7 Jahre",
        "investment_horizon_years": 6, "q_investment_goal_points": 3,
        "q_risk_preference_points": 3, "q_risk_behavior_points": 3,
    }
    rows = [
        (1, "Kenntnisse", "Finanzdienstleistungen: dokumentiert im Beratungsgespraech", 0),
        (2, "Kenntnisse", "Finanzinstrumente: dokumentiert im Beratungsgespraech", 0),
        (3, "Risikofaehigkeit", "Einkommen deckt Verpflichtungen solide in CHF", 2),
        (4, "Risikofaehigkeit", "Herkunft: Einkommen und Vermoegen plausibilisiert", 0),
        (5, "Risikofaehigkeit", "Verpflichtungen sind tragbar in CHF", 2),
        (6, "Risikofaehigkeit", "Solide Sparquote in CHF", 6),
        (7, "Risikofaehigkeit", "Solide freie Vermoegensbasis in % des Vermoegens", 6),
        (8, "Risikofaehigkeit", "Matrix Anlagehorizont: 6 bis 7 Jahre", 0),
        (9, "Risikobereitschaft", "Vermoegen ausgewogen vermehren", 3),
        (10, "Risikobereitschaft", "Rendite und Risiko ausbalancieren", 3),
        (11, "Risikobereitschaft", "Verluste zeitweise aushalten", 3),
    ]
    marker = json.dumps({"source": "react_profiling_editor", "status": "documented"})
    return {
        **state,
        "answers": [
            {"question_number": n, "question_section": s, "answer_label": label, "answer_points": p}
            for n, s, label, p in rows
        ],
        "knowledge_services_json": marker,
        "knowledge_instruments_json": marker,
        "income_sources_json": json.dumps(["Beratungsgespraech"]),
    }


# ── Speichern: Standard-Fragebogen ──────────────────────────────────────────────

def test_standard_questionnaire_payload_is_accepted(client, mandate_id):
    resp = _post(client, mandate_id, standard_risk_payload())
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["q_income_points"] == 3
    assert body["final_score_x10"] == 70


def test_standard_payload_with_umlaut_free_and_dash_variants_is_accepted(client, mandate_id):
    payload = standard_risk_payload(income=4, pref=0)
    _answer(payload, 3)["answer_label"] = "Ueber CHF 20'000"
    _answer(payload, 10)["answer_label"] = _answer(payload, 10)["answer_label"].replace("−", "-")
    resp = _post(client, mandate_id, payload)
    assert resp.status_code == 201, resp.text


# ── O-1: nicht-konforme Antwortstruktur ─────────────────────────────────────────

def test_beta_editor_payload_is_rejected_with_reason_code(client, mandate_id):
    resp = _post(client, mandate_id, beta_editor_payload())
    assert resp.status_code == 422, resp.text
    assert _reason(resp) == NOT_STANDARD
    assert "Standard-Fragebogen neu erfassen" in resp.json()["detail"]["message"]


@pytest.mark.parametrize("mutate", [
    pytest.param(lambda p: _answer(p, 1).update(answer_label="Finanzdienstleistungen: dokumentiert im Beratungsgespraech"), id="q1-placeholder"),
    pytest.param(lambda p: _answer(p, 4).update(answer_label="Herkunft: Einkommen und Vermoegen plausibilisiert"), id="q4-placeholder"),
    pytest.param(lambda p: _answer(p, 6).update(answer_label="Solide Sparquote in CHF"), id="q6-unknown-option"),
    pytest.param(lambda p: _answer(p, 8).update(answer_label="Matrix Anlagehorizont: 8 bis 11 Jahre"), id="q8-foreign-format"),
    pytest.param(lambda p: p["answers"].append(dict(_answer(p, 9))), id="duplicate-question"),
    pytest.param(lambda p: p.update(knowledge_services_json=json.dumps({"source": "react_profiling_editor"})), id="source-marker"),
])
def test_nonstandard_answer_structure_is_rejected(client, mandate_id, mutate):
    payload = standard_risk_payload()
    mutate(payload)
    resp = _post(client, mandate_id, payload)
    assert resp.status_code == 422, resp.text
    assert _reason(resp) == NOT_STANDARD


# ── Gespeicherte Profile (Bestand) ──────────────────────────────────────────────

def _seed_assessment(session_factory, *, knowledge_json: str, answers: list[tuple]) -> str:
    now = _now()
    with session_factory() as s:
        client_row = Client(
            id=str(uuid.uuid4()), client_number=f"RQB-{uuid.uuid4().hex[:6]}",
            first_name="Bestand", last_name="Profil", advisor_id="user-rq-integrity",
            household_type="Einzelperson", created_at=now, updated_at=now,
        )
        s.add(client_row)
        s.flush()
        mandate = Mandate(
            id=str(uuid.uuid4()), client_id=client_row.id,
            mandate_number=f"RQB-M-{uuid.uuid4().hex[:6]}", mandate_type="Anlageberatung", opened_at=now[:10],
            created_at=now, updated_at=now,
        )
        s.add(mandate)
        s.flush()
        fields = derive_current_risk_fields(
            q_income_points=3, q_obligations_points=3, q_savings_points=9, q_wealth_points=9,
            investment_horizon_label="Mehr als 12 Jahre", q_investment_goal_points=3,
            q_risk_preference_points=3, q_risk_behavior_points=3,
        )
        ra = RiskAssessment(
            id=str(uuid.uuid4()), mandate_id=mandate.id, version=1, is_current=1,
            valid_from=now[:10], is_overridden=0, assessed_at=now, assessed_by="user-rq-integrity",
            created_at=now, updated_at=now,
            knowledge_services_json=knowledge_json, knowledge_instruments_json=knowledge_json,
            income_sources_json=CURRENT_RISK_SCHEMA_MARKERS["income_sources_json"],
            **fields,
        )
        s.add(ra)
        s.flush()
        for number, label, points in answers:
            s.add(RiskAssessmentAnswer(
                id=str(uuid.uuid4()), assessment_id=ra.id, question_number=number,
                question_section="Risikoprofil", answer_label=label, answer_points=points,
                created_at=now,
            ))
        s.commit()
        return mandate.id


def test_stored_legacy_standard_profile_stays_strategy_ready(session_factory):
    mandate_id = _seed_assessment(session_factory, knowledge_json="{}", answers=CURRENT_RISK_ANSWERS)
    with session_factory() as s:
        assert require_strategy_ready_assessment(s, mandate_id) is not None


def test_stored_beta_editor_profile_is_not_strategy_ready(session_factory):
    marker = json.dumps({"source": "react_profiling_editor", "status": "documented"})
    mandate_id = _seed_assessment(session_factory, knowledge_json=marker, answers=CURRENT_RISK_ANSWERS)
    with session_factory() as s:
        with pytest.raises(ValueError) as exc:
            require_strategy_ready_assessment(s, mandate_id)
    assert NOT_STANDARD in str(exc.value)
    assert "Standard-Fragebogen neu erfassen" in str(exc.value)


def test_stored_profile_with_placeholder_answers_is_not_strategy_ready(session_factory):
    rows = [
        (n, "Finanzdienstleistungen: dokumentiert im Beratungsgespraech", 0) if n == 1 else (n, label, points)
        for n, label, points in CURRENT_RISK_ANSWERS
    ]
    mandate_id = _seed_assessment(session_factory, knowledge_json="{}", answers=rows)
    with session_factory() as s:
        ra = s.query(RiskAssessment).filter(RiskAssessment.mandate_id == mandate_id).one()
        _ = ra.answers  # geladen wie in den Strategie-Pfaden mit Antworten
        from services.risk_assessment_semantics import validate_risk_assessment_model_input
        with pytest.raises(ValueError) as exc:
            validate_risk_assessment_model_input(ra, mandate_type="Anlageberatung")
    assert NOT_STANDARD in str(exc.value)


def test_beta_marker_blocks_even_with_documented_override():
    from services.risk_assessment_semantics import validate_risk_assessment_model_input
    marker = json.dumps({"source": "react_profiling_editor"})
    probe = SimpleNamespace(
        final_score_x10=30, final_profile="Defensiv", is_overridden=1,
        override_score_x10=30, override_profile="Defensiv",
        override_reason="Kundenwunsch ausdruecklich dokumentiert",
        override_client_confirmed=1, override_warning_delivered=1,
        knowledge_services_json=marker, knowledge_instruments_json=marker, answers=[],
    )
    with pytest.raises(ValueError) as exc:
        validate_risk_assessment_model_input(copy.copy(probe))
    assert NOT_STANDARD in str(exc.value)
