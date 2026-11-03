"""PDF-Baustein: Retrozessionen je empfohlenem Produkt (Art. 26 FIDLEG).

Audit 2026-11, Paket P1 (Luecke L1). Bewusst ein eigener Baustein neben
``kostenausweis.py`` -- der Kostenausweis ruft ihn nur auf. Daten kommen
ausschliesslich aus ``payload["product_retrocessions"]``
(services/retrocession_disclosure.py); fehlt der Schluessel (Nachweis vor P1
eingefroren oder Ausweis ohne Produktbezug), rendert der Baustein nichts.
"""
from __future__ import annotations

from typing import Any

from reportlab.lib.colors import HexColor
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from services.pdf.components.advisory_palette import (
    COLOR_INK,
    COLOR_INK_MUTED,
    COLOR_INK_SUBTLE,
    COLOR_RULE,
    COLOR_STATUS_GELB,
    COLOR_STATUS_ROT,
    FONT_SANS,
    FONT_SANS_BOLD,
    MARGIN_LEFT,
    MARGIN_RIGHT,
    PAGE_SIZE,
)
from services.pdf.components.swiss_numbers import format_bps_as_pct, format_chf_rappen

TITLE = "Vergütungen von Dritten (Retrozessionen) je Produkt"


def build_retrocession_flowables(
    data: dict[str, Any] | None,
    styles,
    *,
    compact: bool = False,
) -> list[Any]:
    disclosure = (data or {}).get("product_retrocessions")
    if not isinstance(disclosure, dict):
        return []
    lines = [line for line in disclosure.get("lines") or [] if isinstance(line, dict)]
    if not lines:
        return []
    currency = str((data or {}).get("currency") or "CHF").upper().strip() or "CHF"

    rows: list[list[Any]] = [[
        _th("Produkt", styles),
        _th("ISIN", styles),
        _th("Satz p.a.", styles),
        _th("Betrag p.a. (Schätzung)", styles),
        _th("Behandlung", styles),
    ]]
    flagged_rows: list[int] = []
    for index, line in enumerate(lines, start=1):
        status = str(line.get("status") or "unknown")
        if status == "unknown":
            rate_text, amount_text = "unbekannt", "unbekannt"
        elif status == "none":
            rate_text, amount_text = "keine", "—"
        else:
            rate_text = format_bps_as_pct(line.get("rate_bps"), decimals=2)
            amount_text = format_chf_rappen(line.get("estimated_annual_rappen"), currency=currency)
        if status == "unknown" or line.get("requires_resolution"):
            flagged_rows.append(index)
        rows.append([
            Paragraph(_escape(line.get("product_name") or "Produkt"), _style(styles["caption"], color=COLOR_INK)),
            Paragraph(_escape(line.get("isin") or "fehlt"), _style(styles["micro"], color=COLOR_INK_SUBTLE)),
            Paragraph(_escape(rate_text), _style(styles["caption_mono"], color=COLOR_INK)),
            Paragraph(_escape(amount_text), _style(styles["caption_mono"], color=COLOR_INK)),
            Paragraph(_escape(line.get("treatment_label") or "—"), _style(styles["micro"], color=COLOR_INK_MUTED)),
        ])
    width = _inner_width()
    table = Table(
        rows,
        colWidths=[width * 0.30, width * 0.15, width * 0.11, width * 0.16, width * 0.28],
        repeatRows=1,
    )
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_INK),
        ("LINEBELOW", (0, 1), (-1, -1), 0.3, COLOR_RULE),
        ("ALIGN", (2, 1), (3, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 3 if compact else 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3 if compact else 5),
    ]
    for row_index in flagged_rows:
        line = lines[row_index - 1]
        color = COLOR_STATUS_ROT if line.get("requires_resolution") else COLOR_STATUS_GELB
        style_cmds.append(("LINEBEFORE", (0, row_index), (0, row_index), 2.5, color))
    table.setStyle(TableStyle(style_cmds))

    note = (
        "Vergütungen, die Ihr Finanzdienstleister von Dritten im Zusammenhang mit den "
        "empfohlenen Produkten erhält, stehen grundsätzlich Ihnen zu. Sie dürfen nur behalten "
        "werden, wenn Sie nach Aufklärung über Art und Umfang ausdrücklich verzichtet "
        "hat (Art. 26 FIDLEG; Art. 400 OR; BGE 132 III 460 und 137 III 393). Die Beträge "
        "sind Teil der Produktkosten (TER) und nicht zusätzlich im Total enthalten. "
        "«unbekannt» heisst: der Satz ist nicht erfasst; das Produkt gilt nicht als "
        "retrozessionsfrei."
    )
    return [
        Spacer(1, (2 if compact else 4) * mm),
        Paragraph(
            _escape(TITLE.upper()),
            _style(styles["micro"], font=FONT_SANS_BOLD, color=COLOR_INK_SUBTLE),
        ),
        Spacer(1, 1.5 * mm),
        table,
        Spacer(1, 1.5 * mm),
        Paragraph(_escape(note), _style(styles["micro"], color=COLOR_INK_MUTED)),
    ]


def _th(text: str, styles) -> Paragraph:
    return Paragraph(_escape(text), _style(styles["micro"], font=FONT_SANS_BOLD, color=HexColor("#FFFFFF")))


def _inner_width() -> float:
    page_width, _ = PAGE_SIZE
    return page_width - MARGIN_LEFT - MARGIN_RIGHT


def _style(base: ParagraphStyle, *, font: str | None = None, color=None) -> ParagraphStyle:
    return ParagraphStyle(
        f"{base.name}Retrocession{font or ''}",
        parent=base,
        fontName=font or base.fontName or FONT_SANS,
        textColor=color or base.textColor,
        spaceBefore=0,
        spaceAfter=0,
    )


def _escape(value: Any) -> str:
    return (
        str(value if value is not None else "—")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
