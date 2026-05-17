"""Z5 - C6: strategy_base = advisory - external_reserve durchgaengig.

Vor dem Fix:
  Wenn external_reserve_rappen > 0 berechnet wurde, blieben target_amount,
  Simulationspfade und Live-Rebalancing trotzdem auf advisory_wealth als
  Basis. Damit zeigte der Berater einen Soll-Betrag der die externe
  Reserve impliziterweise mit-investierte.

Nach dem Fix:
  - investable_advisory_wealth_rappen = max(0, advisory - external_reserve)
  - target_amount_rappen = investable * target_bps / 10000
  - Sim/MC starten bei investable
  - Live-Rebalancing rechnet auf investable
  - Payload exponiert strategy_base_rappen als expliziten Alias
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

from models.clients import Client
from models.mandates import Mandate
from models.profiling import RiskAssessment
from models.users import User
from models.wealth import Cashflow, Goal, WealthPosition
from services.portfolio_engine import (
    _investable_advisory_wealth_rappen,
    ensure_runtime_reference_data,
    generate_target_allocation,
)
from tests.risk_fixture_helpers import CURRENT_RISK_SCHEMA_MARKERS, add_current_risk_answers


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'audit_z5.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_c6_helper_returns_advisory_minus_reserve():
    """_investable_advisory_wealth_rappen muss advisory - external_reserve
    liefern, mit Schutz gegen negative Werte."""
    assert _investable_advisory_wealth_rappen(1_000_000_00, 200_000_00) == 800_000_00
    assert _investable_advisory_wealth_rappen(500_000_00, 0) == 500_000_00
    # Schutz gegen Negativ wenn Reserve > advisory
    assert _investable_advisory_wealth_rappen(100_000_00, 200_000_00) == 0


def test_c6_helper_handles_none_inputs():
    assert _investable_advisory_wealth_rappen(0, 0) == 0
    assert _investable_advisory_wealth_rappen(None, 0) == 0


def _seed_full(session_factory, *, advisory_value_rappen: int = 100_000_000):
    """Setup mit Beratungsvermoegen-Position + Cashflow der Reserve erzwingt."""
    advisor_id = "user-z5-1"
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
            id=str(uuid.uuid4()), client_id=cid,
            label="Depot", position_type="Depot",
            assignment="Beratungsvermögen",
            current_value_rappen=advisory_value_rappen, currency="CHF",
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
        # Goal das Reserve erzwingt: Einmalige Ausgabe in 2 Jahren
        # Bei advisory 1Mio, Reserve 200k -> liquidity ceiling 3% = 30k
        # -> external_reserve = 200k - 30k = 170k
        target_date = datetime.date.today().replace(year=datetime.date.today().year + 2)
        s.add(Goal(
            id=str(uuid.uuid4()), mandate_id=mid, client_id=cid,
            goal_family="Konsum", goal_type="Einmalige_Ausgabe",
            label="Auto", rank=1, weight_bps=1000,
            goal_scope="Beratungsvermoegen",
            target_amount_rappen=int(advisory_value_rappen * 0.20),  # 20% des Vermoegens
            target_date=target_date.isoformat(),
            is_ongoing=0, is_active=1,
            created_at=now, updated_at=now,
        ))
        s.commit()
    return advisor_id, cid, mid, aid


def test_c6_payload_exposes_strategy_base_rappen(session_factory):
    """generate_target_allocation muss strategy_base_rappen im Payload setzen
    und es muss = investable_advisory_wealth_rappen sein."""
    advisor_id, cid, mid, aid = _seed_full(session_factory)
    with session_factory() as s:
        ensure_runtime_reference_data(s, advisor_id)
        s.commit()
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = generate_target_allocation(s, mandate, advisor_id, preferences=None)
        s.commit()
    assert "strategy_base_rappen" in result
    assert result["strategy_base_rappen"] == result["investable_advisory_wealth_rappen"]


def test_c6_target_amounts_use_investable_when_external_reserve_active(session_factory):
    """Wenn external_reserve > 0: bucket target_amount_rappen rechnet auf
    investable, NICHT auf advisory."""
    advisor_id, cid, mid, aid = _seed_full(session_factory)
    with session_factory() as s:
        ensure_runtime_reference_data(s, advisor_id)
        s.commit()
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = generate_target_allocation(s, mandate, advisor_id, preferences=None)
        s.commit()
    advisory = result["advisory_wealth_rappen"]
    investable = result["investable_advisory_wealth_rappen"]
    external_reserve = result["external_reserve_rappen"]
    # Erzwungener external_reserve > 0 vom seed
    if external_reserve <= 0:
        pytest.skip("Test-Setup hat keinen external_reserve erzwungen.")
    # Wenn es einen external reserve gibt, ist investable < advisory
    assert investable < advisory
    # target_amount = investable * target_bps / 10000 (NICHT advisory).
    for bucket in result["buckets"]:
        target_bps = int(bucket["target_weight_bps"])
        target_amount = int(bucket["target_amount_rappen"])
        expected = int(round(investable * target_bps / 10000))
        # Kleine Toleranz fuer Rundung
        assert abs(target_amount - expected) <= 1, (
            f"{bucket['asset_class']}: target_amount {target_amount} != {expected} "
            f"(investable * {target_bps}/10000)"
        )


def test_c6_target_amounts_equal_advisory_when_no_reserve(session_factory):
    """Ohne external_reserve sind investable == advisory und target_amount
    rechnet auf advisory. Sanity check."""
    advisor_id = "user-z5-2"
    cid = str(uuid.uuid4())
    mid = str(uuid.uuid4())
    aid = str(uuid.uuid4())
    now = _now()
    with session_factory() as s:
        s.add(User(id=advisor_id, username="adv2", password_hash="h",
                   full_name="A2", role="advisor", is_active=1,
                   created_at=now, updated_at=now))
        s.add(Client(id=cid, client_number=f"C-{cid[:6]}",
                     first_name="T", last_name="Y", advisor_id=advisor_id,
                     created_at=now, updated_at=now))
        s.add(Mandate(id=mid, client_id=cid, mandate_number=f"M-{mid[:6]}",
                      mandate_type="Anlageberatung", opened_at=now,
                      created_at=now, updated_at=now))
        s.add(WealthPosition(
            id=str(uuid.uuid4()), client_id=cid,
            label="Depot", position_type="Depot", assignment="Beratungsvermögen",
            current_value_rappen=100_000_000, currency="CHF",
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
        ensure_runtime_reference_data(s, advisor_id)
        s.commit()
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = generate_target_allocation(s, mandate, advisor_id, preferences=None)
        s.commit()
    # Keine Goals -> kein external_reserve
    assert result["external_reserve_rappen"] == 0
    assert result["investable_advisory_wealth_rappen"] == result["advisory_wealth_rappen"]
    assert result["strategy_base_rappen"] == result["advisory_wealth_rappen"]
