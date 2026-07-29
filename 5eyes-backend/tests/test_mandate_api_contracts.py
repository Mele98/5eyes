from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, get_db
from main import app
from models.users import User
from services.auth import get_current_user


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'mandate_api_contracts.db'}",
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
        id="user-mandate-contract",
        username="advisor",
        password_hash="h",
        full_name="Advisor",
        role="advisor",
        is_active=1,
        created_at=_utc_now_iso(),
        updated_at=_utc_now_iso(),
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


def _create_client(auth_client: TestClient, advisor_user: User) -> str:
    response = auth_client.post(
        "/clients",
        json={
            "client_number": "FOUND-001",
            "first_name": "Foundation",
            "last_name": "Client",
            "advisor_id": advisor_user.id,
            "household_type": "Einzelperson",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _create_mandate(auth_client: TestClient, client_id: str, number: str = "FOUND-M-GOAL") -> str:
    response = auth_client.post(
        f"/clients/{client_id}/mandates",
        json={"mandate_number": number, "mandate_type": "Anlageberatung"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_create_mandate_persists_investment_universe(auth_client, advisor_user):
    client_id = _create_client(auth_client, advisor_user)

    response = auth_client.post(
        f"/clients/{client_id}/mandates",
        json={
            "mandate_number": "FOUND-M-001",
            "mandate_type": "Anlageberatung",
            "investment_universe": "Alternativ",
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["investment_universe"] == "Alternativ"

    reload_response = auth_client.get(f"/mandates/{body['id']}")
    assert reload_response.status_code == 200, reload_response.text
    assert reload_response.json()["investment_universe"] == "Alternativ"


def test_update_mandate_roundtrips_building_block_defaults(auth_client, advisor_user):
    client_id = _create_client(auth_client, advisor_user)
    mandate = auth_client.post(
        f"/clients/{client_id}/mandates",
        json={"mandate_number": "FOUND-M-002", "mandate_type": "Anlageberatung"},
    ).json()
    defaults = {
        "equitiesGeo": "Global",
        "bondsDuration": "Kurzfristig",
        "realestateMarket": "Schweiz",
    }

    response = auth_client.put(
        f"/mandates/{mandate['id']}",
        json={"default_building_blocks_json": json.dumps(defaults)},
    )

    assert response.status_code == 200, response.text
    assert json.loads(response.json()["default_building_blocks_json"]) == defaults

    reload_response = auth_client.get(f"/mandates/{mandate['id']}")
    assert reload_response.status_code == 200, reload_response.text
    assert json.loads(reload_response.json()["default_building_blocks_json"]) == defaults


def test_create_mandate_hidden_report_sections_defaults_to_null(auth_client, advisor_user):
    """2026-07-27 (HUD-Konfiguration): neue Mandate haben KEINE ausgeblendeten
    Sektionen -- Backwards-Compat, alles sichtbar per Default."""
    client_id = _create_client(auth_client, advisor_user)
    response = auth_client.post(
        f"/clients/{client_id}/mandates",
        json={"mandate_number": "FOUND-M-HUD-1", "mandate_type": "Anlageberatung"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["hidden_report_sections"] is None


def test_update_mandate_roundtrips_hidden_report_sections(auth_client, advisor_user):
    client_id = _create_client(auth_client, advisor_user)
    mandate = auth_client.post(
        f"/clients/{client_id}/mandates",
        json={"mandate_number": "FOUND-M-HUD-2", "mandate_type": "Anlageberatung"},
    ).json()
    hidden = ["cover", "disclaimer"]

    response = auth_client.put(
        f"/mandates/{mandate['id']}",
        json={"hidden_report_sections": json.dumps(hidden)},
    )
    assert response.status_code == 200, response.text
    assert json.loads(response.json()["hidden_report_sections"]) == hidden

    reload_response = auth_client.get(f"/mandates/{mandate['id']}")
    assert reload_response.status_code == 200, reload_response.text
    assert json.loads(reload_response.json()["hidden_report_sections"]) == hidden


def test_create_mandate_jurisdiction_defaults_to_null(auth_client, advisor_user):
    """2026-07-27 (Laender-Skalierung): neue Mandate haben KEIN gesetztes
    jurisdiction -- NULL wird von Backend-Code als 'CH' interpretiert
    (Backwards-Compat, siehe models/mandates.py)."""
    client_id = _create_client(auth_client, advisor_user)
    response = auth_client.post(
        f"/clients/{client_id}/mandates",
        json={"mandate_number": "FOUND-M-JUR-1", "mandate_type": "Anlageberatung"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["jurisdiction"] is None


def test_update_mandate_roundtrips_jurisdiction(auth_client, advisor_user):
    client_id = _create_client(auth_client, advisor_user)
    mandate = auth_client.post(
        f"/clients/{client_id}/mandates",
        json={"mandate_number": "FOUND-M-JUR-2", "mandate_type": "Anlageberatung"},
    ).json()

    response = auth_client.put(
        f"/mandates/{mandate['id']}",
        json={"jurisdiction": "DE"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["jurisdiction"] == "DE"

    reload_response = auth_client.get(f"/mandates/{mandate['id']}")
    assert reload_response.status_code == 200, reload_response.text
    assert reload_response.json()["jurisdiction"] == "DE"


def test_foundation_customer_data_roundtrip(auth_client, advisor_user):
    """Phase-1-Fundament: die wichtigsten Beratungsdaten ueberleben Speichern/Laden.

    Dieser Test ist bewusst ein API-Roundtrip statt reiner Unit-Test: genau diese
    Daten bilden spaeter die Asset Allocation, den Vergleich und die
    Zusammenfassung.
    """
    client_id = _create_client(auth_client, advisor_user)
    mandate_response = auth_client.post(
        f"/clients/{client_id}/mandates",
        json={"mandate_number": "FOUND-M-003", "mandate_type": "Anlageberatung"},
    )
    assert mandate_response.status_code == 201, mandate_response.text
    mandate_id = mandate_response.json()["id"]

    wealth_response = auth_client.post(
        f"/clients/{client_id}/wealth-positions",
        json={
            "label": "Depot Hausbank",
            "position_type": "Depot",
            "assignment": "Beratungsvermögen",
            "current_value_rappen": 2_000_000_00,
            "alloc_equities_bps": 5500,
            "alloc_bonds_bps": 3000,
            "alloc_real_estate_bps": 500,
            "alloc_liquidity_bps": 1000,
            "alloc_alternatives_bps": 0,
        },
    )
    assert wealth_response.status_code == 201, wealth_response.text
    wealth_id = wealth_response.json()["id"]
    wealth_update = auth_client.put(
        f"/clients/{client_id}/wealth-positions/{wealth_id}",
        json={"current_value_rappen": 2_100_000_00, "notes": "aktualisiert"},
    )
    assert wealth_update.status_code == 200, wealth_update.text
    assert wealth_update.json()["current_value_rappen"] == 2_100_000_00
    wealth_list = auth_client.get(f"/clients/{client_id}/wealth-positions")
    assert wealth_list.status_code == 200, wealth_list.text
    assert [row["id"] for row in wealth_list.json()] == [wealth_id]

    income_response = auth_client.post(
        f"/clients/{client_id}/cashflows",
        json={
            "cashflow_type": "Income",
            "label": "Lohn",
            "amount_rappen": 1_000_000,
            "frequency": "monatlich",
        },
    )
    expense_response = auth_client.post(
        f"/clients/{client_id}/cashflows",
        json={
            "cashflow_type": "Expense",
            "label": "Lebenskosten",
            "amount_rappen": 500_000,
            "frequency": "monatlich",
        },
    )
    assert income_response.status_code == 201, income_response.text
    assert expense_response.status_code == 201, expense_response.text
    cashflows = auth_client.get(f"/clients/{client_id}/cashflows")
    assert cashflows.status_code == 200, cashflows.text
    assert {row["label"] for row in cashflows.json()} == {"Lohn", "Lebenskosten"}
    cashflow_summary = auth_client.get(f"/clients/{client_id}/cashflow-summary")
    assert cashflow_summary.status_code == 200, cashflow_summary.text
    assert cashflow_summary.json()["recurring_net_rappen"] == 6_000_000

    goal_response = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json={
            "goal_family": "Vermögen",
            "goal_type": "Vermögensziel",
            "label": "Zielvermögen",
            "rank": 1,
            "weight_bps": 10000,
            "target_wealth_rappen": 3_000_000_00,
            "horizon_years": 10,
        },
    )
    assert goal_response.status_code == 201, goal_response.text
    goals = auth_client.get(f"/mandates/{mandate_id}/goals")
    assert goals.status_code == 200, goals.text
    assert goals.json()[0]["label"] == "Zielvermögen"
    assert goals.json()[0]["target_wealth_rappen"] == 3_000_000_00

    # Sprint 14 Phase 4 F10: vollstaendiges Risk-Payload — Validierung
    # _risk_assessment_has_current_questionnaire_answers fordert alle 11 Fragen
    # mit spezifischen Antwort-Markern (siehe portfolio_engine._CURRENT_RISK_ANSWER_POINTS
    # und _risk_answer_matches_current_questionnaire).
    risk_response = auth_client.post(
        f"/mandates/{mandate_id}/risk-assessments",
        json={
            "q_income_points": 4,
            "q_obligations_points": 4,
            "q_savings_points": 12,
            "q_wealth_points": 12,
            "investment_horizon_label": "Mehr als 12 Jahre",
            "investment_horizon_years": 12,
            "q_investment_goal_points": 4,
            "q_risk_preference_points": 4,
            "q_risk_behavior_points": 4,
            "knowledge_services_json": "{}",
            "knowledge_instruments_json": "{}",
            "income_sources_json": "[\"Berufliche Taetigkeit\"]",
            "answers": [
                {"question_number": 1, "question_section": "Kenntnisse",
                 "answer_label": "Finanzdienstleistungen: Beratung und Verwaltung", "answer_points": 0},
                {"question_number": 2, "question_section": "Kenntnisse",
                 "answer_label": "Finanzinstrumente: Anlagefonds und ETFs", "answer_points": 0},
                {"question_number": 3, "question_section": "Risikofaehigkeit",
                 "answer_label": "CHF 20'000 oder mehr", "answer_points": 4},
                {"question_number": 4, "question_section": "Risikofaehigkeit",
                 "answer_label": "Herkunft: Berufliche Taetigkeit, Vermoegensanlagen", "answer_points": 0},
                {"question_number": 5, "question_section": "Risikofaehigkeit",
                 "answer_label": "CHF 5'000 oder weniger", "answer_points": 4},
                {"question_number": 6, "question_section": "Risikofaehigkeit",
                 "answer_label": "CHF 2'000'000 oder mehr", "answer_points": 12},
                {"question_number": 7, "question_section": "Risikofaehigkeit",
                 "answer_label": "Mehr als 50 %", "answer_points": 12},
                {"question_number": 8, "question_section": "Risikofaehigkeit",
                 "answer_label": "Mehr als 12 Jahre - Matrix-Faktor", "answer_points": 0},
                {"question_number": 9, "question_section": "Risikobereitschaft",
                 "answer_label": "Das investierte Kapital soll sich stetig vermehren.", "answer_points": 3},
                {"question_number": 10, "question_section": "Risikobereitschaft",
                 "answer_label": "Ich strebe eine hoehere Rendite an und bin bereit, dafuer ein erhoehtes Risiko einzugehen.",
                 "answer_points": 3},
                {"question_number": 11, "question_section": "Risikobereitschaft",
                 "answer_label": "Ich kann den Verlust voruebergehend akzeptieren und halte an meinen Anlagen fest.",
                 "answer_points": 3},
            ],
        },
    )
    assert risk_response.status_code == 201, risk_response.text
    current_risk = auth_client.get(f"/mandates/{mandate_id}/risk-assessments/current")
    assert current_risk.status_code == 200, current_risk.text
    assert current_risk.json()["id"] == risk_response.json()["id"]
    assert current_risk.json()["answers"][0]["question_number"] == 1


def test_return_goal_cannot_be_saved_as_hard(auth_client, advisor_user):
    client_id = _create_client(auth_client, advisor_user)
    mandate_id = _create_mandate(auth_client, client_id, "FOUND-M-RETURN-HARD")

    response = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json={
            "goal_family": "Rendite",
            "goal_type": "Renditeziel",
            "label": "Renditeziel",
            "rank": 1,
            "goal_scope": "Beratungsvermögen",
            "target_return_bps": 450,
            "hardness": "Hart",
        },
    )

    assert response.status_code == 422, response.text
    assert "Renditeziel" in response.text


def test_return_goal_requires_positive_target_return(auth_client, advisor_user):
    client_id = _create_client(auth_client, advisor_user)
    mandate_id = _create_mandate(auth_client, client_id, "FOUND-M-RETURN-POS")

    response = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json={
            "goal_family": "Rendite",
            "goal_type": "Renditeziel",
            "label": "Renditeziel",
            "rank": 1,
            "goal_scope": "Beratungsvermögen",
            "target_return_bps": 0,
            "hardness": "Opportunistisch",
        },
    )

    assert response.status_code == 422, response.text
    assert "positive Zielrendite" in response.text


def test_goal_update_cannot_leave_stale_amount_when_switching_to_return_goal(auth_client, advisor_user):
    client_id = _create_client(auth_client, advisor_user)
    mandate_id = _create_mandate(auth_client, client_id, "FOUND-M-RETURN-STALE")
    goal = auth_client.post(
        f"/mandates/{mandate_id}/goals",
        json={
            "goal_family": "Cashflow",
            "goal_type": "Einmalige_Ausgabe",
            "label": "Eigenmittel",
            "rank": 1,
            "goal_scope": "Beratungsvermögen",
            "target_amount_rappen": 50_000_00,
            "target_date": "2030-01-01",
            "hardness": "Primär",
        },
    )
    assert goal.status_code == 201, goal.text

    response = auth_client.put(
        f"/mandates/{mandate_id}/goals/{goal.json()['id']}",
        json={
            "goal_family": "Rendite",
            "goal_type": "Renditeziel",
            "label": "Renditeziel",
            "target_return_bps": 450,
            "hardness": "Opportunistisch",
        },
    )

    assert response.status_code == 422, response.text
    assert "Zielbetrag" in response.text
