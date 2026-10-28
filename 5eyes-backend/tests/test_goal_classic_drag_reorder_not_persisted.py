"""GOAL-RANK-HARDNESS-ROUNDTRIP-001 (Kontrollrunde 37 audit finding).

Befund: der Drag-and-drop-Reorder der Classic UI (`setupDrag` in
5eyes_v2.html) verschob nur DOM-Knoten und nummerierte die Badges via
`renum()` neu. Weder Backend noch `currentGoals` wurden angefasst; ein Reload
verwarf die "gespeicherte" Reihenfolge.

GESCHLOSSEN 2026-10-25 (ADR-10c): der Drop ruft `persistGoalOrder()`. Diese
Funktion liest die neue DOM-Folge, schreibt sie atomar per
`PUT /mandates/{id}/goals/order` (mit `expected_goal_ids` = zuletzt gesehene
Folge, CAS) und uebernimmt die Server-Antwort in `currentGoals`. Bei
Requestfehler zeigt sie den Fehler und laedt den persistierten Stand neu
(sichtbarer Rollback).

Die Tests extrahieren die ECHTEN Funktionen aus der HTML-Datei
(Klammerabgleich) und fuehren `persistGoalOrder()` in node mit minimalen
Stubs fuer DOM/API aus.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest


HTML_PATH = Path(__file__).resolve().parents[2] / "5eyes-electron" / "frontend" / "5eyes_v2.html"


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def _extract_function(html: str, signature: str, prefix: str = "function ") -> str:
    """Extract a top-level `function <signature>(...){...}` body by brace
    matching, starting at the first occurrence of `function <signature>(`.
    """
    marker = prefix + signature + "("
    start = html.index(marker)
    open_brace = html.index("{", start)
    depth = 0
    i = open_brace
    while i < len(html):
        if html[i] == "{":
            depth += 1
        elif html[i] == "}":
            depth -= 1
            if depth == 0:
                return html[start:i + 1]
        i += 1
    raise AssertionError("Unbalanced braces while extracting function " + signature)


def test_setup_drag_and_renum_functions_exist():
    html = _html()
    assert "function setupDrag()" in html
    assert "function renum()" in html
    assert "async function persistGoalOrder()" in html


def test_drag_reorder_drop_handler_persists_the_new_order():
    """Der Drop-Handler verschiebt den Knoten, nummeriert neu UND persistiert."""
    setup_drag_src = _extract_function(_html(), "setupDrag")
    drop_handler_match = re.search(
        r"addEventListener\('drop',function\(e\)\{(.*?)\}\);",
        setup_drag_src,
        re.DOTALL,
    )
    assert drop_handler_match, "Could not locate the 'drop' listener inside setupDrag()"
    drop_body = drop_handler_match.group(1)
    assert "list.insertBefore(drag,this)" in drop_body
    assert "renum()" in drop_body
    assert "persistGoalOrder()" in drop_body


def _run_persist(goals: list[dict], dom_order: list[str], *, fail: bool, mandate: str = "m-1") -> dict:
    fn_src = _extract_function(_html(), "persistGoalOrder", prefix="async function ")
    script = f"""
    var currentGoals = {json.dumps(goals)};
    var calls = {{put: [], rendered: [], refreshed: [], errors: [], dirty: 0}};
    var document = {{ querySelectorAll: function(sel) {{
      return {json.dumps(dom_order)}.map(function(id) {{ return {{ getAttribute: function() {{ return id; }} }}; }});
    }} }};
    function getActiveMandateId() {{ return {json.dumps(mandate)}; }}
    function isDemoMandateId(id) {{ return String(id).indexOf('demo-') === 0; }}
    function renderGoalList(items, isDemo) {{ calls.rendered.push(items.map(function(g) {{ return [g.id, g.rank]; }})); }}
    function syncAllocationPendingViews() {{}}
    function markStrategyDirty() {{ calls.dirty += 1; }}
    function showAppError(msg) {{ calls.errors.push(String(msg)); }}
    function goalSaveErrorText(e) {{ return String(e && e.detail || e); }}
    async function refreshGoalsUI(mid) {{ calls.refreshed.push(mid); }}
    var API = {{ put: async function(url, body) {{
      calls.put.push([url, body]);
      if ({json.dumps(fail)}) throw {{detail: 'Die Ziel-Reihenfolge wurde inzwischen geaendert.'}};
      return body.goal_ids.map(function(id, i) {{ return {{id: id, rank: i + 1}}; }});
    }} }};
    {fn_src}
    persistGoalOrder().then(function(ok) {{
      calls.ok = ok;
      calls.currentGoals = currentGoals.map(function(g) {{ return [g.id, g.rank]; }});
      process.stdout.write(JSON.stringify(calls));
    }});
    """
    proc = subprocess.run(["node", "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


GOALS = [{"id": "a", "rank": 1}, {"id": "b", "rank": 2}, {"id": "c", "rank": 3}]


def test_persist_goal_order_writes_full_permutation_with_cas():
    if shutil.which("node") is None:
        pytest.skip("node binary not available to execute extracted JS")
    out = _run_persist(GOALS, ["c", "a", "b"], fail=False)
    assert out["put"] == [[
        "/mandates/m-1/goals/order",
        {"goal_ids": ["c", "a", "b"], "expected_goal_ids": ["a", "b", "c"]},
    ]]
    assert out["ok"] is True
    assert out["currentGoals"] == [["c", 1], ["a", 2], ["b", 3]]
    assert out["dirty"] == 1
    assert out["refreshed"] == []


def test_persist_goal_order_rolls_back_visibly_on_request_error():
    if shutil.which("node") is None:
        pytest.skip("node binary not available to execute extracted JS")
    out = _run_persist(GOALS, ["c", "a", "b"], fail=True)
    assert out["ok"] is False
    assert out["refreshed"] == ["m-1"], "Rollback = Neuladen des persistierten Stands"
    assert len(out["errors"]) == 1 and "inzwischen geaendert" in out["errors"][0]
    assert out["currentGoals"] == [["a", 1], ["b", 2], ["c", 3]]
    assert out["dirty"] == 0


def test_persist_goal_order_in_demo_mode_reorders_locally():
    if shutil.which("node") is None:
        pytest.skip("node binary not available to execute extracted JS")
    out = _run_persist(GOALS, ["b", "c", "a"], fail=False, mandate="demo-1")
    assert out["put"] == []
    assert out["currentGoals"] == [["b", 1], ["c", 2], ["a", 3]]
