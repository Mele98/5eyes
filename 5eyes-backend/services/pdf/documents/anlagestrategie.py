"""Sprint 11: Anlagestrategie-PDF — Replikat der Frontend-Vorlage
buildAnlagestrategieDocHtml. A4 Landscape, 8 Sektionen, FIDLEG-Footer.

Spec: docs/planning/2026-05-17-sprint-11-pdf-replikation.md
"""
from __future__ import annotations

from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, Spacer, Table, TableStyle

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

    return _build_anlagestrategie_flowables_template_order(
        ctx, data, styles, advisory_label
    )

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
    flowables.append(PageBreak())

    # A.4 Risikoprofil-Box (eigene Seite wie Referenzvorlage)
    flowables.extend(make_wealtharchitekten_header(
        ctx, mandate_number=data.mandate_number,
        advisory_wealth_label=advisory_label,
    ))
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

    # A.5 Anlagepraeferenzen
    flowables.extend(make_wealtharchitekten_header(
        ctx, mandate_number=data.mandate_number,
        advisory_wealth_label=advisory_label,
    ))
    flowables.extend(_make_preferences_section(data.allocation_preferences, styles))
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
        flowables.append(PageBreak())
        flowables.extend(make_wealtharchitekten_header(
            ctx, mandate_number=data.mandate_number,
            advisory_wealth_label=advisory_label,
        ))
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
    else:
        flowables.append(_section_title_with_fallback(
            "Risikoindikatoren",
            "Noch keine Monte-Carlo-Simulation. Wird mit 'Anlagestrategie "
            "berechnen' generiert.",
            styles,
        ))
    flowables.append(PageBreak())

    flowables.extend(make_wealtharchitekten_header(
        ctx, mandate_number=data.mandate_number,
        advisory_wealth_label=advisory_label,
    ))
    if data.goal_analysis:
        flowables.extend(make_ziele_section(
            data.goal_analysis, base_currency=ctx.base_currency,
        ))
    else:
        flowables.append(_section_title_with_fallback(
            "Zielerreichung",
            "Noch keine Zielerreichungsanalyse gespeichert. Wird mit "
            "'Anlagestrategie berechnen' generiert.",
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
    flowables.append(PageBreak())
    flowables.extend(make_unterschrift_section())
    flowables.append(PageBreak())

    # ============================================================
    # ANHANG
    # ============================================================
    flowables.extend(make_kennzahlen_erlaeuterungen_section())
    flowables.append(PageBreak())

    flowables.extend(make_disclaimer_section())

    return flowables


def _build_anlagestrategie_flowables_template_order(
    ctx: PDFContext,
    data: AnlagestrategieData,
    styles,
    advisory_label: str | None,
) -> list:
    """Builds the 19-page order of the provided reference scan."""
    flowables: list = []

    def header():
        flowables.extend(make_wealtharchitekten_header(
            ctx,
            mandate_number=data.mandate_number,
            advisory_wealth_label=advisory_label,
        ))

    def empty_section(title: str, text: str):
        flowables.append(_section_title_with_fallback(title, text, styles))

    # 1 Cover
    flowables.extend(make_cover_page(
        ctx,
        client_address_lines=list(getattr(data, "client_address_lines", []) or []),
        client_phone=getattr(data, "client_phone", None),
    ))
    flowables.append(PageBreak())

    # 2 Eignungspruefung
    header()
    if data.risk_answers or data.knowledge_services or data.knowledge_instruments:
        flowables.extend(make_eignungspruefung_section(
            answers=data.risk_answers,
            services_knowledge=data.knowledge_services,
            instruments_knowledge=data.knowledge_instruments,
        ))
    else:
        empty_section(
            "Eignungspruefung",
            "Noch keine Eignungspruefung erfasst. Bitte im Risikoprofil-Tab den Fragebogen ausfuellen.",
        )
    flowables.append(PageBreak())

    # 3 Risikoprofil
    header()
    if data.risk_score_x10 is not None or data.risk_profile_label:
        flowables.extend(make_risikoprofil_box(
            score_x10=data.risk_score_x10,
            profile_label=data.risk_profile_label,
            horizon_years=data.investment_horizon_years or data.horizon_years,
            mandate_type=data.mandate_type,
        ))
    else:
        empty_section("Risikoprofil", "Noch kein Risikoprofil gespeichert.")
    flowables.append(PageBreak())

    # 4 Anlagepraeferenzen
    header()
    flowables.extend(_make_preferences_section(data.allocation_preferences, styles))
    flowables.append(PageBreak())

    # 5 Vermoegensstruktur: Donuts
    header()
    if data.target_allocation_bps and sum(data.target_allocation_bps.values()) > 0:
        from reportlab.platypus import KeepTogether
        title_para = Paragraph(
            '<font color="#475569" size="9"><b>VERMOEGENSSTRUKTUR - AUSGANGSLAGE UND EMPFEHLUNG</b></font>',
            styles["section_title"],
        )
        has_current = (
            data.current_allocation_bps
            and sum(int(v or 0) for v in data.current_allocation_bps.values()) > 0
        )
        if has_current:
            donuts = make_two_donuts_comparison(
                data.current_allocation_bps,
                data.target_allocation_bps,
                current_products=data.advisory_positions,
                target_products=data.products,
                diameter_mm=42.0,
            )
            flowables.append(KeepTogether([title_para, *donuts]))
        else:
            flowables.append(KeepTogether([
                title_para,
                make_saa_donut_with_legend(
                    data.target_allocation_bps,
                    products=data.products,
                    diameter_mm=48.0,
                ),
            ]))
    else:
        empty_section("Vermoegensstruktur", "Noch keine Soll-Allokation berechnet.")
    flowables.append(PageBreak())

    # 6 Vermoegensstruktur: Tabellenwerte
    header()
    if data.target_allocation_bps and sum(data.target_allocation_bps.values()) > 0:
        flowables.extend(make_saa_bar_table(
            data.target_allocation_bps,
            bucket_bands_bps=data.bucket_bands_bps,
            bucket_amounts_rappen=data.bucket_amounts_rappen,
            base_currency=ctx.base_currency,
            advisory_wealth_rappen=data.advisory_wealth_rappen,
        ))
    else:
        empty_section("Vermoegensstruktur", "Noch keine Soll-Allokation berechnet.")
    flowables.append(PageBreak())

    # 7 Investitionsansatz
    flowables.extend(make_investitionsansatz_section())
    flowables.append(PageBreak())

    # 8 Anlageuniversum
    flowables.extend(make_anlageuniversum_section())
    flowables.append(PageBreak())

    # 9 Zusammenfassung + Unterschrift
    flowables.extend(make_zusammenfassung_section())
    flowables.append(Spacer(1, 6 * mm))
    flowables.extend(make_unterschrift_section())
    flowables.append(PageBreak())

    # 10 Ausgangslage-Cover
    flowables.extend(make_section_cover("Ihre persoenliche Ausgangslage"))
    flowables.append(PageBreak())

    # 11 Vermoegensuebersicht
    header()
    if data.advisory_positions or data.other_wealth_positions:
        flowables.extend(make_vermoegensuebersicht_section(
            data.advisory_positions,
            data.other_wealth_positions,
            base_currency=ctx.base_currency,
        ))
    else:
        empty_section(
            "Vermoegensuebersicht",
            "Noch keine Vermoegenspositionen erfasst. Bitte im Vermoegens-Tab die aktuellen Bestaende erfassen.",
        )
    flowables.append(PageBreak())

    # 12 Kapitalzufluesse + Ziele
    header()
    if data.cashflow_events:
        flowables.extend(make_cashflows_section(
            data.cashflow_events,
            base_currency=ctx.base_currency,
        ))
        flowables.append(Spacer(1, 4 * mm))
    if data.goals_list:
        flowables.extend(make_ziele_overview_section(
            data.goals_list,
            base_currency=ctx.base_currency,
        ))
    if not (data.cashflow_events or data.goals_list):
        empty_section("Kapitalzufluesse & Ziele", "Noch keine Cashflow-Ereignisse oder Anlageziele erfasst.")
    flowables.append(PageBreak())

    # 13 Gesamtvermoegen: Donuts
    header()
    if data.target_allocation_bps and sum(data.target_allocation_bps.values()) > 0:
        from reportlab.platypus import KeepTogether
        title_para = Paragraph(
            '<font color="#475569" size="9"><b>VERMOEGENSSTRUKTUR - GESAMTVERMOEGEN</b></font>',
            styles["section_title"],
        )
        if data.current_allocation_bps and sum(int(v or 0) for v in data.current_allocation_bps.values()) > 0:
            total_donuts = make_two_donuts_comparison(
                data.current_allocation_bps,
                data.target_allocation_bps,
                current_products=data.advisory_positions + data.other_wealth_positions,
                target_products=data.products,
                diameter_mm=42.0,
            )
            flowables.append(KeepTogether([title_para, *total_donuts]))
        else:
            flowables.append(KeepTogether([
                title_para,
                make_saa_donut_with_legend(
                    data.target_allocation_bps,
                    products=data.products,
                    diameter_mm=48.0,
                ),
            ]))
    else:
        empty_section("Vermoegensstruktur Gesamtvermoegen", "Noch keine Soll-Allokation berechnet.")
    flowables.append(PageBreak())

    # 14 Gesamtvermoegen: Tabellenwerte
    header()
    if data.target_allocation_bps and sum(data.target_allocation_bps.values()) > 0:
        flowables.extend(make_saa_bar_table(
            data.target_allocation_bps,
            bucket_bands_bps=data.bucket_bands_bps,
            bucket_amounts_rappen=data.bucket_amounts_rappen,
            base_currency=ctx.base_currency,
            advisory_wealth_rappen=data.advisory_wealth_rappen,
        ))
    else:
        empty_section("Vermoegensstruktur Gesamtvermoegen", "Noch keine Soll-Allokation berechnet.")
    flowables.append(PageBreak())

    # 15 Empfehlung
    header()
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
        empty_section("Risikoindikatoren", "Noch keine Monte-Carlo-Simulation gespeichert.")
    flowables.append(Spacer(1, 4 * mm))
    if data.goal_analysis:
        flowables.extend(make_ziele_section(
            data.goal_analysis,
            base_currency=ctx.base_currency,
        ))
    else:
        empty_section("Zielerreichung", "Noch keine Zielerreichungsanalyse gespeichert.")
    flowables.append(PageBreak())

    # 16-17 Kennzahlen
    flowables.extend(make_kennzahlen_erlaeuterungen_section())
    flowables.append(PageBreak())
    flowables.extend(_make_kennzahlen_hinweise_section(styles))
    flowables.append(PageBreak())

    # 18 Fondsuebersicht
    flowables.extend(make_produkte_section(
        data.products,
        base_currency=ctx.base_currency,
    ))
    flowables.append(PageBreak())

    # 19 Disclaimer
    flowables.extend(make_disclaimer_section())

    return flowables


def _make_preferences_section(preferences, styles) -> list:
    """Anlagepraeferenzen als ruhige, tabellarische Vorlagen-Seite."""
    from services.pdf.components.header import _esc
    from services.pdf.styles import (
        COLOR_BORDER,
        COLOR_TABLE_HEADER_BG,
        COLOR_TEXT,
        COLOR_TEXT_LIGHT,
        FONT_BOLD,
        FONT_DEFAULT,
        FONT_SIZE_TABLE,
        FONT_SIZE_TABLE_HEADER,
        PAGE_SIZE,
    )

    prefs = preferences if isinstance(preferences, dict) else {}
    policy = prefs.get("policy") if isinstance(prefs.get("policy"), dict) else {}
    product = prefs.get("product") if isinstance(prefs.get("product"), dict) else {}
    geo = prefs.get("geo") if isinstance(prefs.get("geo"), dict) else {}
    asset_classes = prefs.get("assetClasses") if isinstance(prefs.get("assetClasses"), dict) else {}
    tilts = prefs.get("tilts") if isinstance(prefs.get("tilts"), dict) else {}
    bands = prefs.get("bands") if isinstance(prefs.get("bands"), dict) else {}

    rows = [["Bereich", "Festgehaltene Praeferenz"]]
    rows.extend([
        ["Nachhaltigkeit", _label(policy.get("esg"), {
            "none": "Keine ESG-Praeferenz",
            "esg_integration": "ESG-Integration",
            "best_in_class": "Best-in-Class",
            "negative_screening": "Negativ-Screening",
            "impact": "Impact Investing",
            "net_zero": "Paris-aligned / Net Zero",
        }, "Standard / keine gesonderte Vorgabe")],
        ["Anlageuniversum", _label(policy.get("universe"), {
            "standard": "Standard",
            "extended": "Erweitert",
            "funds_only": "Nur Fonds/ETFs",
            "listed_only": "Nur kotierte Instrumente",
        }, "Standard")],
        ["Heimmarkt", _label(policy.get("homeBias"), {
            "none": "Kein Heimmarkt-Bias",
            "ch_focus": "Schweiz-Fokus bevorzugt",
            "europe_focus": "Europa-Fokus",
            "global": "Global neutral",
        }, "Schweiz-Fokus bevorzugt")],
        ["Waehrung", _label(policy.get("hedging"), {
            "none": "Keine FX-Vorgabe",
            "hedged": "FX-gehedgt bevorzugt",
            "chf_only": "Nur CHF-Instrumente",
            "risk_budget": "FX ausserhalb Risiko-Budget",
        }, "Keine FX-Vorgabe")],
        ["Aktien", str(asset_classes.get("equitiesGeo") or "Schweiz Fokus")],
        ["Obligationen", str(asset_classes.get("bondsDuration") or "Langfristig")],
        ["Immobilien", str(asset_classes.get("realestateMarket") or "Schweiz")],
        ["Alternative Anlagen", _alternatives_label(asset_classes)],
    ])

    restrictions = []
    restriction_labels = [
        ("noDerivatives", "Keine Derivate"),
        ("noLeverage", "Keine Hebelprodukte"),
        ("noStructured", "Keine strukturierten Produkte"),
        ("listedOnly", "Nur kotierte Titel"),
        ("fundsOnly", "Nur Fonds/ETFs"),
    ]
    for key, label in restriction_labels:
        if product.get(key):
            restrictions.append(label)
    geo_labels = [
        ("chFocus", "CH-Fokus"),
        ("noEm", "Kein Schwellenlaender-Exposure"),
        ("hedgingRequired", "FX-Absicherung obligatorisch"),
        ("chfOnly", "Nur CHF-Instrumente"),
        ("noUsd", "Kein USD"),
    ]
    for key, label in geo_labels:
        if geo.get(key):
            restrictions.append(label)
    tilt_names = {
        "fossil": "Fossile Energie",
        "defense": "Verteidigung",
        "tobacco": "Tabak",
        "alcohol": "Alkohol",
        "gaming": "Gluecksspiel",
        "nuclear": "Kernenergie",
    }
    tilt_actions = {
        "exclude": "ausschliessen",
        "underweight": "untergewichten",
        "overweight": "uebergewichten",
    }
    for key, mode in tilts.items():
        if mode and mode != "neutral" and key in tilt_names:
            restrictions.append(f"{tilt_names[key]} {tilt_actions.get(mode, mode)}")
    rows.append(["Restriktionen", "; ".join(restrictions) if restrictions else "Keine aktiven Restriktionen"])

    band_labels = []
    for key, override in bands.items():
        if not isinstance(override, dict):
            continue
        parts = []
        for field, label in (("min_bps", "Min"), ("target_bps", "Soll"), ("max_bps", "Max")):
            value = override.get(field)
            if value is not None:
                parts.append(f"{label} {int(value) / 100:.1f}%")
        if parts:
            band_labels.append(f"{key}: " + " / ".join(parts))
    rows.append(["Individuelle Bandbreiten", "; ".join(band_labels) if band_labels else "Keine Overrides"])

    table_rows = []
    for idx, (area, preference) in enumerate(rows):
        is_header = idx == 0
        font = FONT_BOLD if is_header else FONT_DEFAULT
        color = "#475569" if is_header else "#0f172a"
        table_rows.append([
            Paragraph(
                f'<font name="{font}" color="{color}">{_esc(area)}</font>',
                _preference_cell_style(is_header),
            ),
            Paragraph(
                f'<font name="{font}" color="{color}">{_esc(preference)}</font>',
                _preference_cell_style(is_header),
            ),
        ])
    page_width, _ = PAGE_SIZE
    table_width = page_width - 24 * mm
    table = Table(table_rows, colWidths=[table_width * 0.30, table_width * 0.70], repeatRows=1)
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
        ("FONTSIZE", (0, 0), (-1, 0), FONT_SIZE_TABLE_HEADER),
        ("FONTSIZE", (0, 1), (-1, -1), FONT_SIZE_TABLE),
        ("FONTNAME", (0, 1), (-1, -1), FONT_DEFAULT),
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_TABLE_HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), COLOR_TEXT_LIGHT),
        ("TEXTCOLOR", (0, 1), (-1, -1), COLOR_TEXT),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, COLOR_BORDER),
        ("LINEBELOW", (0, 1), (-1, -2), 0.3, COLOR_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))

    return [
        Paragraph("Anlagepraeferenzen", styles["heading"]),
        Paragraph(
            "Die Praeferenzen beeinflussen die Umsetzung innerhalb der Anlageklassen "
            "und werden bei der Produktauswahl sowie bei Bandbreiten beruecksichtigt.",
            styles["body"],
        ),
        Spacer(1, 4 * mm),
        table,
    ]


def _make_kennzahlen_hinweise_section(styles) -> list:
    """Second explanation page, mirroring the reference's split metrics appendix."""
    from services.pdf.components.header import _esc
    from services.pdf.styles import FONT_BOLD, FONT_DEFAULT, FONT_SIZE_BODY

    paragraphs = [
        (
            "Fehlbetrag",
            "Der Fehlbetrag misst den Betrag, der als zusaetzliches Kapital aus heutiger "
            "Perspektive benoetigt wird, um die Zielerreichung in einem sehr schlechten "
            "Kapitalmarktszenario zu stabilisieren. Er ist eine Orientierungsgroesse und "
            "keine Garantie."
        ),
        (
            "Einordnung",
            "Die ausgewiesenen Kennzahlen sind Planungs- und Beratungsgroessen. Sie "
            "beruhen auf Modellannahmen, Kapitalmarkterwartungen und den erfassten "
            "Kundendaten. Aenderungen bei Zielen, Vermoegen, Anlagehorizont oder "
            "Risikoprofil koennen die Empfehlung wesentlich veraendern."
        ),
        (
            "Dokumentation",
            "Abweichungen, Berater-Overrides, fehlende Informationen und besondere "
            "Kundenentscheide muessen im Beratungsprotokoll festgehalten werden. Eine "
            "Strategie darf nur umgesetzt werden, wenn die Eignungspruefung vollstaendig "
            "und plausibel dokumentiert ist."
        ),
    ]

    flowables = [Paragraph("Erlaeuterungen zu den Kennzahlen", styles["heading"])]
    for title, text in paragraphs:
        flowables.append(Spacer(1, 3 * mm))
        flowables.append(Paragraph(
            f'<font name="{FONT_BOLD}" size="{FONT_SIZE_BODY}" color="#0f172a">'
            f'{_esc(title)}</font>',
            styles["subheading"],
        ))
        flowables.append(Paragraph(
            f'<font name="{FONT_DEFAULT}" size="{FONT_SIZE_BODY}" color="#334155">'
            f'{_esc(text)}</font>',
            styles["body"],
        ))
    return flowables


def _label(value, labels: dict, fallback: str) -> str:
    return labels.get(str(value or ""), str(value or fallback))


def _alternatives_label(asset_classes: dict) -> str:
    labels = [
        ("altsGold", "Gold / Rohstoffe"),
        ("altsLiquidAlts", "Liquid Alternatives"),
        ("altsHedge", "Hedge Funds"),
        ("altsPe", "Private Equity"),
        ("altsCrypto", "Krypto"),
    ]
    selected = [label for key, label in labels if asset_classes.get(key)]
    return " + ".join(selected) if selected else "Keine Schwerpunkte"


def _preference_cell_style(is_header: bool):
    from reportlab.lib.styles import ParagraphStyle
    from services.pdf.styles import FONT_DEFAULT, FONT_SIZE_TABLE, FONT_SIZE_TABLE_HEADER

    size = FONT_SIZE_TABLE_HEADER if is_header else FONT_SIZE_TABLE
    return ParagraphStyle(
        "PreferenceCellHeader" if is_header else "PreferenceCell",
        fontName=FONT_DEFAULT,
        fontSize=size,
        leading=max(size + 3, 10),
        spaceAfter=0,
    )


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
