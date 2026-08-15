"""Source-level contracts for direct-property scope and listed-RE defaults."""
from __future__ import annotations

import re
from pathlib import Path


HTML_PATH = (
    Path(__file__).resolve().parents[2]
    / "5eyes-electron"
    / "frontend"
    / "5eyes_v2.html"
)


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def test_direct_real_estate_editor_locks_scope_and_payload_fails_safe():
    html = _html()
    editor = html.split("function showAwFields(val) {", 1)[1].split(
        "// ─── ADMIN TOOLS", 1
    )[0]
    property_branch = re.search(
        r"(?:if|else\s+if)\s*\(\s*val\s*===\s*['\"]Immobilien['\"]\s*\)"
        r"\s*\{(?P<body>.*?)\}",
        editor,
        flags=re.DOTALL,
    )

    assert property_branch, "Immobilien need an explicit, non-editable scope branch"
    branch_body = property_branch.group("body")
    assert "Anderes Vermögen" in branch_body
    assert "disabled" in branch_body

    payload_builder = html.split(
        "function buildWealthPositionPayload(cat,typ,note){", 1
    )[1].split("async function saveWealthPosition()", 1)[0]
    assignment_setup = payload_builder.split("var akt=", 1)[0]
    assert "posType==='Immobilien'" in assignment_setup
    assert "'Anderes Vermögen'" in assignment_setup


def test_frontend_listed_real_estate_defaults_match_backend_450_bps():
    html = _html()
    cma_defaults = html.split("var ADMIN_CMA_DEFAULTS = {", 1)[1].split("};", 1)[0]
    subasset_defaults = html.split(
        "var ADMIN_CMA_SUBASSET_DEFAULTS = [", 1
    )[1].split("];", 1)[0]
    projection_inputs = html.split("function wealthProjectionInputs(scope){", 1)[1].split(
        "function cashflowProjectionComponents(row){", 1
    )[0]

    assert re.search(r"real_estate_ch_return_bps\s*:\s*450\b", cma_defaults)
    assert re.search(
        r"name:\s*['\"]Immobilien Schweiz['\"].*?"
        r"expected_return_bps:\s*450\b",
        subasset_defaults,
        flags=re.DOTALL,
    )
    assert "ADMIN_CMA_DEFAULTS.real_estate_ch_return_bps||450" in projection_inputs
    assert "ADMIN_CMA_DEFAULTS.real_estate_ch_return_bps||330" not in projection_inputs
