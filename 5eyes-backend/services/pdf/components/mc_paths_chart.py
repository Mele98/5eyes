"""ReportLab Monte-Carlo wealth path chart for Advisory-Report Section 11.

Pure ReportLab implementation of the reporting frontend's SVG chart
(MonteCarloPathsChart.tsx): quantile fan, p50 median, CHF axis labels,
sparse year ticks, and goal markers coloured by the same achievability
classification.

REPORT-FAN-CHART-BANDS-001 (2026-10-18): two SYMMETRIC bands P10-P90
(central 80 % of paths) and P25-P75 (central 50 %) plus median, like the
report and the app's P10/P90 figures. Before: one asymmetric p5-p75 band
(70 % of paths). Payloads without p10/p25/p90 fall back to p5-p75, labelled
honestly as "70 %, asymmetrisch". Goal targets above the fan extend the
scale up to GOAL_SCALE_CAP x fan maximum; higher targets get an edge marker
(triangle) with the exact value instead of being silently clamped.
"""
from __future__ import annotations

import math
from typing import Any

from reportlab.graphics.shapes import Circle, Drawing, Line, Polygon, PolyLine, String
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth

from services.pdf.components.advisory_palette import (
    COLOR_INK,
    COLOR_INK_MUTED,
    COLOR_INK_SUBTLE,
    COLOR_RULE,
    COLOR_STATUS_GELB,
    COLOR_STATUS_GRUEN,
    COLOR_STATUS_NEUTRAL,
    COLOR_STATUS_ROT,
    FONT_MONO,
    FONT_SANS,
    FONT_SANS_BOLD,
)
from services.pdf.components.goal_classification import classify_goals
from services.pdf.components.swiss_numbers import format_chf_rappen


# Outer band (P10-P90) light, inner band (P25-P75) drawn on top, darker --
# same visual order as the report's two translucent layers.
COLOR_BAND_FILL = colors.HexColor("#DDE8EA")
COLOR_BAND_INNER_FILL = colors.HexColor("#B9CDD6")
COLOR_P50 = colors.HexColor("#2E5477")

# Same constants as MonteCarloPathsChart.tsx
GOAL_SCALE_CAP = 2.0
MAX_Y_INTERVALS = 4
_MIO_RAPPEN = 1_000_000 * 100

STATUS_COLOR = {
    "erreichbar": COLOR_STATUS_GRUEN,
    "knapp": COLOR_STATUS_GELB,
    "nicht_erreichbar": COLOR_STATUS_ROT,
    "past": COLOR_STATUS_NEUTRAL,
    "beyond_horizon": COLOR_STATUS_NEUTRAL,
    "unknown": COLOR_STATUS_NEUTRAL,
}


def build_mc_paths_drawing(
    paths: dict[str, Any] | None,
    goals: list[dict[str, Any]],
    *,
    width_mm: float = 180,
    height_mm: float = 85,
) -> Drawing | None:
    """Build a ReportLab Drawing for the Monte-Carlo quantile fan.

    Returns None when data is pending or malformed, matching the frontend's
    defensive `return null` path.
    """
    if not paths or paths.get("data_pending"):
        return None

    time_axis = list(paths.get("time_axis") or [])
    p5 = [_as_float(v) for v in (paths.get("p5") or [])]
    p50 = [_as_float(v) for v in (paths.get("p50") or [])]
    p75 = [_as_float(v) for v in (paths.get("p75") or [])]
    n = len(time_axis)
    if n < 2 or len(p5) != n or len(p50) != n or len(p75) != n:
        return None
    if any(v is None or not math.isfinite(v) for v in p5 + p50 + p75):
        return None
    fan = select_fan_bands(paths, n)
    if fan is None:
        return None

    width = float(width_mm) * mm
    height = float(height_mm) * mm
    pad_right = 6 * mm
    pad_top = 9.5 * mm
    pad_bottom = 15 * mm

    classifications = classify_goals(goals, paths)
    goal_by_id = {str(g.get("goal_id") or ""): g for g in goals}
    in_horizon_targets: list[float] = []
    for c in classifications:
        if c.get("t_index") is None:
            continue
        goal = goal_by_id.get(str(c.get("goal_id") or "")) or {}
        target = _as_float(goal.get("target_amount_rappen"))
        if target is not None and math.isfinite(target):
            in_horizon_targets.append(target)
    fan_max = max(max(fan["outer_hi"]), max(float(v) for v in p50))  # type: ignore[arg-type]
    max_value, y_step = compute_y_scale(fan_max, in_horizon_targets)
    format_y_tick = make_y_tick_formatter(max_value, y_step)
    min_value = 0.0
    value_range = max_value - min_value or 1.0
    y_tick_values = [k * y_step for k in range(int(round(max_value / y_step)) + 1)]
    # Linker Rand nach der breitesten Achsenbeschriftung (Monospace), damit
    # "CHF 12.25 Mio." nicht abgeschnitten wird.
    widest_tick = max(stringWidth(format_y_tick(v), FONT_MONO, 7) for v in y_tick_values)
    pad_left = max(17.5 * mm, widest_tick + 5 * mm)
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom
    plot_bottom = pad_bottom
    plot_top = plot_bottom + plot_h

    def x_for(i: int) -> float:
        return pad_left + (i / (n - 1)) * plot_w

    def y_for(value: float) -> float:
        return plot_bottom + ((value - min_value) / value_range) * plot_h

    drawing = Drawing(width, height)

    for k, value in enumerate(y_tick_values):
        y = y_for(float(value))
        drawing.add(Line(
            pad_left, y, width - pad_right, y,
            strokeColor=COLOR_RULE,
            strokeWidth=1 if k == 0 else 0.5,
        ))
        drawing.add(String(
            pad_left - 3 * mm,
            y - 2,
            format_y_tick(value),
            textAnchor="end",
            fontName=FONT_MONO,
            fontSize=7,
            fillColor=COLOR_INK_SUBTLE,
        ))

    drawing.add(Polygon(
        _band_points(fan["outer_lo"], fan["outer_hi"], x_for, y_for),
        fillColor=COLOR_BAND_FILL,
        strokeColor=None,
    ))
    if fan["inner_lo"] is not None and fan["inner_hi"] is not None:
        drawing.add(Polygon(
            _band_points(fan["inner_lo"], fan["inner_hi"], x_for, y_for),
            fillColor=COLOR_BAND_INNER_FILL,
            strokeColor=None,
        ))

    p50_points: list[float] = []
    for i, value in enumerate(p50):
        p50_points.extend([x_for(i), y_for(float(value))])  # type: ignore[arg-type]
    drawing.add(PolyLine(
        p50_points,
        strokeColor=COLOR_P50,
        strokeWidth=1.8,
    ))

    any_above_scale = False
    for classification in classifications:
        t_index = classification.get("t_index")
        if t_index is None:
            continue
        goal = goal_by_id.get(str(classification.get("goal_id") or ""))
        if not goal:
            continue
        target_amount = _as_float(goal.get("target_amount_rappen"))
        if target_amount is None:
            continue
        status = str(classification.get("status") or "unknown")
        marker_color = STATUS_COLOR.get(status, COLOR_STATUS_NEUTRAL)
        x = x_for(int(t_index))
        above_scale = float(target_amount) > max_value
        any_above_scale = any_above_scale or above_scale
        y_target = y_for(min(max(float(target_amount), min_value), max_value))
        drawing.add(Line(
            x, plot_bottom, x, plot_top,
            strokeColor=marker_color,
            strokeWidth=0.8,
            strokeDashArray=[3, 3],
        ))
        if above_scale:
            # Edge marker: target above the scale -> upward triangle + exact
            # value instead of a dot that seems to sit on the band.
            drawing.add(Polygon(
                [x, y_target + 1, x - 3.6, y_target - 5, x + 3.6, y_target - 5],
                fillColor=marker_color,
                strokeColor=None,
            ))
        else:
            drawing.add(Circle(x, y_target, 3.6, fillColor=marker_color, strokeColor=None))

        label = str(goal.get("label") or goal.get("goal_id") or "").strip()
        if above_scale:
            label = (
                f"{_shorten(label, 24)} · Ziel "
                f"{format_chf_rappen(int(round(float(target_amount))))} (über Skala)"
            ).strip(" ·")
        else:
            label = _shorten(label, 30)
        if label:
            text_anchor = "start"
            label_x = x + 2.5 * mm
            limit = 60 * mm if above_scale else 18 * mm
            if label_x > width - pad_right - limit:
                label_x = x - 2.5 * mm
                text_anchor = "end"
            if above_scale:
                label_y = y_target - 4.5 * mm
            else:
                label_y = min(max(y_target + 2.5 * mm, plot_bottom + 4), plot_top - 4)
            drawing.add(String(
                label_x,
                label_y,
                label,
                textAnchor=text_anchor,
                fontName=FONT_SANS_BOLD,
                fontSize=7,
                fillColor=COLOR_INK,
            ))

    x_tick_indices = _spaced_indices(n, 6)
    for i in x_tick_indices:
        drawing.add(String(
            x_for(i),
            plot_bottom - 5 * mm,
            str(time_axis[i]),
            textAnchor="middle",
            fontName=FONT_MONO,
            fontSize=7,
            fillColor=COLOR_INK_SUBTLE,
        ))

    drawing.add(Line(
        pad_left, plot_bottom, pad_left, plot_top,
        strokeColor=COLOR_INK_MUTED,
        strokeWidth=1,
    ))
    drawing.add(Line(
        pad_left, plot_bottom, width - pad_right, plot_bottom,
        strokeColor=COLOR_INK_MUTED,
        strokeWidth=1,
    ))

    _draw_legend(drawing, pad_left, height - 5 * mm, fan, any_above_scale)
    return drawing


def select_fan_bands(paths: dict[str, Any], n: int) -> dict[str, Any] | None:
    """Same rule as selectFanBands() in MonteCarloPathsChart.tsx.

    Prefers P10-P90 + P25-P75. If p10/p25/p90 are all absent (older
    payload): p5-p75, labelled as 70 %, asymmetric. Partially present or
    malformed: None (no chart instead of a silently different band).
    Expects already validated p5/p50/p75 of length n.
    """
    raw = {k: list(paths.get(k) or []) for k in ("p10", "p25", "p90")}
    p5 = [float(v) for v in (paths.get("p5") or [])]
    p75 = [float(v) for v in (paths.get("p75") or [])]
    if not any(raw.values()):
        return {
            "outer_lo": p5,
            "outer_hi": p75,
            "inner_lo": None,
            "inner_hi": None,
            "outer_legend": "Bandbreite P5–P75 (70 % der Verläufe, asymmetrisch)",
            "inner_legend": None,
        }
    parsed: dict[str, list[float]] = {}
    for key, values in raw.items():
        floats = [_as_float(v) for v in values]
        if len(floats) != n or any(v is None or not math.isfinite(v) for v in floats):
            return None
        parsed[key] = [float(v) for v in floats]  # type: ignore[arg-type]
    return {
        "outer_lo": parsed["p10"],
        "outer_hi": parsed["p90"],
        "inner_lo": parsed["p25"],
        "inner_hi": p75,
        "outer_legend": "Bandbreite P10–P90 (8 von 10 Verläufen)",
        "inner_legend": "Kernbereich P25–P75 (5 von 10 Verläufen)",
    }


def nice_step(raw: float) -> float:
    """Smallest step from 1/2/2.5/5 x 10^k that is >= raw."""
    if not (raw > 0) or not math.isfinite(raw):
        return 1.0
    base = 10.0 ** math.floor(math.log10(raw))
    for m in (1.0, 2.0, 2.5, 5.0):
        candidate = m * base
        if candidate >= raw * (1 - 1e-12):
            return candidate
    return 10.0 * base


def compute_y_scale(fan_max: float, goal_targets: list[float]) -> tuple[float, float]:
    """Upper bound = smallest multiple of a round step covering 105 % of
    max(fan maximum, goals <= GOAL_SCALE_CAP x fan maximum); at most
    MAX_Y_INTERVALS intervals. Returns (max_value, step)."""
    safe_fan_max = fan_max if fan_max > 0 and math.isfinite(fan_max) else 1.0
    cap = safe_fan_max * GOAL_SCALE_CAP
    in_scale = [v for v in goal_targets if 0 < v <= cap]
    top = max([safe_fan_max, *in_scale]) * 1.05
    step = nice_step(top / MAX_Y_INTERVALS)
    max_value = math.ceil(top / step - 1e-9) * step
    return max_value, step


def make_y_tick_formatter(max_value_rappen: float, step_rappen: float):
    """One fixed number of decimals for the whole axis. From CHF 1 Mio.:
    "CHF x.xx Mio." with as many decimals as the step needs; below: full
    amount with apostrophe (swiss_numbers.format_chf_rappen)."""
    if max_value_rappen < _MIO_RAPPEN:
        return lambda rappen: format_chf_rappen(int(round(rappen)))
    step_mio = step_rappen / _MIO_RAPPEN
    decimals = 0
    while decimals < 3 and abs(step_mio * 10**decimals - round(step_mio * 10**decimals)) > 1e-9:
        decimals += 1

    def _fmt(rappen: float) -> str:
        if rappen == 0:
            return "CHF 0"
        return f"CHF {rappen / _MIO_RAPPEN:.{decimals}f} Mio."

    return _fmt


def _band_points(lo, hi, x_for, y_for) -> list[float]:
    """Polygon: upper edge forward, lower edge backward."""
    points: list[float] = []
    for i, value in enumerate(hi):
        points.extend([x_for(i), y_for(float(value))])
    for i, value in reversed(list(enumerate(lo))):
        points.extend([x_for(i), y_for(float(value))])
    return points


def _draw_legend(
    drawing: Drawing, x: float, y: float, fan: dict[str, Any], any_above_scale: bool,
) -> None:
    font_size = 7
    gap = 5 * mm

    def swatch_item(cx: float, fill, text: str) -> float:
        drawing.add(Polygon(
            [cx, y - 3, cx + 9, y - 3, cx + 9, y + 3, cx, y + 3],
            fillColor=fill,
            strokeColor=COLOR_P50,
            strokeWidth=0.4,
        ))
        drawing.add(String(
            cx + 12, y - 2, text,
            fontName=FONT_SANS, fontSize=font_size, fillColor=COLOR_INK_SUBTLE,
        ))
        return cx + 12 + stringWidth(text, FONT_SANS, font_size) + gap

    cursor = swatch_item(x, COLOR_BAND_FILL, fan["outer_legend"])
    if fan["inner_legend"]:
        cursor = swatch_item(cursor, COLOR_BAND_INNER_FILL, fan["inner_legend"])
    drawing.add(Line(
        cursor, y, cursor + 10, y,
        strokeColor=COLOR_P50,
        strokeWidth=1.8,
    ))
    median_text = "Median (P50)"
    drawing.add(String(
        cursor + 13, y - 2, median_text,
        fontName=FONT_SANS, fontSize=font_size, fillColor=COLOR_INK_SUBTLE,
    ))
    if any_above_scale:
        # Second legend line (still above the plot area, inside pad_top)
        y2 = y - 8
        drawing.add(Polygon(
            [x + 3.6, y2 + 3, x, y2 - 3, x + 7.2, y2 - 3],
            fillColor=COLOR_INK_SUBTLE,
            strokeColor=None,
        ))
        drawing.add(String(
            x + 12, y2 - 2, "Ziel über der Skala (Wert beschriftet)",
            fontName=FONT_SANS, fontSize=font_size, fillColor=COLOR_INK_SUBTLE,
        ))


def _spaced_indices(length: int, n_max: int) -> list[int]:
    if length <= n_max:
        return list(range(length))
    step = (length - 1) / (n_max - 1)
    return sorted({round(k * step) for k in range(n_max)})


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _shorten(value: str, max_len: int) -> str:
    if len(value) <= max_len:
        return value
    return value[: max_len - 3].rstrip() + "..."


__all__ = [
    "build_mc_paths_drawing",
    "compute_y_scale",
    "make_y_tick_formatter",
    "nice_step",
    "select_fan_bands",
]
