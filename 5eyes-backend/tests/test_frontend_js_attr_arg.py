"""Frontend-Contract-Tests fuer jsAttrArg() — sichere String-Embedding in HTML-Attributen.

Behebt den XSS-/JS-Bruch-Bug bei dynamischen onclick-Konstrukten:
  onclick="foo('" + escapeHtml(value) + "')"
funktioniert nicht sicher, weil escapeHtml(value) nur HTML-eskapiert,
nicht JS-string-literal. Single-Quotes im Wert werden im HTML-Attribute-
Kontext zurück-decoded und brechen aus dem JS-String aus.

jsAttrArg eskapiert in zwei Schritten:
1. JS-Literal escape (\\, ', newline)
2. HTML-Attribute escape (& " < >)
"""
from __future__ import annotations

import re
from pathlib import Path

FRONTEND_HTML = (
    Path(__file__).resolve().parents[2]
    / "5eyes-electron" / "frontend" / "5eyes_v2.html"
)


def _html() -> str:
    return FRONTEND_HTML.read_text(encoding="utf-8")


def _function_body(name: str) -> str:
    """Extract function body via brace matching."""
    html = _html()
    idx = html.find(f"function {name}(")
    assert idx >= 0, f"Function {name} nicht gefunden"
    # Find opening brace
    brace_start = html.find("{", idx)
    depth = 0
    for i in range(brace_start, min(brace_start + 4000, len(html))):
        if html[i] == "{":
            depth += 1
        elif html[i] == "}":
            depth -= 1
            if depth == 0:
                return html[brace_start : i + 1]
    raise AssertionError(f"Function body for {name} unbalanced")


def test_js_attr_arg_function_exists():
    assert "function jsAttrArg(value)" in _html()


def test_js_attr_arg_escapes_in_correct_order():
    body = _function_body("jsAttrArg")
    # JS-escape FIRST (backslash, single quote, newline)
    # then HTML-escape (& " < >)
    js_step = body.find("\\\\\\\\")  # '\\\\' in JS source → 2 backslashes
    html_step = body.find("&amp;")
    assert js_step >= 0 and html_step >= 0
    assert js_step < html_step, "JS-Escape muss VOR HTML-Escape laufen, sonst werden Backslashes doppelt eskapiert"


def test_js_attr_arg_handles_all_required_chars():
    body = _function_body("jsAttrArg")
    # JS-literal escapes: backslash, single quote, newline
    assert "\\\\" in body  # backslash escape
    assert "\\'" in body  # single quote escape
    assert "\\n" in body  # newline escape
    # HTML attribute escapes: ampersand, double quote, angle brackets
    assert "&amp;" in body
    assert "&quot;" in body
    assert "&lt;" in body
    assert "&gt;" in body


def test_js_attr_arg_handles_null_undefined():
    body = _function_body("jsAttrArg")
    # Either `value == null` (covers null + undefined) or explicit checks
    assert "value == null" in body or "value === null" in body or "value==null" in body


def test_js_attr_arg_doc_comment_explains_xss_motivation():
    html = _html()
    idx = html.find("function jsAttrArg(value)")
    preceding = html[max(0, idx - 1500) : idx]
    # Mention escapeHtml limitation + JS-string-context
    assert "escapeHtml" in preceding, "Doc should reference the escapeHtml bug it fixes"
    assert "onclick" in preceding, "Doc should mention the onclick use-case"


def test_escape_html_still_works_for_non_attribute_contexts():
    """escapeHtml bleibt der Default für innerHTML/textContent.
    jsAttrArg ist nur für dynamische JS-Argumente in HTML-Attributen."""
    html = _html()
    # escapeHtml soll weiter existieren
    assert "function escapeHtml(value)" in html
    # und immer noch &#39; für single quotes ausgeben (Standard-Behavior)
    body = _function_body("escapeHtml")
    assert "&#39;" in body
