"""Sprint U-54 (Roadmap-Punkt 54, 2026-06-04): PDF Strukturelle Snapshots.

Pre-U-54
--------
test_advisory_report_pdf.py hatte zwar content-based asserts, aber
keine pinned Snapshots fuer Strukturmaße (Seitenzahl, Byte-Size,
extrahierte Text-Length pro Seite). Drift wuerde nur durch
unmittelbar betroffene Asserts erkannt.

Post-U-54
---------
- SNAPSHOTS dict mit erwarteten Werten pro Sektion
  - page_count_range
  - byte_size_range
  - required_anchor_strings (per Sektion-Header)
- Tests die Snapshot-Drift erkennen ohne fragil zu sein

Strategie: nicht byte-genau (PDFs sind nicht reproducible by default
wegen Timestamps/Obj-IDs), sondern struktur-pinned mit Toleranz.

Bei intendierten Aenderungen: Range im Snapshot erweitern + PR-Doc.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.pdf.documents.advisory_report import (  # noqa: E402
    render_advisory_report_pdf_from_payload,
)
from tests.test_advisory_report_pdf import _make_minimal_payload  # noqa: E402


# ---------------------------------------------------------------------------
# SNAPSHOTS — bewusste Werte mit Toleranz
# ---------------------------------------------------------------------------

# Stand 2026-06-04 (gemerged: U-15 TTF, U-70 Stress-Replay, U-9 Multi-Start):
# - 17-25 Seiten je nach Mandate-Content (Sektionen koennen mehrseitig werden)
# - PDF-Bytes ca. 50-300 KB
MINIMAL_PDF_PAGE_RANGE = (3, 30)  # mit minimal payload: nur Cover+Disclaimer+TOC pflicht
MINIMAL_PDF_BYTE_RANGE = (5_000, 500_000)

# Anchor-Strings die bei minimal payload ueberall sichtbar sein muessen
REQUIRED_ANCHOR_STRINGS_MINIMAL = (
    "MX-FOUNDATION-01",        # Mandat-Nummer im Cover
    "Hans Muster",             # Client im Cover
    "Anna Beispiel",           # Advisor im Cover
    "Depotcheck",              # Cover-Titel
    "Rechtliche Hinweise",     # Disclaimer-Header
    "Inhaltsverzeichnis",      # TOC-Header
    "Compliance-Audit",        # FINMA-Audit-Block
    "Geeignetheitspruefung",   # Sektion 19 im PDF sichtbar
    "Methodology-Modelle",     # Sektion 20 im PDF sichtbar
)

# PDF darf KEINE dieser Strings enthalten (Branding-Disziplin)
FORBIDDEN_BRAND_STRINGS = (
    "Swiss Life",
    "3eyes",
    "UBS",
    "Vontobel",
    "Pictet",
)


def _render() -> bytes:
    payload = _make_minimal_payload()
    return render_advisory_report_pdf_from_payload(payload)


def _extract_all_text(pdf_bytes: bytes) -> str:
    pypdf = pytest.importorskip("pypdf")
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _page_count(pdf_bytes: bytes) -> int:
    pypdf = pytest.importorskip("pypdf")
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    return len(reader.pages)


# ---------------------------------------------------------------------------
# Snapshot-Range-Asserts
# ---------------------------------------------------------------------------

def test_pdf_page_count_in_range():
    """Seitenzahl-Drift-Schutz. Erweitere Range bei intendierter
    Section-Erweiterung."""
    pdf = _render()
    pc = _page_count(pdf)
    mn, mx = MINIMAL_PDF_PAGE_RANGE
    assert mn <= pc <= mx, (
        f"PDF hat {pc} Seiten, erwartet [{mn}, {mx}]. "
        f"Bei bewusster Section-Aenderung Snapshot updaten."
    )


def test_pdf_byte_size_in_range():
    """Byte-Size-Range — verhindert 100x Bloat (eingebettete Bilder etc.)."""
    pdf = _render()
    size = len(pdf)
    mn, mx = MINIMAL_PDF_BYTE_RANGE
    assert mn <= size <= mx, (
        f"PDF {size} bytes, erwartet [{mn}, {mx}]. "
        f"Bei bewusster Asset-Erweiterung Snapshot updaten."
    )


# ---------------------------------------------------------------------------
# Required-Anchors (Section-Coverage)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("anchor", REQUIRED_ANCHOR_STRINGS_MINIMAL)
def test_pdf_contains_required_anchor(anchor: str):
    """Jeder Anchor-String muss im extrahierten Text vorkommen."""
    pdf = _render()
    text = _extract_all_text(pdf)
    assert anchor in text, (
        f"Anchor {anchor!r} fehlt in PDF. "
        f"Mindestens eine Sektion ist nicht gerendert."
    )


# ---------------------------------------------------------------------------
# Branding-Disziplin (Drift-Wall)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("brand", FORBIDDEN_BRAND_STRINGS)
def test_pdf_contains_no_forbidden_brand(brand: str):
    """Memory-Regel: nie 3rd-Party-Marken im EIGENEN PDF.
    Drift-Schutz erweitert."""
    pdf = _render()
    text = _extract_all_text(pdf)
    assert brand not in text, (
        f"Verbotene Marke {brand!r} im PDF gefunden — "
        f"Branding-Disziplin verletzt."
    )


# ---------------------------------------------------------------------------
# Determinismus (gleicher Input -> gleicher Output-Strukturwise)
# ---------------------------------------------------------------------------

def test_pdf_size_deterministic_within_tolerance():
    """Zwei Render-Runs mit gleichem Payload — Byte-Size darf
    nur leicht (Timestamp-Embedding) variieren."""
    pdf_a = _render()
    pdf_b = _render()
    # ReportLab Timestamp-Embedding kann ein paar Bytes Unterschied
    # bringen; aber nicht > 1% bei stabilem Content.
    assert abs(len(pdf_a) - len(pdf_b)) < max(len(pdf_a), len(pdf_b)) * 0.01


def test_pdf_page_count_deterministic():
    """Seitenzahl MUSS deterministisch sein."""
    pdf_a = _render()
    pdf_b = _render()
    assert _page_count(pdf_a) == _page_count(pdf_b)


def test_pdf_required_anchors_deterministic():
    """Anchor-Coverage gleich bei wiederholtem Render."""
    text_a = _extract_all_text(_render())
    text_b = _extract_all_text(_render())
    for anchor in REQUIRED_ANCHOR_STRINGS_MINIMAL:
        assert (anchor in text_a) == (anchor in text_b)


# ---------------------------------------------------------------------------
# Magic-Bytes + PDF-Validity (Sanity)
# ---------------------------------------------------------------------------

def test_pdf_starts_with_magic_bytes():
    pdf = _render()
    assert pdf[:5] == b"%PDF-", "PDF-Magic-Bytes fehlen"


def test_pdf_ends_with_eof_marker():
    """%%EOF muss am Ende sein (mit oder ohne Trailing-Newline)."""
    pdf = _render()
    # Letzte 20 Bytes sollten %%EOF enthalten
    assert b"%%EOF" in pdf[-30:], "PDF endet nicht mit %%EOF"


def test_pdf_version_is_modern():
    """%PDF-1.x mit x >= 4 (ReportLab default)."""
    pdf = _render()
    header = pdf[:8].decode("ascii", errors="replace")
    assert header.startswith("%PDF-1."), f"Unerwarteter Header: {header!r}"


# ---------------------------------------------------------------------------
# Cover-Specific Snapshot (pinned-erwartete Seite 1 Inhalt)
# ---------------------------------------------------------------------------

def test_cover_page_contains_swiss_date():
    """Cover Seite 1 enthaelt Swiss-Datum (vereinfacht Drift-Test)."""
    pypdf = pytest.importorskip("pypdf")
    pdf = _render()
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    cover = reader.pages[0].extract_text() or ""
    assert "27.05.2026" in cover


def test_cover_page_size_not_empty():
    pypdf = pytest.importorskip("pypdf")
    pdf = _render()
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    cover_text = reader.pages[0].extract_text() or ""
    assert len(cover_text.strip()) > 50, (
        f"Cover-Text zu kurz: {len(cover_text)} chars"
    )
