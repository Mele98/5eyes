"""A11Y-GP-001 (B2B-Trust-Audit Runde 3, 2026-10-05): the Golden-Path stepper
(.tnav .tstep, exactly the Login -> Stammdaten -> Vermoegen -> Cashflows &
Ziele -> Risikoprofil -> Asset Allokation -> Portfolio -> Review & Abschluss
navigation) had zero keyboard semantics: no role, no tabindex, no keydown
handler -- confirmed 0/61 across all clickable divs in this file by the
audit, this being the single most used one.

See docs/audits/2026-10-05-b2b-accessibility-golden-path-and-pdf-audit.md
(finding A11Y-GP-001).

Fix: each .tstep now carries role="tab" + tabindex="0" + aria-selected,
the <nav> carries role="tablist", and a dedicated handleTstepKeydown()
function activates the same go() navigation on Enter/Space that onclick
already used. go() itself was extended to keep aria-selected in sync with
the actually-active step on every navigation.

This test is a static-source regression test (same convention as
test_frontend_review_cockpit.py in this suite), not a live DOM/keyboard
execution -- it locks in the markup/wiring, not runtime behavior.
"""
from __future__ import annotations

import re
from pathlib import Path

HTML_PATH = Path(__file__).resolve().parents[2] / "5eyes-electron" / "frontend" / "5eyes_v2.html"


def _read_html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def test_tnav_has_tablist_role():
    html = _read_html()
    assert re.search(r'<nav class="tnav" role="tablist"', html), (
        "the golden-path stepper <nav> must declare role=\"tablist\""
    )


def test_all_seven_tsteps_have_tab_role_and_keyboard_semantics():
    html = _read_html()
    tstep_divs = re.findall(r'<div class="tstep[^"]*"[^>]*>', html)
    assert len(tstep_divs) == 7, (
        f"expected exactly 7 golden-path step elements, found {len(tstep_divs)}"
    )
    for div in tstep_divs:
        assert 'role="tab"' in div, f"missing role=\"tab\" on: {div}"
        assert 'tabindex="0"' in div, f"missing tabindex=\"0\" on: {div}"
        assert 'aria-selected=' in div, f"missing aria-selected on: {div}"
        assert 'onkeydown="handleTstepKeydown(' in div, (
            f"missing keyboard activation handler on: {div}"
        )


def test_handle_tstep_keydown_function_exists_and_activates_on_enter_and_space():
    html = _read_html()
    match = re.search(
        r"function handleTstepKeydown\(event,p,el\)\{(.*?)\}\n",
        html,
        re.DOTALL,
    )
    assert match, "handleTstepKeydown() function not found"
    body = match.group(1)
    assert "Enter" in body and (" '" in body or '" "' in body or "' '" in body), (
        "handleTstepKeydown must react to both Enter and Space"
    )
    assert "go(p,el)" in body, "handleTstepKeydown must delegate to the real go() navigation"


def test_go_function_keeps_aria_selected_in_sync_with_active_step():
    html = _read_html()
    go_fn = re.search(r"async function go\(p,b\)\{(.*?)\n\}\n", html, re.DOTALL)
    assert go_fn, "go() function not found"
    assert "setAttribute('aria-selected'" in go_fn.group(1), (
        "go() must update aria-selected on every step element when "
        "navigating, not just the CSS active/done classes -- otherwise "
        "screen readers keep announcing the original step as selected"
    )
