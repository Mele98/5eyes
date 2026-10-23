"""Target-only depot analysis for the client consultation."""
from __future__ import annotations

from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, Spacer

from services.pdf.base import DepotCheckData, PDFContext
from services.pdf.components.backtest_metrics import make_backtest_metrics_table
from services.pdf.components.depotcheck_soll import (
    make_concentration_table,
    make_cost_table,
    make_diversification_heatmap,
    make_exposure_bars,
    make_risk_kpis,
    make_sub_allocation_table,
    make_summary_text,
    make_target_allocation_bars,
)
from services.pdf.components.header import _esc, make_wealtharchitekten_header
from services.pdf.components.single_report_disclaimer import (
    make_single_report_cover,
)
from services.pdf.components.stress_table import make_stress_table
from services.pdf.components.wealth_chart import make_wealth_chart
from services.pdf.styles import FONT_BOLD, FONT_DEFAULT, make_paragraph_styles


def build_depotcheck_flowables(ctx: PDFContext, data: DepotCheckData) -> list:
    """Compose a professional SOLL analysis without current-vs-target drift."""
    flowables: list = []
    advisory_label = (
        _format_amount(data.total_advisory_wealth_rappen, ctx.base_currency)
        if data.total_advisory_wealth_rappen
        else None
    )

    flowables.extend(make_single_report_cover(
        ctx,
        title="Depot-Check",
        subtitle="Analyse des empfohlenen Zielportfolios",
        mandate_number=data.mandate_number,
        advisory_wealth_label=advisory_label,
        focus_points=[
            "Zielstruktur nach Haupt- und Subanlageklassen",
            "Diversifikation nach Laendern, Sektoren und Waehrungen",
            "Risiko, Kosten, historische Einordnung und Klumpenrisiken",
            "Beratungsgrundlage fuer den Abgleich mit externen Depotunterlagen",
        ],
    ))
    flowables.append(PageBreak())

    _start_page(
        flowables,
        ctx,
        data,
        advisory_label,
        "Hauptanlageklassen",
        "Die farbigen Balken zeigen die empfohlene Zielquote. Helle Bereiche "
        "markieren die dokumentierten Bandbreiten.",
    )
    flowables.append(make_target_allocation_bars(
        data.target_allocation_bps,
        data.bucket_bands_bps,
    ))
    flowables.append(Spacer(1, 7 * mm))
    flowables.append(make_summary_text(
        _allocation_story(data.target_allocation_bps, data.risk_profile_label)
    ))
    flowables.append(PageBreak())

    _start_page(
        flowables,
        ctx,
        data,
        advisory_label,
        "Subanlageklassen",
        "Die Detailstruktur zeigt, wie die Hauptanlageklassen in konkrete "
        "Anlagesegmente und Zielbetraege uebersetzt werden.",
    )
    flowables.append(make_sub_allocation_table(
        data.sub_allocations,
        ctx.base_currency,
    ))
    flowables.append(PageBreak())

    _start_page(
        flowables,
        ctx,
        data,
        advisory_label,
        "Laenderallokation",
        "Die Darstellung basiert ausschliesslich auf dem empfohlenen "
        "Zielportfolio. Kleinere Positionen koennen in Sammelkategorien liegen.",
    )
    flowables.append(make_exposure_bars(data.soll_country_exposure_bps))
    flowables.append(PageBreak())

    _start_page(
        flowables,
        ctx,
        data,
        advisory_label,
        "Sektorallokation",
        "Sektorquoten zeigen die wirtschaftliche Streuung der Zielstruktur "
        "und helfen, dominante Themen sichtbar zu machen.",
    )
    flowables.append(make_exposure_bars(data.soll_sector_exposure_bps))
    flowables.append(PageBreak())

    _start_page(
        flowables,
        ctx,
        data,
        advisory_label,
        "Waehrungsallokation",
        "Die Waehrungsdarstellung zeigt die wirtschaftliche Exposition vor "
        "allfaelligen Absicherungen und dient der Beratung ueber Fremdwaehrungsrisiken.",
    )
    flowables.append(make_exposure_bars(data.soll_currency_exposure_bps))
    flowables.append(PageBreak())

    _start_page(
        flowables,
        ctx,
        data,
        advisory_label,
        "Risikoanalyse",
        "Modellwerte beschreiben die erwartete Schwankungs- und Verlustdimension "
        "der Zielstruktur; sie sind keine Garantie fuer kuenftige Ergebnisse.",
    )
    flowables.append(make_risk_kpis(data.risk_profile_label, data.risk_metrics))
    flowables.append(Spacer(1, 6 * mm))
    flowables.append(_section_title("Historische Stress-Szenarien"))
    if data.stress_scenarios:
        flowables.append(make_stress_table(data.stress_scenarios))
    else:
        flowables.append(_fallback("Noch keine belastbaren Stress-Szenarien verfuegbar."))
    flowables.append(PageBreak())

    _start_page(
        flowables,
        ctx,
        data,
        advisory_label,
        "Diversifikation und Klumpenrisiken",
        "Der Herfindahl-Hirschman-Index (HHI) verdichtet die Konzentration je "
        "Dimension. Je tiefer der Wert, desto breiter ist die Verteilung.",
    )
    flowables.append(make_diversification_heatmap(data.soll_concentration_hhi))
    flowables.append(Spacer(1, 6 * mm))
    flowables.append(_section_title("Groesste Zielpositionen"))
    flowables.append(make_concentration_table(data.top_positions, ctx.base_currency))
    flowables.append(PageBreak())

    _start_page(
        flowables,
        ctx,
        data,
        advisory_label,
        "Kosten und Gebuehren",
        "Einmalige und laufende Kosten werden getrennt ausgewiesen. Schaetzwerte "
        "und unvollstaendige Daten bleiben als solche erkennbar.",
    )
    flowables.append(make_cost_table(data.cost_disclosure, ctx.base_currency))
    if data.warnings:
        flowables.append(Spacer(1, 5 * mm))
        flowables.append(_section_title("Annahmen und Datenqualitaet"))
        for warning in data.warnings[:6]:
            flowables.append(Paragraph(
                f'<font name="{FONT_DEFAULT}" size="8.5" color="#475569">'
                f'- {_esc(warning)}</font>',
                make_paragraph_styles()["small"],
            ))
    flowables.append(PageBreak())

    _start_page(
        flowables,
        ctx,
        data,
        advisory_label,
        "Performancevergleich",
        "Historische Simulation der Zielstrategie im Vergleich mit der zum "
        "Risikoprofil passenden strategischen Referenz. Vergangenheitswerte "
        "sind keine Prognose.",
    )
    performance = data.performance or {}
    if not performance.get("data_pending") and performance.get("wealth_path_rappen"):
        flowables.append(make_wealth_chart(
            performance.get("wealth_path_rappen") or [],
            performance.get("benchmark_wealth_path_rappen") or None,
            height_mm=30,
            title="Historischer Vermoegensverlauf",
        ))
        flowables.append(Spacer(1, 4 * mm))
        flowables.append(make_backtest_metrics_table(
            performance.get("metrics") or {},
            performance.get("benchmark_metrics") or None,
        ))
    else:
        flowables.append(_fallback(
            str(performance.get("note") or "Performancevergleich noch nicht verfuegbar.")
        ))
    flowables.append(PageBreak())

    _start_page(
        flowables,
        ctx,
        data,
        advisory_label,
        "Qualitative Einschaetzung",
        "Die Schlussbeurteilung fasst die Zielstruktur fuer das "
        "Beratungsgespraech zusammen.",
    )
    flowables.append(make_summary_text(data.qualitative_assessment or ""))
    flowables.append(Spacer(1, 8 * mm))
    flowables.append(_section_title("Methodik und rechtlicher Hinweis"))
    flowables.append(Paragraph(
        '<font name="{}" size="8.5" color="#475569">'
        'Der Depot-Check analysiert ausschliesslich das empfohlene Zielportfolio. '
        'Der Abgleich mit Bank- oder Drittdepotunterlagen erfolgt ausserhalb '
        'dieses Dokuments durch den Berater. Expositionswerte koennen auf '
        'Produkt- und Referenzdaten beruhen; fehlende Daten werden nicht als '
        'Nullwerte interpretiert.</font>'.format(FONT_DEFAULT),
        make_paragraph_styles()["small"],
    ))
    flowables.append(Paragraph(
        '<font name="{}" size="8.5" color="#475569">'
        'Modellrechnungen, Stress-Szenarien und historische Vergleiche sind '
        'keine Prognosen und keine Zusicherung kuenftiger Ergebnisse. '
        'Massgeblich bleiben die dokumentierte Beratung, Produktunterlagen, '
        'Kosteninformationen und Vertragsunterlagen.</font>'.format(FONT_DEFAULT),
        make_paragraph_styles()["small"],
    ))
    return flowables


def _start_page(
    flowables: list,
    ctx: PDFContext,
    data: DepotCheckData,
    advisory_label: str | None,
    title: str,
    intro: str,
) -> None:
    flowables.extend(make_wealtharchitekten_header(
        ctx,
        mandate_number=data.mandate_number,
        advisory_wealth_label=advisory_label,
        document_title="Depot-Check",
    ))
    flowables.append(Paragraph(
        f'<font name="{FONT_BOLD}" size="18" color="#0f172a">{_esc(title)}</font>',
        make_paragraph_styles()["heading"],
    ))
    flowables.append(Paragraph(
        f'<font name="{FONT_DEFAULT}" size="9.5" color="#475569">{_esc(intro)}</font>',
        make_paragraph_styles()["body"],
    ))
    flowables.append(Spacer(1, 4 * mm))


def _section_title(text: str):
    return Paragraph(
        f'<font name="{FONT_BOLD}" color="#475569" size="9">{_esc(text).upper()}</font>',
        make_paragraph_styles()["section_title"],
    )


def _fallback(text: str):
    return Paragraph(
        f'<font name="{FONT_DEFAULT}" size="9" color="#64748b"><i>{_esc(text)}</i></font>',
        make_paragraph_styles()["small_muted"],
    )


def _allocation_story(allocation_bps, profile: str | None) -> str:
    active = [
        (bucket, int(value or 0))
        for bucket, value in allocation_bps.items()
        if int(value or 0) > 0
    ]
    active.sort(key=lambda item: -item[1])
    if not active:
        return "Noch keine Zielallokation dokumentiert."
    lead = active[0]
    from services.pdf.styles import asset_class_label

    return (
        f"Die Zielstruktur ist auf das Risikoprofil {profile or 'nicht dokumentiert'} "
        f"ausgerichtet. Den groessten Anteil bildet {asset_class_label(lead[0])} "
        f"mit {lead[1] / 100:.1f}%. Insgesamt werden {len(active)} "
        "Hauptanlageklassen kombiniert. Die Bandbreiten definieren den "
        "strategischen Handlungsrahmen und sind keine kurzfristigen Handelssignale."
    )


def _format_amount(rappen: int, currency: str) -> str:
    return f"{currency} {int(rappen or 0) / 100:,.0f}".replace(",", "'")
