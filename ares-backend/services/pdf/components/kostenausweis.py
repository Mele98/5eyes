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
    COLOR_STATUS_ROT,
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
    # CERT-COST-PUBLICATION-001 (COST-RENDER-SEMANTICS-001, 2026-10-09): der
    # Einleitungstext behauptete bisher UNABHAENGIG von data["currency"]
    # immer "Schweizer Franken" -- fuer ein EUR-/USD-Mandat widersprach der
    # Fliesstext damit den (bereits korrekt dynamischen) Zahlen weiter unten.
    # _currency_intro_phrase() ist dieselbe Quelle wie _summary_metrics/
    # _cost_table (data["currency"]), kein zweiter Berechnungsweg.
    currency_for_intro = str((data or {}).get("currency") or "CHF").upper().strip() or "CHF"
    out: list[Any] = [
        Paragraph("FIDLEG KOSTENTRANSPARENZ", styles["kicker"]),
        Paragraph("Kostenausweis ex-ante", styles["h1"]),
        Spacer(1, 3 * mm),
        _rule(),
        Spacer(1, 5 * mm),
        Paragraph(
            "Voraussichtliche Kosten der empfohlenen Finanzdienstleistung "
            "und des Zielportfolios. Einmalige und laufende Kosten werden "
            f"getrennt sowie {_currency_intro_phrase(currency_for_intro)} und "
            "als Quote der Berechnungsbasis ausgewiesen.",
            _style(styles["body"], color=COLOR_INK_MUTED),
        ),
        Spacer(1, (2 if compact else 4) * mm),
    ]

    if data and data.get("evidence_status") == "blocked":
        # COST-SNAPSHOT-BINDING-001: ungueltiger Kostennachweis ist ein
        # ausgewiesener Fehler (rot), nicht "Daten ausstehend" und nie Zahlen.
        out.extend([
            _status_panel(
                "Kostennachweis ungültig",
                _first_warning(data),
                styles,
                color=COLOR_STATUS_ROT,
            ),
            Spacer(1, 5 * mm),
            _legal_note(styles),
        ])
        return out

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

    # Bugfix 2026-08-07 (CEO/CFO/CIO-Audit): data["currency"] wird bereits von
    # services.cost_disclosure aus mandate.base_currency berechnet -- vorher
    # ignoriert, format_chf_rappen() zeigte fuer EUR-/USD-Mandate faelschlich
    # immer "CHF" im FIDLEG-Pflichtdokument.
    currency = str(data.get("currency") or "CHF").upper().strip() or "CHF"
    totals = data.get("totals") or {}
    out.append(_summary_metrics(data, totals, styles, currency=currency, compact=compact))
    out.append(Spacer(1, (3 if compact else 5) * mm))
    out.append(_cost_table(
        list(data.get("cost_items") or []),
        totals,
        styles,
        currency=currency,
        compact=compact,
    ))

    # AUDIT-2026-11 P1 (L1): Retrozession je Produkt -- eigener Baustein
    # (Abschnitt am Dateiende), rendert nichts ohne
    # payload["product_retrocessions"].
    out.extend(build_retrocession_flowables(data, styles, compact=compact))

    warnings = [str(item) for item in data.get("warnings") or [] if str(item).strip()]
    if warnings:
        out.append(Spacer(1, (2 if compact else 4) * mm))
        out.append(_assumptions_panel(warnings, styles, compact=compact))

    out.append(Spacer(1, (3 if compact else 5) * mm))
    out.append(_legal_note(styles, compact=compact))
    return out


def _summary_metrics(data: dict, totals: dict, styles, *, currency: str = "CHF", compact: bool) -> Table:
    metrics = [
        ("ANLAGEBASIS", format_chf_rappen(data.get("advisory_wealth_rappen"), currency=currency)),
        ("EINMALIG", format_chf_rappen(totals.get("one_time_rappen"), currency=currency)),
        ("LAUFEND P.A.", format_chf_rappen(totals.get("annual_rappen"), currency=currency)),
        ("ERSTES JAHR", format_chf_rappen(totals.get("first_year_rappen"), currency=currency)),
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
    currency: str = "CHF",
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
            Paragraph(_escape(format_chf_rappen(item.get("amount_rappen"), currency=currency)), _style(
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
            currency=currency,
            strong=False,
        ),
        _total_row(
            "Total laufende Kosten p.a.",
            totals.get("annual_bps"),
            totals.get("annual_rappen"),
            styles,
            currency=currency,
            strong=False,
        ),
        _total_row(
            "Gesamtkosten im ersten Jahr",
            totals.get("first_year_bps"),
            totals.get("first_year_rappen"),
            styles,
            currency=currency,
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


def _total_row(label: str, bps: Any, amount: Any, styles, *, currency: str = "CHF", strong: bool) -> list[Any]:
    font = FONT_SANS_BOLD if strong else FONT_SANS
    return [
        Paragraph(_escape(label), _style(styles["caption"], font=font, color=COLOR_INK)),
        "",
        Paragraph(_escape(format_bps_as_pct(bps, decimals=2)), _style(
            styles["caption_mono"], font=font, color=COLOR_INK,
        )),
        Paragraph(_escape(format_chf_rappen(amount, currency=currency)), _style(
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


# CERT-COST-PUBLICATION-001 (COST-RENDER-SEMANTICS-001): ISO-4217-Code ->
# deutsche Waehrungsbezeichnung fuer den Fliesstext. Nur Formatierung, keine
# neue Kostenberechnung -- unbekannte Codes fallen ehrlich auf den Code
# selbst zurueck statt eine falsche Waehrung zu behaupten.
_CURRENCY_NAMES_DE: dict[str, str] = {
    "CHF": "Schweizer Franken",
    "EUR": "Euro",
    "USD": "US-Dollar",
    "GBP": "britischen Pfund",
    "JPY": "japanischen Yen",
}


def _currency_intro_phrase(currency: str) -> str:
    name = _CURRENCY_NAMES_DE.get(currency)
    if name:
        return f"in {name}"
    return f"in {currency}"


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


# ===========================================================================
# AUDIT-2026-11 P1 (L1): Retrozessionen je empfohlenem Produkt (Art. 26 FIDLEG).
# Abgegrenzter Baustein; Daten nur aus payload["product_retrocessions"]
# (services/cost_disclosure.py, Abschnitt P1). Fehlt der Schluessel (Nachweis
# vor P1 eingefroren oder Ausweis ohne Produktbezug), rendert er nichts.
# ===========================================================================

RETROCESSION_TITLE = "Vergütungen von Dritten (Retrozessionen) je Produkt"


def build_retrocession_flowables(
    data: dict[str, Any] | None,
    styles,
    *,
    compact: bool = False,
) -> list[Any]:
    disclosure = (data or {}).get("product_retrocessions")
    if not isinstance(disclosure, dict):
        return []
    lines = [line for line in disclosure.get("lines") or [] if isinstance(line, dict)]
    if not lines:
        return []
    currency = str((data or {}).get("currency") or "CHF").upper().strip() or "CHF"

    rows: list[list[Any]] = [[
        _th("Produkt", styles),
        _th("ISIN", styles),
        _th("Satz p.a.", styles),
        _th("Betrag p.a.", styles),
        _th("Behandlung", styles),
    ]]
    flagged_rows: list[int] = []
    for index, line in enumerate(lines, start=1):
        status = str(line.get("status") or "unknown")
        if status == "unknown":
            rate_text, amount_text = "unbekannt", "unbekannt"
        elif status == "none":
            rate_text, amount_text = "keine", "—"
        else:
            rate_text = format_bps_as_pct(line.get("rate_bps"), decimals=2)
            amount_text = "geschätzt " + _retro_amount(line.get("estimated_annual_rappen"), currency=currency)
            # N-861-3: bei einer Mandatszeile beide Betraege klar beschriften
            # (Schaetzung aus dem Produktsatz vs. im Mandat aufgeklaert).
            if line.get("covered_by_mandate_entry") and line.get("mandate_disclosed_rappen"):
                amount_text += " / aufgeklärt " + _retro_amount(
                    line.get("mandate_disclosed_rappen"), currency=currency,
                )
            # N-861-8: einmalig/ohne Frequenz offengelegt ist keine Aufklaerung
            # einer laufenden Retrozession.
            if line.get("mandate_disclosed_other_rappen"):
                amount_text += (
                    " / offengelegt (einmalig bzw. ohne Frequenz) "
                    + _retro_amount(line.get("mandate_disclosed_other_rappen"), currency=currency)
                    + ", deckt die jährliche Retrozession nicht"
                )
        if status == "unknown" or line.get("requires_resolution"):
            flagged_rows.append(index)
        rows.append([
            Paragraph(_escape(line.get("product_name") or "Produkt"), _retro_style(styles["caption"], color=COLOR_INK)),
            Paragraph(_escape(line.get("isin") or "fehlt"), _retro_style(styles["micro"], color=COLOR_INK_SUBTLE)),
            Paragraph(_escape(rate_text), _retro_style(styles["caption_mono"], color=COLOR_INK)),
            Paragraph(_escape(amount_text), _retro_style(styles["caption_mono"], color=COLOR_INK)),
            Paragraph(_escape(line.get("treatment_label") or "—"), _retro_style(styles["micro"], color=COLOR_INK_MUTED)),
        ])
    width = _inner_width()
    table = Table(
        rows,
        colWidths=[width * 0.30, width * 0.15, width * 0.11, width * 0.16, width * 0.28],
        repeatRows=1,
    )
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_INK),
        ("LINEBELOW", (0, 1), (-1, -1), 0.3, COLOR_RULE),
        ("ALIGN", (2, 1), (3, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 3 if compact else 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3 if compact else 5),
    ]
    for row_index in flagged_rows:
        line = lines[row_index - 1]
        color = COLOR_STATUS_ROT if line.get("requires_resolution") else COLOR_STATUS_GELB
        style_cmds.append(("LINEBEFORE", (0, row_index), (0, row_index), 2.5, color))
    table.setStyle(TableStyle(style_cmds))

    note = (
        "Vergütungen, die Ihr Finanzdienstleister von Dritten im Zusammenhang mit den "
        "empfohlenen Produkten erhält, stehen grundsätzlich Ihnen zu. Sie dürfen nur behalten "
        "werden, wenn Sie nach Aufklärung über Art und Umfang ausdrücklich verzichtet "
        "haben (Art. 26 FIDLEG; Art. 400 OR; BGE 132 III 460 und 137 III 393). Die Beträge "
        "sind Teil der Produktkosten (TER) und nicht zusätzlich im Total enthalten. "
        "Betrag p.a.: «geschätzt» = Satz × investiertes Volumen; «aufgeklärt» = der Ihnen "
        "im Mandat jährlich offengelegte Betrag; beide auf Rappen genau. «unbekannt» heisst: "
        "der Satz ist nicht erfasst; das Produkt gilt nicht als retrozessionsfrei."
    )
    return [
        Spacer(1, (2 if compact else 4) * mm),
        Paragraph(
            _escape(RETROCESSION_TITLE.upper()),
            _retro_style(styles["micro"], font=FONT_SANS_BOLD, color=COLOR_INK_SUBTLE),
        ),
        Spacer(1, 1.5 * mm),
        table,
        Spacer(1, 1.5 * mm),
        Paragraph(_escape(note), _retro_style(styles["micro"], color=COLOR_INK_MUTED)),
    ]


def _retro_amount(rappen: Any, *, currency: str = "CHF") -> str:
    """N-861-12: Retro-Betraege immer mit zwei Nachkommastellen. Sonst
    stuenden bei Teil-Deckung zwei gleich gerundete Betraege (z.B. CHF 500
    "geschaetzt" und CHF 500 "aufgeklaert" bei 499.99) neben "deckt nur einen
    Teil" -- ein Widerspruch im Kundendokument."""
    if rappen is None:
        return "—"
    try:
        value = int(rappen)
    except (TypeError, ValueError):
        return "—"
    whole, cents = divmod(abs(value), 100)
    unit = str(currency or "CHF").upper().strip() or "CHF"
    sign = "-" if value < 0 else ""
    return f"{unit} {sign}{whole:,}.{cents:02d}".replace(",", "'")


def _retro_style(base: ParagraphStyle, *, font: str | None = None, color=None) -> ParagraphStyle:
    return ParagraphStyle(
        f"{base.name}Retrocession{font or ''}",
        parent=base,
        fontName=font or base.fontName or FONT_SANS,
        textColor=color or base.textColor,
        spaceBefore=0,
        spaceAfter=0,
    )
