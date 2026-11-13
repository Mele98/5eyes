"""Sprint 12: Vertrags-PDF (ContractDocument).

Druckt einen einzelnen Vertrag (Anlagestrategie-Vertrag, Beratungsvertrag,
etc.) mit Praeambel, Haftungsklausel, Sondervereinbarungen und Unterschrift.

Inhalte stammen aus ContractDocument.content_json (per Frontend-Modal
m-contract-edit gepflegt).
"""
from __future__ import annotations

from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, Spacer, Table, TableStyle

from services.pdf.base import PDFContext
from services.pdf.components.header import _esc, make_banner_header
from services.pdf.components.unterschrift import make_unterschrift_section
from core.presentation_rounding import format_amount_minor
from services.pdf.styles import (
    COLOR_BORDER,
    COLOR_TEXT,
    COLOR_TEXT_LIGHT,
    FONT_BOLD,
    FONT_DEFAULT,
    FONT_SIZE_BODY,
    FONT_SIZE_HEADING,
    PAGE_SIZE,
    make_paragraph_styles,
)


def build_vertrag_flowables(ctx: PDFContext, data) -> list:
    """Vertrags-PDF Komposition.

    data ist VertragData mit:
    - document_title (str)
    - praeambel (str)
    - haftungsklausel (str)
    - sondervereinbarungen (str | None)
    - ort_unterzeichnung (str)
    - vereinbarungs_datum (str ISO yyyy-mm-dd oder dd.mm.yyyy)
    - mandate_number (str | None)
    - advisory_wealth_rappen (int | None)
    - document_type (str | None) — z.B. 'Anlagestrategie', 'Beratungsvertrag'
    """
    # H8 C-2: die Kundeninformation (Art. 8/9 FIDLEG) ist ein vorvertragliches
    # Dokument und laeuft ueber denselben Renderer.
    if getattr(data, "document_kind", None) == KUNDENINFORMATION_KIND:
        return build_kundeninformation_flowables(ctx, data)
    flowables: list = []
    styles = make_paragraph_styles()

    # ---- Header-Banner ----
    advisory_label = None
    if getattr(data, "advisory_wealth_rappen", None):
        advisory_label = _format_amount(data.advisory_wealth_rappen, ctx.base_currency)
    flowables.extend(make_banner_header(
        ctx,
        mandate_number=getattr(data, "mandate_number", None),
        advisory_wealth_label=advisory_label,
        document_title=str(getattr(data, "document_type", None) or "Vertrag"),
    ))

    # ---- Dokument-Titel ----
    doc_title = str(getattr(data, "document_title", "") or "Beratungsdokument")
    doc_type = str(getattr(data, "document_type", "") or "")
    flowables.append(Paragraph(
        f'<font name="{FONT_BOLD}" size="16" color="#0f172a">{_esc(doc_title)}</font>',
        _para_compact(after=2),
    ))
    if doc_type:
        flowables.append(Paragraph(
            f'<font name="{FONT_DEFAULT}" size="9" color="#64748b">'
            f'Dokument-Typ: {_esc(doc_type)}</font>',
            _para_compact(after=4),
        ))
    flowables.append(Spacer(1, 4 * mm))

    # ---- Praeambel ----
    praeambel = str(getattr(data, "praeambel", "") or "")
    if praeambel:
        flowables.append(_section_title("Präambel"))
        flowables.append(Paragraph(
            f'<font name="{FONT_DEFAULT}" size="{FONT_SIZE_BODY}" color="#334155">'
            f'{_esc(praeambel)}</font>',
            styles["body"],
        ))
        flowables.append(Spacer(1, 3 * mm))

    # ---- Vertragsgegenstand (Mandate-Daten als Kontext) ----
    flowables.append(_section_title("Vertragsgegenstand"))
    kontext_lines = []
    if getattr(data, "mandate_number", None):
        kontext_lines.append(("Mandat-Nummer", data.mandate_number))
    if getattr(data, "advisory_wealth_rappen", None):
        kontext_lines.append((
            "Beratungsvermögen",
            _format_amount(data.advisory_wealth_rappen, ctx.base_currency),
        ))
    kontext_lines.append(("Beratungsdatum", _format_date(getattr(data, "vereinbarungs_datum", ""))))
    kontext_lines.append((
        "Beratungsort",
        str(getattr(data, "ort_unterzeichnung", "Zürich") or "Zürich"),
    ))

    if kontext_lines:
        kontext_rows = [
            [
                Paragraph(f'<font color="#64748b" size="8"><b>{_esc(label).upper()}</b></font>',
                          _para_compact(after=0)),
                Paragraph(f'<font name="{FONT_BOLD}" size="10">{_esc(value)}</font>',
                          _para_compact(after=0)),
            ]
            for label, value in kontext_lines
        ]
        page_width, _ = PAGE_SIZE
        table_w = page_width - 24 * mm
        ktbl = Table(kontext_rows, colWidths=[table_w * 0.30, table_w * 0.70])
        ktbl.setStyle(TableStyle([
            ("LINEBELOW", (0, 0), (-1, -2), 0.3, COLOR_BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        flowables.append(ktbl)
    flowables.append(Spacer(1, 4 * mm))

    # ---- Haftungsklausel ----
    haftung = str(getattr(data, "haftungsklausel", "") or "")
    if haftung:
        flowables.append(_section_title("Beratungshinweis & Haftung"))
        flowables.append(Paragraph(
            f'<font name="{FONT_DEFAULT}" size="{FONT_SIZE_BODY}" color="#334155">'
            f'{_esc(haftung)}</font>',
            styles["body"],
        ))
        flowables.append(Spacer(1, 3 * mm))

    # ---- Sondervereinbarungen ----
    sonder = str(getattr(data, "sondervereinbarungen", "") or "")
    if sonder:
        flowables.append(_section_title("Sondervereinbarungen"))
        flowables.append(Paragraph(
            f'<font name="{FONT_DEFAULT}" size="{FONT_SIZE_BODY}" color="#334155">'
            f'{_esc(sonder)}</font>',
            styles["body"],
        ))
        flowables.append(Spacer(1, 4 * mm))

    # ---- Bestätigung & Unterschrift (Standard-Komponente) ----
    flowables.extend(make_unterschrift_section())

    return flowables


def _format_amount(rappen: int, currency: str = "CHF") -> str:
    # Bugfix 2026-08-07 (CEO/CFO/CIO-Audit): rappen ist bereits in
    # mandate.base_currency (siehe portfolio_engine._load_allocation_inputs).
    # Kein zweites convert_rappen("CHF"->currency) -- sonst doppelte FX-Konvertierung.
    return format_amount_minor(rappen, currency or "CHF")


def _format_date(raw: str) -> str:
    """ISO yyyy-mm-dd → dd.mm.yyyy. Sonst Original."""
    if not raw:
        return "—"
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


def _para_compact(after: float = 2):
    from reportlab.lib.styles import ParagraphStyle
    return ParagraphStyle(
        "VertCell",
        fontName=FONT_DEFAULT,
        fontSize=FONT_SIZE_BODY,
        leading=12,
        spaceAfter=after,
    )


# ---------------------------------------------------------------------------
# H8 C-2 (Compliance-Audit 2026-11-07): Kundeninformation nach Art. 8/9 FIDLEG.
#
# Vorvertragliches Dokument, deshalb ueber den Vertrags-Renderer
# (render_vertrag -> build_vertrag_flowables) mit ``document_kind``
# "kundeninformation". Die Angaben zum Finanzdienstleister kommen
# ausschliesslich aus den rechtlichen Angaben des Tenants. Die allgemeinen
# Texte unten sind eine eigene, sachliche Formulierung von Ares
# (COMPLIANCE-GEGENLESEN vor dem ersten echten Kunden, siehe Handoff H-148).
# Jede inhaltliche Textaenderung braucht eine neue Vorlagenversion
# (services/recommendation_release_gate.py::CLIENT_INFORMATION_TEMPLATE_VERSION).
# ---------------------------------------------------------------------------

KUNDENINFORMATION_KIND = "kundeninformation"

KUNDENINFORMATION_SERVICE_TEXTS: dict[str, str] = {
    "Vermögensverwaltung": (
        "Vermögensverwaltung: Der Finanzdienstleister verwaltet das vereinbarte "
        "Vermögen nach eigenem Ermessen im Rahmen der mit Ihnen festgelegten "
        "Anlagestrategie und trifft die einzelnen Anlageentscheide in Ihrem Namen. "
        "Risiken der Dienstleistung: Einzelne Entscheide werden ohne Ihre vorgängige "
        "Zustimmung getroffen. Die Wertentwicklung hängt von der vereinbarten "
        "Strategie und den Marktverhältnissen ab und kann negativ sein."
    ),
    "Anlageberatung": (
        "Anlageberatung: Der Finanzdienstleister gibt Ihnen persönliche Empfehlungen "
        "zu Geschäften mit Finanzinstrumenten unter Berücksichtigung Ihres Portfolios. "
        "Sie entscheiden selbst, ob Sie einer Empfehlung folgen. Risiken der "
        "Dienstleistung: Empfehlungen beruhen auf Ihren Angaben und auf Einschätzungen "
        "zum Zeitpunkt der Beratung. Die Entscheide und das Anlagerisiko tragen Sie."
    ),
    "Finanzplanung": (
        "Finanzplanung: Analyse und Planung Ihrer finanziellen Situation (Vermögen, "
        "Einkommen, Ausgaben, Ziele). Werden dabei persönliche Empfehlungen zu "
        "Finanzinstrumenten abgegeben, gelten dafür die Regeln der Anlageberatung."
    ),
    "Reporting only": (
        "Berichterstattung: Darstellung und Auswertung Ihres Vermögens, ohne "
        "persönliche Empfehlungen zu Finanzinstrumenten."
    ),
}

KUNDENINFORMATION_GENERAL_RISKS: tuple[str, ...] = (
    "Marktrisiko: Die Kurse von Finanzinstrumenten schwanken. Verluste bis zum "
    "vollständigen Verlust des eingesetzten Kapitals sind möglich.",
    "Währungsrisiko: Anlagen in einer anderen als Ihrer Referenzwährung unterliegen "
    "Wechselkursschwankungen.",
    "Zins- und Kreditrisiko: Zinsänderungen beeinflussen die Kurse von Anleihen. "
    "Schuldner können zahlungsunfähig werden.",
    "Liquiditätsrisiko: Manche Finanzinstrumente lassen sich nicht jederzeit oder "
    "nur mit Preisabschlag verkaufen.",
    "Konzentrationsrisiko: Eine geringe Streuung über Anlagen, Schuldner, Branchen "
    "oder Länder erhöht das Verlustrisiko.",
    "Alternative und komplexe Anlagen (z. B. Private Equity, Hedge Funds, "
    "Derivate): Hebelwirkung, eingeschränkte Transparenz und lange Bindungsfristen "
    "können die Risiken erhöhen.",
    "Vergangene Wertentwicklungen und Prognosen sind keine Gewähr für künftige "
    "Ergebnisse.",
)

KUNDENINFORMATION_DOCUMENTS_NOTE = (
    "Zu den einzelnen Finanzinstrumenten erhalten Sie, soweit erstellt, das "
    "Basisinformationsblatt und den Prospekt kostenlos auf Anfrage."
)

KUNDENINFORMATION_OMBUDSMAN_INTRO = (
    "Bei Streitigkeiten können Sie ein Vermittlungsverfahren bei der folgenden "
    "Ombudsstelle einleiten (Art. 74 ff. FIDLEG):"
)

KUNDENINFORMATION_RECEIPT_TEXT = (
    "Ich bestätige, diese Kundeninformation vor Abschluss des Vertrags erhalten "
    "zu haben."
)


def _ki_paragraph(text: str, styles) -> Paragraph:
    return Paragraph(
        f'<font name="{FONT_DEFAULT}" size="{FONT_SIZE_BODY}" color="#334155">'
        f'{_esc(text)}</font>',
        styles["body"],
    )


def _ki_pairs_table(pairs) -> Table:
    page_width, _ = PAGE_SIZE
    table_w = page_width - 24 * mm
    rows = [
        [
            Paragraph(f'<font color="#64748b" size="8"><b>{_esc(label).upper()}</b></font>',
                      _para_compact(after=0)),
            Paragraph(f'<font name="{FONT_DEFAULT}" size="9">{_esc(value)}</font>',
                      _para_compact(after=0)),
        ]
        for label, value in pairs
    ]
    table = Table(rows, colWidths=[table_w * 0.32, table_w * 0.68])
    table.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, COLOR_BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return table


def build_kundeninformation_flowables(ctx: PDFContext, data) -> list:
    styles = make_paragraph_styles()
    flowables: list = []
    flowables.extend(make_banner_header(
        ctx,
        mandate_number=getattr(data, "mandate_number", None),
        advisory_wealth_label=None,
        document_title="Kundeninformation",
    ))
    flowables.append(Paragraph(
        f'<font name="{FONT_BOLD}" size="16" color="#0f172a">'
        'Kundeninformation vor Vertragsabschluss</font>',
        _para_compact(after=2),
    ))
    flowables.append(Paragraph(
        f'<font name="{FONT_DEFAULT}" size="9" color="#64748b">'
        'Informationen nach Art. 8 und 9 FIDLEG über den Finanzdienstleister, die '
        'Dienstleistung, die Risiken, die Kosten, wirtschaftliche Bindungen und das '
        'berücksichtigte Marktangebot.</font>',
        _para_compact(after=4),
    ))

    flowables.append(_section_title("Finanzdienstleister"))
    flowables.append(_ki_pairs_table(tuple(data.provider_lines)))
    flowables.append(Spacer(1, 3 * mm))

    flowables.append(_section_title("Ombudsstelle"))
    flowables.append(_ki_paragraph(KUNDENINFORMATION_OMBUDSMAN_INTRO, styles))
    flowables.append(_ki_pairs_table((
        ("Ombudsstelle", data.ombudsman_name),
        ("Adresse", data.ombudsman_address),
    )))
    flowables.append(Spacer(1, 3 * mm))

    flowables.append(_section_title("Dienstleistung und ihre Risiken"))
    service_text = KUNDENINFORMATION_SERVICE_TEXTS.get(str(data.mandate_type or ""))
    flowables.append(_ki_paragraph(
        service_text
        or f"Vereinbarte Dienstleistung: {data.mandate_type or 'nicht festgelegt'}.",
        styles,
    ))
    flowables.append(Spacer(1, 3 * mm))

    flowables.append(_section_title("Allgemeine Risiken von Finanzinstrumenten"))
    for line in KUNDENINFORMATION_GENERAL_RISKS:
        flowables.append(_ki_paragraph(f"• {line}", styles))
    flowables.append(_ki_paragraph(KUNDENINFORMATION_DOCUMENTS_NOTE, styles))
    flowables.append(Spacer(1, 3 * mm))

    flowables.append(_section_title("Kosten"))
    if data.cost_lines:
        flowables.append(_ki_pairs_table(tuple(data.cost_lines)))
    if data.cost_note:
        flowables.append(_ki_paragraph(data.cost_note, styles))
    for line in data.retrocession_lines:
        flowables.append(_ki_paragraph(line, styles))
    flowables.append(Spacer(1, 3 * mm))

    flowables.append(_section_title("Wirtschaftliche Bindungen an Dritte"))
    for line in data.economic_ties:
        flowables.append(_ki_paragraph(line, styles))
    flowables.append(Spacer(1, 3 * mm))

    flowables.append(_section_title("Berücksichtigtes Marktangebot"))
    for line in data.market_offer_lines:
        flowables.append(_ki_paragraph(line, styles))
    flowables.append(Spacer(1, 3 * mm))

    flowables.append(_section_title("Ausführung und Verwahrung"))
    bank = str(data.depot_bank or "").strip()
    flowables.append(_ki_paragraph(
        "Aufträge werden über die Depotbank ausgeführt; dort wird das Vermögen "
        "verwahrt" + (f" ({bank})." if bank else "."),
        styles,
    ))
    flowables.append(Spacer(1, 3 * mm))

    flowables.append(Paragraph(
        f'<font name="{FONT_DEFAULT}" size="7" color="#64748b">'
        f'Vorlage {_esc(data.template_version)} · Rechtliche Angaben Revision '
        f'{int(data.legal_profile_revision)} · {_esc(str(data.legal_profile_hash)[:12])}</font>',
        _para_compact(after=4),
    ))
    flowables.extend(make_unterschrift_section(
        client_confirm_text=KUNDENINFORMATION_RECEIPT_TEXT,
        advisor_confirm_text="Übergeben durch:",
    ))
    return flowables
