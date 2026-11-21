"""Customer sign-off document for the final advisory decision."""
from __future__ import annotations

from core.customer_terms import customer_suitability_text
from core.preference_labels import method_label
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, Spacer, Table, TableStyle

from services.pdf.base import ContractSignoffData, PDFContext
from services.pdf.components.band_deviation import make_band_deviation_section
from services.pdf.components.depotcheck_soll import (
    make_sub_allocation_table,
    make_summary_text,
    make_target_allocation_bars,
)
from services.pdf.components.header import _esc, make_banner_header
from services.pdf.components.single_report_disclaimer import make_single_report_cover
from services.pdf.components.unterschrift import make_unterschrift_section
from core.presentation_rounding import allocation_pct_texts, format_amount_minor, format_bps_as_pct
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
        subtitle="Anlagestrategie und Kundenbestätigung",
        mandate_number=data.mandate_number,
        advisory_wealth_label=advisory_label,
        focus_points=[
            "Dokumentiertes Risikoprofil und allfällige manuelle Anpassung",
            "Gewählte Anlagestrategie mit Zielallokation und Bandbreiten",
            "Zusammenfassung der Beratung und finale Empfehlung",
            "Bestätigung durch Kunde und Berater",
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
            "Keine manuelle Anpassung des Risikoprofils",
            "Die Strategiewahl basiert auf dem dokumentierten Risikoprofil.",
            colors.HexColor("#e8f2ec"),
            colors.HexColor("#2f6d4f"),
        ))
    flowables.append(Spacer(1, 7 * mm))
    flowables.append(make_summary_text(
        "Die Zielallokation darf das dokumentierte Risikobudget nicht "
        "überschreiten. Eine höhere Zielrendite führt deshalb nicht "
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
    # BAND-DEVIATION-REASON-REQUIRED-001: der Kunde bestaetigt die Abweichung
    # vom Eignungsrahmen des Risikoprofils samt Begruendung mit.
    flowables.extend(make_band_deviation_section(
        data.band_house_deviations,
        profile_label=data.band_house_profile,
        reason=data.band_deviation_reason,
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
        # SIGN-CLAIM-001: ohne belegte finale Empfehlung keine Behauptung.
        or "Für dieses Mandat liegt keine finalisierte Empfehlung vor."
    ))
    flowables.append(PageBreak())

    _start_page(flowables, ctx, data, advisory_label, "Aufklärung und Bestätigung")
    flowables.append(Paragraph(
        '<font name="{}" size="9.5" color="#334155">'
        'Mit der Unterzeichnung bestätigen die Parteien die Besprechung und '
        'Dokumentation der nachstehenden Punkte. Die Unterschrift ersetzt '
        'keine Produktunterlagen oder Vertragsbedingungen.</font>'.format(FONT_DEFAULT),
        make_paragraph_styles()["body"],
    ))
    flowables.append(Spacer(1, 4 * mm))
    acknowledgements = list(data.client_acknowledgements or _default_acknowledgements(data))
    if data.band_house_deviations and not data.client_acknowledgements:
        acknowledgements.insert(2, (
            "Die Abweichung vom Eignungsrahmen des Risikoprofils (vereinbarte "
            "Bandbreiten ausserhalb des Rahmens des Risikoprofils) und ihre "
            "dokumentierte Begründung wurden erläutert und vom Kunden bewusst "
            "bestätigt."
        ))
    for item in acknowledgements:
        flowables.append(_acknowledgement_row(item))
        flowables.append(Spacer(1, 2 * mm))
    flowables.append(PageBreak())
    _start_page(flowables, ctx, data, advisory_label, "Unterschriften")
    flowables.append(Paragraph(
        '<font name="{}" size="9.5" color="#334155">'
        'Die nachstehenden Bestätigungen beziehen sich auf das vollständige '
        'vorliegende Dokument und die im Beratungsgespräch übergebenen '
        'Unterlagen.</font>'.format(FONT_DEFAULT),
        make_paragraph_styles()["body"],
    ))
    flowables.append(Spacer(1, 6 * mm))
    if (getattr(ctx, "watermark_mode", "none") or "none") == UNPUBLISHED_MODE:
        # N-910-01: Soll-Allokation nicht (gueltig) publiziert -> kein
        # Unterschriftsblock, nur der Hinweis (Entwurf, nie archiviert).
        flowables.append(_not_for_signature_box())
        return flowables
    flowables.extend(make_unterschrift_section(
        client_confirm_text=(
            "Ich bestätige, dass mir Risikoprofil, Zielallokation, "
            "Bandbreiten, Kosten, Risiken und die finale Empfehlung erklärt "
            "wurden. Eine dokumentierte manuelle Anpassung des Risikoprofils "
            "habe ich ausdrücklich besprochen und bestätigt."
        ),
        advisor_confirm_text=advisor_confirm_text(data),
        signature_space_mm=18,
    ))
    return flowables


UNPUBLISHED_MODE = "unpublished"
NOT_FOR_SIGNATURE_TEXT = "Nicht zur Unterzeichnung"


def _not_for_signature_box() -> Table:
    """Ersatz des Unterschriftsblocks fuer einen Entwurf (N-910-01)."""
    text = (
        f'<font name="{FONT_BOLD}" size="12" color="#B91C1C">{NOT_FOR_SIGNATURE_TEXT}</font><br/>'
        f'<font name="{FONT_DEFAULT}" size="9" color="#334155">'
        "Entwurf – die Soll-Allokation ist nicht publiziert. Dieses Dokument dient "
        "der Besprechung; unterzeichnet wird erst die Fassung nach der Publikation.</font>"
    )
    box = Table([[Paragraph(text, make_paragraph_styles()["body"])]], colWidths=[PAGE_SIZE[0] - 24 * mm])
    box.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 1.0, colors.HexColor("#B91C1C")),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return box


def _start_page(
    flowables: list,
    ctx: PDFContext,
    data: ContractSignoffData,
    advisory_label: str | None,
    title: str,
) -> None:
    flowables.extend(make_banner_header(
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
        ["Dokumentierter Punkt", "Festgehaltene Ausprägung"],
        ["Risikoprofil", data.risk_profile_label or "Nicht dokumentiert"],
        ["Risikoprofil manuell überschrieben", "Ja" if data.risk_is_overridden else "Nein"],
        ["Gewählte Anlagestrategie", data.strategy_name or "Strategische Zielallokation"],
        ["Limitierender Faktor", _limiting_factor_label(data.limiting_factor)],
    ]
    # KN4-B / DEMO-B3: Methode nur als Kundentext; unbekannt -> Zeile weglassen.
    method = method_label(data.strategy_method)
    if method:
        rows.insert(5, ["Berechnungsmethode", method])
    return _table(rows, [0.38, 0.62])


def _override_panel(reason: str | None) -> Table:
    return _status_panel(
        "Manuelle Anpassung des Risikoprofils dokumentiert",
        "Begründung: " + (reason or "Keine Begründung hinterlegt."),
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
    # G7: Zielquoten apportioniert (Summe 100.0 %), wie App und Anlagestrategie-PDF.
    shown = allocation_pct_texts({b: int(v or 0) for b, v in allocation.items() if int(v or 0) > 0})
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
            shown[bucket],
            f"{format_bps_as_pct(int(band[0] or 0), decimals=1)}",
            f"{format_bps_as_pct(int(band[1] or 0), decimals=1)}",
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
        rows.append(["-", "Keine strukturierten Einträge", "Beratung verbal dokumentiert."])
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


# KN7 (H-181, CTO-Nachtrag Punkt 1): Bestaetigungstexte je Pruefgrundlage.
# Status aus derselben Funktion wie Sektion 19 des Advisory-Reports
# (customer_suitability_text). «Geeignetheit geprueft» nur bei einer
# Geeignetheitspruefung (risk_assessment, konform); Execution-only und
# institutionelle Kunden bestaetigen nie eine Pruefung, die nicht stattfand.
_ADVISOR_CONFIRM_CHECKED = {
    "risk_assessment": (
        "Der Berater bestätigt, die Geeignetheit geprüft, die Empfehlung "
        "begründet und die wesentlichen Risiken, Kosten sowie "
        "Zielkonflikte dokumentiert zu haben."
    ),
    "appropriateness": (
        "Der Berater bestätigt, die Angemessenheit geprüft, die Empfehlung "
        "begründet und die wesentlichen Risiken, Kosten sowie "
        "Zielkonflikte dokumentiert zu haben."
    ),
}
_ADVISOR_CONFIRM_WITHOUT_CHECK = (
    "Der Berater bestätigt, die Empfehlung begründet und die wesentlichen "
    "Risiken, Kosten sowie Zielkonflikte dokumentiert zu haben."
)
_ACK_CHECKED = {
    "risk_assessment": (
        "Die Geeignetheit der Empfehlung, wesentliche Risiken, Bandbreiten, "
        "Kosten und mögliche Zielkonflikte wurden erläutert."
    ),
    "appropriateness": (
        "Die Angemessenheit der Dienstleistung, wesentliche Risiken, Bandbreiten, "
        "Kosten und mögliche Zielkonflikte wurden erläutert."
    ),
}
_ACK_WITHOUT_CHECK = (
    "Wesentliche Risiken, Bandbreiten, Kosten und mögliche Zielkonflikte der "
    "Empfehlung wurden erläutert."
)


def _suitability_status(data: ContractSignoffData) -> tuple[str, str, str]:
    """(Status, Kundentext, Grundlage) -- dieselbe Regel wie Sektion 19."""
    basis = str(getattr(data, "suitability_basis", None) or "").strip()
    status, text = customer_suitability_text({
        "suitability_basis": basis,
        "is_compliant": getattr(data, "suitability_is_compliant", None),
        "audit_degraded": bool(getattr(data, "suitability_audit_degraded", False)),
    })
    return status, text, basis


def advisor_confirm_text(data: ContractSignoffData) -> str:
    status, text, basis = _suitability_status(data)
    if status == "ok" and basis in _ADVISOR_CONFIRM_CHECKED:
        return _ADVISOR_CONFIRM_CHECKED[basis]
    # Keine (gueltige) Pruefung: nichts bestaetigen, den Grund nennen.
    return f"{_ADVISOR_CONFIRM_WITHOUT_CHECK} {text}"


def suitability_acknowledgement(data: ContractSignoffData) -> str:
    status, _text, basis = _suitability_status(data)
    if status == "ok" and basis in _ACK_CHECKED:
        return _ACK_CHECKED[basis]
    return _ACK_WITHOUT_CHECK


def _default_acknowledgements(data: ContractSignoffData) -> list[str]:
    return [
        "Die Angaben zur persönlichen und finanziellen Situation sowie zum Risikoprofil sind vollständig und korrekt besprochen worden.",
        suitability_acknowledgement(data),
        "Eine allfällige manuelle Anpassung des Risikoprofils wurde mit Begründung dokumentiert und vom Kunden bewusst bestätigt.",
        "Der Kunde hat die relevanten Produkt-, Kosten- und Vertragsunterlagen erhalten oder weiss, wo diese verfügbar sind.",
        "Personendaten werden für Beratung, Dokumentation, gesetzliche Nachweise und Vertragserfüllung gemäss revDSG bearbeitet.",
        "Es bestehen keine Zusicherungen zu künftiger Rendite, Zielerreichung oder Verlustfreiheit.",
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
        "liquiditaetsreserve": "Liquiditätsreserve",
        "bandbreite": "Strategische Bandbreiten",
        "zielkonflikt": "Zielkonflikt",
        "gemeinsamer_engpass": "Gemeinsamer Engpass (ein Konflikt)",
        "solver_konvergenz": "Berechnung / Konvergenz",
    }
    return labels.get(str(value or "").lower(), str(value or "Nicht klassifiziert"))


def _format_amount(rappen: int | None, currency: str) -> str:
    return format_amount_minor(int(rappen or 0), currency or "CHF")
