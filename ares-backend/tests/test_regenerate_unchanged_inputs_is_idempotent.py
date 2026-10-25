"""REGENERATE-IDEMPOTENT-001 (Assetallocation-Audit 2026-10-14).

Generation is deterministic: regenerating with unchanged inputs reproduces the
identical allocation (same targets, same ``allocation_context_hash``). It still
wrote a NEW version and demoted the current one -- which orphaned an already
certified Final recommendation bound to it: the current-recommendation payload
then answered 409 "basiert nicht auf der aktuellen Soll-Allokation" and the
Final run vanished from the client portal, although nothing had changed.

Expected: unchanged inputs -> the existing allocation stays current (same id,
same version); the Final run stays the current recommendation. Control: a
real input change (risk override) still produces a new version.
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

configure_mappers()

import routers.profiling as profiling_router  # noqa: E402
import services.portfolio_engine as pe  # noqa: E402
from models.allocation import TargetAllocation  # noqa: E402
from models.mandates import Mandate  # noqa: E402
from models.profiling import RiskAssessment  # noqa: E402
from models.review import RecommendationRun  # noqa: E402
from models.users import User  # noqa: E402
from routers.review import finalize_recommendation, get_current_recommendation_payload  # noqa: E402
from schemas.profiling import RiskAssessmentOverride  # noqa: E402
from services.foundation_example import (  # noqa: E402
    FOUNDATION_MANDATE_NUMBER,
    upsert_foundation_example_case,
)


@pytest.fixture()
def session_factory(tmp_path, monkeypatch):
    monkeypatch.setattr(pe, "_OPTIMIZER_N_PATHS_DEFAULT", 48, raising=False)
    engine = create_engine(f"sqlite:///{tmp_path / 'regen.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    yield sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    engine.dispose()


def _request():
    return SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1"))


def _seed(s):
    adv = User(id="advisor-1", username="advisor", password_hash="h", full_name="Advisor",
               role="advisor", is_active=1, created_at="2026-03-27T00:00:00.000Z",
               updated_at="2026-03-27T00:00:00.000Z")
    s.add(adv)
    s.commit()
    upsert_foundation_example_case(s, adv)
    s.commit()
    return adv, s.query(Mandate).filter(Mandate.mandate_number == FOUNDATION_MANDATE_NUMBER).one()


def _current_ta(s, mandate_id):
    return s.query(TargetAllocation).filter(
        TargetAllocation.mandate_id == mandate_id,
        TargetAllocation.is_current == 1,
        TargetAllocation.deleted_at.is_(None),
    ).one()


def test_regenerate_with_unchanged_inputs_keeps_allocation_and_final_run(session_factory):
    with session_factory() as s:
        adv, mandate = _seed(s)
        # Bring the allocation onto the current engine first (the foundation
        # seed may predate later engine changes) -- this is the version the
        # advisor certifies.
        ta = pe.generate_target_allocation(db=s, mandate=mandate, user_id=adv.id, preferences=None)["target_allocation"]
        s.commit()
        run = pe.generate_recommendation_run(
            db=s, mandate=mandate, user_id=adv.id, preferences=None,
            target_allocation_id=ta.id, run_type="Optimizer", depot_bank=None,
        )["run"]
        s.commit()
        finalize_recommendation(mandate.id, run.id, _request(), db=s, current_user=adv)
        assert s.get(RecommendationRun, run.id).result_status == "Final"

        again = pe.generate_target_allocation(db=s, mandate=mandate, user_id=adv.id, preferences=None)
        s.commit()

        current = _current_ta(s, mandate.id)
        assert again["target_allocation"].id == ta.id == current.id
        assert int(current.version) == int(ta.version)
        payload = get_current_recommendation_payload(mandate.id, db=s, current_user=adv)
        payload = payload if isinstance(payload, dict) else payload.model_dump()
        run_payload = payload.get("run") or payload.get("recommendation_run") or {}
        run_id = run_payload.get("id") if isinstance(run_payload, dict) else getattr(run_payload, "id", None)
        assert run_id == run.id


def test_real_input_change_still_creates_a_new_version(session_factory):
    with session_factory() as s:
        adv, mandate = _seed(s)
        ta = pe.generate_target_allocation(db=s, mandate=mandate, user_id=adv.id, preferences=None)["target_allocation"]
        s.commit()
        ra = s.query(RiskAssessment).filter(
            RiskAssessment.mandate_id == mandate.id, RiskAssessment.is_current == 1,
        ).one()
        profiling_router.override_risk_assessment(
            mandate.id, ra.id,
            RiskAssessmentOverride(
                override_score_x10=30, override_profile="Defensiv",
                override_reason="Kunde wuenscht nach Verlusterfahrung eine defensive Ausrichtung",
                override_client_confirmed=True, override_warning_delivered=True,
            ),
            _request(), db=s, current_user=adv,
        )
        new = pe.generate_target_allocation(db=s, mandate=mandate, user_id=adv.id, preferences=None)["target_allocation"]
        s.commit()
        assert new.id != ta.id
        assert int(new.version) == int(ta.version) + 1
