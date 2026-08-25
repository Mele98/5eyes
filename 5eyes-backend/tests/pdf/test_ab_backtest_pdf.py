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


def test_renders_table_with_5_metric_rows():
    """5 Metrik-Zeilen + Header = 6 Zeilen in der KPI-Tabelle.

    Sprint-Update: die KPI-Tabelle umfasst jetzt Erwartete Rendite,
    Erwartete Volatilitaet, TER, Sharpe und Max. Risky Fraction.
    """
    flowables = _build_ab_backtest_flowables(_sample_ab_payload(), _styles())
    from reportlab.platypus import Table
    # Suche die KPI-Tabelle (6+ Zeilen) — _hr ist auch Table aber 1-zeilig
    tables = [f for f in flowables if isinstance(f, Table)]
    kpi_table = next(
        (t for t in tables if len(t._cellvalues) >= 6),
        None,
    )
    assert kpi_table is not None
    assert len(kpi_table._cellvalues) == 6


def test_empty_payload_renders_section_header_without_crash():
    """Sprint-Update: bei leerem Payload rendert die Sektion weiterhin den
    Section-Header (Sektion 18 / Policy-A/B-Vergleich), bricht aber nicht ab
    und crasht nicht (policy_a/policy_b werden zu {} defaulted)."""
    out = _build_ab_backtest_flowables({}, _styles())
    assert out  # nicht leer — Header wird gerendert
    header_text = " | ".join(getattr(f, "text", "") for f in out)
    assert "Sektion 18" in header_text
    assert "Policy-A/B-Vergleich" in header_text


def test_policy_names_in_metrics_table_header():
    """Vergleich enthaelt beide Policy-Namen.

    Sprint-Update: die Policy-Namen stehen jetzt in der KPI-Tabellen-
    Kopfzeile (A: <name> / B: <name>) statt im Section-Titel.
    """
    flowables = _build_ab_backtest_flowables(_sample_ab_payload(), _styles())
    from reportlab.platypus import Table
    tables = [f for f in flowables if isinstance(f, Table)]
    kpi_table = next(t for t in tables if len(t._cellvalues) >= 6)
    all_text = " | ".join(
        getattr(cell, "text", str(cell))
        for row in kpi_table._cellvalues
        for cell in row
    )
    assert "Conservative-Default" in all_text
    assert "Growth-Tilt" in all_text


def test_section_kicker_and_title():
    """Sprint-Update: Kicker ist 'Sektion 18', Titel 'Policy-A/B-Vergleich'."""
    flowables = _build_ab_backtest_flowables(_sample_ab_payload(), _styles())
    kicker = getattr(flowables[0], "text", "")
    title = getattr(flowables[1], "text", "")
    assert "Sektion 18" in kicker
    assert "Policy-A/B-Vergleich" in title


def test_table_includes_all_metric_labels():
    """Sprint-Update: Metrik-Labels sind jetzt deutsch und um
    'Max. Risky Fraction' erweitert."""
    flowables = _build_ab_backtest_flowables(_sample_ab_payload(), _styles())
    from reportlab.platypus import Table
    tables = [f for f in flowables if isinstance(f, Table)]
    kpi_table = next(t for t in tables if len(t._cellvalues) >= 6)
    all_text = " | ".join(
        getattr(cell, "text", str(cell))
        for row in kpi_table._cellvalues
        for cell in row
    )
    for metric in (
        "Erwartete Rendite",
        "Erwartete Volatilität",
        "TER",
        "Sharpe",
        "Max. Risky Fraction",
    ):
        assert metric in all_text


def test_negative_delta_rendered_signed():
    """Delta < 0 wird in der read-only Vergleichstabelle als vorzeichen-
    behafteter negativer Wert ausgewiesen.

    Sprint-Update: die KPI-Tabelle ist bewusst neutral gehalten (kein
    rotes Value-Judgment-Coloring), die Delta-Spalte berechnet sich aus
    den Policy-Werten (B - A) und zeigt das Vorzeichen. policy_b Sharpe
    30 vs. policy_a 38 -> Delta -0.08.
    """
    payload = _sample_ab_payload()
    payload["policy_b"]["sharpe_ratio_x100"] = 30
    flowables = _build_ab_backtest_flowables(payload, _styles())
    from reportlab.platypus import Table
    tables = [f for f in flowables if isinstance(f, Table)]
    kpi_table = next(t for t in tables if len(t._cellvalues) >= 6)
    # Sharpe-Zeile (Index 4: Header + Rendite + Volatilitaet + TER -> 4=Sharpe)
    sharpe_row = kpi_table._cellvalues[4]
    # Label-Spalte bestaetigen
    assert "Sharpe" in getattr(sharpe_row[0], "text", "")
    sharpe_delta_text = getattr(sharpe_row[3], "text", "")
    assert sharpe_delta_text.startswith("-"), sharpe_delta_text
    assert "0.08" in sharpe_delta_text


def test_methodology_note_included():
    """Methoden-Hinweis ist in der Sektion vorhanden.

    Sprint-Update: der Methoden-Hinweis steht jetzt als erlaeuternder
    Intro-Absatz direkt unter dem Section-Header (read-only Policy-Effekt
    auf gleichem Risikoprofil + gleicher Kapitalmarktannahme), nicht mehr
    als separater Fussnoten-Block am Ende.
    """
    flowables = _build_ab_backtest_flowables(_sample_ab_payload(), _styles())
    combined = " | ".join(getattr(f, "text", "") for f in flowables)
    assert (
        "Kapitalmarktannahme" in combined
        or "read-only" in combined
        or "Policy-Effekt" in combined
        or "Risikoprofil" in combined
    )


def test_section_skipped_when_payload_has_no_ab_backtest():
    """Source-Parse: Section-Aufruf in _build_all_flowables nur bei
    nicht-leerem payload['ab_backtest']."""
    src = (
        BACKEND_ROOT / "services" / "pdf" / "documents" / "advisory_report.py"
    ).read_text(encoding="utf-8")
    assert "payload.get(\"ab_backtest\")" in src
    assert "_build_ab_backtest_flowables" in src
