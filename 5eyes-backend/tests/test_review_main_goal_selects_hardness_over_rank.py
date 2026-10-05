"""Round 47 red test — GOAL-RANK-HARDNESS-ROUNDTRIP-001.

External audit (Kontrollrunde 37, Repro 3,
docs/audits/2026-09-28-goal-funding-priority-and-achievability-attribution-audit.md):
the Classic UI's Review screen selects the "Hauptziel" (main goal) via
``mainGoalAchievability()`` in 5eyes-electron/frontend/5eyes_v2.html, which
sorts the stochastic achievability rows by hardness FIRST and rank SECOND.
That means a secondary (rank 2) hard goal is shown as the main goal even
when a primary (rank 1) goal exists with a much higher success probability
-- the Review's "Hauptziel" claim is not the canonical rank-1 goal.

Harness note: 5eyes-backend/tests/test_frontend_review_cockpit.py (the
established "frontend contract" test for this same screen) only asserts
that certain literal strings/markers (element ids, function signatures,
field names) are present in the raw 5eyes_v2.html source text. It does not
actually execute any extracted JavaScript -- there is no JS engine, jsdom,
or node-subprocess harness anywhere in this repo's existing frontend test
suite (checked across all ~80 `test_frontend_*`/`test_*_wiring_contract.py`
files that reference 5eyes_v2.html). So there is no pre-existing
"extraction/execution mechanism" to reuse verbatim for calling the real
function with real inputs.

To avoid faking a result, this test instead extracts the REAL
``mainGoalAchievability`` function body straight out of the shipped HTML
(brace-matched, not hand-copied) and executes it for real in a `node`
subprocess (Node is available in this environment: `node --version` ->
v24.14.0) against the exact two-goal repro from the audit. Everything
mainGoalAchievability() reads from module/global scope
(`currentGoals`, `allocationAchievability`) is supplied as minimal stubs;
the sort/selection logic itself is the untouched, real code from
5eyes_v2.html. Production code is not modified.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

HTML_PATH = Path(__file__).resolve().parents[2] / "5eyes-electron" / "frontend" / "5eyes_v2.html"


def _extract_function(html: str, name: str) -> str:
    """Brace-match the real `function <name>(...){...}` out of the HTML source."""
    marker = f"function {name}("
    start = html.index(marker)
    brace_start = html.index("{", start)
    depth = 0
    i = brace_start
    while i < len(html):
        if html[i] == "{":
            depth += 1
        elif html[i] == "}":
            depth -= 1
            if depth == 0:
                return html[start : i + 1]
        i += 1
    raise AssertionError(f"could not brace-match function {name}() in {html!r}")


def _run_main_goal_achievability(goals: list[dict], rows: list[dict]) -> dict:
    """Execute the REAL mainGoalAchievability() from 5eyes_v2.html in node.

    `allocationAchievability` is stubbed to just hand back the rows we pass
    in (mainGoalAchievability's own first line is
    `var rows=allocationAchievability(result);`, so we pass `rows` itself as
    the `result` argument and let the stub echo it straight through). The
    sort/selection logic below that line is the real, unmodified function.
    """
    html = HTML_PATH.read_text(encoding="utf-8")
    fn_src = _extract_function(html, "mainGoalAchievability")
    script = f"""
    var currentGoals = {json.dumps(goals)};
    function allocationAchievability(result) {{ return result; }}
    {fn_src}
    var rows = {json.dumps(rows)};
    var picked = mainGoalAchievability(rows);
    process.stdout.write(JSON.stringify(picked));
    """
    proc = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, (
        "node harness failed to execute the real mainGoalAchievability() "
        f"extracted from 5eyes_v2.html (this would be a harness failure, "
        f"NOT the documented GOAL-RANK-HARDNESS-ROUNDTRIP-001 behaviour):\n"
        f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )
    return json.loads(proc.stdout)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "GOAL-RANK-HARDNESS-ROUNDTRIP-001 — round 47 red test (Review "
        "main-goal selection picks hardness over rank), see audit "
        "docs/audits/2026-09-28-goal-funding-priority-and-achievability-"
        "attribution-audit.md"
    ),
)
def test_review_main_goal_is_canonical_rank_one_not_hardness_sorted():
    """mainGoalAchievability() must pick the rank-1 goal as 'Hauptziel'.

    Repro from the audit: a rank-1 primary goal with 90% probability
    co-exists with a rank-2 HARD goal at only 20% probability. The
    canonically correct "Hauptziel" is the rank-1 goal. The real function
    currently returns the rank-2 hard goal instead, because it sorts
    hardness before rank.
    """
    goals = [
        {"id": "primary", "rank": 1},
        {"id": "secondary", "rank": 2},
    ]
    rows = [
        {
            "goal_id": "primary",
            "label": "Primary rank 1",
            "probability": 0.9,
            "hardness": "Primär",
        },
        {
            "goal_id": "secondary",
            "label": "Hard rank 2",
            "probability": 0.2,
            "hardness": "Hart",
        },
    ]

    picked = _run_main_goal_achievability(goals, rows)

    assert picked["goal_id"] == "primary", (
        "mainGoalAchievability() must select the canonical rank-1 goal as "
        f"'Hauptziel', not sort hardness before rank. Got: {picked!r}"
    )
