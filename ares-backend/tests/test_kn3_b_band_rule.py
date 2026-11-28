"""KN3-B Nachtrag 2 (CTO-Entscheid): Band 0/0 heisst "Obergrenze 0".

Befund (Dok. 118 E2E3-01, Backend-Seite): Review-Trigger
(services/review_engine.py), Live-Rebalancing
(services/portfolio_engine_live_rebalancing.py), Depotcheck inkl. PDF/Advisory-
Report (services/depot_check.py) und der SAA-Abgleich der Finalisierung werteten
ein Band 0/0 als "keine Grenze" -- ein Kapitalschutz-Profil mit 35.6 % Aktien
(Band 0-0 %) galt als in Ordnung. Jetzt gilt eine Regel (core/band_rule.py),
dieselbe wie die Classic-Oberflaeche (KN3-U ``aresBandStatus``):

* 0/0 und Ist > 0 -> verletzt (oberhalb); 0/0 und Ist 0 -> im Band.
* Punktband min == max > 0 bleibt eine echte Grenze (H6).
* Normales Band unveraendert.
* Fehlende Grenze (``None``) -> nicht bewertbar, nie "im Band".

Platzhalter-Pruefung: Die Bandspalten der Soll-Allokation sind NOT NULL mit
CHECK min <= Ziel <= max (models/allocation.py, ares_schema.sql); geschrieben
werden sie nur aus Hausmatrix/Optimizer (portfolio_engine.py) bzw. aus
expliziten manuellen Grenzen (manual_target_allocation.py). 0/0 bedeutet also
immer Ziel 0 = vom Profil ausgeschlossen, nie "nicht konfiguriert".

Gegenproben: Sonderfall "0/0 = keine Grenze" in einer der Stellen zurueck -> rot.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests.test_ccx_p1_snapshot_hash import session_factory  # noqa: F401,E402
from core.band_rule import BAND_ABOVE, BAND_BELOW, BAND_IN, BAND_UNKNOWN, band_breach_bps, band_status, in_band


@pytest.mark.parametrize("current, low, high, expected", [
    (3560, 0, 0, BAND_ABOVE),      # Kapitalschutz: Aktien 35.6 %, Band 0-0 %
    (0, 0, 0, BAND_IN),            # ausgeschlossen und nicht gehalten
    (600, 500, 500, BAND_ABOVE),   # Punktband H6
    (400, 500, 500, BAND_BELOW),
    (500, 500, 500, BAND_IN),
    (4000, 3000, 5000, BAND_IN),   # normales Band
    (2900, 3000, 5000, BAND_BELOW),
    (5100, 3000, 5000, BAND_ABOVE),
    (3560, None, 0, BAND_UNKNOWN),  # Grenze fehlt
    (3560, 0, None, BAND_UNKNOWN),
    (None, 0, 0, BAND_UNKNOWN),
])
def test_one_band_rule(current, low, high, expected):
    assert band_status(current, low, high) == expected


def test_breach_and_in_band_helpers():
    assert band_breach_bps(3560, 0, 0) == 3560
    assert band_breach_bps(600, 500, 500) == 100
    assert band_breach_bps(4000, 3000, 5000) == 0
    assert band_breach_bps(1, None, 0) is None
    assert in_band(3560, 0, 0) is False and in_band(0, 0, 0) is True and in_band(1, None, None) is None


def _allocation(**bands):
    values = {}
    for bucket in ("equities", "bonds", "real_estate", "alternatives", "liquidity"):
        values[f"target_{bucket}_bps"] = 0
        values[f"band_{bucket}_min_bps"] = 0
        values[f"band_{bucket}_max_bps"] = 10000
    values.update(target_bonds_bps=9330, band_bonds_min_bps=8000, band_bonds_max_bps=10000,
                  target_liquidity_bps=670, band_liquidity_min_bps=0, band_liquidity_max_bps=1000,
                  band_equities_min_bps=0, band_equities_max_bps=0)
    values.update(bands)
    return SimpleNamespace(**values)


def test_live_rebalancing_flags_holding_in_zero_band():
    from services.portfolio_engine_live_rebalancing import _build_live_bucket_drifts

    entries = [
        {"asset_class": "Aktien", "current_market_value_rappen": 3_560_00},
        {"asset_class": "Obligationen", "current_market_value_rappen": 5_770_00},
        {"asset_class": "Liquiditaet", "current_market_value_rappen": 670_00},
    ]
    drifts, breached, _total = _build_live_bucket_drifts(_allocation(), entries, 10_000_00)
    assert "Aktien" in breached, breached
    eq = next(d for d in drifts if d["asset_class"] == "Aktien")
    assert (eq["band_min_bps"], eq["band_max_bps"]) == (0, 0)
    # Gegenstueck: ohne Aktienbestand ist das 0/0-Band eingehalten.
    entries[0]["current_market_value_rappen"] = 0
    entries[1]["current_market_value_rappen"] = 9_330_00
    _drifts, breached, _total = _build_live_bucket_drifts(_allocation(), entries, 10_000_00)
    assert "Aktien" not in breached, breached


def test_review_trigger_counts_zero_band_point_band_and_skips_missing_band():
    from services.review_engine import band_drifts

    drifts = band_drifts([
        {"asset_class": "Aktien", "current_weight_bps": 3560, "band_min_bps": 0, "band_max_bps": 0},
        {"asset_class": "Alternative", "current_weight_bps": 600, "band_min_bps": 500, "band_max_bps": 500},
        {"asset_class": "Obligationen", "current_weight_bps": 5770, "band_min_bps": 3000, "band_max_bps": 7000},
        {"asset_class": "Immobilien", "current_weight_bps": 900},  # keine Bandangabe -> nicht bewertbar
    ])
    assert [(d["label"], d["breach_bps"]) for d in drifts] == [("Aktien", 3560), ("Alternative", 100)]
    assert "ueber Maximum 0.00%" in drifts[0]["detail"] or "ueber Maximum 0" in drifts[0]["detail"]


def test_depot_check_marks_zero_band_holding_out_of_band(session_factory):
    from services.depot_check import compute_depot_check
    from tests.test_depot_check import (
        _make_mandate, _make_product, _make_rec_position, _make_rec_run, _make_target_allocation, _make_user,
    )

    with session_factory() as s:
        _make_user(s)
        mandate = _make_mandate(s)
        run = _make_rec_run(s, mandate_id=mandate.id, client_id=mandate.client_id)
        s.flush()
        prod = _make_product(s, asset_class="Aktien", sub_asset_class="Aktien Schweiz")
        s.flush()
        _make_rec_position(s, run_id=run.id, product_id=prod.id, current_amount_rappen=356_000_00)
        bond = _make_product(s, asset_class="Obligationen", sub_asset_class="Obligationen CHF")
        s.flush()
        _make_rec_position(s, run_id=run.id, product_id=bond.id, current_amount_rappen=644_000_00)
        ta = _make_target_allocation(s, mandate_id=mandate.id, equities_bps=0, bonds_bps=9330,
                                     real_estate_bps=0, alternatives_bps=0, liquidity_bps=670)
        ta.band_equities_min_bps, ta.band_equities_max_bps = 0, 0
        ta.band_real_estate_min_bps, ta.band_real_estate_max_bps = 0, 0
        s.commit()
        result = compute_depot_check(s, mandate)
    eq = result["buckets"]["equities"]
    assert eq["ist_bps"] == 3560 and (eq["band_min_bps"], eq["band_max_bps"]) == (0, 0)
    assert eq["in_band"] is False, eq
    # 0/0 ohne Bestand ist eingehalten (nicht "nicht bewertbar").
    assert result["buckets"]["real_estate"]["in_band"] is True


def test_depot_check_without_allocation_is_not_evaluable(session_factory):
    from services.depot_check import compute_depot_check
    from tests.test_depot_check import _make_mandate, _make_product, _make_rec_position, _make_rec_run, _make_user

    with session_factory() as s:
        _make_user(s)
        mandate = _make_mandate(s)
        run = _make_rec_run(s, mandate_id=mandate.id, client_id=mandate.client_id)
        s.flush()
        prod = _make_product(s, asset_class="Aktien", sub_asset_class="Aktien Schweiz")
        s.flush()
        _make_rec_position(s, run_id=run.id, product_id=prod.id, current_amount_rappen=100_000_00)
        s.commit()
        result = compute_depot_check(s, mandate)
    assert result["buckets"]["equities"]["in_band"] is None


def test_depot_pdf_shows_zero_band_as_limit():
    from io import BytesIO

    from pypdf import PdfReader
    from reportlab.platypus import SimpleDocTemplate

    from services.pdf.components.drift_table import make_drift_table

    buckets = {"equities": {"label": "Aktien", "ist_bps": 3560, "soll_bps": 0, "drift_bps": 3560,
                            "band_min_bps": 0, "band_max_bps": 0, "in_band": False}}
    buf = BytesIO()
    SimpleDocTemplate(buf).build([make_drift_table(buckets)])
    text = " ".join((p.extract_text() or "") for p in PdfReader(BytesIO(buf.getvalue())).pages)
    assert "ausserhalb" in text and "0.0 % – 0.0 %" in text, text


def test_finalization_saa_check_warns_on_zero_band_holding():
    """Kleiner Bestand (innerhalb der Gewichtstoleranz) in einem 0/0-Band ist
    trotzdem "ausserhalb der Bandbreite"."""
    from services.product_eligibility_finalization import saa_bucket_reconciliation_warnings

    allocation = _allocation(target_bonds_bps=9330, target_liquidity_bps=670)
    positions = [SimpleNamespace(product_id="p-eq", target_weight_bps=50),
                 SimpleNamespace(product_id="p-bd", target_weight_bps=9280),
                 SimpleNamespace(product_id="p-lq", target_weight_bps=670)]
    products = {"p-eq": SimpleNamespace(asset_class="Aktien"), "p-bd": SimpleNamespace(asset_class="Obligationen"),
                "p-lq": SimpleNamespace(asset_class="Liquiditaet")}
    warnings = saa_bucket_reconciliation_warnings(allocation, positions, products)
    eq = [w for w in warnings if "SAA-Abgleich Aktien" in w]
    assert eq and "ausserhalb der Bandbreite" in eq[0] and "Bandbreite 0.00-0.00%" in eq[0], warnings
    assert not [w for w in warnings if "SAA-Abgleich Obligationen" in w], warnings
