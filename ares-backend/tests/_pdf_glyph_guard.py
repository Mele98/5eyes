"""N-877-02/07: fail-closed Glyphen-Guard fuer PDF-Tests.

ReportLab setzt Zeichen, die ein eingebetteter TTF-Font nicht enthaelt, still
auf .notdef (leerer Kasten im Kundendokument). ``glyph_guard`` haengt sich an
``TTFont.splitString`` -- darueber laufen alle TTF-Textpfade (Canvas,
Paragraph, Tabellenzellen, reportlab.graphics) -- und meldet jedes Zeichen
ohne Glyphe mit Font, Zeichen und Codepoint. NBSP mappt ReportLab selbst auf
Space und ist ausgenommen.

``tests/conftest.py`` aktiviert den Guard automatisch fuer ALLE Tests
(N-877-09); Opt-out nur per Marker ``allow_missing_glyphs`` (fuer die
Positivkontrolle, die absichtlich ein fehlendes Zeichen zeichnet).
"""
from __future__ import annotations

import contextlib


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
