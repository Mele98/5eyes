"""Anlagestrategie-PDF — vollstaendiges Dokument."""
from __future__ import annotations

from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from services.pdf.base import AnlagestrategieData, PDFContext
from services.pdf.components.header import make_document_header, _esc
from services.pdf.components.pie_chart import make_saa_pie_chart
from services.pdf.components.table import make_saa_table
from services.pdf.styles import (
    COLOR_BORDER,
    FONT_BOLD,
    FONT_DEFAULT,
    FONT_SIZE_BODY,
    FONT_SIZE_SMALL,
    make_paragraph_styles,
)


def build_anlagestrategie_flowables(
    ctx: PDFContext, data: AnlagestrategieData
) -> list:
    """Returns Flowable-Liste fuer das Anlagestrategie-PDF."""
    styles = make_paragraph_styles()
    flowables: list = []

    # ---- Header ----
    flowables.extend(make_document_header("Anlagestrategie", ctx))

    # ---- Sektion 1: Strategie-Uebersicht ----
    flowables.append(Paragraph("Strategie-Uebersicht", styles["heading"]))

    if data.risk_profile_label:
        flowables.append(Paragraph(
            f"<b>Risikoprofil:</b> {_esc(data.risk_profile_label)}",
            styles["body"],
        ))
    flowables.append(Paragraph(
        f"<b>Anlagehorizont:</b> {data.horizon_years} Jahre",
        styles["body"],
    ))
    flowables.append(Paragraph(
        f"<b>Erwartete Rendite p.a.:</b> {data.cma_expected_return_bps / 100.0:.2f} %",
        styles["body"],
    ))
    flowables.append(Paragraph(
        f"<b>Erwartete Volatilitaet p.a.:</b> {data.cma_expected_vol_bps / 100.0:.2f} %",
        styles["body"],
    ))

    flowables.append(Spacer(1, 5 * mm))

    # ---- Sektion 2: Asset-Allokation (Tabelle + Torte side-by-side) ----
    flowables.append(Paragraph("Strategische Asset-Allokation (SAA)", styles["heading"]))

    saa_table = make_saa_table(dict(data.target_allocation_bps))
    saa_pie = make_saa_pie_chart(dict(data.target_allocation_bps))

    composite = Table(
        [[saa_table, saa_pie]],
        colWidths=[110 * mm, 60 * mm],
    )
    composite.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    flowables.append(KeepTogether([composite]))

    flowables.append(Spacer(1, 5 * mm))

    # ---- Sektion 3: Monte Carlo Erwartungen ----
    if data.monte_carlo_stats:
        flowables.append(Paragraph("Monte-Carlo-Projektion", styles["heading"]))
        stats = data.monte_carlo_stats
        ccy = ctx.base_currency
        mc_rows = [
            ["Szenario", f"End-Vermoegen ({ccy})"],
            ["P10 (pessimistisch)", _fmt_amount(stats.get("p10", 0), ccy)],
            ["P50 (Median)", _fmt_amount(stats.get("p50", 0), ccy)],
            ["P90 (optimistisch)", _fmt_amount(stats.get("p90", 0), ccy)],
        ]
        mc_table = Table(mc_rows, colWidths=[80 * mm, 50 * mm])
        mc_table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
            ("FONTSIZE", (0, 0), (-1, -1), FONT_SIZE_BODY),
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ("LINEBELOW", (0, 0), (-1, 0), 1.0, COLOR_BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        flowables.append(mc_table)
        flowables.append(Spacer(1, 3 * mm))

    # ---- Sektion 4: Optimizer-Begruendung (falls vorhanden) ----
    if data.optimizer_reasoning:
        flowables.append(Paragraph("Begruendung", styles["heading"]))
        flowables.append(Paragraph(_esc(data.optimizer_reasoning), styles["body"]))

    flowables.append(Spacer(1, 8 * mm))

    # ---- Disclaimer ----
    flowables.append(Paragraph(
        "Dieser Bericht enthaelt Schaetzwerte basierend auf Modell-Annahmen "
        "und vergangenen Marktdaten. Tatsaechliche Renditen koennen erheblich "
        "abweichen. Dieser Bericht ersetzt keine persoenliche Anlageberatung. "
        "Steuerliche Effekte sind vereinfacht modelliert und ersetzen keine "
        "Steuerberatung.",
        styles["disclaimer"],
    ))

    return flowables


def _fmt_amount(amount: float, currency: str = "CHF") -> str:
    """Formatiert Rappen-Betrag in der gewuenschten Mandate-Currency.

    5eyes-intern alles in CHF/Rappen. Bei non-CHF wird via services.currency
    konvertiert (DEFAULT_FX_RATES wenn keine DB-Source). Fallback bei
    Konvertierungs-Fehler: zeige CHF-Wert mit Hinweis.
    """
    ccy = (currency or "CHF").upper().strip()
    try:
        if ccy == "CHF":
            value = amount / 100.0
        else:
            from services.currency.converter import convert_rappen
            value = convert_rappen(amount, "CHF", ccy) / 100.0
        return f"{ccy} {value:,.0f}".replace(",", "'")
    except Exception:
        chf = amount / 100.0
        return f"CHF {chf:,.0f}".replace(",", "'")
