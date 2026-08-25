"""Risikoprofil-PDF: vollständige FINMA-taugliche Kundendokumentation."""
from __future__ import annotations

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from services.pdf.base import PDFContext, RisikoprofilData
from services.pdf.components.eignungspruefung import make_eignungspruefung_section
from services.pdf.components.header import _esc, make_wealtharchitekten_header
from services.pdf.components.unterschrift import make_unterschrift_section
from services.pdf.styles import (
    COLOR_BORDER,
    COLOR_TABLE_HEADER_BG,
    FONT_BOLD,
    FONT_DEFAULT,
    PAGE_SIZE,
    make_paragraph_styles,
)


def build_risikoprofil_flowables(
    ctx: PDFContext, data: RisikoprofilData
) -> list:
    """Rendert Risikoprofil, Fragebogen, Override-Nachweis und Signatur."""
    styles = make_paragraph_styles()
    flowables: list = []
    advisory_label = (
        _format_amount(data.advisory_wealth_rappen, ctx.base_currency)
        if data.advisory_wealth_rappen
        else None
    )

    flowables.extend(make_wealtharchitekten_header(
        ctx,
        mandate_number=data.mandate_number,
        advisory_wealth_label=advisory_label,
        document_title="Risikoprofil",
    ))
    flowables.append(_intro_block(styles))
    flowables.append(Spacer(1, 4 * mm))

    flowables.append(_profile_summary_table(data, styles))

    if data.is_overridden:
        flowables.append(Spacer(1, 4 * mm))
        flowables.append(_override_documentation(data, styles))

    flowables.append(Spacer(1, 5 * mm))
    flowables.extend(make_eignungspruefung_section(
        answers=data.risk_answers,
        services_knowledge=data.knowledge_services,
        instruments_knowledge=data.knowledge_instruments,
    ))

    if data.suitability_note:
        flowables.append(Spacer(1, 5 * mm))
        flowables.append(_section_title("Beraterdokumentation"))
        flowables.append(Paragraph(_esc(data.suitability_note), styles["body"]))

    flowables.append(Spacer(1, 6 * mm))
    flowables.append(_section_title("Rechtlicher Hinweis"))
    flowables.append(Paragraph(
        "Dieses Dokument hält die Angaben zur Risikofähigkeit, "
        "Risikobereitschaft sowie zu Kenntnissen und Erfahrungen fest. "
        "Es dient als Gesprächs- und Nachweisdokumentation für die "
        "Eignungsprüfung; interne Punktewerte werden im Kundendokument "
        "bewusst nicht ausgewiesen.",
        styles["disclaimer"],
    ))

    flowables.append(Spacer(1, 8 * mm))
    flowables.extend(make_unterschrift_section(
        client_confirm_text=(
            "Ich bestätige, dass die vorstehenden Angaben zu Risikoprofil, "
            "Kenntnissen und Erfahrungen im Beratungsgespräch besprochen "
            "und korrekt dokumentiert wurden."
        ),
        advisor_confirm_text=(
            "Der Anlageberater bestätigt, das Risikoprofil, allfällige "
            "Übersteuerungen und die Eignungsprüfung dokumentiert zu haben."
        ),
    ))

    return flowables


def _intro_block(styles) -> Table:
    page_width, _ = PAGE_SIZE
    table_width = page_width - 24 * mm
    body = Paragraph(
        "Zusammenfassung der dokumentierten Risikoprofilierung. "
        "Der Fragebogen wird vollständig mit Frage und Antwort ausgewiesen, "
        "damit der Kunde die Angaben vor Unterzeichnung prüfen kann.",
        styles["body"],
    )
    table = Table([[body]], colWidths=[table_width])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ("BOX", (0, 0), (-1, -1), 0.5, COLOR_BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return table


def _profile_summary_table(data: RisikoprofilData, styles) -> Table:
    page_width, _ = PAGE_SIZE
    table_width = page_width - 24 * mm
    horizon = f"{data.experience_years} Jahre" if data.experience_years else "Nicht dokumentiert"
    mandate_type = data.mandate_type or "Nicht dokumentiert"
    override = "Ja" if data.is_overridden else "Nein"
    rows = [
        [
            _metric_cell("Risikoprofil", data.risk_profile_label or "Nicht definiert", styles),
            _metric_cell("Anlagehorizont", horizon, styles),
            _metric_cell("Mandat", mandate_type, styles),
            _metric_cell("Übersteuert", override, styles),
        ]
    ]
    table = Table(rows, colWidths=[table_width / 4] * 4)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ("BOX", (0, 0), (-1, -1), 0.5, COLOR_BORDER),
        ("LINEAFTER", (0, 0), (-2, -1), 0.25, COLOR_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return table


def _metric_cell(label: str, value: str, styles) -> Paragraph:
    return Paragraph(
        f'<font name="{FONT_DEFAULT}" size="7" color="#64748b">{_esc(label).upper()}</font>'
        f'<br/><font name="{FONT_BOLD}" size="11" color="#0f172a">{_esc(value)}</font>',
        styles["body"],
    )


def _override_documentation(data: RisikoprofilData, styles) -> Table:
    page_width, _ = PAGE_SIZE
    table_width = page_width - 24 * mm
    rows = [
        ["Übersteuerung", "Dokumentierter Stand"],
        ["Begründung", data.override_reason or "Nicht dokumentiert"],
        [
            "Kundenbestätigung",
            "Ja" if data.override_client_confirmed else "Noch nicht dokumentiert",
        ],
        [
            "Warnhinweis",
            "Zugestellt" if data.override_warning_delivered else "Noch nicht dokumentiert",
        ],
    ]
    table = Table(
        [[Paragraph(_esc(str(left)), styles["body"]), Paragraph(_esc(str(right)), styles["body"])]
         for left, right in rows],
        colWidths=[table_width * 0.32, table_width * 0.68],
    )
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_TABLE_HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#475569")),
        ("BOX", (0, 0), (-1, -1), 0.5, COLOR_BORDER),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, COLOR_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def _section_title(text: str):
    style = make_paragraph_styles()["section_title"]
    return Paragraph(
        f'<font name="{FONT_BOLD}" size="12" color="#0f172a">{_esc(text)}</font>',
        style,
    )


def _format_amount(value_rappen: int | None, currency: str = "CHF") -> str:
    if not value_rappen:
        return ""
    amount = int(round(value_rappen / 100))
    return f"{currency} {amount:,.0f}".replace(",", "'")
