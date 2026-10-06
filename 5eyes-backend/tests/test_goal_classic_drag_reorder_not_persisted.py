"""GOAL-RANK-HARDNESS-ROUNDTRIP-001 (Kontrollrunde 37 audit finding).

The Classic UI's drag-and-drop goal reordering (`setupDrag` in
5eyes_v2.html, registered on `#zl .goal` rows and re-invoked from
`renderGoalList`) only moves DOM nodes around and relabels the visual
priority badge via `renum()`. It does not call the backend (`API.put` /
`API.post`, the helper every legitimate goal-save path in this file uses -
see `saveGoal()`) and it does not touch `currentGoals`, the real in-memory
goals array that `saveGoal()` / `upsertSavedGoal()` / `refreshGoalsUI()`
mutate and persist. So a drag-reorder creates a purely cosmetic
impression of a saved new order: a page reload (which repopulates
`currentGoals` from the backend via `refreshGoalsUI`) discards it
entirely, with no rollback/undo because nothing was ever changed to roll
back.

This test uses the same static-extraction mechanism as
test_frontend_review_cockpit.py (read 5eyes_v2.html as text, assert
against isolated string/regex extractions of the real source) rather than
executing the handler inside a DOM, since `setupDrag`'s drop handler is
wired directly to native `dragstart`/`dragover`/`drop` DOM events with no
jsdom/browser runtime available in this Python test suite.
"""
import re
from pathlib import Path

import pytest


HTML_PATH = Path(__file__).resolve().parents[2] / "5eyes-electron" / "frontend" / "5eyes_v2.html"


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def _extract_function(html: str, signature: str) -> str:
    """Extract a top-level `function <signature>(...){...}` body by brace
    matching, starting at the first occurrence of `function <signature>(`.
    """
    marker = "function " + signature + "("
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
    # Sanity: confirm the real handler names referenced by this audit
    # finding still exist under these names before asserting on their body.
    assert "function setupDrag()" in html
    assert "function renum()" in html


@pytest.mark.xfail(
    strict=True,
    reason=(
        "GOAL-RANK-HARDNESS-ROUNDTRIP-001 — round 47 red test (drag-and-drop "
        "reorder is cosmetic only, not persisted), see audit "
        "docs/audits/2026-09-28-goal-funding-priority-and-achievability-attribution-audit.md"
    ),
)
def test_drag_reorder_handler_does_not_persist_new_rank_order():
    """RED (documents GOAL-RANK-HARDNESS-ROUNDTRIP-001): a drag-and-drop
    reorder of goals must actually be persisted - either by calling the
    backend save/reorder endpoint (API.put/API.post, as saveGoal() does),
    or at minimum by reordering the real in-memory `currentGoals` array
    in the same order as the dragged DOM nodes so a subsequent save/sort
    would preserve it.

    Today it does neither: `setupDrag`'s drop handler only calls
    `list.insertBefore(drag,this)` (a DOM move) followed by `renum()`,
    and `renum()` only rewrites the `.pd` badge textContent/className -
    neither touches `currentGoals` or the backend.
    """
    html = _html()
    setup_drag_src = _extract_function(html, "setupDrag")
    renum_src = _extract_function(html, "renum")
    drag_and_renum_src = setup_drag_src + "\n" + renum_src

    calls_backend = bool(re.search(r"API\.(put|post)\(", drag_and_renum_src))
    mutates_current_goals = "currentGoals" in drag_and_renum_src

    assert calls_backend or mutates_current_goals, (
        "Expected the drag-reorder handler (setupDrag) or its post-drop "
        "callback (renum) to persist the new order - either via a backend "
        "call (API.put/API.post) or by reordering the in-memory "
        "`currentGoals` array - but it does neither. Extracted source:\n\n"
        + drag_and_renum_src
    )


def test_drag_reorder_drop_handler_only_moves_dom_nodes():
    """Pins down the precise mechanism so this test fails for the
    documented reason, not some unrelated refactor: the `drop` listener's
    body is exactly a DOM reinsert + `renum()`, nothing else.
    """
    html = _html()
    setup_drag_src = _extract_function(html, "setupDrag")
    drop_handler_match = re.search(
        r"addEventListener\('drop',function\(e\)\{(.*?)\}\);",
        setup_drag_src,
        re.DOTALL,
    )
    assert drop_handler_match, "Could not locate the 'drop' listener inside setupDrag()"
    drop_body = drop_handler_match.group(1)
    assert "list.insertBefore(drag,this)" in drop_body
    assert "renum()" in drop_body
    assert "API." not in drop_body
    assert "currentGoals" not in drop_body
