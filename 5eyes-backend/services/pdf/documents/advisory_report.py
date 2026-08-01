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
from services.pdf.components.unterschrift import make_unterschrift_section
from services.pdf.components.table_of_contents import (
    TocCollector,
    TocSectionAnchor,
    make_toc_table,
)
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
from services.pdf.components.goal_classification import classify_goals
from services.pdf.components.mc_paths_chart import build_mc_paths_drawing
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
    *,
    watermark_mode: str = "none",
) -> bytes:
    """PDF-Bytes des Advisory-Reports für ein Mandat.

    Verwendet denselben Aggregator wie das Frontend; das PDF spiegelt
    1:1 dieselben Daten. Inhalt aktuell: Cover + Disclaimer + TOC (PR A).

    Sprint U-91 (2026-06-06): watermark_mode steuert Wasserzeichen-Druck:
      - 'none' (Default): kein Wasserzeichen
      - 'entwurf': rotes diagonales 'ENTWURF' fuer Vor-Druck-Review
      - 'vertraulich': graues 'VERTRAULICH'-Marker am Seitenrand
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
    # WP4 (2026-07-31): Provisorik-Gate. Fuer CH (jurisdiction in (None, "CH"))
    # liefert der Resolver IMMER None -- unveraendertes Verhalten, kein neuer
    # Key im Payload, bestehende Tests bleiben gruen. Fuer Nicht-CH-Mandate
    # ohne IC-freigegebene CapitalMarketAssumption wird ein sichtbares
    # Warnbanner auf dem Cover platziert (Variante (b): Berater darf intern
    # weiterarbeiten, aber die Dokument-Qualitaet ist fuer den Endkunden nie
    # stillschweigend verschleiert, siehe Constraint 3).
    provisional_notice = _resolve_advisory_report_provisional_notice(db, mandate)
    if provisional_notice is not None:
        payload["provisional_notice"] = provisional_notice
    return render_advisory_report_pdf_from_payload(payload, watermark_mode=watermark_mode)


def _resolve_advisory_report_provisional_notice(
    db: Session, mandate: Mandate,
) -> dict[str, Any] | None:
    """WP4: liefert None fuer CH ODER eine bereits IC-freigegebene Nicht-CH-CMA.

    Andernfalls ein dict {jurisdiction, cma_status, message}, das im PDF als
    sichtbares "PROVISORISCH -- NICHT IC-FREIGEGEBEN"-Banner erscheint.

    WP-B (2026-08-01): duenner Wrapper um die generalisierte
    `services.pdf.provisional_notice.resolve_pdf_provisional_notice` (dort
    jetzt Single-Source-of-Truth fuer alle 6 CMA-/Allokations-abhaengigen
    PDF-Dokumenttypen, siehe dortige Docstring fuer die vollstaendige
    Erklaerung der Primaer-/Fallback-Quelle). Name/Signatur bewusst
    unveraendert -- `tests/test_provisional_pdf_gate.py` importiert diese
    Funktion direkt.
    """
    from services.pdf.provisional_notice import resolve_pdf_provisional_notice

    return resolve_pdf_provisional_notice(db, mandate)


def render_advisory_report_pdf_from_payload(
    payload: dict[str, Any], *, watermark_mode: str = "none",
) -> bytes:
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
    # U-13 (2026-06-02): Two-Pass-Render fuer echte Seitenzahlen im TOC.
    # Pass 1 zaehlt Seiten + sammelt Section-Startseiten via TocCollector.
    # Pass 2 rendert mit den realen page-numbers in der TOC-Tabelle.
    # Vorher: single-pass mit AdvisoryNumberedCanvas — TOC zeigte nur Titel.
    _scratch_buf, scratch_doc = _new_doc()
    counter = _PageCounter()
    toc_collector = TocCollector()
    scratch_doc.build(
        _build_all_flowables(payload, styles, toc_collector=toc_collector),
        onFirstPage=counter, onLaterPages=counter,
    )
    total_pages = counter.page_count or 1
    toc_page_numbers = toc_collector.page_numbers_by_title()
    # Roadmap #71/#72: same collector also carries the bookmark key per
    # section, so the Pass-2 TOC table can render real internal hyperlinks
    # (not just page numbers) — see `make_toc_table` / `TocSectionAnchor`.
    toc_section_ids = toc_collector.section_ids_by_title()

    out_buf, out_doc = _new_doc()
    chrome = make_advisory_page_chrome(
        mandate_number=mandate_number,
        generated_at_iso=generated_at,
        total_pages_hint=total_pages,
    )
    out_doc.build(
        _build_all_flowables(
            payload, styles,
            toc_page_numbers=toc_page_numbers,
            toc_section_ids=toc_section_ids,
        ),
        onFirstPage=chrome, onLaterPages=chrome,
    )
    elapsed = time.perf_counter() - started
    logger.info("advisory_report_pdf_render_seconds=%.3f mode=two_pass", elapsed)
    return out_buf.getvalue()


def _build_all_flowables(
    payload: dict[str, Any],
    styles: dict,
    *,
    toc_collector: TocCollector | None = None,
    toc_page_numbers: dict[str, int] | None = None,
    toc_section_ids: dict[str, str] | None = None,
) -> list[Any]:
    """Erzeugt einen *frischen* Flowable-Snapshot — wird zweimal aufgerufen
    (Pass 1 zum Zaehlen + TOC-Sammeln, Pass 2 zum Zeichnen mit echten
    Seitenzahlen). U-13. `toc_section_ids` (Roadmap #71/#72) ist nur in
    Pass 2 gesetzt und macht die TOC-Zeilen zu echten internen Links."""
    # 2026-07-27 (HUD-Konfiguration): compute_advisory_report() entfernt
    # ausgeblendete Top-Level-Keys bereits VOR diesem Payload -- die einzige
    # Ausnahme sind PROTECTED_REPORT_SECTIONS (nie entfernt). Ein fehlender
    # Key bedeutet also eindeutig "vom Berater ausgeblendet" (im
    # unveraenderten Default-Fall sind IMMER alle Keys vorhanden). Jede
    # hideable Sektion wird deshalb komplett uebersprungen (kein PageBreak,
    # kein TOC-Anker) statt nur mit leerem Inhalt gerendert -- sonst waere
    # eine "ausgeblendete" Sektion im PDF trotzdem als fast leere Seite
    # sichtbar. Geschuetzte Sektionen (cover/disclaimer/cost_disclosure/
    # suitability_*/beratungsprotokoll) bleiben bewusst unconditional.
    flowables: list[Any] = []
    flowables.extend(_build_cover_flowables(
        payload.get("cover") or {}, styles,
        provisional_notice=payload.get("provisional_notice"),
    ))
    flowables.append(PageBreak())
    flowables.append(_toc_anchor(toc_collector, "disclaimer", "Rechtliche Hinweise"))
    flowables.extend(_build_disclaimer_flowables(payload.get("disclaimer") or {}, styles))
    flowables.append(PageBreak())
    if "inhaltsverzeichnis" in payload:
        flowables.append(_toc_anchor(toc_collector, "toc", "Inhaltsverzeichnis"))
        flowables.extend(_build_toc_flowables(
            payload.get("inhaltsverzeichnis") or {}, styles,
            page_numbers_by_title=toc_page_numbers,
            section_ids_by_title=toc_section_ids,
        ))
        flowables.append(PageBreak())
    if "ausgangslage" in payload:
        flowables.append(_toc_anchor(toc_collector, "ausgangslage", "Ausgangslage"))
        flowables.extend(_build_ausgangslage_flowables(payload.get("ausgangslage") or {}, styles))
        flowables.append(PageBreak())
    if "positionen" in payload:
        flowables.append(_toc_anchor(toc_collector, "positionen", "Übersicht Ihrer Positionen"))
        flowables.extend(_build_positionen_flowables(payload.get("positionen") or {}, styles))
        flowables.append(PageBreak())
    if "pruefpunkte" in payload:
        flowables.append(_toc_anchor(toc_collector, "pruefpunkte", "Was wir im Depotcheck prüfen"))
        flowables.extend(_build_pruefpunkte_flowables(payload.get("pruefpunkte") or {}, styles))
        flowables.append(PageBreak())
    if "erkenntnisse" in payload:
        flowables.append(_toc_anchor(toc_collector, "erkenntnisse", "Erkenntnisse aus dem Depotcheck"))
        flowables.extend(_build_erkenntnisse_flowables(payload.get("erkenntnisse") or {}, styles))
        flowables.append(PageBreak())
    if "asset_allocation" in payload:
        flowables.append(_toc_anchor(toc_collector, "asset_allocation", "Asset Allocation"))
        flowables.extend(_build_asset_allocation_flowables(payload.get("asset_allocation") or {}, styles))
        flowables.append(PageBreak())
    if "risikowaehrungen" in payload:
        flowables.append(_toc_anchor(toc_collector, "risikowaehrungen", "Risikowährungen"))
        flowables.extend(_build_risikowaehrungen_flowables(payload.get("risikowaehrungen") or {}, styles))
        flowables.append(PageBreak())
    if "branchen" in payload:
        flowables.append(_toc_anchor(toc_collector, "branchen", "Diversifikation Branchen"))
        flowables.extend(_build_branchen_flowables(payload.get("branchen") or {}, styles))
        flowables.append(PageBreak())
    if "goal_based_investing" in payload:
        flowables.append(_toc_anchor(toc_collector, "goal_based_investing", "Zielbasierte Optimierung"))
        flowables.extend(_build_goals_flowables(payload.get("goal_based_investing") or {}, styles))
        flowables.append(PageBreak())
    if "risikoprofilierung" in payload:
        flowables.append(_toc_anchor(toc_collector, "risikoprofilierung", "Risikoprofilierung"))
        flowables.extend(_build_risikoprofil_flowables(payload.get("risikoprofilierung") or {}, styles))
        flowables.append(PageBreak())
    if "building_blocks" in payload:
        flowables.append(_toc_anchor(toc_collector, "building_blocks", "Building Blocks / iSAA"))
        flowables.extend(_build_building_blocks_flowables(payload.get("building_blocks") or {}, styles))
        flowables.append(PageBreak())
    if "statement_pm" in payload:
        flowables.append(_toc_anchor(toc_collector, "statement_pm", "Statement aus dem Portfoliomanagement"))
        flowables.extend(_build_statement_pm_flowables(payload.get("statement_pm") or {}, styles))
        flowables.append(PageBreak())
    if "weiteres_vorgehen" in payload:
        flowables.append(_toc_anchor(toc_collector, "weiteres_vorgehen", "Weiteres Vorgehen"))
        flowables.extend(_build_weiteres_vorgehen_flowables(payload.get("weiteres_vorgehen") or {}, styles))
        flowables.append(PageBreak())
    flowables.append(_toc_anchor(toc_collector, "beratungsprotokoll", "Beratungsprotokoll"))
    flowables.extend(_build_beratungsprotokoll_flowables(payload.get("beratungsprotokoll") or {}, styles))
    flowables.append(PageBreak())
    if "stress_replay" in payload:
        flowables.append(_toc_anchor(toc_collector, "stress_replay", "Historische Stress-Szenarien"))
        flowables.extend(_build_stress_replay_flowables(payload.get("stress_replay") or {}, styles))
        flowables.append(PageBreak())
    # A/B-Backtest (U-71) — pending-State wird vom Renderer selbst behandelt.
    # Bereits vor der HUD-Konfiguration bedingt gerendert (Vorbild fuer alle
    # anderen hideable Sektionen oben).
    ab_bt = payload.get("ab_backtest") or {}
    if ab_bt:
        flowables.extend(_build_ab_backtest_flowables(ab_bt, styles))
        flowables.append(PageBreak())
    # U-FINMA-3 (2026-05-29, re-architektiert 2026-06-09): SuitabilityCheck-
    # Summary fuer Berater-Sicht (per-Mandat, Single-Check). Geschuetzt (FIDLEG).
    flowables.append(_toc_anchor(toc_collector, "suitability_summary", "Eignungspruefung"))
    flowables.extend(_build_suitability_summary_flowables(
        payload.get("suitability_summary") or {}, styles,
    ))
    flowables.append(PageBreak())
    # Kostenausweis vor Compliance-Audit. Geschuetzt (FIDLEG Art. 8/9).
    flowables.extend(build_kostenausweis_flowables(
        payload.get("cost_disclosure") or {},
        styles,
    ))
    flowables.append(PageBreak())
    render_compliance_audit_section(payload, flowables, styles)
    # U-93: Signatur-Block am Bericht-Ende.
    flowables.append(PageBreak())
    flowables.extend(make_unterschrift_section())
    return flowables


def _toc_anchor(
    collector: TocCollector | None,
    section_id: str,
    title: str,
) -> TocSectionAnchor:
    return TocSectionAnchor(collector, section_id, title)


class _PageCounter:
    """Page-Callback ohne Drawing, der die finale Seitenzahl tracked."""

    def __init__(self) -> None:
        self.page_count: int = 0

    def __call__(self, canvas, doc) -> None:
        self.page_count = max(self.page_count, int(doc.page))


# ---------------------------------------------------------------------------
# Sektion 1 — Cover
# ---------------------------------------------------------------------------

def _build_cover_flowables(
    cover: dict,
    styles: dict,
    *,
    provisional_notice: dict[str, Any] | None = None,
) -> list[Any]:
    """Editorial Cover-Layout:
    - WP4-Provisorik-Banner (nur Nicht-CH ohne IC-Freigabe, sonst nichts)
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

    # WP4 (2026-07-31): fuer CH ist provisional_notice IMMER None (siehe
    # _resolve_advisory_report_provisional_notice) -- dieser Block ist damit
    # fuer den CH-Bestand ein No-Op, kein zusaetzliches Element im Flowable-
    # Baum, byte-identisches Cover.
    if provisional_notice:
        out.append(_build_provisional_notice_banner(provisional_notice, styles))
        out.append(Spacer(1, 8 * mm))

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


def _build_provisional_notice_banner(notice: dict[str, Any], styles: dict) -> Table:
    """WP4 (2026-07-31): sichtbares Warnbanner fuer Nicht-CH-Berichte ohne
    IC-freigegebene Kapitalmarktannahmen. Wird ausschliesslich vom Cover
    aufgerufen wenn `provisional_notice` gesetzt ist (siehe
    `_resolve_advisory_report_provisional_notice`) -- fuer CH nie."""
    from reportlab.lib.colors import HexColor

    heading = Paragraph(
        _escape("PROVISORISCH — NICHT IC-FREIGEGEBEN"),
        _ar_paragraph_style(
            styles["body"], font=FONT_SANS_BOLD, color=COLOR_STATUS_ROT,
        ),
    )
    message = str(notice.get("message") or "").strip() or (
        "Diese Kapitalmarktannahmen sind noch nicht vom Investment Committee "
        "freigegeben."
    )
    body = Paragraph(
        _escape(message),
        _ar_paragraph_style(styles["caption"], color=COLOR_INK_MUTED),
    )
    banner = Table([[heading], [body]], colWidths=[None])
    banner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HexColor("#F0D9D9")),
        ("BOX", (0, 0), (-1, -1), 0.6, COLOR_STATUS_ROT),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (0, 0), 8),
        ("BOTTOMPADDING", (0, 0), (0, 0), 2),
        ("TOPPADDING", (0, 1), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 8),
    ]))
    return banner


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

def _build_toc_flowables(
    toc: dict,
    styles: dict,
    *,
    page_numbers_by_title: dict[str, int] | None = None,
    section_ids_by_title: dict[str, str] | None = None,
) -> list[Any]:
    """Kapitel mit echten Seitenzahlen aus dem Two-Pass-Collector.

    `section_ids_by_title` (Roadmap #71/#72) macht jede Zeile zusätzlich zu
    einem klickbaren internen Link auf den jeweiligen Sektions-Anker."""
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
    out.append(make_toc_table(
        kapitel,
        styles,
        inner_width=inner_width,
        page_numbers_by_title=page_numbers_by_title,
        section_ids_by_title=section_ids_by_title,
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
    "past":            ("Vergangen",      "#E9EBEE", "#7A8395"),
    "beyond_horizon":  ("Jenseits Horizont","#E9EBEE", "#7A8395"),
    "unknown":         ("Unklar",         "#E9EBEE", "#7A8395"),
}


def _build_goals_flowables(gbi: dict, styles: dict) -> list[Any]:
    """Goals-Tabelle + Achievement-Score-KPI + MC-Chart/-Hinweis."""
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
    mc = gbi.get("monte_carlo_paths") or {}
    mc_classifications = classify_goals(goals, mc)
    chart = build_mc_paths_drawing(mc, goals)
    if chart is not None:
        out.append(chart)
        out.append(Spacer(1, 5 * mm))
    elif mc.get("data_pending"):
        out.append(Paragraph(
            f"<b>Monte-Carlo-Pfade:</b> "
            f"{_escape(str(mc.get('note') or 'in Vorbereitung'))}",
            _ar_paragraph_style(styles["caption"], color=COLOR_INK_MUTED),
        ))
        out.append(Spacer(1, 5 * mm))

    if goals:
        out.append(_goals_table(goals, styles, mc_classifications))
    else:
        out.append(Paragraph(
            "<i>Keine Ziele erfasst.</i>",
            styles["caption"],
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


def _goals_table(
    goals: list[dict],
    styles: dict,
    mc_classifications: list[dict] | None = None,
) -> Table:
    """Goal-Achievability-Tabelle mit 8 Spalten.

    Spalten: Ziel/Typ/Hartheit/Ziel-Datum/Zielwert/Status/MC-Status/
    Wahrscheinlichkeit. U-72 (MC-Status-Spalte) und Stage-9 (Hartheit +
    Ziel-Datum aus Stochastic-Optimizer goal_achievability_json) kombiniert.
    """
    page_width, _ = PAGE_SIZE
    inner_width = page_width - MARGIN_LEFT - MARGIN_RIGHT
    col_label = inner_width * 0.20
    col_type = inner_width * 0.10
    col_hardness = inner_width * 0.11
    col_target_date = inner_width * 0.10
    col_target = inner_width * 0.13
    col_status = inner_width * 0.11
    col_mc_status = inner_width * 0.13
    col_prob = (
        inner_width - col_label - col_type - col_hardness - col_target_date
        - col_target - col_status - col_mc_status
    )

    header = [
        _th("Ziel", styles), _th("Typ", styles),
        _th("Hartheit", styles), _th("Ziel-Datum", styles),
        _th("Zielwert", styles), _th("Status", styles),
        _th("MC-Status", styles),
        _th("Wahrscheinlichkeit", styles),
    ]
    rows = [header]
    mc_by_goal_id = {
        str(c.get("goal_id") or ""): c
        for c in (mc_classifications or [])
        if isinstance(c, dict)
    }
    for g in goals:
        label = _safe_string(g.get("label"))
        goal_type = _safe_string(g.get("goal_type"))
        hardness = _safe_string(g.get("hardness")) or "—"
        target_date = _safe_string(g.get("target_date")) or "—"
        target = format_chf_rappen(g.get("target_amount_rappen"))
        status = str(g.get("status") or "data_pending").lower()
        mc_status = str(
            (mc_by_goal_id.get(str(g.get("goal_id") or "")) or {}).get("status")
            or "unknown"
        ).lower()
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
            _goal_status_pill(mc_status, styles),
            Paragraph(_escape(prob), _ar_paragraph_style(
                styles["caption_mono"], color=COLOR_INK,
            )),
        ])
    table = Table(rows, colWidths=[
        col_label, col_type, col_hardness, col_target_date,
        col_target, col_status, col_mc_status, col_prob,
    ])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, 0), 0.4, COLOR_RULE),
        ("LINEBELOW", (0, 1), (-1, -1), 0.2, COLOR_RULE),
        ("ALIGN", (7, 0), (7, -1), "RIGHT"),  # Wahrscheinlichkeit rechts (Spalte 8)
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
# Sektion 18 — A/B-HouseMatrix-Backtest (Sprint U-71)
# ---------------------------------------------------------------------------

def _build_ab_backtest_flowables(ab: dict, styles: dict) -> list[Any]:
    """Read-only Policy-Vergleich im Advisory-Report-PDF."""
    out: list[Any] = []
    out.append(Paragraph("Sektion 18", styles["kicker"]))
    out.append(Paragraph("Policy-A/B-Vergleich", styles["h1"]))
    out.append(Spacer(1, 4 * mm))
    out.append(_hr())
    out.append(Spacer(1, 5 * mm))

    if ab.get("data_pending"):
        out.append(_editorial_note(
            "A/B-Backtest",
            str(ab.get("note") or "A/B-Backtest aktuell nicht verfügbar."),
            styles,
        ))
        return out

    policy_a = ab.get("policy_a") or {}
    policy_b = ab.get("policy_b") or {}
    out.append(Paragraph(
        "Der Vergleich rechnet zwei House-Matrix-Policies auf demselben "
        "Risikoprofil und derselben Kapitalmarktannahme. Er ist read-only "
        "und isoliert den Policy-Effekt ohne Tilts, Goals oder Reserve-Logik.",
        _ar_paragraph_style(styles["caption"], color=COLOR_INK_MUTED),
    ))
    out.append(Spacer(1, 5 * mm))
    out.append(_ab_metrics_table(policy_a, policy_b, styles))
    out.append(Spacer(1, 6 * mm))
    out.append(_ab_bucket_diff_table(ab.get("buckets_diff") or [], styles))
    stress = list(ab.get("stress_diff") or [])
    if stress:
        out.append(Spacer(1, 6 * mm))
        out.append(Paragraph(
            "Stress-Replay-Differenz",
            _ar_paragraph_style(
                styles["caption"], color=COLOR_INK, font=FONT_SANS_BOLD,
            ),
        ))
        out.append(Spacer(1, 2 * mm))
        out.append(_ab_stress_diff_table(stress, styles))
    for warning in ab.get("warnings") or []:
        out.append(Spacer(1, 4 * mm))
        out.append(_editorial_note("Hinweis", str(warning), styles))
    note = str(ab.get("note") or "")
    if note:
        out.append(Spacer(1, 4 * mm))
        out.append(Paragraph(
            _escape(note),
            _ar_paragraph_style(styles["micro"], color=COLOR_INK_SUBTLE),
        ))
    return out


def _ab_metrics_table(policy_a: dict, policy_b: dict, styles: dict) -> Table:
    rows = [[
        _th("Kennzahl", styles),
        _th(f"A: {_ab_policy_label(policy_a)}", styles),
        _th(f"B: {_ab_policy_label(policy_b)}", styles),
        _th("Delta B-A", styles),
    ]]
    metric_rows = [
        (
            "Erwartete Rendite",
            "expected_return_bps",
            format_bps_as_pct,
            format_bps_signed_pct,
        ),
        (
            "Erwartete Volatilität",
            "expected_volatility_bps",
            format_bps_as_pct,
            format_bps_signed_pct,
        ),
        ("TER", "expected_ter_bps", format_bps_as_pct, format_bps_signed_pct),
        ("Sharpe", "sharpe_ratio_x100", _format_x100, _format_signed_x100),
        (
            "Max. Risky Fraction",
            "max_risky_fraction_bps",
            format_bps_as_pct,
            format_bps_signed_pct,
        ),
    ]
    for label, key, fmt, delta_fmt in metric_rows:
        a = int(policy_a.get(key) or 0)
        b = int(policy_b.get(key) or 0)
        rows.append([
            Paragraph(_escape(label), styles["caption"]),
            Paragraph(_escape(fmt(a)), styles["caption_mono"]),
            Paragraph(_escape(fmt(b)), styles["caption_mono"]),
            Paragraph(_escape(delta_fmt(b - a)), styles["caption_mono"]),
        ])

    page_width, _ = PAGE_SIZE
    inner_width = page_width - MARGIN_LEFT - MARGIN_RIGHT
    table = Table(
        rows,
        colWidths=[inner_width * 0.30, inner_width * 0.24, inner_width * 0.24, inner_width * 0.22],
    )
    table.setStyle(_report_table_style())
    return table


def _ab_bucket_diff_table(rows_in: list[dict], styles: dict) -> Table:
    rows = [[
        _th("Anlageklasse", styles),
        _th("Policy A", styles),
        _th("Policy B", styles),
        _th("Delta B-A", styles),
    ]]
    for item in rows_in:
        delta = int(item.get("delta_bps") or 0)
        rows.append([
            Paragraph(
                _escape(_safe_string(item.get("label"))),
                _ar_paragraph_style(
                    styles["caption"], color=COLOR_INK, font=FONT_SANS_BOLD,
                ),
            ),
            Paragraph(_escape(format_bps_as_pct(item.get("a_bps"))), styles["caption_mono"]),
            Paragraph(_escape(format_bps_as_pct(item.get("b_bps"))), styles["caption_mono"]),
            Paragraph(_escape(format_bps_signed_pct(delta)), styles["caption_mono"]),
        ])

    page_width, _ = PAGE_SIZE
    inner_width = page_width - MARGIN_LEFT - MARGIN_RIGHT
    table = Table(
        rows,
        colWidths=[inner_width * 0.34, inner_width * 0.22, inner_width * 0.22, inner_width * 0.22],
    )
    table.setStyle(_report_table_style())
    return table


def _ab_stress_diff_table(rows_in: list[dict], styles: dict) -> Table:
    rows = [[
        _th("Szenario", styles),
        _th("Return A", styles),
        _th("Return B", styles),
        _th("Delta", styles),
        _th("MaxDD A/B", styles),
    ]]
    for item in rows_in:
        rows.append([
            Paragraph(
                _escape(_safe_string(item.get("label"))),
                _ar_paragraph_style(
                    styles["caption"], color=COLOR_INK, font=FONT_SANS_BOLD,
                ),
            ),
            Paragraph(
                _escape(format_bps_signed_pct(item.get("a_cumulative_return_bps"))),
                styles["caption_mono"],
            ),
            Paragraph(
                _escape(format_bps_signed_pct(item.get("b_cumulative_return_bps"))),
                styles["caption_mono"],
            ),
            Paragraph(
                _escape(format_bps_signed_pct(item.get("delta_cumulative_return_bps"))),
                styles["caption_mono"],
            ),
            Paragraph(
                _escape(
                    f"-{format_bps_as_pct(abs(int(item.get('a_max_drawdown_bps') or 0)))}"
                    f" / -{format_bps_as_pct(abs(int(item.get('b_max_drawdown_bps') or 0)))}"
                ),
                styles["caption_mono"],
            ),
        ])

    page_width, _ = PAGE_SIZE
    inner_width = page_width - MARGIN_LEFT - MARGIN_RIGHT
    table = Table(
        rows,
        colWidths=[inner_width * 0.30, inner_width * 0.16, inner_width * 0.16, inner_width * 0.16, inner_width * 0.22],
    )
    table.setStyle(_report_table_style())
    return table


def _report_table_style() -> TableStyle:
    return TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, 0), 0.4, COLOR_RULE),
        ("LINEBELOW", (0, 1), (-1, -1), 0.2, COLOR_RULE),
    ])


def _ab_policy_label(policy: dict) -> str:
    name = _safe_string(policy.get("policy_name"))
    version = policy.get("version")
    suffix = "aktuell" if policy.get("is_current") else "Vergleich"
    try:
        return f"{name} v{int(version)} ({suffix})"
    except (TypeError, ValueError):
        return f"{name} ({suffix})"


def _format_x100(value: int | float | None) -> str:
    try:
        return f"{float(value or 0) / 100:.2f}"
    except (TypeError, ValueError):
        return "0.00"


def _format_signed_x100(value: int | float | None) -> str:
    try:
        numeric = float(value or 0) / 100
    except (TypeError, ValueError):
        numeric = 0.0
    sign = "+" if numeric > 0 else ""
    return f"{sign}{numeric:.2f}"


# ---------------------------------------------------------------------------
# Sektion 27 — Suitability-Summary (Sprint U-FINMA-3, Roadmap-Punkt 3,
# re-architektiert 2026-06-09 von Sektion 17)
# ---------------------------------------------------------------------------

_SUITABILITY_RESULT_PILL = {
    "passed":     ("Eignung gegeben",       "#E5EEDF", "#4E6F58"),
    "mismatch":   ("Mismatch dokumentiert", "#F0D9D9", "#9E4747"),
    "incomplete": ("Pruefung unvollstaendig","#F4EBD5", "#B59243"),
}

_DUTY_TYPE_LABEL = {
    "suitability":     "Eignungspruefung (Suitability)",
    "appropriateness": "Angemessenheitspruefung (Appropriateness)",
    "informational":   "Informationspruefung",
    "execution_only":  "Execution-only",
}


def _build_suitability_summary_flowables(ss: dict, styles: dict) -> list[Any]:
    """FINMA-Eignungspruefung als eigenstaendige PDF-Sektion.

    Stellt im Bericht sichtbar den juengsten SuitabilityCheck dar:
    Status-Pill (passed/mismatch/incomplete), wer hat wann was geprueft,
    Result-Notes, fehlende Infos, Warnungs-/Bestaetigungs-Spur falls
    Mismatch + Kunde weitergefuehrt, Referenzen, Empty-State.
    """
    out: list[Any] = []
    out.append(Paragraph("Sektion 27", styles["kicker"]))
    out.append(Paragraph("Eignungspruefung", styles["h1"]))
    out.append(Spacer(1, 4 * mm))
    out.append(_hr())
    out.append(Spacer(1, 5 * mm))

    if not ss or not ss.get("has_check"):
        out.append(_ss_empty_state(styles))
        return out

    out.append(_ss_summary_box(ss, styles))
    out.append(Spacer(1, 5 * mm))

    notes = str(ss.get("result_notes") or "").strip()
    if notes:
        out.append(Paragraph("Beurteilung", styles["h2"]))
        out.append(Spacer(1, 2 * mm))
        out.append(Paragraph(
            _escape(notes),
            _ar_paragraph_style(styles["body"], color=COLOR_INK_MUTED),
        ))
        out.append(Spacer(1, 4 * mm))

    missing = ss.get("missing_information") or []
    if missing:
        out.append(_ss_missing_info_block(missing, styles))
        out.append(Spacer(1, 4 * mm))

    if ss.get("client_proceeded_despite"):
        out.append(_ss_override_workflow_block(ss, styles))
        out.append(Spacer(1, 4 * mm))

    refs = ss.get("references") or {}
    if any(refs.values()):
        out.append(Paragraph("Verknuepfte Datensaetze", styles["h2"]))
        out.append(Spacer(1, 2 * mm))
        out.append(_ss_references_table(refs, ss, styles))

    return out


def _ss_summary_box(ss: dict, styles: dict) -> Table:
    """3-Spalten-Box: Status-Pill + Geprueft von + Pflichttyp/Datum."""
    from reportlab.lib.colors import HexColor

    page_width, _ = PAGE_SIZE
    inner_width = page_width - MARGIN_LEFT - MARGIN_RIGHT

    result = str(ss.get("result") or "").strip()
    pill_label, pill_fill, pill_text = _SUITABILITY_RESULT_PILL.get(
        result, ("Status unklar", "#E9EBEE", "#3B475A"),
    )
    pill = Table(
        [[Paragraph(
            _escape(pill_label),
            _ar_paragraph_style(
                styles["micro"], color=HexColor(pill_text), font=FONT_SANS_BOLD,
            ),
        )]],
        colWidths=[None],
    )
    pill.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HexColor(pill_fill)),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))

    def _cell_label(text: str) -> Paragraph:
        return Paragraph(
            _escape(text.upper()),
            _ar_paragraph_style(
                styles["micro"], color=COLOR_INK_SUBTLE, font=FONT_SANS_BOLD,
            ),
        )

    def _cell_value(text: str) -> Paragraph:
        return Paragraph(
            _escape(text),
            _ar_paragraph_style(
                styles["body"], color=COLOR_INK, font=FONT_SANS_BOLD, size=12,
            ),
        )

    advisor_name = str(ss.get("checked_by_name") or "—")
    duty_type = str(ss.get("duty_type") or "")
    duty_label = _DUTY_TYPE_LABEL.get(duty_type, duty_type or "—")
    performed_at = _format_swiss_datetime(str(ss.get("performed_at") or ""))

    pill_col = Table([[_cell_label("Ergebnis")], [pill]])
    pill_col.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (0, 0), 6),
    ]))
    advisor_col = Table(
        [[_cell_label("Geprueft von")], [_cell_value(advisor_name)]],
    )
    advisor_col.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (0, 0), 6),
    ]))
    duty_col = Table([
        [_cell_label("Pflichttyp / Zeitpunkt")],
        [_cell_value(duty_label)],
        [Paragraph(
            _escape(performed_at),
            _ar_paragraph_style(styles["caption"], color=COLOR_INK_MUTED),
        )],
    ])
    duty_col.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (0, -1), 2),
    ]))

    box = Table(
        [[pill_col, advisor_col, duty_col]],
        colWidths=[inner_width / 3] * 3,
    )
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


def _ss_missing_info_block(missing: list, styles: dict) -> Table:
    """Gelber Hinweis-Block: Liste der bei der Pruefung fehlenden Infos."""
    from reportlab.lib.colors import HexColor

    lines: list[Any] = [
        Paragraph(
            "<b>Fehlende Informationen zum Zeitpunkt der Pruefung</b>",
            _ar_paragraph_style(
                styles["caption"], color=HexColor("#B59243"), font=FONT_SANS_BOLD,
            ),
        ),
    ]
    for item in missing:
        lines.append(Paragraph(
            f"• {_escape(str(item))}",
            _ar_paragraph_style(styles["caption"], color=COLOR_INK),
        ))
    inner = Table([[p] for p in lines])
    inner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HexColor("#F4EBD5")),
        ("LINEBEFORE", (0, 0), (0, -1), 2.5, HexColor("#B59243")),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return inner


def _ss_override_workflow_block(ss: dict, styles: dict) -> Table:
    """Roter Audit-Block: Kunde wurde trotz Mismatch weitergefuehrt
    (FIDLEG Art. 12). Zeigt Warnungs-/Bestaetigungs-Spur."""
    from reportlab.lib.colors import HexColor

    warning_at = _format_swiss_datetime(str(ss.get("warning_delivered_at") or ""))
    ack_at = _format_swiss_datetime(str(ss.get("client_acknowledged_at") or ""))
    warning_line = (
        f"Warnung ausgehaendigt am {warning_at}"
        if ss.get("warning_delivered")
        else "Warnung NICHT dokumentiert ausgehaendigt"
    )
    ack_line = (
        f"Kunde hat Hinweis bestaetigt am {ack_at}"
        if ss.get("client_acknowledged")
        else "Kundenbestaetigung NICHT dokumentiert"
    )

    lines: list[Any] = [
        Paragraph(
            "<b>Kunde fuhrt trotz Mismatch fort (FIDLEG Art. 12)</b>",
            _ar_paragraph_style(
                styles["caption"], color=HexColor("#9E4747"), font=FONT_SANS_BOLD,
            ),
        ),
        Paragraph(
            f"• {_escape(warning_line)}",
            _ar_paragraph_style(styles["caption"], color=COLOR_INK),
        ),
        Paragraph(
            f"• {_escape(ack_line)}",
            _ar_paragraph_style(styles["caption"], color=COLOR_INK),
        ),
    ]
    inner = Table([[p] for p in lines])
    inner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HexColor("#F0D9D9")),
        ("LINEBEFORE", (0, 0), (0, -1), 2.5, HexColor("#9E4747")),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return inner


def _ss_references_table(refs: dict, ss: dict, styles: dict) -> Table:
    """Schmale Referenz-Tabelle: Welche Datensaetze haengen am Check?"""
    page_width, _ = PAGE_SIZE
    inner_width = page_width - MARGIN_LEFT - MARGIN_RIGHT

    rows_def: list[tuple[str, str]] = []
    if refs.get("risk_assessment_id"):
        rows_def.append(("Risikoprofil-Assessment", str(refs["risk_assessment_id"])))
    if refs.get("knowledge_assessment_id"):
        rows_def.append(("Kenntnisse-Assessment", str(refs["knowledge_assessment_id"])))
    if refs.get("advisory_log_id"):
        log_id = str(refs["advisory_log_id"])
        if ss.get("linked_log_present"):
            rows_def.append(("Beratungsprotokoll-Eintrag", log_id))
        else:
            rows_def.append((
                "Beratungsprotokoll-Eintrag",
                f"{log_id} (nicht gefunden)",
            ))
    if refs.get("recommendation_run_id"):
        rows_def.append(("Empfehlungs-Run", str(refs["recommendation_run_id"])))
    if refs.get("document_id"):
        rows_def.append(("Beleg-Dokument", str(refs["document_id"])))

    header = [
        Paragraph(
            _escape("Datensatz".upper()),
            _ar_paragraph_style(
                styles["micro"], color=COLOR_INK_SUBTLE, font=FONT_SANS_BOLD,
            ),
        ),
        Paragraph(
            _escape("Referenz".upper()),
            _ar_paragraph_style(
                styles["micro"], color=COLOR_INK_SUBTLE, font=FONT_SANS_BOLD,
            ),
        ),
    ]
    body_rows = [
        [
            Paragraph(
                _escape(label),
                _ar_paragraph_style(styles["caption"], color=COLOR_INK),
            ),
            Paragraph(
                _escape(value),
                _ar_paragraph_style(styles["caption"], color=COLOR_INK_MUTED, font=FONT_MONO),
            ),
        ]
        for label, value in rows_def
    ]
    table = Table(
        [header, *body_rows],
        colWidths=[inner_width * 0.35, inner_width * 0.65],
    )
    table.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, 0), 0.4, COLOR_RULE),
        ("LINEBELOW", (0, 1), (-1, -2), 0.2, COLOR_RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return table


def _ss_empty_state(styles: dict) -> Table:
    """Empty-State wenn kein SuitabilityCheck zum Mandat existiert."""
    page_width, _ = PAGE_SIZE
    inner_width = page_width - MARGIN_LEFT - MARGIN_RIGHT

    title = Paragraph(
        "<b>Noch keine Eignungspruefung dokumentiert</b>",
        _ar_paragraph_style(styles["body"], color=COLOR_INK, font=FONT_SANS_BOLD),
    )
    body = Paragraph(
        _escape(
            "Vor der Umsetzung der Anlagestrategie ist eine FINMA-konforme "
            "Eignungspruefung (Suitability nach FIDLEG) durchzufuehren und "
            "im System zu hinterlegen. Sie erscheint danach an dieser Stelle."
        ),
        _ar_paragraph_style(styles["caption"], color=COLOR_INK_MUTED),
    )
    box = Table([[title], [Spacer(1, 2 * mm)], [body]], colWidths=[inner_width])
    box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), COLOR_CANVAS_SUBTLE),
        ("LINEBEFORE", (0, 0), (0, -1), 2.5, COLOR_STATUS_NEUTRAL),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return box


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
