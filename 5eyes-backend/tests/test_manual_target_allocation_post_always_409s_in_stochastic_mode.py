"""TA-EDITOR-WRITE-CONTRACT-001 (round 46 red test).

Verified against the real code in routers/allocation.py::create_target_allocation
(the manual ``POST /mandates/{id}/target-allocation`` endpoint that backs the
React AllocationEditor's "save" action, see
tests/test_allocation_editor_wiring_contract.py): after every other
compliance gate (archived/missing policy -> 404, missing strategy-ready risk
assessment -> 409, mismatched based_on_assessment_id -> 422) there is an
unconditional::

    if settings.optimizer_mode != "house_matrix":
        raise HTTPException(status_code=409, ...)

``optimizer_mode`` defaults to ``"stochastic"`` (config.py:278) and
production actively ENFORCES ``optimizer_mode == "stochastic"``
(config.py:571-573: ``app_env == 'production' and self.optimizer_mode !=
'stochastic'`` raises at startup). Combined, this means: in the one
``optimizer_mode`` value production is allowed to run with, this endpoint
409s unconditionally for every well-formed payload -- the manual "edit and
save a target allocation" workflow the React editor exposes is functionally
unreachable in production, independent of payload validity.

This test builds a mandate that clears every OTHER gate (current optimizer
policy, strategy-ready + fresh risk assessment, correctly-anchored
based_on_assessment_id, valid allocation/bands) and posts it with
``settings.optimizer_mode`` set to ``"stochastic"`` -- the production value
(sibling test test_audit_z1_strategy_gates.py::
test_c2_create_target_allocation_happy_path_returns_201 has to monkeypatch
optimizer_mode to the NON-default "house_matrix" to reach 201 at all, which
is exactly the gap documented here).

Desired/correct behaviour: a valid manual save must succeed (201) -- or be
routed through a working alternative path -- even while optimizer_mode is at
its production value. Currently it always 409s for this reason alone, so
this test is intentionally red (xfail, strict) until the endpoint's
optimizer_mode gate is removed/relaxed or the manual-save path is reworked.

See audit 2026-10-04-target-allocation-editor-context-and-release-lifecycle-
integrity-audit.md (not committed in this repo).
"""
from __future__ import annotations
import sys
import uuid
import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from config import settings
from database import Base, get_db
from main import app
from models import tenant as _tenant_model  # noqa: F401
from models.allocation import OptimizerPolicy
from models.clients import Client
from models.mandates import Mandate
from models.profiling import RiskAssessment
from models.users import User
from services.auth import get_current_user, require_advisor
from services.portfolio_engine import ensure_runtime_reference_data
from tests.risk_fixture_helpers import (
    CURRENT_RISK_SCHEMA_MARKERS,
    add_current_risk_answers,
    derive_current_risk_fields,
    noop_lifespan,
)


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'ta_write_contract.db'}",
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
    return User(id="user-ta-wc-1", username="adv", password_hash="h",
                full_name="Adv", role="advisor", is_active=1,
                created_at=_now(), updated_at=_now())


@pytest.fixture()
def auth_client(session_factory, advisor, monkeypatch):
    def _odb():
        with session_factory() as s:
            yield s
    monkeypatch.setattr(app.router, "lifespan_context", noop_lifespan)
    app.dependency_overrides[get_db] = _odb
    app.dependency_overrides[get_current_user] = lambda: advisor
    app.dependency_overrides[require_advisor] = lambda: advisor
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _make_client_and_mandate(session_factory, advisor):
    cid = str(uuid.uuid4())
    mid = str(uuid.uuid4())
    now = _now()
    with session_factory() as s:
        if not s.query(User).filter(User.id == advisor.id).first():
            s.add(advisor)
        s.add(Client(id=cid, client_number=f"C-{cid[:6]}",
                     first_name="T", last_name="X",
                     advisor_id=advisor.id, created_at=now, updated_at=now))
        s.add(Mandate(id=mid, client_id=cid, mandate_number=f"M-{mid[:6]}",
                      mandate_type="Anlageberatung", opened_at=now,
                      created_at=now, updated_at=now))
        s.commit()
    return cid, mid


def _seed_runtime(session_factory, advisor_id):
    with session_factory() as s:
        ensure_runtime_reference_data(s, advisor_id)
        s.commit()


def _add_strategy_ready_assessment(session_factory, mid, advisor_id):
    """Vollstaendige UND frische (365-Tage) Risikoprofilierung -- klärt das
    require_strategy_ready_assessment- UND das audit_mandate_suitability-Gate,
    falls require_suitability_before_recommendation aktiviert ist."""
    aid = str(uuid.uuid4())
    now = _now()
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
    with session_factory() as s:
        s.add(RiskAssessment(
            id=aid, mandate_id=mid, version=1, is_current=1,
            valid_from=now[:10],
            **risk_fields,
            is_overridden=0,
            **CURRENT_RISK_SCHEMA_MARKERS,
            assessed_at=now, assessed_by=advisor_id,
            created_at=now, updated_at=now,
        ))
        add_current_risk_answers(s, aid, now)
        s.commit()
    return aid


def _valid_ta_body(policy_id, based_on_assessment_id, **overrides):
    """Vollstaendig gueltiges TargetAllocationCreate-Payload -- Summe der
    target_*_bps = 10'000, alle Bands enthalten den jeweiligen Zielwert."""
    base = dict(
        policy_id=policy_id,
        based_on_assessment_id=based_on_assessment_id,
        target_equities_bps=4500, target_bonds_bps=3500,
        target_real_estate_bps=1000, target_alternatives_bps=500,
        target_liquidity_bps=500,
        band_equities_min_bps=2500, band_equities_max_bps=5500,
        band_bonds_min_bps=2500, band_bonds_max_bps=4500,
        band_real_estate_min_bps=500, band_real_estate_max_bps=1500,
        band_alternatives_min_bps=300, band_alternatives_max_bps=800,
        band_liquidity_min_bps=200, band_liquidity_max_bps=800,
    )
    base.update(overrides)
    return base


# TA-EDITOR-WRITE-CONTRACT-001 fixed (CERT-TA-WRITE-LIFECYCLE-001, 2026-10-09):
# routers/allocation.py::create_target_allocation no longer 409s on
# optimizer_mode alone -- the unconditional mode gate was removed and every
# manual write (any mode) now goes through the same modern-context build
# (CMA anchor, server-recomputed risky_fraction_bps, context artifacts) as
# the engine Generate path. xfail removed because this now genuinely passes
# (confirmed XPASS before removal); IMPLEMENTED_NOT_VERIFIED pending Codex's
# independent re-gate, not CLOSED.
def test_manual_target_allocation_post_always_409s_in_stochastic_mode(
    auth_client, session_factory, advisor, monkeypatch
):
    # Produktions-Default UND Produktions-ZWANG (config.py: app_env ==
    # 'production' erlaubt NUR optimizer_mode == 'stochastic'). Bewusst NICHT
    # auf "house_matrix" umgestellt -- genau das muesste der Happy-Path-
    # Sibling-Test (test_audit_z1_strategy_gates.py::
    # test_c2_create_target_allocation_happy_path_returns_201) tun, um
    # ueberhaupt 201 zu erreichen, was die Luecke erst sichtbar macht.
    monkeypatch.setattr(settings, "optimizer_mode", "stochastic")

    _seed_runtime(session_factory, advisor.id)
    cid, mid = _make_client_and_mandate(session_factory, advisor)
    aid = _add_strategy_ready_assessment(session_factory, mid, advisor.id)
    with session_factory() as s:
        policy_id = s.query(OptimizerPolicy).filter(
            OptimizerPolicy.is_current == 1
        ).first().id

    resp = auth_client.post(
        f"/mandates/{mid}/target-allocation",
        json=_valid_ta_body(policy_id, aid),
    )

    # Policy-404-Gate, Strategy-Ready-409-Gate und based_on_assessment_id-
    # 422-Gate sind hier alle geklaert (aktuelle Policy, vollstaendige+
    # frische Risikoprofilierung, korrekt verankerte assessment_id) -- ein
    # 409 an dieser Stelle kann NUR noch vom optimizer_mode-Gate kommen.
    assert resp.status_code != 409, (
        "Manuelles Speichern einer gueltigen Soll-Allokation darf im "
        "Produktions-optimizer_mode ('stochastic') nicht pauschal "
        f"blockiert sein. Response: {resp.status_code} {resp.text}"
    )
    assert resp.status_code in (200, 201), resp.text
