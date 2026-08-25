"""Customer sign-off document for the final advisory decision."""
from __future__ import annotations

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, Spacer, Table, TableStyle

from services.pdf.base import ContractSignoffData, PDFContext
from services.pdf.components.depotcheck_soll import (
    make_sub_allocation_table,
    make_summary_text,
    make_target_allocation_bars,
)
from services.pdf.components.header import _esc, make_wealtharchitekten_header
from services.pdf.components.single_report_disclaimer import make_single_report_cover
from services.pdf.components.unterschrift import make_unterschrift_section
from services.pdf.styles import (
    COLOR_BORDER,
    COLOR_TEXT,
    COLOR_TEXT_LIGHT,
    FONT_BOLD,
    FONT_DEFAULT,
    PAGE_SIZE,
    make_paragraph_styles,
)


def build_contract_signoff_flowables(
    ctx: PDFContext,
    data: ContractSignoffData,
) -> list:
    """Compose the final document that customer and advisor can sign."""
    flowables: list = []
    advisory_label = (
        _format_amount(data.advisory_wealth_rappen, ctx.base_currency)
        if data.advisory_wealth_rappen
        else None
    )
    flowables.extend(make_single_report_cover(
        ctx,
        title="Beratungsentscheid",
        subtitle="Anlagestrategie und Kundenbestaetigung",
        mandate_number=data.mandate_number,
        advisory_wealth_label=advisory_label,
        focus_points=[
            "Dokumentiertes Risikoprofil und allfaelliger Override",
            "Gewaehlte Anlagestrategie mit Zielallokation und Bandbreiten",
            "Zusammenfassung der Beratung und finale Empfehlung",
            "Bestaetigung durch Kunde und Berater",
        ],
    ))
    flowables.append(PageBreak())

    _start_page(flowables, ctx, data, advisory_label, "Risikoprofil und Strategiewahl")
    flowables.append(_risk_strategy_table(data))
    flowables.append(Spacer(1, 7 * mm))
    if data.risk_is_overridden:
        flowables.append(_override_panel(data.risk_override_reason))
    else:
        flowables.append(_status_panel(
            "Kein manueller Override",
            "Die Strategiewahl basiert auf dem dokumentierten Risikoprofil.",
            colors.HexColor("#e8f2ec"),
            colors.HexColor("#2f6d4f"),
        ))
    flowables.append(Spacer(1, 7 * mm))
    flowables.append(make_summary_text(
        "Die Zielallokation darf das dokumentierte Risikobudget nicht "
        "ueberschreiten. Eine hoehere Zielrendite fuehrt deshalb nicht "
        "automatisch zu einer riskanteren Strategie."
    ))
    flowables.append(PageBreak())

    _start_page(flowables, ctx, data, advisory_label, "Zielallokation und Bandbreiten")
    flowables.append(make_target_allocation_bars(
        data.target_allocation_bps,
        data.bucket_bands_bps,
        row_height_mm=8.5,
    ))
    flowables.append(Spacer(1, 6 * mm))
    flowables.append(_allocation_table(
        data.target_allocation_bps,
        data.bucket_bands_bps,
        data.advisory_wealth_rappen,
        ctx.base_currency,
    ))
    flowables.append(PageBreak())

    _start_page(flowables, ctx, data, advisory_label, "Subanlageklassen und Ausrichtung")
    flowables.append(make_sub_allocation_table(data.sub_allocations, ctx.base_currency))
    flowables.append(Spacer(1, 7 * mm))
    flowables.append(_section_title("Portfolioausrichtung"))
    flowables.append(make_summary_text(
        data.portfolio_orientation
        or "Keine separate Portfolioausrichtung dokumentiert."
    ))
    flowables.append(PageBreak())

    _start_page(flowables, ctx, data, advisory_label, "Beratungsinhalt und Empfehlung")
    flowables.append(_section_title("Besprochene Inhalte"))
    flowables.append(_consultation_table(data.consultation_summary))
    flowables.append(Spacer(1, 7 * mm))
    flowables.append(_section_title("Finale Empfehlung"))
    flowables.append(make_summary_text(
        data.final_recommendation
        or "Die finale Empfehlung ist in der aktuellen Portfolioempfehlung dokumentiert."
    ))
    flowables.append(PageBreak())

    _start_page(flowables, ctx, data, advisory_label, "Aufklaerung und Bestaetigung")
    flowables.append(Paragraph(
        '<font name="{}" size="9.5" color="#334155">'
        'Mit der Unterzeichnung bestaetigen die Parteien die Besprechung und '
        'Dokumentation der nachstehenden Punkte. Die Unterschrift ersetzt '
        'keine Produktunterlagen oder Vertragsbedingungen.</font>'.format(FONT_DEFAULT),
        make_paragraph_styles()["body"],
    ))
    flowables.append(Spacer(1, 4 * mm))
    for item in data.client_acknowledgements or _default_acknowledgements():
        flowables.append(_acknowledgement_row(item))
        flowables.append(Spacer(1, 2 * mm))
    flowables.append(PageBreak())
    _start_page(flowables, ctx, data, advisory_label, "Unterschriften")
    flowables.append(Paragraph(
        '<font name="{}" size="9.5" color="#334155">'
        'Die nachstehenden Bestaetigungen beziehen sich auf das vollstaendige '
        'vorliegende Dokument und die im Beratungsgespraech uebergebenen '
        'Unterlagen.</font>'.format(FONT_DEFAULT),
        make_paragraph_styles()["body"],
    ))
    flowables.append(Spacer(1, 6 * mm))
    flowables.extend(make_unterschrift_section(
        client_confirm_text=(
            "Ich bestaetige, dass mir Risikoprofil, Zielallokation, "
            "Bandbreiten, Kosten, Risiken und die finale Empfehlung erklaert "
            "wurden. Einen dokumentierten Override habe ich ausdruecklich "
            "besprochen und bestaetigt."
        ),
        advisor_confirm_text=(
            "Der Berater bestaetigt, die Geeignetheit geprueft, die Empfehlung "
            "begruendet und die wesentlichen Risiken, Kosten sowie "
            "Zielkonflikte dokumentiert zu haben."
        ),
        signature_space_mm=18,
    ))
    return flowables


def _start_page(
    flowables: list,
    ctx: PDFContext,
    data: ContractSignoffData,
    advisory_label: str | None,
    title: str,
) -> None:
    flowables.extend(make_wealtharchitekten_header(
        ctx,
        mandate_number=data.mandate_number,
        advisory_wealth_label=advisory_label,
        document_title="Beratungsentscheid",
    ))
    flowables.append(Paragraph(
        f'<font name="{FONT_BOLD}" size="18" color="#0f172a">{_esc(title)}</font>',
        make_paragraph_styles()["heading"],
    ))
    flowables.append(Spacer(1, 4 * mm))


def _risk_strategy_table(data: ContractSignoffData) -> Table:
    rows = [
        ["Dokumentierter Punkt", "Festgehaltene Auspraegung"],
        ["Risikoprofil", data.risk_profile_label or "Nicht dokumentiert"],
        ["Risikoprofil manuell ueberschrieben", "Ja" if data.risk_is_overridden else "Nein"],
        ["Gewaehlte Anlagestrategie", data.strategy_name or "Strategische Zielallokation"],
        ["Berechnungsmethode", data.strategy_method or "Nicht dokumentiert"],
        ["Limitierender Faktor", _limiting_factor_label(data.limiting_factor)],
    ]
    return _table(rows, [0.38, 0.62])


def _override_panel(reason: str | None) -> Table:
    return _status_panel(
        "Manueller Risikoprofil-Override dokumentiert",
        "Begruendung: " + (reason or "Keine Begruendung hinterlegt."),
        colors.HexColor("#fbf4df"),
        colors.HexColor("#8a6718"),
    )


def _status_panel(title: str, body: str, bg, accent) -> Table:
    content = [
        Paragraph(
            f'<font name="{FONT_BOLD}" size="10" color="#0f172a">{_esc(title)}</font>',
            _cell_style(),
        ),
        Paragraph(
            f'<font name="{FONT_DEFAULT}" size="9" color="#475569">{_esc(body)}</font>',
            _cell_style(),
        ),
    ]
    table = Table([[content]], colWidths=[PAGE_SIZE[0] - 24 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg),
        ("LINEBEFORE", (0, 0), (0, -1), 2.2, accent),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))
    return table


def _allocation_table(allocation, bands, wealth, currency) -> Table:
    from services.pdf.styles import asset_class_label

    rows = [["Hauptanlageklasse", "Zielquote", "Band Min", "Band Max", "Zielbetrag"]]
    for bucket, value in sorted(
        allocation.items(),
        key=lambda item: -int(item[1] or 0),
    ):
        bps = int(value or 0)
        if bps <= 0:
            continue
        band = bands.get(bucket) or (bps, bps)
        amount = int((wealth or 0) * bps / 10000)
        rows.append([
            asset_class_label(bucket),
            f"{bps / 100:.1f}%",
            f"{int(band[0] or 0) / 100:.1f}%",
            f"{int(band[1] or 0) / 100:.1f}%",
            _format_amount(amount, currency),
        ])
    if len(rows) == 1:
        rows.append(["Keine Zielallokation", "-", "-", "-", "-"])
    return _table(rows, [0.36, 0.14, 0.14, 0.14, 0.22], numeric_start=1)


def _consultation_table(items: list) -> Table:
    rows = [["Datum / Status", "Thema", "Dokumentation"]]
    for item in items[:12]:
        if isinstance(item, str):
            rows.append(["-", "Beratungsinhalt", item])
            continue
        rows.append([
            str(item.get("entry_date") or item.get("status") or "-"),
            Paragraph(_esc(item.get("title") or item.get("entry_type") or "-"), _cell_style()),
            Paragraph(
                _esc(item.get("decision") or item.get("description") or "-"),
                _cell_style(),
            ),
        ])
    if len(rows) == 1:
        rows.append(["-", "Keine strukturierten Eintraege", "Beratung verbal dokumentiert."])
    return _table(rows, [0.18, 0.28, 0.54])


def _acknowledgement_row(text: str) -> Table:
    table = Table(
        [["[  ]", Paragraph(_esc(text), _cell_style())]],
        colWidths=[12 * mm, PAGE_SIZE[0] - 36 * mm],
    )
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TEXTCOLOR", (0, 0), (0, 0), COLOR_TEXT_LIGHT),
        ("FONTNAME", (0, 0), (0, 0), FONT_BOLD),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    return table


def _default_acknowledgements() -> list[str]:
    return [
        "Die Angaben zur persoenlichen und finanziellen Situation sowie zum Risikoprofil sind vollstaendig und korrekt besprochen worden.",
        "Die Geeignetheit der Empfehlung, wesentliche Risiken, Bandbreiten, Kosten und moegliche Zielkonflikte wurden erlaeutert.",
        "Ein allfaelliger manueller Override des Risikoprofils wurde mit Begruendung dokumentiert und vom Kunden bewusst bestaetigt.",
        "Der Kunde hat die relevanten Produkt-, Kosten- und Vertragsunterlagen erhalten oder weiss, wo diese verfuegbar sind.",
        "Personendaten werden fuer Beratung, Dokumentation, gesetzliche Nachweise und Vertragserfuellung gemaess revDSG bearbeitet.",
        "Es bestehen keine Zusicherungen zu kuenftiger Rendite, Zielerreichung oder Verlustfreiheit.",
    ]


def _table(rows: list[list], widths: list[float], numeric_start: int | None = None) -> Table:
    total_width = PAGE_SIZE[0] - 24 * mm
    table = Table(rows, colWidths=[total_width * value for value in widths], repeatRows=1)
    commands = [
        ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
        ("FONTNAME", (0, 1), (-1, -1), FONT_DEFAULT),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
        ("TEXTCOLOR", (0, 0), (-1, 0), COLOR_TEXT_LIGHT),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, COLOR_BORDER),
        ("LINEBELOW", (0, 1), (-1, -1), 0.3, COLOR_BORDER),
        ("FONTSIZE", (0, 0), (-1, 0), 7.5),
        ("FONTSIZE", (0, 1), (-1, -1), 8.5),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    if numeric_start is not None:
        commands.append(("ALIGN", (numeric_start, 1), (-1, -1), "RIGHT"))
    table.setStyle(TableStyle(commands))
    return table


def _section_title(text: str):
    return Paragraph(
        f'<font name="{FONT_BOLD}" color="#475569" size="9">{_esc(text).upper()}</font>',
        make_paragraph_styles()["section_title"],
    )


def _cell_style():
    from reportlab.lib.styles import ParagraphStyle

    return ParagraphStyle(
        "ContractSignoffCell",
        fontName=FONT_DEFAULT,
        fontSize=8.5,
        leading=11,
        textColor=COLOR_TEXT,
        spaceAfter=0,
    )


def _limiting_factor_label(value: str | None) -> str:
    labels = {
        "risikoprofil": "Risikoprofil",
        "liquiditaetsreserve": "Liquiditaetsreserve",
        "bandbreite": "Strategische Bandbreiten",
        "zielkonflikt": "Zielkonflikt",
        "solver_konvergenz": "Berechnung / Konvergenz",
    }
    return labels.get(str(value or "").lower(), str(value or "Nicht klassifiziert"))


def _format_amount(rappen: int | None, currency: str) -> str:
    return f"{currency} {int(rappen or 0) / 100:,.0f}".replace(",", "'")
