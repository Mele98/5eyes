"""REPORT-FAN-CHART-BANDS-001: PDF-Faecher (Sektion 11) mit denselben
symmetrischen Baendern wie der Web-Report: P10-P90 (80 %), P25-P75 (50 %)
und Median; Fallback p5-p75 ehrlich beschriftet; Zielmarker oberhalb der
Skala nicht still geklemmt.

Reine Drawing-Tests, keine DB.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from reportlab.graphics.shapes import Circle, Line, Polygon, PolyLine, String  # noqa: E402

from services.pdf.components.mc_paths_chart import (  # noqa: E402
    GOAL_SCALE_CAP,
    build_mc_paths_drawing,
    compute_y_scale,
    make_y_tick_formatter,
    nice_step,
)

N = 11
START = 270_000_000


def _series(rate: float) -> list[int]:
    return [round(START * rate**t) for t in range(N)]


def _legacy_paths() -> dict:
    return {
        "data_pending": False,
        "time_axis": [str(2026 + t) for t in range(N)],
        "p5": _series(1.02),
        "p50": _series(1.05),
        "p75": _series(1.06),
        "n_paths": 1000,
        "horizon_years": N - 1,
    }


def _fan_paths() -> dict:
    return _legacy_paths() | {
        "p10": _series(1.03),
        "p25": _series(1.04),
        "p90": _series(1.075),
    }


def _texts(drawing) -> list[str]:
    return [n.text for n in drawing.contents if isinstance(n, String)]


def _band_polygons(drawing) -> list[Polygon]:
    # Baender haben 2N Punkte = 4N Koordinaten (Legenden-Swatches: 4 Punkte)
    return [n for n in drawing.contents if isinstance(n, Polygon) and len(n.points) == 4 * N]


def _median_mapping(drawing, p50: list[int]):
    median = next(n for n in drawing.contents if isinstance(n, PolyLine))
    ys = median.points[1::2]
    b = (ys[-1] - ys[0]) / (p50[-1] - p50[0])
    a = ys[0] - b * p50[0]
    return lambda v: a + b * v


def _goal(goal_id: str, target: int, year: int = 2035, label: str = "Ziel") -> dict:
    return {
        "goal_id": goal_id,
        "label": label,
        "target_amount_rappen": target,
        "target_date": f"{year}-01-01",
    }


def test_fan_payload_draws_p10_p90_and_p25_p75_exactly():
    paths = _fan_paths()
    drawing = build_mc_paths_drawing(paths, [])
    assert drawing is not None
    texts = _texts(drawing)
    assert "Bandbreite P10–P90 (8 von 10 Verläufen)" in texts
    assert "Kernbereich P25–P75 (5 von 10 Verläufen)" in texts
    assert "Median (P50)" in texts
    assert not any("p5" in t.lower() and "p75" in t.lower() for t in texts)

    outer, inner = _band_polygons(drawing)  # Reihenfolge: aussen, dann innen darueber
    y_of = _median_mapping(drawing, paths["p50"])
    ys_outer = outer.points[1::2]
    ys_inner = inner.points[1::2]
    for i in range(N):
        assert ys_outer[i] == pytest.approx(y_of(paths["p90"][i]))
        assert ys_outer[2 * N - 1 - i] == pytest.approx(y_of(paths["p10"][i]))
        assert ys_inner[i] == pytest.approx(y_of(paths["p75"][i]))
        assert ys_inner[2 * N - 1 - i] == pytest.approx(y_of(paths["p25"][i]))


def test_legacy_payload_keeps_p5_p75_but_labels_it_honestly():
    paths = _legacy_paths()
    drawing = build_mc_paths_drawing(paths, [])
    assert drawing is not None
    texts = _texts(drawing)
    assert "Bandbreite P5–P75 (70 % der Verläufe, asymmetrisch)" in texts
    assert "Band p5-p75" not in texts
    bands = _band_polygons(drawing)
    assert len(bands) == 1
    y_of = _median_mapping(drawing, paths["p50"])
    assert bands[0].points[2 * N - 1] == pytest.approx(y_of(paths["p75"][-1]))
    assert bands[0].points[2 * N + 1] == pytest.approx(y_of(paths["p5"][-1]))


@pytest.mark.parametrize("broken", ["missing_p90", "short_p10", "nan_p25"])
def test_partial_or_broken_fan_quantiles_render_no_chart(broken):
    paths = _fan_paths()
    if broken == "missing_p90":
        del paths["p90"]
    elif broken == "short_p10":
        paths["p10"] = paths["p10"][:5]
    else:
        paths["p25"][3] = float("nan")
    assert build_mc_paths_drawing(paths, []) is None


def test_goal_far_above_scale_gets_edge_marker_with_exact_value():
    goals = [_goal("hard", 50_000_000_00, label="Stiftung")]
    drawing = build_mc_paths_drawing(_fan_paths(), goals)
    assert drawing is not None
    texts = _texts(drawing)
    assert "Stiftung · Ziel CHF 50'000'000 (über Skala)" in texts
    assert "Ziel über der Skala (Wert beschriftet)" in texts
    # Kein Punkt (Circle) fuer dieses Ziel -- stattdessen Dreieck
    assert not any(isinstance(n, Circle) for n in drawing.contents)


def test_goal_moderately_above_fan_extends_scale_and_stays_a_dot_inside_plot():
    paths = _fan_paths()
    target = round(max(paths["p90"]) * 1.6)
    drawing = build_mc_paths_drawing(paths, [_goal("stretch", target, year=2034)])
    assert drawing is not None
    circles = [n for n in drawing.contents if isinstance(n, Circle)]
    assert len(circles) == 1
    # Punkt sitzt exakt auf dem Zielwert (nicht auf den Skalenrand geklemmt)
    y_of = _median_mapping(drawing, paths["p50"])
    assert circles[0].cy == pytest.approx(y_of(target))
    grid_ys = [n.y1 for n in drawing.contents if isinstance(n, Line) and n.y1 == n.y2]
    assert circles[0].cy < max(grid_ys)
    assert "Ziel über der Skala (Wert beschriftet)" not in _texts(drawing)


def test_scale_helpers_match_report_frontend():
    assert nice_step(1.2) == 2
    assert nice_step(2.1) == 2.5
    assert nice_step(26.25) == 50
    assert compute_y_scale(100, []) == (150, 50)
    assert compute_y_scale(4_200_000_00, []) == (6_000_000_00, 2_000_000_00)
    assert compute_y_scale(100, [100 * GOAL_SCALE_CAP])[0] >= 210
    assert compute_y_scale(100, [201]) == compute_y_scale(100, [])

    mio = lambda chf: chf * 100  # noqa: E731
    f1 = make_y_tick_formatter(mio(1_000_000), mio(250_000))
    assert f1(0) == "CHF 0"
    assert f1(mio(500_000)) == "CHF 0.50 Mio."
    assert make_y_tick_formatter(mio(6_000_000), mio(2_000_000))(mio(4_000_000)) == "CHF 4 Mio."
    assert make_y_tick_formatter(mio(750_000), mio(250_000))(mio(250_000)) == "CHF 250'000"


def test_y_axis_ticks_share_one_decimal_count():
    drawing = build_mc_paths_drawing(_fan_paths(), [])
    ticks = [t for t in _texts(drawing) if t.endswith(" Mio.")]
    assert ticks
    decimals = {len(t.split(" ")[1].partition(".")[2]) for t in ticks}
    assert len(decimals) == 1
