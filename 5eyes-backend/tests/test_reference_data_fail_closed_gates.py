"""Independent regression gates for allocation reference-data selection.

Test-only review surface: these cases exercise the production entry points and
jurisdiction resolver without monkeypatching their decision logic.  Missing or
ambiguous reference rows must fail before the stochastic solver and must never
cause runtime inserts in production.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

import services.portfolio_engine as pe
from models.allocation import (
    BuildingBlock,
    CapitalMarketAssumption,
    HouseMatrix,
    OptimizerPolicy,
    TargetAllocation,
)
from models.mandates import Mandate
from services.jurisdiction.exceptions import (
    JurisdictionReferenceDataConflictError,
    JurisdictionReferenceDataMissingError,
)
from services.jurisdiction.resolve import resolve_building_blocks_for_jurisdiction
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


def _policy(row_id: str) -> OptimizerPolicy:
    now = _now()
    return OptimizerPolicy(
        id=row_id,
        policy_name=f"Reference gate {row_id}",
        version=1,
        is_current=1,
        valid_from=now[:10],
        created_by="reference-gate",
        created_at=now,
        updated_at=now,
    )


def _building_block(
    row_id: str,
    policy_id: str,
    *,
    jurisdiction: str | None,
    asset_class: str = "Aktien",
    sub_asset_class: str = "Aktien Global",
    universe: str = "Standard",
) -> BuildingBlock:
    now = _now()
    return BuildingBlock(
        id=row_id,
        policy_id=policy_id,
        asset_class=asset_class,
        sub_asset_class=sub_asset_class,
        universe=universe,
        risky_fraction_bps=8000,
        is_active=1,
        jurisdiction=jurisdiction,
        created_at=now,
        updated_at=now,
    )


def _reference_counts(session) -> tuple[int, int, int, int]:
    return (
        session.query(OptimizerPolicy).count(),
        session.query(CapitalMarketAssumption).count(),
        session.query(HouseMatrix).count(),
        session.query(BuildingBlock).count(),
    )


@pytest.mark.parametrize("jurisdiction", ["CH", "DE"])
def test_duplicate_current_optimizer_policy_fails_closed_for_every_jurisdiction(
    session_factory,
    jurisdiction,
):
    with session_factory() as session:
        session.add_all(
            [
                _policy(f"policy-{jurisdiction.lower()}-a-{uuid.uuid4()}"),
                _policy(f"policy-{jurisdiction.lower()}-b-{uuid.uuid4()}"),
            ]
        )
        session.commit()
        before = _reference_counts(session)

        with pytest.raises(
            JurisdictionReferenceDataConflictError,
            match=r"Mehrere aktuelle OptimizerPolicy|nicht eindeutig",
        ):
            pe.ensure_runtime_reference_data(
                session,
                "reference-gate",
                jurisdiction=jurisdiction,
            )

        assert _reference_counts(session) == before


@pytest.mark.parametrize("missing_kind", ["policy", "cma"])
def test_production_missing_policy_or_cma_never_autoseeds(
    session_factory,
    monkeypatch,
    missing_kind,
):
    monkeypatch.setattr(pe.settings, "app_env", "production")
    with session_factory() as session:
        if missing_kind == "cma":
            session.add(_policy(f"policy-without-cma-{uuid.uuid4()}"))
            session.commit()
        before = _reference_counts(session)

        with pytest.raises(
            JurisdictionReferenceDataMissingError,
            match=r"Produktion|Autoseeding|OptimizerPolicy|CH-CMA",
        ):
            pe.ensure_runtime_reference_data(
                session,
                "reference-gate",
                jurisdiction="CH",
            )

        session.flush()
        assert _reference_counts(session) == before


@pytest.mark.parametrize("duplicate_scope", ["shared", "exact"])
def test_duplicate_building_block_logical_key_is_a_conflict(
    session_factory,
    duplicate_scope,
):
    policy_id = f"policy-bb-{duplicate_scope}-{uuid.uuid4()}"
    duplicate_jurisdiction = None if duplicate_scope == "shared" else "DE"
    with session_factory() as session:
        session.add(_policy(policy_id))
        session.add_all(
            [
                _building_block(
                    f"bb-{duplicate_scope}-a-{uuid.uuid4()}",
                    policy_id,
                    jurisdiction=duplicate_jurisdiction,
                ),
                _building_block(
                    f"bb-{duplicate_scope}-b-{uuid.uuid4()}",
                    policy_id,
                    jurisdiction=duplicate_jurisdiction,
                ),
            ]
        )
        if duplicate_scope == "shared":
            # Non-CH resolution requires at least one exact country row.  It is
            # deliberately a different logical key so it cannot override and
            # conceal the ambiguous shared sleeve above.
            session.add(
                _building_block(
                    f"bb-de-anchor-{uuid.uuid4()}",
                    policy_id,
                    jurisdiction="DE",
                    asset_class="Obligationen",
                    sub_asset_class="Obligationen EUR IG",
                )
            )
        session.commit()

        with pytest.raises(
            JurisdictionReferenceDataConflictError,
            match=r"Mehrere gleichrangige BuildingBlock|nicht eindeutig",
        ):
            resolve_building_blocks_for_jurisdiction(
                session,
                policy_id,
                "DE",
                investment_universe="Standard",
            )


def test_generate_rejects_explicit_alternative_universe_without_rows_before_solver(
    session_factory,
    monkeypatch,
):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    monkeypatch.setattr(pe, "_OPTIMIZER_N_PATHS_DEFAULT", 48)
    monkeypatch.setattr(
        pe,
        "_run_allocation_monte_carlo",
        lambda **_kwargs: {"goal_summaries": [], "current_goal_summaries": []},
    )
    advisor_id, _client_id, mandate_id, _assessment_id, _goal_id = (
        _seed_realistic_mandate(
            session_factory,
            suffix="explicit-alternative-universe-missing",
        )
    )
    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        mandate.investment_universe = "Alternativ"
        session.commit()
        before = session.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mandate_id
        ).count()

    solver_calls = _install_solver_double(monkeypatch, weights_bps=FINAL_WEIGHTS)
    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        with pytest.raises(
            JurisdictionReferenceDataMissingError,
            match=r"explizit.*Universum.*Alternativ|Alternativ.*CH",
        ):
            pe.generate_target_allocation(
                session,
                mandate,
                advisor_id,
                preferences=_preferences(),
            )
        assert session.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mandate_id
        ).count() == before

    assert solver_calls == []


def test_generate_accepts_explicit_standard_universe_when_standard_rows_exist(
    session_factory,
    monkeypatch,
):
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    monkeypatch.setattr(pe, "_OPTIMIZER_N_PATHS_DEFAULT", 48)
    monkeypatch.setattr(
        pe,
        "_run_allocation_monte_carlo",
        lambda **_kwargs: {"goal_summaries": [], "current_goal_summaries": []},
    )
    advisor_id, _client_id, mandate_id, _assessment_id, _goal_id = (
        _seed_realistic_mandate(
            session_factory,
            suffix="explicit-standard-universe",
        )
    )
    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        mandate.investment_universe = "Standard"
        session.commit()

    solver_calls = _install_solver_double(monkeypatch, weights_bps=FINAL_WEIGHTS)
    result = _generate(
        session_factory,
        mandate_id,
        advisor_id,
        _preferences(),
    )

    assert len(solver_calls) == 1
    assert result["target_allocation"].is_current == 1

