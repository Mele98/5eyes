from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base
from main import app
from models.allocation import BuildingBlock, HouseMatrix, TargetAllocation
from models.clients import Client
from models.mandates import Mandate
from models.profiling import RiskAssessment
from models.review import PriceHistory, Product, RecommendationHolding, RecommendationRun, ReviewTrigger
from models.users import AdviserRegistration, User
from models.wealth import Cashflow, Goal, WealthPosition
from price_updater import fetch_latest_price, refresh_all_prices, summarize_price_quality
from routers.auth import get_adviser_registration
from routers.clients import cashflow_summary
from routers.profiling import create_risk_assessment
from routers.review import active_triggers, create_advisory_log_entry, create_trigger, dashboard_summary
from routers.review import auto_apply_product_id_mappings, auto_apply_product_reference_data
from routers.wealth import create_cashflow, create_goal, create_wealth_position, delete_cashflow
from services.auth import get_client_for_user_or_404, get_mandate_for_user_or_404
from services.eodhd_client import preview_eodhd_reference
from services.foundation_example import FOUNDATION_CLIENT_NUMBER, FOUNDATION_MANDATE_NUMBER, upsert_foundation_example_case
from services.openfigi_client import preview_openfigi_mapping
from services.portfolio_engine import (
    _aligned_reference_price,
    ALLOWED_HOUSE_MATRIX_PROFILES,
    ALLOWED_PRODUCT_ASSET_CLASSES,
    ALLOWED_PRODUCT_TYPES,
    build_recommendation_payload_from_run,
    build_target_payload_from_allocation,
    ensure_default_products,
    ensure_runtime_reference_data,
    generate_recommendation_run,
    generate_target_allocation,
)
from services.review_engine import (
    SYSTEM_TRIGGER_DRIFT,
    SYSTEM_TRIGGER_GOALS,
    SYSTEM_TRIGGER_MARKET_DATA,
    SYSTEM_TRIGGER_REVIEW,
    refresh_system_review_triggers,
)
from schemas.profiling import RiskAssessmentCreate
from schemas.allocation import TargetAllocationGenerateResponse
from schemas.review import AdvisoryLogCreate, ReviewTriggerCreate
from schemas.review import ProductIdMappingBatchApplyRequest, ProductReferenceBatchApplyRequest
from schemas.wealth import CashflowCreate, GoalCreate, WealthPositionCreate


@pytest.fixture()
def session_factory(tmp_path):
    db_path = tmp_path / "test_runtime_contracts.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    testing_session_local = sessionmaker(
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
        bind=engine,
    )
    Base.metadata.create_all(bind=engine)
    try:
        yield testing_session_local
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def advisor_user():
    return User(
        id="advisor-1",
        username="advisor",
        password_hash="hash",
        full_name="Advisor User",
        role="advisor",
        is_active=1,
        created_at="2026-03-27T00:00:00.000Z",
        updated_at="2026-03-27T00:00:00.000Z",
    )


@pytest.fixture()
def other_advisor_user():
    return User(
        id="advisor-2",
        username="advisor2",
        password_hash="hash",
        full_name="Advisor Two",
        role="advisor",
        is_active=1,
        created_at="2026-03-27T00:00:00.000Z",
        updated_at="2026-03-27T00:00:00.000Z",
    )


def seed_client_and_mandate(session_factory, advisor_user) -> tuple[str, str]:
    with session_factory() as session:
        session.add(
            User(
                id=advisor_user.id,
                username=advisor_user.username,
                password_hash=advisor_user.password_hash,
                full_name=advisor_user.full_name,
                role=advisor_user.role,
                is_active=advisor_user.is_active,
                created_at=advisor_user.created_at,
                updated_at=advisor_user.updated_at,
            )
        )
        session.add(
            Client(
                id="client-1",
                client_number="C-100001",
                first_name="Max",
                last_name="Muster",
                country_of_residence="CH",
                language="DE",
                household_type="Einzelperson",
                client_classification="Privatkunde",
                is_professional_opt_out=0,
                is_qualified_investor=0,
                advisor_id=advisor_user.id,
                created_at="2026-03-27T00:00:00.000Z",
                updated_at="2026-03-27T00:00:00.000Z",
            )
        )
        session.add(
            Mandate(
                id="mandate-1",
                client_id="client-1",
                mandate_number="M-100001",
                mandate_type="Anlageberatung",
                status="Aktiv",
                base_currency="CHF",
                advisory_language="DE",
                opened_at="2026-03-27",
                created_at="2026-03-27T00:00:00.000Z",
                updated_at="2026-03-27T00:00:00.000Z",
            )
        )
        session.commit()
    return "client-1", "mandate-1"


def seed_foreign_client_and_mandate(session_factory, other_advisor_user) -> tuple[str, str]:
    with session_factory() as session:
        session.add(
            User(
                id=other_advisor_user.id,
                username=other_advisor_user.username,
                password_hash=other_advisor_user.password_hash,
                full_name=other_advisor_user.full_name,
                role=other_advisor_user.role,
                is_active=other_advisor_user.is_active,
                created_at=other_advisor_user.created_at,
                updated_at=other_advisor_user.updated_at,
            )
        )
        session.add(
            Client(
                id="client-foreign-1",
                client_number="C-200001",
                first_name="Fremd",
                last_name="Kunde",
                country_of_residence="CH",
                language="DE",
                household_type="Einzelperson",
                client_classification="Privatkunde",
                is_professional_opt_out=0,
                is_qualified_investor=0,
                advisor_id=other_advisor_user.id,
                created_at="2026-03-27T00:00:00.000Z",
                updated_at="2026-03-27T00:00:00.000Z",
            )
        )
        session.add(
            Mandate(
                id="mandate-foreign-1",
                client_id="client-foreign-1",
                mandate_number="M-200001",
                mandate_type="Anlageberatung",
                status="Aktiv",
                base_currency="CHF",
                advisory_language="DE",
                opened_at="2026-03-27",
                created_at="2026-03-27T00:00:00.000Z",
                updated_at="2026-03-27T00:00:00.000Z",
            )
        )
        session.commit()
    return "client-foreign-1", "mandate-foreign-1"


def test_runtime_routes_expose_frontend_contracts():
    route_map = {(route.path, tuple(sorted(route.methods or []))) for route in app.routes}

    assert ("/mandates/{mandate_id}/risk-assessments", ("POST",)) in route_map
    assert ("/clients/{client_id}/cashflows/{cf_id}", ("DELETE",)) in route_map
    assert ("/mandates/{mandate_id}/triggers/system-refresh", ("POST",)) in route_map
    assert ("/building-blocks/current", ("GET",)) in route_map
    assert ("/admin/system/foundation-example", ("POST",)) in route_map
    assert ("/mandates/{mandate_id}/target-allocation/current/payload", ("GET",)) in route_map
    assert ("/mandates/{mandate_id}/recommendations/current/payload", ("GET",)) in route_map
    assert ("/mandates/{mandate_id}/recommendations/{run_id}/holdings", ("GET",)) in route_map
    assert ("/mandates/{mandate_id}/recommendations/{run_id}/positions/{position_id}/holding", ("PUT",)) in route_map
    assert ("/mandates/{mandate_id}/recommendations/{run_id}/positions/{position_id}/holding", ("DELETE",)) in route_map
    assert ("/products/openfigi/resolve", ("POST",)) in route_map
    assert ("/products/openfigi/apply", ("POST",)) in route_map
    assert ("/products/openfigi/auto-apply", ("POST",)) in route_map
    assert ("/products/{product_id}/market-override", ("PUT",)) in route_map
    assert ("/products/market-data/status", ("GET",)) in route_map
    assert ("/products/eodhd/resolve", ("POST",)) in route_map
    assert ("/products/eodhd/apply", ("POST",)) in route_map
    assert ("/products/eodhd/auto-apply", ("POST",)) in route_map
    assert ("/admin/system/compliance", ("GET",)) in route_map


def test_openfigi_mapping_preview_normalizes_isin_candidates(monkeypatch):
    import services.openfigi_client as openfigi_client

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                [
                    {
                        "data": [
                            {
                                "figi": "BBG000BLNNH6",
                                "ticker": "IBM",
                                "name": "INTL BUSINESS MACHINES CORP",
                                "exchCode": "US",
                                "compositeFIGI": "BBG000BLNNH6",
                                "shareClassFIGI": "BBG001S5S399",
                                "securityType": "Common Stock",
                                "securityType2": "Common Stock",
                                "marketSector": "Equity",
                                "securityDescription": "IBM",
                            }
                        ]
                    }
                ]
            ).encode("utf-8")

    def fake_urlopen(request, timeout=15):
        assert request.full_url == openfigi_client.OPENFIGI_MAPPING_URL
        payload = json.loads(request.data.decode("utf-8"))
        assert payload[0]["idType"] == "ID_ISIN"
        assert payload[0]["idValue"] == "CH0001341608"
        return FakeResponse()

    monkeypatch.setattr(openfigi_client, "urlopen", fake_urlopen)

    result = preview_openfigi_mapping(
        isin="CH0001341608",
        currency="CHF",
        context={"product_name": "UBS ETF Example"},
    )

    assert result["source"] == "openfigi"
    assert result["resolved_from"]["product_name"] == "UBS ETF Example"
    assert result["request_job"]["currency"] == "CHF"
    assert result["candidates"][0]["figi"] == "BBG000BLNNH6"
    assert result["candidates"][0]["ticker"] == "IBM"


def test_openfigi_mapping_preview_requires_basis():
    with pytest.raises(ValueError):
        preview_openfigi_mapping()


def test_product_model_supports_mapping_fields(session_factory):
    with session_factory() as session:
        product = Product(
            id="prod-map-1",
            isin="CH0001341608",
            symbol=None,
            figi="BBG000BLNNH6",
            composite_figi="BBG000BLNNH6",
            share_class_figi="BBG001S5S399",
            exchange_code="SW",
            market_sector="Equity",
            security_type="Common Stock",
            security_type2="Common Stock",
            mapping_provider="openfigi",
            mapping_resolved_at="2026-03-28T10:00:00.000Z",
            reference_data_provider="eodhd",
            reference_data_refreshed_at="2026-03-28T10:05:00.000Z",
            product_name="Mapped Product",
            provider="Test Provider",
            product_type="ETF",
            asset_class="Aktien",
            currency="CHF",
            is_active=1,
            created_at="2026-03-28T00:00:00.000Z",
            updated_at="2026-03-28T00:00:00.000Z",
        )
        session.add(product)
        session.commit()
        stored = session.query(Product).filter(Product.id == "prod-map-1").one()

    assert stored.figi == "BBG000BLNNH6"
    assert stored.exchange_code == "SW"
    assert stored.mapping_provider == "openfigi"
    assert stored.reference_data_provider == "eodhd"


def test_eodhd_reference_preview_scores_exact_isin_and_currency_matches(monkeypatch):
    import services.eodhd_client as eodhd_client

    monkeypatch.setattr(
        eodhd_client,
        "_search_eodhd",
        lambda query, limit=10: [
            {
                "Code": "UBSG",
                "Exchange": "SW",
                "Name": "Auto Map Product",
                "Type": "ETF",
                "Currency": "CHF",
                "ISIN": "CH0001341608",
            },
            {
                "Code": "UBSG",
                "Exchange": "US",
                "Name": "Auto Map Product ADR",
                "Type": "ADR",
                "Currency": "USD",
                "ISIN": "US0001341608",
            },
        ],
    )

    result = preview_eodhd_reference(
        isin="CH0001341608",
        symbol="UBSG",
        product_name="Auto Map Product",
        exchange_code="SW",
        currency="CHF",
        context={"product_name": "Auto Map Product"},
    )

    assert result["source"] == "eodhd"
    assert result["query_used"]["type"] == "isin"
    assert result["candidates"][0]["exchange_code"] == "SW"
    assert result["candidates"][0]["currency"] == "CHF"
    assert result["candidates"][0]["match_score"] > result["candidates"][1]["match_score"]


def test_price_quality_exposes_isin_only_direct_lookup(session_factory):
    with session_factory() as session:
        session.add(
            Product(
                id="prod-isin-only",
                isin="CH0001341608",
                symbol=None,
                product_name="ISIN Only Product",
                provider="Test Provider",
                product_type="ETF",
                asset_class="Aktien",
                currency="CHF",
                is_active=1,
                created_at="2026-03-28T00:00:00.000Z",
                updated_at="2026-03-28T00:00:00.000Z",
            )
        )
        session.commit()
        quality = summarize_price_quality(session)

    assert quality["direct_lookup_products_count"] == 1
    assert quality["direct_isin_lookup_products_count"] == 1
    assert quality["direct_symbol_lookup_products_count"] == 0


def test_fetch_latest_prices_batch_flags_isin_only_products(session_factory):
    with session_factory() as session:
        product = Product(
            id="prod-isin-batch",
            isin="CH0001341608",
            symbol=None,
            product_name="ISIN Batch Product",
            provider="Test Provider",
            product_type="ETF",
            asset_class="Aktien",
            currency="CHF",
            is_active=1,
            created_at="2026-03-28T00:00:00.000Z",
            updated_at="2026-03-28T00:00:00.000Z",
        )
        points, failures = refresh_all_prices.__globals__["fetch_latest_prices_batch"]([product])

    assert not points
    assert failures[product.id]["lookup_mode"] == "direct_isin"
    assert "nur ISIN" in failures[product.id]["error"]


def test_auto_apply_openfigi_mapping_enriches_isin_only_products(session_factory, advisor_user, monkeypatch):
    import routers.review as review_router_module

    with session_factory() as session:
        session.add(
            Product(
                id="prod-auto-map",
                isin="CH0001341608",
                symbol=None,
                product_name="Auto Map Product",
                provider="Test Provider",
                product_type="ETF",
                asset_class="Aktien",
                currency="CHF",
                is_active=1,
                created_at="2026-03-28T00:00:00.000Z",
                updated_at="2026-03-28T00:00:00.000Z",
            )
        )
        session.commit()

        monkeypatch.setattr(
            review_router_module,
            "preview_openfigi_mapping",
            lambda **kwargs: {
                "source": "openfigi",
                "api_key_used": False,
                "request_job": {"idType": "ID_ISIN", "idValue": kwargs.get("isin")},
                "resolved_from": kwargs.get("context") or {},
                "warning": None,
                "error": None,
                "candidates": [
                    {
                        "figi": "BBG000BLNNH6",
                        "ticker": "UBSG",
                        "name": "Auto Map Product",
                        "exch_code": "SW",
                        "composite_figi": "BBG000BLNNH6",
                        "share_class_figi": "BBG001S5S399",
                        "security_type": "Common Stock",
                        "security_type2": "Common Stock",
                        "market_sector": "Equity",
                        "security_description": "UBSG",
                    }
                ],
            },
        )

        result = auto_apply_product_id_mappings(
            body=ProductIdMappingBatchApplyRequest(limit=10, dry_run=False),
            db=session,
            current_user=advisor_user,
        )
        stored = session.query(Product).filter(Product.id == "prod-auto-map").one()

    assert result["processed"] == 1
    assert result["applied"] == 1
    assert stored.symbol == "UBSG"
    assert stored.figi == "BBG000BLNNH6"
    assert stored.mapping_provider == "openfigi"


def test_auto_apply_eodhd_reference_enriches_products(session_factory, advisor_user, monkeypatch):
    import routers.review as review_router_module

    with session_factory() as session:
        session.add(
            Product(
                id="prod-auto-ref",
                isin="CH0001341608",
                symbol="UBSG",
                product_name="Auto Ref Product",
                provider="Test Provider",
                product_type="ETF",
                asset_class="Aktien",
                currency="CHF",
                is_active=1,
                created_at="2026-03-28T00:00:00.000Z",
                updated_at="2026-03-28T00:00:00.000Z",
            )
        )
        session.commit()

        monkeypatch.setattr(
            review_router_module,
            "preview_eodhd_reference",
            lambda **kwargs: {
                "source": "eodhd",
                "api_key_used": True,
                "query_used": {"type": "symbol", "value": kwargs.get("symbol")},
                "resolved_from": kwargs.get("context") or {},
                "warning": None,
                "candidates": [
                    {
                        "symbol": "UBSG",
                        "exchange_code": "SW",
                        "name": "UBS ETF Product",
                        "instrument_type": "ETF",
                        "country": "CH",
                        "currency": "CHF",
                        "isin": "CH0001341608",
                        "match_score": 90,
                    }
                ],
            },
        )

        result = auto_apply_product_reference_data(
            body=ProductReferenceBatchApplyRequest(limit=10, dry_run=False, overwrite_name=True),
            db=session,
            current_user=advisor_user,
        )
        stored = session.query(Product).filter(Product.id == "prod-auto-ref").one()

    assert result["processed"] == 1
    assert result["applied"] == 1
    assert stored.reference_data_provider == "eodhd"
    assert stored.reference_data_refreshed_at is not None
    assert stored.exchange_code == "SW"
    assert stored.product_name == "UBS ETF Product"


def test_runtime_reference_data_house_matrix_rows_are_self_consistent(session_factory, advisor_user):
    seed_client_and_mandate(session_factory, advisor_user)

    with session_factory() as session:
        ensure_runtime_reference_data(session, advisor_user.id)
        entries = session.query(HouseMatrix).order_by(HouseMatrix.score_from.asc()).all()

    assert len(entries) == 6
    covered_scores = []
    for entry in entries:
        target_total = (
            int(entry.liq_target_bps or 0)
            + int(entry.bonds_target_bps or 0)
            + int(entry.equity_target_bps or 0)
            + int(entry.real_estate_target_bps or 0)
            + int(entry.alt_target_bps or 0)
        )
        assert target_total == 10000
        assert 0 <= int(entry.max_risky_fraction_bps or 0) <= 10000
        assert int(entry.equity_minimum_bps or 0) <= int(entry.equity_max_bps or 0)
        assert entry.profile_name in ALLOWED_HOUSE_MATRIX_PROFILES
        covered_scores.extend(range(int(entry.score_from), int(entry.score_to) + 1))
    assert sorted(covered_scores) == list(range(1, 11))


def test_runtime_reference_data_matches_fachlogik_tables(session_factory, advisor_user):
    seed_client_and_mandate(session_factory, advisor_user)

    with session_factory() as session:
        _, cma = ensure_runtime_reference_data(session, advisor_user.id)
        growth = session.query(HouseMatrix).filter(HouseMatrix.score_from == 7, HouseMatrix.score_to == 8).one()
        equities = session.query(HouseMatrix).filter(HouseMatrix.score_from == 10, HouseMatrix.score_to == 10).one()
        blocks = {
            (row.asset_class, row.sub_asset_class): row
            for row in session.query(BuildingBlock).all()
        }
        inflation_path = json.loads(cma.inflation_path_json or "{}")

    assert growth.profile_name == "Wachstum"
    assert int(growth.equity_target_bps) == 6800
    assert int(growth.equity_minimum_bps) == 6000
    assert int(growth.max_risky_fraction_bps) == 8000
    assert int(equities.equity_target_bps) == 9000
    assert int(equities.equity_max_bps) == 9500
    assert int(equities.max_risky_fraction_bps) == 10000
    assert int(blocks[("Aktien", "Aktien Schweiz")].risky_fraction_bps) == 7000
    assert int(blocks[("Immobilien", "Immobilien Schweiz")].risky_fraction_bps) == 5000
    assert int(blocks[("Alternative", "Gold / Rohstoffe")].risky_fraction_bps) == 8000
    assert int(blocks[("Obligationen", "Obligationen High Yield")].risky_fraction_bps) == 5000
    assert inflation_path["2026"] == 50
    assert inflation_path["2035"] == 70
    assert inflation_path["2040"] == 110


def test_risk_assessment_runtime_endpoint_logic_returns_scored_payload(session_factory, advisor_user):
    _, mandate_id = seed_client_and_mandate(session_factory, advisor_user)

    payload = RiskAssessmentCreate(
        q_income_points=4,
        q_obligations_points=4,
        q_savings_points=12,
        q_wealth_points=12,
        investment_horizon_label="Mehr als 12 Jahre",
        investment_horizon_years=15,
        q_investment_goal_points=4,
        q_risk_preference_points=4,
        q_risk_behavior_points=4,
        answers=[],
    )

    with session_factory() as session:
        result = create_risk_assessment(
            mandate_id=mandate_id,
            body=payload,
            db=session,
            current_user=advisor_user,
        )

    assert result.mandate_id == mandate_id
    assert result.risk_willingness_score_x10 == 100
    assert result.final_score_x10 == 100
    assert result.final_profile == "Aktien"


def test_foundation_example_case_is_generation_ready_and_idempotent(session_factory, advisor_user):
    with session_factory() as session:
        session.add(
            User(
                id=advisor_user.id,
                username=advisor_user.username,
                password_hash=advisor_user.password_hash,
                full_name=advisor_user.full_name,
                role=advisor_user.role,
                is_active=advisor_user.is_active,
                created_at=advisor_user.created_at,
                updated_at=advisor_user.updated_at,
            )
        )
        session.commit()

        first = upsert_foundation_example_case(session, advisor_user)
        session.commit()
        second = upsert_foundation_example_case(session, advisor_user)
        session.commit()

        example_client = session.query(Client).filter(Client.client_number == FOUNDATION_CLIENT_NUMBER).one()
        example_mandate = session.query(Mandate).filter(Mandate.mandate_number == FOUNDATION_MANDATE_NUMBER).one()
        positions = session.query(WealthPosition).filter(WealthPosition.client_id == example_client.id).all()
        cashflows = session.query(Cashflow).filter(Cashflow.client_id == example_client.id).all()
        goals = session.query(Goal).filter(Goal.mandate_id == example_mandate.id).all()
        assessment = session.query(RiskAssessment).filter(RiskAssessment.mandate_id == example_mandate.id).one()
        allocations = session.query(TargetAllocation).filter(TargetAllocation.mandate_id == example_mandate.id).all()
        recommendation_runs = session.query(RecommendationRun).filter(RecommendationRun.mandate_id == example_mandate.id).all()
        system_triggers = session.query(ReviewTrigger).filter(
            ReviewTrigger.mandate_id == example_mandate.id,
            ReviewTrigger.is_system == 1,
        ).all()

    assert first["positions_count"] == 6
    assert first["cashflows_count"] == 7
    assert first["goals_count"] == 4
    assert first["risk_profile"] == "Wachstumsorientiert"
    assert first["advisory_wealth_rappen"] < first["total_wealth_rappen"]
    assert first["annual_net_cashflow_rappen"] > 0
    assert first["house_matrix_profile"] == "Wachstum"
    assert first["monte_carlo_simulations"] >= 250
    assert 0 <= first["target_downside_probability_pct"] <= 100
    assert first["target_terminal_p50_rappen"] > 0
    assert first["goal_score_weighted_pct"] > 0
    assert first["projection_end_year"] >= date.today().year
    assert 0 <= first["market_data_fresh_coverage_pct"] <= 100
    assert first["market_data_missing_price_count"] >= 0
    assert second["client_id"] == example_client.id
    assert second["mandate_id"] == example_mandate.id
    assert len(positions) == 6
    assert len(cashflows) == 7
    assert len(goals) == 4
    assert assessment.final_profile == "Wachstumsorientiert"
    assert any((cf.label or "") == "3a Kapitalbezug" and str(cf.frequency) == "einmalig" for cf in cashflows)
    assert len(allocations) == 1
    assert len(recommendation_runs) == 1
    assert len(system_triggers) >= 2


def test_default_products_match_live_schema_constraints(session_factory, advisor_user):
    seed_client_and_mandate(session_factory, advisor_user)

    with session_factory() as session:
        ensure_default_products(session)
        products = session.query(Product).all()

    assert products
    for product in products:
        assert product.product_type in ALLOWED_PRODUCT_TYPES
        assert product.asset_class in ALLOWED_PRODUCT_ASSET_CLASSES


def test_aligned_reference_price_recalibrates_proxy_regime_switch():
    reference = PriceHistory(
        id="ref-old",
        product_id="prod-1",
        price_date="2026-03-27",
        price_rappen=100000,
        currency="CHF",
        source="yfinance",
        fetched_at="2026-03-27T18:00:00.000Z",
    )
    latest = PriceHistory(
        id="ref-new",
        product_id="prod-1",
        price_date="2026-03-28",
        price_rappen=15288,
        currency="CHF",
        source="stooq",
        fetched_at="2026-03-28T18:00:00.000Z",
    )

    aligned, recalibrated = _aligned_reference_price(reference, latest, "proxy")

    assert recalibrated is True
    assert aligned is latest


def test_default_products_have_runtime_market_profiles(session_factory, advisor_user):
    seed_client_and_mandate(session_factory, advisor_user)

    with session_factory() as session:
        ensure_default_products(session)
        products = {product.product_name: product for product in session.query(Product).all()}
        quality = summarize_price_quality(session)
        cash_price = fetch_latest_price(products["Kontoguthaben CHF"])

    assert quality["mapping_gap_count"] == 0
    assert quality["direct_lookup_products_count"] >= 2
    assert quality["proxy_lookup_products_count"] >= 1
    assert quality["synthetic_lookup_products_count"] >= 3
    assert cash_price.source == "synthetic_par"
    assert cash_price.price_rappen == 100
    assert cash_price.currency == "CHF"


def test_refresh_all_prices_batches_external_and_synthetic_profiles(session_factory, monkeypatch):
    import pandas as pd
    import price_updater as price_updater_module

    with session_factory() as session:
        session.add_all(
            [
                Product(
                    id="prod-energy",
                    product_name="Energy Select Sector ETF",
                    provider="State Street",
                    product_type="ETF",
                    asset_class="Aktien",
                    sub_asset_class="Thema Fossile Energie",
                    currency="USD",
                    is_active=1,
                    created_at="2026-03-28T00:00:00.000Z",
                    updated_at="2026-03-28T00:00:00.000Z",
                ),
                Product(
                    id="prod-cash",
                    product_name="Kontoguthaben CHF",
                    provider="Hausbank",
                    product_type="Cash",
                    asset_class="Liquiditaet",
                    sub_asset_class="Kontoguthaben",
                    currency="CHF",
                    is_active=1,
                    created_at="2026-03-28T00:00:00.000Z",
                    updated_at="2026-03-28T00:00:00.000Z",
                ),
            ]
        )
        session.commit()

        def fake_download(**kwargs):
            assert kwargs["tickers"] == "XLE"
            index = pd.DatetimeIndex([pd.Timestamp("2026-03-28")])
            columns = pd.MultiIndex.from_tuples([("XLE", "Close")])
            return pd.DataFrame([[91.23]], index=index, columns=columns)

        fake_yf = type("FakeYF", (), {"download": staticmethod(fake_download)})
        monkeypatch.setattr(price_updater_module, "yf", fake_yf)

        summary = refresh_all_prices(session)
        prices = session.query(PriceHistory).order_by(PriceHistory.product_id.asc()).all()

    assert summary["processed"] == 2
    assert summary["failed"] == 0
    assert summary["inserted"] == 2
    assert {row.product_id for row in prices} == {"prod-cash", "prod-energy"}
    assert {row.source for row in prices} == {"synthetic_par", "yfinance"}


def test_refresh_all_prices_reuses_existing_fresh_price_when_provider_fails(session_factory, monkeypatch):
    import pandas as pd
    import price_updater as price_updater_module

    with session_factory() as session:
        session.add(
            Product(
                id="prod-reuse",
                product_name="Energy Select Sector ETF",
                provider="State Street",
                product_type="ETF",
                asset_class="Aktien",
                sub_asset_class="Thema Fossile Energie",
                currency="USD",
                is_active=1,
                created_at="2026-03-28T00:00:00.000Z",
                updated_at="2026-03-28T00:00:00.000Z",
            )
        )
        session.add(
            PriceHistory(
                id="price-reuse",
                product_id="prod-reuse",
                price_date=date.today().isoformat(),
                price_rappen=9123,
                currency="USD",
                source="yfinance",
                fetched_at=date.today().isoformat() + "T12:00:00.000Z",
            )
        )
        session.commit()

        def fake_download(**kwargs):
            return pd.DataFrame()

        fake_yf = type("FakeYF", (), {"download": staticmethod(fake_download)})
        monkeypatch.setattr(price_updater_module, "yf", fake_yf)
        monkeypatch.setattr(price_updater_module, "fetch_stooq_price", lambda symbol, *, currency=None: (_ for _ in ()).throw(ValueError("no fallback")))

        summary = refresh_all_prices(session)
        prices = session.query(PriceHistory).filter(PriceHistory.product_id == "prod-reuse").all()

    assert summary["processed"] == 1
    assert summary["reused_fresh"] == 1
    assert summary["failed"] == 0
    assert summary["unchanged"] == 1
    assert len(prices) == 1


def test_refresh_all_prices_uses_stooq_fallback_for_external_profiles(session_factory, monkeypatch):
    import pandas as pd
    import price_updater as price_updater_module

    with session_factory() as session:
        session.add(
            Product(
                id="prod-stooq",
                product_name="Energy Select Sector ETF",
                provider="State Street",
                product_type="ETF",
                asset_class="Aktien",
                sub_asset_class="Thema Fossile Energie",
                currency="USD",
                is_active=1,
                created_at="2026-03-28T00:00:00.000Z",
                updated_at="2026-03-28T00:00:00.000Z",
            )
        )
        session.commit()

        def fake_download(**kwargs):
            return pd.DataFrame()

        def fake_stooq(symbol, *, currency=None):
            assert symbol == "XLE"
            return price_updater_module.PricePoint(
                price_date="2026-03-27",
                price_rappen=6256,
                currency=(currency or "USD"),
                source="stooq",
            )

        fake_yf = type("FakeYF", (), {"download": staticmethod(fake_download)})
        monkeypatch.setattr(price_updater_module, "yf", fake_yf)
        monkeypatch.setattr(price_updater_module, "fetch_stooq_price", fake_stooq)

        summary = refresh_all_prices(session)
        price = session.query(PriceHistory).filter(PriceHistory.product_id == "prod-stooq").one()

    assert summary["processed"] == 1
    assert summary["failed"] == 0
    assert summary["inserted"] == 1
    assert price.source == "stooq"
    assert price.price_rappen == 6256


def test_delete_cashflow_marks_record_inactive(session_factory, advisor_user):
    client_id, _ = seed_client_and_mandate(session_factory, advisor_user)

    with session_factory() as session:
        session.add(
            Cashflow(
                id="cf-1",
                client_id=client_id,
                cashflow_type="Expense",
                label="Fixkosten",
                amount_rappen=250000,
                currency="CHF",
                frequency="monatlich",
                nature="wiederkehrend",
                is_inflation_linked=0,
                is_active=1,
                created_at="2026-03-27T00:00:00.000Z",
                updated_at="2026-03-27T00:00:00.000Z",
            )
        )
        session.commit()

    with session_factory() as session:
        delete_cashflow(
            client_id=client_id,
            cf_id="cf-1",
            db=session,
            current_user=advisor_user,
        )

    with session_factory() as session:
        cashflow = session.query(Cashflow).filter(Cashflow.id == "cf-1").one()
        assert cashflow.is_active == 0
        assert cashflow.deleted_at is not None


def test_create_cashflow_requires_date_for_one_off(session_factory, advisor_user):
    client_id, _ = seed_client_and_mandate(session_factory, advisor_user)

    payload = CashflowCreate(
        cashflow_type="Income",
        label="3a Auszahlung",
        amount_rappen=35000000,
        frequency="einmalig",
        nature="einmalig",
    )

    with session_factory() as session:
        with pytest.raises(HTTPException) as exc_info:
            create_cashflow(
                client_id=client_id,
                body=payload,
                db=session,
                current_user=advisor_user,
            )

    assert exc_info.value.status_code == 422
    assert "Datum" in exc_info.value.detail


def test_create_cashflow_normalizes_frequency_aliases(session_factory, advisor_user):
    client_id, _ = seed_client_and_mandate(session_factory, advisor_user)

    cases = [
        ("jaehrlich", "jährlich", None),
        ("halbjaehrlich", "halbjährlich", None),
        ("vierteljaehrlich", "quartalsweise", None),
        ("one-time", "einmalig", "2026-06-30"),
    ]

    with session_factory() as session:
        for idx, (raw_frequency, expected_frequency, event_date) in enumerate(cases, start=1):
            payload = CashflowCreate(
                cashflow_type="Income",
                label=f"Alias {idx}",
                amount_rappen=100000,
                frequency=raw_frequency,
                nature="einmalig" if expected_frequency == "einmalig" else "wiederkehrend",
                valid_from=event_date,
                valid_until=event_date,
            )
            result = create_cashflow(
                client_id=client_id,
                body=payload,
                db=session,
                current_user=advisor_user,
            )
            assert result.frequency == expected_frequency


def test_create_cashflow_persists_capital_withdrawal_metadata(session_factory, advisor_user):
    client_id, _ = seed_client_and_mandate(session_factory, advisor_user)

    payload = CashflowCreate(
        cashflow_type="Income",
        label="3a Kapitalbezug",
        amount_rappen=32000000,
        gross_amount_rappen=35000000,
        tax_amount_rappen=3000000,
        frequency="einmalig",
        nature="einmalig",
        timing_precision="month",
        valid_from="2028-06",
        notes="3a Kapitalbezug",
    )

    with session_factory() as session:
        result = create_cashflow(
            client_id=client_id,
            body=payload,
            db=session,
            current_user=advisor_user,
        )

    assert result.amount_rappen == 32000000
    assert result.gross_amount_rappen == 35000000
    assert result.tax_amount_rappen == 3000000
    assert result.frequency == "einmalig"
    assert result.timing_precision == "month"
    assert result.valid_from == "2028-06-01"
    assert result.valid_until == "2028-06-01"


def test_create_cashflow_rejects_net_amount_above_gross(session_factory, advisor_user):
    client_id, _ = seed_client_and_mandate(session_factory, advisor_user)

    payload = CashflowCreate(
        cashflow_type="Income",
        label="FZK Kapitalbezug",
        amount_rappen=36000000,
        gross_amount_rappen=35000000,
        tax_amount_rappen=1000000,
        frequency="einmalig",
        nature="einmalig",
        valid_from="2028-06-30",
        valid_until="2028-06-30",
        notes="FZK Kapitalbezug",
    )

    with session_factory() as session:
        with pytest.raises(HTTPException) as exc_info:
            create_cashflow(
                client_id=client_id,
                body=payload,
                db=session,
                current_user=advisor_user,
            )

    assert exc_info.value.status_code == 422
    assert "Bruttobetrag" in exc_info.value.detail


def test_cashflow_summary_counts_only_current_year_cashflows(session_factory, advisor_user):
    client_id, _ = seed_client_and_mandate(session_factory, advisor_user)
    current_year = "2026-01-01"

    with session_factory() as session:
        session.add_all(
            [
                Cashflow(
                    id="cf-income-ended",
                    client_id=client_id,
                    cashflow_type="Income",
                    label="Alter Lohn",
                    amount_rappen=1000000,
                    currency="CHF",
                    frequency="monatlich",
                    nature="wiederkehrend",
                    valid_until="2025-12-31",
                    is_inflation_linked=0,
                    is_active=1,
                    created_at="2026-03-27T00:00:00.000Z",
                    updated_at="2026-03-27T00:00:00.000Z",
                ),
                Cashflow(
                    id="cf-income-active",
                    client_id=client_id,
                    cashflow_type="Income",
                    label="Lohn aktuell",
                    amount_rappen=1200000,
                    currency="CHF",
                    frequency="monatlich",
                    nature="wiederkehrend",
                    valid_from=current_year,
                    valid_until="2032-12-31",
                    is_inflation_linked=0,
                    is_active=1,
                    created_at="2026-03-27T00:00:00.000Z",
                    updated_at="2026-03-27T00:00:00.000Z",
                ),
                Cashflow(
                    id="cf-income-future",
                    client_id=client_id,
                    cashflow_type="Income",
                    label="3a später",
                    amount_rappen=35000000,
                    currency="CHF",
                    frequency="einmalig",
                    nature="einmalig",
                    valid_from="2028-06-30",
                    valid_until="2028-06-30",
                    is_inflation_linked=0,
                    is_active=1,
                    created_at="2026-03-27T00:00:00.000Z",
                    updated_at="2026-03-27T00:00:00.000Z",
                ),
                Cashflow(
                    id="cf-expense-active",
                    client_id=client_id,
                    cashflow_type="Expense",
                    label="Fixkosten",
                    amount_rappen=400000,
                    currency="CHF",
                    frequency="monatlich",
                    nature="wiederkehrend",
                    is_inflation_linked=0,
                    is_active=1,
                    created_at="2026-03-27T00:00:00.000Z",
                    updated_at="2026-03-27T00:00:00.000Z",
                ),
            ]
        )
        session.commit()
        summary = cashflow_summary(client_id=client_id, db=session, current_user=advisor_user)

    assert summary.summary_year == 2026
    assert summary.total_income_rappen == 14400000
    assert summary.total_expense_rappen == 4800000
    assert summary.surplus_rappen == 9600000


def test_cashflow_summary_applies_occurrence_count_by_frequency(session_factory, advisor_user):
    client_id, _ = seed_client_and_mandate(session_factory, advisor_user)
    current_year = date.today().year
    start_of_year = f"{current_year}-01-01"
    one_off_date = f"{current_year}-06-30"

    with session_factory() as session:
        session.add_all(
            [
                Cashflow(
                    id="cf-monthly",
                    client_id=client_id,
                    cashflow_type="Income",
                    label="Monatlich",
                    amount_rappen=10000,
                    currency="CHF",
                    frequency="monatlich",
                    nature="wiederkehrend",
                    valid_from=start_of_year,
                    is_inflation_linked=0,
                    is_active=1,
                    created_at="2026-03-27T00:00:00.000Z",
                    updated_at="2026-03-27T00:00:00.000Z",
                ),
                Cashflow(
                    id="cf-quarterly",
                    client_id=client_id,
                    cashflow_type="Income",
                    label="Vierteljährlich",
                    amount_rappen=10000,
                    currency="CHF",
                    frequency="quartalsweise",
                    nature="wiederkehrend",
                    valid_from=start_of_year,
                    is_inflation_linked=0,
                    is_active=1,
                    created_at="2026-03-27T00:00:00.000Z",
                    updated_at="2026-03-27T00:00:00.000Z",
                ),
                Cashflow(
                    id="cf-semiannual",
                    client_id=client_id,
                    cashflow_type="Income",
                    label="Halbjährlich",
                    amount_rappen=10000,
                    currency="CHF",
                    frequency="halbjährlich",
                    nature="wiederkehrend",
                    valid_from=start_of_year,
                    is_inflation_linked=0,
                    is_active=1,
                    created_at="2026-03-27T00:00:00.000Z",
                    updated_at="2026-03-27T00:00:00.000Z",
                ),
                Cashflow(
                    id="cf-annual",
                    client_id=client_id,
                    cashflow_type="Income",
                    label="Jährlich",
                    amount_rappen=10000,
                    currency="CHF",
                    frequency="jährlich",
                    nature="wiederkehrend",
                    valid_from=start_of_year,
                    is_inflation_linked=0,
                    is_active=1,
                    created_at="2026-03-27T00:00:00.000Z",
                    updated_at="2026-03-27T00:00:00.000Z",
                ),
                Cashflow(
                    id="cf-once",
                    client_id=client_id,
                    cashflow_type="Income",
                    label="Einmalig",
                    amount_rappen=50000,
                    currency="CHF",
                    frequency="einmalig",
                    nature="einmalig",
                    valid_from=one_off_date,
                    valid_until=one_off_date,
                    is_inflation_linked=0,
                    is_active=1,
                    created_at="2026-03-27T00:00:00.000Z",
                    updated_at="2026-03-27T00:00:00.000Z",
                ),
            ]
        )
        session.commit()
        summary = cashflow_summary(client_id=client_id, db=session, current_user=advisor_user)

    assert summary.total_income_rappen == 240000
    assert summary.total_expense_rappen == 0
    assert summary.surplus_rappen == 240000


def test_create_goal_derives_horizon_and_frequency_from_timing_fields(session_factory, advisor_user):
    _, mandate_id = seed_client_and_mandate(session_factory, advisor_user)
    current_year = date.today().year

    payload = GoalCreate(
        goal_family="Cashflow",
        goal_type="Wiederkehrende_Ausgabe",
        label="Ausbildung Kind",
        rank=1,
        goal_scope="Beratungsvermögen",
        value_mode="nominal",
        target_amount_rappen=300000,
        start_date=f"{current_year + 4}-08-01",
        is_ongoing=True,
        frequency="monatlich",
        hardness="Hart",
    )

    with session_factory() as session:
        result = create_goal(
            mandate_id=mandate_id,
            body=payload,
            db=session,
            current_user=advisor_user,
        )

    assert result.frequency == "monatlich"
    assert result.is_ongoing == 1
    assert result.start_date == f"{current_year + 4}-08-01"
    assert result.horizon_years == 5


def test_create_goal_uses_target_date_for_one_off_goal(session_factory, advisor_user):
    _, mandate_id = seed_client_and_mandate(session_factory, advisor_user)
    current_year = date.today().year

    payload = GoalCreate(
        goal_family="Cashflow",
        goal_type="Einmalige_Ausgabe",
        label="Eigenheim Kauf",
        rank=1,
        goal_scope="Beratungsvermögen",
        value_mode="nominal",
        target_amount_rappen=15000000,
        target_date=f"{current_year + 2}-06-30",
        hardness="Hart",
    )

    with session_factory() as session:
        result = create_goal(
            mandate_id=mandate_id,
            body=payload,
            db=session,
            current_user=advisor_user,
        )

    assert result.frequency is None
    assert result.is_ongoing == 0
    assert result.start_date == f"{current_year + 2}-06-30"
    assert result.horizon_years == 3


def test_create_wealth_position_rejects_free_text_mortgage_link(session_factory, advisor_user):
    client_id, _ = seed_client_and_mandate(session_factory, advisor_user)

    payload = WealthPositionCreate(
        label="Hypothek Eigenheim",
        position_type="Hypothek",
        assignment="Verbindlichkeit",
        current_value_rappen=78000000,
        mortgage_bank="UBS",
        mortgage_type="Festhypothek",
        mortgage_linked_property_id="Eigentumswohnung Zürich",
    )

    with session_factory() as session:
        with pytest.raises(HTTPException) as exc_info:
            create_wealth_position(
                client_id=client_id,
                body=payload,
                db=session,
                current_user=advisor_user,
            )

    assert exc_info.value.status_code == 422
    assert "Immobilien-Position" in exc_info.value.detail


def test_create_wealth_position_accepts_valid_mortgage_property_link(session_factory, advisor_user):
    client_id, _ = seed_client_and_mandate(session_factory, advisor_user)

    with session_factory() as session:
        session.add(
            WealthPosition(
                id="property-1",
                client_id=client_id,
                label="Eigentumswohnung Zürich",
                position_type="Immobilien",
                assignment="Anderes Vermögen",
                current_value_rappen=120000000,
                currency="CHF",
                property_usage="Selbstgenutzt",
                is_active=1,
                created_at="2026-03-27T00:00:00.000Z",
                updated_at="2026-03-27T00:00:00.000Z",
            )
        )
        session.commit()

    payload = WealthPositionCreate(
        label="Hypothek Eigenheim",
        position_type="Hypothek",
        assignment="Verbindlichkeit",
        current_value_rappen=78000000,
        mortgage_bank="UBS",
        mortgage_type="Festhypothek",
        mortgage_linked_property_id="property-1",
    )

    with session_factory() as session:
        result = create_wealth_position(
            client_id=client_id,
            body=payload,
            db=session,
            current_user=advisor_user,
        )

    assert result.client_id == client_id
    assert result.mortgage_linked_property_id == "property-1"


def test_generate_target_allocation_reflects_cashflow_and_goal_constraints(session_factory, advisor_user):
    client_id, mandate_id = seed_client_and_mandate(session_factory, advisor_user)

    payload = RiskAssessmentCreate(
        q_income_points=4,
        q_obligations_points=4,
        q_savings_points=12,
        q_wealth_points=12,
        investment_horizon_label="Mehr als 12 Jahre",
        investment_horizon_years=15,
        q_investment_goal_points=4,
        q_risk_preference_points=4,
        q_risk_behavior_points=4,
        answers=[],
    )

    with session_factory() as session:
        create_risk_assessment(
            mandate_id=mandate_id,
            body=payload,
            db=session,
            current_user=advisor_user,
        )
        session.add_all(
            [
                WealthPosition(
                    id="depot-1",
                    client_id=client_id,
                    label="Depot Hauptbank",
                    position_type="Depot",
                    assignment="Beratungsvermögen",
                    current_value_rappen=60000000,
                    currency="CHF",
                    alloc_equities_bps=7000,
                    alloc_bonds_bps=1500,
                    alloc_real_estate_bps=0,
                    alloc_liquidity_bps=1000,
                    alloc_alternatives_bps=500,
                    is_active=1,
                    created_at="2026-03-27T00:00:00.000Z",
                    updated_at="2026-03-27T00:00:00.000Z",
                ),
                WealthPosition(
                    id="property-1",
                    client_id=client_id,
                    label="Renditeliegenschaft",
                    position_type="Immobilien",
                    assignment="Anderes Vermögen",
                    current_value_rappen=90000000,
                    currency="CHF",
                    property_usage="Vermietet",
                    is_active=1,
                    created_at="2026-03-27T00:00:00.000Z",
                    updated_at="2026-03-27T00:00:00.000Z",
                ),
                Cashflow(
                    id="income-1",
                    client_id=client_id,
                    cashflow_type="Income",
                    label="Einkommen",
                    amount_rappen=18000000,
                    currency="CHF",
                    frequency="jährlich",
                    nature="wiederkehrend",
                    is_inflation_linked=0,
                    is_active=1,
                    created_at="2026-03-27T00:00:00.000Z",
                    updated_at="2026-03-27T00:00:00.000Z",
                ),
                Cashflow(
                    id="expense-1",
                    client_id=client_id,
                    cashflow_type="Expense",
                    label="Kosten",
                    amount_rappen=12000000,
                    currency="CHF",
                    frequency="jährlich",
                    nature="wiederkehrend",
                    is_inflation_linked=0,
                    is_active=1,
                    created_at="2026-03-27T00:00:00.000Z",
                    updated_at="2026-03-27T00:00:00.000Z",
                ),
                Goal(
                    id="goal-1",
                    mandate_id=mandate_id,
                    client_id=client_id,
                    goal_family="Cashflow",
                    goal_type="Einmalige_Ausgabe",
                    label="Eigenmittel Kauf",
                    rank=1,
                    goal_scope="Beratungsvermögen",
                    value_mode="nominal",
                    target_amount_rappen=15000000,
                    horizon_years=2,
                    hardness="Hart",
                    is_active=1,
                    created_at="2026-03-27T00:00:00.000Z",
                    updated_at="2026-03-27T00:00:00.000Z",
                ),
            ]
        )
        session.commit()
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        result = generate_target_allocation(
            db=session,
            mandate=mandate,
            user_id=advisor_user.id,
            preferences={
                "limits": {"minReserve": "120'000"},
                "assetClasses": {"liquidityReserveTarget": "150'000", "equitiesGeo": "Schweiz Fokus"},
                "tilts": {},
                "policy": {},
                "product": {},
                "geo": {},
            },
        )

    assert result["target_allocation"].mandate_id == mandate_id
    assert result["reserve_needed_rappen"] >= 15000000
    liquidity_bucket = next(bucket for bucket in result["buckets"] if bucket["asset_class"] == "Liquiditaet")
    assert liquidity_bucket["target_weight_bps"] >= liquidity_bucket["current_weight_bps"]
    assert any("Liquiditaetsbedarf" in reason or "Liquiditaetsquote" in reason for reason in result["reasoning"])


def test_generate_target_allocation_respects_manual_band_overrides(session_factory, advisor_user):
    client_id, mandate_id = seed_client_and_mandate(session_factory, advisor_user)

    payload = RiskAssessmentCreate(
        q_income_points=4,
        q_obligations_points=4,
        q_savings_points=12,
        q_wealth_points=12,
        investment_horizon_label="Mehr als 12 Jahre",
        investment_horizon_years=15,
        q_investment_goal_points=4,
        q_risk_preference_points=4,
        q_risk_behavior_points=4,
        answers=[],
    )

    with session_factory() as session:
        create_risk_assessment(
            mandate_id=mandate_id,
            body=payload,
            db=session,
            current_user=advisor_user,
        )
        session.add(
            WealthPosition(
                id="depot-bands-1",
                client_id=client_id,
                label="Depot Bandbreiten",
                position_type="Depot",
                assignment="Beratungsvermögen",
                current_value_rappen=90000000,
                currency="CHF",
                alloc_equities_bps=6000,
                alloc_bonds_bps=2500,
                alloc_real_estate_bps=500,
                alloc_liquidity_bps=500,
                alloc_alternatives_bps=500,
                is_active=1,
                created_at="2026-03-27T00:00:00.000Z",
                updated_at="2026-03-27T00:00:00.000Z",
            )
        )
        session.flush()
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        result = generate_target_allocation(
            db=session,
            mandate=mandate,
            user_id=advisor_user.id,
            preferences={
                "policy": {},
                "tilts": {},
                "product": {},
                "limits": {},
                "geo": {},
                "assetClasses": {},
                "bands": {
                    "equities": {"min_bps": 6000, "target_bps": 6500, "max_bps": 7200},
                    "bonds": {"min_bps": 1200, "target_bps": 1500, "max_bps": 2200},
                    "real_estate": {"min_bps": 400, "target_bps": 700, "max_bps": 1200},
                    "alternatives": {"min_bps": 300, "target_bps": 500, "max_bps": 800},
                    "liquidity": {"min_bps": 800, "target_bps": 800, "max_bps": 1200},
                },
            },
        )

    target = result["target_allocation"]
    assert int(target.target_equities_bps) == 6500
    assert int(target.band_equities_min_bps) == 6000
    assert int(target.band_equities_max_bps) == 7200
    assert any("Bandbreiten" in reason for reason in result["reasoning"])


def test_generate_target_allocation_uses_weighted_risk_budget(session_factory, advisor_user):
    client_id, mandate_id = seed_client_and_mandate(session_factory, advisor_user)

    payload = RiskAssessmentCreate(
        q_income_points=4,
        q_obligations_points=4,
        q_savings_points=12,
        q_wealth_points=12,
        investment_horizon_label="Mehr als 12 Jahre",
        investment_horizon_years=15,
        q_investment_goal_points=4,
        q_risk_preference_points=4,
        q_risk_behavior_points=4,
        answers=[],
    )

    with session_factory() as session:
        create_risk_assessment(
            mandate_id=mandate_id,
            body=payload,
            db=session,
            current_user=advisor_user,
        )
        session.add(
            WealthPosition(
                id="depot-risky-1",
                client_id=client_id,
                label="Depot Risikobudget",
                position_type="Depot",
                assignment="Beratungsvermögen",
                current_value_rappen=100000000,
                currency="CHF",
                alloc_equities_bps=7000,
                alloc_bonds_bps=1500,
                alloc_real_estate_bps=500,
                alloc_liquidity_bps=500,
                alloc_alternatives_bps=500,
                is_active=1,
                created_at="2026-03-27T00:00:00.000Z",
                updated_at="2026-03-27T00:00:00.000Z",
            )
        )
        session.flush()
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        result = generate_target_allocation(
            db=session,
            mandate=mandate,
            user_id=advisor_user.id,
            preferences={"policy": {}, "tilts": {}, "product": {}, "limits": {}, "geo": {}, "assetClasses": {}},
        )

    assert result["risk_budget_bps"] == 10000
    assert result["risky_fraction_total_bps"] <= result["risk_budget_bps"]
    assert result["risky_fraction_total_bps"] < (
        int(result["target_allocation"].target_equities_bps)
        + int(result["target_allocation"].target_real_estate_bps)
        + int(result["target_allocation"].target_alternatives_bps)
    )
    equities_sub = [item for item in result["sub_allocations"] if item["asset_class"] == "Aktien"]
    assert equities_sub
    assert all(item["risky_fraction_bps"] is not None for item in equities_sub)


def test_generate_target_allocation_uses_dated_cashflow_series(session_factory, advisor_user):
    client_id, mandate_id = seed_client_and_mandate(session_factory, advisor_user)

    payload = RiskAssessmentCreate(
        q_income_points=4,
        q_obligations_points=4,
        q_savings_points=12,
        q_wealth_points=12,
        investment_horizon_label="Mehr als 12 Jahre",
        investment_horizon_years=15,
        q_investment_goal_points=4,
        q_risk_preference_points=4,
        q_risk_behavior_points=4,
        answers=[],
    )

    with session_factory() as session:
        create_risk_assessment(
            mandate_id=mandate_id,
            body=payload,
            db=session,
            current_user=advisor_user,
        )
        session.add(
            WealthPosition(
                id="depot-dated-1",
                client_id=client_id,
                label="Depot Hauptbank",
                position_type="Depot",
                assignment="BeratungsvermÃ¶gen",
                current_value_rappen=50000000,
                currency="CHF",
                alloc_equities_bps=6000,
                alloc_bonds_bps=2500,
                alloc_real_estate_bps=0,
                alloc_liquidity_bps=1000,
                alloc_alternatives_bps=500,
                is_active=1,
                created_at="2026-03-27T00:00:00.000Z",
                updated_at="2026-03-27T00:00:00.000Z",
            )
        )
        session.add_all(
            [
                Cashflow(
                    id="income-dated-1",
                    client_id=client_id,
                    cashflow_type="Income",
                    label="Lohn bis 2032",
                    amount_rappen=1200000,
                    currency="CHF",
                    frequency="monatlich",
                    nature="wiederkehrend",
                    valid_from="2026-01-01",
                    valid_until="2032-12-31",
                    is_inflation_linked=0,
                    is_active=1,
                    created_at="2026-03-27T00:00:00.000Z",
                    updated_at="2026-03-27T00:00:00.000Z",
                ),
                Cashflow(
                    id="income-dated-2",
                    client_id=client_id,
                    cashflow_type="Income",
                    label="3a in 2028",
                    amount_rappen=35000000,
                    currency="CHF",
                    frequency="einmalig",
                    nature="einmalig",
                    valid_from="2028-06-30",
                    valid_until="2028-06-30",
                    is_inflation_linked=0,
                    is_active=1,
                    created_at="2026-03-27T00:00:00.000Z",
                    updated_at="2026-03-27T00:00:00.000Z",
                ),
                Cashflow(
                    id="expense-dated-1",
                    client_id=client_id,
                    cashflow_type="Expense",
                    label="Lebenshaltung",
                    amount_rappen=500000,
                    currency="CHF",
                    frequency="monatlich",
                    nature="wiederkehrend",
                    is_inflation_linked=0,
                    is_active=1,
                    created_at="2026-03-27T00:00:00.000Z",
                    updated_at="2026-03-27T00:00:00.000Z",
                ),
                Goal(
                    id="goal-dated-1",
                    mandate_id=mandate_id,
                    client_id=client_id,
                    goal_family="Vermoegen",
                    goal_type="VermÃ¶gensziel",
                    label="Familienvermögen",
                    rank=1,
                    goal_scope="BeratungsvermÃ¶gen",
                    value_mode="nominal",
                    target_wealth_rappen=180000000,
                    horizon_years=9,
                    hardness="Hart",
                    is_active=1,
                    created_at="2026-03-27T00:00:00.000Z",
                    updated_at="2026-03-27T00:00:00.000Z",
                ),
            ]
        )
        session.commit()
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        result = generate_target_allocation(
            db=session,
            mandate=mandate,
            user_id=advisor_user.id,
            preferences={"policy": {}, "tilts": {}, "product": {}, "limits": {}, "geo": {}, "assetClasses": {}},
        )

    assert result["annual_net_cashflow_rappen"] == 8400000
    assert result["cashflow_projection_series_rappen"][:4] == [8400000, 8400000, 43400000, 8400000]
    assert result["cashflow_projection_series_rappen"][7] == -6000000
    assert len(result["cashflow_projection_series_rappen"]) >= 9


def test_generate_target_allocation_exposes_simulation_and_asset_assumptions(session_factory, advisor_user):
    client_id, mandate_id = seed_client_and_mandate(session_factory, advisor_user)

    payload = RiskAssessmentCreate(
        q_income_points=4,
        q_obligations_points=4,
        q_savings_points=12,
        q_wealth_points=12,
        investment_horizon_label="Mehr als 12 Jahre",
        investment_horizon_years=15,
        q_investment_goal_points=4,
        q_risk_preference_points=4,
        q_risk_behavior_points=4,
        answers=[],
    )

    with session_factory() as session:
        create_risk_assessment(
            mandate_id=mandate_id,
            body=payload,
            db=session,
            current_user=advisor_user,
        )
        session.add(
            WealthPosition(
                id="depot-sim-1",
                client_id=client_id,
                label="Depot Simulation",
                position_type="Depot",
                assignment="Beratungsvermögen",
                current_value_rappen=100000000,
                currency="CHF",
                alloc_equities_bps=5500,
                alloc_bonds_bps=3000,
                alloc_real_estate_bps=500,
                alloc_liquidity_bps=500,
                alloc_alternatives_bps=500,
                is_active=1,
                created_at="2026-03-27T00:00:00.000Z",
                updated_at="2026-03-27T00:00:00.000Z",
            )
        )
        session.add(
            Cashflow(
                id="cf-sim-1",
                client_id=client_id,
                cashflow_type="Income",
                label="Sparquote",
                amount_rappen=1200000,
                currency="CHF",
                frequency="monatlich",
                nature="wiederkehrend",
                valid_from="2026-01-01",
                valid_until="2035-12-31",
                is_inflation_linked=0,
                is_active=1,
                created_at="2026-03-27T00:00:00.000Z",
                updated_at="2026-03-27T00:00:00.000Z",
            )
        )
        session.commit()
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        result = generate_target_allocation(
            db=session,
            mandate=mandate,
            user_id=advisor_user.id,
            preferences={
                "policy": {},
                "tilts": {},
                "product": {},
                "limits": {},
                "geo": {},
                "assetClasses": {},
                "simulation": {"horizonYears": 12, "stressMultiplier": 1.5, "rebalanceMode": "bands", "monteCarloRuns": 900},
            },
        )

    simulation = result["simulation"]
    monte_carlo = result["monte_carlo"]
    assumptions = {item["asset_class"]: item for item in result["asset_class_assumptions"]}
    assert simulation["horizon_years"] == 12
    assert simulation["start_year"] == date.today().year
    assert len(simulation["year_labels"]) == 13
    assert len(simulation["target_mix_series_rappen"]) == 13
    assert len(simulation["current_mix_series_rappen"]) == 13
    assert len(simulation["real_target_series_rappen"]) == 13
    assert simulation["stress_multiplier"] == 1.5
    assert simulation["rebalance_mode"] == "bands"
    assert monte_carlo["simulations"] == 900
    assert monte_carlo["horizon_years"] == 12
    assert len(monte_carlo["year_labels"]) == 13
    assert len(monte_carlo["target_p50_series_rappen"]) == 13
    assert len(monte_carlo["target_p10_series_rappen"]) == 13
    assert len(monte_carlo["goal_summaries"]) == 0
    assert monte_carlo["target_p90_series_rappen"][-1] >= monte_carlo["target_p50_series_rappen"][-1] >= monte_carlo["target_p10_series_rappen"][-1]
    assert monte_carlo["target_var_95_1y_bps"] <= monte_carlo["target_cvar_95_1y_bps"] <= 10000
    assert 0 <= monte_carlo["target_loss_probability_1y_pct"] <= 100
    assert 0 <= monte_carlo["target_max_drawdown_p50_bps"] <= monte_carlo["target_max_drawdown_p95_bps"] <= 10000
    assert 0 <= monte_carlo["target_downside_probability_pct"] <= 100
    assert assumptions["Aktien"]["risky_fraction_bps"] >= assumptions["Obligationen"]["risky_fraction_bps"]
    assert assumptions["Aktien"]["expected_return_bps"] > assumptions["Obligationen"]["expected_return_bps"]
    assert assumptions["Liquiditaet"]["market_data_role"].startswith("Live-Preise")
    assert any("Pfadsimulation" in item for item in result["reasoning"])
    validated = TargetAllocationGenerateResponse.model_validate(result)
    assert validated.monte_carlo.simulations == 900


def test_generate_target_allocation_goal_analysis_exposes_timing_and_return_targets(session_factory, advisor_user):
    client_id, mandate_id = seed_client_and_mandate(session_factory, advisor_user)

    payload = RiskAssessmentCreate(
        q_income_points=4,
        q_obligations_points=4,
        q_savings_points=12,
        q_wealth_points=12,
        investment_horizon_label="Mehr als 12 Jahre",
        investment_horizon_years=15,
        q_investment_goal_points=4,
        q_risk_preference_points=4,
        q_risk_behavior_points=4,
        answers=[],
    )

    with session_factory() as session:
        create_risk_assessment(
            mandate_id=mandate_id,
            body=payload,
            db=session,
            current_user=advisor_user,
        )
        session.add(
            WealthPosition(
                id="depot-goal-analysis-1",
                client_id=client_id,
                label="Depot Analyse",
                position_type="Depot",
                assignment="BeratungsvermÃƒÂ¶gen",
                current_value_rappen=60000000,
                currency="CHF",
                alloc_equities_bps=6000,
                alloc_bonds_bps=2500,
                alloc_real_estate_bps=0,
                alloc_liquidity_bps=1000,
                alloc_alternatives_bps=500,
                is_active=1,
                created_at="2026-03-27T00:00:00.000Z",
                updated_at="2026-03-27T00:00:00.000Z",
            )
        )
        session.add_all(
            [
                Goal(
                    id="goal-timing-oneoff",
                    mandate_id=mandate_id,
                    client_id=client_id,
                    goal_family="Cashflow",
                    goal_type="Einmalige_Ausgabe",
                    label="Eigenmittel",
                    rank=1,
                    goal_scope="BeratungsvermÃ¶gen",
                    value_mode="nominal",
                    target_amount_rappen=35000000,
                    start_date="2028-06-30",
                    target_date="2028-06-30",
                    hardness="Hart",
                    is_active=1,
                    created_at="2026-03-27T00:00:00.000Z",
                    updated_at="2026-03-27T00:00:00.000Z",
                ),
                Goal(
                    id="goal-timing-recurring",
                    mandate_id=mandate_id,
                    client_id=client_id,
                    goal_family="Cashflow",
                    goal_type="Pensionsausgabe",
                    label="Pensionsbedarf",
                    rank=2,
                    goal_scope="BeratungsvermÃ¶gen",
                    value_mode="nominal",
                    target_amount_rappen=800000,
                    start_date="2032-01-01",
                    target_date="2040-12-31",
                    frequency="monatlich",
                    hardness="PrimÃ¤r",
                    is_active=1,
                    created_at="2026-03-27T00:00:00.000Z",
                    updated_at="2026-03-27T00:00:00.000Z",
                ),
                Goal(
                    id="goal-timing-return",
                    mandate_id=mandate_id,
                    client_id=client_id,
                    goal_family="Rendite",
                    goal_type="Renditeziel",
                    label="Renditeziel",
                    rank=3,
                    goal_scope="GesamtvermÃ¶gen",
                    value_mode="nominal",
                    target_return_bps=450,
                    target_date="2034-12-31",
                    hardness="Opportunistisch",
                    is_active=1,
                    created_at="2026-03-27T00:00:00.000Z",
                    updated_at="2026-03-27T00:00:00.000Z",
                ),
            ]
        )
        session.commit()
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        result = generate_target_allocation(
            db=session,
            mandate=mandate,
            user_id=advisor_user.id,
            preferences={"policy": {}, "tilts": {}, "product": {}, "limits": {}, "geo": {}, "assetClasses": {}},
        )

    analysis = {item["label"]: item for item in result["goal_analysis"]}
    assert analysis["Eigenmittel"]["timing_label"] == "am 2028-06-30"
    assert analysis["Eigenmittel"]["frequency"] is None
    assert analysis["Eigenmittel"]["path_success_rate_pct"] is not None
    assert analysis["Pensionsbedarf"]["timing_label"].endswith("bis 2040-12-31")
    assert analysis["Pensionsbedarf"]["projected_value_p90_rappen"] >= analysis["Pensionsbedarf"]["projected_value_p50_rappen"] >= analysis["Pensionsbedarf"]["projected_value_p10_rappen"]
    assert analysis["Renditeziel"]["target_return_bps"] == 450
    assert analysis["Renditeziel"]["target_wealth_rappen"] is None
    assert analysis["Renditeziel"]["timing_label"] == "bis 2034-12-31"
    assert analysis["Renditeziel"]["funded_ratio_p50"] is not None


def test_generate_target_allocation_clamps_monte_carlo_runs(session_factory, advisor_user):
    client_id, mandate_id = seed_client_and_mandate(session_factory, advisor_user)

    payload = RiskAssessmentCreate(
        q_income_points=4,
        q_obligations_points=4,
        q_savings_points=12,
        q_wealth_points=12,
        investment_horizon_label="Mehr als 12 Jahre",
        investment_horizon_years=15,
        q_investment_goal_points=4,
        q_risk_preference_points=4,
        q_risk_behavior_points=4,
        answers=[],
    )

    with session_factory() as session:
        create_risk_assessment(
            mandate_id=mandate_id,
            body=payload,
            db=session,
            current_user=advisor_user,
        )
        session.add(
            WealthPosition(
                id="depot-clamp-runs",
                client_id=client_id,
                label="Depot Clamp",
                position_type="Depot",
                assignment="BeratungsvermÃ¶gen",
                current_value_rappen=50000000,
                currency="CHF",
                alloc_equities_bps=5000,
                alloc_bonds_bps=3500,
                alloc_real_estate_bps=500,
                alloc_liquidity_bps=500,
                alloc_alternatives_bps=500,
                is_active=1,
                created_at="2026-03-27T00:00:00.000Z",
                updated_at="2026-03-27T00:00:00.000Z",
            )
        )
        session.commit()
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        low_runs = generate_target_allocation(
            db=session,
            mandate=mandate,
            user_id=advisor_user.id,
            preferences={"simulation": {"monteCarloRuns": 50}},
        )
        high_runs = generate_target_allocation(
            db=session,
            mandate=mandate,
            user_id=advisor_user.id,
            preferences={"simulation": {"monteCarloRuns": 9000}},
        )

    assert low_runs["monte_carlo"]["simulations"] == 250
    assert high_runs["monte_carlo"]["simulations"] == 2500


def test_build_target_payload_from_allocation_exposes_monte_carlo(session_factory, advisor_user):
    client_id, mandate_id = seed_client_and_mandate(session_factory, advisor_user)

    payload = RiskAssessmentCreate(
        q_income_points=4,
        q_obligations_points=4,
        q_savings_points=12,
        q_wealth_points=12,
        investment_horizon_label="Mehr als 12 Jahre",
        investment_horizon_years=15,
        q_investment_goal_points=4,
        q_risk_preference_points=4,
        q_risk_behavior_points=4,
        answers=[],
    )

    with session_factory() as session:
        create_risk_assessment(
            mandate_id=mandate_id,
            body=payload,
            db=session,
            current_user=advisor_user,
        )
        session.add(
            WealthPosition(
                id="depot-build-target-1",
                client_id=client_id,
                label="Depot Payload",
                position_type="Depot",
                assignment="BeratungsvermÃ¶gen",
                current_value_rappen=80000000,
                currency="CHF",
                alloc_equities_bps=5000,
                alloc_bonds_bps=3500,
                alloc_real_estate_bps=500,
                alloc_liquidity_bps=500,
                alloc_alternatives_bps=500,
                is_active=1,
                created_at="2026-03-27T00:00:00.000Z",
                updated_at="2026-03-27T00:00:00.000Z",
            )
        )
        session.add(
            Goal(
                id="goal-build-target-wealth",
                mandate_id=mandate_id,
                client_id=client_id,
                goal_family="Vermoegen",
                goal_type="Vermoegensziel",
                label="Kapitalausbau",
                rank=1,
                goal_scope="BeratungsvermÃ¶gen",
                value_mode="nominal",
                target_wealth_rappen=120000000,
                target_date="2035-12-31",
                hardness="PrimÃ¤r",
                is_active=1,
                created_at="2026-03-27T00:00:00.000Z",
                updated_at="2026-03-27T00:00:00.000Z",
            )
        )
        session.commit()
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        generated = generate_target_allocation(
            db=session,
            mandate=mandate,
            user_id=advisor_user.id,
            preferences={"simulation": {"horizonYears": 10, "stressMultiplier": 1.0, "rebalanceMode": "calendar", "monteCarloRuns": 600}},
        )
        allocation = generated["target_allocation"]
        policy, cma = ensure_runtime_reference_data(session, advisor_user.id)
        assessment = session.query(RiskAssessment).filter(RiskAssessment.mandate_id == mandate_id, RiskAssessment.is_current == 1).one()
        payload_result = build_target_payload_from_allocation(
            db=session,
            mandate=mandate,
            allocation=allocation,
            policy=policy,
            cma=cma,
            assessment=assessment,
            preferences={"simulation": {"horizonYears": 10, "stressMultiplier": 1.0, "rebalanceMode": "calendar", "monteCarloRuns": 600}},
        )

    assert payload_result["monte_carlo"]["simulations"] == 600
    assert payload_result["monte_carlo"]["horizon_years"] == 10
    assert payload_result["monte_carlo"]["year_labels"][0] == date.today().year
    assert payload_result["goal_analysis"][0]["path_success_rate_pct"] is not None
    assert any("Pfadsimulation" in item for item in payload_result["reasoning"])


def test_generate_recommendation_run_builds_product_positions(session_factory, advisor_user):
    client_id, mandate_id = seed_client_and_mandate(session_factory, advisor_user)
    reference_day = date.fromordinal(date.today().toordinal() - 1)
    payload_result = None

    payload = RiskAssessmentCreate(
        q_income_points=4,
        q_obligations_points=4,
        q_savings_points=12,
        q_wealth_points=12,
        investment_horizon_label="Mehr als 12 Jahre",
        investment_horizon_years=15,
        q_investment_goal_points=4,
        q_risk_preference_points=4,
        q_risk_behavior_points=4,
        answers=[],
    )

    with session_factory() as session:
        create_risk_assessment(
            mandate_id=mandate_id,
            body=payload,
            db=session,
            current_user=advisor_user,
        )
        session.add(
            WealthPosition(
                id="depot-1",
                client_id=client_id,
                label="Depot Hauptbank",
                position_type="Depot",
                assignment="Beratungsvermögen",
                current_value_rappen=80000000,
                currency="CHF",
                alloc_equities_bps=6500,
                alloc_bonds_bps=2000,
                alloc_real_estate_bps=500,
                alloc_liquidity_bps=500,
                alloc_alternatives_bps=500,
                is_active=1,
                created_at="2026-03-27T00:00:00.000Z",
                updated_at="2026-03-27T00:00:00.000Z",
            )
        )
        session.commit()
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        allocation = generate_target_allocation(
            db=session,
            mandate=mandate,
            user_id=advisor_user.id,
            preferences={
                "policy": {"homeBias": "ch_focus"},
                "tilts": {"defense": "overweight", "gaming": "underweight"},
                "product": {"fundsOnly": True},
                "limits": {},
                "geo": {},
                "assetClasses": {"equitiesGeo": "Global", "altsGold": True, "liquidityInstrument": "Festgeld"},
            },
        )
        session.commit()
        result = generate_recommendation_run(
            db=session,
            mandate=mandate,
            user_id=advisor_user.id,
            preferences={
                "policy": {"homeBias": "ch_focus"},
                "tilts": {"defense": "overweight", "gaming": "underweight"},
                "product": {"fundsOnly": True},
                "limits": {},
                "geo": {},
                "assetClasses": {"equitiesGeo": "Global", "altsGold": True, "liquidityInstrument": "Festgeld"},
            },
            target_allocation_id=allocation["target_allocation"].id,
            depot_bank="UBS AG Zürich",
        )
        hydrated = build_recommendation_payload_from_run(
            db=session,
            mandate=mandate,
            run=result["run"],
            user_id=advisor_user.id,
            preferences=None,
        )
        if hydrated["positions"]:
            session.add(
                PriceHistory(
                    id="price-hydrated-1-ref",
                    product_id=hydrated["positions"][0]["product_id"],
                    price_date=reference_day.isoformat(),
                    price_rappen=100000,
                    currency="CHF",
                    source="yfinance",
                    fetched_at=reference_day.isoformat() + "T18:00:00.000Z",
                )
            )
            session.add(
                PriceHistory(
                    id="price-hydrated-1-live",
                    product_id=hydrated["positions"][0]["product_id"],
                    price_date=date.today().isoformat(),
                    price_rappen=123450,
                    currency="CHF",
                    source="yfinance",
                    fetched_at=date.today().isoformat() + "T18:00:00.000Z",
                )
            )
            session.commit()
            hydrated = build_recommendation_payload_from_run(
                db=session,
                mandate=mandate,
                run=result["run"],
                user_id=advisor_user.id,
                preferences=None,
            )
            policy, cma = ensure_runtime_reference_data(session, advisor_user.id)
            assessment = session.query(RiskAssessment).filter(
                RiskAssessment.mandate_id == mandate_id,
                RiskAssessment.is_current == 1,
            ).one()
            payload_result = build_target_payload_from_allocation(
                db=session,
                mandate=mandate,
                allocation=allocation["target_allocation"],
                policy=policy,
                cma=cma,
                assessment=assessment,
                preferences=None,
            )

    assert result["run"].mandate_id == mandate_id
    assert result["positions"]
    assert result["average_ter_bps"] >= 0
    assert len({position["product_id"] for position in result["positions"]}) == len(result["positions"])
    assert any("Umsetzung ueber UBS AG Zürich" in position["rationale"] for position in result["positions"])
    assert hydrated["run"].id == result["run"].id
    assert len(hydrated["positions"]) == len(result["positions"])
    assert hydrated["target_allocation_id"] == allocation["target_allocation"].id
    assert "market_data_quality" in hydrated
    assert hydrated["market_data_quality"]["active_products_count"] == len(hydrated["positions"])
    assert hydrated["market_data_quality"]["mapping_gap_count"] == 0
    assert any(position["latest_price_date"] == date.today().isoformat() for position in hydrated["positions"])
    assert hydrated["live_rebalancing"] is not None
    assert hydrated["live_rebalancing"]["position_drifts"]
    assert any(position["lookup_mode"] in {"direct", "proxy", "synthetic_par"} for position in hydrated["positions"])
    assert any(position["lookup_symbol"] for position in hydrated["positions"])
    assert any(
        position["reference_price_date"] in {reference_day.isoformat(), date.today().isoformat()}
        for position in hydrated["positions"]
    )
    assert any(position["current_market_value_rappen"] not in (None, position["target_amount_rappen"]) for position in hydrated["positions"])
    assert payload_result is not None
    assert payload_result["live_rebalancing"] is not None
    assert payload_result["live_rebalancing"]["bucket_drifts"]


def test_recommendation_payload_prefers_actual_holdings_for_live_drift(session_factory, advisor_user):
    client_id, mandate_id = seed_client_and_mandate(session_factory, advisor_user)
    reference_day = date.fromordinal(date.today().toordinal() - 1)

    payload = RiskAssessmentCreate(
        q_income_points=4,
        q_obligations_points=4,
        q_savings_points=12,
        q_wealth_points=12,
        investment_horizon_label="Mehr als 12 Jahre",
        investment_horizon_years=15,
        q_investment_goal_points=4,
        q_risk_preference_points=4,
        q_risk_behavior_points=4,
        answers=[],
    )

    with session_factory() as session:
        create_risk_assessment(
            mandate_id=mandate_id,
            body=payload,
            db=session,
            current_user=advisor_user,
        )
        session.add(
            WealthPosition(
                id="depot-holdings-1",
                client_id=client_id,
                label="Depot Holdings",
                position_type="Depot",
                assignment="BeratungsvermÃ¶gen",
                current_value_rappen=80000000,
                currency="CHF",
                alloc_equities_bps=6500,
                alloc_bonds_bps=2000,
                alloc_real_estate_bps=500,
                alloc_liquidity_bps=500,
                alloc_alternatives_bps=500,
                is_active=1,
                created_at="2026-03-27T00:00:00.000Z",
                updated_at="2026-03-27T00:00:00.000Z",
            )
        )
        session.commit()
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        allocation = generate_target_allocation(
            db=session,
            mandate=mandate,
            user_id=advisor_user.id,
            preferences={"policy": {}, "tilts": {}, "product": {}, "limits": {}, "geo": {}, "assetClasses": {}},
        )
        result = generate_recommendation_run(
            db=session,
            mandate=mandate,
            user_id=advisor_user.id,
            preferences={"policy": {}, "tilts": {}, "product": {}, "limits": {}, "geo": {}, "assetClasses": {}},
            target_allocation_id=allocation["target_allocation"].id,
            depot_bank="UBS AG Zürich",
        )
        assert result["positions"]
        first_position = result["positions"][0]
        session.add(
            PriceHistory(
                id="price-holding-ref",
                product_id=first_position["product_id"],
                price_date=reference_day.isoformat(),
                price_rappen=100000,
                currency="CHF",
                source="yfinance",
                fetched_at=reference_day.isoformat() + "T18:00:00.000Z",
            )
        )
        session.add(
            PriceHistory(
                id="price-holding-live",
                product_id=first_position["product_id"],
                price_date=date.today().isoformat(),
                price_rappen=125000,
                currency="CHF",
                source="yfinance",
                fetched_at=date.today().isoformat() + "T18:00:00.000Z",
            )
        )
        session.flush()
        session.add(
            RecommendationHolding(
                id="holding-1",
                run_id=result["run"].id,
                recommendation_position_id=first_position["id"],
                product_id=first_position["product_id"],
                depot_bank="UBS AG Zürich",
                custody_account_number="CH-DEPOT-1",
                as_of_date=date.today().isoformat(),
                units_milli=1500,
                avg_cost_price_rappen=101000,
                source="manual",
                created_at="2026-03-27T00:00:00.000Z",
                updated_at="2026-03-27T00:00:00.000Z",
            )
        )
        session.commit()

        hydrated = build_recommendation_payload_from_run(
            db=session,
            mandate=mandate,
            run=result["run"],
            user_id=advisor_user.id,
            preferences=None,
        )

    first_hydrated = next(item for item in hydrated["positions"] if item["id"] == first_position["id"])
    assert hydrated["live_rebalancing"] is not None
    assert hydrated["live_rebalancing"]["holding_positions_count"] == 1
    assert hydrated["live_rebalancing"]["implied_positions_count"] >= 0
    assert first_hydrated["holding_present"] is True
    assert first_hydrated["valuation_basis"] == "actual_holding_units"
    assert first_hydrated["holding_depot_bank"] == "UBS AG Zürich"
    assert first_hydrated["holding_units_milli"] == 1500
    assert first_hydrated["current_units_milli"] == 1500
    assert first_hydrated["current_market_value_rappen"] == 187500
    assert hydrated["warnings"] == [] or all(isinstance(item, str) for item in hydrated["warnings"])


def test_generate_recommendation_run_carries_holdings_forward_by_product(session_factory, advisor_user):
    client_id, mandate_id = seed_client_and_mandate(session_factory, advisor_user)

    payload = RiskAssessmentCreate(
        q_income_points=4,
        q_obligations_points=4,
        q_savings_points=12,
        q_wealth_points=12,
        investment_horizon_label="Mehr als 12 Jahre",
        investment_horizon_years=15,
        q_investment_goal_points=4,
        q_risk_preference_points=4,
        q_risk_behavior_points=4,
        answers=[],
    )

    with session_factory() as session:
        create_risk_assessment(
            mandate_id=mandate_id,
            body=payload,
            db=session,
            current_user=advisor_user,
        )
        session.add(
            WealthPosition(
                id="depot-carry-1",
                client_id=client_id,
                label="Depot Carry",
                position_type="Depot",
                assignment="BeratungsvermÃ¶gen",
                current_value_rappen=80000000,
                currency="CHF",
                alloc_equities_bps=6500,
                alloc_bonds_bps=2000,
                alloc_real_estate_bps=500,
                alloc_liquidity_bps=500,
                alloc_alternatives_bps=500,
                is_active=1,
                created_at="2026-03-27T00:00:00.000Z",
                updated_at="2026-03-27T00:00:00.000Z",
            )
        )
        session.commit()
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        allocation = generate_target_allocation(
            db=session,
            mandate=mandate,
            user_id=advisor_user.id,
            preferences={"policy": {}, "tilts": {}, "product": {}, "limits": {}, "geo": {}, "assetClasses": {}},
        )
        first_run = generate_recommendation_run(
            db=session,
            mandate=mandate,
            user_id=advisor_user.id,
            preferences={"policy": {}, "tilts": {}, "product": {}, "limits": {}, "geo": {}, "assetClasses": {}},
            target_allocation_id=allocation["target_allocation"].id,
        )
        first_position = first_run["positions"][0]
        session.add(
            RecommendationHolding(
                id="holding-carry-1",
                run_id=first_run["run"].id,
                recommendation_position_id=first_position["id"],
                product_id=first_position["product_id"],
                depot_bank="UBS AG Zurich",
                custody_account_number="CARRY-1",
                as_of_date=date.today().isoformat(),
                units_milli=7777,
                avg_cost_price_rappen=99000,
                source="manual",
                created_at="2026-03-27T00:00:00.000Z",
                updated_at="2026-03-27T00:00:00.000Z",
            )
        )
        session.commit()

        second_run = generate_recommendation_run(
            db=session,
            mandate=mandate,
            user_id=advisor_user.id,
            preferences={"policy": {}, "tilts": {}, "product": {}, "limits": {}, "geo": {}, "assetClasses": {}},
            target_allocation_id=allocation["target_allocation"].id,
        )
        hydrated = build_recommendation_payload_from_run(
            db=session,
            mandate=mandate,
            run=second_run["run"],
            user_id=advisor_user.id,
            preferences=None,
        )

    assert hydrated["run"].id == second_run["run"].id
    assert hydrated["live_rebalancing"]["holding_positions_count"] >= 1
    assert any(item["holding_present"] for item in hydrated["positions"])
    carried = next(item for item in hydrated["positions"] if item["holding_present"])
    assert carried["holding_units_milli"] == 7777
    assert carried["holding_depot_bank"] == "UBS AG Zurich"
    assert carried["valuation_basis"] == "actual_holding_units"


def test_deleted_holding_does_not_resurface_from_older_runs(session_factory, advisor_user):
    client_id, mandate_id = seed_client_and_mandate(session_factory, advisor_user)

    payload = RiskAssessmentCreate(
        q_income_points=4,
        q_obligations_points=4,
        q_savings_points=12,
        q_wealth_points=12,
        investment_horizon_label="Mehr als 12 Jahre",
        investment_horizon_years=15,
        q_investment_goal_points=4,
        q_risk_preference_points=4,
        q_risk_behavior_points=4,
        answers=[],
    )

    with session_factory() as session:
        create_risk_assessment(
            mandate_id=mandate_id,
            body=payload,
            db=session,
            current_user=advisor_user,
        )
        session.add(
            WealthPosition(
                id="depot-delete-carry-1",
                client_id=client_id,
                label="Depot Delete Carry",
                position_type="Depot",
                assignment="BeratungsvermÃ¶gen",
                current_value_rappen=80000000,
                currency="CHF",
                alloc_equities_bps=6500,
                alloc_bonds_bps=2000,
                alloc_real_estate_bps=500,
                alloc_liquidity_bps=500,
                alloc_alternatives_bps=500,
                is_active=1,
                created_at="2026-03-27T00:00:00.000Z",
                updated_at="2026-03-27T00:00:00.000Z",
            )
        )
        session.commit()
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        allocation = generate_target_allocation(
            db=session,
            mandate=mandate,
            user_id=advisor_user.id,
            preferences={"policy": {}, "tilts": {}, "product": {}, "limits": {}, "geo": {}, "assetClasses": {}},
        )
        first_run = generate_recommendation_run(
            db=session,
            mandate=mandate,
            user_id=advisor_user.id,
            preferences={"policy": {}, "tilts": {}, "product": {}, "limits": {}, "geo": {}, "assetClasses": {}},
            target_allocation_id=allocation["target_allocation"].id,
        )
        first_position = first_run["positions"][0]
        session.add(
            RecommendationHolding(
                id="holding-delete-carry-1",
                run_id=first_run["run"].id,
                recommendation_position_id=first_position["id"],
                product_id=first_position["product_id"],
                depot_bank="UBS AG Zurich",
                custody_account_number="DEL-1",
                as_of_date=date.today().isoformat(),
                units_milli=5000,
                avg_cost_price_rappen=99500,
                source="manual",
                created_at="2026-03-27T00:00:00.000Z",
                updated_at="2026-03-27T00:00:00.000Z",
            )
        )
        session.commit()

        second_run = generate_recommendation_run(
            db=session,
            mandate=mandate,
            user_id=advisor_user.id,
            preferences={"policy": {}, "tilts": {}, "product": {}, "limits": {}, "geo": {}, "assetClasses": {}},
            target_allocation_id=allocation["target_allocation"].id,
        )
        second_position = second_run["positions"][0]
        carried = session.query(RecommendationHolding).filter(
            RecommendationHolding.run_id == second_run["run"].id,
            RecommendationHolding.recommendation_position_id == second_position["id"],
            RecommendationHolding.deleted_at.is_(None),
        ).first()
        assert carried is not None
        carried.deleted_at = "2026-03-28T10:00:00.000Z"
        carried.updated_at = carried.deleted_at
        session.commit()

        third_run = generate_recommendation_run(
            db=session,
            mandate=mandate,
            user_id=advisor_user.id,
            preferences={"policy": {}, "tilts": {}, "product": {}, "limits": {}, "geo": {}, "assetClasses": {}},
            target_allocation_id=allocation["target_allocation"].id,
        )
        hydrated = build_recommendation_payload_from_run(
            db=session,
            mandate=mandate,
            run=third_run["run"],
            user_id=advisor_user.id,
            preferences=None,
        )

    if hydrated["live_rebalancing"] is not None:
        assert hydrated["live_rebalancing"]["holding_positions_count"] == 0
    assert all(not item["holding_present"] for item in hydrated["positions"])


def test_review_engine_emits_market_data_trigger_for_missing_prices(session_factory, advisor_user):
    client_id, mandate_id = seed_client_and_mandate(session_factory, advisor_user)

    payload = RiskAssessmentCreate(
        q_income_points=4,
        q_obligations_points=4,
        q_savings_points=12,
        q_wealth_points=12,
        investment_horizon_label="Mehr als 12 Jahre",
        investment_horizon_years=15,
        q_investment_goal_points=4,
        q_risk_preference_points=4,
        q_risk_behavior_points=4,
        answers=[],
    )

    with session_factory() as session:
        create_risk_assessment(
            mandate_id=mandate_id,
            body=payload,
            db=session,
            current_user=advisor_user,
        )
        session.add(
            WealthPosition(
                id="depot-market-trigger",
                client_id=client_id,
                label="Depot Trigger",
                position_type="Depot",
                assignment="Beratungsvermögen",
                current_value_rappen=90000000,
                currency="CHF",
                alloc_equities_bps=6000,
                alloc_bonds_bps=2500,
                alloc_real_estate_bps=500,
                alloc_liquidity_bps=500,
                alloc_alternatives_bps=500,
                is_active=1,
                created_at="2026-03-27T00:00:00.000Z",
                updated_at="2026-03-27T00:00:00.000Z",
            )
        )
        session.commit()
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        allocation = generate_target_allocation(
            db=session,
            mandate=mandate,
            user_id=advisor_user.id,
            preferences=None,
        )
        session.commit()
        generate_recommendation_run(
            db=session,
            mandate=mandate,
            user_id=advisor_user.id,
            preferences=None,
            target_allocation_id=allocation["target_allocation"].id,
            depot_bank="UBS AG Zürich",
        )
        triggers = refresh_system_review_triggers(session, mandate, advisor_user.id)

    market_trigger = next((trigger for trigger in triggers if trigger.trigger_name == SYSTEM_TRIGGER_MARKET_DATA), None)
    assert market_trigger is not None
    assert market_trigger.status == "Ausgelöst"
    assert "ohne Preis" in str(market_trigger.triggered_value or "")


def test_advisory_log_rejects_non_schema_decision_values():
    with pytest.raises(ValidationError):
        AdvisoryLogCreate(
            entry_type="Sonstiges",
            title="Smoke Log",
            decision="Umschichtung",
        )


def test_advisory_log_accepts_schema_allowed_decision_value(session_factory, advisor_user):
    _, mandate_id = seed_client_and_mandate(session_factory, advisor_user)

    payload = AdvisoryLogCreate(
        entry_type="Sonstiges",
        title="Smoke Log",
        decision="Strategie angepasst",
        description="Runtime contract test",
        entry_date="2026-03-27",
    )

    with session_factory() as session:
        result = create_advisory_log_entry(
            mandate_id=mandate_id,
            body=payload,
            db=session,
            current_user=advisor_user,
        )

    assert result.mandate_id == mandate_id
    assert result.decision == "Strategie angepasst"


def _obsolete_create_trigger_normalizes_review_frequency_aliases(session_factory, advisor_user):
    _, mandate_id = seed_client_and_mandate(session_factory, advisor_user)

    with session_factory() as session:
        result = create_trigger(
            mandate_id=mandate_id,
            body=ReviewTriggerCreate(
                trigger_type="Zeit",
                trigger_name="Jahres-Review Alias",
                frequency="12 Monate",
                next_due_at="2027-03-27",
            ),
            db=session,
            current_user=advisor_user,
        )

    assert result.frequency == "jährlich"


def test_create_trigger_normalizes_review_frequency_aliases_v2(session_factory, advisor_user):
    _, mandate_id = seed_client_and_mandate(session_factory, advisor_user)

    with session_factory() as session:
        result = create_trigger(
            mandate_id=mandate_id,
            body=ReviewTriggerCreate(
                trigger_type="Zeit",
                trigger_name="Jahres-Review Alias",
                frequency="12 Monate",
                next_due_at="2027-03-27",
            ),
            db=session,
            current_user=advisor_user,
        )

    assert result.frequency == "jährlich"


def test_refresh_system_review_triggers_creates_review_and_goal_alerts(session_factory, advisor_user):
    client_id, mandate_id = seed_client_and_mandate(session_factory, advisor_user)

    payload = RiskAssessmentCreate(
        q_income_points=2,
        q_obligations_points=2,
        q_savings_points=4,
        q_wealth_points=4,
        investment_horizon_label="4 bis 5 Jahre",
        investment_horizon_years=5,
        q_investment_goal_points=2,
        q_risk_preference_points=2,
        q_risk_behavior_points=2,
        answers=[],
    )

    with session_factory() as session:
        create_risk_assessment(
            mandate_id=mandate_id,
            body=payload,
            db=session,
            current_user=advisor_user,
        )
        session.add(
            WealthPosition(
                id="depot-system-1",
                client_id=client_id,
                label="Depot Hauptbank",
                position_type="Depot",
                assignment="Beratungsvermögen",
                current_value_rappen=30000000,
                currency="CHF",
                alloc_equities_bps=5000,
                alloc_bonds_bps=3000,
                alloc_real_estate_bps=0,
                alloc_liquidity_bps=2000,
                alloc_alternatives_bps=0,
                is_active=1,
                created_at="2026-03-27T00:00:00.000Z",
                updated_at="2026-03-27T00:00:00.000Z",
            )
        )
        session.add(
            Goal(
                id="goal-risk-1",
                mandate_id=mandate_id,
                client_id=client_id,
                goal_family="Vermoegen",
                goal_type="Vermögensziel",
                label="Frühpensionierung",
                rank=1,
                goal_scope="Gesamtvermögen",
                value_mode="nominal",
                target_wealth_rappen=150000000,
                horizon_years=3,
                hardness="Hart",
                is_active=1,
                created_at="2026-03-27T00:00:00.000Z",
                updated_at="2026-03-27T00:00:00.000Z",
            )
        )
        session.commit()
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        generate_target_allocation(
            db=session,
            mandate=mandate,
            user_id=advisor_user.id,
            preferences={"policy": {}, "tilts": {}, "product": {}, "limits": {}, "geo": {}, "assetClasses": {}},
        )
        refresh_system_review_triggers(session, mandate, advisor_user.id)
        session.commit()
        triggers = session.query(ReviewTrigger).filter(
            ReviewTrigger.mandate_id == mandate_id,
            ReviewTrigger.is_system == 1,
        ).all()

    names = {trigger.trigger_name for trigger in triggers}
    assert SYSTEM_TRIGGER_REVIEW in names
    assert SYSTEM_TRIGGER_GOALS in names
    review_trigger = next(trigger for trigger in triggers if trigger.trigger_name == SYSTEM_TRIGGER_REVIEW)
    assert review_trigger.frequency == "jährlich"
    goal_trigger = next(trigger for trigger in triggers if trigger.trigger_name == SYSTEM_TRIGGER_GOALS)
    assert goal_trigger.status != "Erledigt"
    assert "Fr" in (goal_trigger.triggered_value or "")


def test_refresh_system_review_triggers_resolves_drift_when_portfolio_returns_inside_bands(session_factory, advisor_user):
    client_id, mandate_id = seed_client_and_mandate(session_factory, advisor_user)

    payload = RiskAssessmentCreate(
        q_income_points=4,
        q_obligations_points=4,
        q_savings_points=12,
        q_wealth_points=12,
        investment_horizon_label="Mehr als 12 Jahre",
        investment_horizon_years=15,
        q_investment_goal_points=4,
        q_risk_preference_points=4,
        q_risk_behavior_points=4,
        answers=[],
    )

    with session_factory() as session:
        create_risk_assessment(
            mandate_id=mandate_id,
            body=payload,
            db=session,
            current_user=advisor_user,
        )
        session.add(
            WealthPosition(
                id="depot-drift-1",
                client_id=client_id,
                label="Depot Drift",
                position_type="Depot",
                assignment="Beratungsvermögen",
                current_value_rappen=80000000,
                currency="CHF",
                alloc_equities_bps=10000,
                alloc_bonds_bps=0,
                alloc_real_estate_bps=0,
                alloc_liquidity_bps=0,
                alloc_alternatives_bps=0,
                is_active=1,
                created_at="2026-03-27T00:00:00.000Z",
                updated_at="2026-03-27T00:00:00.000Z",
            )
        )
        session.commit()
        mandate = session.query(Mandate).filter(Mandate.id == mandate_id).one()
        allocation_result = generate_target_allocation(
            db=session,
            mandate=mandate,
            user_id=advisor_user.id,
            preferences={"policy": {}, "tilts": {}, "product": {}, "limits": {}, "geo": {}, "assetClasses": {}},
        )
        refresh_system_review_triggers(session, mandate, advisor_user.id)
        session.flush()
        drift_trigger = session.query(ReviewTrigger).filter(
            ReviewTrigger.mandate_id == mandate_id,
            ReviewTrigger.trigger_name == SYSTEM_TRIGGER_DRIFT,
            ReviewTrigger.is_system == 1,
        ).one()
        assert drift_trigger.status != "Erledigt"
        position = session.query(WealthPosition).filter(WealthPosition.id == "depot-drift-1").one()
        target = allocation_result["target_allocation"]
        position.alloc_equities_bps = int(target.target_equities_bps)
        position.alloc_bonds_bps = int(target.target_bonds_bps)
        position.alloc_real_estate_bps = int(target.target_real_estate_bps)
        position.alloc_liquidity_bps = int(target.target_liquidity_bps)
        position.alloc_alternatives_bps = int(target.target_alternatives_bps)
        session.flush()
        refresh_system_review_triggers(session, mandate, advisor_user.id)
        session.commit()
        resolved_trigger = session.query(ReviewTrigger).filter(
            ReviewTrigger.mandate_id == mandate_id,
            ReviewTrigger.trigger_name == SYSTEM_TRIGGER_DRIFT,
            ReviewTrigger.is_system == 1,
        ).one()

    assert resolved_trigger.status == "Erledigt"


def test_access_helpers_block_foreign_client_and_mandate(session_factory, advisor_user, other_advisor_user):
    seed_client_and_mandate(session_factory, advisor_user)
    foreign_client_id, foreign_mandate_id = seed_foreign_client_and_mandate(session_factory, other_advisor_user)

    with session_factory() as session:
        with pytest.raises(HTTPException) as client_exc:
            get_client_for_user_or_404(foreign_client_id, session, advisor_user)
        with pytest.raises(HTTPException) as mandate_exc:
            get_mandate_for_user_or_404(foreign_mandate_id, session, advisor_user)

    assert client_exc.value.status_code == 404
    assert mandate_exc.value.status_code == 404


def test_dashboard_summary_and_active_triggers_are_scoped_to_advisor(session_factory, advisor_user, other_advisor_user):
    client_id, mandate_id = seed_client_and_mandate(session_factory, advisor_user)
    foreign_client_id, foreign_mandate_id = seed_foreign_client_and_mandate(session_factory, other_advisor_user)

    with session_factory() as session:
        session.execute(
            text(
                """
                CREATE VIEW v_client_wealth_summary AS
                SELECT
                    c.id AS client_id,
                    TRIM(COALESCE(c.first_name, '') || ' ' || COALESCE(c.last_name, '')) AS client_name,
                    10000 AS gross_wealth_rappen,
                    0 AS liabilities_rappen,
                    10000 AS net_worth_rappen,
                    10000 AS advisory_wealth_rappen
                FROM clients c
                WHERE c.deleted_at IS NULL
                """
            )
        )
        session.execute(
            text(
                """
                CREATE VIEW v_active_triggers AS
                SELECT
                    rt.id AS id,
                    rt.mandate_id AS mandate_id,
                    rt.trigger_name AS trigger_name,
                    rt.status AS status,
                    TRIM(COALESCE(c.first_name, '') || ' ' || COALESCE(c.last_name, '')) AS client_name,
                    m.mandate_number AS mandate_number
                FROM review_triggers rt
                JOIN mandates m ON m.id = rt.mandate_id
                JOIN clients c ON c.id = m.client_id
                WHERE rt.deleted_at IS NULL
                """
            )
        )
        session.add(
            ReviewTrigger(
                id="trigger-own-1",
                mandate_id=mandate_id,
                trigger_type="Zeit",
                trigger_name="Eigen",
                status="AusgelÃ¶st",
                is_system=0,
                calendar_exported=0,
                created_at="2026-03-27T00:00:00.000Z",
                updated_at="2026-03-27T00:00:00.000Z",
            )
        )
        session.add(
            ReviewTrigger(
                id="trigger-foreign-1",
                mandate_id=foreign_mandate_id,
                trigger_type="Zeit",
                trigger_name="Fremd",
                status="AusgelÃ¶st",
                is_system=0,
                calendar_exported=0,
                created_at="2026-03-27T00:00:00.000Z",
                updated_at="2026-03-27T00:00:00.000Z",
            )
        )
        session.commit()

        summary = dashboard_summary(db=session, current_user=advisor_user)
        triggers = active_triggers(db=session, current_user=advisor_user)

    assert [item["client_id"] for item in summary["clients"]] == [client_id]
    assert summary["active_alerts"] == 1
    assert [item["mandate_id"] for item in triggers] == [mandate_id]
    assert foreign_client_id not in [item["client_id"] for item in summary["clients"]]
    assert foreign_mandate_id not in [item["mandate_id"] for item in triggers]


def test_get_adviser_registration_only_allows_self_or_admin(session_factory, advisor_user, other_advisor_user):
    seed_client_and_mandate(session_factory, advisor_user)
    seed_foreign_client_and_mandate(session_factory, other_advisor_user)

    with session_factory() as session:
        session.add(
            AdviserRegistration(
                id="reg-foreign-1",
                user_id=other_advisor_user.id,
                register_body="FINMA Beraterregister",
                register_status="Aktiv",
                created_at="2026-03-27T00:00:00.000Z",
                updated_at="2026-03-27T00:00:00.000Z",
            )
        )
        session.commit()

        with pytest.raises(HTTPException) as exc:
            get_adviser_registration(
                user_id=other_advisor_user.id,
                db=session,
                current_user=advisor_user,
            )

    assert exc.value.status_code == 403
