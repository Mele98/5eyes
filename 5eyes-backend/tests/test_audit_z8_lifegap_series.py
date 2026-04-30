"""Z8 - C9 W2: Backend liefert deterministische IST/SOLL-Series mit Lebensluecken-Visualisierung.

W2.1 _apply_cashflow_to_bucket_values gibt Defizit-Rest zurueck wenn Buckets aufgezehrt sind.
W2.2 _simulate_bucket_path totals zeigen Lebensluecke (negative Werte) bei chronischem Defizit.
W2.3 Bei positivem Cashflow-Saldo bleibt totals unveraendert (kein Regression).
W2.4 Mandat-Level: build_target_payload_from_allocation simulation.current_mix_series_rappen
     enthaelt negativen Endwert wenn Lebensluecke vorliegt.
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
from models.profiling import RiskAssessment, RiskAssessmentAnswer
from models.users import User
from models.wealth import Cashflow, WealthPosition
from services.portfolio_engine import (
    _apply_cashflow_to_bucket_values,
    _simulate_bucket_path,
    build_target_payload_from_allocation,
    ensure_runtime_reference_data,
    generate_target_allocation,
)


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'audit_z8.db'}",
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
# W2.1 - _apply_cashflow_to_bucket_values returns deficit
# ============================================================================

def test_w2_1_apply_cashflow_positive_returns_zero_deficit():
    values = {"liquidity": 1_000_00, "bonds": 0, "equities": 0,
              "alternatives": 0, "real_estate": 0}
    deficit = _apply_cashflow_to_bucket_values(values, 500_00)
    assert deficit == 0
    assert values["liquidity"] == 1_500_00


def test_w2_1_apply_cashflow_negative_within_buckets_returns_zero_deficit():
    values = {"liquidity": 500_00, "bonds": 0, "equities": 0,
              "alternatives": 0, "real_estate": 0}
    deficit = _apply_cashflow_to_bucket_values(values, -300_00)
    assert deficit == 0
    assert values["liquidity"] == 200_00


def test_w2_1_apply_cashflow_negative_exhausts_all_buckets_returns_remainder():
    """Defizit groesser als Vermoegen -> Rest wird zurueckgegeben."""
    values = {"liquidity": 100_00, "bonds": 50_00, "equities": 0,
              "alternatives": 0, "real_estate": 0}
    deficit = _apply_cashflow_to_bucket_values(values, -300_00)
    # Total available was 150_00, deficit = 300_00 - 150_00 = 150_00
    assert deficit == 150_00
    assert values["liquidity"] == 0
    assert values["bonds"] == 0


# ============================================================================
# W2.2 - _simulate_bucket_path zeigt Lebensluecke
# ============================================================================

def test_w2_2_simulate_bucket_path_negative_totals_under_chronic_deficit():
    """Mandat mit kleiner Liquiditaet und chronisch negativem Cashflow:
    totals muss am Ende negativ sein (Lebensluecke)."""
    start_values = {"liquidity": 100_000_00, "bonds": 0, "equities": 0,
                    "alternatives": 0, "real_estate": 0}
    returns_by_asset = {"liquidity": 0, "bonds": 0, "equities": 0,
                        "alternatives": 0, "real_estate": 0}
    targets = {"liquidity": 10000, "bonds": 0, "equities": 0,
               "alternatives": 0, "real_estate": 0}
    minimums = {k: 0 for k in targets}
    maximums = {k: 10000 for k in targets}
    cashflow_series = [-50_000_00] * 5  # 5 Jahre je -50k -> Total -250k > Start 100k

    totals, _ = _simulate_bucket_path(
        start_values=start_values,
        returns_by_asset=returns_by_asset,
        cashflow_series_rappen=cashflow_series,
        targets=targets,
        minimums=minimums,
        maximums=maximums,
        start_year=2026,
        rebalance_mode="none",
    )
    assert totals[0] == 100_000_00
    assert totals[-1] < 0, f"Lebensluecke erwartet, totals[-1]={totals[-1]}"


def test_w2_2_simulate_bucket_path_positive_unchanged_no_regression():
    """Mandat mit positivem Cashflow: keine Aenderung gegenueber alter Logik."""
    start_values = {"liquidity": 100_000_00, "bonds": 0, "equities": 0,
                    "alternatives": 0, "real_estate": 0}
    returns_by_asset = {"liquidity": 100, "bonds": 0, "equities": 0,
                        "alternatives": 0, "real_estate": 0}
    targets = {"liquidity": 10000, "bonds": 0, "equities": 0,
               "alternatives": 0, "real_estate": 0}
    minimums = {k: 0 for k in targets}
    maximums = {k: 10000 for k in targets}
    cashflow_series = [10_000_00] * 3  # 3 Jahre je +10k

    totals, _ = _simulate_bucket_path(
        start_values=start_values,
        returns_by_asset=returns_by_asset,
        cashflow_series_rappen=cashflow_series,
        targets=targets,
        minimums=minimums,
        maximums=maximums,
        start_year=2026,
        rebalance_mode="none",
    )
    # 100k * 1.01 + 10k = 111k; * 1.01 + 10k = 122.11k; * 1.01 + 10k = 133.33k
    assert totals[0] == 100_000_00
    for value in totals:
        assert value > 0


# ============================================================================
# W2.4 - Mandat-Level: simulation.current_mix_series_rappen mit Lebensluecke
# ============================================================================

def _seed_lifegap_mandate(session_factory):
    """Seedet ein Mandat mit Defizit: 200k Beratungsvermoegen + 100k Ausgaben/Jahr."""
    advisor_id = "user-z8-1"
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
            id="pos-z8-1", client_id=cid,
            label="Depot", position_type="Depot", assignment="Beratungsvermögen",
            current_value_rappen=200_000_00, currency="CHF",
            alloc_equities_bps=4000, alloc_bonds_bps=3000,
            alloc_real_estate_bps=1000, alloc_liquidity_bps=1000,
            alloc_alternatives_bps=1000,
            is_active=1, created_at=now, updated_at=now,
        ))
        # Ausgaben 100k/J ohne Einkommen -> Vermoegen aufgezehrt
        s.add(Cashflow(
            id="cf-z8-1", client_id=cid, label="Ausgaben",
            cashflow_type="Expense", amount_rappen=100_000_00,
            currency="CHF", frequency="jährlich", nature="wiederkehrend",
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
            assessed_at=now, assessed_by=advisor_id,
            created_at=now, updated_at=now,
        ))
        for q in (3, 5, 6, 7, 8, 9, 10, 11):
            s.add(RiskAssessmentAnswer(
                id=str(uuid.uuid4()), assessment_id=aid,
                question_number=q, question_section="Risikoprofil",
                answer_label=f"A{q}", answer_points=2,
                created_at=now,
            ))
        s.commit()
        ensure_runtime_reference_data(s, advisor_id)
        s.commit()
    return advisor_id, cid, mid, aid


def test_w2_4_payload_current_mix_series_negative_when_lifegap(session_factory):
    """generate_target_allocation -> simulation.current_mix_series_rappen
    muss am Ende negativ sein bei chronischem Defizit (Lebensluecke).
    """
    advisor_id, cid, mid, aid = _seed_lifegap_mandate(session_factory)
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = generate_target_allocation(s, mandate, advisor_id, preferences=None)
    sim = result.get("simulation") or {}
    series = sim.get("current_mix_series_rappen") or []
    assert series, "current_mix_series_rappen muss vorhanden sein"
    assert series[0] == 200_000_00
    # Bei 200k Start und 100k/Jahr Ausgaben (ohne Einkommen, ohne Wachstum)
    # geht das Vermoegen nach 2-3 Jahren in die Luecke. Horizon ist 10J standardmaessig.
    assert series[-1] < 0, f"Lebensluecke erwartet, series[-1]={series[-1]}"
