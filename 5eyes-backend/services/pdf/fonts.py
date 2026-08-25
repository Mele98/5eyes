"""Editorial font registration for ReportLab PDFs.

U-15 embeds the same editorial families used by the reporting sub-app:
Cormorant Garamond for serif headings and Inter for body text.
The module is intentionally defensive: missing TTF files downgrade to
ReportLab stock fonts instead of breaking PDF generation.
"""
from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

logger = logging.getLogger(__name__)


FONT_DIR_RELATIVE = Path("assets") / "fonts"

FONT_FILES = {
    "CormorantGaramond": "CormorantGaramond-Regular.ttf",
    "CormorantGaramond-Italic": "CormorantGaramond-Italic.ttf",
    "CormorantGaramond-SemiBold": "CormorantGaramond-SemiBold.ttf",
    "Inter": "Inter-Regular.ttf",
    "Inter-Medium": "Inter-Medium.ttf",
    "Inter-SemiBold": "Inter-SemiBold.ttf",
}


@dataclass(frozen=True)
class EditorialFontNames:
    serif: str
    serif_bold: str
    serif_italic: str
    sans: str
    sans_medium: str
    sans_bold: str
    mono: str = "Courier"


_EDITORIAL_NAMES = EditorialFontNames(
    serif="CormorantGaramond",
    serif_bold="CormorantGaramond-SemiBold",
    serif_italic="CormorantGaramond-Italic",
    sans="Inter",
    sans_medium="Inter-Medium",
    sans_bold="Inter-SemiBold",
)

_FALLBACK_NAMES = EditorialFontNames(
    serif="Times-Roman",
    serif_bold="Times-Bold",
    serif_italic="Times-Italic",
    sans="Helvetica",
    sans_medium="Helvetica",
    sans_bold="Helvetica-Bold",
)

_REGISTERED = False
_AVAILABLE = False


def resolve_font_asset_dir() -> Path:
    """Return the most likely font asset directory.

    In PyInstaller bundles, files may be unpacked below `sys._MEIPASS`; in the
    source tree they live in `5eyes-backend/assets/fonts`.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        bundle_root = Path(str(meipass))
        candidates = [
            bundle_root / "5eyes-backend" / FONT_DIR_RELATIVE,
            bundle_root / FONT_DIR_RELATIVE,
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate

    backend_root = Path(__file__).resolve().parents[2]
    return backend_root / FONT_DIR_RELATIVE


def editorial_font_names() -> EditorialFontNames:
    """Return registered editorial names or ReportLab stock fallbacks."""
    register_editorial_fonts()
    return _EDITORIAL_NAMES if _AVAILABLE else _FALLBACK_NAMES


def register_editorial_fonts(font_dir: str | Path | None = None) -> bool:
    """Register Cormorant Garamond and Inter with ReportLab.

    Returns True when all editorial fonts are available. If `font_dir` is
    provided, the check is isolated and does not mutate the process-wide
    availability flag; this keeps tests for degraded mode independent from the
    real registration state.
    """
    global _REGISTERED, _AVAILABLE

    if font_dir is None and _REGISTERED:
        return _AVAILABLE

    asset_dir = Path(font_dir) if font_dir is not None else resolve_font_asset_dir()
    missing = [
        filename
        for filename in FONT_FILES.values()
        if not (asset_dir / filename).exists()
    ]
    if missing:
        logger.warning(
            "Editorial PDF fonts missing in %s: %s. Falling back to stock fonts.",
            asset_dir,
            ", ".join(sorted(missing)),
        )
        if font_dir is None:
            _REGISTERED = True
            _AVAILABLE = False
        return False

    try:
        for font_name, filename in FONT_FILES.items():
            _register_ttf(font_name, asset_dir / filename)
        pdfmetrics.registerFontFamily(
            "CormorantGaramond",
            normal="CormorantGaramond",
            bold="CormorantGaramond-SemiBold",
            italic="CormorantGaramond-Italic",
            boldItalic="CormorantGaramond-SemiBold",
        )
        pdfmetrics.registerFontFamily(
            "Inter",
            normal="Inter",
            bold="Inter-SemiBold",
            italic="Inter",
            boldItalic="Inter-SemiBold",
        )
    except Exception as exc:  # noqa: BLE001 - PDF generation must degrade
        logger.warning(
            "Editorial PDF font registration failed (%s). Falling back to stock fonts.",
            exc,
        )
        if font_dir is None:
            _REGISTERED = True
            _AVAILABLE = False
        return False

    if font_dir is None:
        _REGISTERED = True
        _AVAILABLE = True
    return True


def _register_ttf(font_name: str, path: Path) -> None:
    if font_name in pdfmetrics.getRegisteredFontNames():
        return
    pdfmetrics.registerFont(TTFont(font_name, str(path)))
