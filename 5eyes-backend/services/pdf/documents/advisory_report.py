"""Sprint U-P26 PR A — Advisory-Report Server-PDF (Foundation: Cover + Disclaimer + TOC).

`render_advisory_report_pdf(db, mandate, advisor)` liefert die PDF-Bytes
des institutionellen Depotcheck-Reports. Konsumiert denselben Aggregator
wie die React-Sub-App (`services.advisory_report.compute_advisory_report`)
— Single-Source-of-Truth.

PR A deckt die ersten drei Sektionen ab:
- Cover (Seite 1)
- Disclaimer (Seite 2)
- Inhaltsverzeichnis (Seite 3)
plus Page-Header/Footer ab Seite 2.

Sektionen 4-15 (Ausgangslage, Positionen, Erkenntnisse, AA, Branchen,
Risikoprofil, Building Blocks, Weiteres Vorgehen) folgen in U-P26 PR B-F.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from io import BytesIO
from typing import Any

from reportlab.lib.units import mm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy.orm import Session

from models.mandates import Mandate
from models.users import User
from services.cost_disclosure import build_cost_disclosure
from services.advisory_report import compute_advisory_report
from services.pdf.fonts import register_editorial_fonts
from services.pdf.components.advisory_page_chrome import (
    AdvisoryNumberedCanvas,
    _format_swiss_datetime,
    make_advisory_page_chrome,
)
from services.pdf.components.compliance_audit import render_compliance_audit_section
from services.pdf.components.kostenausweis import build_kostenausweis_flowables
from services.pdf.components.advisory_palette import (
    COLOR_ACCENT,
    COLOR_CANVAS_SUBTLE,
    COLOR_GOLD,
    COLOR_INK,
    COLOR_INK_MUTED,
    COLOR_INK_SUBTLE,
    COLOR_RULE,
    COLOR_STATUS_GRUEN,
    COLOR_STATUS_NEUTRAL,
    COLOR_STATUS_ROT,
    FONT_MONO,
    FONT_SANS,
    FONT_SANS_BOLD,
    FONT_SIZE_BODY,
    FONT_SIZE_CAPTION,
    FONT_SIZE_MICRO,
    MARGIN_BOTTOM,
    MARGIN_LEFT,
    MARGIN_RIGHT,
    MARGIN_TOP,
    PAGE_SIZE,
    make_advisory_styles,
)
from services.pdf.components.swiss_numbers import (
    format_bps_as_pct,
    format_bps_signed_pct,
    format_chf_rappen,
    format_integer,
)


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public Entry-Point
# ---------------------------------------------------------------------------

def render_advisory_report_pdf(
    db: Session,
    mandate: Mandate,
    advisor: User | None = None,
) -> bytes:
    """PDF-Bytes des Advisory-Reports für ein Mandat.

    Verwendet denselben Aggregator wie das Frontend; das PDF spiegelt
    1:1 dieselben Daten. Inhalt aktuell: Cover + Disclaimer + TOC (PR A).
    """
    payload = compute_advisory_report(db, mandate, advisor=advisor)
    if not payload.get("cost_disclosure"):
        try:
            payload["cost_disclosure"] = build_cost_disclosure(db, mandate)
        except Exception:
            logger.warning(
                "Ex-ante cost disclosure failed; rendering degraded section.",
                exc_info=True,
            )
            payload["cost_disclosure"] = {
                "data_pending": True,
                "warnings": [
                    "Kosten konnten für diesen Bericht nicht vollständig "
                    "ermittelt werden."
                ],
            }
    return render_advisory_report_pdf_from_payload(payload)


def render_advisory_report_pdf_from_payload(payload: dict[str, Any]) -> bytes:
    """Pure PDF-Render aus einem bereits berechneten Aggregator-Payload.

    Single-Pass-Build: `AdvisoryNumberedCanvas` sammelt die finalen
    Seitenzustände und zeichnet den Page-Chrome beim Speichern mit bekannter
    Gesamtseitenzahl. Falls ReportLab in diesem Pfad scheitert, fällt der
    Renderer auf den bisherigen Two-Pass-Pfad zurück.
    """
    register_editorial_fonts()
    cover = payload.get("cover") or {}
    mandate_number = str(cover.get("mandate_number") or "—")
    generated_at = str(payload.get("generated_at") or "")
    client_name = str(cover.get("client_name") or "—")
    styles = make_advisory_styles()

    def _new_doc() -> tuple[BytesIO, SimpleDocTemplate]:
        buf = BytesIO()
        return buf, SimpleDocTemplate(
            buf,
            pagesize=PAGE_SIZE,
            topMargin=MARGIN_TOP,
            bottomMargin=MARGIN_BOTTOM,
            leftMargin=MARGIN_LEFT,
            rightMargin=MARGIN_RIGHT,
            title=f"5eyes Advisory Report — {client_name}",
            author=str(cover.get("advisor_name") or ""),
            subject="Strategische Portfolioanalyse",
            creator="5eyes",
        )

    started = time.perf_counter()
    try:
        out_buf, out_doc = _new_doc()

        def _canvasmaker(*args, **kwargs) -> AdvisoryNumberedCanvas:
            return AdvisoryNumberedCanvas(
                *args,
                mandate_number=mandate_number,
                generated_at_iso=generated_at,
                **kwargs,
            )

        out_doc.build(
            _build_all_flowables(payload, styles),
            canvasmaker=_canvasmaker,
        )
        elapsed = time.perf_counter() - started
        logger.info("advisory_report_pdf_render_seconds=%.3f mode=single_pass", elapsed)
        return out_buf.getvalue()
    except Exception:
        logger.warning(
            "Single-pass advisory PDF render failed; falling back to two-pass.",
            exc_info=True,
        )
        return _render_advisory_report_pdf_two_pass(
            _new_doc,
            payload,
            styles,
            mandate_number=mandate_number,
            generated_at=generated_at,
        )


def _render_advisory_report_pdf_two_pass(
    new_doc,
    payload: dict[str, Any],
    styles: dict,
    *,
    mandate_number: str,
    generated_at: str,
) -> bytes:
    """Compatibility fallback for environments that reject canvasmaker."""
    _scratch_buf, scratch_doc = new_doc()
    counter = _PageCounter()
    scratch_doc.build(
        _build_all_flowables(payload, styles),
        onFirstPage=counter, onLaterPages=counter,
    )
    total_pages = counter.page_count or 1

    out_buf, out_doc = new_doc()
    chrome = make_advisory_page_chrome(
        mandate_number=mandate_number,
        generated_at_iso=generated_at,
        total_pages_hint=total_pages,
    )
    out_doc.build(
        _build_all_flowables(payload, styles),
        onFirstPage=chrome, onLaterPages=chrome,
    )
    return out_buf.getvalue()


def _build_all_flowables(payload: dict[str, Any], styles: dict) -> list[Any]:
    """Erzeugt einen frischen Flowable-Snapshot fuer einen PDF-Build."""
    flowables: list[Any] = []
    flowables.extend(_build_cover_flowables(payload.get("cover") or {}, styles))
    flowables.append(PageBreak())
    flowables.extend(_build_disclaimer_flowables(payload.get("disclaimer") or {}, styles))
    flowables.append(PageBreak())
    flowables.extend(_build_toc_flowables(payload.get("inhaltsverzeichnis") or {}, styles))
    flowables.append(PageBreak())
    flowables.extend(_build_ausgangslage_flowables(payload.get("ausgangslage") or {}, styles))
    flowables.append(PageBreak())
    flowables.extend(_build_positionen_flowables(payload.get("positionen") or {}, styles))
    flowables.append(PageBreak())
    flowables.extend(_build_pruefpunkte_flowables(payload.get("pruefpunkte") or {}, styles))
    flowables.append(PageBreak())
    flowables.extend(_build_erkenntnisse_flowables(payload.get("erkenntnisse") or {}, styles))
    flowables.append(PageBreak())
    flowables.extend(_build_asset_allocation_flowables(payload.get("asset_allocation") or {}, styles))
    flowables.append(PageBreak())
    flowables.extend(_build_risikowaehrungen_flowables(payload.get("risikowaehrungen") or {}, styles))
    flowables.append(PageBreak())
    flowables.extend(_build_branchen_flowables(payload.get("branchen") or {}, styles))
    flowables.append(PageBreak())
    flowables.extend(_build_goals_flowables(payload.get("goal_based_investing") or {}, styles))
    flowables.append(PageBreak())
    flowables.extend(_build_risikoprofil_flowables(payload.get("risikoprofilierung") or {}, styles))
    flowables.append(PageBreak())
    flowables.extend(_build_building_blocks_flowables(payload.get("building_blocks") or {}, styles))
    flowables.append(PageBreak())
    flowables.extend(_build_statement_pm_flowables(payload.get("statement_pm") or {}, styles))
    flowables.append(PageBreak())
    flowables.extend(_build_weiteres_vorgehen_flowables(payload.get("weiteres_vorgehen") or {}, styles))
    flowables.append(PageBreak())
    flowables.extend(_build_beratungsprotokoll_flowables(payload.get("beratungsprotokoll") or {}, styles))
    flowables.append(PageBreak())
    flowables.extend(_build_stress_replay_flowables(payload.get("stress_replay") or {}, styles))
    flowables.append(PageBreak())
    # Sprint U-71 (2026-06-06): A/B-Backtest-Sektion nur wenn der Berater
    # via payload['ab_backtest'] explizit ein Vergleichsresultat injiziert.
    # Wenn nicht vorhanden -> Sektion wird stillschweigend ausgelassen.
    ab_bt = payload.get("ab_backtest") or {}
    if ab_bt:
        flowables.extend(_build_ab_backtest_flowables(ab_bt, styles))
        flowables.append(PageBreak())
    # Der Kostenausweis folgt im Dossier auf die Interessenkonflikt-
    # Offenlegungen (Sektion 18) und vor dem konsolidierten Compliance-Audit.
    flowables.extend(build_kostenausweis_flowables(
        payload.get("cost_disclosure") or {},
        styles,
    ))
    flowables.append(PageBreak())
    render_compliance_audit_section(payload, flowables, styles)
    return flowables


class _PageCounter:
    """Page-Callback ohne Drawing, der die finale Seitenzahl tracked."""

    def __init__(self) -> None:
        self.page_count: int = 0

    def __call__(self, canvas, doc) -> None:
        self.page_count = max(self.page_count, int(doc.page))


# ---------------------------------------------------------------------------
# Sektion 1 — Cover
# ---------------------------------------------------------------------------

def _build_cover_flowables(cover: dict, styles: dict) -> list[Any]:
    """Editorial Cover-Layout:
    - Wordmark oben
    - Display-Titel + Subtitle (Mitte oben)
    - 2×2-Grid mit Berater/Mandate/Datum (unten)
    - dünner Gold-Akzent zwischen Titel und Grid
    """
    page_width, page_height = PAGE_SIZE
    inner_width = page_width - MARGIN_LEFT - MARGIN_RIGHT

    title = str(cover.get("title") or "Depotcheck")
    subtitle = str(cover.get("subtitle") or "Strategische Portfolioanalyse")
    client_name = str(cover.get("client_name") or "—")
    mandate_number = str(cover.get("mandate_number") or "—")
    advisor_name = str(cover.get("advisor_name") or "—")
    report_date = _format_swiss_date(str(cover.get("report_date") or ""))

    out: list[Any] = []

    # Wordmark + Tagline (oben)
    out.append(Paragraph("<b>5eyes</b>", _ar_paragraph_style(
        styles["caption"], font=FONT_SANS_BOLD, color=COLOR_INK, size=FONT_SIZE_CAPTION,
    )))
    out.append(Paragraph(
        "Wealth Architects",
        _ar_paragraph_style(styles["micro"], color=COLOR_INK_SUBTLE),
    ))
    out.append(Spacer(1, 38 * mm))

    # Display-Titel + Subtitle (mittiger Block)
    out.append(Paragraph(title, styles["display"]))
    out.append(Paragraph(
        f"<i>{_escape(subtitle)}</i>",
        _ar_paragraph_style(styles["h3"], color=COLOR_INK_MUTED),
    ))
    out.append(Spacer(1, 4 * mm))

    # dünner Gold-Akzent als horizontale 60mm-Linie (Mini-Rule)
    rule_table = Table(
        [[""]],
        colWidths=[60 * mm],
        rowHeights=[1.2],
    )
    rule_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), COLOR_GOLD),
        ("LINEBELOW", (0, 0), (-1, -1), 0, COLOR_GOLD),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
    ]))
    out.append(rule_table)
    out.append(Spacer(1, 32 * mm))

    # 2×2-Grid mit Kunde / Mandat / Berater / Datum
    col_w = inner_width / 2
    grid_data = [
        [
            _kvp(styles, "Kundin / Kunde", client_name),
            _kvp(styles, "Mandat-Nr.", mandate_number),
        ],
        [
            _kvp(styles, "Berater / Beraterin", advisor_name),
            _kvp(styles, "Berichtsdatum", report_date),
        ],
    ]
    grid = Table(grid_data, colWidths=[col_w, col_w])
    grid.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    out.append(grid)
    return out


def _kvp(styles: dict, label: str, value: str):
    """Label-Value-Paar fürs Cover-Grid: kicker oben, body unten."""
    label_p = Paragraph(
        _escape(label.upper()),
        _ar_paragraph_style(
            styles["micro"], font=FONT_SANS_BOLD, color=COLOR_INK_SUBTLE,
        ),
    )
    value_p = Paragraph(_escape(value), styles["body"])
    inner = Table(
        [[label_p], [value_p]],
        colWidths=[None],
    )
    inner.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (0, 0), 2),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 0),
    ]))
    return inner


# ---------------------------------------------------------------------------
# Sektion 2 — Disclaimer
# ---------------------------------------------------------------------------

def _build_disclaimer_flowables(disclaimer: dict, styles: dict) -> list[Any]:
    """7 Hinweise nummeriert, FINMA-konformer Ton, kompakt."""
    out: list[Any] = []
    out.append(Paragraph("Sektion 2", styles["kicker"]))
    out.append(Paragraph("Rechtliche Hinweise", styles["h1"]))
    out.append(Spacer(1, 4 * mm))
    out.append(_hr())
    out.append(Spacer(1, 4 * mm))

    hinweise = disclaimer.get("hinweise") or []
    for idx, hinweis in enumerate(hinweise, start=1):
        text = _escape(str(hinweis or ""))
        if not text:
            continue
        bullet = f"<font color='#6F7A8A'>{idx:02d}</font>  {text}"
        out.append(Paragraph(bullet, _ar_paragraph_style(
            styles["caption"], color=COLOR_INK_MUTED, leading=FONT_SIZE_CAPTION + 4,
        )))
        out.append(Spacer(1, 2 * mm))

    if not hinweise:
        out.append(Paragraph(
            "<i>Keine rechtlichen Hinweise erfasst.</i>",
            styles["caption"],
        ))
    return out


# ---------------------------------------------------------------------------
# Sektion 3 — Inhaltsverzeichnis
# ---------------------------------------------------------------------------

def _build_toc_flowables(toc: dict, styles: dict) -> list[Any]:
    """12 Kapitel mit Nummer, Name, Punktreihe, Seitenzahl-Placeholder.

    Echte Seitenzahlen erfordern Two-Pass-Build (Folge-PR). Aktuell
    rendern wir den Kapitel-Namen ohne Seitenzahl, damit Layout stabil
    bleibt — Berater sieht trotzdem die Struktur.
    """
    out: list[Any] = []
    out.append(Paragraph("Sektion 3", styles["kicker"]))
    out.append(Paragraph("Inhaltsverzeichnis", styles["h1"]))
    out.append(Spacer(1, 4 * mm))
    out.append(_hr())
    out.append(Spacer(1, 6 * mm))

    kapitel = toc.get("kapitel") or []
    if not kapitel:
        out.append(Paragraph(
            "<i>Keine Kapitel erfasst.</i>",
            styles["caption"],
        ))
        return out

    page_width, _ = PAGE_SIZE
    inner_width = page_width - MARGIN_LEFT - MARGIN_RIGHT
    # Sprint U-13 (2026-06-06): TOC bekommt 3 Spalten — Nr/Titel/Seite
    nr_col = 14 * mm
    page_col = 22 * mm
    title_col = inner_width - nr_col - page_col

    # Sprint U-13 (2026-06-06): Estimated-Page-Numbers basierend auf
    # Kapitel-Reihenfolge. Echtere Seitenzahlen kommen mit Two-Pass-
    # Render (siehe U-26).
    # Annahme: Cover=1, Disclaimer=2, TOC=3, dann ca. 1.5 Seiten pro
    # Folge-Kapitel. Berater sieht: 'Seite ca. X' mit Hinweis darauf
    # dass exakte Seitenzahl mit dem finalen Druck variieren kann.
    estimated_pages_per_section_after_toc = [
        1, 2, 3,  # Cover / Disclaimer / TOC -> Sektion 1/2/3
    ]
    # Ab Sektion 4 (Ausgangslage): geschaetzt ~1.5 Seiten pro Sektion
    running_page = 3
    for _idx in range(3, max(3, len(kapitel))):
        running_page += 2  # konservativ 2 Seiten pro Sektion
        estimated_pages_per_section_after_toc.append(running_page)

    rows = []
    for i, k in enumerate(kapitel):
        nr = _format_two_digits(k.get("nr"))
        title = _escape(str(k.get("title") or "—"))
        # Fallback wenn mehr Kapitel als unsere Estimate-Liste
        estimated_page = (
            estimated_pages_per_section_after_toc[i]
            if i < len(estimated_pages_per_section_after_toc)
            else (estimated_pages_per_section_after_toc[-1] + 2)
        )
        page_label = f"ca. {estimated_page}"
        rows.append([
            Paragraph(
                f"<font face='{FONT_SANS}' size='{FONT_SIZE_MICRO}' color='#6F7A8A'>{nr}</font>",
                styles["caption"],
            ),
            Paragraph(title, _ar_paragraph_style(styles["body"], color=COLOR_INK)),
            Paragraph(
                f"<font face='{FONT_SANS}' size='{FONT_SIZE_MICRO}' color='#6F7A8A'>{page_label}</font>",
                _ar_paragraph_style(styles["caption"], color=COLOR_INK_SUBTLE),
            ),
        ])
    table = Table(rows, colWidths=[nr_col, title_col, page_col])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, -2), 0.2, COLOR_RULE),
        ("ALIGN", (2, 0), (2, -1), "RIGHT"),  # Page rechts-bündig
    ]))
    out.append(table)
    out.append(Spacer(1, 4 * mm))
    # Sprint U-13: Disclaimer fuer geschaetzte Seitenzahlen
    out.append(Paragraph(
        "<i>Geschaetzte Seitenzahlen. Die exakten Seitenzahlen werden mit "
        "dem finalen Druck der Sektionen variieren.</i>",
        _ar_paragraph_style(styles["caption"], color=COLOR_INK_SUBTLE),
    ))
    return out


# ---------------------------------------------------------------------------
# Sektion 4 — Ausgangslage (Client-Info + Wealth-Summary + Key-Metrics)
# ---------------------------------------------------------------------------

def _build_ausgangslage_flowables(ausgangslage: dict, styles: dict) -> list[Any]:
    """Editorial 2-Spalten-Layout: links Client-Info, rechts Wealth-Summary,
    unten 6 KPI-Karten."""
    out: list[Any] = []
    out.append(Paragraph("Sektion 4", styles["kicker"]))
    out.append(Paragraph("Ausgangslage", styles["h1"]))
    out.append(Spacer(1, 4 * mm))
    out.append(_hr())
    out.append(Spacer(1, 6 * mm))

    client_info = ausgangslage.get("client_info") or {}
    wealth = ausgangslage.get("wealth_summary") or {}
    metrics = ausgangslage.get("key_metrics") or {}

    page_width, _ = PAGE_SIZE
    inner_width = page_width - MARGIN_LEFT - MARGIN_RIGHT
    col_w = (inner_width - 6 * mm) / 2

    left_col = _build_client_info_block(client_info, styles)
    right_col = _build_wealth_summary_block(wealth, styles)

    grid = Table(
        [[left_col, right_col]],
        colWidths=[col_w, col_w],
    )
    grid.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    out.append(grid)

    out.append(Spacer(1, 8 * mm))
    out.append(_hr())
    out.append(Spacer(1, 6 * mm))
    out.append(Paragraph("Kennzahlen", styles["h2"]))
    out.append(Spacer(1, 3 * mm))
    out.append(_build_key_metrics_row(metrics, styles))
    return out


def _build_client_info_block(client_info: dict, styles: dict):
    """Linke Spalte der Sektion 4 — 7 Label-Wert-Paare in einer Tabelle."""
    horizont = client_info.get("anlagehorizont_jahre")
    rows = [
        ("Alter", _format_age(client_info.get("alter"))),
        (
            "Anlagehorizont",
            f"{format_integer(horizont)} Jahre" if horizont else "—",
        ),
        ("Risikoprofil", _safe_string(client_info.get("risikoprofil"))),
        ("Anlageziel", _safe_string(client_info.get("anlageziel"))),
        (
            "Liquiditätsbedarf",
            format_chf_rappen(client_info.get("liquiditaetsbedarf_rappen")),
        ),
        ("Steuerdomizil", _safe_string(client_info.get("steuerdomizil"))),
        ("Referenzwährung", _safe_string(client_info.get("referenzwaehrung"))),
    ]
    return _label_value_table(rows, styles)


def _build_wealth_summary_block(wealth: dict, styles: dict):
    """Rechte Spalte der Sektion 4 — 5 Vermögens-Kategorien."""
    rows = [
        ("Gesamtvermögen", format_chf_rappen(wealth.get("gesamtvermoegen_rappen"))),
        ("Beratungsvermögen", format_chf_rappen(wealth.get("beratungsvermoegen_rappen"))),
        ("Immobilien", format_chf_rappen(wealth.get("immobilien_rappen"))),
        ("Vorsorge", format_chf_rappen(wealth.get("vorsorge_rappen"))),
        ("Kredite", format_chf_rappen(wealth.get("kredite_rappen"))),
    ]
    return _label_value_table(rows, styles)


def _label_value_table(rows: list[tuple[str, str]], styles: dict) -> Table:
    """Kompakte 2-Spalten-Tabelle: Label links (caption), Wert rechts (body).

    Verwendet überall die gleichen Padding-Werte, damit Sektionen
    visuell konsistent sind.
    """
    data = []
    for label, value in rows:
        data.append([
            Paragraph(
                _escape(label),
                _ar_paragraph_style(
                    styles["caption"], color=COLOR_INK_SUBTLE,
                ),
            ),
            Paragraph(
                _escape(value or "—"),
                _ar_paragraph_style(
                    styles["body"], color=COLOR_INK, font=FONT_SANS_BOLD,
                ),
            ),
        ])
    table = Table(data, colWidths=[None, None])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, -2), 0.2, COLOR_RULE),
    ]))
    return table


def _build_key_metrics_row(metrics: dict, styles: dict) -> Table:
    """6 KPI-Karten in einer Zeile (Risky-Fraction / Zielerreichung /
    erw Vol / erw Return / Max DD / VaR 95)."""
    page_width, _ = PAGE_SIZE
    inner_width = page_width - MARGIN_LEFT - MARGIN_RIGHT
    col_w = inner_width / 6

    karten = [
        ("Risky-Fraction", format_bps_as_pct(metrics.get("risky_fraction_bps"))),
        ("Zielerreichung", format_bps_as_pct(metrics.get("zielerreichung_bps"))),
        ("Erw. Volatilität", format_bps_as_pct(metrics.get("exp_vol_bps"))),
        ("Erw. Rendite", format_bps_as_pct(metrics.get("exp_return_bps"))),
        ("Max Drawdown", format_bps_as_pct(metrics.get("max_drawdown_bps"))),
        ("VaR 95 %", format_bps_as_pct(metrics.get("var_95_bps"))),
    ]
    cells = [
        _kpi_card(label, value, styles) for label, value in karten
    ]
    row = Table([cells], colWidths=[col_w] * 6)
    row.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 1),
        ("RIGHTPADDING", (0, 0), (-1, -1), 1),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return row


def _kpi_card(label: str, value: str, styles: dict) -> Table:
    """Mini-Karte: Label oben (micro), Wert mittig (body-bold)."""
    label_p = Paragraph(
        _escape(label),
        _ar_paragraph_style(
            styles["micro"], color=COLOR_INK_SUBTLE, font=FONT_SANS_BOLD,
        ),
    )
    value_p = Paragraph(
        _escape(value or "—"),
        _ar_paragraph_style(
            styles["body"], color=COLOR_INK, font=FONT_SANS_BOLD,
        ),
    )
    card = Table([[label_p], [value_p]])
    card.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (0, 0), 6),
        ("BOTTOMPADDING", (0, 0), (0, 0), 2),
        ("TOPPADDING", (0, 1), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 6),
        ("BACKGROUND", (0, 0), (-1, -1), COLOR_CANVAS_SUBTLE),
        ("LINEBELOW", (0, 0), (-1, 0), 0.2, COLOR_RULE),
    ]))
    return card


# ---------------------------------------------------------------------------
# Sektion 5 — Übersicht Positionen
# ---------------------------------------------------------------------------

def _build_positionen_flowables(positionen: dict, styles: dict) -> list[Any]:
    """Positionen gruppiert nach Anlageklasse (Bucket). Jede Gruppe als
    Tabelle mit Produkt-Name / Anteil / Wert. Total unten."""
    out: list[Any] = []
    out.append(Paragraph("Sektion 5", styles["kicker"]))
    out.append(Paragraph("Übersicht Ihrer Positionen", styles["h1"]))
    out.append(Spacer(1, 4 * mm))
    out.append(_hr())
    out.append(Spacer(1, 5 * mm))

    hinweis = str(positionen.get("hinweis") or "").strip()
    if hinweis:
        out.append(Paragraph(
            _escape(hinweis),
            _ar_paragraph_style(styles["caption"], color=COLOR_INK_MUTED),
        ))
        out.append(Spacer(1, 4 * mm))

    groups = positionen.get("groups") or []
    if not groups:
        out.append(Paragraph(
            "<i>Keine Positionen erfasst.</i>",
            styles["caption"],
        ))
        return out

    for group in groups:
        out.extend(_build_position_group(group, styles))
        out.append(Spacer(1, 4 * mm))

    total_rappen = positionen.get("total_rappen") or 0
    if total_rappen:
        out.append(_hr())
        out.append(Spacer(1, 2 * mm))
        out.append(Paragraph(
            f"Total: <b>{format_chf_rappen(total_rappen)}</b>",
            _ar_paragraph_style(
                styles["body"], color=COLOR_INK, font=FONT_SANS_BOLD,
            ),
        ))
    return out


def _build_position_group(group: dict, styles: dict) -> list[Any]:
    """Ein Bucket: Header (Label + Share + Total) + Positions-Tabelle."""
    out: list[Any] = []
    label = _safe_string(group.get("label"))
    share_bps = group.get("share_bps")
    total_rappen = group.get("total_rappen")

    header_text = (
        f"<b>{_escape(label)}</b>"
        f"  &mdash; {format_bps_as_pct(share_bps)}"
        f"  &middot; {format_chf_rappen(total_rappen)}"
    )
    out.append(Paragraph(header_text, _ar_paragraph_style(
        styles["body"], color=COLOR_INK,
    )))
    out.append(Spacer(1, 1.5 * mm))

    positions = group.get("positions") or []
    if not positions:
        out.append(Paragraph(
            "<i>Keine Positionen in dieser Anlageklasse.</i>",
            styles["caption"],
        ))
        return out

    page_width, _ = PAGE_SIZE
    inner_width = page_width - MARGIN_LEFT - MARGIN_RIGHT
    # Spalten: Name (flex), ISIN (mono), Anteil (right), Wert (right)
    col_name = inner_width * 0.50
    col_isin = inner_width * 0.18
    col_share = inner_width * 0.14
    col_value = inner_width * 0.18

    header_row = [
        Paragraph("Position", _ar_paragraph_style(
            styles["micro"], color=COLOR_INK_SUBTLE, font=FONT_SANS_BOLD,
        )),
        Paragraph("ISIN", _ar_paragraph_style(
            styles["micro"], color=COLOR_INK_SUBTLE, font=FONT_SANS_BOLD,
        )),
        Paragraph("Anteil", _ar_paragraph_style(
            styles["micro"], color=COLOR_INK_SUBTLE, font=FONT_SANS_BOLD,
        )),
        Paragraph("Wert", _ar_paragraph_style(
            styles["micro"], color=COLOR_INK_SUBTLE, font=FONT_SANS_BOLD,
        )),
    ]

    rows = [header_row]
    for pos in positions:
        name = _safe_string(pos.get("product_name"))
        isin = _safe_string(pos.get("isin"))
        currency_suffix = _safe_string(pos.get("currency"))
        provider = _safe_string(pos.get("provider"))
        detail_parts = []
        if provider and provider != "—":
            detail_parts.append(provider)
        if currency_suffix and currency_suffix != "—":
            detail_parts.append(currency_suffix)
        detail_line = " · ".join(detail_parts)
        name_html = _escape(name)
        if detail_line:
            name_html += (
                f"<br/><font size='{FONT_SIZE_MICRO}' color='#6F7A8A'>"
                f"{_escape(detail_line)}</font>"
            )
        rows.append([
            Paragraph(name_html, styles["caption"]),
            Paragraph(
                _escape(isin),
                _ar_paragraph_style(
                    styles["caption_mono"], color=COLOR_INK_MUTED,
                ),
            ),
            Paragraph(
                format_bps_as_pct(pos.get("share_bps")),
                _ar_paragraph_style(
                    styles["caption"], color=COLOR_INK,
                ),
            ),
            Paragraph(
                format_chf_rappen(pos.get("market_value_rappen")),
                _ar_paragraph_style(
                    styles["caption"], color=COLOR_INK,
                ),
            ),
        ])

    table = Table(
        rows,
        colWidths=[col_name, col_isin, col_share, col_value],
    )
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("ALIGN", (2, 0), (3, -1), "RIGHT"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.4, COLOR_RULE),
        ("LINEBELOW", (0, 1), (-1, -1), 0.2, COLOR_RULE),
    ]))
    out.append(table)
    return out


# ---------------------------------------------------------------------------
# Sektion 6 — Was wir im Depotcheck prüfen (statische Beschreibungen)
# ---------------------------------------------------------------------------

def _build_pruefpunkte_flowables(pruefpunkte: dict, styles: dict) -> list[Any]:
    """Editorial-Liste der 10 Prüf-Bereiche.

    Layout: ein 2-Spalten-Grid mit Titel links (h3) und Beschreibung rechts
    (body-muted). Dünne Trenn-Linien zwischen Blöcken, Editorial-Anmutung.
    """
    out: list[Any] = []
    out.append(Paragraph("Sektion 6", styles["kicker"]))
    out.append(Paragraph("Was wir im Depotcheck prüfen", styles["h1"]))
    out.append(Spacer(1, 4 * mm))
    out.append(_hr())
    out.append(Spacer(1, 5 * mm))

    bloecke = pruefpunkte.get("bloecke") or []
    if not bloecke:
        out.append(Paragraph(
            "<i>Keine Prüfpunkte erfasst.</i>",
            styles["caption"],
        ))
        return out

    page_width, _ = PAGE_SIZE
    inner_width = page_width - MARGIN_LEFT - MARGIN_RIGHT
    title_col = inner_width * 0.32
    desc_col = inner_width - title_col

    rows = []
    for block in bloecke:
        title = _safe_string(block.get("title"))
        desc = _safe_string(block.get("beschreibung"))
        rows.append([
            Paragraph(
                _escape(title),
                _ar_paragraph_style(
                    styles["body"], color=COLOR_INK, font=FONT_SANS_BOLD,
                ),
            ),
            Paragraph(_escape(desc), styles["body_muted"]),
        ])

    table = Table(rows, colWidths=[title_col, desc_col])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, -2), 0.2, COLOR_RULE),
    ]))
    out.append(table)
    return out


# ---------------------------------------------------------------------------
# Sektion 7 — Erkenntnisse aus dem Depotcheck (mit Ampel-Pills)
# ---------------------------------------------------------------------------

# Mapping Ampel-Status → (Label, Fillcolor, Textcolor)
_AMPEL_PALETTE = {
    "gruen":            ("OK",       "#E5EEDF", "#4E6F58"),
    "gelb":             ("Achtung",  "#F4EBD5", "#B59243"),
    "rot":              ("Handeln",  "#F0D9D9", "#9E4747"),
    "nicht_beurteilbar":("Pendant",  "#E9EBEE", "#7A8395"),
}


def _build_erkenntnisse_flowables(erkenntnisse: dict, styles: dict) -> list[Any]:
    """Tabelle: Prüfpunkt | Ampel | Beurteilung | Handlungsempfehlung.

    Ampel-Pills sind kleine farbige Rechtecke mit Status-Label (gruen→OK,
    gelb→Achtung, rot→Handeln, nicht_beurteilbar→Pendant). Matte Farben
    gemäss Design-System (NICHT signal-grün/-rot).
    """
    out: list[Any] = []
    out.append(Paragraph("Sektion 7", styles["kicker"]))
    out.append(Paragraph("Erkenntnisse aus dem Depotcheck", styles["h1"]))
    out.append(Spacer(1, 4 * mm))
    out.append(_hr())
    out.append(Spacer(1, 5 * mm))

    checks = erkenntnisse.get("checks") or []
    if not checks:
        out.append(Paragraph(
            "<i>Keine Erkenntnisse erfasst.</i>",
            styles["caption"],
        ))
        return out

    page_width, _ = PAGE_SIZE
    inner_width = page_width - MARGIN_LEFT - MARGIN_RIGHT
    col_pruefpunkt = inner_width * 0.22
    col_ampel = inner_width * 0.10
    col_beurteilung = inner_width * 0.36
    col_empfehlung = inner_width - col_pruefpunkt - col_ampel - col_beurteilung

    header_row = [
        Paragraph("Prüfpunkt", _ar_paragraph_style(
            styles["micro"], color=COLOR_INK_SUBTLE, font=FONT_SANS_BOLD,
        )),
        Paragraph("Status", _ar_paragraph_style(
            styles["micro"], color=COLOR_INK_SUBTLE, font=FONT_SANS_BOLD,
        )),
        Paragraph("Beurteilung", _ar_paragraph_style(
            styles["micro"], color=COLOR_INK_SUBTLE, font=FONT_SANS_BOLD,
        )),
        Paragraph("Handlungsempfehlung", _ar_paragraph_style(
            styles["micro"], color=COLOR_INK_SUBTLE, font=FONT_SANS_BOLD,
        )),
    ]
    rows = [header_row]

    cell_styles: list[tuple] = []  # zusätzliche TableStyle-Commands

    for idx, check in enumerate(checks, start=1):
        pruefpunkt = _safe_string(check.get("pruefpunkt"))
        bewertung = str(check.get("bewertung") or "nicht_beurteilbar").lower()
        beurteilung = _safe_string(check.get("beurteilung"))
        empfehlung = _safe_string(check.get("handlungsempfehlung"))

        ampel_cell = _ampel_pill(bewertung, styles)
        rows.append([
            Paragraph(
                _escape(pruefpunkt),
                _ar_paragraph_style(styles["caption"], color=COLOR_INK, font=FONT_SANS_BOLD),
            ),
            ampel_cell,
            Paragraph(_escape(beurteilung), styles["caption"]),
            Paragraph(_escape(empfehlung), styles["caption"]),
        ])

    table = Table(
        rows,
        colWidths=[col_pruefpunkt, col_ampel, col_beurteilung, col_empfehlung],
    )
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, 0), 0.4, COLOR_RULE),
        ("LINEBELOW", (0, 1), (-1, -1), 0.2, COLOR_RULE),
        *cell_styles,
    ]))
    out.append(table)
    return out


def _ampel_pill(status: str, styles: dict) -> Table:
    """Liefert ein kleines Pill-Element mit Status-Label und Hintergrundfarbe."""
    from reportlab.lib.colors import HexColor

    label, fill_hex, text_hex = _AMPEL_PALETTE.get(
        status, _AMPEL_PALETTE["nicht_beurteilbar"]
    )
    pill = Table(
        [[Paragraph(
            _escape(label),
            _ar_paragraph_style(
                styles["micro"], color=HexColor(text_hex), font=FONT_SANS_BOLD,
            ),
        )]],
        colWidths=[None],
    )
    pill.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HexColor(fill_hex)),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return pill


# ---------------------------------------------------------------------------
# Sektionen 8 / 9 / 10 — IST vs SOLL mit Bar-Charts
# ---------------------------------------------------------------------------

def _build_asset_allocation_flowables(aa: dict, styles: dict) -> list[Any]:
    """Sektion 8 — Asset Allocation: 5 Anlageklassen IST vs SOLL inkl.
    Toleranzbänder. Anmerkungen-Text aus Aggregator (vom Berater
    überschreibbar via MandateReportNotes, U-P28 PR B)."""
    return _build_bar_chart_section(
        nr=8, kicker="Sektion 8", title="Asset Allocation",
        subtitle=(
            "IST-Portfolio gegen strategische SOLL-Allokation, "
            "Drift gegenüber Toleranzband."
        ),
        items=aa.get("items") or [],
        ist_basiert_auf_soll=bool(aa.get("ist_basiert_auf_soll")),
        editorial_label="Einordnung",
        editorial_text=str(aa.get("anmerkungen") or ""),
        styles=styles,
        show_bands=True,
    )


def _build_risikowaehrungen_flowables(rw: dict, styles: dict) -> list[Any]:
    """Sektion 9 — Risikowährungen. Items haben keine Bands; Erklärung-Text
    aus Aggregator."""
    return _build_bar_chart_section(
        nr=9, kicker="Sektion 9", title="Risikowährungen",
        subtitle=(
            "Währungsrisiken als geordnete Exposure-Kategorien "
            "mit SOLL-Vergleich."
        ),
        items=rw.get("items") or [],
        ist_basiert_auf_soll=bool(rw.get("ist_basiert_auf_soll")),
        editorial_label="Einordnung",
        editorial_text=str(rw.get("erklaerung") or ""),
        styles=styles,
        show_bands=False,
    )


def _build_branchen_flowables(br: dict, styles: dict) -> list[Any]:
    """Sektion 10 — Branchen. Sortiert nach Spec (GICS-Reihenfolge), aber
    nur Top-Items + Sammelkategorie 'Übrige'. Analyse-Text aus Aggregator."""
    return _build_bar_chart_section(
        nr=10, kicker="Sektion 10", title="Diversifikation Branchen",
        subtitle=(
            "GICS-Sektoren mit IST/SOLL-Vergleich und Sammelkategorie "
            "für nicht-GICS-Anlagen."
        ),
        items=br.get("items") or [],
        ist_basiert_auf_soll=bool(br.get("ist_basiert_auf_soll")),
        editorial_label="Analyse",
        editorial_text=str(br.get("analyse") or ""),
        styles=styles,
        show_bands=False,
        extra_note=str(br.get("hinweis") or "").strip(),
    )


def _build_bar_chart_section(
    *,
    nr: int,
    kicker: str,
    title: str,
    subtitle: str,
    items: list[dict],
    ist_basiert_auf_soll: bool,
    editorial_label: str,
    editorial_text: str,
    styles: dict,
    show_bands: bool,
    extra_note: str = "",
) -> list[Any]:
    """Gemeinsamer Aufbau für Sektion 8/9/10. Header → Banner → Bars → Editorial."""
    from services.pdf.components.advisory_bar_chart import make_bar_chart_ist_soll

    out: list[Any] = []
    out.append(Paragraph(kicker, styles["kicker"]))
    out.append(Paragraph(title, styles["h1"]))
    out.append(Paragraph(
        f"<i>{_escape(subtitle)}</i>",
        _ar_paragraph_style(styles["h3"], color=COLOR_INK_MUTED),
    ))
    out.append(Spacer(1, 3 * mm))
    out.append(_hr())
    out.append(Spacer(1, 4 * mm))

    if ist_basiert_auf_soll:
        out.append(_data_basis_banner(styles))
        out.append(Spacer(1, 3 * mm))

    if extra_note:
        out.append(Paragraph(
            _escape(extra_note),
            _ar_paragraph_style(styles["caption"], color=COLOR_INK_MUTED),
        ))
        out.append(Spacer(1, 3 * mm))

    if not items:
        out.append(Paragraph(
            "<i>Keine Datenpunkte erfasst.</i>",
            styles["caption"],
        ))
        return out

    page_width, _ = PAGE_SIZE
    inner_width = page_width - MARGIN_LEFT - MARGIN_RIGHT
    chart = make_bar_chart_ist_soll(
        items, inner_width_pt=inner_width, show_bands=show_bands,
    )
    out.append(chart)

    if editorial_text:
        out.append(Spacer(1, 5 * mm))
        out.append(_editorial_note(editorial_label, editorial_text, styles))

    return out


def _data_basis_banner(styles: dict) -> Table:
    """Banner-Hinweis: IST basiert auf SOLL (alte Mandate ohne aktuelle Bestände)."""
    text = Paragraph(
        "<b>Datenstand:</b> IST basiert aktuell auf SOLL-/Empfehlungswerten. "
        "Sobald aktuelle Bestände gepflegt sind, zeigt der Bericht echte "
        "Portfolio-Drifts.",
        _ar_paragraph_style(styles["caption"], color=COLOR_INK_MUTED),
    )
    banner = Table([[text]])
    banner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), COLOR_CANVAS_SUBTLE),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("BOX", (0, 0), (-1, -1), 0.3, COLOR_RULE),
    ]))
    return banner


def _editorial_note(label: str, body: str, styles: dict) -> Table:
    """„Anmerkung"-Box mit Akzent-Linie links."""
    label_p = Paragraph(
        _escape(label.upper()),
        _ar_paragraph_style(
            styles["micro"], color=COLOR_INK_SUBTLE, font=FONT_SANS_BOLD,
        ),
    )
    body_p = Paragraph(
        _escape(body),
        _ar_paragraph_style(styles["body"], color=COLOR_INK_MUTED),
    )
    note = Table([[label_p], [body_p]])
    note.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), COLOR_CANVAS_SUBTLE),
        ("LINEBEFORE", (0, 0), (0, -1), 2.5, COLOR_ACCENT),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (0, 0), 8),
        ("BOTTOMPADDING", (0, 0), (0, 0), 2),
        ("TOPPADDING", (0, 1), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 8),
    ]))
    return note


# ---------------------------------------------------------------------------
# Sektion 11 — Goal-Based Investing
# ---------------------------------------------------------------------------

_GOAL_STATUS_PILL = {
    "erreichbar":      ("Erreichbar",     "#E5EEDF", "#4E6F58"),
    "knapp":           ("Knapp",          "#F4EBD5", "#B59243"),
    "nicht_erreichbar":("Schwierig",      "#F0D9D9", "#9E4747"),
    "data_pending":    ("Daten ausstehend","#E9EBEE", "#7A8395"),
}


def _build_goals_flowables(gbi: dict, styles: dict) -> list[Any]:
    """Goals-Tabelle + Achievement-Score-KPI + MC-Hinweis."""
    out: list[Any] = []
    out.append(Paragraph("Sektion 11", styles["kicker"]))
    out.append(Paragraph("Zielbasierte Optimierung", styles["h1"]))
    out.append(Spacer(1, 4 * mm))
    out.append(_hr())
    out.append(Spacer(1, 5 * mm))

    score_bps = gbi.get("goal_achievement_score_bps")
    if score_bps is not None:
        out.append(_achievement_score_kpi(int(score_bps), styles))
        out.append(Spacer(1, 5 * mm))

    goals = gbi.get("goals") or []
    if goals:
        out.append(_goals_table(goals, styles))
    else:
        out.append(Paragraph(
            "<i>Keine Ziele erfasst.</i>",
            styles["caption"],
        ))

    mc = gbi.get("monte_carlo_paths") or {}
    if mc.get("data_pending"):
        out.append(Spacer(1, 6 * mm))
        out.append(Paragraph(
            f"<b>Monte-Carlo-Pfade:</b> {_escape(str(mc.get('note') or 'in Vorbereitung'))}",
            _ar_paragraph_style(styles["caption"], color=COLOR_INK_MUTED),
        ))
    return out


def _achievement_score_kpi(score_bps: int, styles: dict):
    """Großer Score-Block: Wert mittig, Label oben."""
    label_p = Paragraph(
        "GEWICHTETER ZIELERREICHUNGS-SCORE",
        _ar_paragraph_style(
            styles["micro"], color=COLOR_INK_SUBTLE, font=FONT_SANS_BOLD,
        ),
    )
    value_p = Paragraph(
        f"<font size='28' color='#0F1C2E'><b>{format_bps_as_pct(score_bps, decimals=0)}</b></font>",
        _ar_paragraph_style(styles["body"], color=COLOR_INK),
    )
    card = Table([[label_p], [value_p]])
    card.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (0, 0), 10),
        ("BOTTOMPADDING", (0, 0), (0, 0), 2),
        ("TOPPADDING", (0, 1), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 10),
        ("BACKGROUND", (0, 0), (-1, -1), COLOR_CANVAS_SUBTLE),
        ("LINEBEFORE", (0, 0), (0, -1), 2.5, COLOR_ACCENT),
    ]))
    return card


def _goals_table(goals: list[dict], styles: dict) -> Table:
    """Sprint U-72 (2026-06-06): Goal-Achievability-Tabelle mit 7 Spalten
    (Ziel/Typ/Hartheit/Ziel-Datum/Zielwert/Status/Wahrscheinlichkeit).

    Pre-U-72 hatte die Tabelle nur 5 Spalten (Ziel/Typ/Zielwert/Status/
    Wahrscheinlichkeit) — Hartheit (Hart/Primär/Opportunistisch) und
    Ziel-Datum fehlten obwohl beide im goal_achievability_json
    aus Stochastic-Optimizer verfuegbar sind und FINMA-relevant sind.
    """
    page_width, _ = PAGE_SIZE
    inner_width = page_width - MARGIN_LEFT - MARGIN_RIGHT
    col_label = inner_width * 0.24
    col_type = inner_width * 0.12
    col_hardness = inner_width * 0.14
    col_target_date = inner_width * 0.12
    col_target = inner_width * 0.14
    col_status = inner_width * 0.13
    col_prob = inner_width - col_label - col_type - col_hardness - col_target_date - col_target - col_status

    header = [
        _th("Ziel", styles), _th("Typ", styles),
        _th("Hartheit", styles), _th("Ziel-Datum", styles),
        _th("Zielwert", styles), _th("Status", styles),
        _th("Wahrscheinlichkeit", styles),
    ]
    rows = [header]
    for g in goals:
        label = _safe_string(g.get("label"))
        goal_type = _safe_string(g.get("goal_type"))
        hardness = _safe_string(g.get("hardness")) or "—"
        target_date = _safe_string(g.get("target_date")) or "—"
        target = format_chf_rappen(g.get("target_amount_rappen"))
        status = str(g.get("status") or "data_pending").lower()
        prob = format_bps_as_pct(g.get("probability_bps"))
        rows.append([
            Paragraph(_escape(label), _ar_paragraph_style(
                styles["caption"], color=COLOR_INK, font=FONT_SANS_BOLD,
            )),
            Paragraph(_escape(goal_type), styles["caption"]),
            Paragraph(_escape(hardness), styles["caption"]),
            Paragraph(_escape(target_date), styles["caption_mono"]),
            Paragraph(_escape(target), styles["caption"]),
            _goal_status_pill(status, styles),
            Paragraph(_escape(prob), _ar_paragraph_style(
                styles["caption_mono"], color=COLOR_INK,
            )),
        ])
    table = Table(rows, colWidths=[
        col_label, col_type, col_hardness, col_target_date,
        col_target, col_status, col_prob,
    ])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, 0), 0.4, COLOR_RULE),
        ("LINEBELOW", (0, 1), (-1, -1), 0.2, COLOR_RULE),
        ("ALIGN", (6, 0), (6, -1), "RIGHT"),  # Wahrscheinlichkeit rechts
    ]))
    return table


def _th(text: str, styles: dict) -> Paragraph:
    return Paragraph(
        _escape(text),
        _ar_paragraph_style(
            styles["micro"], color=COLOR_INK_SUBTLE, font=FONT_SANS_BOLD,
        ),
    )


def _goal_status_pill(status: str, styles: dict):
    from reportlab.lib.colors import HexColor

    label, fill_hex, text_hex = _GOAL_STATUS_PILL.get(
        status, _GOAL_STATUS_PILL["data_pending"]
    )
    pill = Table(
        [[Paragraph(
            _escape(label),
            _ar_paragraph_style(
                styles["micro"], color=HexColor(text_hex), font=FONT_SANS_BOLD,
            ),
        )]],
        colWidths=[None],
    )
    pill.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HexColor(fill_hex)),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return pill


# ---------------------------------------------------------------------------
# Sektion 12 — Risikoprofilierung
# ---------------------------------------------------------------------------

def _build_risikoprofil_flowables(rp: dict, styles: dict) -> list[Any]:
    """Risikoprofil-Box (final_profile + 3 Scores) + Override-Hinweis +
    Fragen-Liste."""
    out: list[Any] = []
    out.append(Paragraph("Sektion 12", styles["kicker"]))
    out.append(Paragraph("Risikoprofilierung", styles["h1"]))
    out.append(Spacer(1, 4 * mm))
    out.append(_hr())
    out.append(Spacer(1, 5 * mm))

    profile_label = _safe_string(rp.get("final_profile"))
    final_score = rp.get("final_score_x10")
    capacity = rp.get("risk_capacity_score_x10")
    willingness = rp.get("risk_willingness_score_x10")
    risky_bps = rp.get("risky_fraction_bps")
    is_overridden = bool(rp.get("is_overridden"))
    override_reason = str(rp.get("override_reason") or "").strip()

    out.append(_risikoprofil_summary(
        profile_label, final_score, risky_bps, styles,
    ))
    out.append(Spacer(1, 4 * mm))

    out.append(_risikoprofil_scores_block(capacity, willingness, styles))

    if is_overridden:
        out.append(Spacer(1, 3 * mm))
        text = (
            "<b>Manuelle Übersteuerung:</b> "
            + (_escape(override_reason) if override_reason else "ohne Begründung")
        )
        out.append(Paragraph(
            text,
            _ar_paragraph_style(styles["caption"], color=COLOR_STATUS_NEUTRAL),
        ))

    questions = rp.get("questions") or []
    if questions:
        out.append(Spacer(1, 5 * mm))
        out.append(Paragraph("Fragen der Risikoprofilierung", styles["h2"]))
        out.append(_risikoprofil_questions_table(questions, styles))
    return out


def _risikoprofil_summary(
    profile_label: str, final_score, risky_bps, styles: dict,
) -> Table:
    """Drei-Spalten-Box: Profil-Name | Score x/100 | Risikobudget."""
    page_width, _ = PAGE_SIZE
    inner_width = page_width - MARGIN_LEFT - MARGIN_RIGHT

    def _cell(label: str, value: str) -> Table:
        label_p = Paragraph(
            _escape(label.upper()),
            _ar_paragraph_style(
                styles["micro"], color=COLOR_INK_SUBTLE, font=FONT_SANS_BOLD,
            ),
        )
        value_p = Paragraph(
            _escape(value),
            _ar_paragraph_style(
                styles["body"], color=COLOR_INK, font=FONT_SANS_BOLD, size=14,
            ),
        )
        inner = Table([[label_p], [value_p]])
        inner.setStyle(TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
        ]))
        return inner

    score_text = (
        f"{int(final_score)} / 100" if isinstance(final_score, int) and final_score > 0
        else "—"
    )
    risky_text = format_bps_as_pct(risky_bps)

    cells = [
        _cell("Profil", profile_label),
        _cell("Score", score_text),
        _cell("Risikobudget", risky_text),
    ]
    box = Table([cells], colWidths=[inner_width / 3] * 3)
    box.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, -1), COLOR_CANVAS_SUBTLE),
        ("LINEBEFORE", (0, 0), (0, -1), 2.5, COLOR_ACCENT),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    return box


def _risikoprofil_scores_block(capacity, willingness, styles: dict) -> Table:
    """Score-Bars Risk-Capacity und Risk-Willingness."""
    page_width, _ = PAGE_SIZE
    inner_width = page_width - MARGIN_LEFT - MARGIN_RIGHT

    def _score_row(label: str, score) -> Table:
        try:
            normalized = int(score or 0)
        except (TypeError, ValueError):
            normalized = 0
        score_text = f"{normalized} / 100" if normalized > 0 else "—"
        label_p = Paragraph(
            _escape(label),
            _ar_paragraph_style(
                styles["caption"], color=COLOR_INK, font=FONT_SANS_BOLD,
            ),
        )
        value_p = Paragraph(
            _escape(score_text),
            _ar_paragraph_style(
                styles["caption_mono"], color=COLOR_INK_MUTED,
            ),
        )
        # mini-Bar als drawing
        from reportlab.graphics.shapes import Drawing, Rect

        bar_width = inner_width * 0.45
        track = Drawing(bar_width, 7)
        track.add(Rect(
            0, 0, bar_width, 4,
            fillColor=COLOR_CANVAS_SUBTLE, strokeColor=None,
        ))
        track.add(Rect(
            0, 0, max(0, min(100, normalized)) / 100 * bar_width, 4,
            fillColor=COLOR_ACCENT, strokeColor=None,
        ))
        row = Table(
            [[label_p, track, value_p]],
            colWidths=[inner_width * 0.30, bar_width, inner_width * 0.20],
        )
        row.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("ALIGN", (2, 0), (2, -1), "RIGHT"),
        ]))
        return row

    box = Table(
        [[_score_row("Risikofähigkeit", capacity)],
         [_score_row("Risikobereitschaft", willingness)]],
        colWidths=[inner_width],
    )
    box.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("LINEBELOW", (0, 0), (-1, -2), 0.2, COLOR_RULE),
    ]))
    return box


def _risikoprofil_questions_table(questions: list[dict], styles: dict) -> Table:
    page_width, _ = PAGE_SIZE
    inner_width = page_width - MARGIN_LEFT - MARGIN_RIGHT
    col_q = inner_width * 0.78
    col_p = inner_width - col_q

    rows = [[_th("Frage", styles), _th("Punkte", styles)]]
    for q in questions:
        rows.append([
            Paragraph(_escape(str(q.get("frage") or "—")), styles["caption"]),
            Paragraph(
                format_integer(q.get("points")),
                _ar_paragraph_style(
                    styles["caption_mono"], color=COLOR_INK_MUTED,
                ),
            ),
        ])
    table = Table(rows, colWidths=[col_q, col_p])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.4, COLOR_RULE),
        ("LINEBELOW", (0, 1), (-1, -1), 0.2, COLOR_RULE),
    ]))
    return table


# ---------------------------------------------------------------------------
# Sektion 13 — Building Blocks / iSAA
# ---------------------------------------------------------------------------

def _build_building_blocks_flowables(bb: dict, styles: dict) -> list[Any]:
    """5 Building Blocks (Target + Band) + Constraints + Methodologie-Text."""
    out: list[Any] = []
    out.append(Paragraph("Sektion 13", styles["kicker"]))
    out.append(Paragraph("Building Blocks", styles["h1"]))
    out.append(Spacer(1, 4 * mm))
    out.append(_hr())
    out.append(Spacer(1, 5 * mm))

    blocks = bb.get("blocks") or []
    if blocks:
        out.append(_building_blocks_table(blocks, styles))
    else:
        out.append(Paragraph(
            "<i>Keine Building Blocks erfasst.</i>",
            styles["caption"],
        ))

    methodologie = str(bb.get("methodologie") or "").strip()
    if methodologie:
        out.append(Spacer(1, 5 * mm))
        out.append(_editorial_note("Methodologie", methodologie, styles))

    constraints = bb.get("constraints") or []
    if constraints:
        out.append(Spacer(1, 5 * mm))
        out.append(Paragraph("Constraints", styles["h2"]))
        out.append(_constraints_table(constraints, styles))
    return out


def _building_blocks_table(blocks: list[dict], styles: dict) -> Table:
    page_width, _ = PAGE_SIZE
    inner_width = page_width - MARGIN_LEFT - MARGIN_RIGHT
    col_label = inner_width * 0.30
    col_target = inner_width * 0.20
    col_band = inner_width - col_label - col_target

    rows = [[_th("Anlageklasse", styles), _th("Target", styles), _th("Band", styles)]]
    for b in blocks:
        label = _safe_string(b.get("label"))
        target = format_bps_as_pct(b.get("target_bps"))
        band_min = b.get("band_min_bps")
        band_max = b.get("band_max_bps")
        if band_min is not None and band_max is not None:
            band_text = (
                f"{format_bps_as_pct(band_min)} – {format_bps_as_pct(band_max)}"
            )
        else:
            band_text = "—"
        rows.append([
            Paragraph(_escape(label), _ar_paragraph_style(
                styles["caption"], color=COLOR_INK, font=FONT_SANS_BOLD,
            )),
            Paragraph(_escape(target), _ar_paragraph_style(
                styles["caption_mono"], color=COLOR_INK,
            )),
            Paragraph(_escape(band_text), _ar_paragraph_style(
                styles["caption_mono"], color=COLOR_INK_MUTED,
            )),
        ])
    table = Table(rows, colWidths=[col_label, col_target, col_band])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, 0), 0.4, COLOR_RULE),
        ("LINEBELOW", (0, 1), (-1, -1), 0.2, COLOR_RULE),
    ]))
    return table


def _constraints_table(constraints: list[dict], styles: dict) -> Table:
    page_width, _ = PAGE_SIZE
    inner_width = page_width - MARGIN_LEFT - MARGIN_RIGHT
    col_label = inner_width * 0.30
    col_value = inner_width * 0.15
    col_desc = inner_width - col_label - col_value

    rows = [[_th("Constraint", styles), _th("Wert", styles), _th("Beschreibung", styles)]]
    for c in constraints:
        rows.append([
            Paragraph(
                _escape(str(c.get("label") or "—")),
                _ar_paragraph_style(
                    styles["caption"], color=COLOR_INK, font=FONT_SANS_BOLD,
                ),
            ),
            Paragraph(
                format_bps_as_pct(c.get("value_bps")),
                _ar_paragraph_style(
                    styles["caption_mono"], color=COLOR_INK,
                ),
            ),
            Paragraph(
                _escape(str(c.get("beschreibung") or "")),
                styles["caption"],
            ),
        ])
    table = Table(rows, colWidths=[col_label, col_value, col_desc])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, 0), 0.4, COLOR_RULE),
        ("LINEBELOW", (0, 1), (-1, -1), 0.2, COLOR_RULE),
    ]))
    return table


# ---------------------------------------------------------------------------
# Sektion 14 — Statement aus dem Portfoliomanagement
# ---------------------------------------------------------------------------

def _build_statement_pm_flowables(stmt: dict, styles: dict) -> list[Any]:
    """7 Investmentgrundsätze als editoriale Liste — Titel + Body."""
    out: list[Any] = []
    out.append(Paragraph("Sektion 14", styles["kicker"]))
    out.append(Paragraph("Statement aus dem Portfoliomanagement", styles["h1"]))
    out.append(Spacer(1, 4 * mm))
    out.append(_hr())
    out.append(Spacer(1, 5 * mm))

    principles = stmt.get("principles") or []
    if not principles:
        out.append(Paragraph(
            "<i>Keine Investmentgrundsätze erfasst.</i>",
            styles["caption"],
        ))
        return out

    page_width, _ = PAGE_SIZE
    inner_width = page_width - MARGIN_LEFT - MARGIN_RIGHT
    nr_col = 12 * mm
    body_col = inner_width - nr_col

    rows = []
    for idx, p in enumerate(principles, start=1):
        title = _safe_string(p.get("title"))
        body = _safe_string(p.get("body"))
        nr_cell = Paragraph(
            f"<font color='#B39455'>{idx:02d}</font>",
            _ar_paragraph_style(
                styles["caption_mono"], color=COLOR_GOLD, size=FONT_SIZE_CAPTION + 2,
            ),
        )
        body_cell = Table(
            [
                [Paragraph(
                    _escape(title),
                    _ar_paragraph_style(
                        styles["body"], color=COLOR_INK, font=FONT_SANS_BOLD,
                    ),
                )],
                [Paragraph(_escape(body), styles["body_muted"])],
            ],
        )
        body_cell.setStyle(TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (0, 0), 0),
            ("BOTTOMPADDING", (0, 0), (0, 0), 1),
            ("TOPPADDING", (0, 1), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 1), (-1, -1), 0),
        ]))
        rows.append([nr_cell, body_cell])

    table = Table(rows, colWidths=[nr_col, body_col])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LINEBELOW", (0, 0), (-1, -2), 0.2, COLOR_RULE),
    ]))
    out.append(table)
    return out


# ---------------------------------------------------------------------------
# Sektion 15 — Weiteres Vorgehen
# ---------------------------------------------------------------------------

def _build_weiteres_vorgehen_flowables(wv: dict, styles: dict) -> list[Any]:
    """Berater-individuelle Texte aus MandateReportNotes (U-P28 PR B).
    Auto-Default-Platzhalter werden gedimmt-kursiv gerendert.
    """
    out: list[Any] = []
    out.append(Paragraph("Sektion 15", styles["kicker"]))
    out.append(Paragraph("Weiteres Vorgehen", styles["h1"]))
    out.append(Spacer(1, 4 * mm))
    out.append(_hr())
    out.append(Spacer(1, 5 * mm))

    block_opt = str(wv.get("block_optimierungen") or "")
    block_ziel = str(wv.get("block_zielstrategie") or "")
    offene_fragen = wv.get("offene_fragen") or []
    todos = wv.get("todos") or []
    dokumente = wv.get("dokumente") or []
    termin = str(wv.get("naechster_termin") or "").strip()

    page_width, _ = PAGE_SIZE
    inner_width = page_width - MARGIN_LEFT - MARGIN_RIGHT
    col_w = (inner_width - 6 * mm) / 2

    out.append(Table(
        [[
            _vorgehen_block("Optimierungsmassnahmen", block_opt, styles),
            _vorgehen_block("Zielstrategie", block_ziel, styles),
        ]],
        colWidths=[col_w, col_w],
        style=TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ]),
    ))

    out.append(Spacer(1, 6 * mm))

    list_col = (inner_width - 12 * mm) / 3
    out.append(Table(
        [[
            _vorgehen_list("Offene Fragen", offene_fragen, styles),
            _vorgehen_list("To-Dos", todos, styles),
            _vorgehen_list("Dokumente", dokumente, styles),
        ]],
        colWidths=[list_col, list_col, list_col],
        style=TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ]),
    ))

    out.append(Spacer(1, 6 * mm))
    out.append(_hr())
    out.append(Spacer(1, 3 * mm))
    out.append(Paragraph(
        "NÄCHSTER TERMIN",
        _ar_paragraph_style(
            styles["micro"], color=COLOR_INK_SUBTLE, font=FONT_SANS_BOLD,
        ),
    ))
    out.append(Paragraph(
        _escape(termin) if termin else "<i>Noch nicht vereinbart.</i>",
        _ar_paragraph_style(
            styles["body"], color=COLOR_INK if termin else COLOR_INK_SUBTLE,
        ),
    ))
    return out


def _vorgehen_block(title: str, body: str, styles: dict) -> Table:
    """Ein Text-Block: Titel oben, Body unten — gedimmt-kursiv wenn Auto-Default."""
    is_persisted = bool(body) and not body.startswith("(Vom Berater zu ergänzen")
    body_style = _ar_paragraph_style(
        styles["body"] if is_persisted else styles["body_muted"],
        color=COLOR_INK if is_persisted else COLOR_INK_SUBTLE,
    )
    rendered_body = (
        _escape(body) if is_persisted else f"<i>{_escape(body or '—')}</i>"
    )
    inner = Table([
        [Paragraph(
            _escape(title.upper()),
            _ar_paragraph_style(
                styles["micro"], color=COLOR_INK_SUBTLE, font=FONT_SANS_BOLD,
            ),
        )],
        [Paragraph(rendered_body, body_style)],
    ])
    inner.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (0, 0), 10),
        ("BOTTOMPADDING", (0, 0), (0, 0), 4),
        ("TOPPADDING", (0, 1), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 10),
        ("BOX", (0, 0), (-1, -1), 0.3, COLOR_RULE),
    ]))
    return inner


def _vorgehen_list(title: str, items: list[str], styles: dict) -> Table:
    """Eine Liste: Titel oben, bullets unten — leere Liste zeigt Hinweis."""
    if items:
        bullet_paragraphs = [
            Paragraph(
                f"·  {_escape(str(item))}",
                _ar_paragraph_style(styles["caption"], color=COLOR_INK),
            )
            for item in items if str(item).strip()
        ]
    else:
        bullet_paragraphs = [Paragraph(
            "<i>Keine Einträge.</i>",
            _ar_paragraph_style(styles["caption"], color=COLOR_INK_SUBTLE),
        )]

    rows = [
        [Paragraph(
            _escape(title.upper()),
            _ar_paragraph_style(
                styles["micro"], color=COLOR_INK_SUBTLE, font=FONT_SANS_BOLD,
            ),
        )],
    ]
    for p in bullet_paragraphs:
        rows.append([p])

    inner = Table(rows)
    inner.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (0, 0), 10),
        ("BOTTOMPADDING", (0, 0), (0, 0), 4),
        ("TOPPADDING", (0, 1), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 1),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 10),
        ("BOX", (0, 0), (-1, -1), 0.3, COLOR_RULE),
    ]))
    return inner


# ---------------------------------------------------------------------------
# Sektion 16 — Beratungsprotokoll (Sprint U-FINMA-2.3)
# ---------------------------------------------------------------------------

def _build_beratungsprotokoll_flowables(bp: dict, styles: dict) -> list[Any]:
    """FINMA-konforme Beratungsprotokoll-Übersicht im PDF.

    Layout:
    - Header (Sektion 16)
    - Übersicht-Block: aktive Einträge + letzter Termin + Tage-seit
    - Mismatch-Banner wenn `has_active_mismatches` (rot)
    - Retention-Warnung wenn `!retention_audit_ok` (gelb)
    - Letzter Eintrag (wenn vorhanden): Typ, Datum, Channel, Dauer,
      Topics, Risk-Warnings, Status-Pill, Hash-Marker
    - Fallback wenn kein Eintrag erfasst
    """
    out: list[Any] = []
    out.append(Paragraph("Sektion 16", styles["kicker"]))
    out.append(Paragraph("Beratungsprotokoll", styles["h1"]))
    out.append(Spacer(1, 4 * mm))
    out.append(_hr())
    out.append(Spacer(1, 5 * mm))

    total = int(bp.get("total_active") or 0)
    last_review = str(bp.get("last_review_date") or "—")
    days_since = bp.get("days_since_last_review")
    has_mismatches = bool(bp.get("has_active_mismatches"))
    retention_ok = bool(bp.get("retention_audit_ok"))
    mismatches = bp.get("suitability_mismatches") or []
    latest = bp.get("latest_entry")

    out.append(_bp_summary_block(
        total=total,
        last_review=last_review,
        days_since=days_since,
        styles=styles,
    ))
    out.append(Spacer(1, 5 * mm))

    if has_mismatches and mismatches:
        out.append(_bp_mismatch_banner(mismatches, styles))
        out.append(Spacer(1, 4 * mm))

    if not retention_ok:
        out.append(_bp_retention_warning(styles))
        out.append(Spacer(1, 4 * mm))

    if latest:
        out.append(Paragraph("Letzter Eintrag", styles["h2"]))
        out.append(Spacer(1, 2 * mm))
        out.append(_bp_latest_entry_block(latest, styles))
    else:
        out.append(_bp_no_entry_hint(styles))
    return out


def _bp_summary_block(*, total: int, last_review: str, days_since, styles: dict) -> Table:
    """3-Spalten-Box: aktive Einträge · letzter Termin · Tage seit."""
    page_width, _ = PAGE_SIZE
    inner_width = page_width - MARGIN_LEFT - MARGIN_RIGHT
    if isinstance(days_since, (int, float)) and days_since >= 0:
        days_text = "heute" if int(days_since) == 0 else f"vor {int(days_since)} Tagen"
    else:
        days_text = "—"

    def _cell(label: str, value: str) -> Table:
        l = Paragraph(
            _escape(label.upper()),
            _ar_paragraph_style(
                styles["micro"], color=COLOR_INK_SUBTLE, font=FONT_SANS_BOLD,
            ),
        )
        v = Paragraph(
            _escape(value),
            _ar_paragraph_style(
                styles["body"], color=COLOR_INK, font=FONT_SANS_BOLD, size=14,
            ),
        )
        inner = Table([[l], [v]])
        inner.setStyle(TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
        ]))
        return inner

    cells = [
        _cell("Aktive Einträge", str(total)),
        _cell("Letzter Termin", last_review),
        _cell("Letzte Beratung", days_text),
    ]
    box = Table([cells], colWidths=[inner_width / 3] * 3)
    box.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, -1), COLOR_CANVAS_SUBTLE),
        ("LINEBEFORE", (0, 0), (0, -1), 2.5, COLOR_ACCENT),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    return box


def _bp_mismatch_banner(mismatches: list, styles: dict) -> Table:
    """Roter Hinweis-Block: aktive Suitability-Mismatches."""
    from reportlab.lib.colors import HexColor

    text_lines = [
        Paragraph(
            "<b>Aktive Suitability-Hinweise</b>",
            _ar_paragraph_style(
                styles["caption"], color=HexColor("#9E4747"), font=FONT_SANS_BOLD,
            ),
        ),
    ]
    for m in mismatches:
        text_lines.append(Paragraph(
            f"• {_escape(str(m))}",
            _ar_paragraph_style(styles["caption"], color=COLOR_INK),
        ))
    inner = Table([[p] for p in text_lines])
    inner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HexColor("#F0D9D9")),
        ("LINEBEFORE", (0, 0), (0, -1), 2.5, HexColor("#9E4747")),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return inner


def _bp_retention_warning(styles: dict) -> Table:
    """Gelber Warning-Block: Aufbewahrungs-Frist läuft ab."""
    from reportlab.lib.colors import HexColor

    p = Paragraph(
        "<b>Aufbewahrungs-Hinweis:</b> Mindestens ein Beratungsprotokoll-"
        "Eintrag läuft in den nächsten 30 Tagen ab. FIDLEG verlangt eine "
        "10-Jahres-Aufbewahrung — bitte Archiv-Pflicht überprüfen.",
        _ar_paragraph_style(styles["caption"], color=COLOR_INK_MUTED),
    )
    inner = Table([[p]])
    inner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HexColor("#F4EBD5")),
        ("LINEBEFORE", (0, 0), (0, -1), 2.5, HexColor("#B59243")),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return inner


_BP_STATUS_PILL = {
    "Empfohlen":          ("Empfohlen",      "#E9EBEE", "#3B475A"),
    "Beschlossen":        ("Beschlossen",    "#E5EEDF", "#4E6F58"),
    "Umgesetzt":          ("Umgesetzt",      "#D9C79A", "#B39455"),
    "Überarbeitung nötig":("Überarbeitung",  "#F4EBD5", "#B59243"),
    "Abgelehnt":          ("Abgelehnt",      "#F0D9D9", "#9E4747"),
}


def _bp_status_pill(status: str, styles: dict) -> Table:
    from reportlab.lib.colors import HexColor

    label, fill_hex, text_hex = _BP_STATUS_PILL.get(
        status, ("Unbekannt", "#E9EBEE", "#3B475A")
    )
    pill = Table(
        [[Paragraph(
            _escape(label),
            _ar_paragraph_style(
                styles["micro"], color=HexColor(text_hex), font=FONT_SANS_BOLD,
            ),
        )]],
        colWidths=[None],
    )
    pill.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HexColor(fill_hex)),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return pill


def _bp_latest_entry_block(entry: dict, styles: dict) -> Table:
    """Detail-Block: Header (Datum/Typ) + Channel/Dauer + Topics + Warnings + Hash."""
    page_width, _ = PAGE_SIZE
    inner_width = page_width - MARGIN_LEFT - MARGIN_RIGHT

    title = _safe_string(entry.get("title"))
    entry_type = _safe_string(entry.get("entry_type"))
    datetime_iso = str(entry.get("entry_datetime") or entry.get("entry_date") or "")
    pretty_dt = _format_swiss_datetime(datetime_iso)
    duration = entry.get("duration_minutes")
    duration_text = f"{duration} min" if isinstance(duration, (int, float)) else "—"
    channel = _safe_string(entry.get("communication_channel")).capitalize()
    status = str(entry.get("status") or "Empfohlen")
    topics = entry.get("topics") or []
    warnings = entry.get("risk_warnings_given") or []
    version = int(entry.get("version") or 1)
    hash_short = (entry.get("integrity_hash") or "")[:16]
    description = _safe_string(entry.get("description"))

    rows = []

    # Header-Zeile: Titel + Status
    header_cells = [
        Paragraph(
            _escape(title),
            _ar_paragraph_style(styles["body"], color=COLOR_INK, font=FONT_SANS_BOLD),
        ),
        _bp_status_pill(status, styles),
    ]
    rows.append(header_cells)

    # Meta: Typ · Datum · Channel · Dauer
    meta = (
        f"{_escape(entry_type)}  &middot;  {_escape(pretty_dt)}  &middot;  "
        f"{_escape(channel) or '—'}  &middot;  {_escape(duration_text)}  &middot;  "
        f"Version {version}"
    )
    rows.append([
        Paragraph(
            meta,
            _ar_paragraph_style(styles["caption"], color=COLOR_INK_MUTED),
        ),
        Paragraph("", styles["caption"]),
    ])

    # Description
    if description and description != "—":
        rows.append([
            Paragraph(
                _escape(description),
                _ar_paragraph_style(styles["body"], color=COLOR_INK),
            ),
            Paragraph("", styles["caption"]),
        ])

    table = Table(rows, colWidths=[inner_width * 0.78, inner_width * 0.22])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -2), 0.2, COLOR_RULE),
    ]))

    # Topics + Warnings + Hash in separate Block
    out_table = Table(
        [
            [table],
            [_bp_topics_block(topics, warnings, hash_short, styles)],
        ],
        colWidths=[inner_width],
    )
    out_table.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (0, 0), 4),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 0),
        ("BOX", (0, 0), (-1, -1), 0.3, COLOR_RULE),
    ]))
    return out_table


def _bp_topics_block(
    topics: list, warnings: list, hash_short: str, styles: dict,
) -> Table:
    """Topics + Risk-Warnings + Hash-Marker als kompakter Block."""
    page_width, _ = PAGE_SIZE
    inner_width = page_width - MARGIN_LEFT - MARGIN_RIGHT - 10

    rows = []

    if topics:
        rows.append([
            Paragraph(
                "THEMEN",
                _ar_paragraph_style(
                    styles["micro"], color=COLOR_INK_SUBTLE, font=FONT_SANS_BOLD,
                ),
            ),
            Paragraph(
                " · ".join(_escape(str(t)) for t in topics),
                _ar_paragraph_style(styles["caption"], color=COLOR_INK),
            ),
        ])

    if warnings:
        warning_html = "<br/>".join(f"• {_escape(str(w))}" for w in warnings)
        rows.append([
            Paragraph(
                "RISIKO-HINWEISE",
                _ar_paragraph_style(
                    styles["micro"], color=COLOR_INK_SUBTLE, font=FONT_SANS_BOLD,
                ),
            ),
            Paragraph(
                warning_html,
                _ar_paragraph_style(styles["caption"], color=COLOR_INK),
            ),
        ])

    if hash_short:
        rows.append([
            Paragraph(
                "INTEGRITÄT",
                _ar_paragraph_style(
                    styles["micro"], color=COLOR_INK_SUBTLE, font=FONT_SANS_BOLD,
                ),
            ),
            Paragraph(
                f"<font face='{FONT_MONO}'>{_escape(hash_short)}…</font>  "
                "<font color='#4E6F58'><b>verifiziert</b></font>",
                _ar_paragraph_style(styles["caption"], color=COLOR_INK_MUTED),
            ),
        ])

    if not rows:
        return Table([[Paragraph(
            "<i>Keine Themen / Hinweise erfasst.</i>",
            styles["caption"],
        )]])

    inner = Table(rows, colWidths=[inner_width * 0.18, inner_width * 0.82])
    inner.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("BACKGROUND", (0, 0), (-1, -1), COLOR_CANVAS_SUBTLE),
    ]))
    return inner


def _bp_no_entry_hint(styles: dict) -> Table:
    p = Paragraph(
        "<i>Noch kein Beratungsprotokoll für dieses Mandat erfasst. "
        "Bitte beim nächsten Termin einen FIDLEG-konformen Eintrag "
        "anlegen.</i>",
        _ar_paragraph_style(styles["caption"], color=COLOR_INK_SUBTLE),
    )
    inner = Table([[p]])
    inner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), COLOR_CANVAS_SUBTLE),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return inner


# ---------------------------------------------------------------------------
# Sektion 17 — Historische Stress-Szenarien (Sprint U-70)
# ---------------------------------------------------------------------------

def _build_ab_backtest_flowables(ab: dict, styles: dict) -> list[Any]:
    """Sprint U-71 (2026-06-06): A/B-Backtest-Vergleich (Policy A vs B).

    Erwartet die Struktur aus services.backtest_ab.run_ab_backtest():
      - policy_a: dict mit policy_name, weights_bps, expected_return_bps,
        expected_volatility_bps, sharpe_ratio_x100, expected_ter_bps
      - policy_b: dict (selbe Struktur)
      - risk_metrics_diff: delta_* Felder
      - buckets_diff: per-Bucket-Diff
      - stress_diff: list[dict] mit Stress-Szenarien-Vergleich

    Wird stillschweigend ausgelassen wenn payload['ab_backtest'] leer ist.
    """
    out: list[Any] = []
    policy_a = ab.get("policy_a") or {}
    policy_b = ab.get("policy_b") or {}
    if not policy_a and not policy_b:
        # Nicht persistiert -> Sektion ueberspringen (oben gefiltert,
        # hier defensiv).
        return out

    out.append(Paragraph("A/B-Backtest", styles["kicker"]))
    out.append(Paragraph(
        f"Vergleich {_safe_string(policy_a.get('policy_name')) or 'Policy A'} "
        f"vs {_safe_string(policy_b.get('policy_name')) or 'Policy B'}",
        styles["h1"],
    ))
    out.append(Spacer(1, 4 * mm))
    out.append(_hr())
    out.append(Spacer(1, 5 * mm))

    # KPI-Tabelle: Metrik | Policy A | Policy B | Δ
    diff = ab.get("risk_metrics_diff") or {}
    metric_rows = [
        ("Expected-Return (Netto)", "expected_return_bps", format_bps_as_pct, "delta_expected_return_bps"),
        ("Expected-Volatility", "expected_volatility_bps", format_bps_as_pct, "delta_expected_volatility_bps"),
        ("Expected-TER", "expected_ter_bps", format_bps_as_pct, "delta_expected_ter_bps"),
        ("Sharpe-Ratio (x100)", "sharpe_ratio_x100", lambda v: str(int(v) if v is not None else 0), "delta_sharpe_ratio_x100"),
    ]
    header = [
        _th("Metrik", styles), _th("Policy A", styles),
        _th("Policy B", styles), _th("Δ", styles),
    ]
    rows: list[list[Any]] = [header]
    for label, key, fmt, delta_key in metric_rows:
        a_val = policy_a.get(key)
        b_val = policy_b.get(key)
        delta = diff.get(delta_key, (b_val or 0) - (a_val or 0))
        rows.append([
            Paragraph(_escape(label), _ar_paragraph_style(
                styles["caption"], color=COLOR_INK, font=FONT_SANS_BOLD,
            )),
            Paragraph(_escape(fmt(a_val)), styles["caption_mono"]),
            Paragraph(_escape(fmt(b_val)), styles["caption_mono"]),
            Paragraph(
                _escape(fmt(delta)),
                _ar_paragraph_style(
                    styles["caption_mono"],
                    color=COLOR_INK if int(delta or 0) >= 0 else "#B91C1C",
                ),
            ),
        ])

    page_width, _ = PAGE_SIZE
    inner_width = page_width - MARGIN_LEFT - MARGIN_RIGHT
    table = Table(rows, colWidths=[
        inner_width * 0.40,
        inner_width * 0.20,
        inner_width * 0.20,
        inner_width * 0.20,
    ])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, 0), 0.4, COLOR_RULE),
        ("LINEBELOW", (0, 1), (-1, -1), 0.2, COLOR_RULE),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
    ]))
    out.append(table)

    # Methoden-Hinweis
    out.append(Spacer(1, 6 * mm))
    out.append(Paragraph(
        "<i>Methode: forward-looking CMA-basierter Vergleich der "
        "House-Matrix-Allokationen. Δ &gt; 0 bedeutet bessere Eigenschaft "
        "fuer Policy B vs Policy A.</i>",
        _ar_paragraph_style(styles["caption"], color=COLOR_INK_SUBTLE),
    ))
    return out


def _build_stress_replay_flowables(sr: dict, styles: dict) -> list[Any]:
    """Stress-Replay-Tabelle im Advisory-Report-PDF."""
    out: list[Any] = []
    out.append(Paragraph("Sektion 17", styles["kicker"]))
    out.append(Paragraph("Historische Stress-Szenarien", styles["h1"]))
    out.append(Spacer(1, 4 * mm))
    out.append(_hr())
    out.append(Spacer(1, 5 * mm))

    note = str(sr.get("note") or "")
    scenarios = list(sr.get("scenarios") or [])
    if sr.get("data_pending") or not scenarios:
        out.append(_editorial_note(
            "Stress-Replay",
            note or "Stress-Replay aktuell nicht verfügbar.",
            styles,
        ))
        return out

    out.append(Paragraph(
        "Die historischen Stress-Szenarien wenden definierte Marktphasen "
        "auf die aktuelle Zielallokation an. Die Auswertung ist eine "
        "Szenarioanalyse und kein Renditeversprechen.",
        _ar_paragraph_style(styles["caption"], color=COLOR_INK_MUTED),
    ))
    out.append(Spacer(1, 5 * mm))
    out.append(_stress_replay_table(scenarios, styles))
    if note:
        out.append(Spacer(1, 5 * mm))
        out.append(Paragraph(
            _escape(note),
            _ar_paragraph_style(styles["micro"], color=COLOR_INK_SUBTLE),
        ))
    return out


def _stress_replay_table(scenarios: list[dict], styles: dict) -> Table:
    page_width, _ = PAGE_SIZE
    inner_width = page_width - MARGIN_LEFT - MARGIN_RIGHT
    col_scenario = inner_width * 0.30
    col_return = inner_width * 0.14
    col_drawdown = inner_width * 0.25
    col_recovery = inner_width * 0.14
    col_period = inner_width - col_scenario - col_return - col_drawdown - col_recovery

    max_drawdown = max(
        abs(int(s.get("max_drawdown_bps") or 0)) for s in scenarios
    ) or 1
    rows = [[
        _th("Szenario", styles),
        _th("Return", styles),
        _th("Max-Drawdown", styles),
        _th("Recovery", styles),
        _th("Zeitraum", styles),
    ]]
    for scenario in scenarios:
        return_bps = int(scenario.get("cumulative_return_bps") or 0)
        drawdown_bps = int(scenario.get("max_drawdown_bps") or 0)
        recovery = scenario.get("recovery_months")
        recovery_text = "—" if recovery is None else f"{int(recovery)} Mt."
        return_color = COLOR_STATUS_GRUEN if return_bps >= 0 else COLOR_STATUS_ROT
        rows.append([
            Paragraph(
                _escape(_safe_string(scenario.get("label"))),
                _ar_paragraph_style(
                    styles["caption"], color=COLOR_INK, font=FONT_SANS_BOLD,
                ),
            ),
            Paragraph(
                _escape(format_bps_signed_pct(return_bps)),
                _ar_paragraph_style(
                    styles["caption_mono"], color=return_color, font=FONT_MONO,
                ),
            ),
            _stress_drawdown_cell(drawdown_bps, max_drawdown, styles),
            Paragraph(_escape(recovery_text), styles["caption_mono"]),
            Paragraph(
                _escape(_safe_string(scenario.get("period"))),
                styles["caption"],
            ),
        ])

    table = Table(
        rows,
        colWidths=[col_scenario, col_return, col_drawdown, col_recovery, col_period],
    )
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, 0), 0.4, COLOR_RULE),
        ("LINEBELOW", (0, 1), (-1, -1), 0.2, COLOR_RULE),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
    ]))
    return table


def _stress_drawdown_cell(drawdown_bps: int, max_drawdown_bps: int, styles: dict) -> Table:
    from reportlab.graphics.shapes import Drawing, Rect

    value = abs(int(drawdown_bps or 0))
    max_value = max(abs(int(max_drawdown_bps or 0)), 1)
    bar_width = 48 * mm
    bar_height = 4.5 * mm
    filled = bar_width * min(value / max_value, 1.0)

    drawing = Drawing(bar_width, bar_height)
    drawing.add(Rect(0, 0, bar_width, bar_height, fillColor=COLOR_CANVAS_SUBTLE, strokeColor=None))
    drawing.add(Rect(0, 0, filled, bar_height, fillColor=COLOR_STATUS_ROT, strokeColor=None))
    label = Paragraph(
        _escape(f"-{format_bps_as_pct(value)}"),
        _ar_paragraph_style(styles["caption_mono"], color=COLOR_INK),
    )
    table = Table([[label, drawing]], colWidths=[24 * mm, bar_width])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return table


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_string(value: Any) -> str:
    """`None`/`""` → `—`. Sonst trimmed str."""
    if value is None:
        return "—"
    text = str(value).strip()
    return text or "—"


def _format_age(age: Any) -> str:
    """`49` → `49 Jahre`. `0`/`None` → `—`."""
    try:
        n = int(age)
    except (TypeError, ValueError):
        return "—"
    if n <= 0:
        return "—"
    return f"{n} Jahre"

def _ar_paragraph_style(
    base,
    *,
    font: str | None = None,
    color=None,
    size: float | None = None,
    leading: float | None = None,
):
    """Erzeugt einen Style mit Overrides auf einem Basisstyle (ohne side-effects)."""
    from reportlab.lib.styles import ParagraphStyle

    return ParagraphStyle(
        f"{base.name}Variant",
        parent=base,
        fontName=font or base.fontName,
        textColor=color or base.textColor,
        fontSize=size or base.fontSize,
        leading=leading or base.leading,
    )


def _hr():
    """Dünne horizontale Trenn-Linie als Flowable."""
    page_width, _ = PAGE_SIZE
    inner_width = page_width - MARGIN_LEFT - MARGIN_RIGHT
    rule = Table([[""]], colWidths=[inner_width], rowHeights=[0.3])
    rule.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), COLOR_RULE),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
    ]))
    return rule


def _format_swiss_date(iso: str) -> str:
    """`2026-05-27` → `27.05.2026`. Fallback: Original-String."""
    if not iso or len(iso) < 10:
        return iso or "—"
    try:
        dt = datetime.fromisoformat(iso[:10])
    except ValueError:
        return iso
    return dt.strftime("%d.%m.%Y")


def _format_two_digits(value: Any) -> str:
    try:
        return f"{int(value):02d}"
    except (TypeError, ValueError):
        return "—"


def _escape(text: str) -> str:
    """ReportLab Paragraph akzeptiert mini-HTML. Wir escapen die Standard-Trio."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
