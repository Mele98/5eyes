"""Cover and disclaimer blocks for narrow single-rubric PDFs."""
from __future__ import annotations

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import HRFlowable, Paragraph, Spacer, Table, TableStyle

from services.pdf.base import PDFContext
from services.pdf.components.header import _esc
from services.pdf.styles import (
    COLOR_BORDER,
    COLOR_HEADER_BG,
    COLOR_TEXT,
    FONT_BOLD,
    FONT_DEFAULT,
    PAGE_SIZE,
    make_paragraph_styles,
)


def make_single_report_cover(
    ctx: PDFContext,
    *,
    title: str,
    subtitle: str,
    mandate_number: str | None = None,
    advisory_wealth_label: str | None = None,
) -> list:
    """Simple title page for one focused report extract."""
    page_width, _ = PAGE_SIZE
    table_width = page_width - 24 * mm
    org = ctx.advisor_org or ctx.advisor_name or "Emanuele Konzelmann"
    rows = [
        ["Berater", ctx.advisor_name or "-"],
        ["Mandat", ctx.mandate_name or "-"],
        ["Datum", ctx.report_date.strftime("%d.%m.%Y")],
    ]
    if mandate_number:
        rows.append(["Mandatsnummer", mandate_number])
    if advisory_wealth_label:
        rows.append(["Beratungsvermoegen", advisory_wealth_label])

    info_table = Table(
        [
            [
                Paragraph(
                    f'<font name="{FONT_BOLD}" color="#64748b" size="8">{_esc(label).upper()}</font>',
                    _cover_line(),
                ),
                Paragraph(
                    f'<font name="{FONT_DEFAULT}" color="#0f172a" size="10">{_esc(value)}</font>',
                    _cover_line(),
                ),
            ]
            for label, value in rows
        ],
        colWidths=[table_width * 0.28, table_width * 0.72],
    )
    info_table.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, COLOR_BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))

    return [
        Spacer(1, 12 * mm),
        Paragraph(
            f'<font name="{FONT_BOLD}" size="10" color="#64748b">{_esc(org).upper()}</font>',
            _cover_title(10, after=5 * mm),
        ),
        Paragraph(
            f'<font name="{FONT_BOLD}" size="34" color="#0f172a">{_esc(title)}</font>',
            _cover_title(34, after=4 * mm),
        ),
        Paragraph(
            f'<font name="{FONT_DEFAULT}" size="12" color="#475569">{_esc(subtitle)}</font>',
            _cover_title(12, after=8 * mm),
        ),
        _horizontal_line(1.0),
        Spacer(1, 12 * mm),
        info_table,
        Spacer(1, 24 * mm),
        _horizontal_line(0.5, colors.HexColor("#cbd5e1")),
        Spacer(1, 6 * mm),
        Paragraph(
            '<font name="Helvetica-Oblique" size="10" color="#64748b">'
            'Isolierter Auszug aus dem Beratungsprozess. Das vollstaendige '
            'Kundendossier wird im Abschlussbericht dokumentiert.</font>',
            _cover_title(10, after=0),
        ),
    ]


def make_single_report_disclaimer(
    *,
    title: str,
    scope: str,
) -> list:
    """Legal disclaimer for customer-requested single-section PDFs."""
    styles = make_paragraph_styles()
    paragraphs = [
        (
            f"Dieser Bericht ist ein isolierter Auszug zur Rubrik {scope}. "
            "Er wurde auf Kundenwunsch bzw. zur gezielten Besprechung "
            "erstellt und basiert auf den im System zum Erstellungszeitpunkt "
            "erfassten Kundendaten, Praeferenzen, Werten und "
            "Berechnungsannahmen."
        ),
        (
            "Der Auszug ersetzt nicht das vollstaendige Beratungsdossier, "
            "keine vollstaendige Beratung, keine Vertragsdokumentation und "
            "keine abschliessende Anlageempfehlung. Fuer die Gesamtbeurteilung "
            "sind immer alle weiteren Beratungs- und Vertragsunterlagen, die "
            "finanzielle Situation, der Anlagehorizont, Praeferenzen, Kosten, "
            "Produktunterlagen und das vollstaendige Abschlussdokument "
            "gemeinsam massgeblich."
        ),
        (
            "Die dargestellten Quoten, Produkte, Werte, Kurse, Risiken und "
            "Kosten koennen sich veraendern. Abweichungen durch Marktbewegungen, "
            "Rundungen, fehlende Daten, Drittquellen, Produktverfuegbarkeit, "
            "Steuern, Transaktionskosten oder Mindeststueckelungen sind moeglich."
        ),
        (
            "Es wird keine Garantie fuer Vollstaendigkeit, Richtigkeit, "
            "kuenftige Wertentwicklung, Zielerreichung oder Umsetzbarkeit "
            "uebernommen. Eine Haftung fuer Entscheide, die allein auf diesem "
            "Einzelauszug beruhen, wird soweit gesetzlich zulaessig "
            "ausgeschlossen."
        ),
        (
            "Dieses Dokument ist vertraulich und nur fuer den bezeichneten "
            "Kunden bzw. das bezeichnete Mandat bestimmt. Eine Weitergabe an "
            "Dritte oder eine Verwendung ausserhalb des dokumentierten "
            "Beratungskontexts bedarf einer separaten Pruefung."
        ),
    ]

    flowables = [
        Paragraph(
            f'<font name="{FONT_BOLD}" size="18" color="#0f172a">{_esc(title)}</font>',
            styles["section_title"],
        ),
        Spacer(1, 5 * mm),
        _horizontal_line(0.8, COLOR_HEADER_BG),
        Spacer(1, 6 * mm),
    ]
    for para in paragraphs:
        flowables.append(Paragraph(
            f'<font name="{FONT_DEFAULT}" size="9" color="#334155">{_esc(para)}</font>',
            styles["body"],
        ))
        flowables.append(Spacer(1, 2 * mm))
    return flowables


def _horizontal_line(thickness: float, color=None):
    return HRFlowable(
        width="100%",
        thickness=thickness,
        color=color or colors.HexColor("#0f172a"),
        spaceBefore=0,
        spaceAfter=0,
    )


def _cover_line():
    from reportlab.lib.styles import ParagraphStyle

    return ParagraphStyle(
        "SingleReportCoverLine",
        fontName=FONT_DEFAULT,
        fontSize=10,
        leading=13,
        spaceAfter=0,
    )


def _cover_title(size: int, *, after: float):
    from reportlab.lib.styles import ParagraphStyle

    return ParagraphStyle(
        f"SingleReportCoverTitle{size}",
        fontName=FONT_DEFAULT,
        fontSize=size,
        leading=max(size * 1.25, 13),
        spaceAfter=after,
    )
