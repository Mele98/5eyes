"""K2 / E2E-07 (Dok. 115): das Portfolio-PDF verspricht "Konkrete Produkte mit ISIN"
nur, wenn jede Position eine ISIN traegt. Positionen ohne ISIN (z. B. aus dem
ungeprueften Seed-Katalog) sind als "Musterprodukt – nicht zur Umsetzung"
gekennzeichnet. Keine Produktdaten werden ergaenzt oder erfunden.
"""
from __future__ import annotations

from datetime import date
from io import BytesIO

from pypdf import PdfReader

from services.pdf.base import PDFContext, PortfolioData
from services.pdf.documents.portfolio import _is_sample_position
from services.pdf.reportlab_renderer import ReportLabRenderer


def _ctx() -> PDFContext:
    return PDFContext(mandate_name="Testkunde Fiktiv", advisor_name="Beraterin Fiktiv",
                      advisor_org="Testfirma Fiktiv AG", report_date=date(2026, 11, 19),
                      audit_hash="k2e2e07k2e2e07k2e2e07k2e", locale="de-CH")


def _position(name: str, isin: str | None) -> dict:
    return {"name": name, "isin": isin, "asset_class": "equities", "sub_asset_class": "Aktien Welt",
            "target_weight_bps": 5000, "target_amount_rappen": 50_000_00, "ter_bps": 20}


def _text(positions: list[dict]) -> str:
    data = PortfolioData(mandate_number="M-K2", advisory_wealth_rappen=100_000_00, positions=positions)
    pdf = ReportLabRenderer().render_portfolio(_ctx(), data)
    return "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages)


def test_positions_without_isin_are_marked_and_no_isin_promise():
    text = _text([_position("Musterfonds A", None), _position("Belegter Fonds B", "CH0000000001")])
    assert "Konkrete Produkte mit ISIN" not in text
    assert "Musterprodukt" in text and "nicht zur Umsetzung" in text
    assert "Musterkatalog: 1 von 2 Positionen ohne ISIN" in text
    assert "ISIN CH0000000001" in text  # belegte Position unveraendert


def test_gegenprobe_all_positions_with_isin_keep_the_promise():
    text = _text([_position("Belegter Fonds B", "CH0000000001"), _position("Belegter Fonds C", "IE0000000002")])
    assert "Konkrete Produkte mit ISIN" in text
    assert "Musterprodukt" not in text and "Musterkatalog" not in text


def test_sample_criterion_is_missing_isin_only():
    assert _is_sample_position({"isin": None})
    assert _is_sample_position({"isin": "  "})
    assert _is_sample_position({})
    assert not _is_sample_position({"isin": "CH0000000001"})
