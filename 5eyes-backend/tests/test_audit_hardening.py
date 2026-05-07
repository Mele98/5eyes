"""Audit-Hardening Tests:

R1a - RecommendationHolding-Snapshot filtert deleted_at direkt im SQL,
      damit eine deleted Latest-Holding nicht eine aeltere non-deleted
      Holding maskiert.

R2  - is_current-Anchor-Lookups verwenden with_for_update() (postgres-
      ready Lock; auf SQLite NoOp). Wir testen NICHT die echte Race-
      Bedingung (SQLite ist single-writer), sondern dass die
      Lock-Klausel im SQL-Statement ist.
"""
from __future__ import annotations
import sys
import uuid
import datetime
import re
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base
from models.allocation import OptimizerPolicy
from models.review import (
    Product,
    RecommendationHolding,
    RecommendationPosition,
    RecommendationRun,
)
from models.mandates import Mandate
from models.clients import Client
from models.users import User
from services.portfolio_engine import (
    _holdings_snapshot_for_run,
    _latest_holdings_by_product_for_mandate,
)


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'audit_hardening.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _seed_run_with_position(session_factory):
    advisor_id = "user-rh-1"
    cid = str(uuid.uuid4())
    mid = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    pos_id = str(uuid.uuid4())
    prod_id = str(uuid.uuid4())
    policy_id = str(uuid.uuid4())
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
        s.add(OptimizerPolicy(id=policy_id, policy_name="Standard",
                               version=1, is_current=1,
                               valid_from=now[:10],
                               optimizer_engine="TBI-V1",
                               max_real_estate_bps=2000,
                               max_alternatives_bps=1500,
                               min_liquidity_bps=200,
                               fee_model_json="{}",
                               created_by=advisor_id,
                               created_at=now, updated_at=now))
        s.add(Product(id=prod_id, product_name="Test ETF", provider="X",
                      product_type="ETF", asset_class="Aktien",
                      sub_asset_class="Aktien Welt", currency="CHF",
                      ter_bps=20, sfdr_class="A",
                      is_active=1, created_at=now, updated_at=now))
        s.add(RecommendationRun(id=run_id, mandate_id=mid, client_id=cid,
                                policy_id=policy_id,
                                run_type="Optimizer", result_status="Final",
                                created_by=advisor_id, created_at=now, updated_at=now))
        s.add(RecommendationPosition(id=pos_id, run_id=run_id,
                                     product_id=prod_id,
                                     target_weight_bps=4000,
                                     target_amount_rappen=100_000_00,
                                     created_at=now, updated_at=now))
        s.commit()
    return advisor_id, cid, mid, run_id, pos_id, prod_id


def _add_holding(session_factory, *, run_id, position_id, product_id,
                 units_milli=1000, market_value_rappen=100_000_00,
                 deleted=False, updated_at=None) -> str:
    hid = str(uuid.uuid4())
    now = updated_at or _now()
    with session_factory() as s:
        s.add(RecommendationHolding(
            id=hid, run_id=run_id,
            recommendation_position_id=position_id,
            product_id=product_id,
            units_milli=units_milli,
            market_value_rappen=market_value_rappen,
            source="manual", as_of_date=now[:10],
            deleted_at=now if deleted else None,
            created_at=now, updated_at=now,
        ))
        s.commit()
    return hid


# Hinweis: R1a (Holdings deleted_at direkt im SQL) wurde verworfen, weil die
# bestehende seen+deleted_at-Schleifen-Logik bewusst designed ist:
# "deleted Latest = Position hat kein gueltiges Holding mehr". Der bestehende
# Test test_deleted_holding_does_not_resurface_from_older_runs in
# test_runtime_contracts.py prueft genau dieses Verhalten.

# ============================================================================
# R2 - with_for_update() im SQL fuer Anchor-Lookups
# ============================================================================

def _read_source(rel: str) -> str:
    return (BACKEND_ROOT / rel).read_text(encoding="utf-8")


def test_r2_profiling_create_knowledge_uses_for_update():
    src = _read_source("routers/profiling.py")
    snippet = re.search(
        r"prev = db\.query\(ClientKnowledge\)\.filter\([^)]*\)[\s\S]*?\.first\(\)",
        src,
    )
    assert snippet, "ClientKnowledge anchor lookup nicht gefunden"
    assert "with_for_update" in snippet.group(0), (
        "ClientKnowledge anchor-lookup muss with_for_update() haben "
        "(postgres-ready Lock, NoOp auf SQLite)."
    )


def test_r2_profiling_create_risk_assessment_uses_for_update():
    src = _read_source("routers/profiling.py")
    snippet = re.search(
        r"prev = db\.query\(RiskAssessment\)\.filter\([^)]*\)[\s\S]*?\.first\(\)",
        src,
    )
    assert snippet, "RiskAssessment anchor lookup nicht gefunden"
    assert "with_for_update" in snippet.group(0), (
        "RiskAssessment anchor-lookup muss with_for_update() haben."
    )


def test_r2_wealth_planning_assumption_uses_for_update():
    src = _read_source("routers/wealth.py")
    snippet = re.search(
        r"prev = db\.query\(PlanningAssumption\)\.filter\([^)]*\)[\s\S]*?\.first\(\)",
        src,
    )
    assert snippet, "PlanningAssumption anchor lookup nicht gefunden"
    assert "with_for_update" in snippet.group(0), (
        "PlanningAssumption anchor-lookup muss with_for_update() haben."
    )


def test_r2_portfolio_engine_target_allocation_uses_for_update():
    src = _read_source("services/portfolio_engine.py")
    snippet = re.search(
        r"previous_current = db\.query\(TargetAllocation\)\.filter\([^)]*?\)[\s\S]*?\.first\(\)",
        src,
    )
    assert snippet, "previous_current TargetAllocation lookup nicht gefunden"
    assert "with_for_update" in snippet.group(0), (
        "TargetAllocation previous_current-lookup muss with_for_update() haben."
    )


# ============================================================================
# Sanity: existing flows weiterhin gruen
# ============================================================================

def test_r2_create_knowledge_still_works(session_factory):
    """End-to-end: knowledge-Create soll trotz Lock weiterhin funktionieren."""
    from fastapi.testclient import TestClient
    from main import app
    from database import get_db
    from services.auth import get_current_user, require_advisor
    from models.users import User

    advisor = User(id="user-r2-1", username="adv", password_hash="h",
                   full_name="Adv", role="advisor", is_active=1,
                   created_at=_now(), updated_at=_now())

    def _odb():
        with session_factory() as s:
            yield s
    app.dependency_overrides[get_db] = _odb
    app.dependency_overrides[get_current_user] = lambda: advisor
    app.dependency_overrides[require_advisor] = lambda: advisor

    cid = str(uuid.uuid4())
    with session_factory() as s:
        s.add(advisor)
        s.add(Client(id=cid, client_number=f"C-{cid[:6]}",
                     first_name="T", last_name="X",
                     advisor_id=advisor.id, created_at=_now(), updated_at=_now()))
        s.commit()

    client = TestClient(app)
    payload = {
        "knowledge_level": "Hoch",
        "exp_equities": "> 5 Jahre",
        "exp_bonds": "> 5 Jahre",
        "exp_funds": "> 5 Jahre",
        "exp_derivatives": "Keine",
        "exp_alternatives": "Keine",
        "exp_structured": "Keine",
    }
    resp = client.post(f"/clients/{cid}/knowledge", json=payload)
    app.dependency_overrides.clear()
    assert resp.status_code == 201, resp.text
