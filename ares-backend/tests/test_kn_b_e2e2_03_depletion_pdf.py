"""KN-B / E2E2-03: Kunden-PDF bei Vermoegensverzehr.

Befund (Dok. 117): Faellt der mittlere Verlauf unter null, druckte das
Anlagestrategie-/Vertrags-PDF "Median CAGR -100.00 %", "Max. Drawdown
-100.00 %" und "Sharpe -28.24". Die App sagt korrekt "Vermögen aufgebraucht
ab JJJJ". Jetzt steht im PDF an diesen Stellen "nicht aussagekräftig" mit dem
Verzehr-Hinweis. Ausserdem: Titel "RISIKOINDIKTATOREN" (Tippfehler).

Gegenprobe: ``target_depletion_note``/``current_depletion_note`` nicht
weiterreichen bzw. ``depleted`` immer False -> die Tests mit Verzehr werden rot.
"""
from __future__ import annotations

import re
from datetime import date
from io import BytesIO

from pypdf import PdfReader

from services.pdf.base import AnlagestrategieData, PDFContext, depletion_note
from services.pdf.components.risiko_metriken import make_risiko_metriken_section
from services.pdf.components.sollist_vergleich import make_sollist_kennzahlen_table
from services.pdf.reportlab_renderer import ReportLabRenderer
from tests.test_n873_03_04_pdf_mc_wiring import (  # noqa: F401
    _strategy_data,
    advisor_user,
    api,
    session_factory,
)

LABELS = [str(year) for year in range(2026, 2034)]
DEPLETING = [450_000_00, 300_000_00, 150_000_00, 10_000_00, -50_000_00, -200_000_00, -400_000_00, -803_336_00]
HEALTHY = [450_000_00 + i * 10_000_00 for i in range(len(LABELS))]


def _pdf_text(flowables) -> str:
    from reportlab.platypus import SimpleDocTemplate

    buf = BytesIO()
    SimpleDocTemplate(buf).build(list(flowables))
    return " ".join(" ".join((p.extract_text() or "").split()) for p in PdfReader(BytesIO(buf.getvalue())).pages)


def test_depletion_note_follows_app_rule():
    assert depletion_note(LABELS, DEPLETING) == "Vermögen aufgebraucht ab 2030"
    assert depletion_note(LABELS, HEALTHY) is None
    # Startwert <= 0: Finanzierungsluecke (wie advisor-guidance.js depletionPhrase).
    assert depletion_note(LABELS, [0, -1, -2]) == "Finanzierungslücke ab 2027"
    # Reserve wie beim gedruckten Endwert: -50k + 60k Reserve ist nicht unter null.
    assert depletion_note(LABELS, [100_00, -50_000_00, -70_000_00], offset=60_000_00) == "Vermögen aufgebraucht ab 2028"
    assert depletion_note(None, [-1]) == "Finanzierungslücke"
    assert depletion_note(LABELS, None) is None


def _metrics(note):
    return _pdf_text(make_risiko_metriken_section(
        expected_return_bps=212, median_cagr_bps=-10_000, volatility_bps=357,
        max_drawdown_bps=10_000, var_95_bps=376, depletion_note=note,
    ))


def test_risk_tiles_show_not_meaningful_instead_of_minus_100():
    text = _metrics("Vermögen aufgebraucht ab 2044")
    assert "100.00" not in text, text
    assert text.count("nicht aussagekräftig") == 2, text
    assert "Vermögen aufgebraucht ab 2044" in text
    # Unveraendert: Erwartete Rendite, Modell-Volatilitaet, VaR.
    assert "2.12" in text and "3.57" in text and "3.76" in text


def test_risk_tile_title_typo_fixed():
    text = _metrics(None)
    assert "RISIKOINDIKATOREN" in text
    assert "INDIKTATOREN" not in text


def test_total_loss_median_without_series_is_not_printed_as_minus_100():
    """Auch ohne Pfadreihe (Altpayload) ist -100 % Median nicht aussagekraeftig."""
    text = _metrics(None)
    assert "-100.00" not in text and "−100.00" not in text, text
    assert "nicht aussagekräftig" in text


def _sollist(target_note, current_note, target_cagr=-10_000, current_cagr=-10_000):
    return _pdf_text(make_sollist_kennzahlen_table(
        target_median_end_rappen=-803_336_00, target_p90_end_rappen=-695_951_00,
        target_p10_end_rappen=-884_018_00, current_median_end_rappen=-700_363_00,
        current_p90_end_rappen=-213_088_00, current_p10_end_rappen=-847_989_00,
        target_cagr_bps=target_cagr, current_cagr_bps=current_cagr,
        target_volatility_1y_bps=357, current_volatility_1y_bps=414,
        end_year_label="2055", target_depletion_note=target_note, current_depletion_note=current_note,
    ))


def test_sollist_table_has_no_minus_100_or_sharpe_on_depletion():
    text = _sollist("Vermögen aufgebraucht ab 2044", "Vermögen aufgebraucht ab 2041")
    assert "-100.00" not in text and "-28.24" not in text and "-24.35" not in text, text
    assert "nicht aussagekräftig – Vermögen aufgebraucht ab 2044" in text
    assert "nicht aussagekräftig – Vermögen aufgebraucht ab 2041" in text
    assert "Werte unter null zeigen die Finanzierungslücke" in text
    # Endwerte bleiben sichtbar (Finanzierungsluecke), Volatilitaet unveraendert.
    assert "803'336" in text and "3.57" in text


def test_sollist_table_unchanged_without_depletion():
    text = _sollist(None, None, target_cagr=504, current_cagr=420)
    assert "5.04" in text and "4.20" in text
    assert "nicht aussagekräftig" not in text
    assert "Finanzierungslücke" not in text


CTX = PDFContext(mandate_name="Muster", advisor_name="Berater", advisor_org="Muster AG",
                 report_date=date(2026, 11, 19), audit_hash="abc123def456789012345678", locale="de-CH")


def _metric_cells_not_meaningful(flat: str, target_year: str, current_year: str) -> bool:
    cells = (f" nicht aussagekräftig – Vermögen aufgebraucht ab {target_year}"
             f" nicht aussagekräftig – Vermögen aufgebraucht ab {current_year} ")
    labels = (r"Rendite p\.a\. \(Median\)", r"Rendite/Risiko \(Sharpe[^)]*\)")
    return all(re.search(label + re.escape(cells), flat) for label in labels)


def test_metric_cell_check_controls():
    ok = ("Erzeugt: 2026-11-28 Rendite p.a. (Median) nicht aussagekräftig – Vermögen aufgebraucht ab 2044"
          " nicht aussagekräftig – Vermögen aufgebraucht ab 2041 Volatilität 1 Jahr 3.57 %"
          " Rendite/Risiko (Sharpe, risikofrei 0.8 %) nicht aussagekräftig – Vermögen aufgebraucht ab 2044"
          " nicht aussagekräftig – Vermögen aufgebraucht ab 2041 Ende")
    assert _metric_cells_not_meaningful(ok, "2044", "2041")  # Tag 28 im Datum stoert nicht
    for bad in ("-28.24", "-3.10", "0.42", "−100.00 %"):
        mutated = ok.replace("(Sharpe, risikofrei 0.8 %) nicht aussagekräftig – Vermögen aufgebraucht ab 2044",
                             f"(Sharpe, risikofrei 0.8 %) {bad}")
        assert not _metric_cells_not_meaningful(mutated, "2044", "2041"), bad


def test_rendered_strategy_pdf_on_depletion():
    data = AnlagestrategieData(
        target_allocation_bps={"equities": 0, "bonds": 9360, "real_estate": 0, "alternatives": 370, "liquidity": 270},
        cma_expected_return_bps=212, cma_expected_vol_bps=357, horizon_years=28,
        advisory_wealth_rappen=450_000_00, max_drawdown_bps=10_000, var_95_bps=376, median_cagr_bps=-10_000,
        target_median_end_rappen=-803_336_00, current_median_end_rappen=-700_363_00,
        current_annualized_return_p50_bps=-10_000, target_volatility_1y_bps=357, current_volatility_1y_bps=414,
        projection_end_year_label="2055",
        target_depletion_note="Vermögen aufgebraucht ab 2044", current_depletion_note="Vermögen aufgebraucht ab 2041",
    )
    pdf = ReportLabRenderer().render_anlagestrategie(CTX, data)
    flat = " ".join(" ".join((pg.extract_text() or "") for pg in PdfReader(BytesIO(pdf)).pages).split())
    assert "-100.00" not in flat and "−100.00" not in flat
    # Semantisch je Kennzahlenzeile (Codex CH-final §8): bei Verzehr steht in den
    # Zellen von Median-Rendite und Sharpe ausschliesslich der Ersatztext -- jeder
    # Zahlenwert (z. B. "Sharpe -28.24") bricht den Treffer. Daten wie
    # "Erzeugt: 2026-11-28" spielen dafuer keine Rolle.
    assert _metric_cells_not_meaningful(flat, "2044", "2041"), flat
    assert "RISIKOINDIKATOREN" in flat and "INDIKTATOREN" not in flat
    assert "Vermögen aufgebraucht ab 2044" in flat


def test_builder_derives_depletion_from_median_path(api, advisor_user, session_factory, monkeypatch):
    labels = [str(year) for year in range(2026, 2026 + len(DEPLETING))]
    override = {
        "simulations": 500, "horizon_years": len(labels) - 1, "year_labels": labels,
        "target_p50_series_rappen": DEPLETING, "current_p50_series_rappen": HEALTHY,
        "target_annualized_return_p50_bps": -10_000, "reserve_accounting_basis": "ledger",
    }
    data = _strategy_data(api, advisor_user, session_factory, monkeypatch, override)
    assert data.target_depletion_note == "Vermögen aufgebraucht ab 2030"
    assert data.current_depletion_note is None
