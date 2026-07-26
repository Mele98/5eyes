"""2026-07-25 (Generalaudit, Wave 13 -- Wealth-Router- + FX-Rate-Fork).

- PlanningAssumptionCreate: retirement_age/life_expectancy/inflation_
  assumption_bps/pension_indexation_bps hatten keinen Bounds-Check --
  fliessen direkt in die MC-Simulation/Ziel-Projektion JEDES Berichts
  fuer das Mandat ein.
- upsert_fx_rates (routers/fx_rates.py): keine Obergrenze auf rate --
  wirkt global auf ALLE Tenants/Mandate (kein tenant_id auf FXRate).
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError
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
from schemas.wealth import PlanningAssumptionCreate


def _now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


# ── PlanningAssumption bounds (reine Pydantic-Unit-Tests) ──────────────────

def test_planning_assumption_rejects_absurd_inflation():
    with pytest.raises(ValidationError):
        PlanningAssumptionCreate(inflation_assumption_bps=-50000)


def test_planning_assumption_rejects_absurd_retirement_age():
    with pytest.raises(ValidationError):
        PlanningAssumptionCreate(retirement_age_primary=5)


def test_planning_assumption_rejects_absurd_life_expectancy():
    with pytest.raises(ValidationError):
        PlanningAssumptionCreate(life_expectancy_primary=500)


def test_planning_assumption_accepts_plausible_values():
    pa = PlanningAssumptionCreate(
        retirement_age_primary=65, life_expectancy_primary=95,
        inflation_assumption_bps=150, pension_indexation_bps=100,
    )
    assert pa.retirement_age_primary == 65
    assert pa.inflation_assumption_bps == 150


def test_planning_assumption_allows_omitted_fields():
    pa = PlanningAssumptionCreate()
    assert pa.retirement_age_primary is None
    assert pa.inflation_assumption_bps is None


# ── FX-Rate upper bound (Endpoint-Ebene, kein Pydantic-Field) ──────────────

@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'fx_rates_bounds.db'}",
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
        id="advisor-fx-bounds", username="advisor-fx-bounds", password_hash="h",
        full_name="FX Advisor", role="advisor", is_active=1,
        created_at=_now_iso(), updated_at=_now_iso(),
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


def test_fx_rate_upsert_rejects_absurdly_high_rate(auth_client, session_factory):
    from models.fx_rate import FXRate

    resp = auth_client.put("/fx-rates", json={"rates": [{"currency": "usd", "rate": 99999.0}]})
    assert resp.status_code == 422, resp.text
    with session_factory() as s:
        assert s.query(FXRate).filter(FXRate.currency == "USD").count() == 0


def test_fx_rate_upsert_accepts_plausible_rate(auth_client):
    resp = auth_client.put("/fx-rates", json={"rates": [{"currency": "usd", "rate": 0.92}]})
    assert resp.status_code == 200, resp.text
