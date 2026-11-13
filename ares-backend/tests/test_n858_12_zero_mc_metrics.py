"""N-858-12 (Dok. 86, Pruefrunde #858): Ein gerechneter MC-Wert von 0 bps
(z. B. reine Liquiditaet: Max-Drawdown 0, VaR 0; IST nur Konto ohne
Schwankung) wurde im PDF als "keine Angabe" (—) gezeigt statt als 0 %.

Ursache war ``int(mc.get(...) or 0) or None`` in ``routers/pdf_reports.py``
plus ``_fmt_pct`` (0 -> "—") in der Kennzahlen-Kachel.
"""
from __future__ import annotations

from datetime import date
from io import BytesIO

import pytest
from pypdf import PdfReader

from routers.pdf_reports import _optional_mc_bps
from services.pdf.base import AnlagestrategieData, PDFContext
from services.pdf.reportlab_renderer import ReportLabRenderer

CTX = PDFContext(mandate_name="Muster", advisor_name="Berater", advisor_org="Muster AG",
                 report_date=date(2026, 11, 7), audit_hash="abc123def456789012345678", locale="de-CH")
TARGET = {"equities": 0, "bonds": 0, "real_estate": 0, "alternatives": 0, "liquidity": 10000}


@pytest.mark.parametrize(
    ("mc", "expected"),
    [
        ({"target_var_95_1y_bps": 0}, 0),
        ({"target_var_95_1y_bps": "0"}, 0),
        ({"target_var_95_1y_bps": 250}, 250),
        ({"target_var_95_1y_bps": None}, None),
        ({"target_var_95_1y_bps": ""}, None),
        ({}, None),
    ],
)
def test_optional_mc_bps_keeps_zero(mc, expected):
    assert _optional_mc_bps(mc, "target_var_95_1y_bps") == expected


def _flat_text(pdf: bytes) -> str:
    return " ".join(" ".join((pg.extract_text() or "") for pg in PdfReader(BytesIO(pdf)).pages).split())


def test_zero_drawdown_and_var_render_as_zero_percent():
    data = AnlagestrategieData(
        target_allocation_bps=TARGET, cma_expected_return_bps=80, cma_expected_vol_bps=40,
        horizon_years=10, advisory_wealth_rappen=100_000_00,
        max_drawdown_bps=0, var_95_bps=0, median_cagr_bps=0,
        target_volatility_1y_bps=0, current_volatility_1y_bps=0,
        current_annualized_return_p50_bps=0,
    )
    flat = _flat_text(ReportLabRenderer().render_anlagestrategie(CTX, data))
    assert "Max. Drawdown 0.00%" in flat or "MAX. DRAWDOWN 0.00%" in flat.upper()
    assert "VAR 95% 0.00%" in flat.upper()
    assert "MEDIAN CAGR 0.00%" in flat.upper()


def test_missing_metrics_still_render_as_dash():
    data = AnlagestrategieData(
        target_allocation_bps=TARGET, cma_expected_return_bps=80, cma_expected_vol_bps=40,
        horizon_years=10, advisory_wealth_rappen=100_000_00,
        max_drawdown_bps=None, var_95_bps=None, median_cagr_bps=None,
    )
    flat = _flat_text(ReportLabRenderer().render_anlagestrategie(CTX, data)).upper()
    assert "VAR 95% —" in flat
    assert "VAR 95% 0.00%" not in flat
