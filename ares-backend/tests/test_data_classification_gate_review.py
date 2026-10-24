"""2026-07-25 (Generalaudit, Fortsetzung): das Phase-0-Datenklassifizierungs-
Gate (enforce_data_classification) fehlte auch fuer Beratungsprotokoll
(AdvisoryLog), Vertragsdokumente (ContractDocument) und Interessenkonflikt-
Offenlegungen (ConflictOfInterestDisclosure) in routers/review.py -- alle
drei enthalten (potenziell) echten Kundendaten-Freitext, wurden aber von
Pydantic vor Ankunft am Endpoint stillschweigend verworfen.
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


def _create_mandate(auth_client, client_id, **overrides):
    payload = {"mandate_number": f"E0-M-{client_id[-8:]}"}
    payload.update(overrides)
    response = auth_client.post(f"/clients/{client_id}/mandates", json=payload)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _valid_advisory_log_payload(**overrides) -> dict:
    base = {
        "entry_type": "Jahresreview",
        "title": "Jahresgespraech 2026",
        "description": "Besprechung der Anlagestrategie und aktuellen Marktlage mit dem Kunden.",
        "entry_datetime": "2026-07-25T09:00:00.000Z",
        "duration_minutes": 45,
        "communication_channel": "persoenlich",
        "cost_disclosure_given": True,
        "topics": ["Strategie", "Kosten"],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Beratungsprotokoll (AdvisoryLog)
# ---------------------------------------------------------------------------

def test_real_advisory_log_is_blocked_when_gate_is_closed(auth_client, session_factory, monkeypatch):
    from models.review import AdvisoryLog

    client_id = _create_synthetic_client(auth_client, "E0-ADV-REAL")
    mandate_id = _create_mandate(auth_client, client_id)
    monkeypatch.setattr(settings, "allow_real_client_data", False)

    response = auth_client.post(
        f"/mandates/{mandate_id}/advisory-log",
        json=_valid_advisory_log_payload(data_classification="real"),
    )
    _assert_phase_zero_block(response)
    with session_factory() as session:
        assert session.query(AdvisoryLog).filter(
            AdvisoryLog.mandate_id == mandate_id,
        ).count() == 0


def test_synthetic_advisory_log_is_allowed_when_gate_is_closed(auth_client, monkeypatch):
    client_id = _create_synthetic_client(auth_client, "E0-ADV-SYNTH")
    mandate_id = _create_mandate(auth_client, client_id)
    monkeypatch.setattr(settings, "allow_real_client_data", False)

    response = auth_client.post(
        f"/mandates/{mandate_id}/advisory-log",
        json=_valid_advisory_log_payload(data_classification="synthetic"),
    )
    assert response.status_code == 201, response.text


def test_advisory_log_omitted_classification_defaults_to_synthetic(auth_client, monkeypatch):
    client_id = _create_synthetic_client(auth_client, "E0-ADV-DEFAULT")
    mandate_id = _create_mandate(auth_client, client_id)
    monkeypatch.setattr(settings, "allow_real_client_data", False)

    response = auth_client.post(
        f"/mandates/{mandate_id}/advisory-log",
        json=_valid_advisory_log_payload(),
    )
    assert response.status_code == 201, response.text


# ---------------------------------------------------------------------------
# Vertragsdokumente (ContractDocument)
# ---------------------------------------------------------------------------

def test_real_document_is_blocked_when_gate_is_closed(auth_client, session_factory, monkeypatch):
    from models.review import ContractDocument

    client_id = _create_synthetic_client(auth_client, "E0-DOC-REAL")
    mandate_id = _create_mandate(auth_client, client_id)
    monkeypatch.setattr(settings, "allow_real_client_data", False)

    response = auth_client.post(
        f"/mandates/{mandate_id}/documents",
        json={
            "document_type": "Beratungsvertrag",
            "title": "Vertrag",
            "data_classification": "real",
        },
    )
    _assert_phase_zero_block(response)
    with session_factory() as session:
        assert session.query(ContractDocument).filter(
            ContractDocument.mandate_id == mandate_id,
        ).count() == 0


def test_synthetic_document_is_allowed_when_gate_is_closed(auth_client, monkeypatch):
    client_id = _create_synthetic_client(auth_client, "E0-DOC-SYNTH")
    mandate_id = _create_mandate(auth_client, client_id)
    monkeypatch.setattr(settings, "allow_real_client_data", False)

    response = auth_client.post(
        f"/mandates/{mandate_id}/documents",
        json={
            "document_type": "Beratungsvertrag",
            "title": "Vertrag",
            "data_classification": "synthetic",
        },
    )
    assert response.status_code == 201, response.text
    assert "data_classification" not in response.json()


# ---------------------------------------------------------------------------
# Interessenkonflikte (ConflictOfInterestDisclosure)
# ---------------------------------------------------------------------------

def test_real_conflict_is_blocked_when_gate_is_closed(auth_client, session_factory, monkeypatch):
    from models.review import ConflictOfInterestDisclosure

    client_id = _create_synthetic_client(auth_client, "E0-CFL-REAL")
    mandate_id = _create_mandate(auth_client, client_id)
    monkeypatch.setattr(settings, "allow_real_client_data", False)

    response = auth_client.post(
        f"/mandates/{mandate_id}/conflicts",
        json={
            "conflict_type": "Retrozession / Inducement",
            "description": "Vertriebsentschaedigung durch Produktanbieter.",
            "data_classification": "real",
        },
    )
    _assert_phase_zero_block(response)
    with session_factory() as session:
        assert session.query(ConflictOfInterestDisclosure).filter(
            ConflictOfInterestDisclosure.mandate_id == mandate_id,
        ).count() == 0


def test_synthetic_conflict_is_allowed_when_gate_is_closed(auth_client, monkeypatch):
    client_id = _create_synthetic_client(auth_client, "E0-CFL-SYNTH")
    mandate_id = _create_mandate(auth_client, client_id)
    monkeypatch.setattr(settings, "allow_real_client_data", False)

    response = auth_client.post(
        f"/mandates/{mandate_id}/conflicts",
        json={
            "conflict_type": "Retrozession / Inducement",
            "description": "Vertriebsentschaedigung durch Produktanbieter.",
            "data_classification": "synthetic",
        },
    )
    assert response.status_code == 201, response.text
    assert "data_classification" not in response.json()


# ---------------------------------------------------------------------------
# Protokoll-Bausteine Mandats-Selektion (custom_override_md = Klienten-Freitext)
# ---------------------------------------------------------------------------

def _create_baustein(auth_client, title: str) -> str:
    response = auth_client.post("/protocol-bausteine", json={"title": title})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_real_baustein_selection_override_is_blocked_when_gate_is_closed(
    auth_client, session_factory, monkeypatch,
):
    from models.protocol_bausteine import MandateBausteinSelection

    client_id = _create_synthetic_client(auth_client, "E0-BST-REAL")
    mandate_id = _create_mandate(auth_client, client_id)
    baustein_id = _create_baustein(auth_client, "E0-BST-REAL-Baustein")
    monkeypatch.setattr(settings, "allow_real_client_data", False)

    response = auth_client.put(
        f"/mandates/{mandate_id}/protocol-bausteine",
        json={
            "selections": [
                {"baustein_id": baustein_id, "custom_override_md": "Echter Klientenname XY"},
            ],
            "data_classification": "real",
        },
    )
    _assert_phase_zero_block(response)
    with session_factory() as session:
        assert session.query(MandateBausteinSelection).filter(
            MandateBausteinSelection.mandate_id == mandate_id,
        ).count() == 0


def test_synthetic_baustein_selection_override_is_allowed_when_gate_is_closed(
    auth_client, monkeypatch,
):
    client_id = _create_synthetic_client(auth_client, "E0-BST-SYNTH")
    mandate_id = _create_mandate(auth_client, client_id)
    baustein_id = _create_baustein(auth_client, "E0-BST-SYNTH-Baustein")
    monkeypatch.setattr(settings, "allow_real_client_data", False)

    response = auth_client.put(
        f"/mandates/{mandate_id}/protocol-bausteine",
        json={
            "selections": [
                {"baustein_id": baustein_id, "custom_override_md": "Platzhalter"},
            ],
            "data_classification": "synthetic",
        },
    )
    assert response.status_code == 200, response.text
