"""N-856-5 (Pruefrunde #856): exakte PO-04-Verschiebung je Golden-Fall.

Der Golden-Snapshot vergleicht die Totals-Momente mit 30 bps Solver-Toleranz.
Die PO-04-Verschiebung (Umsetzung minus SAA) ist in zwei von drei
Bucket-5-Faellen kleiner (default -3/-11, equities_global -6/-21): ohne
PO-04 blieben diese Golden-Faelle gruen. Dieser Test prueft deshalb die
Verschiebung EXAKT in bps, gemessen innerhalb desselben Laufs (Umsetzung und
SAA stammen aus derselben Soll-Allokation, BLAS-Rauschen der SAA hebt sich in
der Differenz auf).

Erwartete Werte = Differenz der Golden-Totals vor/nach PO-04 (unabhaengig
nachgerechnet in Dok. 86, Pruefrunde #856, Abschnitt 3: lineare Rendite
445.4->442.0, 458.3->451.6, 459.3->442.5; Aktien-Bucket-Vola-Plausibilisierung
-11/-22/-54).
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import test_golden_snapshot_ch_regression as G
from database import Base
from models.mandates import Mandate
from services.portfolio_engine import generate_recommendation_run, generate_target_allocation

# combo -> (Rendite-Verschiebung, Vola-Verschiebung) in bps
EXPECTED_SHIFT_BPS = {
    "bucket5_ausgewogen_default_prefs": (-3, -11),
    "bucket5_ausgewogen_equities_global": (-6, -21),
    "bucket5_ausgewogen_chfonly_em_focus": (-17, -53),
}
COMBOS = {combo["name"]: combo for combo in G.COMBOS}


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'n8565.db'}", connect_args={"check_same_thread": False})
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield factory
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.mark.parametrize("name", sorted(EXPECTED_SHIFT_BPS))
def test_po04_shift_is_exact_per_golden_case(session_factory, name):
    combo = COMBOS[name]
    adv, _cid, mid, _aid = G._seed_ch_mandate(session_factory, suffix=name, score_x10=combo["score_x10"])
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        ta = generate_target_allocation(s, mandate, adv, preferences=combo["preferences"])
        ta_id = ta["target_allocation"].id
        saa = (int(ta["expected_return_bps"]), int(ta["expected_volatility_bps"]))
        s.commit()
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        run = generate_recommendation_run(
            s, mandate, adv, preferences=combo["preferences"], target_allocation_id=ta_id,
        )
    assert (run["saa_expected_return_bps"], run["saa_expected_volatility_bps"]) == saa
    shift = (
        run["expected_return_bps"] - run["saa_expected_return_bps"],
        run["expected_volatility_bps"] - run["saa_expected_volatility_bps"],
    )
    assert shift == EXPECTED_SHIFT_BPS[name]
    assert run["implementation_metrics"]["deviating_sub_asset_classes"] == [
        "Aktien Schweiz", "Aktien Schwellenlaender",
    ]
