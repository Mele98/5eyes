"""Z6 - C8: Audit-Anchors + zentrale Drift-Warnings.

Der TargetAllocation-Datensatz speichert ab jetzt zusaetzlich:
  - capital_market_assumptions_id (war F3 schon)
  - preferences_json (Snapshot der Mandatspraeferenzen)
  - input_snapshot_hash (Hash der WealthPositions+Cashflows+Goals)
  - advisory_wealth_at_generation_rappen
  - total_wealth_at_generation_rappen
  - reserve_needed_at_generation_rappen
  - external_reserve_at_generation_rappen

build_target_payload_from_allocation nutzt _strategy_drift_warnings()
um ALLE Drift-Quellen (Assessment, CMA, Inputs, Preferences, Reserve,
Legacy-Anker) zentral als reasoning-Hinweise auszugeben.
"""
from __future__ import annotations
import sys
import datetime
import json
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
    _compute_input_snapshot_hash,
    _strategy_drift_warnings,
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
        f"sqlite:///{tmp_path / 'audit_z6.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _seed(session_factory):
    advisor_id = "user-z6-1"
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
            id="pos-z6-1", client_id=cid,
            label="Depot", position_type="Depot", assignment="Beratungsvermögen",
            current_value_rappen=100_000_000, currency="CHF",
            alloc_equities_bps=4000, alloc_bonds_bps=3000,
            alloc_real_estate_bps=1000, alloc_liquidity_bps=1000, alloc_alternatives_bps=1000,
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


def test_c8_input_snapshot_hash_deterministic():
    """Hash ist deterministisch ueber gleichen Input."""
    pos = type("P", (), dict(id="p1", current_value_rappen=100, assignment="x",
                              position_type="Depot",
                              alloc_equities_bps=0, alloc_bonds_bps=0,
                              alloc_real_estate_bps=0, alloc_liquidity_bps=0,
                              alloc_alternatives_bps=0, property_usage=""))
    h1 = _compute_input_snapshot_hash(
        advisory_positions=[pos], cashflows=[], goals=[],
        advisory_wealth_rappen=100, total_wealth_rappen=100,
    )
    h2 = _compute_input_snapshot_hash(
        advisory_positions=[pos], cashflows=[], goals=[],
        advisory_wealth_rappen=100, total_wealth_rappen=100,
    )
    assert h1 == h2 and len(h1) == 64


def test_c8_input_snapshot_hash_changes_on_value_change():
    """Aendert sich Wealth-Wert, aendert sich der Hash."""
    pos1 = type("P", (), dict(id="p1", current_value_rappen=100, assignment="x",
                                position_type="Depot",
                                alloc_equities_bps=0, alloc_bonds_bps=0,
                                alloc_real_estate_bps=0, alloc_liquidity_bps=0,
                                alloc_alternatives_bps=0, property_usage=""))
    pos2 = type("P", (), dict(id="p1", current_value_rappen=200, assignment="x",
                                position_type="Depot",
                                alloc_equities_bps=0, alloc_bonds_bps=0,
                                alloc_real_estate_bps=0, alloc_liquidity_bps=0,
                                alloc_alternatives_bps=0, property_usage=""))
    h1 = _compute_input_snapshot_hash(
        advisory_positions=[pos1], cashflows=[], goals=[],
        advisory_wealth_rappen=100, total_wealth_rappen=100,
    )
    h2 = _compute_input_snapshot_hash(
        advisory_positions=[pos2], cashflows=[], goals=[],
        advisory_wealth_rappen=200, total_wealth_rappen=200,
    )
    assert h1 != h2


def test_c8_generate_persists_all_anchors(session_factory):
    """generate_target_allocation muss alle neuen Anker setzen."""
    advisor_id, cid, mid, aid = _seed(session_factory)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = generate_target_allocation(s, mandate, advisor_id, preferences=None)
        s.commit()
    ta = result["target_allocation"]
    assert ta.preferences_json, "preferences_json muss persistiert sein"
    assert json.loads(ta.preferences_json), "preferences_json muss valid JSON sein"
    assert ta.input_snapshot_hash and len(ta.input_snapshot_hash) == 64
    assert ta.advisory_wealth_at_generation_rappen == 100_000_000
    assert ta.total_wealth_at_generation_rappen >= 0
    assert ta.reserve_needed_at_generation_rappen is not None
    assert ta.external_reserve_at_generation_rappen is not None


def test_c8_drift_warnings_legacy_allocation_has_legacy_hint():
    """Legacy allocation (alle Anker NULL) bekommt 'incomplete anchors'."""
    legacy_alloc = TargetAllocation(
        id="legacy-1", mandate_id="m1", version=1, is_current=1,
        target_equities_bps=4500, target_bonds_bps=3500,
        target_real_estate_bps=1000, target_alternatives_bps=500,
        target_liquidity_bps=500,
        band_equities_min_bps=2500, band_equities_max_bps=5500,
        band_bonds_min_bps=2500, band_bonds_max_bps=4500,
        band_real_estate_min_bps=500, band_real_estate_max_bps=1500,
        band_alternatives_min_bps=300, band_alternatives_max_bps=800,
        band_liquidity_min_bps=200, band_liquidity_max_bps=800,
        based_on_assessment_id=None,
        capital_market_assumptions_id=None,
        input_snapshot_hash=None,
        policy_id="p1", set_by="u1", set_at=_now(),
        created_at=_now(), updated_at=_now(),
    )
    fake_assess = type("A", (), {"id": "a-current"})()
    fake_cma = type("C", (), {"id": "c-current"})()
    msgs = _strategy_drift_warnings(legacy_alloc, assessment=fake_assess, cma=fake_cma)
    assert any("Audit-Anker" in m for m in msgs), msgs


def test_c8_drift_warnings_input_hash_change_warns():
    """Allocation hat anderen input_snapshot_hash als current -> Warning."""
    alloc = TargetAllocation(
        id="a1", mandate_id="m1", version=1, is_current=1,
        target_equities_bps=4500, target_bonds_bps=3500,
        target_real_estate_bps=1000, target_alternatives_bps=500,
        target_liquidity_bps=500,
        band_equities_min_bps=2500, band_equities_max_bps=5500,
        band_bonds_min_bps=2500, band_bonds_max_bps=4500,
        band_real_estate_min_bps=500, band_real_estate_max_bps=1500,
        band_alternatives_min_bps=300, band_alternatives_max_bps=800,
        band_liquidity_min_bps=200, band_liquidity_max_bps=800,
        based_on_assessment_id="a-current",
        capital_market_assumptions_id="c-current",
        input_snapshot_hash="abc123" * 10 + "0000",  # 64 chars
        policy_id="p1", set_by="u1", set_at=_now(),
        created_at=_now(), updated_at=_now(),
    )
    fake_assess = type("A", (), {"id": "a-current"})()
    fake_cma = type("C", (), {"id": "c-current"})()
    msgs = _strategy_drift_warnings(
        alloc, assessment=fake_assess, cma=fake_cma,
        current_input_snapshot_hash="def" * 21 + "x",  # different
    )
    assert any("Vermoegen, Cashflows oder Ziele" in m for m in msgs), msgs


def test_c8_drift_warnings_preferences_change_warns():
    """preferences_json mismatch -> Warning."""
    alloc = TargetAllocation(
        id="a1", mandate_id="m1", version=1, is_current=1,
        target_equities_bps=4500, target_bonds_bps=3500,
        target_real_estate_bps=1000, target_alternatives_bps=500,
        target_liquidity_bps=500,
        band_equities_min_bps=2500, band_equities_max_bps=5500,
        band_bonds_min_bps=2500, band_bonds_max_bps=4500,
        band_real_estate_min_bps=500, band_real_estate_max_bps=1500,
        band_alternatives_min_bps=300, band_alternatives_max_bps=800,
        band_liquidity_min_bps=200, band_liquidity_max_bps=800,
        based_on_assessment_id="a-current",
        capital_market_assumptions_id="c-current",
        input_snapshot_hash="x" * 64,
        preferences_json='{"old": "prefs"}',
        policy_id="p1", set_by="u1", set_at=_now(),
        created_at=_now(), updated_at=_now(),
    )
    fake_assess = type("A", (), {"id": "a-current"})()
    fake_cma = type("C", (), {"id": "c-current"})()
    msgs = _strategy_drift_warnings(
        alloc, assessment=fake_assess, cma=fake_cma,
        current_input_snapshot_hash="x" * 64,
        current_preferences_json='{"new": "prefs"}',
    )
    assert any("Mandatspraeferenzen" in m for m in msgs), msgs


def test_c8_payload_includes_drift_warnings_after_input_change(session_factory):
    """Erzeuge Allokation, aendere Wealth-Position-Wert, build_payload muss
    Input-Drift-Warning ausgeben."""
    advisor_id, cid, mid, aid = _seed(session_factory)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        generate_target_allocation(s, mandate, advisor_id, preferences=None)
        s.commit()
    # Wealth-Position aendern
    with session_factory() as s:
        pos = s.query(WealthPosition).filter(WealthPosition.id == "pos-z6-1").first()
        pos.current_value_rappen = 150_000_000  # von 100M auf 150M
        pos.updated_at = _now()
        s.commit()
    # build_payload aufrufen
    with session_factory() as s:
        from services.portfolio_engine import ensure_runtime_reference_data
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
    reasoning = " ".join(payload.get("reasoning") or [])
    assert "Vermoegen, Cashflows oder Ziele" in reasoning, reasoning
