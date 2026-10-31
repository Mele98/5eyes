"""CHART-PROXY-SELF-ASSIGN-001 (Assetallocation-Audit 2026-10-14).

Every "Anlagestrategie berechnen" threw ``RangeError: Maximum call stack size
exceeded`` inside the vendored Chart.js (``Object.set`` alternating between
two minified proxy traps). The finding was open since 2026-08-06; three
array-identity hypotheses had been disproved then.

Root cause: Chart.js 4 hands out ``chart.options.*`` sub-objects as resolver
*proxies*. The app wrote

    charts.opt.options.plugins.legend.labels =
        charts.opt.options.plugins.legend.labels || {};

``labels`` already resolves to a proxy (Chart.js defaults define it), so the
``|| {}`` never fires and the proxy is assigned *into itself*. The next write
(``labels.boxWidth = 18``) then recurses between the two set traps until the
stack overflows. Measured in a real Chromium against Chart.js 4.4.1:

    A  app pattern (self-assign, then mutate)  -> RangeError
    B  mutate the proxy only                   -> no error
    C  assign a fresh plain object             -> no error

The same pattern sat at four places. The one on the IST chart's x-axis ticks
(``initCharts``) aborted before the age-axis tick callback was installed.

This is a static-source regression test (same convention as
test_a11y_gp_001_golden_path_stepper_keyboard.py): it forbids the
self-assignment shape on any Chart.js options path.
"""
from __future__ import annotations

import re
from pathlib import Path

HTML_PATH = Path(__file__).resolve().parents[2] / "ares-desktop" / "frontend" / "ares.html"

# <path>.options<...>.<key> = <same path>.options<...>.<key> || ...
_SELF_ASSIGN = re.compile(
    r"(?P<lhs>[A-Za-z_$][\w$]*(?:\.[\w$]+)*\.options(?:\.[\w$]+)+)\s*=\s*(?P=lhs)\s*\|\|"
)


def test_no_chart_options_proxy_is_assigned_into_itself():
    html = HTML_PATH.read_text(encoding="utf-8")
    hits = [
        f"line {html.count(chr(10), 0, m.start()) + 1}: {m.group(0)}"
        for m in _SELF_ASSIGN.finditer(html)
    ]
    assert not hits, (
        "Chart.js options are resolver proxies; `x = x || {}` assigns the proxy "
        "into itself and the next property write overflows the stack "
        "(CHART-PROXY-SELF-ASSIGN-001):\n" + "\n".join(hits)
    )


def test_pattern_detects_the_original_defect():
    """Guard the guard: the regex must match the exact shape that shipped."""
    original = (
        "charts.opt.options.plugins.legend.labels="
        "charts.opt.options.plugins.legend.labels||{};"
    )
    assert _SELF_ASSIGN.search(original)
    assert not _SELF_ASSIGN.search("if(!lg.labels)lg.labels={};")
