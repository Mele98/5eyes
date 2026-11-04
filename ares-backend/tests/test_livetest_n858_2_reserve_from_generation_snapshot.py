"""Pruefrunde #858 N-858-2 -- Reservezeile aus Werten verschiedener Zeitpunkte.

Befund: ``_build_anlagestrategie_data`` nahm das Beratungsvermoegen aus der
TargetAllocation (``advisory_wealth_at_generation_rappen``), die
Strategiebasis aber aus ``build_target_payload_from_allocation`` -- und die
rechnet mit dem AKTUELLEN Beratungsvermoegen. Die Reservezeile war die
Differenz: stieg das Vermoegen nach der Generierung, fiel sie still auf 0;
sank es, wuchs sie um die Differenz.

Soll: Reserve aus dem gespeicherten Generierungs-Snapshot
(``external_reserve_at_generation_rappen``), Strategiebasis = Beratungs-
vermoegen bei Generierung minus diese Reserve; bei abweichendem aktuellem
Vermoegen ein ausdruecklicher Hinweis "Strategie berechnet auf
Beratungsvermoegen ... per <Datum>".
"""
from __future__ import annotations

from datetime import date
from io import BytesIO
from types import SimpleNamespace

import pytest
from pypdf import PdfReader

from routers.pdf_reports import _strategy_basis_from_allocation, _strategy_presentation_amounts
from services.pdf.base import AnlagestrategieData, PDFContext
from services.pdf.reportlab_renderer import ReportLabRenderer

TA = SimpleNamespace(
    advisory_wealth_at_generation_rappen=150_000_00,
    external_reserve_at_generation_rappen=9_000_00,
    created_at="2026-11-02T22:50:00",
)
TARGET = {"equities": 4780, "bonds": 3900, "real_estate": 500, "alternatives": 500, "liquidity": 320}
CTX = PDFContext(mandate_name="Muster", advisor_name="Berater", advisor_org="Muster AG",
                 report_date=date(2026, 11, 3), audit_hash="abc123def456789012345678", locale="de-CH")


def _live_payload(current_advisory: int) -> dict:
    # wie build_target_payload_from_allocation: Basis aus dem AKTUELLEN Vermoegen
    return {"strategy_base_rappen": current_advisory - 9_000_00, "external_reserve_rappen": 9_000_00}


@pytest.mark.parametrize("current", [150_000_00, 180_000_00, 120_000_00])
def test_reserve_and_base_come_from_generation_snapshot(current):
    basis = _strategy_basis_from_allocation(TA, _live_payload(current), current)
    assert basis["advisory_wealth_rappen"] == 150_000_00
    assert basis["external_reserve_rappen"] == 9_000_00
    assert basis["strategy_base_rappen"] == 141_000_00
    amounts = _strategy_presentation_amounts(
        basis["advisory_wealth_rappen"], basis["strategy_base_rappen"], TARGET, [])
    assert amounts["external_reserve_rappen"] == 9_000_00
    assert sum(amounts["bucket_amounts_rappen"].values()) == 141_000_00


@pytest.mark.parametrize("current", [180_000_00, 120_000_00])
def test_changed_wealth_is_flagged_in_pdf(current):
    basis = _strategy_basis_from_allocation(TA, _live_payload(current), current)
    note = basis["note"]
    assert note and "02.11.2026" in note and "150'000" in note
    amounts = _strategy_presentation_amounts(
        basis["advisory_wealth_rappen"], basis["strategy_base_rappen"], TARGET, [])
    data = AnlagestrategieData(target_allocation_bps=TARGET, cma_expected_return_bps=423, cma_expected_vol_bps=754,
                               horizon_years=15, advisory_wealth_rappen=basis["advisory_wealth_rappen"],
                               strategy_basis_note=note, **amounts)
    for render in (ReportLabRenderer().render_asset_allocation, ReportLabRenderer().render_anlagestrategie):
        text = " ".join((pg.extract_text() or "") for pg in PdfReader(BytesIO(render(CTX, data))).pages)
        flat = " ".join(text.split())
        assert "Strategie berechnet auf Beratungsvermögen CHF 150'000 per 02.11.2026" in flat
        assert "9'000" in flat


def test_unchanged_wealth_has_no_note():
    assert _strategy_basis_from_allocation(TA, _live_payload(150_000_00), 150_000_00)["note"] is None


def test_legacy_allocation_without_reserve_snapshot_uses_payload():
    legacy = SimpleNamespace(advisory_wealth_at_generation_rappen=150_000_00,
                             external_reserve_at_generation_rappen=None, created_at="2026-10-01")
    basis = _strategy_basis_from_allocation(legacy, _live_payload(150_000_00), 150_000_00)
    assert basis["external_reserve_rappen"] == 9_000_00
    assert basis["strategy_base_rappen"] == 141_000_00


def test_strategy_pdf_data_uses_generation_snapshot_basis():
    import inspect

    import routers.pdf_reports as pdf_reports

    src = inspect.getsource(pdf_reports._build_anlagestrategie_data)
    assert "_strategy_basis_from_allocation(" in src
    assert "ta_obj, engine_payload, current_advisory_wealth," in src
    assert 'strategy_basis["strategy_base_rappen"]' in src
    assert 'engine_payload.get("strategy_base_rappen")' not in src
