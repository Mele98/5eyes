from pathlib import Path
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from main import app  # noqa: F401 - registers all mapped models for create_all
from models.clients import Client
from models.users import User
from models.wealth import Cashflow
from routers.wealth import update_cashflow
from schemas.wealth import CashflowUpdate


FRONTEND = (
    Path(__file__).resolve().parents[2]
    / "5eyes-electron"
    / "frontend"
    / "5eyes_v2.html"
)


def test_cashflow_update_accepts_type_change():
    update = CashflowUpdate(cashflow_type="Expense", currency="CHF")

    assert update.model_dump(exclude_unset=True) == {
        "cashflow_type": "Expense",
        "currency": "CHF",
    }


def test_cashflow_update_rejects_unknown_type():
    with pytest.raises(ValidationError):
        CashflowUpdate(cashflow_type="Outflow")


def test_cashflow_update_persists_income_to_expense(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'cashflow-type.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    with session_factory() as db:
        user = User(
            id="advisor-cf-type",
            username="advisor-cf-type",
            password_hash="not-used",
            full_name="Cashflow Advisor",
            role="advisor",
            is_active=1,
            created_at=now,
            updated_at=now,
        )
        client = Client(
            id="client-cf-type",
            client_number="CF-TYPE-1",
            first_name="Cashflow",
            last_name="Contract",
            country_of_residence="CH",
            language="DE",
            household_type="Einzelperson",
            client_classification="Privatkunde",
            advisor_id=user.id,
            created_at=now,
            updated_at=now,
        )
        cashflow = Cashflow(
            id="cashflow-cf-type",
            client_id=client.id,
            cashflow_type="Income",
            label="Lebenshaltungskosten",
            amount_rappen=5_300_000,
            currency="CHF",
            frequency="jährlich",
            nature="wiederkehrend",
            is_active=1,
            created_at=now,
            updated_at=now,
        )
        db.add_all([user, client, cashflow])
        db.commit()

        response = update_cashflow(
            client.id,
            cashflow.id,
            CashflowUpdate(cashflow_type="Expense"),
            db,
            user,
        )

        assert response.cashflow_type == "Expense"
        assert db.get(Cashflow, cashflow.id).cashflow_type == "Expense"

    engine.dispose()


def test_income_and_expense_create_actions_have_explicit_defaults():
    html = FRONTEND.read_text(encoding="utf-8")

    assert 'openNewCashflow(\'Income\')">Einnahme erfassen' in html
    assert 'openNewCashflow(\'Expense\')">Ausgabe erfassen' in html
    assert 'openNewCashflow(\'Income\')">+ Zufluss' in html
    assert 'openNewCashflow(\'Expense\')">+ Abfluss' in html


def test_new_cashflow_helper_sets_requested_type_before_opening():
    html = FRONTEND.read_text(encoding="utf-8")

    assert "function openNewCashflow(cashflowType)" in html
    assert "resetCashflowModal(cashflowType);" in html
    assert "defaultCashflowType==='Expense'?'Expense':'Income'" in html
