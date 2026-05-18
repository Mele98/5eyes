"""Sprint 11: Anlagestrategie-PDF — Replikat der Frontend-Vorlage
buildAnlagestrategieDocHtml. A4 Landscape, 8 Sektionen, FIDLEG-Footer.

Spec: docs/planning/2026-05-17-sprint-11-pdf-replikation.md
"""
from __future__ import annotations

from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, Spacer

from services.pdf.base import AnlagestrategieData, PDFContext
from services.pdf.components.cover import make_cover_page, make_section_cover
from services.pdf.components.effektives_portfolio import make_effektives_portfolio_section
from services.pdf.components.eignungspruefung import make_eignungspruefung_section
from services.pdf.components.header import make_wealtharchitekten_header
from services.pdf.components.produkte import make_produkte_section
from services.pdf.components.risiko_metriken import make_risiko_metriken_section
from services.pdf.components.risikoprofil_box import make_risikoprofil_box
from services.pdf.components.saa_bar_table import make_saa_bar_table
from services.pdf.components.saa_donut import (
    make_saa_donut_with_legend,
    make_two_donuts_comparison,
)
from services.pdf.components.cashflows_ziele import (
    make_cashflows_section,
    make_ziele_overview_section,
)
from services.pdf.components.vermoegensuebersicht import make_vermoegensuebersicht_section
from services.pdf.components.text_sections import (
    make_anlageuniversum_section,
    make_disclaimer_section,
    make_investitionsansatz_section,
    make_kennzahlen_erlaeuterungen_section,
    make_zusammenfassung_section,
)
from services.pdf.components.unterschrift import make_unterschrift_section
from services.pdf.components.ziele_table import make_ziele_section


def build_anlagestrategie_flowables(
    ctx: PDFContext, data: AnlagestrategieData
) -> list:
    """Anlagestrategie-PDF mit logischer Beratungs-Reihenfolge.

    Sprint 14 Phase 3 Restrukturierung:
      1. Cover (Persoenliches)
      2. TEIL A — IHRE PERSOENLICHE AUSGANGSLAGE
         - Vermoegensuebersicht
         - Kapitalzufluesse + Ziele
         - Eignungspruefung
         - Risikoprofil
      3. TEIL B — IHRE PERSOENLICHE ANLAGESTRATEGIE
         - Soll-Allokation + 2-Donut-Vergleich
         - Produkte (ISIN-Tabelle gruppiert)
         - Risiko-Metriken
         - Zielerreichung
      4. TEIL C — METHODIK
         - Investitionsansatz
         - Anlageuniversum
      5. TEIL D — BESTAETIGUNG
         - Zusammenfassung + Unterschrift
      6. ANHANG
         - Erlaeuterungen zu den Kennzahlen
         - Disclaimer
    """
    flowables: list = []
    from services.pdf.styles import make_paragraph_styles
    styles = make_paragraph_styles()

    advisory_label = None
    if data.advisory_wealth_rappen:
        advisory_label = _format_amount(data.advisory_wealth_rappen, ctx.base_currency)

    # ============================================================
    # 1. COVER
    # ============================================================
    flowables.extend(make_cover_page(
        ctx,
        client_address_lines=list(getattr(data, "client_address_lines", []) or []),
        client_phone=getattr(data, "client_phone", None),
    ))
    flowables.append(PageBreak())

    # ============================================================
    # TEIL A — IHRE PERSOENLICHE AUSGANGSLAGE
    # ============================================================
    flowables.extend(make_section_cover("Ihre persönliche Ausgangslage"))
    flowables.append(PageBreak())

    # A.1 Vermoegensuebersicht
    flowables.extend(make_wealtharchitekten_header(
        ctx, mandate_number=data.mandate_number,
        advisory_wealth_label=advisory_label,
    ))
    if data.advisory_positions or data.other_wealth_positions:
        flowables.extend(make_vermoegensuebersicht_section(
            data.advisory_positions, data.other_wealth_positions,
            base_currency=ctx.base_currency,
        ))
    else:
        flowables.append(_section_title_with_fallback(
            "Vermögensübersicht",
            "Noch keine Vermögenspositionen erfasst. Bitte im Vermögens-Tab "
            "die aktuellen Bestände erfassen.",
            styles,
        ))
    flowables.append(PageBreak())

    # A.2 Kapitalzufluesse + Ziele
    flowables.extend(make_wealtharchitekten_header(
        ctx, mandate_number=data.mandate_number,
        advisory_wealth_label=advisory_label,
    ))
    if data.cashflow_events:
        flowables.extend(make_cashflows_section(
            data.cashflow_events, base_currency=ctx.base_currency,
        ))
        flowables.append(Spacer(1, 4 * mm))
    if data.goals_list:
        flowables.extend(make_ziele_overview_section(
            data.goals_list, base_currency=ctx.base_currency,
        ))
    if not (data.cashflow_events or data.goals_list):
        flowables.append(_section_title_with_fallback(
            "Kapitalzuflüsse & Ziele",
            "Noch keine Cashflow-Ereignisse oder Anlageziele erfasst.",
            styles,
        ))
    flowables.append(PageBreak())

    # A.3 Eignungspruefung
    flowables.extend(make_wealtharchitekten_header(
        ctx, mandate_number=data.mandate_number,
        advisory_wealth_label=advisory_label,
    ))
    if data.risk_answers or data.knowledge_services or data.knowledge_instruments:
        flowables.extend(make_eignungspruefung_section(
            answers=data.risk_answers,
            services_knowledge=data.knowledge_services,
            instruments_knowledge=data.knowledge_instruments,
        ))
    else:
        flowables.append(_section_title_with_fallback(
            "Eignungsprüfung",
            "Noch keine Eignungsprüfung erfasst. Bitte im Risikoprofil-Tab "
            "den Fragebogen ausfüllen.",
            styles,
        ))
    flowables.append(Spacer(1, 4 * mm))

    # A.4 Risikoprofil-Box (direkt nach Eignungspruefung, denn das ist das Resultat)
    if data.risk_score_x10 is not None or data.risk_profile_label:
        flowables.extend(make_risikoprofil_box(
            score_x10=data.risk_score_x10,
            profile_label=data.risk_profile_label,
            horizon_years=data.investment_horizon_years or data.horizon_years,
            mandate_type=data.mandate_type,
        ))
    else:
        flowables.append(_section_title_with_fallback(
            "Risikoprofil",
            "Noch kein Risikoprofil gespeichert.",
            styles,
        ))
    flowables.append(PageBreak())

    # ============================================================
    # TEIL B — IHRE PERSOENLICHE ANLAGESTRATEGIE
    # ============================================================
    flowables.extend(make_section_cover("Ihre persönliche Anlagestrategie"))
    flowables.append(PageBreak())

    # B.1 Soll-Allokation Bar-Tabelle + 2-Donut-Vergleich
    flowables.extend(make_wealtharchitekten_header(
        ctx, mandate_number=data.mandate_number,
        advisory_wealth_label=advisory_label,
    ))
    if data.target_allocation_bps and sum(data.target_allocation_bps.values()) > 0:
        flowables.extend(make_saa_bar_table(
            data.target_allocation_bps,
            bucket_bands_bps=data.bucket_bands_bps,
            bucket_amounts_rappen=data.bucket_amounts_rappen,
            base_currency=ctx.base_currency,
            advisory_wealth_rappen=data.advisory_wealth_rappen,
        ))
        flowables.append(Spacer(1, 4 * mm))
        from reportlab.platypus import KeepTogether
        title_para = Paragraph(
            f'<font color="#475569" size="9"><b>'
            f'VISUALISIERUNG NACH ANLAGE- UND SUB-ANLAGEKLASSE</b></font>',
            styles["section_title"],
        )
        has_current = (
            data.current_allocation_bps
            and sum(int(v or 0) for v in data.current_allocation_bps.values()) > 0
        )
        if has_current:
            two_donuts = make_two_donuts_comparison(
                data.current_allocation_bps,
                data.target_allocation_bps,
                current_products=data.advisory_positions,
                target_products=data.products,
                diameter_mm=42.0,
            )
            flowables.append(KeepTogether([title_para, *two_donuts]))
        else:
            donut_widget = make_saa_donut_with_legend(
                data.target_allocation_bps, products=data.products,
                diameter_mm=48.0,
            )
            flowables.append(KeepTogether([title_para, donut_widget]))
    else:
        flowables.append(_section_title_with_fallback(
            "Soll-Allokation & Toleranzbänder",
            "Noch keine Soll-Allokation berechnet.",
            styles,
        ))
    flowables.append(PageBreak())

    # B.2 Produkte (ISIN-Tabelle gruppiert mit Subtotalen)
    flowables.extend(make_wealtharchitekten_header(
        ctx, mandate_number=data.mandate_number,
        advisory_wealth_label=advisory_label,
    ))
    flowables.extend(make_produkte_section(
        data.products, base_currency=ctx.base_currency,
    ))
    flowables.append(PageBreak())

    # B.3 Risiko-Metriken + Zielerreichung
    flowables.extend(make_wealtharchitekten_header(
        ctx, mandate_number=data.mandate_number,
        advisory_wealth_label=advisory_label,
    ))
    has_metrics = (
        data.cma_expected_return_bps or data.median_cagr_bps
        or data.cma_expected_vol_bps or data.max_drawdown_bps
        or data.var_95_bps
    )
    if has_metrics:
        flowables.extend(make_risiko_metriken_section(
            expected_return_bps=data.cma_expected_return_bps,
            median_cagr_bps=data.median_cagr_bps,
            volatility_bps=data.cma_expected_vol_bps,
            max_drawdown_bps=data.max_drawdown_bps,
            var_95_bps=data.var_95_bps,
        ))
        flowables.append(Spacer(1, 4 * mm))

    if data.goal_analysis:
        flowables.extend(make_ziele_section(
            data.goal_analysis, base_currency=ctx.base_currency,
        ))
    elif not has_metrics:
        flowables.append(_section_title_with_fallback(
            "Zielerreichung & Risikoindikatoren",
            "Noch keine Monte-Carlo-Simulation. Wird mit 'Anlagestrategie "
            "berechnen' generiert.",
            styles,
        ))
    flowables.append(PageBreak())

    # ============================================================
    # TEIL C — METHODIK
    # ============================================================
    flowables.extend(make_investitionsansatz_section())
    flowables.append(PageBreak())

    flowables.extend(make_anlageuniversum_section())
    flowables.append(PageBreak())

    # ============================================================
    # TEIL D — BESTAETIGUNG
    # ============================================================
    flowables.extend(make_zusammenfassung_section())
    flowables.append(Spacer(1, 6 * mm))
    flowables.extend(make_unterschrift_section())
    flowables.append(PageBreak())

    # ============================================================
    # ANHANG
    # ============================================================
    flowables.extend(make_kennzahlen_erlaeuterungen_section())
    flowables.append(PageBreak())

    flowables.extend(make_disclaimer_section())

    return flowables


def _section_title_with_fallback(title: str, fallback_text: str, styles):
    """Helper: Section-Title + grauer Italic-Text wenn Sektion leer."""
    from services.pdf.components.header import _esc
    from services.pdf.styles import FONT_DEFAULT
    title_para = Paragraph(
        f'<font color="#475569" size="9"><b>{_esc(title).upper()}</b></font>',
        styles["section_title"],
    )
    fallback_para = Paragraph(
        f'<font name="{FONT_DEFAULT}" size="9" color="#94a3b8"><i>'
        f'{_esc(fallback_text)}</i></font>',
        styles["small_muted"],
    )
    # Beide in einer Mini-Liste zurueckgeben
    from reportlab.platypus import KeepTogether
    return KeepTogether([title_para, fallback_para])


def _format_amount(rappen: int, currency: str = "CHF") -> str:
    """Schweizer-Format mit Tausender-Trenner."""
    try:
        if currency == "CHF":
            value = rappen / 100.0
        else:
            from services.currency.converter import convert_rappen
            value = convert_rappen(rappen, "CHF", currency) / 100.0
        return f"{currency} {value:,.0f}".replace(",", "'")
    except Exception:
        return f"CHF {rappen/100.0:,.0f}".replace(",", "'")


# Backwards-Compat: Helper-Funktion fuer Sprint 5 Risikoprofil-PDF
def _fmt_amount(amount: float, currency: str = "CHF") -> str:
    """Legacy-Name fuer test_currency_integration.py."""
    return _format_amount(int(amount), currency)


def _fmt_chf(amount: float) -> str:
    """Backwards-Compat fuer Sprint 5 Tests."""
    return _format_amount(int(amount), "CHF")
