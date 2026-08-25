"""Stage 7 (UX-Spec §5.1, Spec §9 Stufe 7): Goal-Achievability-Tabelle +
Limiting-Factor-Zeile für die Anlagestrategie-PDF.

Wird in services/pdf/documents/anlagestrategie.py in der Sektion
"Strategie-Begründung" eingebettet, wenn die Stochastic Goal Engine aktiv ist
(achievability + limiting_factor sind dann persistiert in TargetAllocation).

Datenquelle: TargetAllocation.goal_achievability_json (Stage 3) +
TargetAllocation.limiting_factor (Stages 2/3). Beide werden in der PDF-
Datenbeschaffung (services/pdf/base.py / documents/anlagestrategie.py) gelesen
und an diese Komponenten weitergereicht.

Sprachlich: KEINE Garantieversprechen, KEINE Aufforderung zur Risikoerhöhung
(siehe services/allocation_messages.py _FORBIDDEN_SUBSTRINGS). Status-Labels
spiegeln die Klassifikation aus objective.py: erreichbar / knapp /
nicht_erreichbar.
"""
from __future__ import annotations

from typing import Iterable, Mapping

from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Table, TableStyle

from services.pdf.components.header import _esc
from services.pdf.styles import (
    COLOR_BORDER,
    COLOR_TABLE_HEADER_BG,
    COLOR_TEXT,
    COLOR_TEXT_LIGHT,
    FONT_BOLD,
    FONT_DEFAULT,
    FONT_SIZE_TABLE,
    FONT_SIZE_TABLE_HEADER,
    PAGE_SIZE,
    make_paragraph_styles,
)


# --------------------------------------------------------------------------
# Limiting-Factor -> menschen-lesbares Label (Berater-/Kunden-Sprache)
# --------------------------------------------------------------------------
# Synchron zu services/risk_matrix.py classify_limiting_factor Output-Werten.

LIMITING_FACTOR_LABELS: dict[str, str] = {
    "risikoprofil": "Risikoprofil limitiert das Zielportfolio",
    "liquiditaetsreserve": "Liquiditätsreserve ist bindend",
    "bandbreite": "Innerhalb der Profil-Bandbreiten",
    "zielkonflikt": "Zielkonflikt zwischen mehreren primären Zielen",
    "solver_konvergenz": "Bandbreiten-Mittelwert (Optimierer-Fallback)",
}


def make_limiting_factor_line(limiting_factor: str | None) -> Paragraph:
    """Eine kompakte Paragraph-Zeile für die Strategie-Begründung mit dem
    aktuellen Limiting-Factor in Klartext. Rendert nichts (leerer Absatz)
    wenn limiting_factor None/leer ist.
    """
    styles = make_paragraph_styles()
    style = styles.get("small_muted") or styles.get("body")
    if not limiting_factor:
        return Paragraph("", style)
    label = LIMITING_FACTOR_LABELS.get(str(limiting_factor), str(limiting_factor))
    return Paragraph(
        f'<font name="{FONT_DEFAULT}" size="10" color="#475569">'
        f'<b>Limitierender Faktor:</b> {_esc(label)}'
        f'</font>',
        style,
    )


# --------------------------------------------------------------------------
# Achievability-Tabelle: Ziel | Typ | Hardness | Wahrscheinlichkeit | Status
# --------------------------------------------------------------------------

# Status -> (Anzeige-Label, Farbe) — synchron zur Ampel im Review-Cockpit
# (UX-Spec §3.3 rvGoalProbBadge).
_STATUS_DISPLAY: dict[str, tuple[str, str]] = {
    "erreichbar":       ("erreichbar",       "#166534"),   # grün
    "knapp":            ("knapp",            "#92400e"),   # gelb-orange
    "nicht_erreichbar": ("nicht erreichbar", "#7f1d1d"),   # rot
}

# Ziel-Typ-Anzeige (technische Goal-Type-Werte -> Berater-Sprache).
# Synchron zu services/optimizer/goal_liabilities.py _GOAL_TYPE_NORMS.
_GOAL_TYPE_LABELS: dict[str, str] = {
    "Renditeziel": "Renditeziel",
    "Vermoegensziel": "Vermögensziel",
    "Einmalige_Ausgabe": "Einmalige Ausgabe",
    "Wiederkehrende_Ausgabe": "Wiederkehrende Ausgabe",
    "Pensionsausgabe": "Pensionsausgabe",
    "Maximierung": "Maximierung",
    # Falls Achievability direkt das target_kind enthält (selten):
    "wealth_at_t": "Vermögensziel",
    "cashflow_in_year": "Cashflow-Ziel",
    "outflow_stream": "Cashflow-Strom",
    "return_rate": "Renditeziel",
    "maximize": "Maximierung",
}

# Hardness-Anzeige (Wir normalisieren Aliase auf 'hart'/'primär'/'opportunistisch').
_HARDNESS_DISPLAY: dict[str, str] = {
    "hart": "hart",
    "primaer": "primär",
    "primär": "primär",
    "primary": "primär",
    "opportunistisch": "opportunistisch",
    "opportunistic": "opportunistisch",
    "opp": "opportunistisch",
}


def _norm_hardness(value: str | None) -> str:
    return _HARDNESS_DISPLAY.get(str(value or "").strip().lower(), str(value or "—"))


def _prob_cell(probability: float | None) -> str:
    """Wahrscheinlichkeit als Prozent-Text (1 Dezimal)."""
    if probability is None:
        return "—"
    try:
        pct = max(0.0, min(1.0, float(probability))) * 100.0
    except (TypeError, ValueError):
        return "—"
    return f"{pct:.0f}%" if abs(pct - round(pct)) < 0.05 else f"{pct:.1f}%"


# Sprint C1 (2026-06-07): Goal-Achievability-Ampel-Balken (visuell)
# Restoriert 3eyes-Style-UX-Schnelligkeit (war regressiv vs Tabelle-only)

_AMPEL_BAR_WIDTH_MM = 30.0
_AMPEL_BAR_HEIGHT_MM = 4.5

_AMPEL_STATUS_COLORS: dict[str, str] = {
    "erreichbar":       "#16a34a",  # gruen (tailwind green-600)
    "knapp":            "#eab308",  # gelb (tailwind yellow-500)
    "nicht_erreichbar": "#dc2626",  # rot (tailwind red-600)
}
_AMPEL_BG_COLOR = "#e2e8f0"  # neutral hellgrau (tailwind slate-200)
_AMPEL_BORDER_COLOR = "#cbd5e1"  # slate-300


def _probability_bar_drawing(probability: float | None, status: str | None) -> Drawing:
    """Sprint C1 (2026-06-07): visueller Ampel-Balken fuer eine Wahrscheinlichkeit.

    Returns ein ReportLab Drawing das in eine Table-Cell eingebettet werden
    kann. Balken zeigt:
    - Hintergrund-Rechteck (hellgrau, voll-Breite)
    - Vordergrund-Rechteck (Status-Farbe, Breite = probability * full_width)
    - Prozent-Text rechts vom Balken

    Wenn probability=None: zeigt nur "—" als Text.
    """
    w_mm = _AMPEL_BAR_WIDTH_MM
    h_mm = _AMPEL_BAR_HEIGHT_MM
    text_width_mm = 9.0  # Reservierter Platz fuer "100.0%"
    total_w_mm = w_mm + text_width_mm + 2.0
    drawing = Drawing(total_w_mm * mm, h_mm * mm + 1 * mm)

    if probability is None:
        # Nur Text "—" rechtsbuendig
        drawing.add(String(
            (text_width_mm / 2) * mm + (w_mm + 2) * mm, 1 * mm,
            "—", fontSize=8, fillColor=colors.HexColor("#94a3b8"),
            textAnchor="middle",
        ))
        return drawing

    try:
        prob = max(0.0, min(1.0, float(probability)))
    except (TypeError, ValueError):
        return _probability_bar_drawing(None, None)

    status_key = str(status or "").strip().lower()
    fg_color_hex = _AMPEL_STATUS_COLORS.get(status_key, "#64748b")

    # Hintergrund-Rechteck (voll-Breite, hellgrau)
    drawing.add(Rect(
        0, 0, w_mm * mm, h_mm * mm,
        fillColor=colors.HexColor(_AMPEL_BG_COLOR),
        strokeColor=colors.HexColor(_AMPEL_BORDER_COLOR),
        strokeWidth=0.3,
    ))

    # Vordergrund-Rechteck (Status-Farbe, anteilige Breite)
    fg_width_mm = w_mm * prob
    if fg_width_mm > 0:
        drawing.add(Rect(
            0, 0, fg_width_mm * mm, h_mm * mm,
            fillColor=colors.HexColor(fg_color_hex),
            strokeColor=colors.HexColor(fg_color_hex),
            strokeWidth=0.3,
        ))

    # Prozent-Text rechts vom Balken
    pct = prob * 100.0
    pct_text = f"{pct:.0f}%" if abs(pct - round(pct)) < 0.05 else f"{pct:.1f}%"
    drawing.add(String(
        (w_mm + 2) * mm, 0.5 * mm,
        pct_text, fontSize=8,
        fillColor=colors.HexColor("#0f172a"),
        textAnchor="start",
    ))
    return drawing


def _status_cell(status: str | None) -> str:
    label, color = _STATUS_DISPLAY.get(str(status or "").strip().lower(), (str(status or "—"), "#475569"))
    return f'<font color="{color}"><b>{_esc(label)}</b></font>'


def make_goal_achievability_table(achievability: Iterable[Mapping]) -> Table:
    """Returns Table mit Ziel | Typ | Hardness | Wahrscheinlichkeit | Status.

    `achievability` ist die persistierte Liste aus
    TargetAllocation.goal_achievability_json (Stage 3). Jedes Item ist ein
    Dict mit mindestens den Keys: goal_id, label, target_kind (oder
    goal_type), probability (0..1), status, hardness.

    Leere achievability -> Tabelle mit Hinweistext (keine Goals = nichts zu
    zeigen, aber kein Render-Bruch).
    """
    achievability_list = list(achievability or [])
    rows = [["Ziel", "Typ", "Hardness", "Wahrscheinlichkeit", "Status"]]

    if not achievability_list:
        rows.append([
            Paragraph(
                '<font color="#94a3b8"><i>Keine quantifizierbaren Ziele dokumentiert. '
                'Strategie ist auf reine Vermögensmaximierung ausgerichtet.</i></font>',
                make_paragraph_styles().get("small_muted") or make_paragraph_styles().get("body"),
            ),
            "", "", "", "",
        ])
    else:
        for goal in achievability_list:
            label = str(goal.get("label") or goal.get("goal_id") or "—")
            # Akzeptiere sowohl goal_type (Berater-Sprache) als auch target_kind
            # (Optimizer-interner Wert).
            typ_raw = str(goal.get("goal_type") or goal.get("target_kind") or "—")
            typ = _GOAL_TYPE_LABELS.get(typ_raw, typ_raw)
            hardness = _norm_hardness(goal.get("hardness"))
            # Sprint C1 (2026-06-07): Ampel-Balken statt nur Prozent-Text.
            # Visuelle Schnellerfassung (3eyes-Style-UX-Restoration).
            prob_bar = _probability_bar_drawing(
                goal.get("probability"), goal.get("status"),
            )
            status = _status_cell(goal.get("status"))
            cell_style = make_paragraph_styles().get("small_muted") or make_paragraph_styles().get("body")
            rows.append([
                Paragraph(_esc(label), cell_style),
                _esc(typ),
                _esc(hardness),
                prob_bar,
                Paragraph(status, cell_style),
            ])

    page_width, _ = PAGE_SIZE
    table_width = page_width - 24 * mm
    table = Table(
        rows,
        colWidths=[
            table_width * 0.38,  # Ziel
            table_width * 0.20,  # Typ
            table_width * 0.13,  # Hardness
            table_width * 0.15,  # Wahrscheinlichkeit
            table_width * 0.14,  # Status
        ],
    )
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
        ("FONTSIZE", (0, 0), (-1, 0), FONT_SIZE_TABLE_HEADER),
        ("FONTSIZE", (0, 1), (-1, -1), FONT_SIZE_TABLE),
        ("FONTNAME", (0, 1), (-1, -1), FONT_DEFAULT),
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_TABLE_HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), COLOR_TEXT_LIGHT),
        ("TEXTCOLOR", (0, 1), (-1, -1), COLOR_TEXT),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, COLOR_BORDER),
        ("LINEBELOW", (0, 1), (-1, -2), 0.3, COLOR_BORDER),
        ("ALIGN", (3, 0), (3, -1), "RIGHT"),   # Wahrscheinlichkeit rechts
        ("ALIGN", (4, 0), (4, -1), "CENTER"),  # Status zentriert
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return table
