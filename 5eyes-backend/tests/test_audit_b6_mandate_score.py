"""B6 - Mandate-Score Aggregation im Backend.

Bisher: Backend lieferte goal_analysis pro Goal, aber keinen aggregierten
Mandats-Score. FE musste aggregieren -> Logik nicht im Audit-Anker, kann
unbemerkt driften.

Wissenschaftlich (ASIP §3.2 / FRP 1, Brunel 2006 Integrated Wealth Management,
FINMA RS 2017/2): Multi-Goal-Aggregation ist methodisch heikel - separate
Anspruchsklassen (z.B. PK-Pflichtteil vs. ueberobligatorisch) duerfen NICHT
einfach aggregiert werden. Best Practice: ZWEI Aggregate liefern:

  weighted_score: gewichteter Mittelwert aller goal_scores nach
    weight_bps * hardness_multiplier_bps. Strategie-Sicht: zeigt
    Gesamterfolg.

  weakest_hard_score: min(score) ueber alle Goals mit hardness=Hart.
    Compliance-Sicht: zeigt den schwaechsten Pflicht-Punkt; PK-konsistent
    (Mindestleistung muss eingehalten werden).

B6.1 _build_mandate_score liefert beide Aggregate
B6.2 weakest_hard_score: None wenn keine harten Goals
B6.3 weighted_score: Hardness-Gewichtung im Multiplier
B6.4 In target_payload eingebaut
"""
from __future__ import annotations
import sys
import datetime
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
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
configure_mappers()

from services.portfolio_engine import _build_mandate_score


# ============================================================================
# B6.1 - _build_mandate_score: Basis
# ============================================================================

def test_b6_no_goals_returns_none():
    score = _build_mandate_score([])
    assert score["weighted_score"] is None
    assert score["weakest_hard_score"] is None
    assert score["weakest_hard_goal_id"] is None


def test_b6_single_goal_weighted_equals_score():
    """Ein Goal -> weighted_score = goal.achievement_score."""
    score = _build_mandate_score([
        {"goal_id": "g1", "achievement_score": 75, "weight_bps": 5000, "hardness": "Primaer"},
    ])
    assert score["weighted_score"] == 75


def test_b6_three_goals_weighted_average():
    """Drei Primaer-Goals mit gleichem weight_bps -> arithmetic mean."""
    goals = [
        {"goal_id": "g1", "achievement_score": 90, "weight_bps": 3000, "hardness": "Primaer"},
        {"goal_id": "g2", "achievement_score": 60, "weight_bps": 3000, "hardness": "Primaer"},
        {"goal_id": "g3", "achievement_score": 30, "weight_bps": 3000, "hardness": "Primaer"},
    ]
    score = _build_mandate_score(goals)
    # alle gleich gewichtet -> Mittel = 60
    assert score["weighted_score"] == 60


# ============================================================================
# B6.2 - weakest_hard
# ============================================================================

def test_b6_weakest_hard_picks_min_hard_score():
    goals = [
        {"goal_id": "g1", "achievement_score": 90, "weight_bps": 5000, "hardness": "Primaer"},
        {"goal_id": "g2", "achievement_score": 80, "weight_bps": 3000, "hardness": "Hart"},
        {"goal_id": "g3", "achievement_score": 45, "weight_bps": 2000, "hardness": "Hart"},
        {"goal_id": "g4", "achievement_score": 10, "weight_bps": 2000, "hardness": "Opportunistisch"},
    ]
    score = _build_mandate_score(goals)
    assert score["weakest_hard_score"] == 45
    assert score["weakest_hard_goal_id"] == "g3"


def test_b6_weakest_hard_none_when_no_hard_goals():
    goals = [
        {"goal_id": "g1", "achievement_score": 50, "weight_bps": 5000, "hardness": "Opportunistisch"},
        {"goal_id": "g2", "achievement_score": 40, "weight_bps": 5000, "hardness": "Primaer"},
    ]
    score = _build_mandate_score(goals)
    assert score["weakest_hard_score"] is None
    assert score["weakest_hard_goal_id"] is None


# ============================================================================
# B6.3 - Hardness-Multiplikator im weighted Score
# ============================================================================

def test_b6_hardness_multiplier_in_weighted():
    """Hartes Goal mit gleichem weight_bps zaehlt 2x staerker als primaer (Multiplier 20000 vs 10000),
    opportunistisch zaehlt 0.4x (Multiplier 4000)."""
    goals = [
        # Hartes Goal mit Score 100, weight 1000 -> effective 1000*2 = 2000
        {"goal_id": "g_hart", "achievement_score": 100, "weight_bps": 1000, "hardness": "Hart"},
        # Opportunistisches Goal mit Score 0, weight 1000 -> effective 1000*0.4 = 400
        {"goal_id": "g_opp", "achievement_score": 0, "weight_bps": 1000, "hardness": "Opportunistisch"},
    ]
    score = _build_mandate_score(goals)
    # weighted = (100*2000 + 0*400) / 2400 = 200000/2400 ≈ 83.33 -> 83
    assert score["weighted_score"] == 83


# ============================================================================
# B6.4 - In target_payload eingebaut
# ============================================================================

from models.clients import Client
from models.mandates import Mandate
from models.profiling import RiskAssessment, RiskAssessmentAnswer
from models.users import User
from models.wealth import Goal, WealthPosition
from services.portfolio_engine import (
    ensure_runtime_reference_data,
    generate_target_allocation,
)
from tests.risk_fixture_helpers import (
    CURRENT_RISK_SCHEMA_MARKERS,
    add_current_risk_answers,
)


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'audit_b6.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_b6_payload_contains_mandate_score(session_factory):
    """target_payload nach generate_target_allocation muss mandate_score enthalten."""
    advisor_id = "user-b6-1"
    cid = str(uuid.uuid4())
    mid = str(uuid.uuid4())
    aid = str(uuid.uuid4())
    now = _now()
    with session_factory() as s:
        s.add(User(id=advisor_id, username="adv", password_hash="h",
                   full_name="Adv", role="advisor", is_active=1,
                   created_at=now, updated_at=now))
        s.add(Client(id=cid, client_number=f"C-{cid[:6]}",
                     first_name="T", last_name="X",
                     advisor_id=advisor_id, created_at=now, updated_at=now))
        s.add(Mandate(id=mid, client_id=cid, mandate_number=f"M-{mid[:6]}",
                      mandate_type="Anlageberatung", opened_at=now,
                      created_at=now, updated_at=now))
        s.add(WealthPosition(
            id="pos-b6", client_id=cid,
            label="Depot", position_type="Depot", assignment="Beratungsvermögen",
            current_value_rappen=500_000_00, currency="CHF",
            alloc_equities_bps=5000, alloc_bonds_bps=3000,
            alloc_real_estate_bps=0, alloc_liquidity_bps=1000,
            alloc_alternatives_bps=1000,
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(Goal(
            id="goal-b6-1", mandate_id=mid, client_id=cid,
            goal_family="Vermoegen", goal_type="Vermoegensziel",
            label="Pension", rank=1, weight_bps=5000,
            target_wealth_rappen=1_000_000_00,
            horizon_years=10, hardness="Hart",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(RiskAssessment(
            id=aid, mandate_id=mid, version=1, is_current=1, valid_from=now[:10],
            q_income_points=2, q_obligations_points=3,
            q_savings_points=6, q_wealth_points=6,
            risk_capacity_total=17, risk_capacity_profile="Wachstumsorientiert",
            risk_capacity_score_x10=60,
            investment_horizon_years=10, investment_horizon_label="8 bis 11 Jahre",
            q_investment_goal_points=3, q_risk_preference_points=3, q_risk_behavior_points=3,
            risk_willingness_total=9, risk_willingness_profile="Ausgewogen",
            risk_willingness_score_x10=60,
            final_score_x10=60, final_profile="Ausgewogen",
            is_overridden=0,
            **CURRENT_RISK_SCHEMA_MARKERS,
            assessed_at=now, assessed_by=advisor_id,
            created_at=now, updated_at=now,
        ))
        add_current_risk_answers(s, aid, now)
        s.commit()
        ensure_runtime_reference_data(s, advisor_id)
        s.commit()
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = generate_target_allocation(s, mandate, advisor_id, preferences=None)
    mandate_score = result.get("mandate_score")
    assert mandate_score is not None, "target_payload muss mandate_score enthalten"
    assert "weighted_score" in mandate_score
    assert "weakest_hard_score" in mandate_score
    assert "weakest_hard_goal_id" in mandate_score
    assert "method" in mandate_score
    # Ein hartes Goal vorhanden -> weakest_hard nicht None
    assert mandate_score["weakest_hard_score"] is not None
    assert mandate_score["weakest_hard_goal_id"] == "goal-b6-1"
