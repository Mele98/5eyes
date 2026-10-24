from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader
from reportlab.platypus import SimpleDocTemplate

from services.cost_disclosure import calculate_cost_disclosure
from services.pdf.components.advisory_palette import (
    MARGIN_BOTTOM,
    MARGIN_LEFT,
    MARGIN_RIGHT,
    MARGIN_TOP,
    PAGE_SIZE,
    make_advisory_styles,
)
from services.pdf.components.kostenausweis import build_kostenausweis_flowables
from services.pdf.documents.advisory_report import (
    render_advisory_report_pdf_from_payload,
)
from tests.test_advisory_report_pdf import _make_minimal_payload


FOUNDATION_POSITIONS = [
    {"amount_rappen": 18_757_500, "ter_bps": 10},
    {"amount_rappen": 15_006_000, "ter_bps": 20},
    {"amount_rappen": 3_751_500, "ter_bps": 12},
    {"amount_rappen": 106_217_470, "ter_bps": 32},
    {"amount_rappen": 67_602_030, "ter_bps": 10},
    {"amount_rappen": 20_008_000, "ter_bps": 52},
    {"amount_rappen": 5_002_000, "ter_bps": 38},
    {"amount_rappen": 7_503_000, "ter_bps": 40},
    {"amount_rappen": 6_252_500, "ter_bps": 8},
]


def _foundation_disclosure() -> dict:
    return calculate_cost_disclosure(
        advisory_wealth_rappen=270_000_000,
        positions=FOUNDATION_POSITIONS,
        fee_model={"default_advisory_fee_bps": 75},
        transaction_cost_bps=15,
        source_run_id="foundation-run",
        as_of="2026-06-06T08:00:00Z",
    )


def _pdf_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _render_component(data: dict) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=PAGE_SIZE,
        topMargin=MARGIN_TOP,
        bottomMargin=MARGIN_BOTTOM,
        leftMargin=MARGIN_LEFT,
        rightMargin=MARGIN_RIGHT,
    )
    doc.build(build_kostenausweis_flowables(data, make_advisory_styles()))
    return buffer.getvalue()


def test_mx_foundation_01_cost_snapshot_is_pinned() -> None:
    data = _foundation_disclosure()

    assert data["data_pending"] is False
    assert data["advisory_wealth_rappen"] == 270_000_000
    assert data["invested_amount_rappen"] == 250_100_000
    assert data["product_cost_coverage_bps"] == 10_000
    assert data["totals"] == {
        "one_time_rappen": 375_150,
        "one_time_bps": 14,
        "annual_rappen": 2_643_834,
        "annual_bps": 98,
        "first_year_rappen": 3_018_984,
        "first_year_bps": 112,
    }
    assert data["is_complete"] is True
    assert data["has_estimates"] is True


def test_cost_items_separate_service_ter_and_transaction_costs() -> None:
    data = _foundation_disclosure()
    by_key = {item["key"]: item for item in data["cost_items"]}

    assert by_key["default_advisory_fee_bps"]["amount_rappen"] == 2_025_000
    assert by_key["product_ter"]["rate_bps"] == 25
    assert by_key["product_ter"]["amount_rappen"] == 618_834
    assert by_key["initial_transaction_costs"]["amount_rappen"] == 375_150
    assert by_key["initial_transaction_costs"]["is_estimate"] is True


def test_unknown_costs_are_not_silently_treated_as_zero() -> None:
    data = calculate_cost_disclosure(
        advisory_wealth_rappen=100_000_000,
        positions=[{"amount_rappen": 100_000_000, "ter_bps": None}],
        fee_model={},
    )

    assert data["is_complete"] is False
    assert data["totals"]["annual_rappen"] == 0
    assert all(item["key"] != "product_ter" for item in data["cost_items"])
    assert any("nicht hinterlegt" in warning for warning in data["warnings"])


def test_component_renders_concrete_totals_and_legal_basis() -> None:
    pdf = _render_component(_foundation_disclosure())
    text = _pdf_text(pdf)
    compact_text = " ".join(text.split())

    assert pdf.startswith(b"%PDF")
    assert "Kostenausweis ex-ante" in text
    assert "Beratungs-/Verwaltungsgebühr" in text
    assert "Produktkosten (gewichtete TER)" in text
    assert "Transaktionskosten Erstumsetzung" in compact_text
    assert "CHF 30'190" in text
    assert "Art. 8 und 9 FIDLEG" in compact_text
    assert "Ex-post-Kostenabrechnung" in compact_text


def test_component_renders_degraded_state_without_crash() -> None:
    pdf = _render_component({
        "data_pending": True,
        "warnings": ["Kostenbasis ist noch nicht vollständig."],
    })
    text = _pdf_text(pdf)

    assert "Kostenausweis ex-ante" in text
    assert "Daten ausstehend" in text
    assert "Kostenbasis ist noch nicht vollständig" in text


def test_advisory_pdf_places_cost_disclosure_before_compliance_audit() -> None:
    payload = _make_minimal_payload()
    payload["cost_disclosure"] = _foundation_disclosure()

    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = PdfReader(BytesIO(pdf))
    page_texts = [page.extract_text() or "" for page in reader.pages]
    cost_page = next(
        index for index, text in enumerate(page_texts)
        if "Kostenausweis ex-ante" in text
    )
    compliance_page = next(
        index for index, text in enumerate(page_texts)
        if "Compliance-Audit" in text
    )

    assert cost_page < compliance_page
    assert "CHF 26'438" in page_texts[cost_page]
    assert "CHF 30'190" in page_texts[cost_page]
