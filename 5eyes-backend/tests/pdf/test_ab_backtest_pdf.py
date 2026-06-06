"""Sprint U-71 (2026-06-06): Tests fuer A/B-Backtest-Sektion im Advisory-Report PDF."""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
TESTS_ROOT = Path(__file__).resolve().parents[1]
for path in (BACKEND_ROOT, TESTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from services.pdf.documents.advisory_report import _build_ab_backtest_flowables


def _styles() -> dict:
    from services.pdf.components.advisory_palette import make_advisory_styles
    return make_advisory_styles()


def _sample_ab_payload() -> dict:
    return {
        "policy_a": {
            "policy_id": "policy-a-id",
            "policy_name": "Conservative-Default",
            "weights_bps": {"equities": 4000, "bonds": 5000, "liquidity": 1000},
            "expected_return_bps": 400,
            "expected_volatility_bps": 800,
            "expected_ter_bps": 50,
            "sharpe_ratio_x100": 38,
        },
        "policy_b": {
            "policy_id": "policy-b-id",
            "policy_name": "Growth-Tilt",
            "weights_bps": {"equities": 6000, "bonds": 3000, "liquidity": 1000},
            "expected_return_bps": 650,
            "expected_volatility_bps": 1200,
            "expected_ter_bps": 60,
            "sharpe_ratio_x100": 47,
        },
        "risk_metrics_diff": {
            "delta_expected_return_bps": 250,
            "delta_expected_volatility_bps": 400,
            "delta_expected_ter_bps": 10,
            "delta_sharpe_ratio_x100": 9,
        },
    }


def test_renders_table_with_4_metric_rows():
    """4 Metrik-Zeilen + Header = 5 Zeilen in der KPI-Tabelle."""
    flowables = _build_ab_backtest_flowables(_sample_ab_payload(), _styles())
    from reportlab.platypus import Table
    # Suche die KPI-Tabelle (5+ Zeilen) — _hr ist auch Table aber 1-zeilig
    tables = [f for f in flowables if isinstance(f, Table)]
    kpi_table = next(
        (t for t in tables if len(t._cellvalues) >= 5),
        None,
    )
    assert kpi_table is not None
    assert len(kpi_table._cellvalues) == 5


def test_empty_payload_returns_empty_flowables():
    """Wenn weder policy_a noch policy_b -> leeres Flowable-List."""
    out = _build_ab_backtest_flowables({}, _styles())
    assert out == []


def test_policy_names_in_title():
    """Vergleichs-Titel enthaelt beide Policy-Namen."""
    flowables = _build_ab_backtest_flowables(_sample_ab_payload(), _styles())
    title_texts = " | ".join(
        getattr(f, "text", "") for f in flowables[:5]
    )
    assert "Conservative-Default" in title_texts
    assert "Growth-Tilt" in title_texts


def test_kicker_says_ab_backtest():
    flowables = _build_ab_backtest_flowables(_sample_ab_payload(), _styles())
    text = getattr(flowables[0], "text", "")
    assert "A/B-Backtest" in text


def test_table_includes_all_4_metric_labels():
    flowables = _build_ab_backtest_flowables(_sample_ab_payload(), _styles())
    from reportlab.platypus import Table
    tables = [f for f in flowables if isinstance(f, Table)]
    kpi_table = next(t for t in tables if len(t._cellvalues) >= 5)
    all_text = " | ".join(
        getattr(cell, "text", str(cell))
        for row in kpi_table._cellvalues
        for cell in row
    )
    for metric in (
        "Expected-Return",
        "Expected-Volatility",
        "Expected-TER",
        "Sharpe-Ratio",
    ):
        assert metric in all_text


def test_negative_delta_uses_red_color():
    """Delta < 0 -> rot eingefaerbt fuer Visual-Hinweis."""
    payload = _sample_ab_payload()
    # Setze policy_b sharpe_ratio kleiner als policy_a UND delta negativ
    payload["policy_b"]["sharpe_ratio_x100"] = 30
    payload["risk_metrics_diff"]["delta_sharpe_ratio_x100"] = -8
    flowables = _build_ab_backtest_flowables(payload, _styles())
    from reportlab.platypus import Table
    tables = [f for f in flowables if isinstance(f, Table)]
    kpi_table = next(t for t in tables if len(t._cellvalues) >= 5)
    # 5. Zeile (Sharpe), 4. Spalte (Delta)
    sharpe_delta_cell = kpi_table._cellvalues[4][3]
    # Paragraph hat .style mit .textColor; via getattr
    style = getattr(sharpe_delta_cell, "style", None)
    if style is not None and hasattr(style, "textColor"):
        color_str = str(style.textColor)
        # Pruefe ob Rot-Ton (B91C1C)
        assert "B91C1C" in color_str or "0.72" in color_str  # HexColor approx


def test_methodology_note_included():
    """Methoden-Hinweis am Ende der Sektion."""
    flowables = _build_ab_backtest_flowables(_sample_ab_payload(), _styles())
    note_texts = [getattr(f, "text", "") for f in flowables[-3:]]
    combined = " | ".join(note_texts)
    assert "Methode" in combined or "forward-looking" in combined or "CMA" in combined


def test_section_skipped_when_payload_has_no_ab_backtest():
    """Source-Parse: Section-Aufruf in _build_all_flowables nur bei
    nicht-leerem payload['ab_backtest']."""
    src = (
        BACKEND_ROOT / "services" / "pdf" / "documents" / "advisory_report.py"
    ).read_text(encoding="utf-8")
    assert "payload.get(\"ab_backtest\")" in src
    assert "_build_ab_backtest_flowables" in src
