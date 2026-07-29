"""2026-07-27 (Fonds-Kuratierung): services.portfolio_engine._filter_products_by_universe
schraenkt den Produktkandidaten-Pool in generate_recommendation_run auf die
ProductUniverseEntry-Positivliste ein, WENN mindestens ein Eintrag fuer
(tenant_id, jurisdiction) existiert -- sonst bleibt der volle Katalog
unveraendert (Backwards-Compat fuer alle Bestandsmandate/CH).
"""
from __future__ import annotations

import datetime
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
from models.mandates import Mandate
from models.review import Product, ProductUniverseEntry
from services.portfolio_engine import _filter_products_by_universe


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'product_universe_filter.db'}",
        connect_args={"check_same_thread": False},
    )
    SF = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield SF
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _products(session_factory, *, count=3):
    now = _now()
    ids = [f"prod-{i}" for i in range(count)]
    with session_factory() as s:
        for pid in ids:
            s.add(Product(
                id=pid, product_name=pid, asset_class="Aktien",
                product_type="ETF", currency="CHF", is_active=1,
                created_at=now, updated_at=now,
            ))
        s.commit()
    return ids


def _mandate(*, tenant_id=None, jurisdiction=None):
    return Mandate(id="mdt-puf-filter", client_id="cli-x", tenant_id=tenant_id,
                   jurisdiction=jurisdiction, mandate_number="M-PUF-F",
                   mandate_type="Anlageberatung", opened_at=_now(),
                   created_at=_now(), updated_at=_now())


def test_no_tenant_id_returns_unfiltered(session_factory):
    ids = _products(session_factory)
    mandate = _mandate(tenant_id=None, jurisdiction="CH")
    with session_factory() as db:
        products = db.query(Product).filter(Product.id.in_(ids)).all()
        result = _filter_products_by_universe(db, mandate, products)
    assert {p.id for p in result} == set(ids)


def test_no_entries_for_tenant_returns_unfiltered(session_factory):
    ids = _products(session_factory)
    mandate = _mandate(tenant_id="firm-puf-filter", jurisdiction="CH")
    with session_factory() as db:
        products = db.query(Product).filter(Product.id.in_(ids)).all()
        result = _filter_products_by_universe(db, mandate, products)
    assert {p.id for p in result} == set(ids)


def test_entries_present_restrict_to_allowed_products(session_factory):
    ids = _products(session_factory)
    now = _now()
    with session_factory() as s:
        s.add(ProductUniverseEntry(
            id="pue-f1", tenant_id="firm-puf-filter", jurisdiction="CH",
            product_id=ids[0], created_by="advisor-x", created_at=now, updated_at=now,
        ))
        s.commit()
    mandate = _mandate(tenant_id="firm-puf-filter", jurisdiction="CH")
    with session_factory() as db:
        products = db.query(Product).filter(Product.id.in_(ids)).all()
        result = _filter_products_by_universe(db, mandate, products)
    assert {p.id for p in result} == {ids[0]}


def test_entries_for_other_jurisdiction_do_not_restrict(session_factory):
    ids = _products(session_factory)
    now = _now()
    with session_factory() as s:
        s.add(ProductUniverseEntry(
            id="pue-f2", tenant_id="firm-puf-filter", jurisdiction="DE",
            product_id=ids[0], created_by="advisor-x", created_at=now, updated_at=now,
        ))
        s.commit()
    mandate = _mandate(tenant_id="firm-puf-filter", jurisdiction="CH")
    with session_factory() as db:
        products = db.query(Product).filter(Product.id.in_(ids)).all()
        result = _filter_products_by_universe(db, mandate, products)
    assert {p.id for p in result} == set(ids)


def test_null_jurisdiction_on_mandate_falls_back_to_ch(session_factory):
    ids = _products(session_factory)
    now = _now()
    with session_factory() as s:
        s.add(ProductUniverseEntry(
            id="pue-f3", tenant_id="firm-puf-filter", jurisdiction="CH",
            product_id=ids[1], created_by="advisor-x", created_at=now, updated_at=now,
        ))
        s.commit()
    mandate = _mandate(tenant_id="firm-puf-filter", jurisdiction=None)
    with session_factory() as db:
        products = db.query(Product).filter(Product.id.in_(ids)).all()
        result = _filter_products_by_universe(db, mandate, products)
    assert {p.id for p in result} == {ids[1]}


def test_soft_deleted_entries_are_ignored(session_factory):
    ids = _products(session_factory)
    now = _now()
    with session_factory() as s:
        s.add(ProductUniverseEntry(
            id="pue-f4", tenant_id="firm-puf-filter", jurisdiction="CH",
            product_id=ids[0], created_by="advisor-x", created_at=now, updated_at=now,
            deleted_at=now,
        ))
        s.commit()
    mandate = _mandate(tenant_id="firm-puf-filter", jurisdiction="CH")
    with session_factory() as db:
        products = db.query(Product).filter(Product.id.in_(ids)).all()
        result = _filter_products_by_universe(db, mandate, products)
    assert {p.id for p in result} == set(ids)


def test_other_tenant_entries_do_not_restrict(session_factory):
    ids = _products(session_factory)
    now = _now()
    with session_factory() as s:
        s.add(ProductUniverseEntry(
            id="pue-f5", tenant_id="firm-other", jurisdiction="CH",
            product_id=ids[0], created_by="advisor-x", created_at=now, updated_at=now,
        ))
        s.commit()
    mandate = _mandate(tenant_id="firm-puf-filter", jurisdiction="CH")
    with session_factory() as db:
        products = db.query(Product).filter(Product.id.in_(ids)).all()
        result = _filter_products_by_universe(db, mandate, products)
    assert {p.id for p in result} == set(ids)
