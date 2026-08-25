"""Bug-#8b (2026-06-08): Backtest-PDF konsumiert die Bug-#8a-Fee-Daten.

Pendant zu PR #242 (Engine + Router). Diese Tests decken:

- BacktestData-Dataclass akzeptiert die neuen Fee-Felder
- pdf_reports._build_backtest_data reicht Fee-Params an Engine durch und
  mappt die Brutto-Pfade in das Dataclass
- backtest.build_backtest_flowables rendert den Brutto-vs-Netto-Block
  nur wenn Fees gepflegt sind (kein Layout-Overhead bei fee=0)
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.pdf.base import BacktestData


# ---------------------------------------------------------------------------
# Dataclass: neue Felder vorhanden, Defaults Backwards-Compat
# ---------------------------------------------------------------------------


def test_backtest_data_hat_fee_felder():
    fields = {f.name for f in BacktestData.__dataclass_fields__.values()}
    assert "strategy_fee_bps" in fields
    assert "benchmark_fee_bps" in fields
    assert "soll_gross_wealth_path_rappen" in fields
    assert "benchmark_gross_wealth_path_rappen" in fields
    assert "soll_gross_metrics" in fields
    assert "benchmark_gross_metrics" in fields


def test_backtest_data_defaults_sind_backwards_compat():
    d = BacktestData()
    assert d.strategy_fee_bps == 0
    assert d.benchmark_fee_bps == 0
    assert d.soll_gross_wealth_path_rappen == ()
    assert d.soll_gross_metrics is None


# ---------------------------------------------------------------------------
# Router-Endpoint + _build_backtest_data-Signaturen
# ---------------------------------------------------------------------------


def test_pdf_endpoint_akzeptiert_fee_params():
    from routers.pdf_reports import get_backtest_pdf
    sig = inspect.signature(get_backtest_pdf)
    assert "strategy_fee_bps" in sig.parameters
    assert "benchmark_fee_bps" in sig.parameters
    assert sig.parameters["strategy_fee_bps"].default is None
    assert sig.parameters["benchmark_fee_bps"].default is None


def test_build_backtest_data_akzeptiert_fee_params():
    from routers.pdf_reports import _build_backtest_data
    sig = inspect.signature(_build_backtest_data)
    assert "strategy_fee_bps" in sig.parameters
    assert "benchmark_fee_bps" in sig.parameters


# ---------------------------------------------------------------------------
# Flowables: Fee-Block erscheint NUR bei Fees>0
# ---------------------------------------------------------------------------


def _sample_path(end_rappen: int):
    """3-Punkte-Pfad fuer Test-Render: start, mid, end."""
    return [(2020, end_rappen // 2), (2021, int(end_rappen * 0.75)), (2022, end_rappen)]


def _flowable_text_blob(flowables) -> str:
    """Sammelt Paragraph-Texte in einem String fuer Assertions."""
    out = []
    for f in flowables:
        txt = getattr(f, "text", None)
        if txt:
            out.append(str(txt))
        elif hasattr(f, "_text"):
            out.append(str(f._text))
    return "\n".join(out)


def test_pdf_kein_fee_block_wenn_keine_fees():
    from services.pdf.base import PDFContext
    from services.pdf.documents.backtest import build_backtest_flowables
    import datetime as _dt
    ctx = PDFContext(
        mandate_name="Test", advisor_name="A",
        report_date=_dt.date(2026, 6, 8), base_currency="CHF",
    )
    data = BacktestData(
        mandate_number="M-1",
        initial_value_rappen=1_000_000_00,
        soll_weights_bps={"equities": 6000, "bonds": 4000, "real_estate": 0, "alternatives": 0, "liquidity": 0},
        start_year=2020,
        end_year=2022,
        soll_wealth_path_rappen=_sample_path(1_100_000_00),
    )
    flow = build_backtest_flowables(ctx, data)
    blob = _flowable_text_blob(flow)
    assert "Bug-#8b" not in blob
    assert "Brutto vs. Netto" not in blob


def test_pdf_fee_block_renderbar_wenn_strategy_fee_gesetzt():
    from services.pdf.base import PDFContext
    from services.pdf.documents.backtest import build_backtest_flowables
    import datetime as _dt
    ctx = PDFContext(
        mandate_name="Test", advisor_name="A",
        report_date=_dt.date(2026, 6, 8), base_currency="CHF",
    )
    data = BacktestData(
        mandate_number="M-1",
        initial_value_rappen=1_000_000_00,
        soll_weights_bps={"equities": 6000, "bonds": 4000, "real_estate": 0, "alternatives": 0, "liquidity": 0},
        start_year=2020,
        end_year=2022,
        soll_wealth_path_rappen=_sample_path(1_080_000_00),  # nach Fees
        strategy_fee_bps=100,
        soll_gross_wealth_path_rappen=_sample_path(1_100_000_00),  # brutto
    )
    flow = build_backtest_flowables(ctx, data)
    blob = _flowable_text_blob(flow)
    assert "Brutto vs. Netto" in blob
    # Strategie-Zeile vorhanden
    assert "Strategie (SOLL)" in blob
    # Fee-pct formatiert (1.00%)
    assert "1.00%" in blob


def test_pdf_fee_block_renderbar_wenn_benchmark_fee_gesetzt():
    from services.pdf.base import PDFContext
    from services.pdf.documents.backtest import build_backtest_flowables
    import datetime as _dt
    ctx = PDFContext(
        mandate_name="Test", advisor_name="A",
        report_date=_dt.date(2026, 6, 8), base_currency="CHF",
    )
    data = BacktestData(
        mandate_number="M-1",
        initial_value_rappen=1_000_000_00,
        soll_weights_bps={"equities": 6000, "bonds": 4000, "real_estate": 0, "alternatives": 0, "liquidity": 0},
        start_year=2020,
        end_year=2022,
        soll_wealth_path_rappen=_sample_path(1_100_000_00),
        benchmark_weights_bps={"equities": 6000, "bonds": 4000, "real_estate": 0, "alternatives": 0, "liquidity": 0},
        benchmark_wealth_path_rappen=_sample_path(1_090_000_00),
        benchmark_fee_bps=30,
        benchmark_gross_wealth_path_rappen=_sample_path(1_100_000_00),
    )
    flow = build_backtest_flowables(ctx, data)
    blob = _flowable_text_blob(flow)
    assert "Benchmark" in blob
    assert "0.30%" in blob


def test_helper_path_end_rappen_robust():
    from services.pdf.documents.backtest import _path_end_rappen
    assert _path_end_rappen([]) == 0
    assert _path_end_rappen([(2020, 100), (2021, 200)]) == 200
    # Nicht-Iterierbar oder ungueltige Form -> 0 (kein Crash)
    assert _path_end_rappen(None) == 0
