"""Z9 - C10: Input-Validierung dauerhaft kompatibel.

C10.1 list_wealth_positions / list_cashflows: nur aktive Records standardmaessig
      (is_active=1), inaktive nur ueber expliziten Query-Param.
C10.2 update_wealth_position: exclude_unset (None-clearing moeglich),
      updated_at setzen, partial alloc_*-Update prueft Konsistenz.
C10.3 _normalize_cashflow_date: invalid format -> 422.
      YYYY-MM -> YYYY-MM-01.
C10.4 _normalize_goal_payload: horizon_years >= 1.
"""
from __future__ import annotations
import sys
import datetime
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy.orm import configure_mappers
from database import Base, get_db
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
configure_mappers()

from main import app
from models.clients import Client
from models.mandates import Mandate
from models.users import User
from models.wealth import Cashflow, Goal, WealthPosition
from services.auth import get_current_user, require_advisor


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'audit_z9.db'}",
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
def advisor():
    return User(id="user-z9-1", username="adv", password_hash="h",
                full_name="Adv", role="advisor", is_active=1,
                created_at=_now(), updated_at=_now())


@pytest.fixture()
def auth_client(session_factory, advisor):
    def _odb():
        with session_factory() as s:
            yield s
    app.dependency_overrides[get_db] = _odb
    app.dependency_overrides[get_current_user] = lambda: advisor
    app.dependency_overrides[require_advisor] = lambda: advisor
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _make_client(session_factory, advisor) -> str:
    cid = str(uuid.uuid4())
    now = _now()
    with session_factory() as s:
        if not s.query(User).filter(User.id == advisor.id).first():
            s.add(advisor)
        s.add(Client(id=cid, client_number=f"C-{cid[:6]}",
                     first_name="T", last_name="X",
                     advisor_id=advisor.id,
                     created_at=now, updated_at=now))
        s.commit()
    return cid


# ============================================================================
# C10.1 - list_wealth_positions: nur aktive standardmaessig
# ============================================================================

def test_c10_1_list_wealth_positions_excludes_inactive_by_default(
    auth_client, session_factory, advisor
):
    cid = _make_client(session_factory, advisor)
    now = _now()
    with session_factory() as s:
        s.add(WealthPosition(
            id="wp-active", client_id=cid, label="Aktiv",
            position_type="Depot", assignment="Beratungsvermögen",
            current_value_rappen=100_000_00, currency="CHF",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(WealthPosition(
            id="wp-inactive", client_id=cid, label="Inaktiv",
            position_type="Depot", assignment="Beratungsvermögen",
            current_value_rappen=50_000_00, currency="CHF",
            is_active=0, created_at=now, updated_at=now,
        ))
        s.commit()
    resp = auth_client.get(f"/clients/{cid}/wealth-positions")
    assert resp.status_code == 200
    ids = {item["id"] for item in resp.json()}
    assert "wp-active" in ids
    assert "wp-inactive" not in ids


def test_c10_1_list_wealth_positions_include_inactive_via_param(
    auth_client, session_factory, advisor
):
    cid = _make_client(session_factory, advisor)
    now = _now()
    with session_factory() as s:
        s.add(WealthPosition(
            id="wp-active2", client_id=cid, label="Aktiv2",
            position_type="Depot", assignment="Beratungsvermögen",
            current_value_rappen=100_000_00, currency="CHF",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(WealthPosition(
            id="wp-inactive2", client_id=cid, label="Inaktiv2",
            position_type="Depot", assignment="Beratungsvermögen",
            current_value_rappen=50_000_00, currency="CHF",
            is_active=0, created_at=now, updated_at=now,
        ))
        s.commit()
    resp = auth_client.get(f"/clients/{cid}/wealth-positions?include_inactive=true")
    assert resp.status_code == 200
    ids = {item["id"] for item in resp.json()}
    assert "wp-active2" in ids and "wp-inactive2" in ids


def test_c10_1_list_cashflows_excludes_inactive_by_default(
    auth_client, session_factory, advisor
):
    cid = _make_client(session_factory, advisor)
    now = _now()
    with session_factory() as s:
        s.add(Cashflow(
            id="cf-active", client_id=cid, label="Lohn",
            cashflow_type="Income", amount_rappen=10_000_00,
            currency="CHF", frequency="monatlich", nature="wiederkehrend",
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(Cashflow(
            id="cf-inactive", client_id=cid, label="Alt-Lohn",
            cashflow_type="Income", amount_rappen=5_000_00,
            currency="CHF", frequency="monatlich", nature="wiederkehrend",
            is_active=0, created_at=now, updated_at=now,
        ))
        s.commit()
    resp = auth_client.get(f"/clients/{cid}/cashflows")
    assert resp.status_code == 200
    ids = {item["id"] for item in resp.json()}
    assert "cf-active" in ids
    assert "cf-inactive" not in ids


# ============================================================================
# C10.2 - update_wealth_position: exclude_unset + updated_at + alloc consistency
# ============================================================================

def test_c10_2_update_wealth_position_sets_updated_at(
    auth_client, session_factory, advisor
):
    cid = _make_client(session_factory, advisor)
    old_ts = "2026-01-01T00:00:00.000Z"
    with session_factory() as s:
        s.add(WealthPosition(
            id="wp-up1", client_id=cid, label="Test",
            position_type="Depot", assignment="Beratungsvermögen",
            current_value_rappen=100_000_00, currency="CHF",
            alloc_equities_bps=6000, alloc_bonds_bps=2500,
            alloc_real_estate_bps=0, alloc_liquidity_bps=1000,
            alloc_alternatives_bps=500,
            is_active=1, created_at=old_ts, updated_at=old_ts,
        ))
        s.commit()
    resp = auth_client.put(
        f"/clients/{cid}/wealth-positions/wp-up1",
        json={"label": "Test geaendert"},
    )
    assert resp.status_code == 200, resp.text
    with session_factory() as s:
        wp = s.query(WealthPosition).filter(WealthPosition.id == "wp-up1").first()
        assert wp.label == "Test geaendert"
        assert wp.updated_at != old_ts, "updated_at muss nach UPDATE neu sein"


def test_c10_2_update_wealth_position_rejects_inconsistent_alloc(
    auth_client, session_factory, advisor
):
    """Partial-Update der alloc_*_bps muss konsistente Summe ergeben.
    Wenn nicht alle Allokations-Felder gleichzeitig gesetzt werden und die
    resultierende Summe nicht 0 oder 10000 ergibt -> 422.
    """
    cid = _make_client(session_factory, advisor)
    now = _now()
    with session_factory() as s:
        s.add(WealthPosition(
            id="wp-up2", client_id=cid, label="Depot",
            position_type="Depot", assignment="Beratungsvermögen",
            current_value_rappen=100_000_00, currency="CHF",
            alloc_equities_bps=6000, alloc_bonds_bps=2500,
            alloc_real_estate_bps=0, alloc_liquidity_bps=1000,
            alloc_alternatives_bps=500,
            is_active=1, created_at=now, updated_at=now,
        ))
        s.commit()
    # Partial-Update: nur Aktien auf 5000 setzen -> Summe waere 9000 - inkonsistent
    resp = auth_client.put(
        f"/clients/{cid}/wealth-positions/wp-up2",
        json={"alloc_equities_bps": 5000},
    )
    assert resp.status_code == 422, resp.text


def test_c10_2_update_wealth_position_accepts_consistent_alloc_full_update(
    auth_client, session_factory, advisor
):
    """Voller Allokations-Update mit Summe 10000 wird akzeptiert."""
    cid = _make_client(session_factory, advisor)
    now = _now()
    with session_factory() as s:
        s.add(WealthPosition(
            id="wp-up3", client_id=cid, label="Depot",
            position_type="Depot", assignment="Beratungsvermögen",
            current_value_rappen=100_000_00, currency="CHF",
            alloc_equities_bps=6000, alloc_bonds_bps=2500,
            alloc_real_estate_bps=0, alloc_liquidity_bps=1000,
            alloc_alternatives_bps=500,
            is_active=1, created_at=now, updated_at=now,
        ))
        s.commit()
    resp = auth_client.put(
        f"/clients/{cid}/wealth-positions/wp-up3",
        json={
            "alloc_equities_bps": 5000,
            "alloc_bonds_bps": 3000,
            "alloc_real_estate_bps": 1000,
            "alloc_liquidity_bps": 500,
            "alloc_alternatives_bps": 500,
        },
    )
    assert resp.status_code == 200, resp.text


# ============================================================================
# C10.3 - _normalize_cashflow_date: invalid format -> 422
# ============================================================================

def test_c10_3_cashflow_invalid_date_returns_422(auth_client, session_factory, advisor):
    cid = _make_client(session_factory, advisor)
    resp = auth_client.post(
        f"/clients/{cid}/cashflows",
        json={
            "cashflow_type": "Income", "label": "Test",
            "amount_rappen": 100_00, "frequency": "monatlich",
            "valid_from": "not-a-date",
        },
    )
    assert resp.status_code == 422, resp.text


def test_c10_3_cashflow_yyyy_mm_normalizes_to_first_day(auth_client, session_factory, advisor):
    """YYYY-MM Format -> YYYY-MM-01."""
    cid = _make_client(session_factory, advisor)
    resp = auth_client.post(
        f"/clients/{cid}/cashflows",
        json={
            "cashflow_type": "Income", "label": "Bonus",
            "amount_rappen": 1_000_00, "frequency": "einmalig",
            "nature": "einmalig",
            "valid_from": "2026-06",
            "timing_precision": "month",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["valid_from"] == "2026-06-01"


# ============================================================================
# C10.4 - goal horizon_years >= 1
# ============================================================================

def test_c10_4_goal_horizon_zero_returns_422(auth_client, session_factory, advisor):
    cid = _make_client(session_factory, advisor)
    mid = str(uuid.uuid4())
    now = _now()
    with session_factory() as s:
        s.add(Mandate(id=mid, client_id=cid, mandate_number=f"M-{mid[:6]}",
                      mandate_type="Anlageberatung", opened_at=now,
                      created_at=now, updated_at=now))
        s.commit()
    resp = auth_client.post(
        f"/mandates/{mid}/goals",
        json={
            "goal_family": "Vermoegen", "goal_type": "Vermoegensziel",
            "label": "Pension", "rank": 1, "weight_bps": 1000,
            "target_wealth_rappen": 1_000_000_00,
            "horizon_years": 0,
        },
    )
    assert resp.status_code == 422, resp.text
