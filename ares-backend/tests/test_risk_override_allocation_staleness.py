"""RISK-OVERRIDE-STALENESS-001 (Assetallocation-Audit 2026-10-14).

The risk-profile override endpoint mutates the current RiskAssessment row IN
PLACE (same id). Every staleness anchor compared only
``based_on_assessment_id`` with the current id, so an allocation generated for
the OLD score stayed current: served without warning, finalizable, depot check
"not stale", suitability audit "compliant".

Measured on the foundation case: score 7.0 -> override 3.0 "Defensiv"; the
allocation was generated with a risk budget of 8000 bps, the new budget is
4500 bps.

Control: an override BEFORE generation is the normal flow and must not mark
the (newer) allocation as stale.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import configure_mappers, sessionmaker

from database import Base
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
from models import tenant as _tenant  # noqa: F401
from fastapi import HTTPException

configure_mappers()

import routers.allocation as allocation_router  # noqa: E402
import routers.profiling as profiling_router  # noqa: E402
import services.portfolio_engine as pe  # noqa: E402
from models.allocation import TargetAllocation  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from models.profiling import RiskAssessment  # noqa: E402
from models.users import User  # noqa: E402
from routers.review import _validate_recommendation_for_finalization  # noqa: E402
from schemas.profiling import RiskAssessmentOverride  # noqa: E402
from services.depot_check import compute_depot_check  # noqa: E402
from services.foundation_example import (  # noqa: E402
    FOUNDATION_MANDATE_NUMBER,
    upsert_foundation_example_case,
)
from services.suitability_audit import audit_mandate_suitability  # noqa: E402

OVERRIDE = RiskAssessmentOverride(
    override_score_x10=30,
    override_profile="Defensiv",
    override_reason="Kunde wuenscht nach Verlusterfahrung eine defensive Ausrichtung",
    override_client_confirmed=True,
    override_warning_delivered=True,
)


@pytest.fixture()
def session_factory(tmp_path, monkeypatch):
    monkeypatch.setattr(pe, "_OPTIMIZER_N_PATHS_DEFAULT", 48, raising=False)
    engine = create_engine(f"sqlite:///{tmp_path / 'override.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    yield sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    engine.dispose()


def _seed(s):
    adv = User(id="advisor-1", username="advisor", password_hash="h", full_name="Advisor",
               role="advisor", is_active=1, created_at="2026-03-27T00:00:00.000Z",
               updated_at="2026-03-27T00:00:00.000Z")
    s.add(adv)
    s.commit()
    upsert_foundation_example_case(s, adv)
    s.commit()
    mandate = s.query(Mandate).filter(Mandate.mandate_number == FOUNDATION_MANDATE_NUMBER).one()
    return adv, mandate


def _request():
    return SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1"))


def _current(s, model, mandate_id):
    q = s.query(model).filter(model.mandate_id == mandate_id, model.is_current == 1)
    if hasattr(model, "deleted_at"):
        q = q.filter(model.deleted_at.is_(None))
    return q.one()


def test_override_after_generation_marks_allocation_stale_everywhere(session_factory):
    with session_factory() as s:
        adv, mandate = _seed(s)
        ta = _current(s, TargetAllocation, mandate.id)
        ra = _current(s, RiskAssessment, mandate.id)
        run = pe.generate_recommendation_run(
            db=s, mandate=mandate, user_id=adv.id, preferences=None,
            target_allocation_id=ta.id, run_type="Optimizer", depot_bank=None,
        )["run"]
        s.commit()
        errors_before, _ = _validate_recommendation_for_finalization(s, mandate, run)
        assert not any("Override" in e for e in errors_before)

        profiling_router.override_risk_assessment(
            mandate.id, ra.id, OVERRIDE, _request(), db=s, current_user=adv,
        )
        assert _current(s, RiskAssessment, mandate.id).id == ra.id  # in place

        with pytest.raises(HTTPException) as exc:
            allocation_router.get_current_allocation_payload(mandate.id, db=s, current_user=adv)
        assert exc.value.status_code == 409
        assert "Override" in str(exc.value.detail)

        s.refresh(run)
        errors, _warnings = _validate_recommendation_for_finalization(s, mandate, run)
        assert any("Override" in e for e in errors), errors

        assert compute_depot_check(s, mandate)["target_allocation_stale"] is True
        assert audit_mandate_suitability(s, mandate)["is_compliant"] is False


def test_override_before_generation_is_not_stale(session_factory):
    with session_factory() as s:
        adv, mandate = _seed(s)
        ra = _current(s, RiskAssessment, mandate.id)
        profiling_router.override_risk_assessment(
            mandate.id, ra.id, OVERRIDE, _request(), db=s, current_user=adv,
        )
        pe.generate_target_allocation(db=s, mandate=mandate, user_id=adv.id, preferences=None)
        s.commit()
        payload = allocation_router.get_current_allocation_payload(mandate.id, db=s, current_user=adv)
        payload = payload if isinstance(payload, dict) else payload.model_dump()
        assert payload["house_matrix_profile"] == "Defensiv"
        assert compute_depot_check(s, mandate)["target_allocation_stale"] is False
