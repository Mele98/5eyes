"""Sprint 14 Phase 2: Kapitalzuflüsse + Ziele-Tabellen (Vorlage Seite 12).

Zwei Tabellen:
- Kapitalzuflüsse: einmalige + wiederkehrende Income-Events
- Anlageziele: priorisierte Ziele mit Zielgröße
"""
from __future__ import annotations

from typing import Iterable, Mapping

from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

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


def make_cashflows_section(events: Iterable[Mapping], *, base_currency: str = "CHF") -> list:
    """Kapitalzuflüsse-Tabelle (einmalige + wiederkehrende Income-Events)."""
    flowables: list = []
    flowables.append(_section_title("🌐  Kapitalzuflüsse"))
    events_list = list(events or [])
    if not events_list:
        flowables.append(_fallback_text("Noch keine Kapitalzuflüsse erfasst."))
        return flowables
    flowables.append(_make_events_table(
        events_list,
        header=["Name", "Haushaltsmitglied", "Wiederholung", "Beginn – Ende",
                f"Betrag ({base_currency})"],
        base_currency=base_currency,
    ))
    return flowables


def make_ziele_overview_section(goals: Iterable[Mapping], *, base_currency: str = "CHF") -> list:
    """Anlageziele-Tabelle (priorisierte Ziele mit Zielgröße).

    Im Gegensatz zur 'Zielerreichungs'-Sektion (ziele_table.py) zeigt diese
    nur die definierten Ziele OHNE Achievement-Score (Seite 12 Vorlage).
    """
    flowables: list = []
    flowables.append(_section_title("🏆  Ihre persönlichen Ziele"))
    goals_list = list(goals or [])
    if not goals_list:
        flowables.append(_fallback_text("Noch keine Ziele erfasst."))
        return flowables
    flowables.append(_make_goals_table(goals_list, base_currency))
    return flowables


def _make_events_table(events: list, *, header: list, base_currency: str):
    rows = [header]
    for ev in events:
        name = str(ev.get("name", "—") or "—")
        household = str(ev.get("household_member", "") or "—")
        recurrence = str(ev.get("recurrence", "Einmalig") or "Einmalig")
        start = str(ev.get("start_label", "") or "—")
        amount = int(ev.get("amount_rappen", 0) or 0)
        rows.append([
            Paragraph(f'<font name="{FONT_BOLD}">{_esc(name)}</font>', _para_cell()),
            _esc(household),
            _esc(recurrence),
            _esc(start),
            _format_amount(amount, base_currency) if amount else "—",
        ])
    return _wrap_table(rows, col_fracs=[0.34, 0.16, 0.14, 0.16, 0.20], align_right_from=4)


def _make_goals_table(goals: list, base_currency: str):
    rows = [["Name", "Kategorie", "Wiederholung", "Beginn – Ende", f"Betrag ({base_currency})"]]
    for g in goals:
        name = str(g.get("name", "—") or "—")
        category = str(g.get("category", "") or "—")
        recurrence = str(g.get("recurrence", "") or "—")
        period = str(g.get("period_label", "") or "—")
        amount = int(g.get("amount_rappen", 0) or 0)
        target_pct = g.get("target_pct", None)
        if amount > 0:
            amount_text = _format_amount(amount, base_currency)
        elif target_pct is not None:
            amount_text = f"{float(target_pct):.2f} %"
        else:
            amount_text = "—"
        rows.append([
            Paragraph(f'<font name="{FONT_BOLD}">{_esc(name)}</font>', _para_cell()),
            _esc(category),
            _esc(recurrence),
            _esc(period),
            amount_text,
        ])
    return _wrap_table(rows, col_fracs=[0.34, 0.18, 0.16, 0.16, 0.16], align_right_from=4)


def _wrap_table(rows: list, *, col_fracs: list, align_right_from: int):
    page_width, _ = PAGE_SIZE
    table_width = page_width - 24 * mm
    col_widths = [table_width * f for f in col_fracs]
    table = Table(rows, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
        ("FONTSIZE", (0, 0), (-1, 0), FONT_SIZE_TABLE_HEADER),
        ("FONTSIZE", (0, 1), (-1, -1), FONT_SIZE_TABLE),
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_TABLE_HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), COLOR_TEXT_LIGHT),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, COLOR_BORDER),
        ("LINEBELOW", (0, 1), (-1, -2), 0.3, COLOR_BORDER),
        ("ALIGN", (align_right_from, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return table


def _format_amount(rappen: int, currency: str = "CHF") -> str:
    try:
        if currency == "CHF":
            value = rappen / 100.0
        else:
            from services.currency.converter import convert_rappen
            value = convert_rappen(rappen, "CHF", currency) / 100.0
        return f"{value:,.0f}".replace(",", "'")
    except Exception:
        return f"{rappen/100.0:,.0f}".replace(",", "'")


def _section_title(text: str):
    style = make_paragraph_styles()["section_title"]
    return Paragraph(
        f'<font name="{FONT_BOLD}" size="12" color="#0f172a">{_esc(text)}</font>',
        style,
    )


def _fallback_text(text: str):
    return Paragraph(
        f'<font name="{FONT_DEFAULT}" size="9" color="#94a3b8"><i>{_esc(text)}</i></font>',
        make_paragraph_styles()["small_muted"],
    )


def _para_cell():
    from reportlab.lib.styles import ParagraphStyle
    return ParagraphStyle(
        "CFCell",
        fontName=FONT_DEFAULT,
        fontSize=FONT_SIZE_TABLE,
        leading=11,
        spaceAfter=0,
    )
