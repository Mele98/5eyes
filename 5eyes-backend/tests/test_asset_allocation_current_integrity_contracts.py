"""Fail-closed contracts for current allocation reference resolution.

These tests cover jurisdiction-scoped reloads and ambiguous/deleted anchors at
the service/router boundary.  They intentionally mutate ORM rows to emulate
legacy imports or manual database repairs that bypass request validation.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import text

import routers.allocation as allocation_router
import services.portfolio_engine as pe
from models.allocation import (
    BuildingBlock,
    CapitalMarketAssumption,
    OptimizerPolicy,
    TargetAllocation,
)
from models.mandates import Mandate
from models.profiling import RiskAssessment
from models.users import User
from test_engine_de_jurisdiction_wiring import _seed_de_mandate
from test_optimizer_production_contract import (
    _generate,
    _install_solver_double,
    _preferences,
    _seed_realistic_mandate,
    session_factory,  # noqa: F401 - shared isolated-database fixture
)


FINAL_WEIGHTS = {
    "equities": 5000,
    "bonds": 3000,
    "real_estate": 500,
    "alternatives": 1000,
    "liquidity": 500,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _clone_row(source, model, **overrides):
    values = {
        column.name: getattr(source, column.name)
        for column in model.__table__.columns
    }
    values.update(overrides)
    return model(**values)


@pytest.fixture(autouse=True)
def _fast_reporting_layers(monkeypatch):
    monkeypatch.setattr(pe, "_OPTIMIZER_N_PATHS_DEFAULT", 48)
    monkeypatch.setattr(
        pe,
        "_run_allocation_monte_carlo",
        lambda **_kwargs: {"goal_summaries": [], "current_goal_summaries": []},
    )


def test_de_current_payload_uses_exact_jurisdiction_and_tenant_context(
    session_factory,
    monkeypatch,
):
    """A persisted DE strategy reload must never enter the CH auto-seed path."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, mandate_id, tenant_id = _seed_de_mandate(
        session_factory,
        suffix="current-payload-context",
        cma_status="committee_approved",
    )
    _install_solver_double(monkeypatch, weights_bps=FINAL_WEIGHTS)
    generated = _generate(
        session_factory,
        mandate_id,
        advisor_id,
        preferences=None,
    )

    def _unexpected_ch_seed(*_args, **_kwargs):
        raise AssertionError("DE current payload entered CH bootstrap")

    monkeypatch.setattr(pe, "_ensure_runtime_reference_data_ch", _unexpected_ch_seed)
    original_resolver = allocation_router.ensure_runtime_reference_data
    calls: list[dict] = []

    def _capturing_resolver(db, user_id, *, jurisdiction="CH", tenant_id=None):
        calls.append({
            "user_id": user_id,
            "jurisdiction": jurisdiction,
            "tenant_id": tenant_id,
        })
        return original_resolver(
            db,
            user_id,
            jurisdiction=jurisdiction,
            tenant_id=tenant_id,
        )

    monkeypatch.setattr(
        allocation_router,
        "ensure_runtime_reference_data",
        _capturing_resolver,
    )

    with session_factory() as session:
        advisor = session.query(User).filter(User.id == advisor_id).one()
        payload = allocation_router.get_current_allocation_payload(
            mandate_id,
            db=session,
            current_user=advisor,
        )

    assert calls == [{
        "user_id": advisor_id,
        "jurisdiction": "DE",
        "tenant_id": tenant_id,
    }]
    assert payload["target_allocation"].id == generated["target_allocation"].id
    labels = {
        str(row["sub_asset_class"])
        for row in payload["sub_allocations"]
    }
    assert any("Deutschland" in label for label in labels)
    assert not any("Schweiz" in label or "CHF" in label for label in labels)


def test_de_current_payload_missing_exact_reference_rows_is_409(
    session_factory,
    monkeypatch,
):
    """A stored snapshot does not authorize replacement with CH reference rows."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, mandate_id, _tenant_id = _seed_de_mandate(
        session_factory,
        suffix="current-payload-missing-de",
        cma_status="committee_approved",
    )
    _install_solver_double(monkeypatch, weights_bps=FINAL_WEIGHTS)
    _generate(session_factory, mandate_id, advisor_id, preferences=None)

    with session_factory() as session:
        for row in session.query(BuildingBlock).filter(
            BuildingBlock.jurisdiction == "DE",
            BuildingBlock.is_active == 1,
        ).all():
            row.is_active = 0
        session.commit()

    def _unexpected_ch_seed(*_args, **_kwargs):
        raise AssertionError("missing DE rows triggered CH bootstrap")

    monkeypatch.setattr(pe, "_ensure_runtime_reference_data_ch", _unexpected_ch_seed)

    with session_factory() as session:
        advisor = session.query(User).filter(User.id == advisor_id).one()
        with pytest.raises(HTTPException) as exc_info:
            allocation_router.get_current_allocation_payload(
                mandate_id,
                db=session,
                current_user=advisor,
            )

    assert exc_info.value.status_code == 409
    assert "DE" in str(exc_info.value.detail) or "Referenz" in str(
        exc_info.value.detail
    )


def test_soft_deleted_snapshot_cma_rejects_current_replacement(
    session_factory,
    monkeypatch,
):
    """A modern allocation is inseparable from its exact, non-deleted CMA."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _client_id, mandate_id, _assessment_id, _goal_id = (
        _seed_realistic_mandate(
            session_factory,
            suffix="soft-deleted-cma-anchor",
        )
    )
    _install_solver_double(monkeypatch, weights_bps=FINAL_WEIGHTS)
    generated = _generate(
        session_factory,
        mandate_id,
        advisor_id,
        _preferences(),
    )

    with session_factory() as session:
        allocation = session.query(TargetAllocation).filter(
            TargetAllocation.id == generated["target_allocation"].id
        ).one()
        snapshot = session.query(CapitalMarketAssumption).filter(
            CapitalMarketAssumption.id
            == allocation.capital_market_assumptions_id
        ).one()
        snapshot_id = snapshot.id
        snapshot.is_current = 0
        snapshot.deleted_at = _now()
        session.flush()
        replacement = _clone_row(
            snapshot,
            CapitalMarketAssumption,
            id=f"replacement-cma-{uuid.uuid4()}",
            version=int(snapshot.version or 0) + 1,
            is_current=1,
            deleted_at=None,
            assumption_set_name=f"Replacement for {snapshot_id}",
        )
        session.add(replacement)
        session.commit()

        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        policy = session.query(OptimizerPolicy).filter(
            OptimizerPolicy.id == allocation.policy_id
        ).one()
        assessment = session.query(RiskAssessment).filter(
            RiskAssessment.id == allocation.based_on_assessment_id
        ).one()
        with pytest.raises(ValueError, match=r"CMA|Kapitalmarkt|verfuegbar"):
            pe.build_target_payload_from_allocation(
                session,
                mandate,
                allocation,
                policy,
                replacement,
                assessment,
                preferences=None,
            )

        advisor = session.query(User).filter(User.id == advisor_id).one()
        with pytest.raises(HTTPException) as exc_info:
            allocation_router.get_current_allocation_payload(
                mandate_id,
                db=session,
                current_user=advisor,
            )

    assert allocation.capital_market_assumptions_id == snapshot_id
    assert replacement.id != snapshot_id
    assert exc_info.value.status_code == 409
    assert "CMA" in str(exc_info.value.detail) or "Kapitalmarkt" in str(
        exc_info.value.detail
    )


def test_duplicate_current_risk_assessment_blocks_generate_and_payload(
    session_factory,
    monkeypatch,
):
    """Score/risk-budget selection must be unique on all consuming paths."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _client_id, mandate_id, assessment_id, _goal_id = (
        _seed_realistic_mandate(
            session_factory,
            suffix="duplicate-current-assessment",
        )
    )
    _install_solver_double(monkeypatch, weights_bps=FINAL_WEIGHTS)
    _generate(session_factory, mandate_id, advisor_id, _preferences())

    with session_factory() as session:
        # Defense in depth for pre-migration/externally damaged databases: the
        # new partial unique index normally blocks this state at INSERT time.
        # Drop it only inside this isolated SQLite fixture so the service-level
        # exact-one resolver remains independently verified.
        session.execute(text("DROP INDEX ux_risk_one_current"))
        source = session.query(RiskAssessment).filter(
            RiskAssessment.id == assessment_id
        ).one()
        session.add(_clone_row(
            source,
            RiskAssessment,
            id=f"duplicate-assessment-{uuid.uuid4()}",
            version=int(source.version or 0) + 1,
            is_current=1,
        ))
        session.commit()

        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        before = session.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mandate_id
        ).count()
        with pytest.raises(ValueError, match=r"Mehrere aktuelle Risikoprofile"):
            pe.generate_target_allocation(
                session,
                mandate,
                advisor_id,
                preferences=_preferences(),
            )
        after = session.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mandate_id
        ).count()

        advisor = session.query(User).filter(User.id == advisor_id).one()
        with pytest.raises(HTTPException) as exc_info:
            allocation_router.get_current_allocation_payload(
                mandate_id,
                db=session,
                current_user=advisor,
            )

    assert after == before
    assert exc_info.value.status_code == 409
    assert "Mehrere aktuelle Risikoprofile" in str(exc_info.value.detail)


def test_duplicate_current_target_allocation_blocks_current_endpoints_and_generate(
    session_factory,
    monkeypatch,
):
    """No current consumer may pick an arbitrary strategy decision."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _client_id, mandate_id, _assessment_id, _goal_id = (
        _seed_realistic_mandate(
            session_factory,
            suffix="duplicate-current-allocation",
        )
    )
    _install_solver_double(monkeypatch, weights_bps=FINAL_WEIGHTS)
    generated = _generate(
        session_factory,
        mandate_id,
        advisor_id,
        _preferences(),
    )

    with session_factory() as session:
        # See the RiskAssessment sibling above.  Database uniqueness has its
        # own migration/ORM tests; this contract deliberately emulates a
        # legacy database without the index and verifies consumer fail-closed.
        session.execute(text("DROP INDEX ux_target_alloc_one_current"))
        source = session.query(TargetAllocation).filter(
            TargetAllocation.id == generated["target_allocation"].id
        ).one()
        session.add(_clone_row(
            source,
            TargetAllocation,
            id=f"duplicate-allocation-{uuid.uuid4()}",
            version=int(source.version or 0) + 1,
            is_current=1,
        ))
        session.commit()

        advisor = session.query(User).filter(User.id == advisor_id).one()
        for current_endpoint in (
            allocation_router.get_current_allocation,
            allocation_router.get_current_allocation_payload,
        ):
            with pytest.raises(HTTPException) as exc_info:
                current_endpoint(
                    mandate_id,
                    db=session,
                    current_user=advisor,
                )
            assert exc_info.value.status_code == 409
            assert "Mehrere aktuelle Soll-Allokationen" in str(
                exc_info.value.detail
            )

        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        before = session.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mandate_id
        ).count()
        with pytest.raises(ValueError, match=r"Mehrere aktuelle Soll-Allokationen"):
            pe.generate_target_allocation(
                session,
                mandate,
                advisor_id,
                preferences=_preferences(),
            )
        after = session.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mandate_id
        ).count()

    assert after == before
