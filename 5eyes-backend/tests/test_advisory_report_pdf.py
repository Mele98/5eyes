"""Sprint U-P26 PR A — Tests fuer den Advisory-Report Server-PDF.

PR A deckt nur Cover + Disclaimer + TOC ab. Spaetere Sprints fuegen
weitere Sektion-Tests hinzu.

Test-Strategie:
- `render_advisory_report_pdf_from_payload` mit Inline-Payload —
  schnell, kein DB-Setup, deterministisch
- Bytes-Smoke + ein Mini-Text-Scan auf erwartete Inhalte
- KEIN Pixel-Perfect-Test (zu fragil), aber strukturelle Assertions

ReportLab schreibt Strings im PDF teils mit hex-encoding (FEFF…) — wir
testen über `pypdf.PdfReader` der das transparent dekodiert.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


from services.pdf.documents.advisory_report import (  # noqa: E402
    render_advisory_report_pdf_from_payload,
)


def _make_minimal_payload() -> dict:
    """Liefert ein gültiges Aggregator-ähnliches Payload mit Minimal-Daten
    für Cover/Disclaimer/TOC."""
    return {
        "schema_version": 2,
        "mandate_id": "test-mandate-id",
        "generated_at": "2026-05-27T14:32:00.000Z",
        "cover": {
            "title": "Depotcheck",
            "subtitle": "Strategische Portfolioanalyse",
            "client_name": "Hans Muster",
            "mandate_number": "MX-FOUNDATION-01",
            "report_date": "2026-05-27",
            "advisor_name": "Anna Beispiel",
        },
        "disclaimer": {
            "hinweise": [
                "Dieser Bericht dient ausschliesslich Beratungszwecken.",
                "Vergangene Performance ist kein Indikator fuer kuenftige Renditen.",
                "Monte-Carlo-Simulationen sind Modellrechnungen mit Modell-Risiken.",
            ],
        },
        "inhaltsverzeichnis": {
            "kapitel": [
                {"nr": 1, "title": "Ausgangslage"},
                {"nr": 2, "title": "Übersicht Ihrer Positionen"},
                {"nr": 3, "title": "Was wir im Depotcheck prüfen"},
            ],
        },
    }


# ---------------------------------------------------------------------------
# 1) Bytes-Smoke: gibt PDF-Bytes zurück
# ---------------------------------------------------------------------------

def test_render_returns_pdf_bytes():
    payload = _make_minimal_payload()
    pdf = render_advisory_report_pdf_from_payload(payload)
    assert isinstance(pdf, (bytes, bytearray))
    assert len(pdf) > 1000, "PDF wirkt verdaechtig klein"
    assert pdf[:5] == b"%PDF-", "Magic Bytes fehlen — kein PDF"


# ---------------------------------------------------------------------------
# 2) Strukturelle Assertions via pypdf
# ---------------------------------------------------------------------------

def test_pdf_has_at_least_three_pages_cover_disclaimer_toc():
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    # Cover + Disclaimer + TOC → mindestens 3 Seiten (kann mehr sein bei
    # langem Disclaimer-Text)
    assert len(reader.pages) >= 3, (
        f"Erwartet mindestens 3 Seiten (Cover/Disclaimer/TOC), "
        f"PDF hat {len(reader.pages)}"
    )


def test_cover_contains_mandate_and_client_and_advisor():
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    cover_text = reader.pages[0].extract_text() or ""
    # Mandat-Nummer + Client + Advisor müssen auf dem Cover sein
    assert "MX-FOUNDATION-01" in cover_text, (
        f"Mandat-Nr. nicht im Cover gefunden. Cover-Text: {cover_text[:300]}"
    )
    assert "Hans Muster" in cover_text
    assert "Anna Beispiel" in cover_text


def test_cover_uses_swiss_date_format():
    """Swiss-Format DD.MM.YYYY (nicht ISO YYYY-MM-DD)."""
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    cover_text = reader.pages[0].extract_text() or ""
    assert "27.05.2026" in cover_text, (
        f"Swiss-Datum fehlt. Cover-Text: {cover_text[:300]}"
    )
    # ISO-Variante darf nicht durchschlagen
    assert "2026-05-27" not in cover_text, (
        "ISO-Datum 2026-05-27 sollte nicht im Cover sein (Swiss-Format erwartet)"
    )


def test_disclaimer_lists_all_hinweise():
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    disclaimer_text = reader.pages[1].extract_text() or ""
    assert "Rechtliche Hinweise" in disclaimer_text
    for hinweis in payload["disclaimer"]["hinweise"]:
        # Erstes Wort als Indicator (Substring-Match wegen Umbrueche)
        first_words = hinweis.split(".")[0][:30]
        assert first_words in disclaimer_text, (
            f"Hinweis '{first_words}…' fehlt im Disclaimer"
        )


def test_toc_lists_kapitel_in_order():
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    toc_text = reader.pages[2].extract_text() or ""
    assert "Inhaltsverzeichnis" in toc_text
    # Reihenfolge der Kapitel muss erhalten sein
    titles = [k["title"] for k in payload["inhaltsverzeichnis"]["kapitel"]]
    positions = [toc_text.find(t) for t in titles]
    assert all(p >= 0 for p in positions), (
        f"Mindestens ein Kapitel fehlt im TOC. Positionen: {positions}"
    )
    assert positions == sorted(positions), (
        f"Kapitel-Reihenfolge nicht respektiert: {positions}"
    )


# ---------------------------------------------------------------------------
# 3) Branding-Disziplin: keine Dritt-Marken im PDF
# ---------------------------------------------------------------------------

def test_pdf_contains_no_third_party_brands():
    """Memory-Regel: NIE Swiss Life, 3eyes etc. in Code/PDF/Texten."""
    pypdf = pytest.importorskip("pypdf")
    payload = _make_minimal_payload()
    pdf = render_advisory_report_pdf_from_payload(payload)
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    all_text = "\n".join((p.extract_text() or "") for p in reader.pages).lower()
    forbidden = ["swiss life", "3eyes", "ubs", "pictet", "julius bär"]
    for term in forbidden:
        assert term not in all_text, f"Verbotene Marke '{term}' im PDF gefunden"


# ---------------------------------------------------------------------------
# 4) Defensiv gegen leere/fehlende Felder
# ---------------------------------------------------------------------------

def test_render_handles_missing_optional_fields():
    payload = {
        "schema_version": 2,
        "mandate_id": "x",
        "generated_at": "",
        "cover": {},
        "disclaimer": {},
        "inhaltsverzeichnis": {},
    }
    pdf = render_advisory_report_pdf_from_payload(payload)
    assert pdf[:5] == b"%PDF-"
    assert len(pdf) > 500


def test_render_handles_special_characters_in_names():
    """XSS-style mini-HTML in Client-Name darf das Layout nicht brechen."""
    payload = _make_minimal_payload()
    payload["cover"]["client_name"] = "<script>alert('xss')</script> & Co."
    pdf = render_advisory_report_pdf_from_payload(payload)
    assert pdf[:5] == b"%PDF-"

    pypdf = pytest.importorskip("pypdf")
    reader = pypdf.PdfReader(__import__("io").BytesIO(pdf))
    cover_text = reader.pages[0].extract_text() or ""
    # Der escape-Mechanismus muss den literal Text rendern, nicht als HTML
    # interpretieren. Substring-Test reicht.
    assert "script" in cover_text  # der Text ist drin, aber als literal
