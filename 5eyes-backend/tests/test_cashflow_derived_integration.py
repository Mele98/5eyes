"""2026-06-14: Vermögensgetriebene Cashflows end-to-end.

/cashflows-derived liefert die abgeleiteten Posten; /cashflow-summary und
/cashflow-projection zählen sie MIT (zusammen mit manuell erfassten).
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
from models.wealth import Cashflow, WealthPosition
from services.auth import get_current_user


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'cf_derived.db'}",
                           connect_args={"check_same_thread": False})
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def advisor_user():
    return User(id="adv-cfd", username="adv", password_hash="h", full_name="Adv",
                role="advisor", is_active=1, created_at=_now(), updated_at=_now())


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


def _make_client(session_factory, advisor_id):
    cid = str(uuid.uuid4())
    with session_factory() as s:
        s.add(Client(id=cid, client_number=f"CFD-{cid[:6]}", first_name="Cash",
                     last_name="Test", advisor_id=advisor_id, created_at=_now(), updated_at=_now()))
        s.commit()
    return cid


def _add_position(session_factory, client_id, **fields):
    with session_factory() as s:
        s.add(WealthPosition(
            id=str(uuid.uuid4()), client_id=client_id,
            label=fields.pop("label", "P"),
            position_type=fields.pop("position_type", "Depot"),
            assignment=fields.pop("assignment", "Anderes Vermögen"),
            current_value_rappen=fields.pop("current_value_rappen", 0),
            currency="CHF", is_active=1, created_at=_now(), updated_at=_now(),
            **fields,
        ))
        s.commit()


def _add_cashflow(session_factory, client_id, **fields):
    with session_factory() as s:
        s.add(Cashflow(
            id=str(uuid.uuid4()), client_id=client_id,
            label=fields.pop("label", "Manual"),
            cashflow_type=fields.pop("cashflow_type", "Income"),
            amount_rappen=fields.pop("amount_rappen", 0),
            currency="CHF", frequency=fields.pop("frequency", "jährlich"),
            nature="wiederkehrend", is_active=1, created_at=_now(), updated_at=_now(),
            **fields,
        ))
        s.commit()


def test_derived_endpoint_lists_mortgage_and_rent(auth_client, session_factory, advisor_user):
    cid = _make_client(session_factory, advisor_user.id)
    _add_position(session_factory, cid, label="Hypothek EFH", position_type="Hypothek",
                  assignment="Verbindlichkeit", current_value_rappen=500_000_00,
                  mortgage_interest_rate_bps=150, mortgage_amortization_rappen=10_000_00)
    _add_position(session_factory, cid, label="Renditeobjekt", position_type="Immobilien",
                  current_value_rappen=900_000_00, property_rental_income_rappen=24_000_00)
    rows = auth_client.get(f"/clients/{cid}/cashflows-derived").json()
    labels = {r["label"]: r for r in rows}
    assert labels["Hypothekarzins: Hypothek EFH"]["amount_rappen"] == 750_000
    assert labels["Hypothekarzins: Hypothek EFH"]["is_derived"] == 1
    assert labels["Hypothekarzins: Hypothek EFH"]["cashflow_type"] == "Expense"
    assert labels["Amortisation: Hypothek EFH"]["amount_rappen"] == 10_000_00
    assert labels["Mieteinnahmen: Renditeobjekt"]["cashflow_type"] == "Income"
    assert labels["Mieteinnahmen: Renditeobjekt"]["amount_rappen"] == 24_000_00


def test_summary_includes_derived_alongside_manual(auth_client, session_factory, advisor_user):
    cid = _make_client(session_factory, advisor_user.id)
    this_year = datetime.date.today().year
    # Manuell: Lohn 100k/Jahr.
    _add_cashflow(session_factory, cid, label="Lohn", cashflow_type="Income",
                  amount_rappen=100_000_00, frequency="jährlich", valid_from=f"{this_year}-01-01")
    # Abgeleitet: Hypothekarzins 7'500 (Expense) + Miete 24'000 (Income).
    _add_position(session_factory, cid, label="H", position_type="Hypothek",
                  assignment="Verbindlichkeit", current_value_rappen=500_000_00,
                  mortgage_interest_rate_bps=150, valuation_date=f"{this_year}-01-01")
    _add_position(session_factory, cid, label="Immo", position_type="Immobilien",
                  current_value_rappen=900_000_00,
                  property_rental_income_rappen=24_000_00, valuation_date=f"{this_year}-01-01")
    body = auth_client.get(f"/clients/{cid}/cashflow-summary").json()
    # Einnahmen = Lohn 100k + Miete 24k = 124k; Ausgaben = Zins 7'500.
    assert body["recurring_income_rappen"] == 100_000_00 + 24_000_00
    assert body["recurring_expense_rappen"] == 750_000
    assert body["surplus_rappen"] == (100_000_00 + 24_000_00) - 750_000


def test_projection_includes_derived(auth_client, session_factory, advisor_user):
    cid = _make_client(session_factory, advisor_user.id)
    this_year = datetime.date.today().year
    _add_position(session_factory, cid, label="H", position_type="Hypothek",
                  assignment="Verbindlichkeit", current_value_rappen=400_000_00,
                  mortgage_interest_rate_bps=200, valuation_date=f"{this_year}-01-01")
    body = auth_client.get(f"/clients/{cid}/cashflow-projection?horizon_years=3").json()
    # 400k @ 2% = 8'000 CHF Zins -> Expense in jedem Jahr.
    first = body["years"][0]
    assert first["recurring_expense_rappen"] == 800_000


def test_no_positions_no_derived(auth_client, session_factory, advisor_user):
    cid = _make_client(session_factory, advisor_user.id)
    assert auth_client.get(f"/clients/{cid}/cashflows-derived").json() == []


def test_projection_reflects_direct_amortization_decline(auth_client, session_factory, advisor_user):
    """#31 B-2: direkte Amortisation senkt die Schuld → die wiederkehrende
    Ausgabe (Hypothekarzins) in der Cashflow-Projektion sinkt über die Jahre,
    der Netto-Cashflow steigt entsprechend."""
    cid = _make_client(session_factory, advisor_user.id)
    this_year = datetime.date.today().year
    _add_position(session_factory, cid, label="Hypothek", position_type="Hypothek",
                  assignment="Verbindlichkeit", current_value_rappen=500_000_00,
                  mortgage_interest_rate_bps=200, mortgage_amortization_rappen=100_000_00,
                  mortgage_amortization_type="Direkt", mortgage_type="Festhypothek",
                  valuation_date=f"{this_year}-01-01")
    years = auth_client.get(f"/clients/{cid}/cashflow-projection?horizon_years=4").json()["years"]
    # Zins: 2% von 500/400/300/200k = 10'000/8'000/6'000/4'000 CHF.
    assert years[3]["recurring_expense_rappen"] < years[0]["recurring_expense_rappen"]
    assert years[3]["net_rappen"] > years[0]["net_rappen"]
    # Differenz Jahr0->Jahr3 entspricht ~CHF 6'000 (600'000 Rappen) Zinsersparnis.
    assert (years[3]["net_rappen"] - years[0]["net_rappen"]) >= 400_000


def test_projection_indirect_amortization_constant_interest(auth_client, session_factory, advisor_user):
    """Gegenprobe: indirekte Amortisation lässt die Schuld (und damit den Zins) konstant."""
    cid = _make_client(session_factory, advisor_user.id)
    this_year = datetime.date.today().year
    _add_position(session_factory, cid, label="Hypothek", position_type="Hypothek",
                  assignment="Verbindlichkeit", current_value_rappen=500_000_00,
                  mortgage_interest_rate_bps=200, mortgage_amortization_rappen=100_000_00,
                  mortgage_amortization_type="Indirekt", mortgage_type="Festhypothek",
                  valuation_date=f"{this_year}-01-01")
    years = auth_client.get(f"/clients/{cid}/cashflow-projection?horizon_years=4").json()["years"]
    assert years[3]["recurring_expense_rappen"] == years[0]["recurring_expense_rappen"]
