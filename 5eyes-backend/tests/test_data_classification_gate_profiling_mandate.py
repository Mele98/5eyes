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
from tests.risk_fixture_helpers import standard_risk_payload


def _valid_risk_payload(**overrides) -> dict:
    # Standard-Fragebogen: Punkte passen zu den gewaehlten Antworten (O-2).
    base = standard_risk_payload(horizon=3)
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
