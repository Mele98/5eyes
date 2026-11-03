"""PO-04 (Audit 2026-11, SAA -> Portfolio): Kennzahlen des umgesetzten Portfolios.

Vorher wies der Empfehlungslauf als ``expected_return_bps`` /
``expected_volatility_bps`` stets die Werte der SAA aus -- auch wenn ein
Sleeve mangels Produkt durch ein Produkt einer anderen Sub-Klasse ersetzt
wurde (Reproduktion R4: Gold -> Liquid Alternatives). Die Kennzahlen
beschrieben damit ein Portfolio, das nicht empfohlen wird.

Jetzt: ``expected_*`` beschreiben die Umsetzung (Sub-Klassen der gewaehlten
Produkte, bewertet mit denselben CMA-Sub-Annahmen wie die SAA; keine neuen
Werte), die SAA-Kennzahlen stehen getrennt in ``saa_expected_*`` und
``implementation_metrics`` traegt Basis und Beschriftung.

Orakel: das Gold-Sleeve ist das einzige Sleeve der Anlageklasse Alternative.
Wird es ersetzt, verschiebt sich die Brutto-Rendite linear um
``w_gold * (r_ersatz - r_gold) / 10000`` (Rundung +-2 bps) -- unabhaengig vom
Produktionspfad hergeleitet, direkt aus den Sub-Annahmen der CMA.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import test_golden_snapshot_ch_regression as G
from database import Base
from models.allocation import CapitalMarketAssumption
from models.mandates import Mandate
from models.review import Product
from services.portfolio_engine import (
    build_recommendation_payload_from_run,
    ensure_default_products,
    ensure_hedged_product_variants,
    generate_recommendation_run,
    generate_target_allocation,
)
from services.portfolio_engine_cma import _sub_asset_class_model_map

GOLD = "Gold / Rohstoffe"


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    path = tmp_path_factory.mktemp("po04") / "po04.db"
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    adv, _cid, mid, _aid = G._seed_ch_mandate(factory, suffix="po04", score_x10=70)
    with factory() as s:
        ensure_default_products(s)
        ensure_hedged_product_variants(s)
        s.commit()
    with factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        ta = generate_target_allocation(s, mandate, adv, preferences=None)
        saa = {
            "id": ta["target_allocation"].id,
            "expected_return_bps": int(ta["expected_return_bps"]),
            "expected_volatility_bps": int(ta["expected_volatility_bps"]),
            "gold_bps": sum(
                int(x["target_weight_bps"]) for x in ta["sub_allocations"] if x["sub_asset_class"] == GOLD
            ),
            "cma_id": ta["target_allocation"].capital_market_assumptions_id,
            "payload": {
                "sub_allocations": ta["sub_allocations"],
                "expected_return_bps": ta["expected_return_bps"],
                "expected_volatility_bps": ta["expected_volatility_bps"],
            },
        }
        s.commit()
    try:
        yield factory, adv, mid, saa
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _run(world):
    factory, adv, mid, saa = world
    with factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        result = generate_recommendation_run(s, mandate, adv, preferences=None, target_allocation_id=saa["id"])
        s.commit()
        rebuilt = build_recommendation_payload_from_run(
            db=s, mandate=mandate, run=result["run"], user_id=adv, preferences=None,
        )
        return result, rebuilt


def test_without_substitution_implementation_equals_saa(world):
    """Positivkontrolle: ohne Ersatz sind beide Kennzahlensaetze identisch."""
    _factory, _adv, _mid, saa = world
    assert saa["gold_bps"] > 0
    result, rebuilt = _run(world)
    for payload in (result, rebuilt):
        assert payload["saa_expected_return_bps"] == saa["expected_return_bps"]
        assert payload["saa_expected_volatility_bps"] == saa["expected_volatility_bps"]
        assert payload["expected_return_bps"] == saa["expected_return_bps"]
        assert payload["expected_volatility_bps"] == saa["expected_volatility_bps"]
        meta = payload["implementation_metrics"]
        assert meta["deviates_from_saa"] is False
        assert meta["deviating_sub_asset_classes"] == []
        assert not [w for w in payload["warnings"] if "Kennzahlen der Umsetzung" in w]


def test_substituted_sleeve_changes_run_metrics_not_saa(world):
    """Rot vor dem Fix: der Lauf meldete trotz Gold-Ersatz die SAA-Rendite."""
    factory, _adv, _mid, saa = world
    with factory() as s:
        for product in s.query(Product).filter(Product.sub_asset_class == GOLD).all():
            product.is_active = 0
        cma = s.query(CapitalMarketAssumption).filter(CapitalMarketAssumption.id == saa["cma_id"]).one()
        subs = _sub_asset_class_model_map(cma)
        s.commit()
    result, rebuilt = _run(world)
    gold_position = [p for p in result["positions"] if GOLD in p["source_sub_asset_classes"]]
    assert len(gold_position) == 1
    replacement = gold_position[0]["sub_asset_class"]
    assert replacement != GOLD
    expected_shift = saa["gold_bps"] * (
        int(subs[replacement]["expected_return_bps"]) - int(subs[GOLD]["expected_return_bps"])
    ) / 10000
    assert abs(expected_shift) >= 5, "Szenario muss eine messbare Verschiebung erzeugen"

    for payload in (result, rebuilt):
        # SAA-Kennzahlen bleiben unveraendert und sind separat ausgewiesen.
        assert payload["saa_expected_return_bps"] == saa["expected_return_bps"]
        assert payload["saa_expected_volatility_bps"] == saa["expected_volatility_bps"]
        shift = payload["expected_return_bps"] - saa["expected_return_bps"]
        assert abs(shift - expected_shift) <= 2, (shift, expected_shift)
        # N-856-6: unbedingt geprueft (vorher nur in einem if-Zweig). Ersatz mit
        # tieferer Sub-Vola im einzigen Sleeve der Klasse -> Portfolio-Vola sinkt.
        assert int(subs[replacement]["expected_volatility_bps"]) < int(subs[GOLD]["expected_volatility_bps"])
        assert payload["expected_volatility_bps"] < saa["expected_volatility_bps"]
        meta = payload["implementation_metrics"]
        assert meta["deviates_from_saa"] is True
        assert GOLD in meta["deviating_sub_asset_classes"]
        assert meta["basis"] == "umsetzung"
        assert "umgesetzt" in meta["label"].lower()
        assert [w for w in payload["warnings"] if "Kennzahlen der Umsetzung" in w]


def test_weight_gap_and_unmapped_positions_are_disclosed_not_hidden(world):
    """N-856-6: Luecke bzw. nicht zuordenbare Position werden ausgewiesen."""
    from services.portfolio_engine import _implementation_metrics

    factory, _adv, _mid, saa = world
    payload = saa["payload"]
    rows = [r for r in payload["sub_allocations"] if int(r.get("target_weight_bps") or 0) > 0]
    positions = [
        {"asset_class": r["asset_class"], "sub_asset_class": r["sub_asset_class"],
         "target_weight_bps": int(r["target_weight_bps"])}
        for r in rows
    ]
    with factory() as s:
        cma = s.query(CapitalMarketAssumption).filter(CapitalMarketAssumption.id == saa["cma_id"]).one()
        same = _implementation_metrics(payload, cma, positions)
        assert same["implementation_metrics"]["position_weight_sum_bps"] == 10000
        assert same["implementation_metrics"]["unmapped_weight_bps"] == 0
        assert same["warning"] is None

        gap = sorted(positions, key=lambda p: p["target_weight_bps"])[0]
        shifted = [dict(p) for p in positions if p is not gap] + [
            {"asset_class": "Unbekannt", "sub_asset_class": "X", "target_weight_bps": gap["target_weight_bps"]},
        ]
        result = _implementation_metrics(payload, cma, shifted)
        meta = result["implementation_metrics"]
        assert meta["unmapped_weight_bps"] == gap["target_weight_bps"]
        assert meta["position_weight_sum_bps"] == 10000
        assert "ohne zuordenbare Anlageklasse" in result["warning"]

        short = _implementation_metrics(payload, cma, [dict(p) for p in positions if p is not gap])
        assert short["implementation_metrics"]["position_weight_sum_bps"] == 10000 - gap["target_weight_bps"]
        assert "statt 100%" in short["warning"]
