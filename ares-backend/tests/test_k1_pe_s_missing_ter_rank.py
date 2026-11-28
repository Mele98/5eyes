"""K1 / PE-S (Dok. 116 L-PE-1, Mutation M9): fehlende TER wird nicht bevorzugt.

Vorher: ``score -= int(product.ter_bps or 0)`` -- ein Produkt ohne TER wirkte
wie TER 0 und gewann jede Rangfolge gegen ein belegtes Produkt. Jetzt ist ein
Produkt ohne TER nachrangig (hinter jedem Produkt mit bekannter TER) und im
Payload als ``ter_status="missing"`` markiert ("TER fehlt"). Ausnahme
``product_type='Cash'`` (OWN-PE-05): ``ter_status="not_applicable"``.
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
    _normalize_preferences,
    ensure_default_products,
    ensure_hedged_product_variants,
    generate_recommendation_run,
    generate_target_allocation,
)
from services.portfolio_engine_payload import (
    _missing_ter_positions_count,
    _product_score,
    _product_selection_key,
    product_ter_status,
)


def _product(**kwargs):
    base = dict(
        id="p", product_name="x", product_type="ETF", asset_class="Aktien",
        sub_asset_class="Aktien Global", currency="CHF", ter_bps=5, sfdr_class="8",
        isin=None, theme_tags=None, security_type=None, security_type2=None, market_sector=None,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def test_missing_ter_ranks_behind_any_known_ter():
    prefs = _normalize_preferences(None)
    expensive = _product(id="expensive", ter_bps=1000, isin="ZZ0000000009", sfdr_class=None)
    missing = _product(id="missing", ter_bps=None, isin="AA0000000001")
    ranked = sorted([missing, expensive], key=lambda p: _product_selection_key(p, "Aktien Global", prefs))
    assert [p.id for p in ranked] == ["expensive", "missing"]
    # Auch mit allen Boni (Slot-Treffer, SFDR 8) bleibt die fehlende TER hinter
    # einem teuren Produkt ohne Slot-Treffer.
    off_slot = _product(id="off", ter_bps=1000, sub_asset_class="Aktien Schweiz", sfdr_class=None)
    assert _product_score(missing, "Aktien Global", prefs) < _product_score(off_slot, "Aktien Global", prefs)
    assert _product_score(off_slot, "Aktien Global", prefs) >= 0


def test_ter_status_and_cash_exception():
    assert product_ter_status(_product(ter_bps=0)) == "known"
    assert product_ter_status(_product(ter_bps=None)) == "missing"
    assert product_ter_status(_product(ter_bps=None, product_type="Cash")) == "not_applicable"
    prefs = _normalize_preferences(None)
    cash = _product(id="cash", ter_bps=None, product_type="Cash", asset_class="Liquidität",
                    sub_asset_class="Geldmarkt CHF")
    # Cash ohne TER wird wie TER 0 gewertet (kein Abschlag).
    assert _product_score(cash, "Geldmarkt CHF", prefs) > 0
    assert _missing_ter_positions_count([
        {"ter_bps": None, "ter_status": "not_applicable"},
        {"ter_bps": None, "ter_status": "missing"},
        {"ter_bps": 12, "ter_status": "known"},
    ]) == 1


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'pes.db'}", connect_args={"check_same_thread": False},
    )
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield factory
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _world_position(session_factory, products, suffix):
    from services.product_eligibility import seed_default_catalog_suitability_and_rules

    adv, _cid, mid, _aid = G._seed_ch_mandate(session_factory, suffix=suffix, score_x10=70)
    with session_factory() as s:
        ensure_default_products(s)
        ensure_hedged_product_variants(s)
        # Seed-Weltaktien deaktivieren: der Slot soll nur die Testprodukte sehen.
        for row in s.query(Product).filter(Product.sub_asset_class == "Aktien Global").all():
            row.is_active = 0
        now = G._now()
        created = []
        for product_id, isin, ter in products:
            product = Product(
                id=product_id, product_name=f"Welt {product_id}", provider="Testanbieter",
                product_type="ETF", asset_class="Aktien", sub_asset_class="Aktien Global",
                currency="CHF", ter_bps=ter, sfdr_class="8", isin=isin, is_active=1,
                created_at=now, updated_at=now,
            )
            s.add(product)
            s.flush()
            created.append(product)
        seed_default_catalog_suitability_and_rules(s, products=created, jurisdiction="CH", now=now)
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
        assert len(world) == 1, run["positions"]
        return world[0], run


def test_generate_prefers_known_ter_over_missing_ter(session_factory):
    """Rot vor dem Fix: das Produkt ohne TER (wie TER 0) gewann gegen TER 25."""
    chosen, _run = _world_position(
        session_factory, [("no-ter", "IE00PES00001", None), ("with-ter", "IE00PES00002", 25)], "pes1",
    )
    assert chosen["product_id"] == "with-ter"
    assert chosen["ter_status"] == "known"


def test_generate_marks_missing_ter_when_it_is_the_only_candidate(session_factory):
    """C-COMP-02: ein Produkt ohne belegte Kosten kann keinen Kundenlauf mehr
    tragen -- vorher wurde es mit Warnung "TER fehlt" empfohlen."""
    from core.reason_codes import DomainError

    with pytest.raises(DomainError) as exc:
        _world_position(session_factory, [("no-ter", "IE00PES00001", None)], "pes2")
    assert exc.value.reason_code == "PRODUCT_EVIDENCE_COST_MISSING"
    assert exc.value.extra["product_id"] == "no-ter"


def test_payload_of_an_unbound_run_marks_the_ter_as_missing(session_factory):
    """Ungebundener Lauf (Altbestand): TER bleibt unbekannt, nie 0."""
    from services.portfolio_engine import _average_ter_bps, _missing_ter_positions_count
    from services.portfolio_engine_payload import run_ter_lookup

    with session_factory() as s:
        status, bps = run_ter_lookup(s, "unbound-run")("no-ter")
    assert (status, bps) == ("missing", None)
    item = {"ter_status": status, "ter_bps": bps, "target_weight_bps": 10_000}
    assert _missing_ter_positions_count([item]) == 1 and _average_ter_bps([item]) == 0
