"""Vertrag mit dem Frontend: /clients/{id}/cashflow-summary liefert
annualisierte Cashflow-Werte (12x monatlich, 4x quartalsweise, 2x halbjaehrlich,
1x jaehrlich) und filtert laufende Cashflows korrekt nach valid_from/valid_until.

Dieser Test sichert F7/F8 aus dem Audit ab. Wenn er rot wird, hat sich der
BE-Vertrag geaendert und das Frontend muss nachgezogen werden.
"""
from __future__ import annotations
import sys
import uuid
import datetime
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
from models.clients import Client
from models.users import User
from models.wealth import Cashflow
from services.auth import get_current_user


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'cf_summary_contract.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def advisor_user():
    return User(
        id="user-cfsum-1", username="advisor", password_hash="h",
        full_name="Advisor", role="advisor", is_active=1,
        created_at=_utc_now_iso(), updated_at=_utc_now_iso(),
    )


@pytest.fixture()
def auth_client(session_factory, advisor_user):
    def override_db():
        with session_factory() as s:
            yield s
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: advisor_user
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _make_client(session_factory, advisor_id: str) -> str:
    cid = str(uuid.uuid4())
    now = _utc_now_iso()
    with session_factory() as s:
        s.add(Client(
            id=cid, client_number=f"CF-SUM-{cid[:6]}",
            first_name="Cash", last_name="Test",
            advisor_id=advisor_id, created_at=now, updated_at=now,
        ))
        s.commit()
    return cid


def _add_cashflow(session_factory, client_id: str, **fields):
    now = _utc_now_iso()
    with session_factory() as s:
        s.add(Cashflow(
            id=str(uuid.uuid4()),
            client_id=client_id,
            label=fields.pop("label", "Test"),
            cashflow_type=fields.pop("cashflow_type", "Income"),
            amount_rappen=fields.pop("amount_rappen", 0),
            currency="CHF",
            frequency=fields.pop("frequency", "jährlich"),
            nature=fields.pop("nature", "wiederkehrend"),
            valid_from=fields.pop("valid_from", None),
            valid_until=fields.pop("valid_until", None),
            is_active=1,
            created_at=now, updated_at=now,
            **fields,
        ))
        s.commit()


def test_monthly_income_is_annualized_in_summary(auth_client, session_factory, advisor_user):
    """Lohn 10'000 CHF/Monat erscheint im summary als 12 * 10'000 = 120'000 CHF p.a."""
    cid = _make_client(session_factory, advisor_user.id)
    this_year = datetime.date.today().year
    _add_cashflow(
        session_factory, cid,
        label="Lohn", cashflow_type="Income",
        amount_rappen=1_000_000, frequency="monatlich",
        valid_from=f"{this_year}-01-01",
    )
    resp = auth_client.get(f"/clients/{cid}/cashflow-summary")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["recurring_income_rappen"] == 12 * 1_000_000
    assert body["capital_inflow_rappen"] == 0
    assert body["total_income_rappen"] == 12 * 1_000_000


def test_quarterly_expense_is_annualized(auth_client, session_factory, advisor_user):
    """Steuerakontozahlung 5'000 CHF quartalsweise = 4 * 5'000 = 20'000 CHF p.a."""
    cid = _make_client(session_factory, advisor_user.id)
    this_year = datetime.date.today().year
    _add_cashflow(
        session_factory, cid,
        label="Steuer", cashflow_type="Expense",
        amount_rappen=500_000, frequency="quartalsweise",
        valid_from=f"{this_year}-01-01",
    )
    body = auth_client.get(f"/clients/{cid}/cashflow-summary").json()
    assert body["recurring_expense_rappen"] == 4 * 500_000
    assert body["total_expense_rappen"] == 4 * 500_000


def test_semiannual_income_is_annualized(auth_client, session_factory, advisor_user):
    """Bonus 20'000 CHF halbjaehrlich = 2 * 20'000 = 40'000 CHF p.a."""
    cid = _make_client(session_factory, advisor_user.id)
    this_year = datetime.date.today().year
    _add_cashflow(
        session_factory, cid,
        label="Bonus", cashflow_type="Income",
        amount_rappen=2_000_000, frequency="halbjährlich",
        valid_from=f"{this_year}-01-01",
    )
    body = auth_client.get(f"/clients/{cid}/cashflow-summary").json()
    assert body["recurring_income_rappen"] == 2 * 2_000_000


def test_expired_cashflow_excluded_from_current_year(auth_client, session_factory, advisor_user):
    """Cashflow mit valid_until im Vorjahr darf nicht mehr im aktuellen Jahr erscheinen."""
    cid = _make_client(session_factory, advisor_user.id)
    this_year = datetime.date.today().year
    last_year = this_year - 1
    _add_cashflow(
        session_factory, cid,
        label="Alter Lohn", cashflow_type="Income",
        amount_rappen=1_000_000, frequency="monatlich",
        valid_from=f"{last_year - 1}-01-01",
        valid_until=f"{last_year}-12-31",
    )
    body = auth_client.get(f"/clients/{cid}/cashflow-summary").json()
    assert body["recurring_income_rappen"] == 0
    assert body["surplus_rappen"] == 0


def test_future_cashflow_excluded_from_current_year(auth_client, session_factory, advisor_user):
    """Cashflow mit valid_from in der Zukunft darf nicht im aktuellen Jahr erscheinen."""
    cid = _make_client(session_factory, advisor_user.id)
    future_year = datetime.date.today().year + 5
    _add_cashflow(
        session_factory, cid,
        label="Zukuenftiger Lohn", cashflow_type="Income",
        amount_rappen=1_000_000, frequency="monatlich",
        valid_from=f"{future_year}-01-01",
    )
    body = auth_client.get(f"/clients/{cid}/cashflow-summary").json()
    assert body["recurring_income_rappen"] == 0


def test_one_off_in_current_year_counted_as_capital(auth_client, session_factory, advisor_user):
    """Einmaliger 3a-Bezug im aktuellen Jahr landet in capital_inflow, NICHT in recurring."""
    cid = _make_client(session_factory, advisor_user.id)
    this_year = datetime.date.today().year
    _add_cashflow(
        session_factory, cid,
        label="3a-Bezug", cashflow_type="Income",
        amount_rappen=10_000_000, frequency="einmalig", nature="einmalig",
        valid_from=f"{this_year}-06-30", valid_until=f"{this_year}-06-30",
    )
    body = auth_client.get(f"/clients/{cid}/cashflow-summary").json()
    assert body["capital_inflow_rappen"] == 10_000_000
    assert body["recurring_income_rappen"] == 0
    assert body["total_income_rappen"] == 10_000_000


def test_combined_monthly_income_and_yearly_expense(auth_client, session_factory, advisor_user):
    """Lohn 10k/Monat + Versicherung 4k/Jahr -> 120k Income, 4k Expense, 116k Saldo."""
    cid = _make_client(session_factory, advisor_user.id)
    this_year = datetime.date.today().year
    _add_cashflow(
        session_factory, cid,
        label="Lohn", cashflow_type="Income",
        amount_rappen=1_000_000, frequency="monatlich",
        valid_from=f"{this_year}-01-01",
    )
    _add_cashflow(
        session_factory, cid,
        label="Versicherung", cashflow_type="Expense",
        amount_rappen=400_000, frequency="jährlich",
        valid_from=f"{this_year}-01-01",
    )
    body = auth_client.get(f"/clients/{cid}/cashflow-summary").json()
    assert body["recurring_income_rappen"] == 12 * 1_000_000
    assert body["recurring_expense_rappen"] == 400_000
    assert body["surplus_rappen"] == 12 * 1_000_000 - 400_000
