"""Kontrollrunde 2026-09-24 (Data-Classification-Gate-Coverage-Audit,
Nachtrag zu tests/test_data_classification_gate_coverage_2026_09_21.py).

Drei weitere neue-Zeile-erzeugende Schreibpfade waren nie an das
Phase-0-Gate (services.data_classification.enforce_data_classification)
angeschlossen, obwohl sie demselben etablierten Muster wie AdvisoryLog/
ContractDocument/ConflictDisclosure/Knowledge/RiskAssessment folgen
(neue Zeile + potenziell sensibler Inhalt):

1. POST /clients/{id}/nationalities        -- echte Personendaten.
2. POST /clients/{id}/opt-history           -- Freitext (notes) +
   dokumentiert eine echte Klassifikations-Aenderung.
3. POST /mandates/{id}/suitability-checks   -- Freitext (result_notes),
   FIDLEG-Eignungs-/Angemessenheitspruefung.

Gegenprobe (bewusst NICHT gefixt, siehe PR-Beschreibung): PUT .../triggers/
resolve, PUT .../advisory-log/{id}, POST .../risk-assessments/{id}/override
mutieren nur eine bereits existierende, beim eigentlichen Create bereits
gegateten Zeile -- kein neues Schema-Feld dafuer vorhanden, kein Bypass
moeglich.

Jeder Test prueft: data_classification="real" wird bei
allow_real_client_data=False mit 403 blockiert (keine Zeile persistiert);
"synthetic" geht durch.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from config import settings
from database import Base
from models.clients import Client, ClientNationality, ClientOptHistory
from models.mandates import Mandate
from models.profiling import SuitabilityCheck
from models.users import User
from services.data_classification import PHASE_ZERO_BLOCK_DETAIL

from routers.clients import add_nationality, add_opt_history
from routers.profiling import create_suitability_check
from schemas.clients import NationalityCreate, OptHistoryCreate
from schemas.profiling import SuitabilityCheckCreate


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request_stub():
    return SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1"))


def _assert_phase_zero_block(exc_info) -> None:
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == PHASE_ZERO_BLOCK_DETAIL


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'dc_gate_coverage_20260924.db'}",
        connect_args={"check_same_thread": False},
    )
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield factory
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _seed_advisor_and_client(session_factory, *, client_id="client-dcgate2"):
    with session_factory() as db:
        db.add(User(
            id="advisor-dcgate2", username="advisor-dcgate2", password_hash="x",
            full_name="DC-Gate2 Advisor", role="advisor", is_active=1,
            created_at=_now(), updated_at=_now(),
        ))
        db.add(Client(
            id=client_id, client_number=f"{client_id}-NR", first_name="DC", last_name="Gate2",
            country_of_residence="CH", language="DE", household_type="Einzelperson",
            client_classification="Privatkunde", is_professional_opt_out=0,
            is_qualified_investor=0, advisor_id="advisor-dcgate2",
            created_at=_now(), updated_at=_now(),
        ))
        db.commit()
    return client_id


def _seed_advisor_and_mandate(session_factory, *, mandate_id="mandate-dcgate2"):
    client_id = f"{mandate_id}-client"
    with session_factory() as db:
        db.add(User(
            id="advisor-dcgate2m", username="advisor-dcgate2m", password_hash="x",
            full_name="DC-Gate2 Advisor", role="advisor", is_active=1,
            created_at=_now(), updated_at=_now(),
        ))
        db.add(Client(
            id=client_id, client_number=f"{client_id}-NR", first_name="DC", last_name="Gate2",
            country_of_residence="CH", language="DE", household_type="Einzelperson",
            client_classification="Privatkunde", is_professional_opt_out=0,
            is_qualified_investor=0, advisor_id="advisor-dcgate2m",
            created_at=_now(), updated_at=_now(),
        ))
        db.add(Mandate(
            id=mandate_id, client_id=client_id, mandate_number=f"{mandate_id}-NR",
            mandate_type="Anlageberatung", status="Aktiv", base_currency="CHF",
            advisory_language="DE", opened_at="2026-09-24",
            created_at=_now(), updated_at=_now(),
        ))
        db.commit()
    return mandate_id


def _advisor(user_id: str) -> User:
    return User(id=user_id, username=user_id, password_hash="x", full_name="A",
                role="advisor", is_active=1, created_at=_now(), updated_at=_now())


# ---------------------------------------------------------------------------
# 1) POST /clients/{id}/nationalities
# ---------------------------------------------------------------------------

def test_nationality_real_blocked_when_gate_closed(session_factory, monkeypatch):
    monkeypatch.setattr(settings, "allow_real_client_data", False)
    client_id = _seed_advisor_and_client(session_factory)

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc:
            add_nationality(
                client_id,
                NationalityCreate(country_code="CH", data_classification="real"),
                db=db, current_user=_advisor("advisor-dcgate2"),
            )
        _assert_phase_zero_block(exc)

    with session_factory() as db:
        assert db.query(ClientNationality).filter(
            ClientNationality.client_id == client_id
        ).count() == 0


def test_nationality_synthetic_allowed_when_gate_closed(session_factory, monkeypatch):
    monkeypatch.setattr(settings, "allow_real_client_data", False)
    client_id = _seed_advisor_and_client(session_factory, client_id="client-dcgate2-ok")

    with session_factory() as db:
        result = add_nationality(
            client_id,
            NationalityCreate(country_code="CH", data_classification="synthetic"),
            db=db, current_user=_advisor("advisor-dcgate2"),
        )
        assert result.country_code == "CH"


# ---------------------------------------------------------------------------
# 2) POST /clients/{id}/opt-history
# ---------------------------------------------------------------------------

def test_opt_history_real_blocked_when_gate_closed(session_factory, monkeypatch):
    monkeypatch.setattr(settings, "allow_real_client_data", False)
    client_id = _seed_advisor_and_client(session_factory, client_id="client-dcgate2-opt")

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc:
            add_opt_history(
                client_id,
                OptHistoryCreate(
                    event_type="Opt-Out", from_classification="Privatkunde",
                    to_classification="Professioneller Kunde", notes="echte Notiz",
                    data_classification="real",
                ),
                db=db, current_user=_advisor("advisor-dcgate2"),
            )
        _assert_phase_zero_block(exc)

    with session_factory() as db:
        assert db.query(ClientOptHistory).filter(
            ClientOptHistory.client_id == client_id
        ).count() == 0


def test_opt_history_synthetic_allowed_when_gate_closed(session_factory, monkeypatch):
    monkeypatch.setattr(settings, "allow_real_client_data", False)
    client_id = _seed_advisor_and_client(session_factory, client_id="client-dcgate2-opt-ok")

    with session_factory() as db:
        result = add_opt_history(
            client_id,
            OptHistoryCreate(
                event_type="Opt-Out", from_classification="Privatkunde",
                to_classification="Professioneller Kunde", notes="Test-Notiz",
                data_classification="synthetic",
            ),
            db=db, current_user=_advisor("advisor-dcgate2"),
        )
        assert result.to_classification == "Professioneller Kunde"


# ---------------------------------------------------------------------------
# 3) POST /mandates/{id}/suitability-checks
# ---------------------------------------------------------------------------

def test_suitability_check_real_blocked_when_gate_closed(session_factory, monkeypatch):
    monkeypatch.setattr(settings, "allow_real_client_data", False)
    mandate_id = _seed_advisor_and_mandate(session_factory)

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc:
            create_suitability_check(
                mandate_id,
                SuitabilityCheckCreate(
                    duty_type="Eignungsprüfung", result="Geeignet",
                    result_notes="echte Kundendaten", data_classification="real",
                ),
                _request_stub(), db=db, current_user=_advisor("advisor-dcgate2m"),
            )
        _assert_phase_zero_block(exc)

    with session_factory() as db:
        assert db.query(SuitabilityCheck).filter(
            SuitabilityCheck.mandate_id == mandate_id
        ).count() == 0


def test_suitability_check_synthetic_allowed_when_gate_closed(session_factory, monkeypatch):
    monkeypatch.setattr(settings, "allow_real_client_data", False)
    mandate_id = _seed_advisor_and_mandate(session_factory, mandate_id="mandate-dcgate2-ok")

    with session_factory() as db:
        result = create_suitability_check(
            mandate_id,
            SuitabilityCheckCreate(
                duty_type="Eignungsprüfung", result="Geeignet",
                result_notes="Test-Notiz", data_classification="synthetic",
            ),
            _request_stub(), db=db, current_user=_advisor("advisor-dcgate2m"),
        )
        assert result.mandate_id == mandate_id
