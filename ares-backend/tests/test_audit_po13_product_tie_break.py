"""PO-13 (Audit 2026-11, SAA -> Portfolio): Gleichstand in der Produktwahl.

Vorher entschied bei gleicher Punktzahl die Datenbank-Reihenfolge
(``sorted(..., reverse=True)`` ist stabil, die Kandidatenliste kommt aus einer
ungeordneten Abfrage): von zwei fachlich identischen Produkten gewann das
zuerst eingefuegte. Reproduktion R6 im Audit-Bericht.

Jetzt: hoechster Score, dann Produkte mit ISIN vor solchen ohne, dann ISIN
aufsteigend, dann Produkt-ID aufsteigend -- unabhaengig von der
Einfuegereihenfolge.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import test_golden_snapshot_ch_regression as G
from database import Base
from models.mandates import Mandate
from models.review import Product
from services.portfolio_engine import (
    ensure_default_products,
    ensure_hedged_product_variants,
    generate_recommendation_run,
    generate_target_allocation,
)
from services.portfolio_engine import _normalize_preferences
from services.portfolio_engine_payload import _product_selection_key


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'po13.db'}", connect_args={"check_same_thread": False},
    )
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield factory
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _add_tie_products(session, ordered: list[tuple[str, str]]) -> None:
    """Zwei fachlich identische Welt-Aktien-Produkte (gleicher Score)."""
    from services.product_eligibility import seed_default_catalog_suitability_and_rules

    now = G._now()
    created = []
    for product_id, isin in ordered:
        product = Product(
            id=product_id, product_name=f"Gleichstand {product_id}", provider="Testanbieter",
            product_type="ETF", asset_class="Aktien", sub_asset_class="Aktien Global",
            currency="CHF", ter_bps=5, sfdr_class="8", isin=isin, is_active=1,
            created_at=now, updated_at=now,
        )
        session.add(product)
        session.flush()  # erzwingt die Einfuegereihenfolge
        created.append(product)
    seed_default_catalog_suitability_and_rules(session, products=created, jurisdiction="CH", now=now)


def _chosen_world_product(session_factory, ordered, suffix):
    adv, _cid, mid, _aid = G._seed_ch_mandate(session_factory, suffix=suffix, score_x10=70)
    with session_factory() as s:
        ensure_default_products(s)
        ensure_hedged_product_variants(s)
        _add_tie_products(s, ordered)
        s.commit()
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        ta = generate_target_allocation(s, mandate, adv, preferences=None)
        ta_id = ta["target_allocation"].id
        s.commit()
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        run = generate_recommendation_run(s, mandate, adv, preferences=None, target_allocation_id=ta_id)
        world = [p for p in run["positions"] if "Aktien Global" in p["source_sub_asset_classes"]]
        assert len(world) == 1
        return world[0]["product_id"]


def test_tie_is_broken_by_isin_not_by_insertion_order(session_factory):
    """Rot vor dem Fix: in der Reihenfolge B, A gewann B (zuerst eingefuegt)."""
    # B traegt die hoehere ISIN und wird ZUERST eingefuegt.
    chosen = _chosen_world_product(
        session_factory, [("tie-B", "IE00TIE00002"), ("tie-A", "IE00TIE00001")], "po13ba",
    )
    assert chosen == "tie-A"


def test_tie_result_is_independent_of_insertion_order(session_factory):
    chosen = _chosen_world_product(
        session_factory, [("tie-A", "IE00TIE00001"), ("tie-B", "IE00TIE00002")], "po13ab",
    )
    assert chosen == "tie-A"


def _product(**kwargs):
    base = dict(
        id="p", product_name="x", product_type="ETF", asset_class="Aktien",
        sub_asset_class="Aktien Global", currency="CHF", ter_bps=5, sfdr_class="8",
        isin=None, theme_tags=None, security_type=None, security_type2=None, market_sector=None,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_selection_key_orders_score_then_isin_then_id():
    prefs = _normalize_preferences(None)
    cheaper = _product(id="z-cheap", ter_bps=4, isin="ZZ0000000000")
    with_isin = _product(id="b", isin="IE0000000002")
    lower_isin = _product(id="c", isin="IE0000000001")
    no_isin_low_id = _product(id="a", isin=None)
    no_isin_high_id = _product(id="d", isin="  ")
    ranked = sorted(
        [no_isin_high_id, with_isin, no_isin_low_id, lower_isin, cheaper],
        key=lambda p: _product_selection_key(p, "Aktien Global", prefs),
    )
    # Hoeherer Score (tiefere TER) schlaegt jeden Tie-Break.
    assert [p.id for p in ranked] == ["z-cheap", "c", "b", "a", "d"]
