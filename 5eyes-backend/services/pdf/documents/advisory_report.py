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
    COLOR_GOLD,
    COLOR_INK,
    COLOR_INK_MUTED,
    COLOR_INK_SUBTLE,
    COLOR_RULE,
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
# Helpers
# ---------------------------------------------------------------------------

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
