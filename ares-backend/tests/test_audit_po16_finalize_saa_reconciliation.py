"""PO-16 (Audit 2026-11, SAA -> Portfolio): Finalize gleicht die Anlageklassen ab.

Vorher pruefte die Finalisierung nur die Gewichtssumme (9'900..10'100 bps).
Eine Empfehlung, deren Positionen die Anlageklassen der SAA verfehlen (z. B.
nach manueller Umschichtung von Alternativen in Aktien), lief ohne jeden
Hinweis durch.

Jetzt: sichtbare Warnung (Ergebnis + Audit-Protokoll ``Final; Warnungen: ...``)
bei Abweichung > 100 bps (= Summen-Toleranz des Gates) oder ausserhalb der
Bandbreite der Soll-Allokation. Bewusst KEIN Fehler -- Blockieren ist
Owner-Entscheid Q2.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import test_golden_snapshot_ch_regression as G
from database import Base
from models.mandates import Mandate
from models.review import RecommendationPosition, RecommendationRun
from routers.review import _validate_recommendation_for_finalization
from services.portfolio_engine import (
    ensure_default_products,
    ensure_hedged_product_variants,
    generate_recommendation_run,
    generate_target_allocation,
)
from services.product_eligibility_finalization import saa_bucket_reconciliation_warnings

CODE = "[SAA_BUCKET_DEVIATION]"


def _allocation(**targets):
    fields = ("equities", "bonds", "real_estate", "alternatives", "liquidity")
    values = {}
    for field in fields:
        target, band_min, band_max = targets.get(field, (0, 0, 0))
        values[f"target_{field}_bps"] = target
        values[f"band_{field}_min_bps"] = band_min
        values[f"band_{field}_max_bps"] = band_max
    return SimpleNamespace(**values)


def _pos(pid, weight):
    return SimpleNamespace(product_id=pid, target_weight_bps=weight)


PRODUCTS = {
    "eq": SimpleNamespace(asset_class="Aktien"),
    "bd": SimpleNamespace(asset_class="Obligationen"),
    "liq": SimpleNamespace(asset_class="Liquidität"),
}


def test_matching_portfolio_has_no_warning():
    alloc = _allocation(equities=(6000, 5000, 7000), bonds=(3500, 2500, 4500), liquidity=(500, 0, 1000))
    positions = [_pos("eq", 6000), _pos("bd", 3500), _pos("liq", 500)]
    assert saa_bucket_reconciliation_warnings(alloc, positions, PRODUCTS) == []


def test_deviation_above_tolerance_warns_even_inside_band():
    alloc = _allocation(equities=(6000, 5000, 7000), bonds=(4000, 3000, 5000))
    warnings = saa_bucket_reconciliation_warnings(alloc, [_pos("eq", 6101), _pos("bd", 3899)], PRODUCTS)
    assert len(warnings) == 2 and all(CODE in w for w in warnings)
    # exakt an der Toleranz: kein Hinweis
    assert saa_bucket_reconciliation_warnings(alloc, [_pos("eq", 6100), _pos("bd", 3900)], PRODUCTS) == []


def test_band_breach_warns_with_band_text():
    alloc = _allocation(equities=(6000, 5980, 6020), bonds=(4000, 0, 0))
    warnings = saa_bucket_reconciliation_warnings(alloc, [_pos("eq", 5950), _pos("bd", 4050)], PRODUCTS)
    assert len(warnings) == 1
    assert "Aktien" in warnings[0] and "ausserhalb der Bandbreite" in warnings[0]


@pytest.fixture()
def session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'po16.db'}", connect_args={"check_same_thread": False})
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield factory
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_finalize_validation_warns_but_does_not_block_on_saa_deviation(session_factory):
    """Rot vor dem Fix: keine SAA-Abgleichs-Warnung trotz 5.9 pp Umschichtung."""
    adv, _cid, mid, _aid = G._seed_ch_mandate(session_factory, suffix="po16", score_x10=70)
    with session_factory() as s:
        ensure_default_products(s)
        ensure_hedged_product_variants(s)
        s.commit()
    with session_factory() as s:
        mandate = s.query(Mandate).filter(Mandate.id == mid).first()
        ta = generate_target_allocation(s, mandate, adv, preferences=None)
        s.commit()
        result = generate_recommendation_run(s, mandate, adv, preferences=None, target_allocation_id=ta["target_allocation"].id)
        s.commit()
        run = s.query(RecommendationRun).filter(RecommendationRun.id == result["run"].id).one()

        # Positivkontrolle: der generierte Lauf ist SAA-konform.
        errors, warnings = _validate_recommendation_for_finalization(s, mandate, run)
        assert not [w for w in warnings if CODE in w], warnings

        by_sub = {p["sub_asset_class"]: p for p in result["positions"]}
        alt = next(p for p in result["positions"] if p["asset_class"] == "Alternative")
        equity = by_sub["Aktien Schweiz"]
        moved = int(alt["target_weight_bps"])
        assert moved > 100
        alt_row = s.query(RecommendationPosition).filter(RecommendationPosition.id == alt["id"]).one()
        eq_row = s.query(RecommendationPosition).filter(RecommendationPosition.id == equity["id"]).one()
        eq_row.target_weight_bps = int(eq_row.target_weight_bps) + moved
        s.delete(alt_row)
        s.flush()

        errors_after, warnings_after = _validate_recommendation_for_finalization(s, mandate, run)
        deviation = [w for w in warnings_after if CODE in w]
        assert any(w.startswith("SAA-Abgleich Aktien") for w in deviation), warnings_after
        assert any(w.startswith("SAA-Abgleich Alternative") for w in deviation), warnings_after
        # Nur Warnung: dieselben Fehler wie vorher, nichts Neues blockiert.
        assert not [e for e in errors_after if "SAA" in e]


# ---------------------------------------------------------------------------
# N-856-6 (Pruefrunde #856): Gewichtssumme != 10'000 und Positionen ohne
# Anlageklasse. Vorher wurden Rohgewichte gegen SAA-Ziele verglichen: eine
# manuell auf 10'100 bps aufgeblaehte Empfehlung mit exakt SAA-proportionalen
# Quoten meldete Scheinabweichungen, und eine nicht zuordenbare Position zog
# die uebrigen Quoten unbemerkt nach unten.
# ---------------------------------------------------------------------------


def test_weight_sum_off_target_is_normalised_and_disclosed():
    alloc = _allocation(equities=(6000, 0, 0), bonds=(4000, 0, 0))
    # 6100/4067 = exakt SAA-proportional auf 10'167 bps
    warnings = saa_bucket_reconciliation_warnings(alloc, [_pos("eq", 6100), _pos("bd", 4067)], PRODUCTS)
    assert not [w for w in warnings if CODE in w], warnings
    assert any("[SAA_BUCKET_NORMALIZED]" in w and "101.67%" in w for w in warnings), warnings


def test_unmapped_position_is_reported_and_mapped_buckets_are_normalised():
    alloc = _allocation(equities=(6000, 0, 0), bonds=(4000, 0, 0))
    products = dict(PRODUCTS, x=SimpleNamespace(asset_class=None))
    warnings = saa_bucket_reconciliation_warnings(
        alloc, [_pos("eq", 5700), _pos("bd", 3800), _pos("x", 500)], products,
    )
    assert any("[SAA_BUCKET_UNMAPPED]" in w and "5.00%" in w for w in warnings), warnings
    # 5700/3800 auf die zuordenbaren 9'500 bps normiert = 60/40 = SAA
    assert not [w for w in warnings if CODE in w], warnings
