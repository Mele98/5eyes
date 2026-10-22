"""LIQUIDITY-INSTRUMENT-MODEL-001: Die Electron-App zeigt keine rohen Quell-Codes.

``sub_asset_class_assumptions_reference[].source`` ist ein Maschinen-Code
(u.a. ``unapproved_code_default``). Der Monolith beschriftet bekannte Quellen
lesbar und Unbekanntes neutral als "Andere Quelle".
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HTML_PATH = ROOT / "5eyes-electron" / "frontend" / "5eyes_v2.html"

EXPECTED = {
    "unapproved_code_default": "Modellannahme (nicht IC-freigegeben)",
    "CMA Sub-Asset-Class": "Kapitalmarktannahme (Sub-Anlageklasse)",
    "Asset-Class fallback": "Kapitalmarktannahme (Anlageklasse)",
    "legacy_missing_unavailable": "Historisch nicht verfügbar",
    "irgendwas_neues": "Andere Quelle",
    "": "Andere Quelle",
    "__proto__": "Andere Quelle",
}


def _snippet() -> str:
    html = HTML_PATH.read_text(encoding="utf-8")
    labels = re.search(r"var SUB_ASSET_SOURCE_LABELS=\{[^\n]*\};", html)
    fn = re.search(r"function subAssetSourceLabel\(source\)\{[^\n]*\}", html)
    assert labels and fn
    return labels.group(0) + "\n" + fn.group(0)


def test_renderer_uses_label_function_not_raw_source() -> None:
    html = HTML_PATH.read_text(encoding="utf-8")
    start = html.index("function buildSubAssetClassAssumptionHtml(items){")
    body = html[start:html.index("\nfunction ", start + 10)]
    assert "subAssetSourceLabel(item.source)" in body
    assert "escapeHtml(item.source" not in body


@pytest.mark.skipif(shutil.which("node") is None, reason="node nicht verfuegbar")
def test_source_labels_are_readable() -> None:
    script = (
        _snippet()
        + "\nvar keys=" + json.dumps(list(EXPECTED)) + ";"
        + "\nvar out=keys.map(function(k){return subAssetSourceLabel(k);});"
        + "\nout.push(subAssetSourceLabel(null),subAssetSourceLabel(undefined));"
        + "\nprocess.stdout.write(JSON.stringify(out));"
    )
    result = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, encoding="utf-8", check=True
    )
    out = json.loads(result.stdout)
    for (key, label), got in zip(EXPECTED.items(), out):
        assert got == label, (key, got)
    assert out[-2:] == ["Andere Quelle", "Andere Quelle"]
