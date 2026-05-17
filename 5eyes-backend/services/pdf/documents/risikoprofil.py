"""Risikoprofil-PDF — FINMA W305.02/W305.03-konform (Phase 3, Stub jetzt)."""
from __future__ import annotations

from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from services.pdf.base import PDFContext, RisikoprofilData
from services.pdf.components.header import _esc, make_document_header
from services.pdf.styles import (
    COLOR_BORDER,
    FONT_BOLD,
    FONT_DEFAULT,
    FONT_SIZE_BODY,
    make_paragraph_styles,
)


def build_risikoprofil_flowables(
    ctx: PDFContext, data: RisikoprofilData
) -> list:
    """Stub fuer Risikoprofil-PDF — Vollausbau in Sprint 5 Phase 3."""
    styles = make_paragraph_styles()
    flowables: list = []

    flowables.extend(make_document_header("Risikoprofil", ctx))

    flowables.append(Paragraph("Profil-Klassifikation", styles["heading"]))
    flowables.append(Paragraph(
        f"<b>Risikoprofil:</b> {_esc(data.risk_profile_label)}", styles["body"]
    ))
    flowables.append(Paragraph(
        f"<b>Risikofaehigkeit:</b> {data.risk_capacity_score} / 100",
        styles["body"],
    ))
    flowables.append(Paragraph(
        f"<b>Risikotoleranz:</b> {data.risk_tolerance_score} / 100", styles["body"]
    ))
    flowables.append(Paragraph(
        f"<b>Anlageerfahrung:</b> {data.experience_years} Jahre", styles["body"]
    ))

    if data.knowledge_services:
        flowables.append(Spacer(1, 3 * mm))
        flowables.append(Paragraph("Kenntnisse Finanzdienstleistungen (W305.02)", styles["subheading"]))
        ks_rows = [["Dienstleistung", "Bekannt"]]
        for k, v in data.knowledge_services.items():
            ks_rows.append([_esc(str(k)), "Ja" if v else "Nein"])
        ks_table = Table(ks_rows, colWidths=[110 * mm, 30 * mm])
        ks_table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
            ("FONTSIZE", (0, 0), (-1, -1), FONT_SIZE_BODY),
            ("LINEBELOW", (0, 0), (-1, 0), 1.0, COLOR_BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
        ]))
        flowables.append(ks_table)

    if data.knowledge_instruments:
        flowables.append(Spacer(1, 3 * mm))
        flowables.append(Paragraph("Kenntnisse Finanzinstrumente (W305.03)", styles["subheading"]))
        ki_rows = [["Instrument", "Bekannt"]]
        for k, v in data.knowledge_instruments.items():
            ki_rows.append([_esc(str(k)), "Ja" if v else "Nein"])
        ki_table = Table(ki_rows, colWidths=[110 * mm, 30 * mm])
        ki_table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
            ("FONTSIZE", (0, 0), (-1, -1), FONT_SIZE_BODY),
            ("LINEBELOW", (0, 0), (-1, 0), 1.0, COLOR_BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
        ]))
        flowables.append(ki_table)

    if data.suitability_note:
        flowables.append(Spacer(1, 5 * mm))
        flowables.append(Paragraph("Eignungspruefung", styles["heading"]))
        flowables.append(Paragraph(_esc(data.suitability_note), styles["body"]))

    flowables.append(Spacer(1, 8 * mm))
    flowables.append(Paragraph(
        "Dieser Bericht dokumentiert die Risikoprofil-Erhebung gemaess "
        "FINMA Wegleitung 305.02/305.03 (Eignungspruefung). Daten basieren "
        "auf den Angaben des Mandanten.",
        styles["disclaimer"],
    ))

    return flowables
