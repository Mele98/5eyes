"""Regressions-Lock #96: Verzehr- / Sequence-of-Returns-Kennzahl.

Anteil der MC-Pfade, deren Vermoegen VOR Horizontende aufgezehrt ist
(Pfad-Total <= 0), plus mittleres Erschoepfungsjahr. Misst das
Sequence-of-Returns-Risiko (schlechte Renditen frueh im Verzehr zehren das
Kapital schneller auf). In der Akkumulation (keine Netto-Entnahmen) = 0 %.

Exponiert in monte_carlo: target_/current_depletion_probability_pct +
target_/current_depletion_median_year.
"""
from __future__ import annotations

import datetime
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy.orm import configure_mappers
from database import Base
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth, tenant,
)
configure_mappers()

from models.clients import Client
from models.mandates import Mandate
from models.profiling import RiskAssessment
from models.users import User
from models.wealth import Goal, WealthPosition
from services.portfolio_engine import (
    _sequence_of_returns_depletion,
    ensure_runtime_reference_data,
    generate_target_allocation,
)
from tests.risk_fixture_helpers import (
    CURRENT_RISK_SCHEMA_MARKERS,
    add_current_risk_answers,
)


# ── Unit: die Kennzahl-Logik ─────────────────────────────────────────────────────

def test_depletion_probability_and_median_year():
    # 4 Pfade: 2 erschoepfen (Offset 3 und 5), 2 nie.
    offsets = [3, None, 5, None]
    pct, median_year = _sequence_of_returns_depletion(offsets, 2026)
    assert pct == 50                       # 2 von 4
    assert median_year == 2026 + 5         # Median der betroffenen Offsets {3,5} -> oberer Mittelwert


def test_no_depletion_is_zero_and_none():
    pct, median_year = _sequence_of_returns_depletion([None, None, None], 2026)
    assert pct == 0
    assert median_year is None


def test_empty_offsets_safe():
    pct, median_year = _sequence_of_returns_depletion([], 2026)
    assert pct == 0
    assert median_year is None


def test_full_depletion_hundred_percent():
    pct, _ = _sequence_of_returns_depletion([1, 2, 3], 2026)
    assert pct == 100


# ── Integration: Engine exponiert die Kennzahl, Akkumulation = 0 % ──────────────

def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'sor_depletion.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _seed_accumulation_mandate(session_factory):
    advisor_id = "user-sor"
    cid, mid, aid = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    now = _now()
    with session_factory() as s:
        s.add(User(id=advisor_id, username="adv-sor", password_hash="h",
                   full_name="Adv", role="advisor", is_active=1,
                   created_at=now, updated_at=now))
        s.add(Client(id=cid, client_number=f"C-{cid[:6]}", first_name="T", last_name="Sor",
                     advisor_id=advisor_id, created_at=now, updated_at=now))
        s.add(Mandate(id=mid, client_id=cid, mandate_number=f"M-{mid[:6]}",
                      mandate_type="Anlageberatung", opened_at=now,
                      created_at=now, updated_at=now))
        s.add(WealthPosition(
            id="pos-sor-depot", client_id=cid, label="Depot", position_type="Depot",
            assignment="Beratungsvermögen", current_value_rappen=500_000_00, currency="CHF",
            alloc_equities_bps=5000, alloc_bonds_bps=3000, alloc_liquidity_bps=1000,
            alloc_alternatives_bps=1000, is_active=1, created_at=now, updated_at=now,
        ))
        s.add(Goal(
            id="goal-sor", mandate_id=mid, client_id=cid, goal_family="Vermoegen",
            goal_type="Vermoegensziel", goal_scope="Beratungsvermoegen", label="Wachstum",
            rank=1, weight_bps=10000, target_wealth_rappen=800_000_00, horizon_years=10,
            hardness="Primaer", value_mode="nominal", is_active=1,
            created_at=now, updated_at=now,
        ))
        s.add(RiskAssessment(
            id=aid, mandate_id=mid, version=1, is_current=1, valid_from=now[:10],
            q_income_points=2, q_obligations_points=3, q_savings_points=6, q_wealth_points=6,
            risk_capacity_total=17, risk_capacity_profile="Dynamisch",
            risk_capacity_score_x10=70, investment_horizon_years=10,
            investment_horizon_label="8 bis 11 Jahre",
            q_investment_goal_points=3, q_risk_preference_points=3, q_risk_behavior_points=3,
            risk_willingness_total=9, risk_willingness_profile="Wachstumsorientiert",
            risk_willingness_score_x10=70, final_score_x10=70,
            final_profile="Wachstumsorientiert",
            is_overridden=0, **CURRENT_RISK_SCHEMA_MARKERS,
            assessed_at=now, assessed_by=advisor_id, created_at=now, updated_at=now,
        ))
        add_current_risk_answers(s, aid, now)
        s.commit()
        ensure_runtime_reference_data(s, advisor_id)
        s.commit()
    return advisor_id, mid


def test_engine_exposes_depletion_keys_and_accumulation_is_zero(session_factory):
    advisor_id, mid = _seed_accumulation_mandate(session_factory)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = generate_target_allocation(s, mandate, advisor_id, preferences=None)

    mc = result.get("monte_carlo") or {}
    # Wiring: alle vier Kennzahlen vorhanden + korrekt typisiert.
    assert "target_depletion_probability_pct" in mc
    assert "current_depletion_probability_pct" in mc
    assert isinstance(mc["target_depletion_probability_pct"], int)
    assert isinstance(mc["current_depletion_probability_pct"], int)
    assert mc["target_depletion_median_year"] is None or isinstance(mc["target_depletion_median_year"], int)
    # Reine Akkumulation (kein Verzehr): das Vermoegen wird nie aufgezehrt.
    assert mc["target_depletion_probability_pct"] == 0
    assert mc["target_depletion_median_year"] is None
