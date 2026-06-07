"""Visual building blocks for the target-only depot analysis."""
from __future__ import annotations

from collections.abc import Mapping, Sequence

from reportlab.graphics.shapes import Drawing, Line, Rect, String
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Table, TableStyle

from services.pdf.components.header import _esc
from services.pdf.styles import (
    BUCKET_COLORS,
    COLOR_BORDER,
    COLOR_TABLE_HEADER_BG,
    COLOR_TEXT,
    COLOR_TEXT_LIGHT,
    FONT_BOLD,
    FONT_DEFAULT,
    FONT_SIZE_TABLE,
    FONT_SIZE_TABLE_HEADER,
    PAGE_SIZE,
    asset_class_color,
    asset_class_label,
)

BUCKET_ORDER = ("equities", "bonds", "real_estate", "alternatives", "liquidity")


def make_target_allocation_bars(
    allocation_bps: Mapping[str, int],
    bands_bps: Mapping[str, Sequence[int]] | None = None,
    *,
    width_mm: float | None = None,
    row_height_mm: float = 13.0,
) -> Drawing:
    """Horizontal target bars with a quiet min/max range marker."""
    items = [
        (bucket, int(allocation_bps.get(bucket, 0) or 0))
        for bucket in BUCKET_ORDER
        if int(allocation_bps.get(bucket, 0) or 0) > 0
    ]
    page_width, _ = PAGE_SIZE
    width = (width_mm * mm) if width_mm else page_width - 24 * mm
    row_h = max(8.0, float(row_height_mm)) * mm
    height = max(28 * mm, 10 * mm + row_h * max(1, len(items)))
    drawing = Drawing(width, height)
    if not items:
        drawing.add(String(
            width / 2,
            height / 2,
            "Noch keine Zielallokation berechnet.",
            textAnchor="middle",
            fontName=FONT_DEFAULT,
            fontSize=9,
            fillColor=COLOR_TEXT_LIGHT,
        ))
        return drawing

    label_w = 39 * mm
    value_w = 20 * mm
    bar_x = label_w
    bar_w = width - label_w - value_w
    for index, (bucket, bps) in enumerate(items):
        y = height - 12 * mm - index * row_h
        drawing.add(String(
            0,
            y + 2.5,
            asset_class_label(bucket),
            fontName=FONT_BOLD,
            fontSize=8.5,
            fillColor=COLOR_TEXT,
        ))
        drawing.add(Rect(
            bar_x,
            y,
            bar_w,
            5.5 * mm,
            fillColor=colors.HexColor("#eef2f6"),
            strokeColor=None,
        ))
        band = (bands_bps or {}).get(bucket)
        if band and len(band) >= 2:
            low = max(0, min(10000, int(band[0] or 0)))
            high = max(low, min(10000, int(band[1] or 0)))
            low_x = bar_x + bar_w * low / 10000
            high_x = bar_x + bar_w * high / 10000
            drawing.add(Rect(
                low_x,
                y,
                max(1, high_x - low_x),
                5.5 * mm,
                fillColor=colors.HexColor("#dbe4ee"),
                strokeColor=None,
            ))
        drawing.add(Rect(
            bar_x,
            y,
            bar_w * min(10000, max(0, bps)) / 10000,
            5.5 * mm,
            fillColor=asset_class_color(bucket),
            strokeColor=None,
        ))
        drawing.add(String(
            width,
            y + 2.5,
            f"{bps / 100:.1f}%",
            textAnchor="end",
            fontName=FONT_BOLD,
            fontSize=9,
            fillColor=COLOR_TEXT,
        ))
    drawing.add(String(
        bar_x,
        1.5 * mm,
        "Farbiger Balken = Zielquote; heller Bereich = dokumentierte Bandbreite",
        fontName=FONT_DEFAULT,
        fontSize=7,
        fillColor=COLOR_TEXT_LIGHT,
    ))
    return drawing


def make_sub_allocation_table(rows: list[dict], base_currency: str = "CHF") -> Table:
    data = [["Hauptanlageklasse", "Subanlageklasse", "Produkte", "Zielquote", "Zielbetrag"]]
    for item in rows:
        data.append([
            Paragraph(
                f'<font name="{FONT_BOLD}">{_esc(asset_class_label(item.get("asset_class")))}</font>',
                _cell_style(),
            ),
            Paragraph(_esc(item.get("sub_asset_class") or "-"), _cell_style()),
            str(int(item.get("products", 0) or 0)),
            f'{int(item.get("weight_bps", 0) or 0) / 100:.1f}%',
            _format_amount(int(item.get("amount_rappen", 0) or 0), base_currency),
        ])
    if len(data) == 1:
        data.append(["-", "Noch keine Subanlageklassen verfuegbar.", "-", "-", "-"])
    return _styled_table(data, [0.19, 0.36, 0.10, 0.14, 0.21], right_from=2)


def make_exposure_bars(
    exposure_bps: Mapping[str, int],
    *,
    width_mm: float | None = None,
    max_items: int = 12,
    row_height_mm: float = 7.0,
) -> Drawing:
    items = sorted(
        (
            (str(label), int(value or 0))
            for label, value in exposure_bps.items()
            if int(value or 0) > 0
        ),
        key=lambda item: (-item[1], item[0]),
    )[:max_items]
    page_width, _ = PAGE_SIZE
    width = (width_mm * mm) if width_mm else page_width - 24 * mm
    row_h = max(6.5, float(row_height_mm)) * mm
    height = max(25 * mm, 8 * mm + row_h * max(1, len(items)))
    drawing = Drawing(width, height)
    if not items:
        drawing.add(String(
            width / 2,
            height / 2,
            "Keine belastbaren Expositionsdaten vorhanden.",
            textAnchor="middle",
            fontName=FONT_DEFAULT,
            fontSize=9,
            fillColor=COLOR_TEXT_LIGHT,
        ))
        return drawing

    label_w = 48 * mm
    value_w = 18 * mm
    bar_w = width - label_w - value_w
    max_bps = max(value for _, value in items)
    for index, (label, bps) in enumerate(items):
        y = height - 8 * mm - index * row_h
        drawing.add(String(
            0,
            y + 1.5,
            _shorten(label, 33),
            fontName=FONT_DEFAULT,
            fontSize=7.5,
            fillColor=COLOR_TEXT,
        ))
        drawing.add(Rect(
            label_w,
            y,
            bar_w,
            3.8 * mm,
            fillColor=colors.HexColor("#eef2f6"),
            strokeColor=None,
        ))
        drawing.add(Rect(
            label_w,
            y,
            bar_w * bps / max_bps,
            3.8 * mm,
            fillColor=colors.HexColor("#285d70"),
            strokeColor=None,
        ))
        drawing.add(String(
            width,
            y + 1.5,
            f"{bps / 100:.1f}%",
            textAnchor="end",
            fontName=FONT_BOLD,
            fontSize=7.5,
            fillColor=COLOR_TEXT,
        ))
    return drawing


def make_risk_kpis(profile: str | None, metrics: Mapping[str, object]) -> Table:
    values = [
        ("RISIKOPROFIL", profile or "Nicht dokumentiert"),
        ("ERWARTETE RENDITE P.A.", _fmt_bps(metrics.get("expected_return_bps"))),
        ("ERWARTETE VOLATILITAET", _fmt_bps(metrics.get("expected_vol_bps"))),
        ("ANLAGEHORIZONT", f'{int(metrics.get("horizon_years") or 0)} Jahre'),
        ("MAX. DRAWDOWN MODELL", _fmt_negative_bps(metrics.get("max_drawdown_bps"))),
        ("VALUE-AT-RISK 95%", _fmt_negative_bps(metrics.get("var_95_bps"))),
    ]
    width = (PAGE_SIZE[0] - 24 * mm) / 3
    cells = []
    for label, value in values:
        cells.append(Table(
            [[Paragraph(label, _micro_style())], [Paragraph(_esc(value), _metric_style())]],
            colWidths=[width],
        ))
    table = Table([cells[:3], cells[3:]], colWidths=[width] * 3)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ("BOX", (0, 0), (-1, -1), 0.4, COLOR_BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, COLOR_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return table


def make_diversification_heatmap(hhi: Mapping[str, int]) -> Table:
    labels = (
        ("country", "Laender"),
        ("sector", "Sektoren"),
        ("currency", "Waehrungen"),
        ("top_positions", "Top-Positionen"),
    )
    cells = []
    colors_by_column = []
    for column_index, (key, label) in enumerate(labels):
        value = int(hhi.get(key, 0) or 0)
        level, color = _hhi_level(value)
        cells.append(Paragraph(
            f'<font name="{FONT_BOLD}" size="7.5" color="#64748b">{_esc(label.upper())}</font>'
            f'<br/><font name="{FONT_BOLD}" size="12" color="#0f172a">'
            f'{_esc(str(value) if value else "-")}</font>'
            f'<br/><font name="{FONT_DEFAULT}" size="7.5" color="#334155">'
            f'{_esc(level)}</font>',
            _cell_style(),
        ))
        colors_by_column.append(("LINEBELOW", (column_index, 0), (column_index, 0), 3, color))
    width = PAGE_SIZE[0] - 24 * mm
    table = Table([cells], colWidths=[width / len(labels)] * len(labels))
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ("BOX", (0, 0), (-1, -1), 0.4, COLOR_BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, COLOR_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        *colors_by_column,
    ]))
    return table


def make_concentration_table(positions: list[dict], base_currency: str = "CHF") -> Table:
    rows = [["Position", "Subanlageklasse", "Zielquote", "Zielbetrag", "Beurteilung"]]
    for item in positions[:10]:
        weight = int(item.get("weight_bps", 0) or 0)
        level = "Pruefen" if weight >= 1000 else "Im Rahmen"
        rows.append([
            Paragraph(
                f'<font name="{FONT_BOLD}">{_esc(item.get("product_name") or "-")}</font>'
                + (
                    f'<br/><font color="#64748b" size="7.5">ISIN {_esc(item.get("isin"))}</font>'
                    if item.get("isin")
                    else ""
                ),
                _cell_style(),
            ),
            Paragraph(_esc(item.get("sub_asset_class") or "-"), _cell_style()),
            f"{weight / 100:.1f}%",
            _format_amount(int(item.get("amount_rappen", 0) or 0), base_currency),
            level,
        ])
    if len(rows) == 1:
        rows.append(["-", "Keine Zielpositionen verfuegbar.", "-", "-", "-"])
    table = _styled_table(rows, [0.31, 0.25, 0.12, 0.18, 0.14], right_from=2)
    table.setStyle(TableStyle([
        ("FONTSIZE", (0, 1), (-1, -1), max(7, FONT_SIZE_TABLE - 0.5)),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return table


def make_cost_table(costs: Mapping[str, object], base_currency: str = "CHF") -> Table:
    rows = [["Kostenart", "Turnus", "Satz", "Betrag", "Datenbasis"]]
    if not costs or costs.get("data_pending"):
        rows.append(["Daten ausstehend", "-", "-", "-", str(costs.get("note") or "-")])
    else:
        for item in costs.get("cost_items") or []:
            rows.append([
                Paragraph(_esc(item.get("label") or "Kosten"), _cell_style()),
                str(item.get("frequency") or "-"),
                f'{int(item.get("rate_bps", 0) or 0) / 100:.2f}%',
                _format_amount(int(item.get("amount_rappen", 0) or 0), base_currency),
                Paragraph(_esc(item.get("basis_label") or "-"), _cell_style()),
            ])
        totals = costs.get("totals") or {}
        rows.extend([
            [
                "Total einmalig",
                "einmalig",
                f'{int(totals.get("one_time_bps", 0) or 0) / 100:.2f}%',
                _format_amount(int(totals.get("one_time_rappen", 0) or 0), base_currency),
                "Beratungsvermoegen",
            ],
            [
                "Total laufend p.a.",
                "jaehrlich",
                f'{int(totals.get("annual_bps", 0) or 0) / 100:.2f}%',
                _format_amount(int(totals.get("annual_rappen", 0) or 0), base_currency),
                "Beratungsvermoegen",
            ],
            [
                "Gesamtkosten erstes Jahr",
                "erstes Jahr",
                f'{int(totals.get("first_year_bps", 0) or 0) / 100:.2f}%',
                _format_amount(int(totals.get("first_year_rappen", 0) or 0), base_currency),
                "Beratungsvermoegen",
            ],
        ])
    return _styled_table(rows, [0.34, 0.13, 0.11, 0.18, 0.24], right_from=2)


def make_summary_text(text: str) -> Table:
    content = Paragraph(_esc(text or "Keine qualitative Einschaetzung dokumentiert."), _summary_style())
    table = Table([[content]], colWidths=[PAGE_SIZE[0] - 24 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ("LINEBEFORE", (0, 0), (0, -1), 2.2, colors.HexColor("#285d70")),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    return table


def _styled_table(rows: list[list], fractions: list[float], *, right_from: int) -> Table:
    width = PAGE_SIZE[0] - 24 * mm
    table = Table(rows, colWidths=[width * value for value in fractions], repeatRows=1)
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
        ("FONTNAME", (0, 1), (-1, -1), FONT_DEFAULT),
        ("FONTSIZE", (0, 0), (-1, 0), FONT_SIZE_TABLE_HEADER),
        ("FONTSIZE", (0, 1), (-1, -1), FONT_SIZE_TABLE),
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_TABLE_HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), COLOR_TEXT_LIGHT),
        ("TEXTCOLOR", (0, 1), (-1, -1), COLOR_TEXT),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, COLOR_BORDER),
        ("LINEBELOW", (0, 1), (-1, -1), 0.3, COLOR_BORDER),
        ("ALIGN", (right_from, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def _hhi_level(value: int):
    if value <= 0:
        return "Daten ausstehend", colors.HexColor("#cbd5e1")
    if value < 1500:
        return "Breit diversifiziert", colors.HexColor("#75a685")
    if value < 2500:
        return "Mittlere Konzentration", colors.HexColor("#d8b454")
    return "Erhoehte Konzentration", colors.HexColor("#c87368")


def _fmt_bps(value) -> str:
    if value is None:
        return "-"
    return f"{int(value or 0) / 100:.2f}%"


def _fmt_negative_bps(value) -> str:
    if value is None:
        return "-"
    return f"-{abs(int(value or 0)) / 100:.1f}%"


def _format_amount(rappen: int, currency: str) -> str:
    return f"{currency} {int(rappen or 0) / 100:,.0f}".replace(",", "'")


def _shorten(value: str, length: int) -> str:
    value = str(value or "-")
    return value if len(value) <= length else value[: length - 1] + "..."


def _cell_style():
    from reportlab.lib.styles import ParagraphStyle

    return ParagraphStyle(
        "DepotcheckCell",
        fontName=FONT_DEFAULT,
        fontSize=FONT_SIZE_TABLE,
        leading=10.5,
        spaceAfter=0,
    )


def _micro_style():
    from reportlab.lib.styles import ParagraphStyle

    return ParagraphStyle(
        "DepotcheckMicro",
        fontName=FONT_BOLD,
        fontSize=7,
        leading=9,
        textColor=COLOR_TEXT_LIGHT,
        spaceAfter=0,
    )


def _metric_style():
    from reportlab.lib.styles import ParagraphStyle

    return ParagraphStyle(
        "DepotcheckMetric",
        fontName=FONT_BOLD,
        fontSize=12,
        leading=14,
        textColor=COLOR_TEXT,
        spaceAfter=0,
    )


def _summary_style():
    from reportlab.lib.styles import ParagraphStyle

    return ParagraphStyle(
        "DepotcheckSummary",
        fontName=FONT_DEFAULT,
        fontSize=10,
        leading=14,
        textColor=COLOR_TEXT,
        spaceAfter=0,
    )
