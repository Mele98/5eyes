"""DEPOT-E2E-IDENTITY-001 (P1, open).

Audit: docs/audits/2026-10-05-depotcheck-end-to-end-product-identity-and-
publication-integrity-audit.md (Ares worktree
"5eyes wird zu Ares/asset-allocation-stochastic-core").

Finding: the Depot-Check feature is two incompatible products sharing one
name.

- The HTML modal (5eyes-electron/frontend/5eyes_v2.html, "Depot-Check-Modal",
  id="m-dc") is positioned as a live IST-vs-SOLL drift check: it shows
  "Asset-Klassen-Drift (IST vs SOLL)" and the modal's own PDF-export button
  is tooltipped "Server-PDF: Depot-Check mit Drift, Diversifikation,
  Stress-Replays" -- i.e. the UI promises drift / IST-vs-SOLL content in the
  exported PDF.
- The actual PDF builder (services/pdf/documents/depotcheck.py,
  ReportLabRenderer.render_depotcheck) is INTENTIONALLY target-only
  (SOLL-only): its own test suite (tests/pdf/test_depotcheck_soll_analysis.py)
  explicitly forbids "IST vs." and "Drift-Tabelle" from ever appearing in the
  rendered output.

This test mechanically proves the mismatch: it extracts the modal's PDF
button promise from the real HTML source, and independently renders the
real depot-check PDF from a realistic payload (seeded the same way as
tests/pdf/test_depotcheck_soll_analysis.py does), then asserts that a UI
promising IST-vs-SOLL drift content must be backed by a PDF that actually
contains IST/drift evidence. It does not today -- this is the documented
bug, not a test bug. Wrapped in xfail(strict=True) so the suite stays green
while the mismatch remains open pending a product-identity decision (merge
the two products, or stop promising drift in the PDF-export UI).

Do not "fix" this test by loosening the assertions -- the fix belongs in
the product (UI copy and/or PDF content), not in the test.
"""
from __future__ import annotations

import sys
from datetime import date
from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfReader

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.pdf.base import DepotCheckData, PDFContext  # noqa: E402
from services.pdf.reportlab_renderer import ReportLabRenderer  # noqa: E402

HTML_PATH = BACKEND_ROOT.parent / "5eyes-electron" / "frontend" / "5eyes_v2.html"


def _html_text() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def _depotcheck_modal(text: str) -> str:
    start = text.find('<div class="overlay" id="m-dc">')
    assert start > 0, "Depot-Check-Modal (id=m-dc) fehlt im HTML"
    end = text.find('<div class="overlay"', start + 1)
    assert end > start, "Folge-Modal-Marker nach m-dc nicht gefunden"
    return text[start:end]


def _pdf_button_promise(modal: str) -> str:
    """Extract the title= tooltip of the modal's own PDF-export button."""
    anchor = "downloadServerPdf('depotcheck')"
    idx = modal.find(anchor)
    assert idx > 0, "PDF-Export-Button fuer 'depotcheck' fehlt im Modal"
    title_start = modal.find('title="', idx)
    assert title_start > idx, "title=-Tooltip am PDF-Export-Button fehlt"
    title_start += len('title="')
    title_end = modal.find('"', title_start)
    return modal[title_start:title_end]


def _ui_promises_ist_vs_soll_drift(modal: str) -> bool:
    """Does the modal itself (not just the button) advertise IST-vs-SOLL drift?"""
    return "IST vs SOLL" in modal or "IST vs. SOLL" in modal


def _context() -> PDFContext:
    # Seeded the same way as tests/pdf/test_depotcheck_soll_analysis.py's
    # _context(), to build a realistic depot-check PDF rendering context.
    return PDFContext(
        mandate_name="Muster Mandat",
        advisor_name="Anna Beratung",
        advisor_org="Beratungshaus",
        report_date=date(2026, 6, 7),
        audit_hash="depot-e2e-identity-001-test",
    )


def _data() -> DepotCheckData:
    # Seeded the same way as tests/pdf/test_depotcheck_soll_analysis.py's
    # _data(): a realistic, fully-populated depot-check payload as the
    # renderer actually receives it in production.
    return DepotCheckData(
        mandate_number="M-SOLL-01",
        total_advisory_wealth_rappen=1_000_000_00,
        target_allocation_bps={
            "equities": 5000,
            "bonds": 2500,
            "real_estate": 1000,
            "alternatives": 1000,
            "liquidity": 500,
        },
        bucket_bands_bps={
            "equities": (4500, 5500),
            "bonds": (2000, 3000),
            "real_estate": (500, 1500),
            "alternatives": (500, 1500),
            "liquidity": (250, 1000),
        },
        sub_allocations=[
            {
                "asset_class": "equities",
                "sub_asset_class": "Aktien Welt",
                "weight_bps": 3500,
                "amount_rappen": 350_000_00,
                "products": 2,
            },
            {
                "asset_class": "bonds",
                "sub_asset_class": "Obligationen CHF",
                "weight_bps": 2500,
                "amount_rappen": 250_000_00,
                "products": 2,
            },
        ],
        risk_profile_label="Ausgewogen",
        risk_metrics={
            "expected_return_bps": 430,
            "expected_vol_bps": 890,
            "max_drawdown_bps": 2200,
            "var_95_bps": 1450,
            "horizon_years": 12,
        },
        soll_country_exposure_bps={"Schweiz": 3500, "USA": 3000, "Europa": 2000, "Asien": 1500},
        soll_sector_exposure_bps={"Technologie": 2500, "Finanzen": 2200, "Industrie": 1800},
        soll_currency_exposure_bps={"CHF": 5200, "USD": 3000, "EUR": 1800},
        soll_concentration_hhi={
            "country": 2600,
            "sector": 1800,
            "currency": 3900,
            "top_positions": 1450,
        },
        top_positions=[
            {
                "product_name": "Globaler Aktienfonds",
                "isin": "CH0000000001",
                "sub_asset_class": "Aktien Welt",
                "weight_bps": 1800,
                "amount_rappen": 180_000_00,
            },
        ],
        stress_scenarios=[
            {
                "label": "Finanzkrise",
                "period": "2008-2009",
                "cumulative_return_bps": -1800,
                "max_drawdown_bps": 2400,
                "recovery_months": 28,
            }
        ],
        cost_disclosure={
            "data_pending": False,
            "cost_items": [
                {
                    "label": "Produktkosten",
                    "frequency": "jaehrlich",
                    "rate_bps": 35,
                    "amount_rappen": 3_500_00,
                    "basis_label": "Zielportfolio",
                }
            ],
            "totals": {
                "one_time_bps": 15,
                "one_time_rappen": 1_500_00,
                "annual_bps": 35,
                "annual_rappen": 3_500_00,
                "first_year_bps": 50,
                "first_year_rappen": 5_000_00,
            },
        },
        performance={
            "data_pending": False,
            "wealth_path_rappen": [
                (2019, 100_000_00),
                (2020, 106_000_00),
                (2021, 115_000_00),
            ],
            "benchmark_wealth_path_rappen": [
                (2019, 100_000_00),
                (2020, 104_000_00),
                (2021, 111_000_00),
            ],
            "metrics": {
                "total_return_bps": 1900,
                "cagr_bps": 444,
                "vol_bps": 820,
                "sharpe_x100": 44,
                "max_drawdown_bps": 610,
                "best_year_bps": 850,
                "worst_year_bps": -610,
                "win_rate_x100": 7500,
                "positive_years": 3,
                "years_count": 3,
                "start_value_rappen": 100_000_00,
                "end_value_rappen": 115_000_00,
            },
            "benchmark_metrics": {
                "total_return_bps": 1500,
                "cagr_bps": 356,
                "vol_bps": 760,
                "sharpe_x100": 36,
                "max_drawdown_bps": 450,
                "best_year_bps": 670,
                "worst_year_bps": -450,
                "win_rate_x100": 7500,
                "positive_years": 3,
                "years_count": 3,
                "start_value_rappen": 100_000_00,
                "end_value_rappen": 111_000_00,
            },
        },
        qualitative_assessment=(
            "Die Zielstruktur ist breit diversifiziert und fuer die "
            "dokumentierte Beratung nachvollziehbar."
        ),
    )


def _render_pdf_text() -> str:
    pdf_bytes = ReportLabRenderer().render_depotcheck(_context(), _data())
    reader = PdfReader(BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def test_ui_promise_is_real_and_current():
    """Sanity check (must stay green): the UI really does promise
    IST-vs-SOLL drift content for the Depot-Check PDF export today."""
    modal = _depotcheck_modal(_html_text())
    assert _ui_promises_ist_vs_soll_drift(modal), (
        "Modal wirbt nicht (mehr) mit 'IST vs SOLL' -- DEPOT-E2E-IDENTITY-001 "
        "waere dann obsolet, bitte Audit-Status pruefen."
    )
    promise = _pdf_button_promise(modal)
    assert "Drift" in promise, (
        "PDF-Export-Button verspricht kein Drift mehr -- "
        "DEPOT-E2E-IDENTITY-001 waere dann obsolet, bitte Audit-Status pruefen."
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEPOT-E2E-IDENTITY-001: Das Depot-Check-Modal und sein eigener "
        "PDF-Export-Button versprechen 'Depot-Check mit Drift, Diversifikation, "
        "Stress-Replays' / 'Asset-Klassen-Drift (IST vs SOLL)', aber "
        "ReportLabRenderer.render_depotcheck() ist vertraglich (eigene Testsuite "
        "tests/pdf/test_depotcheck_soll_analysis.py) auf eine reine SOLL-Analyse "
        "festgelegt und verbietet 'IST vs.' / 'Drift-Tabelle' im Rendering. Die "
        "UI verspricht ein Produkt, das der PDF-Renderer nicht liefert. Fix "
        "erfordert eine Produkt-Identitaets-Entscheidung (Produkte zusammen- "
        "fuehren oder PDF-Export-Werbung in der UI entschaerfen) -- siehe "
        "docs/audits/2026-10-05-depotcheck-end-to-end-product-identity-and-"
        "publication-integrity-audit.md."
    ),
)
def test_pdf_export_delivers_on_ui_drift_promise():
    modal = _depotcheck_modal(_html_text())
    assert _ui_promises_ist_vs_soll_drift(modal)
    promise = _pdf_button_promise(modal)
    assert "Drift" in promise

    pdf_text = _render_pdf_text()

    # If the UI promises IST-vs-SOLL drift content for the PDF export, the
    # rendered PDF must actually contain IST/drift evidence somewhere.
    has_ist_evidence = ("IST vs" in pdf_text) or ("Ist-Wert" in pdf_text) or (
        "Drift-Tabelle" in pdf_text
    )
    assert has_ist_evidence, (
        "UI verspricht 'Drift'/'IST vs SOLL' fuer den Depot-Check-PDF-Export, "
        "aber der tatsaechlich gerenderte PDF-Text enthaelt keinen IST/Drift-"
        "Beleg (render_depotcheck liefert nur eine SOLL-Analyse)."
    )
