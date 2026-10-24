"""Echte Fragebogen-Funktionen des Monolithen in Node (minimaler DOM-Ersatz).

Gemeinsam genutzt von den Paritaetstests Frontend <-> Server.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from tests.risk_fixture_helpers import MONOLITH_PATH

NODE = shutil.which("node")

FUNCTIONS = (
    "function riskScoreRounded(",
    "function riskScoreToProfile(",
    "function findRiskCapacityBand(",
    "function riskWillingnessProfile(",
    "function normalizeRiskText(",
    "function canonicalRiskHorizonLabel(",
    "function displayRiskHorizonLabel(",
    "function riskOptionText(",
    "function selectRiskOptionByLabel(",
    "function collectRiskAssessmentUiIssues(",
    "function buildRiskAssessmentPayloadFromUI(",
)


def _function(src: str, signature: str) -> str:
    start = src.index(signature)
    i = src.index("{", start + len(signature) - 1)
    depth, j = 1, i + 1
    while depth:
        depth += {"{": 1, "}": -1}.get(src[j], 0)
        j += 1
    return src[start:j]


def monolith_js() -> str:
    src = MONOLITH_PATH.read_text(encoding="utf-8")
    start = src.index("var RISK_HORIZON_OPTIONS = [")
    end = src.index("var RISK_RHYTHM_POINTS = [10, 5, 0];") + len("var RISK_RHYTHM_POINTS = [10, 5, 0];")
    return src[start:end] + "\n" + "\n".join(_function(src, sig) for sig in FUNCTIONS)


DOM = r"""
var currentMandateData = null;
function fakeOpt(text){
  var cls = new Set();
  return { textContent: text, querySelector: function(){ return { textContent: text }; },
           classList: { add: function(c){ cls.add(c); }, remove: function(c){ cls.delete(c); },
                        contains: function(c){ return cls.has(c); } } };
}
function fakeSection(texts){
  var opts = texts.map(fakeOpt);
  return { querySelectorAll: function(){ return opts; }, opts: opts };
}
"""


def run_node(script: str) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "run.js"
        path.write_text(script, encoding="utf-8")
        proc = subprocess.run([NODE, str(path)], capture_output=True, text=True, encoding="utf-8", timeout=300)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout
