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
from services.advisory_report import compute_advisory_report
from services.pdf.components.advisory_page_chrome import (
    _format_swiss_datetime,
    make_advisory_page_chrome,
)
from services.pdf.components.advisory_palette import (
    COLOR_ACCENT,
    COLOR_CANVAS_SUBTLE,
    COLOR_GOLD,
    COLOR_INK,
    COLOR_INK_MUTED,
    COLOR_INK_SUBTLE,
    COLOR_RULE,
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
    format_chf_rappen,
    format_integer,
)


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
    return render_advisory_report_pdf_from_payload(payload)


def render_advisory_report_pdf_from_payload(payload: dict[str, Any]) -> bytes:
    """Pure PDF-Render aus einem bereits berechneten Aggregator-Payload.

    Wird vor allem für Tests genutzt — der Aggregator selbst kostet DB-
    Setup-Zeit, der reine Render-Pfad kann mit einem statischen Payload
    schnell verifiziert werden.
    """
    buffer = BytesIO()

    cover = payload.get("cover") or {}
    mandate_number = str(cover.get("mandate_number") or "—")
    generated_at = str(payload.get("generated_at") or "")
    client_name = str(cover.get("client_name") or "—")

    doc = SimpleDocTemplate(
        buffer,
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

    styles = make_advisory_styles()
    flowables: list[Any] = []
    flowables.extend(_build_cover_flowables(cover, styles))
    flowables.append(PageBreak())
    flowables.extend(_build_disclaimer_flowables(payload.get("disclaimer") or {}, styles))
    flowables.append(PageBreak())
    flowables.extend(_build_toc_flowables(payload.get("inhaltsverzeichnis") or {}, styles))
    flowables.append(PageBreak())
    flowables.extend(_build_ausgangslage_flowables(payload.get("ausgangslage") or {}, styles))
    flowables.append(PageBreak())
    flowables.extend(_build_positionen_flowables(payload.get("positionen") or {}, styles))

    chrome = make_advisory_page_chrome(
        mandate_number=mandate_number,
        generated_at_iso=generated_at,
    )
    doc.build(flowables, onFirstPage=chrome, onLaterPages=chrome)
    return buffer.getvalue()


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
    nr_col = 14 * mm
    title_col = inner_width - nr_col

    rows = []
    for k in kapitel:
        nr = _format_two_digits(k.get("nr"))
        title = _escape(str(k.get("title") or "—"))
        rows.append([
            Paragraph(
                f"<font face='{FONT_SANS}' size='{FONT_SIZE_MICRO}' color='#6F7A8A'>{nr}</font>",
                styles["caption"],
            ),
            Paragraph(title, _ar_paragraph_style(styles["body"], color=COLOR_INK)),
        ])
    table = Table(rows, colWidths=[nr_col, title_col])
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, -2), 0.2, COLOR_RULE),
    ]))
    out.append(table)
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
