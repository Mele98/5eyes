"""PO-06 (Audit 2026-11, SAA -> Portfolio): Waehrungs-Exposure abgesicherter Produkte.

Vorher leitete der Depot-Check das Waehrungs-Exposure eines Produkts ohne
gepflegtes ``currency_exposure_json`` allein aus der Sub-Anlageklasse ab. Ein
CHF-abgesicherter Welt-Aktien-ETF meldete so ~97 % Fremdwaehrung
(Reproduktion R11), und der Hedge-Vorschlag des Advisory-Reports empfahl, eine
bereits abgesicherte Position nochmals abzusichern.

Jetzt: gepflegtes JSON > Absicherungs-Kennzeichen + Produktwaehrung >
Sub-Klassen-Proxy (nur ohne Produktdaten) > Produktwaehrung; die Herkunft
wird je Position und aggregiert ausgewiesen.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import test_golden_snapshot_ch_regression as G
from database import Base
from models.mandates import Mandate
from services.advisory_report import _check_waehrungsabsicherung
from services.depot_check import compute_depot_check
from services.portfolio_engine import (
    ensure_default_products,
    ensure_hedged_product_variants,
    generate_recommendation_run,
    generate_target_allocation,
)
from services.product_exposures import currency_exposure_with_source, product_is_currency_hedged


def test_hedged_product_reports_home_currency_from_product_data():
    """Rot vor dem Fix (R11): der Proxy meldete USD 6500 fuer einen CHF-hedged ETF."""
    exposure, source = currency_exposure_with_source(
        None, "Aktien Global", product_currency="CHF",
        product_name="Welt-Aktien ETF CHF Hedged", product_type="ETF",
    )
    assert exposure == {"CHF": 10000}
    assert source == "produktname_absicherung"


def test_unhedged_product_without_data_falls_back_to_sub_class_proxy():
    exposure, source = currency_exposure_with_source(
        None, "Aktien Global", product_currency="USD",
        product_name="Welt-Aktien ETF", product_type="ETF",
    )
    assert source == "sub_klassen_proxy"
    assert exposure["USD"] == 6500


def test_maintained_json_wins_over_hedge_marker():
    exposure, source = currency_exposure_with_source(
        json.dumps({"CHF": 9000, "USD": 1000}), "Aktien Global", product_currency="CHF",
        product_name="Welt-Aktien ETF CHF Hedged",
    )
    assert exposure == {"CHF": 9000, "USD": 1000}
    assert source == "produktdaten"


def test_hedge_fund_is_not_a_currency_hedge():
    assert product_is_currency_hedged("Global Hedge Fund", "Fonds") is False
    assert product_is_currency_hedged("Bond CHF hedged", "ETF") is True
    assert product_is_currency_hedged("Obligationen waehrungsgesichert", None) is True


def test_no_product_data_and_no_proxy_uses_product_currency():
    assert currency_exposure_with_source(None, "Unbekannt", product_currency="eur") == ({"EUR": 10000}, "produktwaehrung")
    assert currency_exposure_with_source(None, None) == ({}, "unbekannt")


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'po06.db'}", connect_args={"check_same_thread": False})
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield factory
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_depot_check_and_hedge_proposal_do_not_count_hedged_products_as_fx(session_factory):
    """Rot vor dem Fix: der Basislauf (alle Fremdwaehrungs-Sleeves als CHF-hedged
    Variante) meldete > 30 % Fremdwaehrung und einen Hedge-Vorschlag."""
    adv, _cid, mid, _aid = G._seed_ch_mandate(session_factory, suffix="po06", score_x10=70)
    with session_factory() as s:
        ensure_default_products(s)
        ensure_hedged_product_variants(s)
        s.commit()
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        ta = generate_target_allocation(s, mandate, adv, preferences=None)
        s.commit()
        run = generate_recommendation_run(s, mandate, adv, preferences=None, target_allocation_id=ta["target_allocation"].id)
        s.commit()
        hedged = [p for p in run["positions"] if "hedged" in p["product_name"].lower()]
        assert hedged, "Szenario braucht abgesicherte Produkte im Lauf"
        hedged_bps = sum(p["target_weight_bps"] for p in hedged)

        dc = compute_depot_check(s, mandate)
        fx_bps = sum(v for k, v in dc["currency_exposure_bps"].items() if k != "CHF")
        # Fremdwaehrung kommt nur noch aus nicht abgesicherten Positionen.
        unhedged_fx_positions = [
            p for p in run["positions"]
            if "hedged" not in p["product_name"].lower() and p["sub_asset_class"] not in (
                "Aktien Schweiz", "Aktien Schweiz Small/Mid", "Obligationen CHF IG",
                "Obligationen Global Hedged", "Immobilien Schweiz", "Geldmarktfonds",
                "Festgeld", "Kontoguthaben",
            )
        ]
        assert fx_bps <= sum(p["target_weight_bps"] for p in unhedged_fx_positions) + 5
        assert fx_bps < hedged_bps

        sources = dc["currency_exposure_source_bps"]
        assert sources.get("produktname_absicherung", 0) >= hedged_bps - 5
        top = {p["product_name"]: p for p in dc["top_positions"]}
        for p in hedged:
            if p["product_name"] in top:
                assert top[p["product_name"]]["currency_exposure_source"] == "produktname_absicherung"

        verdict = _check_waehrungsabsicherung(s, mandate, dc)
        assert f"{fx_bps / 100:.1f}%" in verdict["beurteilung"]


def test_hedge_proposal_names_proxy_provenance():
    db = SimpleNamespace(query=lambda *_a, **_k: SimpleNamespace(
        filter=lambda *_a, **_k: SimpleNamespace(order_by=lambda *_a, **_k: SimpleNamespace(first=lambda: None))
    ))
    dc = {"currency_exposure_bps": {"CHF": 7000, "USD": 3000},
          "currency_exposure_source_bps": {"sub_klassen_proxy": 3000, "produktdaten": 7000}}
    verdict = _check_waehrungsabsicherung(db, SimpleNamespace(id="m"), dc)
    assert "Herkunft: 30.0%" in verdict["beurteilung"]
