"""Fail-closed regression gates for allocation reference integrity.

These tests intentionally sit across the service/report/API boundaries.  A
strategy artefact is only reproducible when every downstream object keeps the
exact policy/CMA/allocation anchors that produced it; stale analytics must not
be republished through a PDF fallback; and mandate-scoped planning data must
never be attached to another client.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

import services.portfolio_engine as pe
from models.allocation import (
    CapitalMarketAssumption,
    OptimizerPolicy,
    TargetAllocation,
)
from models.clients import Client
from models.mandates import Mandate
from models.profiling import RiskAssessment
from models.review import Product, RecommendationRun
from models.users import User
from models.wealth import Goal, WealthInflow
from routers.pdf_reports import _build_anlagestrategie_data
from services.pdf import ReportLabRenderer
from services.auth import get_current_user, require_advisor
from test_optimizer_production_contract import (
    _generate,
    _install_solver_double,
    _preferences,
    _seed_realistic_mandate,
    session_factory,  # noqa: F401 - shared isolated-database pytest fixture
)
from test_portfolio_generate_after_saa_recalc import _seed_foundation
from database import get_db
from main import app
from tests.risk_fixture_helpers import noop_lifespan


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _clone_row(source, model, **overrides):
    values = {
        column.name: getattr(source, column.name)
        for column in model.__table__.columns
    }
    values.update(overrides)
    return model(**values)


def _stub_recommendation_tail(monkeypatch) -> None:
    """Keep reference tests focused and deterministic after anchor lookup."""

    def _payload(**kwargs):
        product = (
            kwargs["db"]
            .query(Product)
            .filter(Product.deleted_at.is_(None), Product.is_active == 1)
            .first()
        )
        assert product is not None, "Foundation fixture must expose a product"
        return {
            "sub_allocations": [
                {
                    "asset_class": product.asset_class,
                    "sub_asset_class": product.sub_asset_class,
                    "target_weight_bps": 10_000,
                    "rationale": "reference-integrity test",
                }
            ],
            "advisory_wealth_rappen": 10_000_000,
            "investable_advisory_wealth_rappen": 10_000_000,
            "buckets": [],
            "expected_return_bps": 0,
            "expected_volatility_bps": 0,
        }

    monkeypatch.setattr(pe, "build_target_payload_from_allocation", _payload)
    monkeypatch.setattr(pe, "_product_matches_constraints", lambda *_a, **_kw: True)
    monkeypatch.setattr(pe, "latest_price_snapshot", lambda *_a, **_kw: {})
    monkeypatch.setattr(
        pe,
        "summarize_price_quality",
        lambda *_a, **_kw: {"stale_after_days": 5},
    )
    monkeypatch.setattr(
        pe,
        "build_live_rebalancing_payload",
        lambda **_kw: {"position_drifts": [], "bucket_drifts": []},
    )


@pytest.mark.parametrize("reference_kind", ["missing", "foreign", "deleted"])
def test_explicit_invalid_target_allocation_fails_without_recommendation_run(
    session_factory,
    monkeypatch,
    reference_kind,
):
    """An explicit bad ID must never silently fall back to the current SAA."""
    _stub_recommendation_tail(monkeypatch)

    with session_factory() as session:
        mandate = _seed_foundation(session)
        current = session.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mandate.id,
            TargetAllocation.is_current == 1,
            TargetAllocation.deleted_at.is_(None),
        ).one()
        before = session.query(RecommendationRun).count()

        explicit_id = f"ta-explicit-{reference_kind}-{uuid.uuid4()}"
        if reference_kind == "foreign":
            other_mandate = Mandate(
                id=f"mandate-foreign-{uuid.uuid4()}",
                client_id=mandate.client_id,
                mandate_number=f"M-FOREIGN-{uuid.uuid4().hex[:8]}",
                mandate_type="Anlageberatung",
                opened_at=_now(),
                created_at=_now(),
                updated_at=_now(),
            )
            session.add(other_mandate)
            session.flush()
            session.add(
                _clone_row(
                    current,
                    TargetAllocation,
                    id=explicit_id,
                    mandate_id=other_mandate.id,
                    is_current=0,
                    deleted_at=None,
                )
            )
        elif reference_kind == "deleted":
            session.add(
                _clone_row(
                    current,
                    TargetAllocation,
                    id=explicit_id,
                    is_current=0,
                    deleted_at=_now(),
                )
            )
        session.commit()

        with pytest.raises(ValueError, match=r"target_allocation|Soll-Allokation|Mandat|gel.sch"):
            pe.generate_recommendation_run(
                db=session,
                mandate=mandate,
                user_id="advisor-1",
                preferences=None,
                target_allocation_id=explicit_id,
                run_type="Optimizer",
                depot_bank=None,
            )

        assert session.query(RecommendationRun).count() == before


def test_recommendation_run_uses_exact_allocation_policy_and_cma_anchors(
    session_factory,
    monkeypatch,
):
    """A later runtime-current policy/CMA must not rewrite a historic SAA."""
    _stub_recommendation_tail(monkeypatch)

    with session_factory() as session:
        mandate = _seed_foundation(session)
        allocation = session.query(TargetAllocation).filter(
            TargetAllocation.mandate_id == mandate.id,
            TargetAllocation.is_current == 1,
            TargetAllocation.deleted_at.is_(None),
        ).one()
        allocation_policy = session.query(OptimizerPolicy).filter(
            OptimizerPolicy.id == allocation.policy_id
        ).one()
        allocation_cma = session.query(CapitalMarketAssumption).filter(
            CapitalMarketAssumption.id == allocation.capital_market_assumptions_id
        ).one()

        later_policy = _clone_row(
            allocation_policy,
            OptimizerPolicy,
            id=f"policy-later-{uuid.uuid4()}",
            version=int(allocation_policy.version or 0) + 1,
            is_current=0,
        )
        later_cma = _clone_row(
            allocation_cma,
            CapitalMarketAssumption,
            id=f"cma-later-{uuid.uuid4()}",
            version=int(allocation_cma.version or 0) + 1,
            is_current=0,
        )
        session.add_all([later_policy, later_cma])
        session.commit()

        monkeypatch.setattr(
            pe,
            "ensure_runtime_reference_data",
            lambda *_a, **_kw: (later_policy, later_cma),
        )

        result = pe.generate_recommendation_run(
            db=session,
            mandate=mandate,
            user_id="advisor-1",
            preferences=None,
            target_allocation_id=allocation.id,
            run_type="Optimizer",
            depot_bank=None,
        )

        run = result["run"]
        assert run.target_allocation_id == allocation.id
        assert run.policy_id == allocation.policy_id
        assert run.capital_market_assumptions_id == allocation.capital_market_assumptions_id


@pytest.mark.parametrize("failure_kind", ["input_drift", "missing_snapshot_cma"])
def test_anlagestrategie_data_propagates_v4_integrity_failures(
    session_factory,
    monkeypatch,
    failure_kind,
):
    """The PDF data path must not replace rejected v4 analytics with legacy math."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    monkeypatch.setattr(pe, "_OPTIMIZER_N_PATHS_DEFAULT", 48)
    monkeypatch.setattr(
        pe,
        "_run_allocation_monte_carlo",
        lambda **_kw: {"goal_summaries": [], "current_goal_summaries": []},
    )
    advisor_id, _client_id, mandate_id, _assessment_id, goal_id = (
        _seed_realistic_mandate(
            session_factory,
            suffix=f"pdf-integrity-{failure_kind}",
        )
    )
    _install_solver_double(
        monkeypatch,
        weights_bps={
            "equities": 5000,
            "bonds": 3000,
            "real_estate": 500,
            "alternatives": 1000,
            "liquidity": 500,
        },
    )
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
        if failure_kind == "input_drift":
            goal = session.query(Goal).filter(Goal.id == goal_id).one()
            goal.weight_bps = int(goal.weight_bps or 0) + 1
        else:
            allocation.capital_market_assumptions_id = f"missing-cma-{uuid.uuid4()}"
        session.commit()
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()

        with pytest.raises(ValueError, match=r"veraltet|neu berechnen|Kapitalmarkt|CMA|referenz"):
            _build_anlagestrategie_data(mandate, session)


def test_anlagestrategie_uses_exact_assessment_anchor_for_all_risk_fields(
    session_factory,
    monkeypatch,
):
    """A second current RA must never create a hybrid strategy document."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    monkeypatch.setattr(pe, "_OPTIMIZER_N_PATHS_DEFAULT", 48)
    monkeypatch.setattr(
        pe,
        "_run_allocation_monte_carlo",
        lambda **_kw: {"goal_summaries": [], "current_goal_summaries": []},
    )
    advisor_id, _client_id, mandate_id, assessment_id, _goal_id = (
        _seed_realistic_mandate(
            session_factory,
            suffix="pdf-exact-assessment-anchor",
        )
    )
    with session_factory() as session:
        anchored = session.query(RiskAssessment).filter(
            RiskAssessment.id == assessment_id
        ).one()
        anchored.knowledge_services_json = '{"Anlageberatung":{"known":true}}'
        anchored.knowledge_instruments_json = '{"Anlagefonds":{"known":true}}'
        session.commit()

    _install_solver_double(
        monkeypatch,
        weights_bps={
            "equities": 5000,
            "bonds": 3000,
            "real_estate": 500,
            "alternatives": 1000,
            "liquidity": 500,
        },
    )
    generated = _generate(
        session_factory,
        mandate_id,
        advisor_id,
        _preferences(),
    )

    with session_factory() as session:
        # Modern databases reject a second current RA at the partial unique
        # index.  Remove that index only in this isolated fixture to retain a
        # defense-in-depth regression for damaged/pre-migration databases: the
        # PDF must still source every field from the allocation's exact anchor.
        session.execute(text("DROP INDEX ux_risk_one_current"))
        allocation = session.query(TargetAllocation).filter(
            TargetAllocation.id == generated["target_allocation"].id
        ).one()
        anchored = session.query(RiskAssessment).filter(
            RiskAssessment.id == allocation.based_on_assessment_id
        ).one()
        duplicate = _clone_row(
            anchored,
            RiskAssessment,
            id=f"ra-duplicate-current-{uuid.uuid4()}",
            version=int(anchored.version or 0) + 1,
            supersedes_id=anchored.id,
            is_current=1,
            final_score_x10=20,
            final_profile="Kapitalschutz",
            investment_horizon_years=3,
            investment_horizon_label="Bis 3 Jahre",
            is_overridden=1,
            override_score_x10=15,
            override_profile="Duplicate Current Profile",
            override_reason="Must never enter anchored PDF",
            override_client_confirmed=1,
            override_warning_delivered=1,
            knowledge_services_json='{"Anlageberatung":{"known":false}}',
            knowledge_instruments_json='{"Anlagefonds":{"known":false}}',
            assessed_at="9999-12-31T23:59:59Z",
            created_at="9999-12-31T23:59:59Z",
            updated_at="9999-12-31T23:59:59Z",
        )
        session.add(duplicate)
        session.commit()
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()

        data = _build_anlagestrategie_data(mandate, session)

        assert data.risk_score_x10 == int(anchored.final_score_x10)
        assert data.risk_profile_label == anchored.final_profile
        assert data.risk_is_overridden is False
        assert data.risk_override_reason is None
        assert data.investment_horizon_years == int(
            anchored.investment_horizon_years
        )
        assert data.knowledge_services == {"Anlageberatung": True}
        assert data.knowledge_instruments == {"Anlagefonds": True}
        assert len(data.risk_answers) == 11


@pytest.mark.parametrize(
    "failure_kind",
    [
        "historical_allocation_only",
        "missing_policy",
        "noncurrent_policy",
        "missing_assessment",
        "noncurrent_assessment",
        "missing_snapshot_cma",
    ],
)
def test_anlagestrategie_requires_complete_current_decision_anchors(
    session_factory,
    monkeypatch,
    failure_kind,
):
    """A strategy PDF must never assemble a hybrid from replacement inputs."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    monkeypatch.setattr(pe, "_OPTIMIZER_N_PATHS_DEFAULT", 48)
    monkeypatch.setattr(
        pe,
        "_run_allocation_monte_carlo",
        lambda **_kw: {"goal_summaries": [], "current_goal_summaries": []},
    )
    advisor_id, _client_id, mandate_id, assessment_id, _goal_id = (
        _seed_realistic_mandate(
            session_factory,
            suffix=f"pdf-anchor-{failure_kind}",
        )
    )
    _install_solver_double(
        monkeypatch,
        weights_bps={
            "equities": 5000,
            "bonds": 3000,
            "real_estate": 500,
            "alternatives": 1000,
            "liquidity": 500,
        },
    )
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
        policy = session.query(OptimizerPolicy).filter(
            OptimizerPolicy.id == allocation.policy_id
        ).one()
        assessment = session.query(RiskAssessment).filter(
            RiskAssessment.id == assessment_id
        ).one()

        if failure_kind == "historical_allocation_only":
            allocation.is_current = 0
        elif failure_kind == "missing_policy":
            allocation.policy_id = f"missing-policy-{uuid.uuid4()}"
        elif failure_kind == "noncurrent_policy":
            policy.is_current = 0
        elif failure_kind == "missing_assessment":
            allocation.based_on_assessment_id = f"missing-assessment-{uuid.uuid4()}"
        elif failure_kind == "noncurrent_assessment":
            assessment.is_current = 0
        elif failure_kind == "missing_snapshot_cma":
            allocation.capital_market_assumptions_id = f"missing-cma-{uuid.uuid4()}"
        session.commit()
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()

        with pytest.raises(
            ValueError,
            match=r"Soll-Allokation|Policy|Risikoprofil|Assessment|CMA|Kapitalmarkt|neu berechnen|aktuell",
        ):
            _build_anlagestrategie_data(mandate, session)


@pytest.mark.parametrize(
    ("report_path", "renderer_method"),
    [
        ("anlagestrategie.pdf", "render_anlagestrategie"),
        ("assetallocation.pdf", "render_asset_allocation"),
        ("contract-signoff.pdf", "render_contract_signoff"),
        ("depotcheck.pdf", "render_depotcheck"),
    ],
)
def test_strategy_pdf_endpoints_reject_missing_current_allocation_before_render(
    session_factory,
    monkeypatch,
    report_path,
    renderer_method,
):
    """All strategy consumers expose the same 409 gate and skip rendering."""
    advisor_id, _client_id, mandate_id, _assessment_id, _goal_id = (
        _seed_realistic_mandate(
            session_factory,
            suffix=f"pdf-no-current-{report_path.split('.')[0]}",
        )
    )
    with session_factory() as session:
        advisor = session.query(User).filter(User.id == advisor_id).one()

    renderer_called = False

    def _unexpected_render(*_args, **_kwargs):
        nonlocal renderer_called
        renderer_called = True
        raise AssertionError("renderer must not run without a current strategy")

    monkeypatch.setattr(ReportLabRenderer, renderer_method, _unexpected_render)

    def _override_db():
        with session_factory() as session:
            yield session

    monkeypatch.setattr(app.router, "lifespan_context", noop_lifespan)
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = lambda: advisor
    app.dependency_overrides[require_advisor] = lambda: advisor
    try:
        from fastapi.testclient import TestClient

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(
                f"/mandates/{mandate_id}/reports/{report_path}"
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409, response.text
    assert renderer_called is False


@pytest.mark.parametrize(
    "report_path",
    [
        "anlagestrategie.pdf",
        "assetallocation.pdf",
        "contract-signoff.pdf",
        "depotcheck.pdf",
    ],
)
def test_strategy_consuming_pdf_endpoints_map_input_drift_to_409(
    session_factory,
    monkeypatch,
    report_path,
):
    """Every customer-document endpoint sharing strategy data maps drift to 409."""
    monkeypatch.setattr(pe.settings, "optimizer_mode", "stochastic")
    monkeypatch.setattr(pe, "_OPTIMIZER_N_PATHS_DEFAULT", 48)
    monkeypatch.setattr(
        pe,
        "_run_allocation_monte_carlo",
        lambda **_kw: {"goal_summaries": [], "current_goal_summaries": []},
    )
    advisor_id, _client_id, mandate_id, _assessment_id, goal_id = (
        _seed_realistic_mandate(
            session_factory,
            suffix=f"pdf-route-drift-{report_path.split('.')[0]}",
        )
    )
    _install_solver_double(
        monkeypatch,
        weights_bps={
            "equities": 5000,
            "bonds": 3000,
            "real_estate": 500,
            "alternatives": 1000,
            "liquidity": 500,
        },
    )
    _generate(session_factory, mandate_id, advisor_id, _preferences())

    with session_factory() as session:
        goal = session.query(Goal).filter(Goal.id == goal_id).one()
        goal.weight_bps = int(goal.weight_bps or 0) + 1
        advisor = session.query(User).filter(User.id == advisor_id).one()
        session.commit()

    def _override_db():
        with session_factory() as session:
            yield session

    monkeypatch.setattr(app.router, "lifespan_context", noop_lifespan)
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = lambda: advisor
    app.dependency_overrides[require_advisor] = lambda: advisor
    try:
        from fastapi.testclient import TestClient

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(
                f"/mandates/{mandate_id}/reports/{report_path}"
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409, response.text
    assert "veraltet" in response.text or "neu berechnen" in response.text


def test_create_wealth_inflow_rejects_mandate_of_another_client(
    session_factory,
    monkeypatch,
):
    """Ownership alone is insufficient: mandate.client_id must equal path client."""
    advisor_id, client_a_id, _mandate_a_id, _assessment_id, _goal_id = (
        _seed_realistic_mandate(session_factory, suffix="inflow-cross-client")
    )
    with session_factory() as session:
        advisor = session.query(User).filter(User.id == advisor_id).one()
        client_b = Client(
            id=f"client-b-{uuid.uuid4()}",
            client_number=f"C-B-{uuid.uuid4().hex[:8]}",
            first_name="Client",
            last_name="B",
            advisor_id=advisor_id,
            created_at=_now(),
            updated_at=_now(),
        )
        mandate_b = Mandate(
            id=f"mandate-b-{uuid.uuid4()}",
            client_id=client_b.id,
            mandate_number=f"M-B-{uuid.uuid4().hex[:8]}",
            mandate_type="Anlageberatung",
            opened_at=_now(),
            created_at=_now(),
            updated_at=_now(),
        )
        session.add_all([client_b, mandate_b])
        session.commit()
        mandate_b_id = mandate_b.id

    def _override_db():
        with session_factory() as session:
            yield session

    monkeypatch.setattr(app.router, "lifespan_context", noop_lifespan)
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = lambda: advisor
    app.dependency_overrides[require_advisor] = lambda: advisor
    try:
        from fastapi.testclient import TestClient

        with TestClient(app) as client:
            response = client.post(
                f"/clients/{client_a_id}/wealth-inflows",
                json={
                    "label": "Cross-client inheritance",
                    "source_type": "Erbschaft",
                    "amount_rappen": 10_000_000,
                    "expected_year": 2030,
                    "value_mode": "nominal",
                    "mandate_id": mandate_b_id,
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code in {404, 409, 422}, response.text
    with session_factory() as session:
        assert session.query(WealthInflow).filter(
            WealthInflow.client_id == client_a_id,
            WealthInflow.mandate_id == mandate_b_id,
        ).count() == 0
