"""Z7 - C7: StrategyContext Single-Source-of-Truth Refactor.

Reserve-Berechnung wird zentral in _compute_reserve_for_inputs gehandelt.
Dieselben Inputs MUESSEN zwischen generate_target_allocation und
build_target_payload_from_allocation identische reserve_needed_rappen
und external_reserve_rappen liefern - keine Drift mehr.

C7.1 _compute_reserve_for_inputs ist deterministisch und pure.
C7.2 manueller Reserve-Override aus prefs.limits.minReserve wird hochgenommen.
C7.3 negativer recurring Cashflow erhoeht Reserve auf abs(cf)*3.
C7.4 generate-Pfad und rebuild-Pfad liefern identische Reserve-Zahlen.
C7.5 externe Reserve nur wenn uncapped_bps > saa_liquidity_ceiling_bps.
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

from models.allocation import TargetAllocation
from models.clients import Client
from models.mandates import Mandate
from models.profiling import RiskAssessment
from models.users import User
from models.wealth import Cashflow, Goal, WealthPosition
from services.portfolio_engine import (
    _compute_reserve_for_inputs,
    build_target_payload_from_allocation,
    ensure_runtime_reference_data,
    generate_target_allocation,
)
from tests.risk_fixture_helpers import CURRENT_RISK_SCHEMA_MARKERS, add_current_risk_answers


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'audit_z7.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


# ============================================================================
# C7.1 - _compute_reserve_for_inputs ist deterministisch
# ============================================================================

def test_c7_1_pure_helper_no_inputs_returns_zero():
    needed, external = _compute_reserve_for_inputs(
        goals=[], limits_prefs={}, asset_class_prefs={},
        recurring_net_cashflow_rappen=0,
        recurring_cashflow_projection_series_rappen=[],
        advisory_wealth_rappen=1_000_000_00,
        saa_liquidity_ceiling_bps=300,
    )
    assert needed == 0 and external == 0


def test_c7_1_pure_helper_deterministic():
    """Zwei identische Aufrufe -> identische Resultate."""
    args = dict(
        goals=[], limits_prefs={"minReserve": "50000"}, asset_class_prefs={},
        recurring_net_cashflow_rappen=-1_000_00,
        recurring_cashflow_projection_series_rappen=[-1_000_00, -1_000_00, -1_000_00],
        advisory_wealth_rappen=1_000_000_00,
        saa_liquidity_ceiling_bps=300,
    )
    r1 = _compute_reserve_for_inputs(**args)
    r2 = _compute_reserve_for_inputs(**args)
    assert r1 == r2


# ============================================================================
# C7.2 - manueller Reserve-Override
# ============================================================================

def test_c7_2_manual_reserve_override():
    """prefs.limits.minReserve=50000 CHF -> mind. 50000_00 Rappen Reserve."""
    needed, _ = _compute_reserve_for_inputs(
        goals=[],
        limits_prefs={"minReserve": "50000"},
        asset_class_prefs={},
        recurring_net_cashflow_rappen=0,
        recurring_cashflow_projection_series_rappen=[0, 0, 0],
        advisory_wealth_rappen=10_000_000_00,
        saa_liquidity_ceiling_bps=300,
    )
    assert needed >= 50_000_00


# ============================================================================
# C7.3 - negativer recurring Cashflow
# ============================================================================

def test_c7_3_negative_recurring_cashflow_3x():
    """Negativer recurring Cashflow -> Reserve = abs(cf)*3."""
    needed, _ = _compute_reserve_for_inputs(
        goals=[], limits_prefs={}, asset_class_prefs={},
        recurring_net_cashflow_rappen=-2_000_00,
        recurring_cashflow_projection_series_rappen=[],
        advisory_wealth_rappen=10_000_000_00,
        saa_liquidity_ceiling_bps=300,
    )
    assert needed == 6_000_00, f"Erwartet 6000_00, got {needed}"


# ============================================================================
# C7.5 - externe Reserve nur ueber SAA-Cap
# ============================================================================

def test_c7_5_no_external_reserve_within_cap():
    """Reserve im SAA-Cap (3% von 1M = 30_000) -> keine externe Reserve."""
    needed, external = _compute_reserve_for_inputs(
        goals=[], limits_prefs={"minReserve": "20000"},
        asset_class_prefs={},
        recurring_net_cashflow_rappen=0,
        recurring_cashflow_projection_series_rappen=[],
        advisory_wealth_rappen=1_000_000_00,
        saa_liquidity_ceiling_bps=300,
    )
    assert needed == 20_000_00
    assert external == 0


def test_c7_5_external_reserve_above_cap():
    """Reserve groesser als SAA-Cap -> Differenz wird extern gefuehrt."""
    needed, external = _compute_reserve_for_inputs(
        goals=[], limits_prefs={"minReserve": "100000"},
        asset_class_prefs={},
        recurring_net_cashflow_rappen=0,
        recurring_cashflow_projection_series_rappen=[],
        advisory_wealth_rappen=1_000_000_00,
        saa_liquidity_ceiling_bps=300,
    )
    assert needed == 100_000_00
    saa_cap_rappen = int(round(300 * 1_000_000_00 / 10000))
    assert external == 100_000_00 - saa_cap_rappen


# ============================================================================
# C7.4 - generate-Pfad und rebuild-Pfad liefern identische Reserve
# ============================================================================

def _seed(session_factory):
    advisor_id = "user-z7-1"
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
            id="pos-z7-1", client_id=cid,
            label="Depot", position_type="Depot", assignment="Beratungsvermögen",
            current_value_rappen=100_000_000, currency="CHF",
            alloc_equities_bps=4000, alloc_bonds_bps=3000,
            alloc_real_estate_bps=1000, alloc_liquidity_bps=1000,
            alloc_alternatives_bps=1000,
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(Cashflow(
            id="cf-z7-1", client_id=cid, label="Lohn",
            cashflow_type="Income", amount_rappen=8_000_00,
            currency="CHF", frequency="monatlich", nature="wiederkehrend",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(Cashflow(
            id="cf-z7-2", client_id=cid, label="Miete",
            cashflow_type="Expense", amount_rappen=10_000_00,
            currency="CHF", frequency="monatlich", nature="wiederkehrend",
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
    return advisor_id, cid, mid, aid


def test_c7_4_generate_and_rebuild_reserve_identical(session_factory):
    """generate persistiert reserve_needed_at_generation_rappen + external_reserve_at_generation_rappen.
    build_target_payload_from_allocation MUSS daraus dieselben Zahlen rekonstruieren.
    """
    advisor_id, cid, mid, aid = _seed(session_factory)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = generate_target_allocation(s, mandate, advisor_id, preferences=None)
        s.commit()
    ta = result["target_allocation"]
    generated_reserve = ta.reserve_needed_at_generation_rappen
    generated_external = ta.external_reserve_at_generation_rappen
    assert generated_reserve is not None
    assert generated_external is not None

    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        allocation = s.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mid,
            TargetAllocation.is_current == 1,
        ).first()
        assessment = s.query(RiskAssessment).filter(RiskAssessment.id == aid).first()
        policy, cma = ensure_runtime_reference_data(s, advisor_id)
        payload = build_target_payload_from_allocation(
            db=s, mandate=mandate, allocation=allocation,
            policy=policy, cma=cma, assessment=assessment, preferences=None,
        )

    rebuild_reserve = int(payload.get("reserve_needed_rappen") or 0)
    rebuild_external = int(payload.get("external_reserve_rappen") or 0)
    assert rebuild_reserve == generated_reserve, (
        f"Drift: generate={generated_reserve}, rebuild={rebuild_reserve}"
    )
    assert rebuild_external == generated_external, (
        f"External-Drift: generate={generated_external}, rebuild={rebuild_external}"
    )
