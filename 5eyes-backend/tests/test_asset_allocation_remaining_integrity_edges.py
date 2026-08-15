"""Remaining fail-closed contracts for the allocation decision boundary.

These tests deliberately insert rows through the ORM instead of the API.  The
engine must defend its own boundary even when legacy imports, migrations or
manual database repairs bypass request-schema validation.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

import services.portfolio_engine as pe
from models.allocation import (
    CapitalMarketAssumption,
    HouseMatrix,
    OptimizerPolicy,
    TargetAllocation,
)
from models.clients import Client
from models.mandates import Mandate
from models.profiling import RiskAssessment
from models.wealth import Cashflow, Goal, WealthInflow, WealthPosition
from services.jurisdiction.exceptions import (
    JurisdictionReferenceDataConflictError,
)
from services.jurisdiction.resolve import resolve_cma_for_jurisdiction
from test_optimizer_production_contract import (
    _generate,
    _install_solver_double,
    _preferences,
    _reload_payload,
    _seed_realistic_mandate,
    session_factory,  # noqa: F401 - shared isolated-database pytest fixture
)


FINAL_WEIGHTS = {
    "equities": 5000,
    "bonds": 3000,
    "real_estate": 500,
    "alternatives": 1000,
    "liquidity": 500,
}


@pytest.fixture(autouse=True)
def _fast_reporting_layers(monkeypatch):
    """Keep boundary tests focused; the optimizer call itself remains observed."""
    monkeypatch.setattr(pe, "_OPTIMIZER_N_PATHS_DEFAULT", 48)
    monkeypatch.setattr(
        pe,
        "_run_allocation_monte_carlo",
        lambda **_kwargs: {"goal_summaries": [], "current_goal_summaries": []},
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _add_raw_inflow(
    session,
    *,
    client_id: str,
    mandate_id: str,
    is_active: int,
    suffix: str,
) -> WealthInflow:
    inflow = WealthInflow(
        id=f"raw-inflow-{suffix}-{uuid.uuid4()}",
        client_id=client_id,
        mandate_id=mandate_id,
        label=f"Raw inflow {suffix}",
        source_type="Erbschaft",
        amount_rappen=90_000_000,
        expected_year=date.today().year + 3,
        is_recurring=0,
        frequency="einmalig",
        duration_years=None,
        value_mode="nominal",
        is_active=is_active,
        created_at=_now(),
        updated_at=_now(),
    )
    session.add(inflow)
    return inflow


def _add_raw_position(
    session,
    *,
    client_id: str,
    is_active: int,
    suffix: str,
) -> WealthPosition:
    row = WealthPosition(
        id=f"raw-position-{suffix}-{uuid.uuid4()}",
        client_id=client_id,
        label=f"Raw position {suffix}",
        position_type="Depot",
        assignment="Anderes Vermoegen",
        current_value_rappen=70_000_000,
        currency="CHF",
        alloc_equities_bps=4000,
        alloc_bonds_bps=3000,
        alloc_real_estate_bps=1000,
        alloc_alternatives_bps=1000,
        alloc_liquidity_bps=1000,
        is_active=is_active,
        created_at=_now(),
        updated_at=_now(),
    )
    session.add(row)
    return row


def _add_raw_cashflow(
    session,
    *,
    client_id: str,
    is_active: int,
    suffix: str,
    frequency: str = "jaehrlich",
    valid_from: str | None = None,
    valid_until: str | None = None,
) -> Cashflow:
    row = Cashflow(
        id=f"raw-cashflow-{suffix}-{uuid.uuid4()}",
        client_id=client_id,
        cashflow_type="Income",
        label=f"Raw cashflow {suffix}",
        amount_rappen=12_000_000,
        currency="CHF",
        frequency=frequency,
        nature="wiederkehrend",
        valid_from=valid_from,
        valid_until=valid_until,
        is_inflation_linked=0,
        is_active=is_active,
        created_at=_now(),
        updated_at=_now(),
    )
    session.add(row)
    return row


def _add_raw_goal(
    session,
    *,
    client_id: str,
    mandate_id: str,
    is_active: int,
    suffix: str,
    goal_type: str = "Pensionsausgabe",
    frequency: str | None = "jaehrlich",
) -> Goal:
    row = Goal(
        id=f"raw-goal-{suffix}-{uuid.uuid4()}",
        mandate_id=mandate_id,
        client_id=client_id,
        goal_family="Lebenshaltung",
        goal_type=goal_type,
        label=f"Raw goal {suffix}",
        rank=9,
        weight_bps=1000,
        goal_scope="Beratungsvermoegen",
        value_mode="nominal",
        target_amount_rappen=15_000_000,
        start_date=f"{date.today().year + 5}-01-01",
        target_date=f"{date.today().year + 10}-12-31",
        is_ongoing=0,
        frequency=frequency,
        hardness="Primaer",
        probability_pct=100,
        is_active=is_active,
        created_at=_now(),
        updated_at=_now(),
    )
    session.add(row)
    return row


RAW_MODEL_ERROR_CASES = (
    ("position_active_flag", r"Vermoegensposition|WealthPosition|is_active.*0 oder 1"),
    ("cashflow_active_flag", r"Cashflow|is_active.*0 oder 1"),
    ("goal_active_flag", r"Ziel|Goal|is_active.*0 oder 1"),
    ("cashflow_frequency", r"Cashflow.*Frequenz|frequency|Frequenz"),
    ("cashflow_date_order", r"Enddatum.*Startdatum|valid_until|valid_from|Gueltig"),
    ("goal_type", r"goal_type|Zieltyp|Zielart"),
    ("goal_frequency", r"Ziel.*Frequenz|Goal.*frequency|Frequenz"),
)


def _add_invalid_raw_model_row(
    session,
    *,
    case: str,
    client_id: str,
    mandate_id: str,
) -> None:
    if case == "position_active_flag":
        _add_raw_position(
            session,
            client_id=client_id,
            is_active=2,
            suffix=case,
        )
    elif case == "cashflow_active_flag":
        _add_raw_cashflow(
            session,
            client_id=client_id,
            is_active=2,
            suffix=case,
        )
    elif case == "goal_active_flag":
        _add_raw_goal(
            session,
            client_id=client_id,
            mandate_id=mandate_id,
            is_active=2,
            suffix=case,
        )
    elif case == "cashflow_frequency":
        _add_raw_cashflow(
            session,
            client_id=client_id,
            is_active=1,
            suffix=case,
            frequency="weekly-ish",
        )
    elif case == "cashflow_date_order":
        _add_raw_cashflow(
            session,
            client_id=client_id,
            is_active=1,
            suffix=case,
            valid_from="2031-01-01",
            valid_until="2030-12-31",
        )
    elif case == "goal_type":
        _add_raw_goal(
            session,
            client_id=client_id,
            mandate_id=mandate_id,
            is_active=1,
            suffix=case,
            goal_type="Unbekanntes_Modellziel",
            frequency=None,
        )
    elif case == "goal_frequency":
        _add_raw_goal(
            session,
            client_id=client_id,
            mandate_id=mandate_id,
            is_active=1,
            suffix=case,
            frequency="stuendlich",
        )
    else:
        raise AssertionError(f"unknown raw model test case: {case}")


def _invalid_inflow_mandate_id(
    session,
    *,
    invalid_kind: str,
    target_client_id: str,
    target_mandate_id: str,
    advisor_id: str,
) -> tuple[str, int]:
    if invalid_kind == "invalid_active_flag":
        return target_mandate_id, 2
    if invalid_kind == "missing_mandate":
        return f"missing-mandate-{uuid.uuid4()}", 1
    if invalid_kind != "cross_client_mandate":
        raise AssertionError(f"unknown test case: {invalid_kind}")

    foreign_client = Client(
        id=f"foreign-client-{uuid.uuid4()}",
        client_number=f"C-FOREIGN-{uuid.uuid4().hex[:8]}",
        first_name="Foreign",
        last_name="Client",
        advisor_id=advisor_id,
        created_at=_now(),
        updated_at=_now(),
    )
    foreign_mandate = Mandate(
        id=f"foreign-mandate-{uuid.uuid4()}",
        client_id=foreign_client.id,
        mandate_number=f"M-FOREIGN-{uuid.uuid4().hex[:8]}",
        mandate_type="Anlageberatung",
        opened_at=_now(),
        created_at=_now(),
        updated_at=_now(),
    )
    session.add_all([foreign_client, foreign_mandate])
    session.flush()
    assert foreign_client.id != target_client_id
    return foreign_mandate.id, 1


@pytest.mark.parametrize(
    "invalid_kind,error_pattern",
    [
        ("invalid_active_flag", r"is_active.*0 oder 1"),
        ("missing_mandate", r"fehlendes Mandat|fehlenden Mandat"),
        ("cross_client_mandate", r"anderen Kunden"),
    ],
)
def test_generation_rejects_raw_invalid_wealth_inflow_before_solver(
    session_factory,
    monkeypatch,
    invalid_kind,
    error_pattern,
):
    """Malformed imported inflows must never reach stochastic optimization."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, client_id, mandate_id, _assessment_id, _goal_id = (
        _seed_realistic_mandate(
            session_factory,
            suffix=f"raw-inflow-generate-{invalid_kind}",
        )
    )
    calls = _install_solver_double(monkeypatch, weights_bps=FINAL_WEIGHTS)

    with session_factory() as session:
        invalid_mandate_id, is_active = _invalid_inflow_mandate_id(
            session,
            invalid_kind=invalid_kind,
            target_client_id=client_id,
            target_mandate_id=mandate_id,
            advisor_id=advisor_id,
        )
        _add_raw_inflow(
            session,
            client_id=client_id,
            mandate_id=invalid_mandate_id,
            is_active=is_active,
            suffix=f"generate-{invalid_kind}",
        )
        session.commit()

        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        before = session.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mandate_id
        ).count()
        with pytest.raises(ValueError, match=error_pattern):
            pe.generate_target_allocation(
                session,
                mandate,
                advisor_id,
                preferences=_preferences(),
            )
        after = session.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mandate_id
        ).count()

    assert calls == []
    assert after == before


@pytest.mark.parametrize(
    "invalid_kind,error_pattern",
    [
        ("invalid_active_flag", r"is_active.*0 oder 1"),
        ("missing_mandate", r"fehlendes Mandat|fehlenden Mandat"),
        ("cross_client_mandate", r"anderen Kunden"),
    ],
)
def test_reload_rejects_raw_invalid_wealth_inflow(
    session_factory,
    monkeypatch,
    invalid_kind,
    error_pattern,
):
    """Reload must not publish an old allocation over malformed live inputs."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, client_id, mandate_id, _assessment_id, _goal_id = (
        _seed_realistic_mandate(
            session_factory,
            suffix=f"raw-inflow-reload-{invalid_kind}",
        )
    )
    calls = _install_solver_double(monkeypatch, weights_bps=FINAL_WEIGHTS)
    generated = _generate(
        session_factory,
        mandate_id,
        advisor_id,
        _preferences(),
    )
    assert len(calls) == 1

    with session_factory() as session:
        invalid_mandate_id, is_active = _invalid_inflow_mandate_id(
            session,
            invalid_kind=invalid_kind,
            target_client_id=client_id,
            target_mandate_id=mandate_id,
            advisor_id=advisor_id,
        )
        _add_raw_inflow(
            session,
            client_id=client_id,
            mandate_id=invalid_mandate_id,
            is_active=is_active,
            suffix=f"reload-{invalid_kind}",
        )
        session.commit()

        allocation = session.query(TargetAllocation).filter(
            TargetAllocation.id == generated["target_allocation"].id
        ).one()
        with pytest.raises(ValueError, match=error_pattern):
            _reload_payload(session, allocation)

    assert len(calls) == 1, "Reload must not invoke the stochastic solver"


def test_inactive_raw_wealth_inflow_is_excluded_from_generation_and_reload(
    session_factory,
    monkeypatch,
):
    """A canonical is_active=0 row is ignored without becoming an error."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, client_id, mandate_id, _assessment_id, _goal_id = (
        _seed_realistic_mandate(
            session_factory,
            suffix="raw-inflow-inactive",
        )
    )
    with session_factory() as session:
        _add_raw_inflow(
            session,
            client_id=client_id,
            mandate_id=mandate_id,
            is_active=0,
            suffix="inactive",
        )
        session.commit()

        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        cma = session.query(CapitalMarketAssumption).filter(
            CapitalMarketAssumption.is_current == 1,
            CapitalMarketAssumption.deleted_at.is_(None),
        ).one()
        loaded = pe._load_allocation_inputs(
            session,
            mandate,
            simulation_prefs=_preferences()["simulation"],
            cma=cma,
        )
        assert loaded["wealth_inflows"] == []
        assert not any(loaded["inflow_projection_series_rappen"])

    calls = _install_solver_double(monkeypatch, weights_bps=FINAL_WEIGHTS)
    generated = _generate(
        session_factory,
        mandate_id,
        advisor_id,
        _preferences(),
    )
    assert len(calls) == 1

    with session_factory() as session:
        allocation = session.query(TargetAllocation).filter(
            TargetAllocation.id == generated["target_allocation"].id
        ).one()
        payload = _reload_payload(session, allocation)
        assert payload["target_allocation"].id == allocation.id
    assert len(calls) == 1


@pytest.mark.parametrize("raw_case,error_pattern", RAW_MODEL_ERROR_CASES)
def test_generation_rejects_invalid_raw_position_cashflow_or_goal_before_solver(
    session_factory,
    monkeypatch,
    raw_case,
    error_pattern,
):
    """Every raw planning row is validated before the stochastic call."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, client_id, mandate_id, _assessment_id, _goal_id = (
        _seed_realistic_mandate(
            session_factory,
            suffix=f"raw-model-generate-{raw_case}",
        )
    )
    with session_factory() as session:
        _add_invalid_raw_model_row(
            session,
            case=raw_case,
            client_id=client_id,
            mandate_id=mandate_id,
        )
        session.commit()

    calls = _install_solver_double(monkeypatch, weights_bps=FINAL_WEIGHTS)
    analytics_calls: list[dict] = []
    monkeypatch.setattr(
        pe,
        "_run_allocation_monte_carlo",
        lambda **kwargs: analytics_calls.append(kwargs) or {
            "goal_summaries": [],
            "current_goal_summaries": [],
        },
    )
    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        before = session.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mandate_id
        ).count()
        with pytest.raises(ValueError, match=error_pattern):
            pe.generate_target_allocation(
                session,
                mandate,
                advisor_id,
                preferences=_preferences(),
            )
        after = session.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mandate_id
        ).count()

    assert calls == []
    assert analytics_calls == []
    assert after == before


@pytest.mark.parametrize("raw_case,error_pattern", RAW_MODEL_ERROR_CASES)
def test_reload_rejects_invalid_raw_position_cashflow_or_goal_before_analytics(
    session_factory,
    monkeypatch,
    raw_case,
    error_pattern,
):
    """Reload applies the same raw-row gate before republishing analytics."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, client_id, mandate_id, _assessment_id, _goal_id = (
        _seed_realistic_mandate(
            session_factory,
            suffix=f"raw-model-reload-{raw_case}",
        )
    )
    calls = _install_solver_double(monkeypatch, weights_bps=FINAL_WEIGHTS)
    generated = _generate(
        session_factory,
        mandate_id,
        advisor_id,
        _preferences(),
    )
    assert len(calls) == 1

    with session_factory() as session:
        _add_invalid_raw_model_row(
            session,
            case=raw_case,
            client_id=client_id,
            mandate_id=mandate_id,
        )
        session.commit()

        allocation = session.query(TargetAllocation).filter(
            TargetAllocation.id == generated["target_allocation"].id
        ).one()
        analytics_calls: list[dict] = []
        monkeypatch.setattr(
            pe,
            "_run_allocation_monte_carlo",
            lambda **kwargs: analytics_calls.append(kwargs) or {
                "goal_summaries": [],
                "current_goal_summaries": [],
            },
        )
        with pytest.raises(ValueError, match=error_pattern):
            _reload_payload(session, allocation)

    assert len(calls) == 1
    assert analytics_calls == []


def test_inactive_raw_position_cashflow_and_goal_are_legitimately_excluded(
    session_factory,
    monkeypatch,
):
    """Canonical inactive rows neither affect inputs nor invalidate reload."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, client_id, mandate_id, _assessment_id, _goal_id = (
        _seed_realistic_mandate(
            session_factory,
            suffix="raw-model-inactive",
        )
    )
    with session_factory() as session:
        inactive_position = _add_raw_position(
            session,
            client_id=client_id,
            is_active=0,
            suffix="inactive",
        )
        inactive_cashflow = _add_raw_cashflow(
            session,
            client_id=client_id,
            is_active=0,
            suffix="inactive",
        )
        inactive_goal = _add_raw_goal(
            session,
            client_id=client_id,
            mandate_id=mandate_id,
            is_active=0,
            suffix="inactive",
        )
        session.commit()

        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        cma = session.query(CapitalMarketAssumption).filter(
            CapitalMarketAssumption.is_current == 1,
            CapitalMarketAssumption.deleted_at.is_(None),
        ).one()
        loaded = pe._load_allocation_inputs(
            session,
            mandate,
            simulation_prefs=_preferences()["simulation"],
            cma=cma,
        )
        assert inactive_position.id not in {
            row.id for row in loaded["all_positions"]
        }
        assert inactive_cashflow.id not in {
            row.id for row in loaded["cashflows"]
        }
        assert inactive_goal.id not in {row.id for row in loaded["goals"]}

    calls = _install_solver_double(monkeypatch, weights_bps=FINAL_WEIGHTS)
    generated = _generate(
        session_factory,
        mandate_id,
        advisor_id,
        _preferences(),
    )
    assert len(calls) == 1

    with session_factory() as session:
        allocation = session.query(TargetAllocation).filter(
            TargetAllocation.id == generated["target_allocation"].id
        ).one()
        payload = _reload_payload(session, allocation)
        assert payload["target_allocation"].id == allocation.id
    assert len(calls) == 1


def _minimal_cma(
    row_id: str,
    *,
    jurisdiction: str,
    tenant_id: str | None,
) -> CapitalMarketAssumption:
    return CapitalMarketAssumption(
        id=row_id,
        assumption_set_name=f"Integrity {row_id}",
        version=1,
        valid_from="2026-01-01",
        is_current=1,
        jurisdiction=jurisdiction,
        tenant_id=tenant_id,
        status="committee_approved",
        created_by="integrity-test",
        created_at=_now(),
        updated_at=_now(),
    )


@pytest.mark.parametrize("duplicate_tier", ["tenant", "global"])
def test_non_ch_duplicate_cma_tier_raises_conflict(
    session_factory,
    duplicate_tier,
):
    """Neither tenant overrides nor firmwide fallbacks may be ambiguous."""
    tenant_id = "tenant-de-integrity"
    duplicate_tenant = tenant_id if duplicate_tier == "tenant" else None
    with session_factory() as session:
        session.add_all(
            [
                _minimal_cma(
                    f"cma-de-{duplicate_tier}-a",
                    jurisdiction="DE",
                    tenant_id=duplicate_tenant,
                ),
                _minimal_cma(
                    f"cma-de-{duplicate_tier}-b",
                    jurisdiction="DE",
                    tenant_id=duplicate_tenant,
                ),
            ]
        )
        if duplicate_tier == "tenant":
            # A valid firmwide fallback must not conceal duplicate overrides.
            session.add(
                _minimal_cma(
                    "cma-de-tenant-valid-global",
                    jurisdiction="DE",
                    tenant_id=None,
                )
            )
        session.commit()

        with pytest.raises(JurisdictionReferenceDataConflictError, match=r"Mehrere aktuelle"):
            resolve_cma_for_jurisdiction(
                session,
                "DE",
                tenant_id=tenant_id,
            )


def test_overlapping_house_matrix_rows_block_before_solver(
    session_factory,
    monkeypatch,
):
    """Ambiguous score bands are reference-data conflicts, not solver input."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _client_id, mandate_id, assessment_id, _goal_id = (
        _seed_realistic_mandate(
            session_factory,
            suffix="overlapping-house-matrix",
        )
    )
    with session_factory() as session:
        assessment = session.query(RiskAssessment).filter(
            RiskAssessment.id == assessment_id
        ).one()
        policy = session.query(OptimizerPolicy).filter(
            OptimizerPolicy.is_current == 1,
        ).one()
        score_bucket = pe._risk_score_bucket(assessment)
        source = session.query(HouseMatrix).filter(
            HouseMatrix.policy_id == policy.id,
            HouseMatrix.is_active == 1,
            HouseMatrix.score_from <= score_bucket,
            HouseMatrix.score_to >= score_bucket,
        ).one()
        values = {
            column.name: getattr(source, column.name)
            for column in HouseMatrix.__table__.columns
        }
        values["id"] = f"overlap-house-{uuid.uuid4()}"
        session.add(HouseMatrix(**values))
        session.commit()

    calls = _install_solver_double(monkeypatch, weights_bps=FINAL_WEIGHTS)
    with session_factory() as session:
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        before = session.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mandate_id
        ).count()
        with pytest.raises(ValueError, match=r"mehrdeutig|ueberlappen"):
            pe.generate_target_allocation(
                session,
                mandate,
                advisor_id,
                preferences=_preferences(),
            )
        after = session.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mandate_id
        ).count()

    assert calls == []
    assert after == before


@pytest.mark.parametrize("integrity_case", ["assessment_mismatch", "blank_cma_anchor"])
def test_modern_context_marker_rejects_missing_or_mismatched_anchors(
    session_factory,
    monkeypatch,
    integrity_case,
):
    """context_artifacts_required=1 makes all typed snapshot anchors mandatory."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    advisor_id, _client_id, mandate_id, _assessment_id, _goal_id = (
        _seed_realistic_mandate(
            session_factory,
            suffix=f"modern-marker-{integrity_case}",
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
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        policy = session.query(OptimizerPolicy).filter(
            OptimizerPolicy.id == allocation.policy_id
        ).one()
        cma = session.query(CapitalMarketAssumption).filter(
            CapitalMarketAssumption.id == allocation.capital_market_assumptions_id
        ).one()
        assessment = session.query(RiskAssessment).filter(
            RiskAssessment.id == allocation.based_on_assessment_id
        ).one()
        assert allocation.context_artifacts_required == 1

        if integrity_case == "assessment_mismatch":
            supplied_assessment = SimpleNamespace(id=f"other-assessment-{uuid.uuid4()}")
            error_pattern = r"Risikoprofil|neu berechnen"
        else:
            allocation.capital_market_assumptions_id = ""
            supplied_assessment = assessment
            error_pattern = r"CMA-Snapshot-Anker|CMA"

        with pytest.raises(ValueError, match=error_pattern):
            pe.build_target_payload_from_allocation(
                session,
                mandate,
                allocation,
                policy,
                cma,
                supplied_assessment,
                preferences=None,
            )
