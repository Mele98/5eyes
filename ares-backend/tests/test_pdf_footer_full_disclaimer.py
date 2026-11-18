"""Kunden-PDF-Fusszeile: der FIDLEG-Disclaimer wird vollstaendig ausgegeben.

Befund (Live-Test 2026-11): ``services/pdf/components/footer.py`` kuerzte
Disclaimer + Datum auf 220 Zeichen. In JEDEM Kunden-PDF endete der Pflichttext
mit "Vergan...", es fehlten der Satz "Vergangenheitswerte sind kein
verlaesslicher Indikator fuer zukuenftige Ergebnisse." und "Erstellt am".

Pruefung per PDF-Textextraktion je Dokumenttyp des ReportLab-Renderers. Der
Solltext kommt aus dem Laenderpaket (``legal.footer.disclaimer``), nicht aus
einer Kopie im Test. Gegenprobe: mit wieder eingebauter Kuerzung rot.
"""
from __future__ import annotations

import re
from datetime import date
from io import BytesIO

import pytest
from pypdf import PdfReader

from jurisdictions.documents import default_documents
from services.pdf import base
from services.pdf.components.footer import FOOTER_DISCLAIMER_KEY
from services.pdf.reportlab_renderer import ReportLabRenderer

CTX = base.PDFContext(
    mandate_name="Muster Person",
    advisor_name="Berater Muster",
    advisor_org="Muster AG",
    report_date=date(2026, 11, 2),
    audit_hash="abc123def456789012345678",
    locale="de-CH",
)

_AS = dict(
    target_allocation_bps={"equities": 5000, "bonds": 4000, "liquidity": 1000},
    cma_expected_return_bps=400, cma_expected_vol_bps=800, horizon_years=10,
)

DOCS = {
    "anlagestrategie": lambda r: r.render_anlagestrategie(CTX, base.AnlagestrategieData(**_AS)),
    "asset_allocation": lambda r: r.render_asset_allocation(CTX, base.AnlagestrategieData(**_AS)),
    "risikoprofil": lambda r: r.render_risikoprofil(CTX, base.RisikoprofilData(
        risk_profile_label="Ausgewogen", risk_capacity_score=50, risk_tolerance_score=50)),
    "portfolio": lambda r: r.render_portfolio(CTX, base.PortfolioData()),
    "vertrag": lambda r: r.render_vertrag(CTX, base.VertragData()),
    "contract_signoff": lambda r: r.render_contract_signoff(CTX, base.ContractSignoffData()),
    "protokoll": lambda r: r.render_protokoll(CTX, base.ProtokollData()),
    "depotcheck": lambda r: r.render_depotcheck(CTX, base.DepotCheckData()),
    "cost_disclosure": lambda r: r.render_cost_disclosure(CTX, base.CostDisclosurePDFData()),
    "backtest": lambda r: r.render_backtest(CTX, base.BacktestData()),
}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


@pytest.mark.parametrize("doc", sorted(DOCS))
def test_every_page_carries_full_disclaimer_and_creation_date(doc):
    disclaimer = _norm(default_documents().text(FOOTER_DISCLAIMER_KEY))
    assert disclaimer.endswith("Ergebnisse."), "Laenderpaket-Text unerwartet"
    pdf = DOCS[doc](ReportLabRenderer())
    pages = PdfReader(BytesIO(pdf)).pages
    assert pages
    for number, page in enumerate(pages, start=1):
        text = _norm(page.extract_text() or "")
        assert disclaimer in text, f"{doc} S.{number}: Disclaimer unvollstaendig"
        assert "Erstellt am 02.11.2026" in text, f"{doc} S.{number}: Erstelldatum fehlt"
        assert "Vergan..." not in text
