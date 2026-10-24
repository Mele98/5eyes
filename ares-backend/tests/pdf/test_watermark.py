"""Sprint U-91 (2026-06-06): Tests fuer PDF-Wasserzeichen Entwurf/Vertraulich."""
from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock

BACKEND_ROOT = Path(__file__).resolve().parents[2]
TESTS_ROOT = Path(__file__).resolve().parents[1]
for path in (BACKEND_ROOT, TESTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from services.pdf.components.watermark import (
    WATERMARK_MODES,
    draw_watermark,
)


# ---------------------------------------------------------------------------
# Konstanten
# ---------------------------------------------------------------------------

def test_watermark_modes_includes_3_options():
    assert "none" in WATERMARK_MODES
    assert "entwurf" in WATERMARK_MODES
    assert "vertraulich" in WATERMARK_MODES


# ---------------------------------------------------------------------------
# Mode-Dispatch
# ---------------------------------------------------------------------------

def _mock_canvas() -> MagicMock:
    """Erzeugt einen MagicMock-Canvas der saveState/restoreState +
    draw-Methoden aufzeichnet."""
    canvas = MagicMock()
    return canvas


def test_mode_none_does_nothing():
    """Bei mode='none' sollten KEINE Draw-Calls passieren."""
    canvas = _mock_canvas()
    draw_watermark(canvas, mode="none", page_width=595, page_height=842)
    # saveState/restoreState werden nicht aufgerufen wenn 'none'
    assert not canvas.saveState.called
    assert not canvas.drawCentredString.called


def test_mode_entwurf_draws_diagonal():
    """Entwurf nutzt rotate(45) + drawCentredString('ENTWURF')."""
    canvas = _mock_canvas()
    draw_watermark(canvas, mode="entwurf", page_width=595, page_height=842)
    assert canvas.saveState.called
    assert canvas.restoreState.called
    assert canvas.rotate.called
    rotation_args = canvas.rotate.call_args[0]
    assert rotation_args == (45,)
    # drawCentredString muss 'ENTWURF' enthalten
    draw_args = canvas.drawCentredString.call_args[0]
    assert draw_args[2] == "ENTWURF"


def test_mode_vertraulich_draws_horizontal_top():
    """Vertraulich nutzt drawCentredString OHNE rotate."""
    canvas = _mock_canvas()
    draw_watermark(canvas, mode="vertraulich", page_width=595, page_height=842)
    assert canvas.saveState.called
    assert canvas.restoreState.called
    assert not canvas.rotate.called
    draw_args = canvas.drawCentredString.call_args[0]
    assert "VERTRAULICH" in draw_args[2]


def test_mode_unknown_falls_back_to_none():
    """Unbekannter Modus wird zu 'none' normalisiert."""
    canvas = _mock_canvas()
    draw_watermark(canvas, mode="bogus", page_width=595, page_height=842)
    assert not canvas.saveState.called


def test_mode_case_insensitive():
    canvas = _mock_canvas()
    draw_watermark(canvas, mode="ENTWURF", page_width=595, page_height=842)
    assert canvas.rotate.called


def test_mode_whitespace_stripped():
    canvas = _mock_canvas()
    draw_watermark(canvas, mode="  vertraulich  ", page_width=595, page_height=842)
    assert canvas.drawCentredString.called


def test_alpha_fallback_when_unsupported():
    """Bei aelteren ReportLab-Versionen ohne setFillAlpha darf draw NICHT crashen."""
    canvas = _mock_canvas()
    canvas.setFillAlpha.side_effect = Exception("Old ReportLab")
    # Soll nicht raisen
    draw_watermark(canvas, mode="entwurf", page_width=595, page_height=842)
    assert canvas.drawCentredString.called


# ---------------------------------------------------------------------------
# Source-Integration in advisory_report-Pipeline
# ---------------------------------------------------------------------------

def test_render_pdf_accepts_watermark_mode_kwarg():
    """render_advisory_report_pdf_from_payload muss watermark_mode-Param annehmen."""
    from services.pdf.documents.advisory_report import (
        render_advisory_report_pdf_from_payload,
    )
    import inspect
    sig = inspect.signature(render_advisory_report_pdf_from_payload)
    assert "watermark_mode" in sig.parameters
    assert sig.parameters["watermark_mode"].default == "none"


def test_render_pdf_top_level_accepts_watermark_mode():
    """render_advisory_report_pdf (Top-Level) muss watermark_mode-Param annehmen."""
    from services.pdf.documents.advisory_report import render_advisory_report_pdf
    import inspect
    sig = inspect.signature(render_advisory_report_pdf)
    assert "watermark_mode" in sig.parameters


def test_advisory_numbered_canvas_accepts_watermark_mode():
    """AdvisoryNumberedCanvas-Constructor muss watermark_mode-kwarg akzeptieren."""
    from services.pdf.components.advisory_page_chrome import (
        AdvisoryNumberedCanvas,
    )
    import inspect
    sig = inspect.signature(AdvisoryNumberedCanvas.__init__)
    assert "watermark_mode" in sig.parameters
