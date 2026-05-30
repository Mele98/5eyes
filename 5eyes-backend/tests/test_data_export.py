"""Sprint U-10 — Tests fuer services.data_export.

Strategie
---------
- Realistisches In-Memory-DB-Setup (analog test_advisory_report.py)
- Seedet einen Kunden mit Mandat + Profiling + Wealth-Daten
- Pruefen: Schema-Stabilitaet, Mandantentrennung, Manifest-Counts,
  Legal-Basis-Block.
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import configure_mappers, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
configure_mappers()

from models.clients import Client, ClientNationality
from models.mandates import Mandate
from models.profiling import RiskAssessment, SuitabilityCheck
from models.users import User
from models.wealth import Cashflow, Goal, WealthPosition
from services.data_export import SCHEMA_VERSION, RETENTION_NOTES, export_client_data


_NOW = "2026-05-30T08:00:00.000Z"


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'export.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
        bind=engine,
    )
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _seed_full_client(s) -> tuple[Client, Mandate, User]:
    advisor = User(
        id=str(uuid.uuid4()),
        username=f"adv-{uuid.uuid4().hex[:6]}",
        password_hash="h",
        full_name="Anna Beraterin",
        role="advisor",
        is_active=1,
        created_at=_NOW,
        updated_at=_NOW,
    )
    s.add(advisor)
    client = Client(
        id=str(uuid.uuid4()),
        client_number=f"C-{uuid.uuid4().hex[:6]}",
        first_name="Hans",
        last_name="Muster",
        date_of_birth="1976-03-14",
        advisor_id=advisor.id,
        country_of_residence="CH",
        canton="ZH",
        language="DE",
        created_at=_NOW,
        updated_at=_NOW,
    )
    s.add(client)
    s.add(ClientNationality(
        id=str(uuid.uuid4()),
        client_id=client.id,
        country_code="CH",
        is_primary=1,
        created_at=_NOW,
    ))
    mandate = Mandate(
        id=str(uuid.uuid4()),
        client_id=client.id,
        mandate_number=f"M-{uuid.uuid4().hex[:6]}",
        mandate_type="Anlageberatung",
        opened_at=_NOW,
        created_at=_NOW,
        updated_at=_NOW,
    )
    s.add(mandate)
    s.add(WealthPosition(
        id=str(uuid.uuid4()),
        client_id=client.id,
        position_type="Bankkonto",
        label="Hauptkonto",
        current_value_rappen=10_000_000,  # CHF 100'000
        currency="CHF",
        is_active=1,
        assignment="Beratungsvermögen",
        created_at=_NOW,
        updated_at=_NOW,
    ))
    s.add(Cashflow(
        id=str(uuid.uuid4()),
        client_id=client.id,
        cashflow_type="Income",
        label="Lohn",
        amount_rappen=1_500_000,
        frequency="monatlich",
        is_active=1,
        created_at=_NOW,
        updated_at=_NOW,
    ))
    s.add(Goal(
        id=str(uuid.uuid4()),
        mandate_id=mandate.id,
        client_id=client.id,
        goal_family="Vermoegensaufbau",
        goal_type="Vermögensaufbau",
        label="Pension mit 65",
        target_amount_rappen=150_000_000,
        target_date="2041-03-14",
        hardness="Primaer",
        rank=1,
        is_active=1,
        created_at=_NOW,
        updated_at=_NOW,
    ))
    s.add(RiskAssessment(
        id=str(uuid.uuid4()),
        mandate_id=mandate.id,
        version=1, is_current=1, valid_from=_NOW,
        q_income_points=3, q_obligations_points=2,
        q_savings_points=3, q_wealth_points=3,
        risk_capacity_total=11,
        risk_capacity_profile="Wachstumsorientiert",
        investment_horizon_years=15,
        investment_horizon_label="Langfristig",
        risk_capacity_score_x10=75,
        q_investment_goal_points=4,
        q_risk_preference_points=3,
        q_risk_behavior_points=2,
        risk_willingness_total=9,
        risk_willingness_profile="Ausgewogen",
        risk_willingness_score_x10=60,
        final_score_x10=68,
        final_profile="Ausgewogen",
        assessed_at=_NOW, assessed_by=advisor.id,
        created_at=_NOW, updated_at=_NOW,
    ))
    s.add(SuitabilityCheck(
        id=str(uuid.uuid4()),
        mandate_id=mandate.id,
        client_id=client.id,
        duty_type="suitability",
        result="passed",
        result_notes="Eignung gegeben.",
        checked_by=advisor.id,
        checked_at=_NOW,
        created_at=_NOW,
        updated_at=_NOW,
    ))
    s.flush()
    return client, mandate, advisor


# ---------------------------------------------------------------------------
# Schema-Stabilitaet
# ---------------------------------------------------------------------------

def test_export_returns_expected_top_level_keys(session_factory):
    with session_factory() as s:
        client, _, _ = _seed_full_client(s)
        s.commit()
        payload = export_client_data(s, client.id)

    expected_top = {
        "schema_version",
        "exported_at",
        "client_id",
        "client_number",
        "legal_basis",
        "retention_notes",
        "manifest",
        "sections",
    }
    assert set(payload.keys()) == expected_top
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["exported_at"].endswith("Z")


def test_legal_basis_block_documents_dsg(session_factory):
    with session_factory() as s:
        client, _, _ = _seed_full_client(s)
        s.commit()
        payload = export_client_data(s, client.id)

    lb = payload["legal_basis"]
    assert "DSG" in lb["primary"]
    assert "Art. 25" in lb["primary"]
    assert "JSON" in lb["format"].upper()
    assert any("FIDLEG" in s for s in lb["supplementary"])
    assert any("OR Art. 962" in s for s in lb["supplementary"])


def test_retention_notes_cover_all_section_tables(session_factory):
    with session_factory() as s:
        client, _, _ = _seed_full_client(s)
        s.commit()
        payload = export_client_data(s, client.id)

    # client ist Sonder-Sektion (dict, nicht Liste der Tabelle "clients")
    section_keys = set(payload["sections"].keys()) - {"client"}
    retention_keys = set(RETENTION_NOTES.keys()) - {"clients"}
    missing = section_keys - retention_keys
    assert not missing, f"Sektionen ohne Retention-Note: {missing}"


# ---------------------------------------------------------------------------
# Inhalt
# ---------------------------------------------------------------------------

def test_client_section_contains_personal_data(session_factory):
    with session_factory() as s:
        client, _, _ = _seed_full_client(s)
        s.commit()
        payload = export_client_data(s, client.id)

    cs = payload["sections"]["client"]
    assert cs["first_name"] == "Hans"
    assert cs["last_name"] == "Muster"
    assert cs["date_of_birth"] == "1976-03-14"
    assert cs["country_of_residence"] == "CH"


def test_mandates_section_contains_clients_mandate(session_factory):
    with session_factory() as s:
        client, mandate, _ = _seed_full_client(s)
        s.commit()
        payload = export_client_data(s, client.id)

    mandates = payload["sections"]["mandates"]
    assert len(mandates) == 1
    assert mandates[0]["id"] == mandate.id
    assert mandates[0]["client_id"] == client.id


def test_risk_assessment_and_suitability_are_exported(session_factory):
    with session_factory() as s:
        client, _, _ = _seed_full_client(s)
        s.commit()
        payload = export_client_data(s, client.id)

    assert len(payload["sections"]["risk_assessments"]) == 1
    assert payload["sections"]["risk_assessments"][0]["final_profile"] == "Ausgewogen"
    assert len(payload["sections"]["suitability_checks"]) == 1
    assert payload["sections"]["suitability_checks"][0]["result"] == "passed"


def test_wealth_and_cashflow_and_goal_are_exported(session_factory):
    with session_factory() as s:
        client, _, _ = _seed_full_client(s)
        s.commit()
        payload = export_client_data(s, client.id)

    assert len(payload["sections"]["wealth_positions"]) == 1
    assert payload["sections"]["wealth_positions"][0]["current_value_rappen"] == 10_000_000
    assert len(payload["sections"]["cashflows"]) == 1
    assert payload["sections"]["cashflows"][0]["frequency"] == "monatlich"
    assert len(payload["sections"]["goals"]) == 1
    assert payload["sections"]["goals"][0]["label"] == "Pension mit 65"


def test_manifest_counts_match_section_sizes(session_factory):
    with session_factory() as s:
        client, _, _ = _seed_full_client(s)
        s.commit()
        payload = export_client_data(s, client.id)

    for key, count in payload["manifest"].items():
        section = payload["sections"][key]
        actual = 1 if isinstance(section, dict) else len(section)
        assert actual == count, f"manifest[{key!r}]={count} != actual {actual}"


# ---------------------------------------------------------------------------
# Mandantentrennung
# ---------------------------------------------------------------------------

def test_export_does_not_leak_other_clients_data(session_factory):
    """Wichtiger Datenschutz-Check: Export von Kunde A enthaelt KEINE
    Datensaetze von Kunde B."""
    with session_factory() as s:
        client_a, _, advisor = _seed_full_client(s)
        # Zweiter Kunde mit eigenem Mandat + WealthPosition
        client_b = Client(
            id=str(uuid.uuid4()),
            client_number="C-OTHER",
            first_name="Beat",
            last_name="Beispiel",
            advisor_id=advisor.id,
            country_of_residence="CH",
            created_at=_NOW,
            updated_at=_NOW,
        )
        s.add(client_b)
        mandate_b = Mandate(
            id=str(uuid.uuid4()),
            client_id=client_b.id,
            mandate_number="M-OTHER",
            mandate_type="Anlageberatung",
            opened_at=_NOW,
            created_at=_NOW,
            updated_at=_NOW,
        )
        s.add(mandate_b)
        s.add(WealthPosition(
            id=str(uuid.uuid4()),
            client_id=client_b.id,
            position_type="Bankkonto",
            label="OTHER-CLIENT-DATA",
            current_value_rappen=99_999_999,
            currency="CHF",
            is_active=1,
            created_at=_NOW,
            updated_at=_NOW,
        ))
        s.commit()
        payload = export_client_data(s, client_a.id)

    # Serialisierter Volltext darf NICHTS von Kunde B enthalten
    raw = json.dumps(payload)
    assert "OTHER-CLIENT-DATA" not in raw
    assert "C-OTHER" not in raw
    assert "Beat" not in raw
    assert "Beispiel" not in raw
    assert str(client_b.id) not in raw
    assert str(mandate_b.id) not in raw


# ---------------------------------------------------------------------------
# Robustheit
# ---------------------------------------------------------------------------

def test_export_raises_when_client_missing(session_factory):
    with session_factory() as s:
        with pytest.raises(ValueError, match="nicht gefunden"):
            export_client_data(s, "no-such-client-id")


def test_export_works_for_client_without_mandates(session_factory):
    """Kunde ohne Mandate -> client-Section + leere Listen, kein Crash."""
    with session_factory() as s:
        advisor = User(
            id=str(uuid.uuid4()),
            username="adv",
            password_hash="h",
            full_name="A",
            role="advisor",
            is_active=1,
            created_at=_NOW,
            updated_at=_NOW,
        )
        s.add(advisor)
        client = Client(
            id=str(uuid.uuid4()),
            client_number="C-NEW",
            first_name="Neu",
            last_name="Kunde",
            advisor_id=advisor.id,
            country_of_residence="CH",
            created_at=_NOW,
            updated_at=_NOW,
        )
        s.add(client)
        s.commit()
        payload = export_client_data(s, client.id)

    assert payload["sections"]["client"]["first_name"] == "Neu"
    assert payload["sections"]["mandates"] == []
    assert payload["sections"]["risk_assessments"] == []
    assert payload["sections"]["wealth_positions"] == []
    # Manifest stimmt trotzdem
    assert payload["manifest"]["mandates"] == 0


def test_export_payload_is_json_serializable(session_factory):
    """Alles muss durch json.dumps gehen — kein Datetime, kein Bytes."""
    with session_factory() as s:
        client, _, _ = _seed_full_client(s)
        s.commit()
        payload = export_client_data(s, client.id)

    # Wirft TypeError wenn nicht serialisierbar
    blob = json.dumps(payload)
    assert len(blob) > 1000
