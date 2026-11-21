"""Delta-Pruefrunde #858: N-858-6 (Waehrung), N-858-7 (Basis 0), N-858-8 (Datum).

- N-858-6: Der Hinweis "Strategie berechnet auf Beratungsvermoegen CHF ..."
  hatte "CHF" fest im Code; bei einem EUR-Mandat stand CHF vor EUR-Betraegen.
- N-858-7: Reserve >= Beratungsvermoegen (Strategiebasis 0) liess die Reserve
  still verschwinden (Basis wurde auf das Beratungsvermoegen gesetzt, Reserve 0).
- N-858-8: "per <Datum>" nahm ``created_at[:10]`` (UTC); eine Generierung um
  00:30 Uhr Schweizer Zeit erschien mit dem Vortag.
"""
from __future__ import annotations

from datetime import date
from io import BytesIO
from types import SimpleNamespace

from pypdf import PdfReader

from routers.pdf_reports import _strategy_basis_from_allocation, _strategy_presentation_amounts
from services.pdf.base import AnlagestrategieData, PDFContext
from services.pdf.reportlab_renderer import ReportLabRenderer

TARGET = {"equities": 5000, "bonds": 4000, "liquidity": 1000}


def _ta(**kw):
    base = dict(advisory_wealth_at_generation_rappen=150_000_00, external_reserve_at_generation_rappen=9_000_00,
                created_at="2026-11-02T12:00:00.000Z")
    base.update(kw)
    return SimpleNamespace(**base)


def test_note_uses_mandate_base_currency():
    basis = _strategy_basis_from_allocation(_ta(), {}, 180_000_00, currency="EUR")
    assert "EUR 150'000" in basis["note"] and "EUR 180'000" in basis["note"]
    assert "CHF" not in basis["note"]


def test_zero_strategy_base_keeps_reserve_and_says_so():
    ta = _ta(external_reserve_at_generation_rappen=150_000_00)
    basis = _strategy_basis_from_allocation(ta, {}, 150_000_00)
    assert basis["strategy_base_rappen"] == 0
    assert basis["external_reserve_rappen"] == 150_000_00
    assert "keine investierbare Strategiebasis" in basis["note"]
    amounts = _strategy_presentation_amounts(150_000_00, 0, TARGET, [])
    assert amounts["strategy_base_rappen"] == 0
    assert amounts["external_reserve_rappen"] == 150_000_00
    assert sum(amounts["bucket_amounts_rappen"].values()) == 0
    data = AnlagestrategieData(target_allocation_bps=TARGET, cma_expected_return_bps=300, cma_expected_vol_bps=500,
                               horizon_years=10, advisory_wealth_rappen=150_000_00,
                               strategy_basis_note=basis["note"], **amounts)
    ctx = PDFContext(mandate_name="M", advisor_name="B", report_date=date(2026, 11, 4),
                     audit_hash="abc123def456789012345678", locale="de-CH")
    text = " ".join(" ".join((p.extract_text() or "").split())
                    for p in PdfReader(BytesIO(ReportLabRenderer().render_asset_allocation(ctx, data))).pages)
    assert "Liquiditätsreserve" in text and "150'000" in text
    assert "keine investierbare Strategiebasis" in text


def test_missing_base_still_falls_back_to_advisory():
    amounts = _strategy_presentation_amounts(150_000_00, None, TARGET, [])
    assert amounts["external_reserve_rappen"] == 0
    assert sum(amounts["bucket_amounts_rappen"].values()) == 150_000_00


def test_date_is_rendered_in_zurich_time():
    # 2026-11-02 23:30 UTC = 2026-11-03 00:30 Europe/Zurich (CET, UTC+1)
    basis = _strategy_basis_from_allocation(_ta(created_at="2026-11-02T23:30:00.000Z"), {}, 180_000_00)
    assert "per 03.11.2026" in basis["note"], basis["note"]
