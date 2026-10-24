"""MC-CONTEXT-001 Folgefix (#691): Monolith-Vertrag fuer ausgeblendete
Soll-Projektionen.

* Depot-Check-Modal: liefert ``/backtest/stress-replays`` wegen des
  Projection-Gates keine Szenarien, zeigt der Modal den Gate-Hinweis aus
  ``stress.warning`` statt "Stress-Replay-Endpoint nicht verfuegbar".
* Backtest-Modal: bei ``data.soll === null`` (Gate stale/blocked) steigt
  ``btRender`` nicht mehr frueh aus, sondern rendert den von der
  Soll-Allokation unabhaengigen Benchmark; SOLL-Serien und -Spalten
  werden nur bei vorhandenem ``data.soll`` gebaut.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

HTML_PATH = (
    Path(__file__).resolve().parents[2] / "ares-desktop" / "frontend" / "ares.html"
)


def _function_source(html: str, name: str) -> str:
    start = html.index(f"function {name}(")
    depth = 0
    opened = False
    for idx in range(html.index("{", start), len(html)):
        ch = html[idx]
        if ch == "{":
            depth += 1
            opened = True
        elif ch == "}":
            depth -= 1
            if opened and depth == 0:
                return html[start: idx + 1]
    raise AssertionError(f"function {name} not closed")


def test_bt_render_does_not_bail_out_on_missing_soll_when_benchmark_present():
    src = _function_source(HTML_PATH.read_text(encoding="utf-8"), "btRender")
    # Kein Fruehausstieg allein wegen fehlendem Soll.
    assert not re.search(r"if\(\s*!data\.soll\s*\)\s*\{", src), src[:400]
    assert "if(!btHasSoll && !data.benchmark){" in src
    # Sub-Asset-Benchmark-Tausch passiert vor dem Benchmark-Check.
    assert src.index("data.benchmark = data.benchmark_sub_asset") < src.index(
        "if(!btHasSoll && !data.benchmark){"
    )
    # Jeder Zugriff auf data.soll.* ist durch btHasSoll geschuetzt.
    assert "if(btHasSoll && showRebal){" in src
    assert "if(btHasSoll && showNoRebal){" in src
    assert "'ausgeblendet'" in src
    # Gate-Hinweis kommt ueber die Warnings auch im Benchmark-only-Fall.
    assert "btRenderWarnings(data.warnings || []);" in src.split(
        "if(!btHasSoll && !data.benchmark){"
    )[1]

    metrics = _function_source(
        HTML_PATH.read_text(encoding="utf-8"), "btRenderMetricsTable"
    )
    assert "if(data.soll && showRebal) cols.push({key:'soll_rebal'" in metrics
    assert "if(data.soll && showNoRebal) cols.push({key:'soll_norebal'" in metrics


@pytest.mark.skipif(shutil.which("node") is None, reason="node nicht verfuegbar")
@pytest.mark.parametrize(
    ("stress", "expected"),
    [
        (
            {"scenarios": [], "warning": "Kein aktuelles Risikoprofil – Projektionen ausgeblendet. <x>"},
            "Kein aktuelles Risikoprofil – Projektionen ausgeblendet. &lt;x&gt;",
        ),
        (None, "Stress-Replay-Endpoint nicht verfügbar"),
    ],
)
def test_dc_stress_replays_shows_gate_warning_instead_of_endpoint_text(stress, expected):
    html = HTML_PATH.read_text(encoding="utf-8")
    script = "\n".join([
        _function_source(html, "escapeHtml"),
        _function_source(html, "dcRenderStressReplays"),
        "var el = {innerHTML: ''};",
        "var document = {getElementById: function(){ return el; }};",
        f"dcRenderStressReplays({json.dumps(stress)});",
        "process.stdout.write(el.innerHTML);",
    ])
    out = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True,
        encoding="utf-8", timeout=30, check=True,
    ).stdout
    assert expected in out, out
    if stress is not None:
        assert "Endpoint nicht verfügbar" not in out
