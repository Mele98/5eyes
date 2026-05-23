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


def test_anlagestrategie_renders_limiting_factor_and_goal_achievability(ctx: PDFContext):
    data = AnlagestrategieData(
        target_allocation_bps={
            "equities": 6000,
            "bonds": 3000,
            "real_estate": 500,
            "alternatives": 0,
            "liquidity": 500,
        },
        cma_expected_return_bps=485,
        cma_expected_vol_bps=1120,
        horizon_years=10,
        risk_profile_label="Wachstumsorientiert",
        risk_score_x10=75,
        mandate_number="M-100001",
        advisory_wealth_rappen=1_000_000_00,
        limiting_factor="risikoprofil",
        goal_achievability=[
            {
                "goal_id": "g-1",
                "label": "Pensionsentnahme 2035",
                "goal_type": "Pensionsausgabe",
                "probability": 0.92,
                "status": "erreichbar",
                "hardness": "hart",
            },
            {
                "goal_id": "g-2",
                "label": "Hauskauf 2032",
                "goal_type": "Vermoegensziel",
                "probability": 0.71,
                "status": "knapp",
                "hardness": "primaer",
            },
        ],
    )

    pdf_bytes = ReportLabRenderer().render_anlagestrategie(ctx, data)
    text = _pdf_text(pdf_bytes)

    assert pdf_bytes.startswith(b"%PDF")
    assert "Strategie-Begr" in text
    assert "Limitierender Faktor" in text
    assert "Risikoprofil" in text
    assert "Pensionsentnahme 2035" in text
    assert "Hauskauf 2032" in text


def test_anlagestrategie_omits_empty_strategy_reasoning(ctx: PDFContext):
    data = AnlagestrategieData(
        target_allocation_bps={"equities": 6000, "bonds": 3000, "liquidity": 1000},
        cma_expected_return_bps=485,
        cma_expected_vol_bps=1120,
        horizon_years=10,
        mandate_number="M-100001",
        advisory_wealth_rappen=1_000_000_00,
        limiting_factor=None,
        goal_achievability=[],
    )

    pdf_bytes = ReportLabRenderer().render_anlagestrategie(ctx, data)
    text = _pdf_text(pdf_bytes)

    assert "Strategie-Begr" not in text
    assert "Limitierender Faktor" not in text


def _pdf_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)
