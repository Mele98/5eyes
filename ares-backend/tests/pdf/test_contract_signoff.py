from __future__ import annotations

from datetime import date
from io import BytesIO

from pypdf import PdfReader

from services.pdf.base import ContractSignoffData, PDFContext
from services.pdf.reportlab_renderer import ReportLabRenderer


def _ctx() -> PDFContext:
    return PDFContext(
        mandate_name="Kundin Beispiel",
        advisor_name="Berater Beispiel",
        advisor_org="Beratungshaus",
        report_date=date(2026, 6, 7),
        audit_hash="signoff-audit",
    )


def _data(*, overridden: bool = True) -> ContractSignoffData:
    return ContractSignoffData(
        mandate_number="M-SIGN-01",
        advisory_wealth_rappen=750_000_00,
        risk_profile_label="Ausgewogen",
        risk_is_overridden=overridden,
        risk_override_reason="Kundenwunsch nach dokumentierter Besprechung",
        strategy_name="Zielstrategie Ausgewogen",
        strategy_method="stochastic",
        limiting_factor="risikoprofil",
        target_allocation_bps={
            "equities": 4500,
            "bonds": 3000,
            "real_estate": 1000,
            "alternatives": 1000,
            "liquidity": 500,
        },
        bucket_bands_bps={
            "equities": (4000, 5000),
            "bonds": (2500, 3500),
            "real_estate": (500, 1500),
            "alternatives": (500, 1500),
            "liquidity": (250, 1000),
        },
        sub_allocations=[
            {
                "asset_class": "equities",
                "sub_asset_class": "Aktien Welt",
                "weight_bps": 3000,
                "amount_rappen": 225_000_00,
                "products": 2,
            },
            {
                "asset_class": "equities",
                "sub_asset_class": "Aktien Schweiz",
                "weight_bps": 1500,
                "amount_rappen": 112_500_00,
                "products": 1,
            },
            {
                "asset_class": "bonds",
                "sub_asset_class": "Obligationen CHF",
                "weight_bps": 3000,
                "amount_rappen": 225_000_00,
                "products": 2,
            },
        ],
        portfolio_orientation=(
            "Globale Kernanlage mit dokumentiertem Schweiz-Fokus und "
            "waehrungsabgesicherten Obligationen."
        ),
        consultation_summary=[
            {
                "entry_date": "2026-06-01",
                "title": "Risikoprofil",
                "decision": "Risikoprofil und Override gemeinsam besprochen.",
            },
            {
                "entry_date": "2026-06-03",
                "title": "Zielallokation",
                "decision": "Bandbreiten und Kosten offengelegt.",
            },
        ],
        final_recommendation=(
            "Umsetzung der dokumentierten Zielstrategie innerhalb der "
            "festgehaltenen Bandbreiten."
        ),
    )


def _text(pdf: bytes) -> tuple[PdfReader, str]:
    reader = PdfReader(BytesIO(pdf))
    return reader, "\n".join(page.extract_text() or "" for page in reader.pages)


def test_contract_signoff_contains_all_decision_sections():
    reader, text = _text(
        ReportLabRenderer().render_contract_signoff(_ctx(), _data())
    )

    assert len(reader.pages) == 7
    for anchor in (
        "Risikoprofil und Strategiewahl",
        "Zielallokation und Bandbreiten",
        "Subanlageklassen und Ausrichtung",
        "Beratungsinhalt und Empfehlung",
        "Aufklaerung und Bestaetigung",
        "Band Min",
        "Band Max",
        "Aktien Welt",
        "FINALE EMPFEHLUNG",
    ):
        assert anchor in text


def test_contract_signoff_documents_override_and_reason():
    _, text = _text(
        ReportLabRenderer().render_contract_signoff(_ctx(), _data(overridden=True))
    )
    normalized = " ".join(text.split())

    assert "Manueller Risikoprofil-Override dokumentiert" in text
    assert "Kundenwunsch nach dokumentierter Besprechung" in text
    assert "ausdruecklich besprochen und bestaetigt" in normalized


def test_contract_signoff_documents_no_override():
    _, text = _text(
        ReportLabRenderer().render_contract_signoff(_ctx(), _data(overridden=False))
    )

    assert "Kein manueller Override" in text
    assert "basiert auf dem dokumentierten Risikoprofil" in text


def test_contract_signoff_contains_fidleg_revdsg_and_signatures():
    _, text = _text(
        ReportLabRenderer().render_contract_signoff(_ctx(), _data())
    )

    assert "Geeignetheit" in text
    assert "revDSG" in text
    assert "Ort, Datum / Klient" in text
    assert "Ort, Datum / Anlageberater" in text
    assert "keine Zusicherungen" in text
