"""Beratungsprotokoll-PDF.

Schlankes Abschlussdokument fuer Review & Abschluss: dokumentierte
Entscheide, Empfehlung, Status und Unterschrift.
"""
from __future__ import annotations

from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from services.pdf.base import PDFContext
from services.pdf.components.header import _esc, make_wealtharchitekten_header
from services.pdf.components.unterschrift import make_unterschrift_section
from services.pdf.styles import (
    COLOR_BORDER,
    COLOR_TABLE_HEADER_BG,
    COLOR_TEXT,
    COLOR_TEXT_LIGHT,
    FONT_BOLD,
    FONT_DEFAULT,
    FONT_SIZE_BODY,
    FONT_SIZE_TABLE,
    FONT_SIZE_TABLE_HEADER,
    PAGE_SIZE,
    make_paragraph_styles,
)


def build_protokoll_flowables(ctx: PDFContext, data) -> list:
    flowables: list = []
    styles = make_paragraph_styles()

    advisory_label = None
    if getattr(data, "advisory_wealth_rappen", None):
        advisory_label = _format_amount(data.advisory_wealth_rappen, ctx.base_currency)
    flowables.extend(make_wealtharchitekten_header(
        ctx,
        mandate_number=getattr(data, "mandate_number", None),
        advisory_wealth_label=advisory_label,
        document_title="Beratungsprotokoll",
    ))

    flowables.append(Paragraph(
        f'<font name="{FONT_BOLD}" size="16" color="#0f172a">Beratungsprotokoll</font>',
        styles["heading"],
    ))
    flowables.append(Paragraph(
        '<font name="' + FONT_DEFAULT + '" size="9" color="#475569">'
        'Dieses Dokument fasst die im Beratungsgespraech dokumentierten '
        'Entscheide, Empfehlungen und naechsten Schritte zusammen.'
        '</font>',
        styles["body"],
    ))
    flowables.append(Spacer(1, 4 * mm))

    recommendation_summary = str(getattr(data, "latest_recommendation_summary", "") or "").strip()
    if recommendation_summary:
        flowables.append(_section_title("Empfehlung / Kontext"))
        flowables.append(Paragraph(
            f'<font name="{FONT_DEFAULT}" size="{FONT_SIZE_BODY}" color="#334155">'
            f'{_esc(recommendation_summary)}</font>',
            styles["body"],
        ))
        flowables.append(Spacer(1, 3 * mm))

    entries = list(getattr(data, "entries", []) or [])
    flowables.append(_section_title("Dokumentierte Entscheide"))
    if entries:
        flowables.append(_make_entries_table(entries))
    else:
        flowables.append(Paragraph(
            f'<font name="{FONT_DEFAULT}" size="9" color="#94a3b8"><i>'
            f'Noch kein Advisory-Log-Eintrag dokumentiert. Bitte im Review '
            f'& Abschluss einen Entscheid protokollieren.</i></font>',
            styles["small_muted"],
        ))

    # Bug-#13b (2026-06-08): Beratungsprotokoll-Bausteine aus der pro Mandat
    # gespeicherten Selektion (PR #244+#245). Wenn Bausteine ausgewaehlt
    # sind, erscheinen sie als eigener Abschnitt zwischen Entscheiden und
    # Konflikt-Hinweis. Custom-Override-Text hat Vorrang vor Bibliotheks-
    # Default (siehe _build_protokoll_data).
    bausteine = list(getattr(data, "selected_bausteine", []) or [])
    if bausteine:
        flowables.append(Spacer(1, 4 * mm))
        flowables.append(_section_title("Bausteine zum Beratungsprotokoll"))
        bausteine_sorted = sorted(
            bausteine,
            key=lambda b: (int((b or {}).get("sort_order", 0) or 0), str((b or {}).get("title", ""))),
        )
        for baustein in bausteine_sorted:
            if not isinstance(baustein, dict):
                continue
            title = str(baustein.get("title", "") or "Baustein").strip()
            category = (baustein.get("category") or "").strip()
            content = str(baustein.get("content_md", "") or "").strip()
            heading_parts = [_esc(title)]
            if category:
                heading_parts.append(
                    f'<font size="9" color="#64748b">&middot; {_esc(category)}</font>'
                )
            flowables.append(Paragraph(
                f'<font name="{FONT_BOLD}" size="11" color="#0f172a">'
                + " ".join(heading_parts)
                + "</font>",
                styles["body"],
            ))
            if content:
                # Plain-Text-Rendering: Newlines -> <br/>, kein voller Markdown-
                # Parser (kommt mit dem PDF-Bausteine-Sprint-Followup, falls
                # Berater Markdown wirklich braucht).
                safe = _esc(content).replace("\n", "<br/>")
                flowables.append(Paragraph(
                    f'<font name="{FONT_DEFAULT}" size="{FONT_SIZE_BODY}" color="#334155">'
                    f'{safe}</font>',
                    styles["body"],
                ))
            flowables.append(Spacer(1, 3 * mm))

    # Stage 7: Konflikt-Hinweis fuer FINMA-Audit, wenn die Allocation-Engine
    # mindestens einen Zielkonflikt klassifiziert hat. Pflichthinweis nach
    # Spec UX & Messages §5.2.
    conflict_messages = [
        msg for msg in list(getattr(data, "conflict_messages", []) or [])
        if isinstance(msg, dict)
        and str(msg.get("severity", "")).lower() == "conflict"
    ]
    if conflict_messages:
        flowables.append(Spacer(1, 4 * mm))
        flowables.append(_section_title("Dokumentierte Zielkonflikte"))
        for msg in conflict_messages:
            title = str(msg.get("title", "") or "Zielkonflikt").strip()
            body = str(msg.get("body_advisor", "") or msg.get("body_client", "") or "").strip()
            if body:
                sentence = (
                    "Im Beratungsgespräch wurde folgender Zielkonflikt dokumentiert: "
                    f"{title} — {body.rstrip('.')}."
                )
            else:
                sentence = (
                    "Im Beratungsgespräch wurde folgender Zielkonflikt dokumentiert: "
                    f"{title}."
                )
            flowables.append(Paragraph(
                f'<font name="{FONT_DEFAULT}" size="{FONT_SIZE_BODY}" color="#7f1d1d">{_esc(sentence)}</font>',
                styles["body"],
            ))
            flowables.append(Spacer(1, 2 * mm))

    flowables.append(Spacer(1, 8 * mm))
    flowables.extend(make_unterschrift_section())
    return flowables


def _make_entries_table(entries: list):
    rows = [["Datum", "Typ", "Entscheid / Titel", "Status"]]
    for entry in entries:
        title = str(entry.get("title", "") or "Beratungseintrag")
        description = str(entry.get("description", "") or "").strip()
        decision = str(entry.get("decision", "") or "").strip()
        detail_parts = [f'<font name="{FONT_BOLD}">{_esc(title)}</font>']
        if description:
            detail_parts.append(f'<font color="#475569">{_esc(description)}</font>')
        if decision:
            detail_parts.append(f'<font color="#0f172a">Entscheid: {_esc(decision)}</font>')
        rows.append([
            _format_date(str(entry.get("entry_date", "") or "")),
            _esc(str(entry.get("entry_type", "") or "Beratung")),
            Paragraph("<br/>".join(detail_parts), _para_cell()),
            _esc(str(entry.get("status", "") or "Dokumentiert")),
        ])

    page_width, _ = PAGE_SIZE
    table_width = page_width - 24 * mm
    table = Table(
        rows,
        colWidths=[
            table_width * 0.13,
            table_width * 0.17,
            table_width * 0.54,
            table_width * 0.16,
        ],
        repeatRows=1,
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
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return table


def _format_amount(rappen: int, currency: str = "CHF") -> str:
    # Bugfix 2026-08-07 (CEO/CFO/CIO-Audit): rappen ist bereits in
    # mandate.base_currency (siehe portfolio_engine._load_allocation_inputs).
    # Kein zweites convert_rappen("CHF"->currency) -- sonst doppelte FX-Konvertierung.
    try:
        value = rappen / 100.0
        return f"{currency} {value:,.0f}".replace(",", "'")
    except Exception:
        return f"CHF {rappen/100.0:,.0f}".replace(",", "'")


def _format_date(raw: str) -> str:
    if not raw:
        return "-"
    s = str(raw).strip()
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return f"{s[8:10]}.{s[5:7]}.{s[0:4]}"
    return s


def _section_title(text: str):
    style = make_paragraph_styles()["section_title"]
    return Paragraph(
        f'<font color="#475569" size="9"><b>{_esc(text).upper()}</b></font>',
        style,
    )


def _para_cell():
    from reportlab.lib.styles import ParagraphStyle
    return ParagraphStyle(
        "ProtokollCell",
        fontName=FONT_DEFAULT,
        fontSize=FONT_SIZE_TABLE,
        leading=11,
        spaceAfter=0,
    )
