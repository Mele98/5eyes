"""AA-UX-FORMAT-001 -- EIN Zahlenformat fuer App und Report (UX-Audit Befund 13).

Vorher: Rendite/Vola/CAGR mit toFixed(2) (Monte-Carlo-Werte auf 0.01 %
genau = Scheingenauigkeit), formatBpsPercent sprang zwischen 0 und 1
Nachkommastelle ("-12%" neben "-8.4%"), Minus mal "-" mal "−", Report mit
Leerzeichen vor "%", App ohne, Band-Editor zeigte das IST roh.

Dieser Test fuehrt DIESELBE Falltabelle
(reporting/src/lib/format.contract.json) gegen
* die echten Monolith-Funktionen (fmtNumber/fmtPct/fmtSignedPct/fmtProbPct/
  fmtSharpe/formatCompactCHF) und
* die echte Report-Implementierung reporting/src/lib/format.ts (Node mit
  Type-Stripping)
aus. Weicht eine Seite ab, ist der Test rot.
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
FORMAT_TS = ROOT / "5eyes-electron" / "frontend" / "reporting" / "src" / "lib" / "format.ts"
CONTRACT = ROOT / "5eyes-electron" / "frontend" / "reporting" / "src" / "lib" / "format.contract.json"

_MONO_FNS = (
    "fmtNumber", "fmtPct", "fmtSignedPct", "fmtProbPct", "fmtSharpe",
    "formatCompactCHFAmount", "formatCompactCHF",
    "formatBpsPercent", "formatSignedBpsPercent", "formatRiskLossBps",
    "formatProbabilityPct", "formatRappen", "formatSignedRappen",
    "dcFmtPct", "btFormatPctBps", "btSignedPctBps",
)


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def _extract_function(src: str, name: str) -> str:
    match = re.search(r"\nfunction " + re.escape(name) + r"\(", src)
    assert match, f"Funktion {name} fehlt im Monolithen"
    start = match.start() + 1
    i = src.index("{", start)
    depth, j = 1, i + 1
    while depth:
        depth += {"{": 1, "}": -1}.get(src[j], 0)
        j += 1
    return src[start:j]


def _contract():
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def _node():
    if shutil.which("node") is None:
        pytest.skip("node not available")


_RUNNER = r"""
var C=__CONTRACT__;
var out={cases:C.cases.map(function(c){return __fns[c[0]].apply(null,c[1]);}),
         compact:C.compact_chf_cases.map(function(c){return __compact(c[0]);})};
process.stdout.write(JSON.stringify(out));
"""


def _run_monolith(extra_js: str = ""):
    _node()
    html = _html()
    fns = "\n".join(_extract_function(html, n) for n in _MONO_FNS)
    body = (
        fns
        + "\nvar __fns={fmtPct:fmtPct,fmtSignedPct:fmtSignedPct,fmtProbPct:fmtProbPct,fmtSharpe:fmtSharpe,fmtNumber:fmtNumber};"
        + "\nvar __compact=formatCompactCHF;\n"
    )
    if extra_js:
        script = body + "process.stdout.write(JSON.stringify((function(){" + extra_js + "})()));"
    else:
        script = body + _RUNNER.replace("__CONTRACT__", json.dumps(_contract()))
    proc = subprocess.run(["node", "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _run_report(tmp_path: Path):
    _node()
    runner = tmp_path / "run_contract.mts"
    runner.write_text(
        "import * as F from " + json.dumps(FORMAT_TS.as_uri()) + ";\n"
        "const C = " + json.dumps(_contract()) + ";\n"
        "const fns: Record<string, (...a: unknown[]) => string> = F as never;\n"
        "const out = {cases: C.cases.map((c: [string, unknown[], string]) => fns[c[0]](...c[1])),"
        " compact: C.compact_chf_cases.map((c: [number, string]) => F.fmtChfCompact(c[0]))};\n"
        "process.stdout.write(JSON.stringify(out));\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        ["node", "--experimental-strip-types", "--no-warnings", str(runner)],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    if proc.returncode != 0 and "strip-types" in proc.stderr:
        pytest.skip("Node ohne Type-Stripping")
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_monolith_matches_contract():
    c = _contract()
    out = _run_monolith()
    assert out["cases"] == [case[2] for case in c["cases"]]
    assert out["compact"] == [case[1] for case in c["compact_chf_cases"]]


def test_report_matches_contract_and_monolith(tmp_path):
    c = _contract()
    rep = _run_report(tmp_path)
    assert rep["cases"] == [case[2] for case in c["cases"]]
    assert rep["compact"] == [case[1] for case in c["compact_chf_cases"]]
    assert rep == _run_monolith()


def test_legacy_monolith_formatters_follow_contract():
    out = _run_monolith(
        "return {"
        "a:formatBpsPercent(1200), b:formatBpsPercent(840), c:formatBpsPercent(null),"
        "d:formatSignedBpsPercent(-1200), e:formatSignedBpsPercent(0), f:formatSignedBpsPercent(250),"
        "g:formatRiskLossBps(1830), h:formatRiskLossBps(0), i:formatProbabilityPct(73.4),"
        "j:formatSignedRappen(-1234500), k:dcFmtPct(1234), l:btFormatPctBps(1234,0),"
        "m:btSignedPctBps(-56), n:formatRappen(-500000)"
        "};"
    )
    nb, mi = " ", "−"
    assert out["a"] == f"12.0{nb}%"  # vorher "12%" -- springende Nachkommastellen
    assert out["b"] == f"8.4{nb}%"
    assert out["c"] == f"0.0{nb}%"
    assert out["d"] == f"{mi}12.0{nb}%"
    assert out["e"] == f"0.0{nb}%"
    assert out["f"] == f"+2.5{nb}%"
    assert out["g"] == f"{mi}18.3{nb}%"  # vorher "-18.3%"
    assert out["h"] == f"0.0{nb}%"
    assert out["i"] == f"73{nb}%"
    assert out["j"].startswith(mi + "CHF ")
    assert out["k"] == f"12.3{nb}%"
    assert out["l"] == f"12{nb}%"
    assert out["m"] == f"{mi}0.6{nb}%"
    assert out["n"].startswith("CHF " + mi)
    for v in out.values():
        assert "-" not in v, v


# ---------------------------------------------------------------------------
# Quelltext-Vertrag: keine Scheingenauigkeit, kein rohes Band-Editor-IST
# ---------------------------------------------------------------------------

_AA_RESULT_IDS = (
    "aa-proj-vol", "aa-proj-current-vol", "aa-proj-p50-return", "aa-proj-current-p50-return",
    "aa-proj-cagr", "aa-proj-current-cagr", "ub-cagr-ist", "ub-cagr-opt",
    "ub-return-rein", "ub-return-beratung", "aa-proj-current-metric", "aa-proj-target-metric",
)


def test_simulation_returns_and_volatility_have_one_decimal():
    html = _html()
    for el_id in _AA_RESULT_IDS:
        lines = re.findall(r"setText\('" + re.escape(el_id) + r"',[^\n]*", html)
        assert lines, el_id
        for line in lines:
            assert "toFixed(2)" not in line, line
            if "/100" in line or "fmtPct(" in line or "Bps" in line or "_bps" in line or "Vol" in line:
                assert "fmtPct(" in line and ",1)" in line, line


def test_band_editor_ist_not_raw():
    html = _html()
    assert '<div class="qti">${r.ist}%</div>' not in html
    assert '<div class="qti">${fmtPct(Number(r.ist||0)*100,1)}</div>' in html


def test_compact_chf_always_mio_with_period():
    html = _html()
    assert "' Mio'" not in html
    # Rebalancing-Delta: Apostroph als Dezimalzeichen ("CHF 2'85 Mio.") entfernt
    assert ".toFixed(2).replace('.',\"'\")" not in html


def test_number_cells_use_tabular_nums():
    html = _html()
    assert re.search(r"table td,table th,\.num[^{]*\{font-variant-numeric:tabular-nums;\}", html)
    assert ".num{text-align:right;}" in html
