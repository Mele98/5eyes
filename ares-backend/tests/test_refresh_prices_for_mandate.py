"""Sprint U-P11b (2026-05-22): Tests für per-mandate Live-Preise-Refresh.

Verifiziert mit gemocktem fetch_latest_prices_batch:
- _product_ids_for_mandate liefert nur Products des letzten Runs
- refresh_prices_for_mandate filtert auf Mandate-Scope
- Summary-Counts: processed/inserted/updated/unchanged/failed
- PriceHistory wird tatsächlich geschrieben
- Idempotenz: 2. Aufruf -> unchanged
- Defensive: kein RecommendationRun -> warning, kein Crash
- Defensive: Failure bei einem Produkt killt andere nicht
"""
from __future__ import annotations

import datetime
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, configure_mappers

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from database import Base
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
configure_mappers()

from models.allocation import OptimizerPolicy
from models.clients import Client
from models.mandates import Mandate
from models.review import (
    PriceHistory,
    Product,
    RecommendationPosition,
    RecommendationRun,
)
from models.users import User


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'refresh_prices.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _seed_mandate_with_two_products(session_factory) -> tuple[str, list[str]]:
    """Mandat + 2 Products in RecommendationRun. Returns (mandate_id, [product_ids])."""
    suffix = str(uuid.uuid4())[:6]
    advisor_id = f"adv-{suffix}"
    cid = str(uuid.uuid4())
    mid = str(uuid.uuid4())
    pid = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    prod_a_id = str(uuid.uuid4())
    prod_b_id = str(uuid.uuid4())
    prod_unused_id = str(uuid.uuid4())  # nicht im Run -> wird NICHT refreshed
    now = _now()
    with session_factory() as s:
        s.add(User(id=advisor_id, username=f"adv-{suffix}", password_hash="h",
                   full_name="Adv P", role="advisor", is_active=1,
                   created_at=now, updated_at=now))
        s.add(Client(id=cid, client_number=f"C-{cid[:6]}",
                     first_name="Live", last_name="Prices",
                     advisor_id=advisor_id, created_at=now, updated_at=now))
        s.add(Mandate(id=mid, client_id=cid, mandate_number=f"M-{mid[:6]}",
                      mandate_type="Anlageberatung", opened_at=now,
                      created_at=now, updated_at=now))
        s.add(OptimizerPolicy(id=pid, policy_name="T", version=1, is_current=1,
                              valid_from=now, optimizer_engine="goal_based_v1",
                              max_real_estate_bps=2000, max_alternatives_bps=1000,
                              min_liquidity_bps=0, created_by=advisor_id,
                              created_at=now, updated_at=now))
        for prod_id, name, isin in [
            (prod_a_id, "Test World ETF", "IE00B4L5Y983"),
            (prod_b_id, "Test Bond ETF", "IE00B3F81409"),
            (prod_unused_id, "Unused ETF", "IE00B3DKXQ41"),
        ]:
            s.add(Product(
                id=prod_id, isin=isin, product_name=name,
                product_type="ETF", asset_class="Aktien", currency="USD",
                is_active=1, created_at=now, updated_at=now,
            ))
        s.add(RecommendationRun(
            id=run_id, mandate_id=mid, client_id=cid,
            policy_id=pid, run_type="initial",
            created_by=advisor_id,
            created_at=now, updated_at=now,
        ))
        # Nur prod_a + prod_b im Run, prod_unused nicht
        for prod_id, weight in [(prod_a_id, 6000), (prod_b_id, 4000)]:
            s.add(RecommendationPosition(
                id=str(uuid.uuid4()), run_id=run_id, product_id=prod_id,
                target_weight_bps=weight,
                created_at=now, updated_at=now,
            ))
        s.commit()
    return mid, [prod_a_id, prod_b_id, prod_unused_id]


# ============================================================================
# _product_ids_for_mandate
# ============================================================================


def test_product_ids_for_mandate_returns_only_run_products(session_factory):
    from price_updater import _product_ids_for_mandate
    mid, [pa, pb, pu] = _seed_mandate_with_two_products(session_factory)
    with session_factory() as s:
        ids = _product_ids_for_mandate(s, mid)
    assert set(ids) == {pa, pb}
    assert pu not in ids


def test_product_ids_for_mandate_empty_when_no_run(session_factory):
    """Mandat ohne RecommendationRun -> leere Liste, kein Crash."""
    from price_updater import _product_ids_for_mandate
    suffix = str(uuid.uuid4())[:6]
    advisor_id = f"adv-{suffix}"
    cid = str(uuid.uuid4())
    mid = str(uuid.uuid4())
    now = _now()
    with session_factory() as s:
        s.add(User(id=advisor_id, username=f"adv-{suffix}", password_hash="h",
                   full_name="Adv", role="advisor", is_active=1,
                   created_at=now, updated_at=now))
        s.add(Client(id=cid, client_number=f"C-{cid[:6]}",
                     first_name="NoRun", last_name="X",
                     advisor_id=advisor_id, created_at=now, updated_at=now))
        s.add(Mandate(id=mid, client_id=cid, mandate_number=f"M-{mid[:6]}",
                      mandate_type="Anlageberatung", opened_at=now,
                      created_at=now, updated_at=now))
        s.commit()
        ids = _product_ids_for_mandate(s, mid)
    assert ids == []


# ============================================================================
# refresh_prices_for_mandate — End-to-End mit gemocktem fetch_batch
# ============================================================================


def _mock_batch_for_products(products):
    """Liefert ein dict {product_id: PricePoint} mit deterministischen Preisen."""
    from price_updater import PricePoint
    today = datetime.date.today().isoformat()
    return {
        p.id: PricePoint(price_date=today, price_rappen=10000 + i * 100,
                         currency=p.currency or "USD", source="mock")
        for i, p in enumerate(products)
    }, {}


def test_refresh_prices_for_mandate_inserts_new_history(session_factory):
    from price_updater import refresh_prices_for_mandate
    mid, [pa, pb, pu] = _seed_mandate_with_two_products(session_factory)

    def fake_fetch(products):
        return _mock_batch_for_products(products)

    with patch("price_updater.fetch_latest_prices_batch", side_effect=fake_fetch):
        with session_factory() as s:
            summary = refresh_prices_for_mandate(s, mid)
            histories = s.query(PriceHistory).all()
            history_pids = {h.product_id for h in histories}

    assert summary["mandate_id"] == mid
    assert summary["processed"] == 2  # nur die im Run
    assert summary["inserted"] == 2
    assert summary["updated"] == 0
    assert summary["failed"] == 0
    assert history_pids == {pa, pb}
    assert pu not in history_pids
    assert "finished_at" in summary


def test_refresh_prices_for_mandate_idempotent_second_call_unchanged(session_factory):
    from price_updater import refresh_prices_for_mandate
    mid, [pa, pb, _] = _seed_mandate_with_two_products(session_factory)

    def fake_fetch(products):
        return _mock_batch_for_products(products)

    with patch("price_updater.fetch_latest_prices_batch", side_effect=fake_fetch):
        with session_factory() as s:
            refresh_prices_for_mandate(s, mid)
            summary2 = refresh_prices_for_mandate(s, mid)

    # Beim 2. Call: gleiche price_date + source + price -> "unchanged"
    assert summary2["inserted"] == 0
    assert summary2["unchanged"] == 2
    assert summary2["failed"] == 0


def test_refresh_prices_for_mandate_no_run_returns_warning(session_factory):
    from price_updater import refresh_prices_for_mandate
    suffix = str(uuid.uuid4())[:6]
    advisor_id = f"adv-{suffix}"
    cid = str(uuid.uuid4())
    mid = str(uuid.uuid4())
    now = _now()
    with session_factory() as s:
        s.add(User(id=advisor_id, username=f"adv-{suffix}", password_hash="h",
                   full_name="Adv", role="advisor", is_active=1,
                   created_at=now, updated_at=now))
        s.add(Client(id=cid, client_number=f"C-{cid[:6]}",
                     first_name="No", last_name="Run",
                     advisor_id=advisor_id, created_at=now, updated_at=now))
        s.add(Mandate(id=mid, client_id=cid, mandate_number=f"M-{mid[:6]}",
                      mandate_type="Anlageberatung", opened_at=now,
                      created_at=now, updated_at=now))
        s.commit()
        summary = refresh_prices_for_mandate(s, mid)

    assert summary["processed"] == 0
    assert summary["inserted"] == 0
    assert summary["warnings"]
    assert "Recommendation-Run" in summary["warnings"][0]


def test_refresh_prices_for_mandate_partial_failure_records_failure(session_factory):
    """Ein Produkt failed (kein Price-Point) -> failed=1, andere weiter."""
    from price_updater import refresh_prices_for_mandate, PricePoint
    mid, [pa, pb, _] = _seed_mandate_with_two_products(session_factory)
    today = datetime.date.today().isoformat()

    def fake_fetch(products):
        # Nur pa kriegt einen Preis, pb failed.
        points = {pa: PricePoint(price_date=today, price_rappen=10000,
                                 currency="USD", source="mock")}
        failures = {pb: {"lookup_symbol": "TEST_B", "lookup_mode": "isin",
                         "error": "mocked failure"}}
        return points, failures

    with patch("price_updater.fetch_latest_prices_batch", side_effect=fake_fetch):
        with session_factory() as s:
            summary = refresh_prices_for_mandate(s, mid)

    assert summary["processed"] == 2
    assert summary["inserted"] == 1
    assert summary["failed"] == 1
    assert any(f["product_id"] == pb for f in summary["failures"])
    assert any("mocked failure" in (f.get("error") or "") for f in summary["failures"])


def test_refresh_prices_for_mandate_returns_updated_when_price_changes(session_factory):
    from price_updater import refresh_prices_for_mandate, PricePoint
    mid, [pa, pb, _] = _seed_mandate_with_two_products(session_factory)
    today = datetime.date.today().isoformat()

    call_count = {"n": 0}
    def fake_fetch(products):
        call_count["n"] += 1
        # 1. Call: 10000 rappen für beide; 2. Call: 11000 für pa
        if call_count["n"] == 1:
            points = {p.id: PricePoint(price_date=today, price_rappen=10000,
                                       currency=p.currency or "USD", source="mock")
                      for p in products}
        else:
            points = {}
            for p in products:
                price = 11000 if p.id == pa else 10000
                points[p.id] = PricePoint(price_date=today, price_rappen=price,
                                          currency=p.currency or "USD", source="mock")
        return points, {}

    with patch("price_updater.fetch_latest_prices_batch", side_effect=fake_fetch):
        with session_factory() as s:
            refresh_prices_for_mandate(s, mid)
            summary2 = refresh_prices_for_mandate(s, mid)

    assert summary2["updated"] == 1  # pa hat neuen Preis
    assert summary2["unchanged"] == 1  # pb unverändert
