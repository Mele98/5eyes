"""U-35 snapshot contracts for the 5eyes_v2.html monolith.

The goal is not to bless the monolith forever. The snapshot is a safety net:
module-split PRs must explicitly update the inventory when they change ids,
inline handlers, functions, modal structures, or section boundaries.
"""
from __future__ import annotations

import difflib
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from audit_html_monolith import build_inventory  # noqa: E402

SNAPSHOT_PATH = REPO_ROOT / "docs" / "audits" / "2026-06-02-monolith-inventory.json"
HTML_PATH = REPO_ROOT / "5eyes-electron" / "frontend" / "5eyes_v2.html"


def _load_snapshot() -> dict:
    assert SNAPSHOT_PATH.exists(), f"Inventory snapshot fehlt: {SNAPSHOT_PATH}"
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


def test_monolith_inventory_snapshot_matches_current_html():
    expected = _load_snapshot()
    actual = build_inventory(HTML_PATH)
    if actual == expected:
        return

    expected_json = json.dumps(expected, ensure_ascii=False, indent=2, sort_keys=True)
    actual_json = json.dumps(actual, ensure_ascii=False, indent=2, sort_keys=True)
    diff = "\n".join(difflib.unified_diff(
        expected_json.splitlines(),
        actual_json.splitlines(),
        fromfile="snapshot",
        tofile="current",
        lineterm="",
        n=2,
    ))
    pytest.fail(
        "5eyes_v2.html inventory drift detected.\n"
        f"{_summarize_inventory_drift(expected, actual)}\n\n"
        f"{diff[:12000]}"
    )


def test_monolith_inventory_snapshot_has_required_buckets():
    snapshot = _load_snapshot()
    assert snapshot["source_path"] == "5eyes-electron/frontend/5eyes_v2.html"
    assert set(snapshot["counts"]) == {
        "ids",
        "event_handlers",
        "js_functions",
        "css_selectors",
        "modal_structures",
        "sub_sections",
        "style_blocks",
        "script_blocks",
    }
    assert snapshot["counts"]["ids"] > 500
    assert snapshot["counts"]["event_handlers"] > 250
    assert snapshot["counts"]["js_functions"] > 500
    assert snapshot["counts"]["css_selectors"] > 500
    assert snapshot["counts"]["modal_structures"] > 25
    assert snapshot["counts"]["sub_sections"] > 20


def test_monolith_inventory_tracks_known_refactor_anchors():
    snapshot = _load_snapshot()
    ids = {row["id"] for row in snapshot["ids"]}
    functions = {row["name"] for row in snapshot["js_functions"]}
    sections = {row["id"] for row in snapshot["sub_sections"]}

    assert {"aa-action-list", "bt-res-daily", "sec-returns"} <= ids
    assert {"calculateInvestmentStrategy", "btRunBacktest", "loadAdminAnnualReturns"} <= functions
    assert {"sec-returns", "sec-shadow-comparison-aggregate"} <= sections


def _summarize_inventory_drift(expected: dict, actual: dict) -> str:
    lines = ["Summary:"]
    lines.append(f"  counts expected={expected.get('counts')} actual={actual.get('counts')}")
    for label, key, field in (
        ("ids", "ids", "id"),
        ("functions", "js_functions", "name"),
        ("sections", "sub_sections", "id"),
        ("modals", "modal_structures", "id"),
    ):
        before = {str(row.get(field, "")) for row in expected.get(key, []) if row.get(field)}
        after = {str(row.get(field, "")) for row in actual.get(key, []) if row.get(field)}
        removed = sorted(before - after)
        added = sorted(after - before)
        if not removed and not added:
            continue
        lines.append(f"  {label}: removed={removed[:30]} added={added[:30]}")
    return "\n".join(lines)
