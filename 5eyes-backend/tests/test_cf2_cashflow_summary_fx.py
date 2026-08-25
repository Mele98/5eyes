"""CF-2 (Audit 2026-06-24, backend-engine): /clients/{id}/cashflow-summary rief
totals_for_year() ohne fx_source auf -> Fremdwaehrungs-Cashflows wurden im
Rohbetrag statt zu CHF konvertiert gezeigt (der Schwester-Endpoint
cashflow-projection wurde bereits am 2026-07-16 gefixt, cashflow-summary war
uebersehen). Dieser Test sichert die Nachbesserung vom 2026-07-23 ab:
totals_for_year() bekommt jetzt fx_source=FXRateSource.from_db(db) +
target_currency='CHF', analog zur Projection.
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
        f"sqlite:///{tmp_path / 'cf2_summary_fx.db'}",
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
        id="user-cf2-1", username="advisor-cf2", password_hash="h",
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
            id=cid, client_number=f"CF2-{cid[:6]}",
            first_name="FX", last_name="Test",
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
            currency=fields.pop("currency", "CHF"),
            frequency=fields.pop("frequency", "jährlich"),
            nature=fields.pop("nature", "wiederkehrend"),
            valid_from=fields.pop("valid_from", None),
            valid_until=fields.pop("valid_until", None),
            is_active=1,
            created_at=now, updated_at=now,
            **fields,
        ))
        s.commit()


def test_usd_income_is_converted_to_chf_in_summary(auth_client, session_factory, advisor_user):
    """USD-Lohn 10'000/Jahr muss im Summary zum FX-Default-Kurs (0.88) als
    8'800 CHF erscheinen -- vorher (Bug) wurde der USD-Rohbetrag 1:1 als CHF
    ausgegeben (10'000 statt 8'800)."""
    cid = _make_client(session_factory, advisor_user.id)
    this_year = datetime.date.today().year
    _add_cashflow(
        session_factory, cid,
        label="US-Lohn", cashflow_type="Income",
        amount_rappen=1_000_000, currency="USD", frequency="jährlich",
        valid_from=f"{this_year}-01-01",
    )
    resp = auth_client.get(f"/clients/{cid}/cashflow-summary")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Default FX-Rate USD->CHF = 0.88 (DEFAULT_FX_RATES, kein DB-Override in diesem Test).
    assert body["recurring_income_rappen"] == pytest.approx(880_000, abs=1)
    assert body["total_income_rappen"] == pytest.approx(880_000, abs=1)


def test_chf_income_unaffected_by_fx_conversion(auth_client, session_factory, advisor_user):
    """CHF-Cashflows bleiben unveraendert (Identity-Konvertierung, keine Regression)."""
    cid = _make_client(session_factory, advisor_user.id)
    this_year = datetime.date.today().year
    _add_cashflow(
        session_factory, cid,
        label="CH-Lohn", cashflow_type="Income",
        amount_rappen=1_000_000, currency="CHF", frequency="jährlich",
        valid_from=f"{this_year}-01-01",
    )
    body = auth_client.get(f"/clients/{cid}/cashflow-summary").json()
    assert body["recurring_income_rappen"] == 1_000_000
