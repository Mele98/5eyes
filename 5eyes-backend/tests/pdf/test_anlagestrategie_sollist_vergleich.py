"""Roadmap #57/#58 (Standpunkt 2026-08-07): SOLL/IST-Vergleich + Risiko-
Kennzahlen im Anlagestrategie-PDF -- Dokument-Ebenen-Test (Wiring in
services/pdf/documents/anlagestrategie.py), analog zu
test_anlagestrategie_goal_achievability.py fuer die Achievability-Sektion.
"""
from __future__ import annotations

from datetime import date
from io import BytesIO

import pytest
from pypdf import PdfReader

from services.pdf.base import AnlagestrategieData, PDFContext
from services.pdf.reportlab_renderer import ReportLabRenderer


@pytest.fixture
def ctx() -> PDFContext:
    return PDFContext(
        mandate_name="Hans Muster",
        advisor_name="Anna Berater",
        advisor_org="Muster & Partner AG",
        report_date=date(2026, 5, 23),
        audit_hash="abc123def456789012345678",
        locale="de-CH",
    )


def _base_data(**overrides) -> AnlagestrategieData:
    defaults = dict(
        target_allocation_bps={
            "equities": 6000, "bonds": 3000, "real_estate": 500,
            "alternatives": 0, "liquidity": 500,
        },
        cma_expected_return_bps=485,
        cma_expected_vol_bps=1120,
        horizon_years=10,
        risk_profile_label="Wachstumsorientiert",
        risk_score_x10=75,
        mandate_number="M-100001",
        advisory_wealth_rappen=1_000_000_00,
    )
    defaults.update(overrides)
    return AnlagestrategieData(**defaults)


def _pdf_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def test_sollist_kennzahlen_section_renders_when_mc_data_present(ctx: PDFContext):
    data = _base_data(
        median_cagr_bps=650,
        max_drawdown_bps=1800,
        var_95_bps=900,
        target_median_end_rappen=250_000_00,
        target_p90_end_rappen=320_000_00,
        target_p10_end_rappen=190_000_00,
        current_median_end_rappen=210_000_00,
        current_p90_end_rappen=260_000_00,
        current_p10_end_rappen=170_000_00,
        current_annualized_return_p50_bps=420,
        target_volatility_1y_bps=1200,
        current_volatility_1y_bps=900,
    )
    pdf_bytes = ReportLabRenderer().render_anlagestrategie(ctx, data)
    text = _pdf_text(pdf_bytes)

    assert pdf_bytes.startswith(b"%PDF")
    assert "SOLL/IST-VERGLEICH" in text
    assert "Sharpe" in text
    assert "CHF 250" in text or "250" in text  # Median-Endwert SOLL


def test_sollist_kennzahlen_section_omitted_when_no_mc_data(ctx: PDFContext):
    data = _base_data()  # keine MC-Felder gesetzt -> alles None/leer
    pdf_bytes = ReportLabRenderer().render_anlagestrategie(ctx, data)
    text = _pdf_text(pdf_bytes)

    assert pdf_bytes.startswith(b"%PDF")
    assert "SOLL/IST-VERGLEICH" not in text


def test_sollist_goal_comparison_renders_alongside_ziele_section(ctx: PDFContext):
    data = _base_data(
        goal_analysis=[
            {"goal_id": "g-1", "label": "Pensionsentnahme 2035", "median_achievement_pct": 92,
             "target_amount_rappen": 500_000_00, "projected_value_rappen": 480_000_00,
             "target_kind": "wealth_at_t"},
        ],
        current_goal_analysis=[
            {"goal_id": "g-1", "label": "Pensionsentnahme 2035", "median_achievement_pct": 68},
        ],
    )
    pdf_bytes = ReportLabRenderer().render_anlagestrategie(ctx, data)
    text = _pdf_text(pdf_bytes)

    assert pdf_bytes.startswith(b"%PDF")
    assert "92%" in text
    assert "68%" in text


def test_document_still_renders_when_only_current_goal_analysis_missing(ctx: PDFContext):
    """Backwards-Compat: aeltere TargetAllocation ohne current_goal_analysis
    (Feature noch nicht gelaufen) darf den PDF-Build nicht crashen."""
    data = _base_data(
        goal_analysis=[
            {"goal_id": "g-1", "label": "Ziel A", "median_achievement_pct": 80},
        ],
        current_goal_analysis=[],
    )
    pdf_bytes = ReportLabRenderer().render_anlagestrategie(ctx, data)
    assert pdf_bytes.startswith(b"%PDF")
