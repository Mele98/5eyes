"""Live-Test 2026-11 M8/M9 -- Kennzahlen widersprachen sich im selben PDF.

Befunde (Anlagestrategie-PDF):
- "Volatilitaet 7.54 %" (KPI) vs. "Volatilitaet (1 Jahr) 7.68 %" (Tabelle).
  Echte Definitionsdifferenz: KPI = Modell-Volatilitaet sqrt(w'Sigma w) der
  SAA (``expected_volatility_bps``), Tabelle = in der Monte-Carlo-Simulation
  realisierte 1-Jahres-Volatilitaet (``target_volatility_1y_bps``). Beide
  bleiben, werden aber eindeutig beschriftet.
- Ueberschrift "VaR 95 %" vs. Erlaeuterung "Wahrscheinlichkeit von 99 %".
  Gerechnet wird das 5-%-Quantil der simulierten 1-Jahres-Renditen
  (``portfolio_engine_mc_simulation``: ``_percentile(..., 0.05)``) -> 95 %.
- "Anlagehorizont 15 Jahre" ohne Basis, waehrend Stammdaten 19 J. (Mandat)
  und Grafik "bis 2050" (Lebensende) zeigen: Quelle ist der Anlagehorizont
  des Risikoprofils -> so beschriften.
"""
from __future__ import annotations

import re
from datetime import date
from io import BytesIO

from pypdf import PdfReader

from services.pdf.base import AnlagestrategieData, PDFContext
from services.pdf.reportlab_renderer import ReportLabRenderer

CTX = PDFContext(mandate_name="Muster Person", advisor_name="Berater", advisor_org="Muster AG",
                 report_date=date(2026, 11, 2), audit_hash="abc123def456789012345678", locale="de-CH")


def _text() -> str:
    data = AnlagestrategieData(
        target_allocation_bps={"equities": 4780, "bonds": 3900, "real_estate": 500, "alternatives": 500, "liquidity": 320},
        cma_expected_return_bps=423, cma_expected_vol_bps=754, horizon_years=15,
        investment_horizon_years=15, risk_profile_label="Ausgewogen", risk_score_x10=50,
        mandate_number="M-1", advisory_wealth_rappen=150_000_00,
        median_cagr_bps=397, max_drawdown_bps=1586, var_95_bps=718,
        target_median_end_rappen=170_504_00, target_p90_end_rappen=258_138_00, target_p10_end_rappen=109_284_00,
        current_median_end_rappen=82_500_00, target_volatility_1y_bps=768,
    )
    pdf = ReportLabRenderer().render_anlagestrategie(CTX, data)
    return re.sub(r"[ \t]+", " ", "\n".join(p.extract_text() or "" for p in PdfReader(BytesIO(pdf)).pages))


def test_var_explanation_matches_computed_confidence_level():
    text = _text()
    assert "VaR 95%" in text or "VAR 95%" in text
    assert "99%" not in text and "99 %" not in text, "Erlaeuterung nennt 99 %, gerechnet wird 95 %"
    assert "Wahrscheinlichkeit von 95%" in text.replace("\n", " ")


def test_two_volatility_figures_are_labelled_by_definition():
    flat = _text().replace("\n", " ")
    assert "7.54%" in flat and "7.68 %" in flat
    assert "MODELL" in flat[max(0, flat.index("7.54%") - 120):flat.index("7.54%") + 80].upper()
    row = flat[max(0, flat.index("7.68 %") - 120):flat.index("7.68 %")]
    assert "simuliert" in row, row


def test_investment_horizon_names_its_basis():
    flat = _text().replace("\n", " ")
    i = flat.index("15 Jahre")
    assert "RISIKOPROFIL" in flat[max(0, i - 60):i].upper()
