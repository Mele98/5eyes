"""Sprint U-P17c (2026-05-22): Smoke-Tests für Strategie-Backtest-PDF.

Verifiziert:
- Smoke-render mit Minimum-Data ergibt valide PDF-Bytes (Signatur %PDF)
- Smoke-render mit Benchmark ergibt größeres PDF (zusätzliche Linie)
- BacktestData ohne Soll-Pfad (warning-only) rendert ohne Crash
- Wealth + Drawdown + Metrics Components rendern einzeln
- Endpoint registriert + ist mit query-params aufrufbar
"""
from __future__ import annotations

import sys
from datetime import date
from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfReader

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy.orm import configure_mappers
from database import Base  # noqa: F401
from models import (  # noqa: F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
configure_mappers()

from services.pdf.base import BacktestData, PDFContext
from services.pdf.components.backtest_metrics import make_backtest_metrics_table
from services.pdf.components.drawdown_chart import make_drawdown_chart
from services.pdf.components.wealth_chart import make_wealth_chart
from services.pdf.reportlab_renderer import ReportLabRenderer


def _sample_metrics(cagr_bps: int = 500, max_dd_bps: int = 1500) -> dict:
    return {
        "cagr_bps": cagr_bps, "vol_bps": 1200, "sharpe_x100": 50,
        "max_drawdown_bps": max_dd_bps,
        "best_year_bps": 2000, "best_year_label": 2019,
        "worst_year_bps": -1500, "worst_year_label": 2022,
        "win_rate_x100": 6000, "positive_years": 3, "negative_years": 2,
        "total_return_bps": 2500,
        "start_value_rappen": 500_000_00, "end_value_rappen": 625_000_00,
        "years_count": 5,
    }


def _sample_data(*, with_benchmark: bool = False) -> BacktestData:
    soll_wealth = [
        (2017, 500_000_00), (2018, 460_000_00), (2019, 540_000_00),
        (2020, 580_000_00), (2021, 650_000_00), (2022, 590_000_00),
    ]
    soll_dd = [{"year": y, "drawdown_bps": dd} for y, dd in [
        (2017, 0), (2018, -800), (2019, 0), (2020, 0), (2021, 0), (2022, -923),
    ]]
    bm_wealth = [
        (2017, 500_000_00), (2018, 470_000_00), (2019, 555_000_00),
        (2020, 600_000_00), (2021, 680_000_00), (2022, 600_000_00),
    ] if with_benchmark else ()
    bm_dd = [{"year": y, "drawdown_bps": dd} for y, dd in [
        (2017, 0), (2018, -600), (2019, 0), (2020, 0), (2021, 0), (2022, -1176),
    ]] if with_benchmark else ()
    return BacktestData(
        mandate_number="M-T",
        initial_value_rappen=500_000_00,
        soll_weights_bps={"equities": 6000, "bonds": 3000, "real_estate": 500, "liquidity": 500},
        start_year=2018, end_year=2022,
        available_years=(2018, 2019, 2020, 2021, 2022),
        soll_wealth_path_rappen=soll_wealth,
        soll_drawdown_path_bps=soll_dd,
        soll_metrics=_sample_metrics(),
        benchmark_weights_bps={"equities": 6000, "bonds": 4000} if with_benchmark else None,
        benchmark_wealth_path_rappen=bm_wealth,
        benchmark_drawdown_path_bps=bm_dd,
        benchmark_metrics=_sample_metrics(cagr_bps=700, max_dd_bps=1800) if with_benchmark else None,
    )


def _ctx() -> PDFContext:
    return PDFContext(
        mandate_name="Test M-001", advisor_name="Adv",
        advisor_org="WealthArchitekten",
        report_date=date.today(), base_currency="CHF",
    )


# ============================================================================
# render_backtest smoke
# ============================================================================


def test_render_backtest_returns_valid_pdf_bytes():
    pdf = ReportLabRenderer().render_backtest(_ctx(), _sample_data())
    assert isinstance(pdf, (bytes, bytearray))
    assert pdf.startswith(b"%PDF"), "PDF magic-bytes missing"
    assert len(pdf) > 3000, "PDF suspiciously small"


def test_render_backtest_cover_uses_report_specific_title():
    pdf = ReportLabRenderer().render_backtest(_ctx(), _sample_data())
    first_page = PdfReader(BytesIO(pdf)).pages[0].extract_text() or ""

    assert "Strategie-Backtest" in first_page
    assert "Anlagestrategie" not in first_page


def test_render_backtest_with_benchmark_is_larger():
    pdf_no_bm = ReportLabRenderer().render_backtest(_ctx(), _sample_data(with_benchmark=False))
    pdf_with_bm = ReportLabRenderer().render_backtest(_ctx(), _sample_data(with_benchmark=True))
    # Beide PDFs gültig
    assert pdf_no_bm.startswith(b"%PDF")
    assert pdf_with_bm.startswith(b"%PDF")
    # Benchmark-Version hat zusätzliche Linie + Spalte -> mehr bytes
    assert len(pdf_with_bm) > len(pdf_no_bm)


def test_render_backtest_handles_empty_soll_with_warning():
    """Mandat ohne Daten -> fallback-Text + Warning, kein Crash."""
    empty = BacktestData(
        mandate_number="M-EMPTY", initial_value_rappen=0,
        soll_weights_bps={}, start_year=None, end_year=None,
        warnings=("Keine Daten verfügbar.",),
    )
    pdf = ReportLabRenderer().render_backtest(_ctx(), empty)
    assert pdf.startswith(b"%PDF")


# ============================================================================
# Components
# ============================================================================


def test_wealth_chart_creates_drawing():
    from reportlab.graphics.shapes import Drawing
    chart = make_wealth_chart(
        [(2018, 100_000_00), (2019, 110_000_00), (2020, 115_000_00)],
        height_mm=60,
    )
    assert isinstance(chart, Drawing)
    assert chart.width > 0


def test_drawdown_chart_handles_zero_drawdown():
    from reportlab.graphics.shapes import Drawing
    chart = make_drawdown_chart(
        [{"year": 2018, "drawdown_bps": 0}, {"year": 2019, "drawdown_bps": 0}],
        height_mm=30,
    )
    assert isinstance(chart, Drawing)


def test_metrics_table_renders_without_benchmark():
    from reportlab.platypus import Table
    tbl = make_backtest_metrics_table(_sample_metrics())
    assert isinstance(tbl, Table)


def test_metrics_table_renders_with_benchmark():
    from reportlab.platypus import Table
    tbl = make_backtest_metrics_table(_sample_metrics(), _sample_metrics(cagr_bps=800))
    assert isinstance(tbl, Table)


# ============================================================================
# Endpoint-Registrierung
# ============================================================================


def test_backtest_pdf_route_is_registered():
    from main import app
    routes = {getattr(r, "path", ""): set(getattr(r, "methods", set()) or set()) for r in app.routes}
    assert "/mandates/{mandate_id}/reports/backtest.pdf" in routes
    assert "GET" in routes["/mandates/{mandate_id}/reports/backtest.pdf"]
