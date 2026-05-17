"""F3 - CMA-Versionierung in TargetAllocation.

- TargetAllocation.capital_market_assumptions_id wird beim Erzeugen gesetzt
  (= cma.id zur Generierungszeit).
- build_target_payload_from_allocation warnt im reasoning, wenn die
  aktuelle CMA von der gespeicherten abweicht.
- Bestehende Allocations ohne capital_market_assumptions_id (Legacy)
  loesen die Warnung NICHT aus.
"""
from __future__ import annotations
import sys
import uuid
import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base
from models.allocation import (
    CapitalMarketAssumption,
    OptimizerPolicy,
    TargetAllocation,
)
from models.clients import Client
from models.mandates import Mandate
from models.profiling import RiskAssessment
from models.users import User
from models.wealth import WealthPosition
from services.portfolio_engine import (
    build_target_payload_from_allocation,
    ensure_runtime_reference_data,
    generate_target_allocation,
)
from tests.risk_fixture_helpers import CURRENT_RISK_SCHEMA_MARKERS, add_current_risk_answers


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'audit_f3_cma.db'}",
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
    """Erzeugt Advisor + Client + Mandat + RuntimeReferenz + RiskAssessment + Position."""
    advisor_id = "user-f3-1"
    cid = str(uuid.uuid4())
    mid = str(uuid.uuid4())
    aid = str(uuid.uuid4())
    now = _utc_now_iso()
    with session_factory() as s:
        s.add(User(
            id=advisor_id, username="advisor", password_hash="h",
            full_name="Advisor", role="advisor", is_active=1,
            created_at=now, updated_at=now,
        ))
        s.add(Client(
            id=cid, client_number=f"C-F3-{cid[:6]}",
            first_name="Test", last_name="Mandant",
            advisor_id=advisor_id, created_at=now, updated_at=now,
        ))
        s.add(Mandate(
            id=mid, client_id=cid, mandate_number=f"M-F3-{mid[:6]}",
            mandate_type="Anlageberatung", opened_at=now,
            created_at=now, updated_at=now,
        ))
        s.add(WealthPosition(
            id=str(uuid.uuid4()), client_id=cid,
            label="Test-Depot", position_type="Depot",
            assignment="Beratungsvermögen",
            current_value_rappen=1_000_000_00, currency="CHF",
            alloc_equities_bps=4000, alloc_bonds_bps=3000,
            alloc_real_estate_bps=1000, alloc_liquidity_bps=1000, alloc_alternatives_bps=1000,
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(RiskAssessment(
            id=aid, mandate_id=mid, version=1, is_current=1,
            valid_from=now[:10],
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
    return advisor_id, cid, mid, aid


def test_f3_generate_persists_capital_market_assumptions_id(session_factory):
    """Eine neu generierte TargetAllocation muss capital_market_assumptions_id
    gleich der aktuellen CMA haben."""
    advisor_id, cid, mid, aid = _seed(session_factory)
    with session_factory() as s:
        ensure_runtime_reference_data(s, advisor_id)
        s.commit()
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = generate_target_allocation(s, mandate, advisor_id, preferences=None)
        s.commit()
        ta = result["target_allocation"]
        cma = s.query(CapitalMarketAssumption).filter(CapitalMarketAssumption.is_current == 1).first()
        assert ta.capital_market_assumptions_id == cma.id, (
            "TargetAllocation muss die CMA-ID der Generierungszeit speichern."
        )


def test_f3_payload_warns_when_cma_changed(session_factory):
    """Wechselt die aktuelle CMA, muss build_target_payload_from_allocation
    eine Drift-Warnung im reasoning ausgeben."""
    advisor_id, cid, mid, aid = _seed(session_factory)
    with session_factory() as s:
        ensure_runtime_reference_data(s, advisor_id)
        s.commit()
    # Allocation generieren (erzeugt cma_id-Bindung)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        generate_target_allocation(s, mandate, advisor_id, preferences=None)
        s.commit()

    # Neue CMA-Version "publishen" - alte als nicht-aktuell markieren, neue anlegen
    with session_factory() as s:
        old_cma = s.query(CapitalMarketAssumption).filter(CapitalMarketAssumption.is_current == 1).first()
        old_cma.is_current = 0
        new_cma = CapitalMarketAssumption(
            id=str(uuid.uuid4()),
            assumption_set_name=old_cma.assumption_set_name,
            version=int(old_cma.version or 1) + 1,
            valid_from=_utc_now_iso()[:10],
            is_current=1,
            bonds_chf_ig_return_bps=old_cma.bonds_chf_ig_return_bps,
            bonds_chf_ig_vol_bps=old_cma.bonds_chf_ig_vol_bps,
            bonds_fx_hedged_return_bps=old_cma.bonds_fx_hedged_return_bps,
            bonds_fx_hedged_vol_bps=old_cma.bonds_fx_hedged_vol_bps,
            equity_ch_return_bps=old_cma.equity_ch_return_bps,
            equity_ch_vol_bps=old_cma.equity_ch_vol_bps,
            equity_intl_return_bps=old_cma.equity_intl_return_bps,
            equity_intl_vol_bps=old_cma.equity_intl_vol_bps,
            real_estate_ch_return_bps=old_cma.real_estate_ch_return_bps,
            real_estate_ch_vol_bps=old_cma.real_estate_ch_vol_bps,
            alternatives_gold_return_bps=old_cma.alternatives_gold_return_bps,
            alternatives_gold_vol_bps=old_cma.alternatives_gold_vol_bps,
            liquidity_return_bps=old_cma.liquidity_return_bps,
            liquidity_vol_bps=old_cma.liquidity_vol_bps,
            inflation_path_json=old_cma.inflation_path_json,
            correlation_matrix_json=old_cma.correlation_matrix_json,
            sub_asset_class_assumptions_json=old_cma.sub_asset_class_assumptions_json,
            source=old_cma.source,
            created_by=advisor_id,
            created_at=_utc_now_iso(), updated_at=_utc_now_iso(),
        )
        s.add(new_cma)
        s.commit()

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
    reasoning = " ".join(payload.get("reasoning") or [])
    assert "Kapitalmarktannahmen" in reasoning or "CMA" in reasoning, (
        f"Erwarte CMA-Drift-Warnung im reasoning, gefunden: {reasoning}"
    )


def test_f3_legacy_allocation_without_cma_id_no_warning(session_factory):
    """Eine bestehende Allocation aus der Zeit vor F3 (capital_market_assumptions_id IS NULL)
    darf KEINE Drift-Warnung ausloesen, sonst spammen wir Altdaten."""
    advisor_id, cid, mid, aid = _seed(session_factory)
    with session_factory() as s:
        ensure_runtime_reference_data(s, advisor_id)
        s.commit()
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = generate_target_allocation(s, mandate, advisor_id, preferences=None)
        # Legacy-Zustand simulieren
        result["target_allocation"].capital_market_assumptions_id = None
        s.commit()
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        allocation = s.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mid,
            TargetAllocation.is_current == 1,
        ).first()
        assert allocation.capital_market_assumptions_id is None
        assessment = s.query(RiskAssessment).filter(RiskAssessment.id == aid).first()
        policy, cma = ensure_runtime_reference_data(s, advisor_id)
        payload = build_target_payload_from_allocation(
            db=s, mandate=mandate, allocation=allocation,
            policy=policy, cma=cma, assessment=assessment, preferences=None,
        )
    reasoning = " ".join(payload.get("reasoning") or [])
    assert "Kapitalmarktannahmen" not in reasoning and "CMA" not in reasoning, (
        f"Legacy-Allocation ohne cma_id darf keine CMA-Drift-Warnung ausloesen: {reasoning}"
    )
