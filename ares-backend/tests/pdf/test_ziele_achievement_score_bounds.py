"""N-877-06: Zielerreichung -- Segmente und Beschriftung aus demselben,
geklemmten und kaufmaennisch gerundeten Wert; nicht berechenbare Werte ohne
Balken und ohne Fehler."""
from __future__ import annotations

import io
import math

import pytest
from pypdf import PdfReader
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.platypus import Paragraph, SimpleDocTemplate

from services.pdf.components.ziele_table import (
    _achievement_segments,
    make_ziele_section,
    normalize_achievement_score,
)

# score -> (angezeigter Wert, gefuellte Segmente). Segmente = half-up(Wert / 12.5)
# aus dem ANGEZEIGTEN Wert, damit Balken und Zahl nie auseinanderlaufen.
CASES = [
    (0, 0, 0),
    (6.25, 6, 0),       # 6.25 -> 6 (half-up); 6/12.5 = 0.48 -> 0
    (12.5, 13, 1),      # 12.5 -> 13 (nicht 12 wie Banker's Rounding); 1.04 -> 1
    (18.75, 19, 2),     # 19/12.5 = 1.52 -> 2
    (31.25, 31, 2),     # 31/12.5 = 2.48 -> 2
    (99.4, 99, 8),      # 7.92 -> 8
    (99.6, 100, 8),     # vorher "99/100" bei 8 Segmenten
    (100, 100, 8),
    (100.4, 100, 8),    # Rundungsartefakt innerhalb der Toleranz
    (100.5, 100, 8),    # Toleranzgrenze
    (-0.4, 0, 0),       # Rundungsartefakt innerhalb der Toleranz
]


@pytest.mark.parametrize("score,shown,segments", CASES)
def test_score_is_clamped_and_rounded_half_up(score, shown, segments):
    assert normalize_achievement_score(score) == shown
    assert _achievement_segments(shown) == segments


@pytest.mark.parametrize("score", [None, math.nan, math.inf, "abc", True])
def test_uncomputable_score_is_none(score):
    assert normalize_achievement_score(score) is None


@pytest.mark.parametrize("score", [130, 100.6, -5, -0.6])
def test_out_of_range_score_is_data_error_not_clamped(score, caplog):
    """N-877-08: kein stilles Klemmen -- ausserhalb der Rundungstoleranz ist
    die Zielerreichung nicht berechenbar, mit Warnung ohne Kundendaten."""
    caplog.set_level("WARNING", logger="services.pdf.components.ziele_table")
    assert normalize_achievement_score(score) is None
    assert "ausserhalb 0..100" in caplog.text
    assert str(score) not in caplog.text


def _achievement_cell(score):
    flowables = make_ziele_section([{
        "rank": 1, "label": "Ziel", "achievement_score": score,
        "target_text": "Rente", "shortfall_rappen": 0,
    }])
    table = flowables[-1]
    return table._cellvalues[1][2]


def _cell_text(cell) -> str:
    items = cell if isinstance(cell, list) else [cell]
    return " ".join(i.getPlainText() for i in items if isinstance(i, Paragraph))


@pytest.mark.parametrize("score,shown,segments", CASES)
def test_cell_label_and_bar_use_the_same_value(score, shown, segments):
    cell = _achievement_cell(score)
    assert _cell_text(cell) == f"{shown}/100"
    drawing = next(i for i in cell if isinstance(i, Drawing))
    rects = drawing.contents
    assert len(rects) == 8
    filled = sum(1 for r in rects if r.fillColor != colors.white)
    assert filled == segments


@pytest.mark.parametrize("score", [None, math.nan, 130, -5])
def test_uncomputable_score_renders_text_without_bar(score):
    cell = _achievement_cell(score)
    assert isinstance(cell, Paragraph)
    assert cell.getPlainText() == "nicht berechenbar"
    buf = io.BytesIO()
    SimpleDocTemplate(buf).build(make_ziele_section([{
        "rank": 1, "label": "Ziel", "achievement_score": score,
        "target_text": "Rente", "shortfall_rappen": 0,
    }]))
    text = "".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(buf.getvalue())).pages)
    assert "nicht berechenbar" in text
