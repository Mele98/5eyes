"""Sprint U-15 (2026-06-06): Tests fuer TTF-Embedding der Editorial-Fonts."""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
TESTS_ROOT = Path(__file__).resolve().parents[1]
for path in (BACKEND_ROOT, TESTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

FONTS_DIR = BACKEND_ROOT / "assets" / "fonts"


def test_all_6_font_files_present():
    """Alle 6 TTF-Files muessen unter assets/fonts/ liegen."""
    expected = (
        "CormorantGaramond-Regular.ttf",
        "CormorantGaramond-Italic.ttf",
        "CormorantGaramond-SemiBold.ttf",
        "Inter-Regular.ttf",
        "Inter-Medium.ttf",
        "Inter-SemiBold.ttf",
    )
    for filename in expected:
        path = FONTS_DIR / filename
        assert path.exists(), f"TTF-File fehlt: {filename}"


def test_register_editorial_fonts_returns_true_when_files_present():
    from services.pdf.fonts import register_editorial_fonts
    assert register_editorial_fonts() is True


def test_editorial_font_names_uses_cormorant_and_inter():
    from services.pdf.fonts import editorial_font_names
    names = editorial_font_names()
    assert names.serif == "CormorantGaramond"
    assert names.serif_bold == "CormorantGaramond-SemiBold"
    assert names.serif_italic == "CormorantGaramond-Italic"
    assert names.sans == "Inter"
    assert names.sans_bold == "Inter-SemiBold"


def test_advisory_palette_uses_editorial_fonts():
    """advisory_palette.FONT_SERIF muss auf editorial-serif zeigen."""
    from services.pdf.components.advisory_palette import FONT_SERIF, FONT_SANS
    assert FONT_SERIF == "CormorantGaramond"
    assert FONT_SANS == "Inter"


def test_cover_font_italic_or_default_uses_editorial():
    """cover.FONT_ITALIC_OR_DEFAULT() liefert CormorantGaramond-Italic
    wenn TTFs registriert sind (NICHT mehr Helvetica-Oblique hardcoded)."""
    from services.pdf.components.cover import FONT_ITALIC_OR_DEFAULT
    result = FONT_ITALIC_OR_DEFAULT()
    assert result == "CormorantGaramond-Italic"


def test_single_report_disclaimer_uses_editorial_italic():
    """single_report_disclaimer._editorial_italic_font() liefert
    Cormorant-Italic statt Helvetica-Oblique."""
    from services.pdf.components.single_report_disclaimer import _editorial_italic_font
    result = _editorial_italic_font()
    assert result == "CormorantGaramond-Italic"


def test_no_hardcoded_helvetica_in_pdf_components():
    """Source-Parse: keine 'Helvetica' als PRIMARY-Choice in pdf/components/
    (Fallback nach 'else' oder in Defensive-Try/Except OK)."""
    import re
    pdf_dir = BACKEND_ROOT / "services" / "pdf" / "components"
    bad_files = []
    for py_file in pdf_dir.glob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                continue
            # Erlaubte Fallback-Patterns
            if "fallback" in line.lower():
                continue
            if " else " in line and "Helvetica" in line:
                continue  # ternary-fallback erlaubt
            if stripped.startswith("return") and "Helvetica" in line and (
                "_FALLBACK" in text[max(0, text.find(line)-200):text.find(line)]
                or "except" in text[max(0, text.find(line)-100):text.find(line)]
            ):
                continue  # defensive fallback OK
            if re.search(r'"Helvetica[-A-Za-z]*"', line):
                bad_files.append(f"{py_file.name}:{line_no}: {line.strip()}")
    assert not bad_files, "Hardcoded Helvetica found:\n" + "\n".join(bad_files)


def test_pdfmetrics_registered_cormorant_family():
    """Nach Registration muessen Font-Family-Mappings gesetzt sein."""
    from services.pdf.fonts import register_editorial_fonts
    from reportlab.pdfbase import pdfmetrics
    register_editorial_fonts()
    # Family 'CormorantGaramond' muss registriert sein
    families = pdfmetrics.getRegisteredFontNames()
    assert "CormorantGaramond" in families
    assert "Inter" in families


def test_inter_semibold_registered():
    from services.pdf.fonts import register_editorial_fonts
    from reportlab.pdfbase import pdfmetrics
    register_editorial_fonts()
    families = pdfmetrics.getRegisteredFontNames()
    assert "Inter-SemiBold" in families


def test_cormorant_italic_registered():
    from services.pdf.fonts import register_editorial_fonts
    from reportlab.pdfbase import pdfmetrics
    register_editorial_fonts()
    families = pdfmetrics.getRegisteredFontNames()
    assert "CormorantGaramond-Italic" in families
