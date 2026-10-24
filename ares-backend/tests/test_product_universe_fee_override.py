"""2026-07-27 (Fonds-Kuratierung): eine Verwaltung kann fuer ein Produkt eine
eigene, ausgehandelte Gebuehr hinterlegen (ProductUniverseEntry.override_ter_bps).
build_cost_disclosure muss diese live (kein Snapshot) statt product.ter_bps
verwenden -- NUR fuer den betroffenen Tenant, das globale Produkt bleibt
unveraendert.
"""
from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base
from main import app  # noqa: F401
from models.allocation import OptimizerPolicy, TargetAllocation
from models.clients import Client
from models.mandates import Mandate
from models.review import Product, ProductUniverseEntry, RecommendationPosition, RecommendationRun
from models.tenant import Tenant
from models.users import User
from services.cost_disclosure import build_cost_disclosure


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'product_universe_fee.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _seed(
    SF,
    *,
    mandate_tenant_id: str | None,
    mandate_jurisdiction: str | None,
    product_ter_bps: int,
    override_entries: list[dict] | None = None,
):
    now = _now()
    with SF() as s:
        for tid in {mandate_tenant_id, *[e["tenant_id"] for e in (override_entries or [])]}:
            if tid and s.get(Tenant, tid) is None:
                s.add(Tenant(
                    id=tid, display_name=tid, slug=tid,
                    hosting_tier="tier2", license_status="active",
                    is_active=1, created_at=now, updated_at=now,
                ))
        s.add(User(
            id="advisor-puf", username="advisor-puf", password_hash="h",
            full_name="Advisor", role="advisor", is_active=1,
            tenant_id=mandate_tenant_id, created_at=now, updated_at=now,
        ))
        s.add(Client(
            id="client-puf", client_number="C-PUF", first_name="T", last_name="X",
            advisor_id="advisor-puf", tenant_id=mandate_tenant_id,
            created_at=now, updated_at=now,
        ))
        s.add(Mandate(
            id="mandate-puf", client_id="client-puf", tenant_id=mandate_tenant_id,
            jurisdiction=mandate_jurisdiction, mandate_number="M-PUF",
            mandate_type="Anlageberatung", opened_at=now,
            created_at=now, updated_at=now,
        ))
        s.add(Product(
            id="prod-puf", product_name="Fonds PUF", asset_class="Aktien",
            product_type="ETF", currency="CHF", is_active=1, ter_bps=product_ter_bps,
            created_at=now, updated_at=now,
        ))
        policy = OptimizerPolicy(
            id="pol-puf", policy_name="default", is_current=1, version=1,
            valid_from=now, created_by="advisor-puf", created_at=now, updated_at=now,
        )
        s.add(policy)
        ta = TargetAllocation(
            id="ta-puf", mandate_id="mandate-puf", is_current=1,
            band_equities_min_bps=0, band_equities_max_bps=10000,
            band_bonds_min_bps=0, band_bonds_max_bps=10000,
            band_real_estate_min_bps=0, band_real_estate_max_bps=10000,
            band_alternatives_min_bps=0, band_alternatives_max_bps=10000,
            band_liquidity_min_bps=0, band_liquidity_max_bps=10000,
            policy_id="pol-puf", set_by="advisor-puf", set_at=now,
            advisory_wealth_at_generation_rappen=100_000_000,
            created_at=now, updated_at=now,
        )
        s.add(ta)
        run = RecommendationRun(
            id="run-puf", mandate_id="mandate-puf", client_id="client-puf",
            target_allocation_id="ta-puf", policy_id="pol-puf", run_type="initial",
            fee_assumptions_json=json.dumps({}), created_by="advisor-puf",
            created_at=now, updated_at=now,
        )
        s.add(run)
        s.add(RecommendationPosition(
            id="pos-puf", run_id="run-puf", product_id="prod-puf",
            target_weight_bps=10000, target_amount_rappen=100_000_000,
            created_at=now, updated_at=now,
        ))
        for i, entry in enumerate(override_entries or []):
            s.add(ProductUniverseEntry(
                id=f"pue-{i}", tenant_id=entry["tenant_id"],
                jurisdiction=entry["jurisdiction"], product_id="prod-puf",
                override_ter_bps=entry.get("override_ter_bps"),
                created_by="advisor-puf", created_at=now, updated_at=now,
                deleted_at=entry.get("deleted_at"),
            ))
        s.commit()


def _mandate(SF):
    with SF() as s:
        return s.query(Mandate).filter(Mandate.id == "mandate-puf").first()


def _ter_bps_of_only_position(payload):
    items = [i for i in payload["cost_items"] if i["category"] == "Produktkosten"]
    assert len(items) == 1
    return items[0]


def test_no_override_entries_uses_product_ter_bps(session_factory):
    _seed(session_factory, mandate_tenant_id="firm-puf", mandate_jurisdiction="CH", product_ter_bps=20)
    with session_factory() as db:
        mandate = _mandate(session_factory)
        payload = build_cost_disclosure(db, mandate)
    item = _ter_bps_of_only_position(payload)
    assert item["amount_rappen"] == round(100_000_000 * 20 / 10000)


def test_override_replaces_ter_bps_for_matching_tenant_and_jurisdiction(session_factory):
    _seed(
        session_factory, mandate_tenant_id="firm-puf", mandate_jurisdiction="CH", product_ter_bps=20,
        override_entries=[{"tenant_id": "firm-puf", "jurisdiction": "CH", "override_ter_bps": 5}],
    )
    with session_factory() as db:
        mandate = _mandate(session_factory)
        payload = build_cost_disclosure(db, mandate)
    item = _ter_bps_of_only_position(payload)
    assert item["amount_rappen"] == round(100_000_000 * 5 / 10000)


def test_override_for_other_tenant_does_not_leak(session_factory):
    _seed(
        session_factory, mandate_tenant_id="firm-puf", mandate_jurisdiction="CH", product_ter_bps=20,
        override_entries=[{"tenant_id": "firm-other", "jurisdiction": "CH", "override_ter_bps": 5}],
    )
    with session_factory() as db:
        mandate = _mandate(session_factory)
        payload = build_cost_disclosure(db, mandate)
    item = _ter_bps_of_only_position(payload)
    assert item["amount_rappen"] == round(100_000_000 * 20 / 10000)


def test_override_for_other_jurisdiction_does_not_apply(session_factory):
    _seed(
        session_factory, mandate_tenant_id="firm-puf", mandate_jurisdiction="CH", product_ter_bps=20,
        override_entries=[{"tenant_id": "firm-puf", "jurisdiction": "DE", "override_ter_bps": 5}],
    )
    with session_factory() as db:
        mandate = _mandate(session_factory)
        payload = build_cost_disclosure(db, mandate)
    item = _ter_bps_of_only_position(payload)
    assert item["amount_rappen"] == round(100_000_000 * 20 / 10000)


def test_null_jurisdiction_falls_back_to_ch(session_factory):
    """Mandate.jurisdiction=NULL (Bestandsmandat) -> Code interpretiert als 'CH'."""
    _seed(
        session_factory, mandate_tenant_id="firm-puf", mandate_jurisdiction=None, product_ter_bps=20,
        override_entries=[{"tenant_id": "firm-puf", "jurisdiction": "CH", "override_ter_bps": 5}],
    )
    with session_factory() as db:
        mandate = _mandate(session_factory)
        payload = build_cost_disclosure(db, mandate)
    item = _ter_bps_of_only_position(payload)
    assert item["amount_rappen"] == round(100_000_000 * 5 / 10000)


def test_soft_deleted_override_entry_is_ignored(session_factory):
    _seed(
        session_factory, mandate_tenant_id="firm-puf", mandate_jurisdiction="CH", product_ter_bps=20,
        override_entries=[{
            "tenant_id": "firm-puf", "jurisdiction": "CH", "override_ter_bps": 5,
            "deleted_at": _now(),
        }],
    )
    with session_factory() as db:
        mandate = _mandate(session_factory)
        payload = build_cost_disclosure(db, mandate)
    item = _ter_bps_of_only_position(payload)
    assert item["amount_rappen"] == round(100_000_000 * 20 / 10000)


def test_entry_without_override_value_does_not_change_ter_bps(session_factory):
    """Ein Eintrag existiert (z.B. nur fuer die Fonds-Filterung), aber ohne
    override_ter_bps gesetzt -> product.ter_bps bleibt massgebend."""
    _seed(
        session_factory, mandate_tenant_id="firm-puf", mandate_jurisdiction="CH", product_ter_bps=20,
        override_entries=[{"tenant_id": "firm-puf", "jurisdiction": "CH", "override_ter_bps": None}],
    )
    with session_factory() as db:
        mandate = _mandate(session_factory)
        payload = build_cost_disclosure(db, mandate)
    item = _ter_bps_of_only_position(payload)
    assert item["amount_rappen"] == round(100_000_000 * 20 / 10000)


def test_mandate_without_tenant_id_uses_product_ter_bps(session_factory):
    """Bestandsmandate ohne tenant_id (Backwards-Compat vor Sprint T1) --
    Override-Lookup loest auf DEFAULT_TENANT_ID ('main') auf; ohne Eintraege
    fuer 'main' bleibt das Verhalten unveraendert, kein Crash."""
    _seed(session_factory, mandate_tenant_id=None, mandate_jurisdiction="CH", product_ter_bps=20)
    with session_factory() as db:
        mandate = _mandate(session_factory)
        payload = build_cost_disclosure(db, mandate)
    item = _ter_bps_of_only_position(payload)
    assert item["amount_rappen"] == round(100_000_000 * 20 / 10000)


def test_null_tenant_id_falls_back_to_main_tenant_override(session_factory):
    """2026-07-29 (UI-Verifikation): ein Admin-User/Mandat ohne tenant_id
    (z.B. frisch gebootstrapped, vor dem naechsten Boot-Backfill) MUSS
    trotzdem von Eintraegen profitieren, die unter DEFAULT_TENANT_ID ('main')
    angelegt wurden -- sonst waere das Feature fuer genau den haeufigsten
    Single-Tenant-Deployment-Fall (Tier 1) unbenutzbar."""
    _seed(
        session_factory, mandate_tenant_id=None, mandate_jurisdiction="CH", product_ter_bps=20,
        override_entries=[{"tenant_id": "main", "jurisdiction": "CH", "override_ter_bps": 5}],
    )
    with session_factory() as db:
        mandate = _mandate(session_factory)
        payload = build_cost_disclosure(db, mandate)
    item = _ter_bps_of_only_position(payload)
    assert item["amount_rappen"] == round(100_000_000 * 5 / 10000)
