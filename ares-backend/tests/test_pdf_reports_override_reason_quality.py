"""Kontrollrunde 2026-09-21 (Override-Begruendungs-Audit): die dedizierte
FINMA-W305-Risikoprofil-PDF (routers/pdf_reports.py::get_risikoprofil_pdf)
las override_reason bisher ohne jede Qualitaetspruefung -- derselbe
Massstab wie beim Schreiben (schemas/profiling.py) und beim Live-Engine-
Lauf (services.risk_assessment_semantics.validate_risk_assessment_model_
input) wurde hier nie angewendet. Anders als der 16-Sektionen-Advisory-
Report enthaelt diese eigenstaendige PDF KEINE Section-19-Compliance-
Zusammenfassung -- ein Betrachter dieser PDF allein sah eine schlechte/
fehlende Begruendung unmarkiert.

Fix: bei Qualitaetsverstoss wird ein COMPLIANCE-HINWEIS an den Override-
Text angehaengt (nicht-blockierend, endpoint bleibt defensiv/best-effort
wie zuvor).
"""
from __future__ import annotations

import datetime
import sys
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, get_db
import models.allocation  # noqa: F401
import models.clients  # noqa: F401
import models.client_login  # noqa: F401
import models.fx_rate  # noqa: F401
import models.mandates  # noqa: F401
import models.profiling  # noqa: F401
import models.protocol_bausteine  # noqa: F401
import models.review  # noqa: F401
import models.snapshots  # noqa: F401
import models.tenant  # noqa: F401
import models.users  # noqa: F401
import models.wealth  # noqa: F401

from main import app
from models.clients import Client
from models.mandates import Mandate
from models.profiling import RiskAssessment
from models.users import User
from services.auth import get_current_user


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'pdf_reports_override.db'}",
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
        id="advisor-pdf-override", username="advisor-pdf-override", password_hash="h",
        full_name="Test Advisor", role="advisor", is_active=1,
        created_at=_now(), updated_at=_now(),
    )


@pytest.fixture()
def auth_client(session_factory, advisor_user):
    def override_db():
        with session_factory() as session:
            yield session
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: advisor_user
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def _seed_mandate_with_override(
    session_factory, advisor_user, *, override_reason, mandate_id: str,
) -> str:
    with session_factory() as db:
        db.add(advisor_user)
        client_id = "cli-" + mandate_id
        db.add(Client(
            id=client_id, client_number="C-" + mandate_id, first_name="A", last_name="B",
            country_of_residence="CH", language="DE", household_type="Einzelperson",
            client_classification="Privatkunde", is_professional_opt_out=0,
            is_qualified_investor=0, advisor_id=advisor_user.id,
            created_at=_now(), updated_at=_now(),
        ))
        db.add(Mandate(
            id=mandate_id, client_id=client_id, mandate_number="M-" + mandate_id,
            mandate_type="Anlageberatung", status="Aktiv", base_currency="CHF",
            advisory_language="DE", opened_at="2026-06-08",
            created_at=_now(), updated_at=_now(),
        ))
        db.add(RiskAssessment(
            id="ra-" + mandate_id, mandate_id=mandate_id, version=1, is_current=1,
            valid_from="2026-01-01",
            q_income_points=4, q_obligations_points=4, q_savings_points=12, q_wealth_points=12,
            risk_capacity_total=32, risk_capacity_profile="Ausgewogen",
            investment_horizon_years=15, investment_horizon_label="Mehr als 12 Jahre",
            risk_capacity_score_x10=50,
            q_investment_goal_points=3, q_risk_preference_points=3, q_risk_behavior_points=3,
            risk_willingness_total=9, risk_willingness_profile="Ausgewogen",
            risk_willingness_score_x10=50,
            final_score_x10=50, final_profile="Ausgewogen",
            # Umgeht RiskAssessmentOverride/validate_override_reason_quality
            # bewusst (Direkt-Insert) -- simuliert Altbestand/Migrations-
            # Artefakt, das nie durch die Pydantic-Pruefung lief.
            is_overridden=1, override_score_x10=100, override_profile="Dynamisch",
            override_reason=override_reason,
            override_client_confirmed=0, override_warning_delivered=0,
            assessed_at=_now(), assessed_by=advisor_user.id,
            created_at=_now(), updated_at=_now(),
        ))
        db.commit()
    return mandate_id


def _pdf_text(pdf_bytes: bytes) -> str:
    return "\n".join(
        page.extract_text() or "" for page in PdfReader(BytesIO(pdf_bytes)).pages
    )


def test_risikoprofil_pdf_flags_missing_override_reason(auth_client, advisor_user, session_factory):
    mandate_id = _seed_mandate_with_override(
        session_factory, advisor_user, override_reason=None, mandate_id="mdt-badreason1",
    )
    resp = auth_client.get(f"/mandates/{mandate_id}/reports/risikoprofil.pdf")
    assert resp.status_code == 200, resp.text
    text = _pdf_text(resp.content)
    assert "COMPLIANCE-HINWEIS" in text


def test_risikoprofil_pdf_flags_generic_phrase_override_reason(auth_client, advisor_user, session_factory):
    mandate_id = _seed_mandate_with_override(
        session_factory, advisor_user,
        override_reason="kundenwunsch!!!!!!!!!!!!", mandate_id="mdt-badreason2",
    )
    resp = auth_client.get(f"/mandates/{mandate_id}/reports/risikoprofil.pdf")
    assert resp.status_code == 200, resp.text
    text = _pdf_text(resp.content)
    assert "COMPLIANCE-HINWEIS" in text


def test_risikoprofil_pdf_no_hint_for_valid_override_reason(auth_client, advisor_user, session_factory):
    mandate_id = _seed_mandate_with_override(
        session_factory, advisor_user,
        override_reason=(
            "Kunde hat umfangreiche Erfahrung und wuenscht bewusst "
            "ein aggressiveres Profil als der Fragebogen ergibt."
        ),
        mandate_id="mdt-goodreason",
    )
    resp = auth_client.get(f"/mandates/{mandate_id}/reports/risikoprofil.pdf")
    assert resp.status_code == 200, resp.text
    text = _pdf_text(resp.content)
    assert "COMPLIANCE-HINWEIS" not in text
