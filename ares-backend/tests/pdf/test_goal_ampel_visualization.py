"""Sprint C1 (2026-06-07): Goal-Achievability-Ampel im PDF.

Restoriert 3eyes-Style visuelle Schnelle-Erfassung — vorher war die Goal-
Achievability nur eine Tabelle ohne visuellen Bar (UX-Regression vs 3eyes).
Post-C1: Wahrscheinlichkeit-Cell zeigt Ampel-Balken (gruen/gelb/rot) plus
Prozent-Text.
"""
from __future__ import annotations

import pytest
from reportlab.graphics.shapes import Drawing, Rect, String

from services.pdf.components.goal_achievability import (
    _AMPEL_BAR_HEIGHT_MM,
    _AMPEL_BAR_WIDTH_MM,
    _AMPEL_STATUS_COLORS,
    _probability_bar_drawing,
    make_goal_achievability_table,
)


# ===========================================================================
# Drawing-Komponente
# ===========================================================================


def test_c1_probability_bar_ist_drawing():
    """Returnt ReportLab Drawing-Objekt (kein Crash bei valider Input)."""
    d = _probability_bar_drawing(0.78, "erreichbar")
    assert isinstance(d, Drawing)


def test_c1_probability_bar_none_zeigt_dash():
    """None-Wahrscheinlichkeit zeigt nur Dash-Text, kein Balken."""
    d = _probability_bar_drawing(None, None)
    # Sollte mind. 1 String-Element haben (das Dash)
    strings = [el for el in d.contents if isinstance(el, String)]
    assert len(strings) >= 1
    # Kein Rect (= kein Bar)
    rects = [el for el in d.contents if isinstance(el, Rect)]
    assert len(rects) == 0


def test_c1_probability_bar_komplett_zeigt_bg_fg_text():
    """Vollwertige Wahrscheinlichkeit zeigt BG-Rect + FG-Rect + Text."""
    d = _probability_bar_drawing(0.8, "erreichbar")
    rects = [el for el in d.contents if isinstance(el, Rect)]
    strings = [el for el in d.contents if isinstance(el, String)]
    assert len(rects) == 2  # BG + FG
    assert len(strings) == 1  # Prozent-Text


def test_c1_probability_bar_status_farbe_gruen_erreichbar():
    """Status 'erreichbar' fuellt mit gruen."""
    d = _probability_bar_drawing(0.8, "erreichbar")
    rects = [el for el in d.contents if isinstance(el, Rect)]
    fg_rect = rects[1]  # zweites ist FG
    # Color-Spec hex check via fillColor → reportlab Color-Objekt
    assert fg_rect.fillColor.hexval() == "0x{}".format(
        _AMPEL_STATUS_COLORS["erreichbar"].lstrip("#"),
    )


def test_c1_probability_bar_status_farbe_rot_nicht_erreichbar():
    d = _probability_bar_drawing(0.2, "nicht_erreichbar")
    rects = [el for el in d.contents if isinstance(el, Rect)]
    fg_rect = rects[1]
    assert fg_rect.fillColor.hexval() == "0x{}".format(
        _AMPEL_STATUS_COLORS["nicht_erreichbar"].lstrip("#"),
    )


def test_c1_probability_bar_status_farbe_gelb_knapp():
    d = _probability_bar_drawing(0.6, "knapp")
    rects = [el for el in d.contents if isinstance(el, Rect)]
    fg_rect = rects[1]
    assert fg_rect.fillColor.hexval() == "0x{}".format(
        _AMPEL_STATUS_COLORS["knapp"].lstrip("#"),
    )


def test_c1_probability_bar_unbekannter_status_neutral_farbe():
    """Unbekannter Status → neutrale Farbe, kein Crash."""
    d = _probability_bar_drawing(0.5, "wat_iss_das")
    rects = [el for el in d.contents if isinstance(el, Rect)]
    # Sollte trotzdem 2 Rects haben
    assert len(rects) == 2


def test_c1_probability_bar_breite_skaliert_mit_wahrscheinlichkeit():
    """FG-Rect-Breite = probability * Total-Bar-Breite."""
    from reportlab.lib.units import mm
    expected_total_width = _AMPEL_BAR_WIDTH_MM * mm
    d_full = _probability_bar_drawing(1.0, "erreichbar")
    d_half = _probability_bar_drawing(0.5, "erreichbar")
    rects_full = [el for el in d_full.contents if isinstance(el, Rect)]
    rects_half = [el for el in d_half.contents if isinstance(el, Rect)]
    # FG-Rect-Width im full = total, im half = total/2
    assert abs(rects_full[1].width - expected_total_width) < 0.1
    assert abs(rects_half[1].width - expected_total_width / 2) < 0.1


def test_c1_probability_bar_clampt_auf_0_1():
    """probability > 1.0 oder < 0 wird auf [0,1] geclampt."""
    from reportlab.lib.units import mm
    d_over = _probability_bar_drawing(1.5, "erreichbar")
    d_neg = _probability_bar_drawing(-0.3, "nicht_erreichbar")
    rects_over = [el for el in d_over.contents if isinstance(el, Rect)]
    rects_neg = [el for el in d_neg.contents if isinstance(el, Rect)]
    # Over: 100% FG
    assert abs(rects_over[1].width - _AMPEL_BAR_WIDTH_MM * mm) < 0.1
    # Neg: 0% FG (oder no FG rect added)
    if len(rects_neg) > 1:
        assert rects_neg[1].width <= 0.1


def test_c1_probability_bar_invalid_input_returnt_dash():
    """Nicht-numerische probability → defensive Fallback."""
    d = _probability_bar_drawing("abc", "erreichbar")
    rects = [el for el in d.contents if isinstance(el, Rect)]
    assert len(rects) == 0  # Kein Balken bei broken input


# ===========================================================================
# End-to-End: make_goal_achievability_table mit Ampel-Cells
# ===========================================================================


def test_c1_table_integriert_ampel_balken():
    """make_goal_achievability_table embedded das Drawing in der Cell."""
    achievability = [
        {
            "goal_id": "g1", "label": "Pension",
            "goal_type": "Vermoegensziel", "hardness": "Hart",
            "probability": 0.85, "status": "erreichbar",
        },
        {
            "goal_id": "g2", "label": "Eigenheim",
            "goal_type": "Vermoegensziel", "hardness": "Primär",
            "probability": 0.45, "status": "knapp",
        },
    ]
    table = make_goal_achievability_table(achievability)
    # Inspect cell at row=1 (g1), col=3 (Wahrscheinlichkeit)
    cell_g1_prob = table._cellvalues[1][3]
    cell_g2_prob = table._cellvalues[2][3]
    assert isinstance(cell_g1_prob, Drawing), (
        f"Probability-Cell muss Drawing sein, got {type(cell_g1_prob)}"
    )
    assert isinstance(cell_g2_prob, Drawing)


def test_c1_table_leere_achievability_funktioniert():
    """Backwards-Compat: leere achievability → Hinweistext-Zeile, kein Crash."""
    table = make_goal_achievability_table([])
    # Header + 1 Hinweis-Zeile = 2 Rows
    assert len(table._cellvalues) == 2


def test_c1_table_default_drawing_dimensions():
    """Drawing soll Standard-Dimensionen aus den Konstanten haben."""
    from reportlab.lib.units import mm
    d = _probability_bar_drawing(0.5, "knapp")
    expected_height = (_AMPEL_BAR_HEIGHT_MM + 1) * mm
    assert abs(d.height - expected_height) < 1.0
