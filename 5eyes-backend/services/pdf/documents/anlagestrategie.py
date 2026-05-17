"""Sprint 11: Anlagestrategie-PDF — Replikat der Frontend-Vorlage
buildAnlagestrategieDocHtml. A4 Landscape, 8 Sektionen, FIDLEG-Footer.

Spec: docs/planning/2026-05-17-sprint-11-pdf-replikation.md
"""
from __future__ import annotations

from reportlab.lib.units import mm
from reportlab.platypus import Spacer

from services.pdf.base import AnlagestrategieData, PDFContext
from services.pdf.components.eignungspruefung import make_eignungspruefung_section
from services.pdf.components.header import make_wealtharchitekten_header
from services.pdf.components.produkte import make_produkte_section
from services.pdf.components.risiko_metriken import make_risiko_metriken_section
from services.pdf.components.risikoprofil_box import make_risikoprofil_box
from services.pdf.components.saa_bar_table import make_saa_bar_table
from services.pdf.components.unterschrift import make_unterschrift_section
from services.pdf.components.ziele_table import make_ziele_section


def build_anlagestrategie_flowables(
    ctx: PDFContext, data: AnlagestrategieData
) -> list:
    """8 Sektionen wie Frontend-Vorlage, A4 Landscape.

    1. Header (dark, WealthArchitekten-Banner)
    2. Kenntnisse & Erfahrungen (Eignungspruefung)
    3. Risikoprofil-Box
    4. Soll-Allokation & Toleranzbaender
    5. Umsetzung in Produkte (ISIN)
    6. Risikoindikatoren & Prognose (Monte Carlo)
    7. Anlageziele & Zielerreichung
    8. Bestaetigung & Unterschrift
    """
    flowables: list = []

    # ---- 1. Header ----
    advisory_label = None
    if data.advisory_wealth_rappen:
        advisory_label = _format_amount(data.advisory_wealth_rappen, ctx.base_currency)
    flowables.extend(make_wealtharchitekten_header(
        ctx,
        mandate_number=data.mandate_number,
        advisory_wealth_label=advisory_label,
    ))

    # ---- 2. Eignungspruefung ----
    eignung = make_eignungspruefung_section(
        services_knowledge=data.knowledge_services,
        instruments_knowledge=data.knowledge_instruments,
    )
    if eignung:
        flowables.extend(eignung)
        flowables.append(Spacer(1, 3 * mm))

    # ---- 3. Risikoprofil-Box ----
    risk_box = make_risikoprofil_box(
        score_x10=data.risk_score_x10,
        profile_label=data.risk_profile_label,
        horizon_years=data.investment_horizon_years or data.horizon_years,
        mandate_type=data.mandate_type,
    )
    if risk_box:
        flowables.extend(risk_box)
        flowables.append(Spacer(1, 3 * mm))

    # ---- 4. Soll-Allokation ----
    flowables.extend(make_saa_bar_table(
        data.target_allocation_bps,
        bucket_bands_bps=data.bucket_bands_bps,
        bucket_amounts_rappen=data.bucket_amounts_rappen,
        base_currency=ctx.base_currency,
        advisory_wealth_rappen=data.advisory_wealth_rappen,
    ))
    flowables.append(Spacer(1, 3 * mm))

    # ---- 5. Produkte ----
    flowables.extend(make_produkte_section(
        data.products,
        base_currency=ctx.base_currency,
    ))
    flowables.append(Spacer(1, 3 * mm))

    # ---- 6. Risiko-Metriken ----
    risk_metrics = make_risiko_metriken_section(
        expected_return_bps=data.cma_expected_return_bps,
        median_cagr_bps=data.median_cagr_bps,
        volatility_bps=data.cma_expected_vol_bps,
        max_drawdown_bps=data.max_drawdown_bps,
        var_95_bps=data.var_95_bps,
    )
    if risk_metrics:
        flowables.extend(risk_metrics)
        flowables.append(Spacer(1, 3 * mm))

    # ---- 7. Ziele ----
    ziele = make_ziele_section(data.goal_analysis)
    if ziele:
        flowables.extend(ziele)
        flowables.append(Spacer(1, 3 * mm))

    # ---- 8. Unterschrift ----
    flowables.extend(make_unterschrift_section())

    return flowables


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
