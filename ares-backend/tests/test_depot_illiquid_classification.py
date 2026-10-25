from __future__ import annotations

import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import configure_mappers, sessionmaker


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, tenant, users, wealth,
)

configure_mappers()

from models.allocation import OptimizerPolicy
from models.clients import Client
from models.mandates import Mandate
from models.review import Product, RecommendationPosition, RecommendationRun
from models.users import User
from services.depot_check import (
    _ILLIQUID_WARNING_THRESHOLD_BPS,
    _product_liquidity_tier,
    _wealth_position_liquidity_tier,
    compute_depot_check,
)


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'depot_illiquid.db'}",
        connect_args={"check_same_thread": False},
    )
    sf = sessionmaker(
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
        bind=engine,
    )
    Base.metadata.create_all(bind=engine)
    try:
        yield sf
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _now() -> str:
    return "2026-06-18T09:00:00.000Z"


def _seed_base(s):
    user = User(
        id="adv-illiquid",
        username="advisor-illiquid",
        password_hash="h",
        full_name="Advisor",
        role="advisor",
        is_active=1,
        created_at=_now(),
        updated_at=_now(),
    )
    client = Client(
        id="client-illiquid",
        client_number="C-ILLIQ",
        first_name="Test",
        last_name="Client",
        advisor_id=user.id,
        created_at=_now(),
        updated_at=_now(),
    )
    mandate = Mandate(
        id="mandate-illiquid",
        client_id=client.id,
        mandate_number="M-ILLIQ",
        mandate_type="Anlageberatung",
        opened_at=_now(),
        created_at=_now(),
        updated_at=_now(),
    )
    policy = OptimizerPolicy(
        id="policy-illiquid",
        policy_name="Policy",
        version=1,
        is_current=1,
        valid_from=_now(),
        optimizer_engine="goal_based_v1",
        created_by=user.id,
        created_at=_now(),
        updated_at=_now(),
    )
    run = RecommendationRun(
        id="run-illiquid",
        mandate_id=mandate.id,
        client_id=client.id,
        policy_id=policy.id,
        run_type="initial",
        result_status="Draft",
        created_by=user.id,
        created_at=_now(),
        updated_at=_now(),
    )
    s.add_all([user, client, mandate, policy, run])
    return mandate, run


def _product(
    s,
    *,
    product_type: str,
    asset_class: str,
    sub_asset_class: str,
    liquidity_tier: str | None = None,
) -> Product:
    prod = Product(
        id=str(uuid.uuid4()),
        isin=f"CH{uuid.uuid4().hex[:10].upper()}",
        product_name=sub_asset_class,
        provider="",
        product_type=product_type,
        asset_class=asset_class,
        sub_asset_class=sub_asset_class,
        currency="CHF",
        ter_bps=20,
        liquidity_tier=liquidity_tier,
        created_at=_now(),
        updated_at=_now(),
    )
    s.add(prod)
    return prod


def _position(s, *, run_id: str, product_id: str, amount: int) -> None:
    s.add(RecommendationPosition(
        id=str(uuid.uuid4()),
        run_id=run_id,
        product_id=product_id,
        target_weight_bps=0,
        target_amount_rappen=amount,
        current_amount_rappen=amount,
        created_at=_now(),
        updated_at=_now(),
    ))


def test_private_equity_and_direct_real_estate_are_illiquid() -> None:
    pe = SimpleNamespace(
        product_type="Fonds",
        asset_class="Alternative",
        sub_asset_class="Private Equity",
        product_name="Private Equity Sleeve",
        liquidity_tier="daily",
    )
    direct = SimpleNamespace(
        product_type="Direktimmobilien",
        asset_class="Immobilien",
        sub_asset_class="Direktimmobilien",
        product_name="Liegenschaft",
        liquidity_tier="daily",
    )

    assert _product_liquidity_tier(pe, "alternatives") == "illiquid"
    assert _product_liquidity_tier(direct, "real_estate") == "illiquid"


def test_gold_liquid_alts_real_estate_funds_and_reits_are_not_illiquid() -> None:
    cases = [
        (
            SimpleNamespace(
                product_type="ETF",
                asset_class="Alternative",
                sub_asset_class="Gold / Rohstoffe",
                product_name="Gold ETF",
                liquidity_tier="illiquid",
            ),
            "alternatives",
            "monthly",
        ),
        (
            SimpleNamespace(
                product_type="Fonds",
                asset_class="Alternative",
                sub_asset_class="Liquid Alternatives",
                product_name="Liquid Alternatives",
                liquidity_tier="illiquid",
            ),
            "alternatives",
            "monthly",
        ),
        (
            SimpleNamespace(
                product_type="Immobilienfonds",
                asset_class="Immobilien",
                sub_asset_class="Immobilienfonds",
                product_name="Immobilienfonds",
                liquidity_tier="illiquid",
            ),
            "real_estate",
            "weekly",
        ),
        (
            SimpleNamespace(
                product_type="REIT",
                asset_class="Immobilien",
                sub_asset_class="REIT",
                product_name="Listed REIT",
                liquidity_tier="illiquid",
            ),
            "real_estate",
            "weekly",
        ),
    ]

    for product, bucket, expected in cases:
        assert _product_liquidity_tier(product, bucket) == expected


def test_direct_real_estate_wealth_position_is_illiquid() -> None:
    wp = SimpleNamespace(
        position_type="Immobilien",
        asset_subtype="Direktimmobilien",
        label="Wohnliegenschaft",
        asset_liquidity="daily",
        property_address="Musterstrasse 1",
        property_zip_city="8000 Zurich",
        property_usage="Vermietet",
    )

    assert _wealth_position_liquidity_tier(wp, "real_estate") == "illiquid"


def test_depot_check_warning_counts_only_pe_and_direct_real_estate(session_factory) -> None:
    with session_factory() as s:
        mandate, run = _seed_base(s)
        pe = _product(
            s,
            product_type="Fonds",
            asset_class="Alternative",
            sub_asset_class="Private Equity",
        )
        direct = _product(
            s,
            product_type="Direktimmobilien",
            asset_class="Immobilien",
            sub_asset_class="Direktimmobilien",
        )
        gold = _product(
            s,
            product_type="ETF",
            asset_class="Alternative",
            sub_asset_class="Gold / Rohstoffe",
            liquidity_tier="illiquid",
        )
        real_estate_fund = _product(
            s,
            product_type="Immobilienfonds",
            asset_class="Immobilien",
            sub_asset_class="Immobilienfonds",
            liquidity_tier="illiquid",
        )
        _position(s, run_id=run.id, product_id=pe.id, amount=200_000_00)
        _position(s, run_id=run.id, product_id=direct.id, amount=200_000_00)
        _position(s, run_id=run.id, product_id=gold.id, amount=300_000_00)
        _position(s, run_id=run.id, product_id=real_estate_fund.id, amount=300_000_00)
        s.commit()

        result = compute_depot_check(s, mandate)

    assert result["liquidity_profile"]["illiquid_bps"] == 4000
    assert result["liquidity_profile"]["monthly_bps"] == 3000
    assert result["liquidity_profile"]["weekly_bps"] == 3000
    assert result["liquidity_profile"]["illiquid_bps"] > _ILLIQUID_WARNING_THRESHOLD_BPS
    assert any("Illiquider Anteil" in warning for warning in result["warnings"])


def test_empty_depot_keeps_liquidity_profile_at_zero(session_factory) -> None:
    with session_factory() as s:
        user = User(
            id="adv-empty",
            username="advisor-empty",
            password_hash="h",
            full_name="Advisor",
            role="advisor",
            is_active=1,
            created_at=_now(),
            updated_at=_now(),
        )
        client = Client(
            id="client-empty",
            client_number="C-EMPTY",
            first_name="Empty",
            last_name="Client",
            advisor_id=user.id,
            created_at=_now(),
            updated_at=_now(),
        )
        mandate = Mandate(
            id="mandate-empty",
            client_id=client.id,
            mandate_number="M-EMPTY",
            mandate_type="Anlageberatung",
            opened_at=_now(),
            created_at=_now(),
            updated_at=_now(),
        )
        s.add_all([user, client, mandate])
        s.commit()

        result = compute_depot_check(s, mandate)

    assert result["total_advisory_wealth_rappen"] == 0
    assert result["liquidity_profile"]["illiquid_bps"] == 0
    assert any("Beratungs" in warning for warning in result["warnings"])
