"""Welle 2.1 (2026-07): Opt-in FIDLEG-Suitability-Hard-Gate.

Hintergrund
-----------
Bis Welle 2.1 war der Suitability-Check ein reiner Sichtbarkeits-Layer
(services/suitability_audit.py) — ein Berater konnte einen Empfehlungs-Run
ausloesen OHNE dokumentierte Eignungspruefung; das System zeigte den Befund
nur an, blockierte aber nicht.

Diese Suite verifiziert das NEUE opt-in Hard-Gate im Router-Endpoint
POST /mandates/{id}/target-allocation/generate
(routers/allocation.py::generate_target_allocation_endpoint):

  (a) Flag AUS (Default) -> Run laeuft wie bisher durch (NON-BREAKING).
  (b) Flag AN + fehlende/nicht-konforme Eignungspruefung -> HTTP 409.
  (c) Flag AN + gueltige/konforme Eignungspruefung -> Run laeuft durch.

Das Gate ist bewusst NUR im Router verdrahtet (nicht in portfolio_engine),
und ruft services.suitability_audit.audit_mandate_suitability() auf. Da das
Audit-Ergebnis (is_compliant) das alleinige Block-Kriterium ist, patchen die
Faelle (b)/(c) die Audit-Funktion im Router-Namespace, um den Gate-Pfad
deterministisch und unabhaengig von der Audit-Internlogik zu pruefen.
"""
from __future__ import annotations

import datetime
import sys
import uuid
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import configure_mappers, sessionmaker

from database import Base
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, tenant,
    users, wealth,
)
configure_mappers()

from fastapi import HTTPException

import routers.allocation as alloc
from models.clients import Client
from models.mandates import Mandate
from models.profiling import RiskAssessment
from models.users import User
from models.wealth import Cashflow, WealthPosition
from schemas.allocation import TargetAllocationGenerateRequest
from services.portfolio_engine import ensure_runtime_reference_data
from tests.risk_fixture_helpers import (
    CURRENT_RISK_SCHEMA_MARKERS,
    add_current_risk_answers,
    derive_current_risk_fields,
)


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'suitability_gate.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False,
                      expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _seed_mandate(session_factory) -> tuple[str, str, str]:
    """Vollstaendig strategie-fertiges Mandat: Advisor + Client + Mandate +
    Beratungsdepot + aktuelles Risikoprofil + Reference-Data. Damit laeuft
    generate_target_allocation() ohne 409 aus fachlichen Gruenden durch."""
    advisor_id = "user-suit-gate"
    cid = str(uuid.uuid4())
    mid = str(uuid.uuid4())
    aid = str(uuid.uuid4())
    now = _now()
    with session_factory() as s:
        s.add(User(id=advisor_id, username="adv-suit", password_hash="h",
                   full_name="Adv Suit", role="advisor", is_active=1,
                   created_at=now, updated_at=now))
        s.add(Client(id=cid, client_number=f"C-{cid[:6]}",
                     first_name="Suit", last_name="Gate",
                     advisor_id=advisor_id, created_at=now, updated_at=now))
        s.add(Mandate(id=mid, client_id=cid, mandate_number=f"M-{mid[:6]}",
                      mandate_type="Anlageberatung", opened_at=now,
                      created_at=now, updated_at=now))
        s.add(WealthPosition(
            id="pos-suit-depot", client_id=cid,
            label="Depot", position_type="Depot",
            assignment="Beratungsvermögen",
            current_value_rappen=200_000_00, currency="CHF",
            alloc_equities_bps=4000, alloc_bonds_bps=3000,
            alloc_real_estate_bps=0, alloc_liquidity_bps=2000,
            alloc_alternatives_bps=1000,
            is_active=1, created_at=now, updated_at=now,
        ))
        s.add(Cashflow(
            id="cf-suit-savings", client_id=cid, label="Sparplan",
            cashflow_type="Income", amount_rappen=30_000_00,
            currency="CHF", frequency="jährlich", nature="wiederkehrend",
            is_active=1, created_at=now, updated_at=now,
        ))
        risk_fields = derive_current_risk_fields(
            q_income_points=2,
            q_obligations_points=3,
            q_savings_points=2,
            q_wealth_points=2,
            investment_horizon_label="8 bis 11 Jahre",
            q_investment_goal_points=3,
            q_risk_preference_points=3,
            q_risk_behavior_points=3,
        )
        s.add(RiskAssessment(
            id=aid, mandate_id=mid, version=1, is_current=1, valid_from=now[:10],
            **risk_fields,
            is_overridden=0,
            **CURRENT_RISK_SCHEMA_MARKERS,
            assessed_at=now, assessed_by=advisor_id,
            created_at=now, updated_at=now,
        ))
        add_current_risk_answers(s, aid, now)
        s.commit()
        ensure_runtime_reference_data(s, advisor_id)
        s.commit()
    return advisor_id, cid, mid


class _FakeClient:
    def __init__(self, host="127.0.0.1"):
        self.host = host


class _FakeRequest:
    def __init__(self, host="127.0.0.1"):
        self.headers = {}
        self.client = _FakeClient(host)


def _call_generate(session_factory, advisor_id: str, mid: str):
    with session_factory() as s:
        advisor = s.query(User).filter(User.id == advisor_id).first()
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        return alloc.generate_target_allocation_endpoint(
            mandate_id=mid,
            body=TargetAllocationGenerateRequest(),
            request=_FakeRequest(),
            db=s,
            current_user=advisor,
        )


# ---------------------------------------------------------------------------
# (a) Flag AUS (Default) -> Run laeuft durch (NON-BREAKING)
# ---------------------------------------------------------------------------

def test_gate_default_off_run_proceeds(session_factory, monkeypatch):
    """Default: require_suitability_before_recommendation=False -> kein Gate,
    Run generiert eine TargetAllocation wie bisher. audit_mandate_suitability
    darf NICHT aufgerufen werden."""
    advisor_id, _cid, mid = _seed_mandate(session_factory)
    assert alloc.settings.require_suitability_before_recommendation is False

    def _fail_audit(*_a, **_k):  # pragma: no cover - darf nicht laufen
        raise AssertionError("Audit darf bei ausgeschaltetem Flag nicht laufen")

    monkeypatch.setattr(alloc, "audit_mandate_suitability", _fail_audit)

    result = _call_generate(session_factory, advisor_id, mid)
    assert result["target_allocation"] is not None
    assert result["target_allocation"].id


# ---------------------------------------------------------------------------
# (b) Flag AN + fehlende Eignungspruefung -> HTTP 409
# ---------------------------------------------------------------------------

def test_gate_on_missing_suitability_blocks_409(session_factory, monkeypatch):
    advisor_id, _cid, mid = _seed_mandate(session_factory)
    monkeypatch.setattr(
        alloc.settings, "require_suitability_before_recommendation", True)
    monkeypatch.setattr(
        alloc, "audit_mandate_suitability",
        lambda db, mandate: {
            "is_compliant": False,
            "logs_without_suitability": [{"id": "log-x",
                                          "reason": "no_suitability_check_linked"}],
            "fidleg_basis": "Art. 11/13/16 FIDLEG",
        },
    )

    with pytest.raises(HTTPException) as exc_info:
        _call_generate(session_factory, advisor_id, mid)
    assert exc_info.value.status_code == 409
    assert "FIDLEG" in exc_info.value.detail
    assert "require_suitability_before_recommendation" in exc_info.value.detail


# ---------------------------------------------------------------------------
# (c) Flag AN + gueltige Eignungspruefung -> Run laeuft durch
# ---------------------------------------------------------------------------

def test_gate_on_compliant_suitability_run_proceeds(session_factory, monkeypatch):
    advisor_id, _cid, mid = _seed_mandate(session_factory)
    monkeypatch.setattr(
        alloc.settings, "require_suitability_before_recommendation", True)
    monkeypatch.setattr(
        alloc, "audit_mandate_suitability",
        lambda db, mandate: {
            "is_compliant": True,
            "logs_without_suitability": [],
            "fidleg_basis": "Art. 11/13/16 FIDLEG",
        },
    )

    result = _call_generate(session_factory, advisor_id, mid)
    assert result["target_allocation"] is not None
    assert result["target_allocation"].id
