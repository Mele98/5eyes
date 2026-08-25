"""FIDLEG Art. 8/9 Ex-ante Kostenausweis — Standalone-PDF.

Eigenstaendiges Kundendokument (anders als der Ausweis im DepotCheck-PDF,
der dort als Subsection erscheint). Wird vor Auftragsausfuehrung dem
Kunden ausgehaendigt; ein cost_disclosure_given-Flag im AdvisoryLog
kann beim Druck automatisch gesetzt werden (Audit-Trail, PR 3).

Aufbau:
1. Cover (single-report Stil) mit Fokuspunkten
2. Editorial-Kostenausweis-Block (services.pdf.components.kostenausweis)
3. Optionaler 'pending'-Hinweis wenn noch keine Empfehlung
"""
from __future__ import annotations

from typing import Any, Mapping

from reportlab.lib.units import mm
from reportlab.platypus import PageBreak

from services.pdf.base import CostDisclosurePDFData, PDFContext
from services.pdf.components.kostenausweis import build_kostenausweis_flowables
from services.pdf.components.single_report_disclaimer import make_single_report_cover
from services.pdf.components.advisory_palette import make_advisory_styles
from services.pdf.provisional_notice import make_provisional_notice_flowables
from services.pdf.styles import PAGE_SIZE


def build_cost_disclosure_flowables(
    ctx: PDFContext,
    data: CostDisclosurePDFData,
) -> list[Any]:
    """Vollstaendige Flowable-Liste fuer das standalone Kostenausweis-PDF."""
    flowables: list[Any] = []
    advisory_label = (
        _format_amount(data.advisory_wealth_rappen, ctx.base_currency)
        if data.advisory_wealth_rappen
        else None
    )

    flowables.extend(make_single_report_cover(
        ctx,
        title="Ex-ante Kostenausweis",
        subtitle="Voraussichtliche Kosten der empfohlenen Finanzdienstleistung",
        mandate_number=data.mandate_number,
        advisory_wealth_label=advisory_label,
        focus_points=[
            "Einmalige Kosten (Einrichtung, Transaktionen Erstumsetzung)",
            "Laufende Kosten p.a. (Produktkosten, Dienstleistungs- und Depotgebuehren)",
            "Gesamtkosten im ersten Jahr inkl. Berechnungsbasis",
            "FIDLEG Art. 8/9 und FIDLEV Art. 8/14 — Annahmen und Datenquellen",
        ],
    ))
    # WP-B (2026-08-01): Provisorik-Banner direkt unter dem Cover-Block,
    # noch vor dem PageBreak. Fuer CH ist ctx.provisional_notice IMMER
    # None -> No-Op (Constraint 1).
    page_width, _ = PAGE_SIZE
    flowables.extend(make_provisional_notice_flowables(
        ctx.provisional_notice, table_width=page_width - 24 * mm,
    ))
    flowables.append(PageBreak())

    styles = make_advisory_styles()
    flowables.extend(build_kostenausweis_flowables(
        data.payload,
        styles,
        compact=True,
    ))

    return flowables


def _format_amount(rappen: int, currency: str) -> str:
    # Bugfix 2026-08-07 (CEO/CFO/CIO-Audit): rappen (advisory_wealth_rappen)
    # ist bereits in mandate.base_currency. Kein zweites
    # convert_rappen("CHF"->currency) -- sonst doppelte FX-Konvertierung.
    if not rappen:
        return ""
    value = rappen / 100.0
    return f"{currency} {value:,.0f}".replace(",", "'")
