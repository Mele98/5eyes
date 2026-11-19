"""N-875-02: Der Release-Preflight prueft externe CDN-/Font-Verweise in ALLEN
lokal von ares.html eingebundenen Dateien (inkl. @import/url() in ares.css),
nicht nur in ares.html.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

DESKTOP_ROOT = Path(__file__).resolve().parents[2] / "ares-desktop"
FRONTEND = DESKTOP_ROOT / "frontend"
MODULE = DESKTOP_ROOT / "scripts" / "frontend-external-refs.js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node nicht verfuegbar")


def _scan(frontend_dir: Path) -> list[dict]:
    script = (
        "const m=require(process.argv[1]);"
        "console.log(JSON.stringify(m.findExternalFrontendReferences(process.argv[2])));"
    )
    proc = subprocess.run(
        [NODE, "-e", script, str(MODULE), str(frontend_dir)],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _mirror(tmp_path: Path) -> Path:
    target = tmp_path / "frontend"
    shutil.copytree(FRONTEND, target, ignore=shutil.ignore_patterns("reporting", "node_modules"))
    return target


def test_real_frontend_has_no_external_references():
    assert _scan(FRONTEND) == []


def test_import_in_extracted_stylesheet_is_flagged(tmp_path):
    mirror = _mirror(tmp_path)
    css = mirror / "ares.css"
    css.write_text(
        "@import url(https://fonts.googleapis.com/css2?family=X);\n" + css.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    found = {(f["file"], f["marker"]) for f in _scan(mirror)}
    assert ("ares.css", "fonts.googleapis.com") in found
    assert ("ares.css", "@import") in found


def test_external_url_in_stylesheet_without_known_marker_is_flagged(tmp_path):
    mirror = _mirror(tmp_path)
    css = mirror / "ares.css"
    css.write_text(css.read_text(encoding="utf-8") + "\n.x{background:url(//cdn.example.org/a.png)}\n", encoding="utf-8")
    assert {"file": "ares.css", "marker": "url(extern)"} in _scan(mirror)


def test_cdn_marker_in_extracted_script_is_flagged(tmp_path):
    mirror = _mirror(tmp_path)
    js = mirror / "goal-review-runtime.js"
    js.write_text(js.read_text(encoding="utf-8") + "\n// https://cdn.jsdelivr.net/npm/x\n", encoding="utf-8")
    assert {"file": "goal-review-runtime.js", "marker": "cdn.jsdelivr.net"} in _scan(mirror)


def test_release_check_uses_the_shared_scanner():
    src = (DESKTOP_ROOT / "scripts" / "release-check.js").read_text(encoding="utf-8")
    assert "require('./frontend-external-refs.js')" in src
    assert "findExternalFrontendReferences(path.join(projectRoot, 'frontend'))" in src
    assert "frontendHtml.includes(marker)" not in src
