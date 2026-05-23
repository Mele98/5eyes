from __future__ import annotations

from datetime import date
from io import BytesIO

import pytest
from pypdf import PdfReader

from services.pdf.base import PDFContext, ProtokollData
from services.pdf.reportlab_renderer import ReportLabRenderer


@pytest.fixture
def ctx() -> PDFContext:
    return PDFContext(
        mandate_name="Hans Muster",
        advisor_name="Anna Berater",
        advisor_org="Muster & Partner AG",
        report_date=date(2026, 5, 23),
        audit_hash="abc123def456789012345678",
        locale="de-CH",
    )


def test_protokoll_renders_conflict_hinweis(ctx: PDFContext):
    body = (
        "Das gewuenschte Ziel Hauskauf 2032 ist mit dem aktuellen "
        "Risikoprofil Wachstumsorientiert nicht plausibel erreichbar."
    )
    data = ProtokollData(
        mandate_number="M-100001",
        advisory_wealth_rappen=1_000_000_00,
        entries=[],
        conflict_messages=[
            {
                "code": "CONFLICT_PROFILE_LIMITS",
                "severity": "conflict",
                "title": "Risikoprofil limitiert das Ziel",
                "body_advisor": body,
            }
        ],
    )

    pdf_bytes = ReportLabRenderer().render_protokoll(ctx, data)
    text = _pdf_text(pdf_bytes)

    assert pdf_bytes.startswith(b"%PDF")
    assert "DOKUMENTIERTE ZIELKONFLIKTE" in text
    assert "Im Beratungsgespr\u00e4ch wurde folgender Zielkonflikt dokumentiert" in text
    assert "Risikoprofil limitiert das Ziel" in text
    assert "Hauskauf 2032" in text
    assert "nicht plausibel erreichbar" in text


def test_protokoll_omits_conflict_hinweis_for_non_conflict_messages(ctx: PDFContext):
    data = ProtokollData(
        mandate_number="M-100001",
        advisory_wealth_rappen=1_000_000_00,
        entries=[],
        conflict_messages=[
            {
                "code": "WARN_FALLBACK",
                "severity": "warning",
                "title": "Optimierer auf Bandbreiten-Mitte zurueckgesetzt",
                "body_advisor": "Solver konnte nicht konvergieren.",
            }
        ],
    )

    pdf_bytes = ReportLabRenderer().render_protokoll(ctx, data)
    text = _pdf_text(pdf_bytes)

    assert "DOKUMENTIERTE ZIELKONFLIKTE" not in text
    assert "Im Beratungsgespr" not in text


def _pdf_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)
