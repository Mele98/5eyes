"""Sprint A (2026-05-06) — Quick-Wins-Tests.

Verifiziert:
- A1: WealthInflow CRUD + Integration in cashflow_projection_series
- A2: Max-Pension-Spending Rechner (Itô-korrigierte Annuitaet)
- A3: retirement_year + life_expectancy_year auf mandates → MC-Horizont
- A4: Smooth-Decay opt-in via RESERVE_DECAY_MODE=smooth
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, configure_mappers

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base, get_db
from main import app
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
configure_mappers()

import services.portfolio_engine as pe
from models.clients import Client
from models.mandates import Mandate
from models.profiling import RiskAssessment, RiskAssessmentAnswer
from models.users import User
from models.wealth import Cashflow, Goal, WealthInflow, WealthPosition
from services.auth import get_current_user, require_advisor


def _now() -> str:
    return datetime.now().isoformat() + "Z"


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'sprint_a.db'}",
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
def cleanup_overrides():
    yield
    app.dependency_overrides.clear()


def _seed_mandate(session_factory, suffix: str = ""):
    suffix = suffix or str(uuid.uuid4())[:6]
    advisor_id = f"user-spA-{suffix}"
    cid = str(uuid.uuid4())
    mid = str(uuid.uuid4())
    aid = str(uuid.uuid4())
    now = _now()
    today = date.today()

    with session_factory() as s:
        s.add(User(id=advisor_id, username=f"adv-{suffix}", password_hash="h",
                   full_name="Adv", role="advisor", is_active=1,
                   created_at=now, updated_at=now))
        s.add(Client(id=cid, client_number=f"C-{cid[:6]}",
                     first_name="Test", last_name="Mandant",
                     advisor_id=advisor_id, created_at=now, updated_at=now))
        s.add(Mandate(id=mid, client_id=cid, mandate_number=f"M-{mid[:6]}",
                      mandate_type="Anlageberatung", opened_at=now,
                      created_at=now, updated_at=now))
        s.add(WealthPosition(
            id=f"pos-{suffix}", client_id=cid,
            label="Depot", position_type="Depot", assignment="Beratungsvermögen",
            current_value_rappen=500_000_00, currency="CHF",
            alloc_equities_bps=4000, alloc_bonds_bps=3000,
            alloc_real_estate_bps=0, alloc_liquidity_bps=2000,
            alloc_alternatives_bps=1000,
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(RiskAssessment(
            id=aid, mandate_id=mid, version=1, is_current=1, valid_from=now[:10],
            q_income_points=2, q_obligations_points=3,
            q_savings_points=8, q_wealth_points=8,
            risk_capacity_total=21, risk_capacity_profile="Wachstumsorientiert",
            risk_capacity_score_x10=70,
            investment_horizon_years=15, investment_horizon_label="12 bis 17 Jahre",
            q_investment_goal_points=3, q_risk_preference_points=4, q_risk_behavior_points=3,
            risk_willingness_total=10, risk_willingness_profile="Wachstumsorientiert",
            risk_willingness_score_x10=70,
            final_score_x10=70, final_profile="Wachstumsorientiert",
            is_overridden=0,
            assessed_at=now, assessed_by=advisor_id,
            created_at=now, updated_at=now,
        ))
        for q in (3, 5, 6, 7, 8, 9, 10, 11):
            s.add(RiskAssessmentAnswer(
                id=str(uuid.uuid4()), assessment_id=aid,
                question_number=q, question_section="Risikoprofil",
                answer_label=f"A{q}", answer_points=2, created_at=now,
            ))
        s.commit()
        from services.portfolio_engine import ensure_runtime_reference_data
        ensure_runtime_reference_data(s, advisor_id)
        s.commit()
    return advisor_id, cid, mid, aid


def _client_with_user(session_factory, user):
    def override_db():
        with session_factory() as s:
            yield s
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[require_advisor] = lambda: user
    return TestClient(app)


# ============================================================================
# A1: WealthInflow CRUD + Integration
# ============================================================================


def test_a1_wealth_inflow_crud(session_factory, cleanup_overrides):
    advisor_id, cid, mid, _ = _seed_mandate(session_factory)
    with session_factory() as s:
        advisor = s.query(User).filter(User.id == advisor_id).first()
    client = _client_with_user(session_factory, advisor)

    # CREATE
    resp = client.post(
        f"/clients/{cid}/wealth-inflows",
        json={"label": "Erbschaft Tante", "source_type": "Erbschaft",
              "amount_rappen": 10_000_000, "expected_year": 2030,
              "value_mode": "nominal"},
    )
    assert resp.status_code == 201, resp.text
    inflow_id = resp.json()["id"]

    # LIST
    resp = client.get(f"/clients/{cid}/wealth-inflows")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["source_type"] == "Erbschaft"

    # UPDATE
    resp = client.put(f"/wealth-inflows/{inflow_id}", json={"amount_rappen": 12_000_000})
    assert resp.status_code == 200
    assert resp.json()["amount_rappen"] == 12_000_000

    # DELETE
    resp = client.delete(f"/wealth-inflows/{inflow_id}")
    assert resp.status_code == 204

    # LIST ist jetzt leer
    resp = client.get(f"/clients/{cid}/wealth-inflows")
    assert resp.status_code == 200
    assert resp.json() == []


def test_a1_wealth_inflow_recurring_validation(session_factory, cleanup_overrides):
    """Recurring=1 ohne frequency oder duration -> 422."""
    advisor_id, cid, mid, _ = _seed_mandate(session_factory)
    with session_factory() as s:
        advisor = s.query(User).filter(User.id == advisor_id).first()
    client = _client_with_user(session_factory, advisor)

    resp = client.post(
        f"/clients/{cid}/wealth-inflows",
        json={"label": "Bonus", "source_type": "Bonus",
              "amount_rappen": 500_000, "expected_year": 2027,
              "is_recurring": 1, "value_mode": "nominal"},
    )
    assert resp.status_code == 422


def test_a1_inflow_series_one_time():
    """Helper: einmaliger Inflow im erwarteten Jahr."""
    from types import SimpleNamespace
    inflows = [SimpleNamespace(
        is_active=1, amount_rappen=10_000_000, expected_year=2031,
        is_recurring=0, frequency=None, duration_years=None, value_mode="nominal",
    )]
    s = pe._wealth_inflow_series_rappen(inflows, 10, 2026, None)
    assert s[5] == 10_000_000
    assert sum(s) == 10_000_000


def test_a1_inflow_series_recurring_annual():
    """Helper: jaehrliche recurring inflow ueber 4 Jahre."""
    from types import SimpleNamespace
    inflows = [SimpleNamespace(
        is_active=1, amount_rappen=1_200_000, expected_year=2029,
        is_recurring=1, frequency="jaehrlich", duration_years=4, value_mode="nominal",
    )]
    s = pe._wealth_inflow_series_rappen(inflows, 10, 2026, None)
    assert s[3] == 1_200_000
    assert s[6] == 1_200_000
    assert s[7] == 0
    assert sum(s) == 4_800_000


def test_a1_inflow_real_value_mode_inflation_adjusted():
    """value_mode=real: Inflation kumulativ aufgezinst."""
    from types import SimpleNamespace
    inflows = [SimpleNamespace(
        is_active=1, amount_rappen=10_000_000, expected_year=2031,
        is_recurring=0, frequency=None, duration_years=None, value_mode="real",
    )]
    inflation_series = [150] * 10  # 1.5% pro Jahr
    s = pe._wealth_inflow_series_rappen(inflows, 10, 2026, inflation_series)
    # Year 5 (offset 5): 10M * 1.015^5 ≈ 10.77M
    expected = int(round(10_000_000 * (1.015 ** 5)))
    assert abs(s[5] - expected) < 100  # Toleranz für rounding


# ============================================================================
# A2: Max-Pension-Spending Rechner
# ============================================================================


def test_a2_max_pension_spending_endpoint(session_factory, cleanup_overrides):
    """POST /goals/calculate-max-pension-spending: Annuitaet liefert plausibles Resultat."""
    advisor_id, cid, mid, _ = _seed_mandate(session_factory)
    with session_factory() as s:
        advisor = s.query(User).filter(User.id == advisor_id).first()
    client = _client_with_user(session_factory, advisor)

    resp = client.post(
        f"/mandates/{mid}/goals/calculate-max-pension-spending",
        json={"retirement_year": 2035, "life_expectancy_year": 2065,
              "value_mode": "real", "safety_margin_pct": 0},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # 500k Vermoegen, 30J Auszahlung, ~3% real return → Annuität ~25k/J real.
    assert body["years_in_retirement"] == 30
    assert body["max_annual_chf_rappen"] > 0
    assert body["max_monthly_chf_rappen"] == body["max_annual_chf_rappen"] // 12
    assert body["max_annual_chf_rappen"] < 500_000_00  # < Vermoegen
    # 500k Vermoegen, 30J Horizont: Annuitaet sollte zwischen 10k und 50k CHF/Jahr liegen
    assert 10_000_00 < body["max_annual_chf_rappen"] < 50_000_00
    assert "Itô" in " ".join(body["reasoning"]) or "Annuität" in " ".join(body["reasoning"])


def test_a2_max_pension_spending_safety_margin_reduces(session_factory, cleanup_overrides):
    """Mit safety_margin_pct=20 ist die Annuitaet kleiner als ohne."""
    advisor_id, cid, mid, _ = _seed_mandate(session_factory)
    with session_factory() as s:
        advisor = s.query(User).filter(User.id == advisor_id).first()
    client = _client_with_user(session_factory, advisor)

    base = client.post(
        f"/mandates/{mid}/goals/calculate-max-pension-spending",
        json={"retirement_year": 2035, "life_expectancy_year": 2065,
              "value_mode": "real", "safety_margin_pct": 0},
    ).json()
    safe = client.post(
        f"/mandates/{mid}/goals/calculate-max-pension-spending",
        json={"retirement_year": 2035, "life_expectancy_year": 2065,
              "value_mode": "real", "safety_margin_pct": 20},
    ).json()
    assert safe["max_annual_chf_rappen"] < base["max_annual_chf_rappen"]
    # 20% safety margin -> ca. 80% von base
    ratio = safe["max_annual_chf_rappen"] / base["max_annual_chf_rappen"]
    assert 0.78 <= ratio <= 0.82


def test_a2_max_pension_spending_validation(session_factory, cleanup_overrides):
    """life_expectancy_year <= retirement_year -> 422."""
    advisor_id, cid, mid, _ = _seed_mandate(session_factory)
    with session_factory() as s:
        advisor = s.query(User).filter(User.id == advisor_id).first()
    client = _client_with_user(session_factory, advisor)

    resp = client.post(
        f"/mandates/{mid}/goals/calculate-max-pension-spending",
        json={"retirement_year": 2065, "life_expectancy_year": 2035,
              "value_mode": "real"},
    )
    assert resp.status_code == 422


# ============================================================================
# A3: Lebenserwartung & Renteneintritt → Horizont
# ============================================================================


def test_a3_life_expectancy_extends_horizon(session_factory):
    """mandate.life_expectancy_year erhoeht den Simulation-Horizont."""
    advisor_id, cid, mid, _ = _seed_mandate(session_factory)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        # Default-Horizont (kein life_expectancy gesetzt)
        h_default = pe._simulation_horizon_years({}, [], mandate)
        # Mit Lebenserwartung 30 Jahre in der Zukunft
        future_year = date.today().year + 30
        mandate.life_expectancy_year = future_year
        s.commit()
        h_extended = pe._simulation_horizon_years({}, [], mandate)
    assert h_extended >= 30
    assert h_extended >= h_default


def test_a3_no_mandate_uses_default(session_factory):
    """Ohne mandate-Parameter weiterhin alter Default."""
    h = pe._simulation_horizon_years({}, [], None)
    assert h == pe.DEFAULT_SIMULATION_HORIZON_YEARS


# ============================================================================
# A4: Smooth-Decay Feature-Flag
# ============================================================================


def test_a4_smooth_decay_off_by_default(monkeypatch):
    """Ohne env var: Stufenfunktion (audit-konsistent)."""
    monkeypatch.delenv("RESERVE_DECAY_MODE", raising=False)
    assert pe._reserve_decay_mode_smooth() is False


def test_a4_smooth_decay_opt_in(monkeypatch):
    """Mit RESERVE_DECAY_MODE=smooth: smooth decay aktiv."""
    monkeypatch.setenv("RESERVE_DECAY_MODE", "smooth")
    assert pe._reserve_decay_mode_smooth() is True


def test_a4_decay_factor_table():
    """Decay-Tabelle plausibel: monoton fallend, Plateau bei ≤1J, clamp bei 0.05."""
    f0 = pe._reserve_decay_factor(0)
    f1 = pe._reserve_decay_factor(1)
    f3 = pe._reserve_decay_factor(3)
    f5 = pe._reserve_decay_factor(5)
    f10 = pe._reserve_decay_factor(10)
    f30 = pe._reserve_decay_factor(30)
    assert f0 == 1.0
    assert f1 == 1.0  # Plateau
    assert f3 == 0.90
    assert 0.5 < f5 < 0.8  # Decay ab Year 4
    assert 0.05 < f10 < 0.5
    assert f30 == 0.05  # Clamp-Min
