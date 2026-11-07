"""N-877-02/07: fail-closed Glyphen-Guard fuer PDF-Tests.

ReportLab setzt Zeichen, die ein eingebetteter TTF-Font nicht enthaelt, still
auf .notdef (leerer Kasten im Kundendokument). ``glyph_guard`` haengt sich an
``TTFont.splitString`` -- darueber laufen alle TTF-Textpfade (Canvas,
Paragraph, Tabellenzellen, reportlab.graphics) -- und meldet jedes Zeichen
ohne Glyphe mit Font, Zeichen und Codepoint. NBSP mappt ReportLab selbst auf
Space und ist ausgenommen.

``tests/conftest.py`` aktiviert den Guard automatisch fuer alle PDF-Tests
(``is_pdf_test``); Opt-out nur per Marker ``allow_missing_glyphs`` (fuer die
Positivkontrolle, die absichtlich ein fehlendes Zeichen zeichnet).
"""
from __future__ import annotations

import contextlib
import re

# tests/pdf/** sowie PDF-, Report-, Kostenausweis-, Golden-, Acceptance- und
# Packaging-Smoke-Testdateien.
PDF_TEST_FILE = re.compile(
    r"pdf|report|kosten|cost_disclosure|golden|acceptance|packaging_smoke|backtest|depot_check|protokoll",
    re.IGNORECASE,
)


def is_pdf_test(path) -> bool:
    parts = [p.lower() for p in re.split(r"[\/]", str(path))]
    if len(parts) >= 2 and parts[-2] == "pdf":
        return True
    return bool(PDF_TEST_FILE.search(parts[-1]))


@contextlib.contextmanager
def glyph_guard(label: str):
    from reportlab.pdfbase.ttfonts import TTFont

    missing: set[tuple[str, str, str]] = set()
    original = TTFont.splitString

    def split(self, text, doc, encoding="utf-8"):
        chars = text.decode("utf-8") if isinstance(text, bytes) else text
        cmap = self.face.charToGlyph
        for ch in chars:
            if ord(ch) != 0xA0 and ord(ch) not in cmap:
                missing.add((self.fontName, ch, f"U+{ord(ch):04X}"))
        return original(self, text, doc, encoding)

    TTFont.splitString = split
    try:
        yield missing
    finally:
        TTFont.splitString = original
    assert not missing, f"{label}: Zeichen ohne Glyphe im eingebetteten Font: {sorted(missing)}"
