"""Source-level contracts for direct-property scope and listed-RE defaults."""
from __future__ import annotations

import re
from pathlib import Path
from tests.monolith_source import read_monolith_bundle  # H3/I-04: inkl. ausgelagerter Teile


HTML_PATH = (
    Path(__file__).resolve().parents[2]
    / "ares-desktop"
    / "frontend"
    / "ares.html"
)


def _html() -> str:
    return read_monolith_bundle()


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
    # PROPERTY-UI-PROJECTION-001 (2026-09-14): Signatur um years erweitert.
    projection_inputs = html.split("function wealthProjectionInputs(scope,years){", 1)[1].split(
        "function cashflowProjectionComponents(row){", 1
    )[0]

    assert re.search(r"real_estate_ch_return_bps\s*:\s*450\b", cma_defaults)
    assert re.search(
        r"name:\s*['\"]Immobilien Schweiz['\"].*?"
        r"expected_return_bps:\s*450\b",
        subasset_defaults,
        flags=re.DOTALL,
    )
    # H9 Nachtrag 2: die IST-Projektion rechnet nicht mehr mit Client-
    # Konstanten, sondern mit der Server-CMA (real_estate aus der wirksamen
    # CMA-Version, gleiche Quelle wie das Backend). Kein Fallback auf 330/450.
    assert "ADMIN_CMA_DEFAULTS" not in projection_inputs
    assert "realEstate:Number(_srvRet&&_srvRet.real_estate||0)" in projection_inputs
