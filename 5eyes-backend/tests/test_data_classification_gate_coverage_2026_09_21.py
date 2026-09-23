"""Kontrollrunde 2026-09-21 (Data-Classification-Gate-Coverage-Audit).

services/data_classification.py::enforce_data_classification ist selbst
korrekt und bereits an die meisten mandats-/client-bezogenen Schreibpfade
angeschlossen (Client/Mandate/WealthPosition/Cashflow/Goal/WealthInflow/
PlanningAssumption/Knowledge/RiskAssessment/Review/ContractDocument/
ConflictDisclosure/ProtocolBaustein). Vier Endpunkte waren nie
angeschlossen:

1. PUT  /mandates/{id}/report-notes
2. POST /mandates/{id}/recommendations/{run_id}/portfolio-handoffs
3. POST /mandates/{id}/strategy-snapshots
4. POST /mandates/{id}/target-allocation

Jeder Test hier prueft: data_classification="real" wird bei
allow_real_client_data=False mit 403 blockiert; "synthetic" (oder
weggelassen, wo Optional) geht durch.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for path in (BACKEND_ROOT, TESTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from config import settings
from database import Base
from models.clients import Client
from models.mandates import Mandate
from models.review import MandateReportNotes, RecommendationRun
from models.snapshots import StrategySnapshot
from models.users import User
from services.data_classification import PHASE_ZERO_BLOCK_DETAIL

from routers.allocation import create_target_allocation, put_report_notes
from routers.portfolio_handoff import create_portfolio_handoff
from routers.snapshots import create_snapshot
from schemas.allocation import TargetAllocationCreate
from schemas.portfolio_handoff import PortfolioHandoffCreate
from schemas.review import ReportNotesUpdate
from schemas.snapshots import StrategySnapshotCreate

from test_current_anchor_uniqueness import (  # noqa: E402
    _policy_row,
    _request_stub,
    _risk_payload,
    _seed_advisor_and_mandate,
)
from routers.profiling import create_risk_assessment
from models.allocation import OptimizerPolicy

import routers.portfolio_handoff as portfolio_handoff_router  # noqa: F401
import services.portfolio_handoff as portfolio_handoff_service


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _assert_phase_zero_block(exc_info) -> None:
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == PHASE_ZERO_BLOCK_DETAIL


# ---------------------------------------------------------------------------
# 4) POST /mandates/{id}/target-allocation
# ---------------------------------------------------------------------------

def _target_payload_with_classification(policy_id: str, classification) -> TargetAllocationCreate:
    kwargs = dict(
        target_equities_bps=6000,
        target_bonds_bps=3000,
        target_real_estate_bps=0,
        target_alternatives_bps=0,
        target_liquidity_bps=1000,
        band_equities_min_bps=5000,
        band_equities_max_bps=7000,
        band_bonds_min_bps=2000,
        band_bonds_max_bps=4000,
        band_real_estate_min_bps=0,
        band_real_estate_max_bps=0,
        band_alternatives_min_bps=0,
        band_alternatives_max_bps=0,
        band_liquidity_min_bps=0,
        band_liquidity_max_bps=2000,
        policy_id=policy_id,
    )
    if classification is not None:
        kwargs["data_classification"] = classification
    return TargetAllocationCreate(**kwargs)


@pytest.fixture
def orm_engine():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


def _seed_target_allocation_prereqs(orm_engine, monkeypatch, *, mandate_id="mandate-dcgate"):
    import routers.allocation as allocation_router

    monkeypatch.setattr(allocation_router.settings, "optimizer_mode", "house_matrix")
    now = "2026-09-21T00:00:00Z"
    with Session(orm_engine) as session:
        session.add_all([
            User(
                id="advisor-dcgate", username="advisor-dcgate", password_hash="x",
                full_name="DC-Gate Advisor", role="admin", is_active=1,
                created_at=now, updated_at=now,
            ),
            Client(
                id="client-dcgate", client_number="DCGATE-1", first_name="DC", last_name="Gate",
                country_of_residence="CH", language="DE", household_type="Einzelperson",
                client_classification="Privatkunde", is_professional_opt_out=0,
                is_qualified_investor=0, advisor_id="advisor-dcgate",
                created_at=now, updated_at=now,
            ),
            Mandate(
                id=mandate_id, client_id="client-dcgate", mandate_number="DCGATE-M-1",
                mandate_type="Anlageberatung", status="Aktiv", base_currency="CHF",
                advisory_language="DE", opened_at="2026-09-21",
                investment_universe="Standard", created_at=now, updated_at=now,
            ),
        ])
        session.commit()

    with Session(orm_engine) as session:
        advisor = session.get(User, "advisor-dcgate")
        create_risk_assessment(
            mandate_id, _risk_payload(), _request_stub(), db=session, current_user=advisor,
        )
        session.add(OptimizerPolicy(**_policy_row("policy-dcgate", policy_name="DC-Gate")))
        session.commit()
    return mandate_id


def test_target_allocation_real_blocked_when_gate_closed(orm_engine, monkeypatch):
    monkeypatch.setattr(settings, "allow_real_client_data", False)
    mandate_id = _seed_target_allocation_prereqs(orm_engine, monkeypatch)

    with Session(orm_engine) as session:
        advisor = session.get(User, "advisor-dcgate")
        with pytest.raises(HTTPException) as exc:
            create_target_allocation(
                mandate_id,
                _target_payload_with_classification("policy-dcgate", "real"),
                _request_stub(), db=session, current_user=advisor,
            )
        _assert_phase_zero_block(exc)


def test_target_allocation_synthetic_allowed_when_gate_closed(orm_engine, monkeypatch):
    monkeypatch.setattr(settings, "allow_real_client_data", False)
    mandate_id = _seed_target_allocation_prereqs(orm_engine, monkeypatch)

    with Session(orm_engine) as session:
        advisor = session.get(User, "advisor-dcgate")
        result = create_target_allocation(
            mandate_id,
            _target_payload_with_classification("policy-dcgate", "synthetic"),
            _request_stub(), db=session, current_user=advisor,
        )
        assert result.policy_id == "policy-dcgate"


# ---------------------------------------------------------------------------
# 1) PUT /mandates/{id}/report-notes
# ---------------------------------------------------------------------------

@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'dc_gate_coverage.db'}",
        connect_args={"check_same_thread": False},
    )
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield factory
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _seed_minimal_mandate(session_factory, *, mandate_id="mandate-notes"):
    with session_factory() as db:
        db.add(User(
            id="advisor-notes", username="advisor-notes", password_hash="x",
            full_name="Notes Advisor", role="advisor", is_active=1,
            created_at=_now(), updated_at=_now(),
        ))
        db.add(Client(
            id="client-notes", client_number="NOTES-1", first_name="Notes", last_name="Client",
            country_of_residence="CH", language="DE", household_type="Einzelperson",
            client_classification="Privatkunde", is_professional_opt_out=0,
            is_qualified_investor=0, advisor_id="advisor-notes",
            created_at=_now(), updated_at=_now(),
        ))
        db.add(Mandate(
            id=mandate_id, client_id="client-notes", mandate_number="NOTES-M-1",
            mandate_type="Anlageberatung", status="Aktiv", base_currency="CHF",
            advisory_language="DE", opened_at="2026-09-21",
            created_at=_now(), updated_at=_now(),
        ))
        db.commit()
    return mandate_id


def test_report_notes_real_blocked_when_gate_closed(session_factory, monkeypatch):
    monkeypatch.setattr(settings, "allow_real_client_data", False)
    mandate_id = _seed_minimal_mandate(session_factory)
    advisor = User(id="advisor-notes", username="advisor-notes", password_hash="x",
                    full_name="Notes Advisor", role="advisor", is_active=1,
                    created_at=_now(), updated_at=_now())

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc:
            put_report_notes(
                mandate_id,
                ReportNotesUpdate(aa_anmerkungen="echte Kundendaten", data_classification="real"),
                _request_stub(), db=db, current_user=advisor,
            )
        _assert_phase_zero_block(exc)

    with session_factory() as db:
        assert db.query(MandateReportNotes).filter(
            MandateReportNotes.mandate_id == mandate_id
        ).count() == 0


def test_report_notes_synthetic_allowed_when_gate_closed(session_factory, monkeypatch):
    monkeypatch.setattr(settings, "allow_real_client_data", False)
    mandate_id = _seed_minimal_mandate(session_factory)
    advisor = User(id="advisor-notes", username="advisor-notes", password_hash="x",
                    full_name="Notes Advisor", role="advisor", is_active=1,
                    created_at=_now(), updated_at=_now())

    with session_factory() as db:
        result = put_report_notes(
            mandate_id,
            ReportNotesUpdate(aa_anmerkungen="Test-Notiz", data_classification="synthetic"),
            _request_stub(), db=db, current_user=advisor,
        )
        assert result.aa_anmerkungen == "Test-Notiz"


# ---------------------------------------------------------------------------
# 3) POST /mandates/{id}/strategy-snapshots
# ---------------------------------------------------------------------------

def _snapshot_payload(classification) -> StrategySnapshotCreate:
    kwargs = dict(
        snapshot_date="2026-09-21",
        advisory_assets_rappen=1_000_000_00,
        risk_profile_score=50,
        risk_profile_label="Ausgewogen",
        soll_equities_bps=5000,
        soll_bonds_bps=3000,
        soll_real_estate_bps=1000,
        soll_liquidity_bps=500,
        soll_alternatives_bps=500,
    )
    if classification is not None:
        kwargs["data_classification"] = classification
    return StrategySnapshotCreate(**kwargs)


def test_strategy_snapshot_real_blocked_when_gate_closed(session_factory, monkeypatch):
    monkeypatch.setattr(settings, "allow_real_client_data", False)
    mandate_id = _seed_minimal_mandate(session_factory, mandate_id="mandate-snap")
    advisor = User(id="advisor-notes", username="advisor-notes", password_hash="x",
                    full_name="Notes Advisor", role="advisor", is_active=1,
                    created_at=_now(), updated_at=_now())

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc:
            create_snapshot(
                mandate_id, _snapshot_payload("real"), _request_stub(),
                db=db, current_user=advisor,
            )
        _assert_phase_zero_block(exc)

    with session_factory() as db:
        assert db.query(StrategySnapshot).filter(
            StrategySnapshot.mandate_id == mandate_id
        ).count() == 0


def test_strategy_snapshot_synthetic_allowed_when_gate_closed(session_factory, monkeypatch):
    monkeypatch.setattr(settings, "allow_real_client_data", False)
    mandate_id = _seed_minimal_mandate(session_factory, mandate_id="mandate-snap2")
    advisor = User(id="advisor-notes", username="advisor-notes", password_hash="x",
                    full_name="Notes Advisor", role="advisor", is_active=1,
                    created_at=_now(), updated_at=_now())

    with session_factory() as db:
        result = create_snapshot(
            mandate_id, _snapshot_payload("synthetic"), _request_stub(),
            db=db, current_user=advisor,
        )
        assert result.mandate_id == mandate_id


# ---------------------------------------------------------------------------
# 2) POST /mandates/{id}/recommendations/{run_id}/portfolio-handoffs
# ---------------------------------------------------------------------------

def _seed_handoff_prereqs(session_factory, *, mandate_id="mandate-handoff", run_id="run-handoff"):
    with session_factory() as db:
        db.add(User(
            id="advisor-handoff", username="advisor-handoff", password_hash="x",
            full_name="Handoff Advisor", role="advisor", is_active=1,
            created_at=_now(), updated_at=_now(),
        ))
        db.add(Client(
            id="client-handoff", client_number="HANDOFF-1", first_name="H", last_name="Off",
            country_of_residence="CH", language="DE", household_type="Einzelperson",
            client_classification="Privatkunde", is_professional_opt_out=0,
            is_qualified_investor=0, advisor_id="advisor-handoff",
            created_at=_now(), updated_at=_now(),
        ))
        db.add(Mandate(
            id=mandate_id, client_id="client-handoff", mandate_number="HANDOFF-M-1",
            mandate_type="Vermögensverwaltung", status="Aktiv", base_currency="CHF",
            advisory_language="DE", opened_at="2026-09-21",
            created_at=_now(), updated_at=_now(),
        ))
        db.add(RecommendationRun(
            id=run_id, mandate_id=mandate_id, client_id="client-handoff", policy_id="policy-1",
            run_type="Initial", result_status="Final", created_by="advisor-handoff",
            created_at=_now(), updated_at=_now(),
        ))
        db.commit()
    return mandate_id, run_id


def _patch_handoff_engine(monkeypatch, *, rebalance_amount_rappen=50_000, total_value_rappen=1_000_000):
    payload = {
        "live_rebalancing": {
            "live_total_value_rappen": total_value_rappen,
            "position_drifts": [{
                "product_id": "prod-dcgate",
                "product_name": "Produkt DC-Gate",
                "asset_class": "Aktien",
                "sub_asset_class": "Aktien Global",
                "product_currency": "CHF",
                "rebalance_action": "BUY",
                "rebalance_action_code": "BUY",
                "current_market_value_rappen": 100_000,
                "target_amount_rappen": 100_000 + rebalance_amount_rappen,
                "rebalance_amount_rappen": rebalance_amount_rappen,
                "current_weight_bps": 1000,
                "target_weight_bps": 1200,
            }],
        }
    }
    monkeypatch.setattr(
        portfolio_handoff_service, "build_recommendation_payload_from_run", lambda **kw: payload,
    )


def test_portfolio_handoff_real_blocked_when_gate_closed(session_factory, monkeypatch):
    monkeypatch.setattr(settings, "allow_real_client_data", False)
    mandate_id, run_id = _seed_handoff_prereqs(session_factory)
    _patch_handoff_engine(monkeypatch)
    advisor = User(id="advisor-handoff", username="advisor-handoff", password_hash="x",
                    full_name="Handoff Advisor", role="advisor", is_active=1,
                    created_at=_now(), updated_at=_now())

    with session_factory() as db:
        with pytest.raises(HTTPException) as exc:
            create_portfolio_handoff(
                mandate_id=mandate_id, run_id=run_id,
                body=PortfolioHandoffCreate(
                    recipient_name="UBS AG Zuerich", data_classification="real",
                ),
                request=_request_stub(), db=db, current_user=advisor,
            )
        _assert_phase_zero_block(exc)


def test_portfolio_handoff_synthetic_allowed_when_gate_closed(session_factory, monkeypatch):
    monkeypatch.setattr(settings, "allow_real_client_data", False)
    mandate_id, run_id = _seed_handoff_prereqs(session_factory, mandate_id="mandate-handoff2", run_id="run-handoff2")
    _patch_handoff_engine(monkeypatch)
    advisor = User(id="advisor-handoff", username="advisor-handoff", password_hash="x",
                    full_name="Handoff Advisor", role="advisor", is_active=1,
                    created_at=_now(), updated_at=_now())

    with session_factory() as db:
        result = create_portfolio_handoff(
            mandate_id=mandate_id, run_id=run_id,
            body=PortfolioHandoffCreate(
                recipient_name="UBS AG Zuerich", data_classification="synthetic",
            ),
            request=_request_stub(), db=db, current_user=advisor,
        )
        assert result.recipient_name == "UBS AG Zuerich"
