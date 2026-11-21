"""KN3-B / N-917R2-02: E2E2-03-Regel auch im Advisory-Report und im Depotcheck.

Befund (H-167 R2): Der Advisory-Report (Kunden-PDF, «Persönlicher
Advisory-Report») druckte bei Vermoegensverzehr «Erw. Rendite −100.0 %» und
«Max Drawdown 100.0 %»; der Kunden-PDF-Waechter
(tests/test_livetest_kn3_b_customer_pdf_guard.py) fand dasselbe im Depotcheck
(«MAX. DRAWDOWN MODELL -100.0 %»). Jetzt steht dort «nicht aussagekräftig –
Vermögen aufgebraucht ab JJJJ» wie in Anlagestrategie und Vertrag.

Gegenprobe: ``depleted`` im Advisory-Report bzw. Depotcheck nicht anwenden ->
diese Tests und der Waechter werden rot.
"""
from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader

LABELS = [str(year) for year in range(2026, 2034)]
DEPLETING = [450_000_00, 300_000_00, 150_000_00, 10_000_00, -50_000_00, -200_000_00, -400_000_00, -803_336_00]


def _text(flowables) -> str:
    from reportlab.platypus import SimpleDocTemplate

    buf = BytesIO()
    SimpleDocTemplate(buf).build(list(flowables))
    return " ".join(" ".join((p.extract_text() or "").split()) for p in PdfReader(BytesIO(buf.getvalue())).pages)


def _kpis(metrics, depletion):
    from services.pdf.documents.advisory_report import _build_key_metrics_row, make_advisory_styles
    from services.pdf.fonts import register_editorial_fonts

    register_editorial_fonts()
    styles = make_advisory_styles()
    return _text([_build_key_metrics_row(metrics, styles, depletion=depletion)])


METRICS = {"risky_fraction_bps": 6280, "zielerreichung_bps": None, "exp_vol_bps": 1034,
           "exp_return_bps": -10_000, "max_drawdown_bps": 10_000, "var_95_bps": 1076}


def test_advisory_kpis_show_not_meaningful_on_depletion():
    text = _kpis(METRICS, "Vermögen aufgebraucht ab 2037")
    assert "100.0" not in text, text
    assert text.count("nicht aussagekräftig") == 2, text
    assert "Vermögen aufgebraucht ab 2037" in text
    assert "Median-Rendite (simuliert)" in text and "Erw. Rendite" not in text
    # Unveraendert: Risikoanteil, Volatilitaet, VaR.
    assert "62.8" in text and "10.3" in text and "10.8" in text


def test_advisory_total_loss_median_without_note_is_not_printed():
    text = _kpis(METRICS, None)
    assert "100.0" not in text and "nicht aussagekräftig" in text, text


def test_advisory_kpis_unchanged_without_depletion():
    text = _kpis({**METRICS, "exp_return_bps": 412, "max_drawdown_bps": 1830}, None)
    assert "4.1" in text and "18.3" in text and "nicht aussagekräftig" not in text, text


def test_advisory_depletion_note_comes_from_the_same_report_fan():
    from services.pdf.documents.advisory_report import _report_depletion_note

    payload = {"goal_based_investing": {"monte_carlo_paths": {
        "data_pending": False, "time_axis": LABELS, "p50": DEPLETING}}}
    assert _report_depletion_note(payload) == "Vermögen aufgebraucht ab 2030"
    assert _report_depletion_note({"goal_based_investing": {"monte_carlo_paths": {"data_pending": True}}}) is None
    assert _report_depletion_note({}) is None


def test_depotcheck_drawdown_not_meaningful_on_depletion():
    from services.pdf.components.depotcheck_soll import make_risk_kpis

    base = {"expected_return_bps": 212, "expected_vol_bps": 1034, "horizon_years": 10,
            "max_drawdown_bps": 10_000, "var_95_bps": 1076}
    text = _text([make_risk_kpis("Ausgewogen", {**base, "median_cagr_bps": -10_000,
                                                 "depletion_note": "Vermögen aufgebraucht ab 2037"})])
    assert "-100.0" not in text and "nicht aussagekräftig – Vermögen aufgebraucht ab 2037" in text, text
    healthy = _text([make_risk_kpis("Ausgewogen", {**base, "max_drawdown_bps": 1830, "median_cagr_bps": 412})])
    assert "-18.3" in healthy and "nicht aussagekräftig" not in healthy, healthy
