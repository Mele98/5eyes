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
from services.pdf.components.saa_donut import make_saa_donut_with_legend
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
    """8 Sektionen wie Frontend-Vorlage, A4 Landscape.

    Sprint 11 Phase 5: forcierte PageBreaks + Fallback-Texte fuer leere
    Sektionen. Garantiert mindestens 2 Seiten (Seite 1 = Profil/SAA,
    Seite 2 = Portfolio/Risk/Ziele/Unterschrift).
    """
    flowables: list = []
    from services.pdf.styles import make_paragraph_styles
    styles = make_paragraph_styles()

    # ---- COVER (Seite 1, Swiss-Life-Wealth-Vorlage) ----
    flowables.extend(make_cover_page(
        ctx,
        client_address_lines=list(getattr(data, "client_address_lines", []) or []),
        client_phone=getattr(data, "client_phone", None),
    ))
    flowables.append(PageBreak())

    # ---- 1. Header (Seite 2) ----
    advisory_label = None
    if data.advisory_wealth_rappen:
        advisory_label = _format_amount(data.advisory_wealth_rappen, ctx.base_currency)
    flowables.extend(make_wealtharchitekten_header(
        ctx,
        mandate_number=data.mandate_number,
        advisory_wealth_label=advisory_label,
    ))

    # ---- 2. Eignungspruefung (mit Fallback) ----
    if data.knowledge_services or data.knowledge_instruments:
        flowables.extend(make_eignungspruefung_section(
            services_knowledge=data.knowledge_services,
            instruments_knowledge=data.knowledge_instruments,
        ))
    else:
        flowables.append(_section_title_with_fallback(
            "Kenntnisse & Erfahrungen (Eignungspruefung)",
            "Noch keine Kenntnisse erfasst. Bitte im Risikoprofil-Tab "
            "Finanzdienstleistungen und -instrumente angeben.",
            styles,
        ))
    flowables.append(Spacer(1, 3 * mm))

    # ---- 3. Risikoprofil-Box (mit Fallback) ----
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
            "Noch kein Risikoprofil gespeichert. Bitte im Risikoprofil-Tab "
            "den Fragebogen ausfuellen und speichern.",
            styles,
        ))
    flowables.append(Spacer(1, 3 * mm))

    # ---- 4. Soll-Allokation: Bar-Tabelle + Donut+Legende side-by-side ----
    if data.target_allocation_bps and sum(data.target_allocation_bps.values()) > 0:
        # Bar-Tabelle (volle Breite)
        flowables.extend(make_saa_bar_table(
            data.target_allocation_bps,
            bucket_bands_bps=data.bucket_bands_bps,
            bucket_amounts_rappen=data.bucket_amounts_rappen,
            base_currency=ctx.base_currency,
            advisory_wealth_rappen=data.advisory_wealth_rappen,
        ))
        flowables.append(Spacer(1, 3 * mm))
        # Donut + Sub-Klassen-Legende
        from reportlab.platypus import Table as _DonutTable, TableStyle as _DonutStyle
        donut_widget = make_saa_donut_with_legend(
            data.target_allocation_bps,
            products=data.products,
            diameter_mm=48.0,
        )
        from reportlab.platypus import KeepTogether
        donut_wrap = KeepTogether([
            Paragraph(
                f'<font color="#475569" size="9"><b>'
                f'VISUALISIERUNG NACH ANLAGE- UND SUB-ANLAGEKLASSE</b></font>',
                styles["section_title"],
            ),
            donut_widget,
        ])
        flowables.append(donut_wrap)
    else:
        flowables.append(_section_title_with_fallback(
            "Soll-Allokation & Toleranzbaender",
            "Noch keine Soll-Allokation berechnet. Bitte im Asset-"
            "Allokation-Tab 'Anlagestrategie berechnen' klicken.",
            styles,
        ))

    # ---- PAGE BREAK — Seite 2 startet hier ----
    flowables.append(PageBreak())

    # ---- 5. Produkte (Soll-Vorschlag) ----
    flowables.extend(make_produkte_section(
        data.products,
        base_currency=ctx.base_currency,
    ))
    flowables.append(Spacer(1, 3 * mm))

    # ---- 5b. Effektives Portfolio (IST-Bestand) ----
    flowables.extend(make_effektives_portfolio_section(
        data.products,
        base_currency=ctx.base_currency,
    ))
    flowables.append(Spacer(1, 3 * mm))

    # ---- 6. Risiko-Metriken (mit Fallback) ----
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
    else:
        flowables.append(_section_title_with_fallback(
            "Risikoindiktatoren & Prognose (Monte Carlo)",
            "Noch keine Monte-Carlo-Simulation. Wird zusammen mit "
            "'Anlagestrategie berechnen' generiert.",
            styles,
        ))
    flowables.append(Spacer(1, 3 * mm))

    # ---- 7. Ziele (mit Fallback) ----
    if data.goal_analysis:
        flowables.extend(make_ziele_section(data.goal_analysis))
    else:
        flowables.append(_section_title_with_fallback(
            "Anlageziele & Zielerreichung",
            "Noch keine Ziele erfasst oder Zielerreichung noch nicht "
            "berechnet. Bitte im Cashflow-Tab Ziele anlegen.",
            styles,
        ))
    flowables.append(Spacer(1, 3 * mm))

    # ---- PageBreak vor Erklaerungs-Sektionen ----
    flowables.append(PageBreak())

    # ---- Investitionsansatz (statisch) ----
    flowables.extend(make_investitionsansatz_section())
    flowables.append(PageBreak())

    # ---- Anlageuniversum (statisch) ----
    flowables.extend(make_anlageuniversum_section())
    flowables.append(PageBreak())

    # ---- Zusammenfassung + Unterschrift ----
    flowables.extend(make_zusammenfassung_section())
    flowables.append(Spacer(1, 6 * mm))
    flowables.extend(make_unterschrift_section())
    flowables.append(PageBreak())

    # ---- Trenn-Cover "Ihre persoenliche Ausgangslage" ----
    flowables.extend(make_section_cover("Ihre persönliche Ausgangslage"))
    flowables.append(PageBreak())

    # ---- Kennzahlen-Erlaeuterungen (statisch) ----
    flowables.extend(make_kennzahlen_erlaeuterungen_section())
    flowables.append(PageBreak())

    # ---- Disclaimer (statisch, letzte Seite) ----
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
