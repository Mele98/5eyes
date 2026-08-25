"""2026-07-25 (Generalaudit): das Phase-0-Datenklassifizierungs-Gate
(enforce_data_classification) fehlte fuer Mandate, Risikoprofilierung und
Kenntnisse-&-Erfahrungen -- obwohl Cashflow/Goal/WealthPosition/
WealthInflow/Client bereits abgedeckt waren. Ein mitgesendetes
"data_classification":"real" wurde von Pydantic vorher stillschweigend
verworfen, bevor der Endpoint es je sah. Risikoprofilierung ist die
sensibelste Datenkategorie der App (Einkommen/Vermoegen/Verpflichtungen/
Risikoantworten) -- der schwerste Einzelfund dieser Welle.
"""
from __future__ import annotations

from services.data_classification import PHASE_ZERO_BLOCK_DETAIL
from test_data_classification_gate import (  # noqa: F401
    _assert_phase_zero_block,
    _create_synthetic_client,
    advisor_user,
    auth_client,
    session_factory,
)
from config import settings


def _valid_risk_payload(**overrides) -> dict:
    base = {
        "q_income_points": 3,
        "q_obligations_points": 2,
        "q_savings_points": 8,
        "q_wealth_points": 8,
        "investment_horizon_years": 12,
        "investment_horizon_label": "5 bis 10 Jahre",
        "q_investment_goal_points": 3,
        "q_risk_preference_points": 3,
        "q_risk_behavior_points": 3,
        "answers": [
            {"question_number": 1, "answer_label": "Finanzdienstleistungen: Beratung und Verwaltung", "answer_points": 0},
            {"question_number": 2, "answer_label": "Finanzinstrumente: Anlagefonds und ETFs", "answer_points": 0},
            {"question_number": 3, "answer_label": "CHF 12'000 bis 20'000", "answer_points": 3},
            {"question_number": 4, "answer_label": "Herkunft: Berufliche Taetigkeit", "answer_points": 0},
            {"question_number": 5, "answer_label": "CHF 3'000 bis 5'000", "answer_points": 3},
            {"question_number": 6, "answer_label": "CHF 1'000'000 bis 2'000'000", "answer_points": 9},
            {"question_number": 7, "answer_label": "25 bis 50 %", "answer_points": 9},
            {"question_number": 8, "answer_label": "5 bis 7 Jahre - Matrix-Faktor", "answer_points": 0},
            {"question_number": 9, "answer_label": "Das investierte Kapital soll sich stetig vermehren.", "answer_points": 3},
            {"question_number": 10, "answer_label": "Ich strebe eine hoehere Rendite an und bin bereit, dafuer ein erhoehtes Risiko einzugehen.", "answer_points": 3},
            {"question_number": 11, "answer_label": "Ich kann den Verlust voruebergehend akzeptieren und halte an meinen Anlagen fest.", "answer_points": 3},
        ],
    }
    base.update(overrides)
    return base


def _create_mandate(auth_client, client_id, **overrides):
    payload = {"mandate_number": f"E0-M-{client_id[-8:]}"}
    payload.update(overrides)
    response = auth_client.post(f"/clients/{client_id}/mandates", json=payload)
    assert response.status_code == 201, response.text
    return response.json()["id"]


# ---------------------------------------------------------------------------
# Mandate
# ---------------------------------------------------------------------------

def test_real_mandate_is_blocked_when_gate_is_closed(auth_client, monkeypatch):
    client_id = _create_synthetic_client(auth_client, "E0-MND-REAL")
    monkeypatch.setattr(settings, "allow_real_client_data", False)
    response = auth_client.post(
        f"/clients/{client_id}/mandates",
        json={"mandate_number": "E0-MND-1", "data_classification": "real"},
    )
    _assert_phase_zero_block(response)


def test_synthetic_mandate_is_allowed_when_gate_is_closed(auth_client, monkeypatch):
    client_id = _create_synthetic_client(auth_client, "E0-MND-SYNTH")
    monkeypatch.setattr(settings, "allow_real_client_data", False)
    response = auth_client.post(
        f"/clients/{client_id}/mandates",
        json={"mandate_number": "E0-MND-2", "data_classification": "synthetic"},
    )
    assert response.status_code == 201, response.text
    assert "data_classification" not in response.json()


def test_mandate_update_with_real_classification_is_blocked(auth_client, monkeypatch):
    client_id = _create_synthetic_client(auth_client, "E0-MND-UPD")
    mandate_id = _create_mandate(auth_client, client_id)
    monkeypatch.setattr(settings, "allow_real_client_data", False)
    response = auth_client.put(
        f"/mandates/{mandate_id}",
        json={"data_classification": "real", "depot_bank": "MustNotPersist"},
    )
    _assert_phase_zero_block(response)
    current = auth_client.get(f"/mandates/{mandate_id}")
    assert current.json()["depot_bank"] != "MustNotPersist"


# ---------------------------------------------------------------------------
# Risikoprofilierung (hoechste Sensitivitaet)
# ---------------------------------------------------------------------------

def test_real_risk_assessment_is_blocked_when_gate_is_closed(auth_client, session_factory, monkeypatch):
    from models.profiling import RiskAssessment

    client_id = _create_synthetic_client(auth_client, "E0-RA-REAL")
    mandate_id = _create_mandate(auth_client, client_id)
    monkeypatch.setattr(settings, "allow_real_client_data", False)

    response = auth_client.post(
        f"/mandates/{mandate_id}/risk-assessments",
        json=_valid_risk_payload(data_classification="real"),
    )
    _assert_phase_zero_block(response)
    with session_factory() as session:
        assert session.query(RiskAssessment).filter(
            RiskAssessment.mandate_id == mandate_id,
        ).count() == 0


def test_synthetic_risk_assessment_is_allowed_when_gate_is_closed(auth_client, monkeypatch):
    client_id = _create_synthetic_client(auth_client, "E0-RA-SYNTH")
    mandate_id = _create_mandate(auth_client, client_id)
    monkeypatch.setattr(settings, "allow_real_client_data", False)

    response = auth_client.post(
        f"/mandates/{mandate_id}/risk-assessments",
        json=_valid_risk_payload(data_classification="synthetic"),
    )
    assert response.status_code == 201, response.text
    assert "data_classification" not in response.json()


def test_risk_assessment_omitted_classification_defaults_to_synthetic(auth_client, monkeypatch):
    client_id = _create_synthetic_client(auth_client, "E0-RA-DEFAULT")
    mandate_id = _create_mandate(auth_client, client_id)
    monkeypatch.setattr(settings, "allow_real_client_data", False)

    response = auth_client.post(
        f"/mandates/{mandate_id}/risk-assessments",
        json=_valid_risk_payload(),
    )
    assert response.status_code == 201, response.text


# ---------------------------------------------------------------------------
# Kenntnisse & Erfahrungen
# ---------------------------------------------------------------------------

def test_real_knowledge_is_blocked_when_gate_is_closed(auth_client, session_factory, monkeypatch):
    from models.profiling import ClientKnowledge

    client_id = _create_synthetic_client(auth_client, "E0-KNW-REAL")
    monkeypatch.setattr(settings, "allow_real_client_data", False)

    response = auth_client.post(
        f"/clients/{client_id}/knowledge",
        json={"knowledge_level": "Hoch", "data_classification": "real"},
    )
    _assert_phase_zero_block(response)
    with session_factory() as session:
        assert session.query(ClientKnowledge).filter(
            ClientKnowledge.client_id == client_id,
        ).count() == 0


def test_synthetic_knowledge_is_allowed_when_gate_is_closed(auth_client, monkeypatch):
    client_id = _create_synthetic_client(auth_client, "E0-KNW-SYNTH")
    monkeypatch.setattr(settings, "allow_real_client_data", False)

    response = auth_client.post(
        f"/clients/{client_id}/knowledge",
        json={"knowledge_level": "Hoch", "data_classification": "synthetic"},
    )
    assert response.status_code == 201, response.text
