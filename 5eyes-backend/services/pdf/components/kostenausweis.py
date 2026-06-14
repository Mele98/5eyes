"""Editorial ex-ante cost disclosure for the Advisory-Report PDF."""
from __future__ import annotations

from typing import Any

from reportlab.lib.colors import HexColor
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, Spacer, Table, TableStyle

from services.pdf.components.advisory_palette import (
    COLOR_ACCENT,
    COLOR_CANVAS_SUBTLE,
    COLOR_GOLD,
    COLOR_INK,
    COLOR_INK_MUTED,
    COLOR_INK_SUBTLE,
    COLOR_RULE,
    COLOR_STATUS_GELB,
    COLOR_STATUS_GRUEN,
    FONT_SANS,
    FONT_SANS_BOLD,
    MARGIN_LEFT,
    MARGIN_RIGHT,
    PAGE_SIZE,
)
from services.pdf.components.swiss_numbers import (
    format_bps_as_pct,
    format_chf_rappen,
)


def build_kostenausweis_flowables(
    data: dict[str, Any],
    styles,
    *,
    compact: bool = False,
) -> list[Any]:
    """Render a client-facing ex-ante cost disclosure.

    ``compact`` only tightens vertical spacing; the embedded Advisory-Report
    layout remains unchanged.
    """
    out: list[Any] = [
        Paragraph("FIDLEG KOSTENTRANSPARENZ", styles["kicker"]),
        Paragraph("Kostenausweis ex-ante", styles["h1"]),
        Spacer(1, 3 * mm),
        _rule(),
        Spacer(1, 5 * mm),
        Paragraph(
            "Voraussichtliche Kosten der empfohlenen Finanzdienstleistung "
            "und des Zielportfolios. Einmalige und laufende Kosten werden "
            "getrennt sowie in Schweizer Franken und als Quote der "
            "Berechnungsbasis ausgewiesen.",
            _style(styles["body"], color=COLOR_INK_MUTED),
        ),
        Spacer(1, (2 if compact else 4) * mm),
    ]

    if not data or data.get("data_pending"):
        out.extend([
            _status_panel(
                "Daten ausstehend",
                _first_warning(data),
                styles,
                color=COLOR_STATUS_GELB,
            ),
            Spacer(1, 5 * mm),
            _legal_note(styles),
        ])
        return out

    totals = data.get("totals") or {}
    out.append(_summary_metrics(data, totals, styles, compact=compact))
    out.append(Spacer(1, (3 if compact else 5) * mm))
    out.append(_cost_table(
        list(data.get("cost_items") or []),
        totals,
        styles,
        compact=compact,
    ))

    warnings = [str(item) for item in data.get("warnings") or [] if str(item).strip()]
    if warnings:
        out.append(Spacer(1, (2 if compact else 4) * mm))
        out.append(_assumptions_panel(warnings, styles, compact=compact))

    out.append(Spacer(1, (3 if compact else 5) * mm))
    out.append(_legal_note(styles, compact=compact))
    return out


def _summary_metrics(data: dict, totals: dict, styles, *, compact: bool) -> Table:
    metrics = [
        ("ANLAGEBASIS", format_chf_rappen(data.get("advisory_wealth_rappen"))),
        ("EINMALIG", format_chf_rappen(totals.get("one_time_rappen"))),
        ("LAUFEND P.A.", format_chf_rappen(totals.get("annual_rappen"))),
        ("ERSTES JAHR", format_chf_rappen(totals.get("first_year_rappen"))),
    ]
    cells = []
    for label, value in metrics:
        cells.append(Table(
            [[
                Paragraph(_escape(label), _style(
                    styles["micro"], font=FONT_SANS_BOLD, color=COLOR_INK_SUBTLE,
                )),
            ], [
                Paragraph(_escape(value), _style(
                    styles["body"], font=FONT_SANS_BOLD, color=COLOR_INK, size=12,
                )),
            ]],
            colWidths=[_inner_width() * 0.225],
        ))
    table = Table([cells], colWidths=[_inner_width() * 0.225] * 4)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), COLOR_CANVAS_SUBTLE),
        ("BOX", (0, 0), (-1, -1), 0.4, COLOR_RULE),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, COLOR_RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5 if compact else 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5 if compact else 7),
    ]))
    return table


def _cost_table(
    items: list[dict[str, Any]],
    totals: dict,
    styles,
    *,
    compact: bool,
) -> Table:
    rows: list[list[Any]] = [[
        _th("Kostenart", styles),
        _th("Turnus", styles),
        _th("Satz", styles),
        _th("Betrag", styles),
        _th("Berechnungsbasis", styles),
    ]]
    for item in items:
        label = str(item.get("label") or item.get("category") or "Kosten")
        if item.get("is_estimate"):
            label += " *"
        rows.append([
            Paragraph(_escape(label), _style(styles["caption"], color=COLOR_INK)),
            Paragraph(_escape(_frequency_label(item.get("frequency"))), _style(
                styles["caption"], color=COLOR_INK_MUTED,
            )),
            Paragraph(_escape(format_bps_as_pct(item.get("rate_bps"), decimals=2)), _style(
                styles["caption_mono"], color=COLOR_INK,
            )),
            Paragraph(_escape(format_chf_rappen(item.get("amount_rappen"))), _style(
                styles["caption_mono"], color=COLOR_INK,
            )),
            Paragraph(_escape(str(item.get("basis_label") or "—")), _style(
                styles["micro"], color=COLOR_INK_SUBTLE,
            )),
        ])

    rows.extend([
        _total_row(
            "Total einmalige Kosten",
            totals.get("one_time_bps"),
            totals.get("one_time_rappen"),
            styles,
            strong=False,
        ),
        _total_row(
            "Total laufende Kosten p.a.",
            totals.get("annual_bps"),
            totals.get("annual_rappen"),
            styles,
            strong=False,
        ),
        _total_row(
            "Gesamtkosten im ersten Jahr",
            totals.get("first_year_bps"),
            totals.get("first_year_rappen"),
            styles,
            strong=True,
        ),
    ])

    widths = [
        _inner_width() * 0.33,
        _inner_width() * 0.12,
        _inner_width() * 0.12,
        _inner_width() * 0.18,
        _inner_width() * 0.25,
    ]
    table = Table(rows, colWidths=widths, repeatRows=1)
    last = len(rows) - 1
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_INK),
        ("TEXTCOLOR", (0, 0), (-1, 0), HexColor("#FFFFFF")),
        ("LINEBELOW", (0, 0), (-1, 0), 0.7, COLOR_INK),
        ("LINEBELOW", (0, 1), (-1, last - 3), 0.3, COLOR_RULE),
        ("LINEABOVE", (0, last - 2), (-1, last - 2), 0.8, COLOR_RULE),
        ("BACKGROUND", (0, last - 2), (-1, last - 1), COLOR_CANVAS_SUBTLE),
        ("BACKGROUND", (0, last), (-1, last), HexColor("#E8EFEA")),
        ("LINEABOVE", (0, last), (-1, last), 0.9, COLOR_STATUS_GRUEN),
        ("SPAN", (0, last - 2), (1, last - 2)),
        ("SPAN", (0, last - 1), (1, last - 1)),
        ("SPAN", (0, last), (1, last)),
        ("ALIGN", (2, 1), (3, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4 if compact else 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4 if compact else 6),
    ]))
    return table


def _total_row(label: str, bps: Any, amount: Any, styles, *, strong: bool) -> list[Any]:
    font = FONT_SANS_BOLD if strong else FONT_SANS
    return [
        Paragraph(_escape(label), _style(styles["caption"], font=font, color=COLOR_INK)),
        "",
        Paragraph(_escape(format_bps_as_pct(bps, decimals=2)), _style(
            styles["caption_mono"], font=font, color=COLOR_INK,
        )),
        Paragraph(_escape(format_chf_rappen(amount)), _style(
            styles["caption_mono"], font=font, color=COLOR_INK,
        )),
        Paragraph(
            "Quote bezogen auf das Beratungsvermögen",
            _style(styles["micro"], color=COLOR_INK_SUBTLE),
        ),
    ]


def _assumptions_panel(warnings: list[str], styles, *, compact: bool) -> Table:
    body = [
        Paragraph(
            "ANNAHMEN UND DATENQUALITAET",
            _style(styles["micro"], font=FONT_SANS_BOLD, color=COLOR_INK_SUBTLE),
        )
    ]
    for warning in warnings[:5]:
        body.append(Paragraph(
            f"- {_escape(warning)}",
            _style(styles["caption"], color=COLOR_INK_MUTED),
        ))
    table = Table([[body]], colWidths=[_inner_width()])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HexColor("#F7F4EA")),
        ("BOX", (0, 0), (-1, -1), 0.5, COLOR_GOLD),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 6 if compact else 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6 if compact else 8),
    ]))
    return table


def _legal_note(styles, *, compact: bool = False) -> Table:
    text = (
        "<b>Rechtlicher Hinweis.</b> Dieser Ex-ante-Kostenausweis ist eine "
        "vorausschauende Berechnung gemäss Art. 8 und 9 FIDLEG sowie Art. 8 "
        "und 14 FIDLEV. Nicht im Voraus exakt bestimmbare Kosten werden "
        "annäherungsweise ausgewiesen. Tatsächliche Kosten können aufgrund "
        "von Anlagevolumen, Haltedauer, Transaktionen, Kursen, Spreads, "
        "Courtagen, Börsenabgaben, Währungsumrechnungen, Steuern sowie "
        "Gebühren beteiligter Dritter abweichen. Massgeblich bleiben die "
        "Vertragsunterlagen, Preislisten, Basisinformationsblätter und "
        "Prospekte. Der Ausweis ersetzt keine Ex-post-Kostenabrechnung."
    )
    content = Paragraph(text, _style(styles["caption"], color=COLOR_INK_MUTED))
    table = Table([[content]], colWidths=[_inner_width()])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), COLOR_CANVAS_SUBTLE),
        ("LINEABOVE", (0, 0), (-1, 0), 0.7, COLOR_ACCENT),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 6 if compact else 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6 if compact else 8),
    ]))
    return KeepTogether([table])


def _status_panel(title: str, body: str, styles, *, color) -> Table:
    table = Table([[
        Paragraph(_escape(title), _style(
            styles["body"], font=FONT_SANS_BOLD, color=COLOR_INK,
        )),
        Paragraph(_escape(body), _style(styles["caption"], color=COLOR_INK_MUTED)),
    ]], colWidths=[_inner_width() * 0.23, _inner_width() * 0.77])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), COLOR_CANVAS_SUBTLE),
        ("LINEBEFORE", (0, 0), (0, -1), 3, color),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))
    return table


def _th(text: str, styles) -> Paragraph:
    return Paragraph(_escape(text), _style(
        styles["micro"], font=FONT_SANS_BOLD, color=HexColor("#FFFFFF"),
    ))


def _frequency_label(value: Any) -> str:
    return {
        "einmalig": "einmalig",
        "jährlich": "jährlich",
    }.get(str(value or ""), str(value or "—"))


def _first_warning(data: dict) -> str:
    warnings = list(data.get("warnings") or [])
    return str(warnings[0]) if warnings else "Kostenbasis ist noch nicht vollständig."


def _rule() -> Table:
    table = Table([[""]], colWidths=[_inner_width()], rowHeights=[0.5])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), COLOR_RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return table


def _inner_width() -> float:
    page_width, _ = PAGE_SIZE
    return page_width - MARGIN_LEFT - MARGIN_RIGHT


def _style(
    base: ParagraphStyle,
    *,
    font: str | None = None,
    color=None,
    size: float | None = None,
) -> ParagraphStyle:
    return ParagraphStyle(
        f"{base.name}CostDisclosure{font or ''}{size or ''}",
        parent=base,
        fontName=font or base.fontName or FONT_SANS,
        textColor=color or base.textColor,
        fontSize=size or base.fontSize,
        leading=(size + 3) if size else base.leading,
        spaceBefore=0,
        spaceAfter=0,
    )


def _escape(value: Any) -> str:
    return (
        str(value if value is not None else "—")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
