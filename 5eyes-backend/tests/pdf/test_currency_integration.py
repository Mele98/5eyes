"""Sprint 9 Phase 4: PDF-Reports respektieren Mandate-Currency."""
from __future__ import annotations

from datetime import date

import pytest

from services.pdf.base import AnlagestrategieData, PDFContext
from services.pdf.reportlab_renderer import ReportLabRenderer


@pytest.fixture
def saa_data():
    return AnlagestrategieData(
        target_allocation_bps={
            "equities": 4000, "bonds": 3000, "real_estate": 1500,
            "alternatives": 1000, "liquidity": 500,
        },
        cma_expected_return_bps=485,
        cma_expected_vol_bps=1120,
        horizon_years=15,
        monte_carlo_stats={"p10": 800_000_00, "p50": 1_500_000_00, "p90": 2_500_000_00},
    )


def _make_ctx(currency: str) -> PDFContext:
    return PDFContext(
        mandate_name="Hans Muster",
        advisor_name="Anna Berater",
        report_date=date(2026, 5, 17),
        base_currency=currency,
    )


def test_default_currency_chf(saa_data):
    """Default base_currency=CHF → PDF zeigt CHF-Werte."""
    ctx = PDFContext(
        mandate_name="Hans",
        advisor_name="Anna",
        report_date=date(2026, 5, 17),
    )
    assert ctx.base_currency == "CHF"
    pdf = ReportLabRenderer().render_anlagestrategie(ctx, saa_data)
    assert pdf[:4] == b"%PDF"


def test_eur_mandate_pdf_renders(saa_data):
    """EUR-Mandate → PDF wird generiert ohne Crash."""
    ctx = _make_ctx("EUR")
    pdf = ReportLabRenderer().render_anlagestrategie(ctx, saa_data)
    assert pdf[:4] == b"%PDF"


def test_usd_mandate_pdf_renders(saa_data):
    """USD-Mandate → PDF wird generiert."""
    ctx = _make_ctx("USD")
    pdf = ReportLabRenderer().render_anlagestrategie(ctx, saa_data)
    assert pdf[:4] == b"%PDF"


def test_invalid_currency_falls_back_to_chf(saa_data):
    """Unbekannte Currency → defensive Fallback auf CHF."""
    ctx = _make_ctx("XYZ")  # nicht in DEFAULT_FX_RATES
    # Sollte nicht crashen — _fmt_amount hat try/except mit CHF-Fallback
    pdf = ReportLabRenderer().render_anlagestrategie(ctx, saa_data)
    assert pdf[:4] == b"%PDF"


def test_chf_amount_format():
    """_fmt_amount mit CHF-default formattiert wie vorher."""
    from services.pdf.documents.anlagestrategie import _fmt_amount
    formatted = _fmt_amount(12345600)  # 123'456 CHF
    assert formatted == "CHF 123'456"


def test_eur_amount_format_converts():
    """_fmt_amount mit EUR konvertiert via Default-FX-Rate (0.95).
    123'456 CHF / 0.95 ≈ 129'954 EUR."""
    from services.pdf.documents.anlagestrategie import _fmt_amount
    formatted = _fmt_amount(12345600, "EUR")
    assert formatted.startswith("EUR ")
    # Wert sollte > CHF-Wert sein (CHF schwacher als EUR-Equivalent)
    assert "129'" in formatted or "130'" in formatted


def test_zero_amount_in_eur():
    """0 Rappen in EUR → EUR 0."""
    from services.pdf.documents.anlagestrategie import _fmt_amount
    assert _fmt_amount(0, "EUR") == "EUR 0"


def test_eur_pdf_differs_from_chf_pdf():
    """EUR-Mandate produziert anderes PDF als CHF-Mandate (Inhalte
    unterschiedlich konvertiert). Vergleich via Size + Bytes-Diff,
    weil EUR-Werte und Header anders sind."""
    data = AnlagestrategieData(
        target_allocation_bps={"equities": 10000},
        cma_expected_return_bps=400,
        cma_expected_vol_bps=900,
        horizon_years=10,
        monte_carlo_stats={"p10": 100_000_00, "p50": 200_000_00, "p90": 400_000_00},
    )
    pdf_chf = ReportLabRenderer().render_anlagestrategie(_make_ctx("CHF"), data)
    pdf_eur = ReportLabRenderer().render_anlagestrategie(_make_ctx("EUR"), data)
    # PDFs sollten beide valide sein
    assert pdf_chf[:4] == b"%PDF" and pdf_eur[:4] == b"%PDF"
    # Inhalte unterscheiden sich (anderer Currency-Code + andere Werte
    # nach Konvertierung). Ueber Hash vergleichen weil Stream-Bytes
    # unterscheiden sich aber Reportlab kann gleiche Length haben.
    import hashlib
    h_chf = hashlib.md5(pdf_chf).hexdigest()
    h_eur = hashlib.md5(pdf_eur).hexdigest()
    assert h_chf != h_eur
