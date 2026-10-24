"""TOTAL-WEALTH-LIABILITY-001 (2026-10-21): Monolith zieht ALLE Verbindlichkeiten ab.

Ergaenzt den Codex-Reproducer
``test_2026_10_16_total_wealth_liability_publication_adversarial.py``:

- Liability-Serie = Spiegel von Backend ``_build_external_foundation_projection``:
  jede aktive Position mit assignment 'Verbindlichkeit'; nur Hypotheken
  amortisieren (direkt/indirekt), uebrige Schulden bleiben konstant, auch
  wenn sie (faelschlich) ein Amortisationsfeld tragen.
- Klassischer Reinvermoegens-Kontext zeigt das Netto-Fundament und weist
  ungedeckte Schulden aus.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HTML_PATH = ROOT / "ares-desktop" / "frontend" / "ares.html"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node fehlt")


def _extract_js_function(source: str, name: str) -> str:
    marker = f"function {name}("
    start = source.index(marker)
    brace = source.index("{", start)
    depth = 0
    quote: str | None = None
    escaped = False
    for idx in range(brace, len(source)):
        char = source[idx]
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in ("'", '"', "`"):
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : idx + 1]
    raise AssertionError(f"unterminated JavaScript function {name}")


def _run_node(tmp_path: Path, script: str) -> dict:
    path = tmp_path / "contract.js"
    path.write_text(script, encoding="utf-8")
    completed = subprocess.run(
        ["node", str(path)], check=True, capture_output=True, text=True, encoding="utf-8", timeout=30
    )
    return json.loads(completed.stdout)


def test_liability_series_includes_all_debts_and_only_mortgages_amortize(tmp_path):
    html = HTML_PATH.read_text(encoding="utf-8")
    helper = _extract_js_function(html, "mortgageLiabilityAndPledgedSeriesRappen")
    script = helper + """
const positions = [
  {position_type:'Hypothek', assignment:'Verbindlichkeit', current_value_rappen:30000000,
   mortgage_amortization_type:'Direkt', mortgage_amortization_rappen:1000000},
  {position_type:'Hypothek', assignment:'Verbindlichkeit', current_value_rappen:10000000,
   mortgage_amortization_type:'Indirekt (Säule 3a)', mortgage_amortization_rappen:500000},
  // Privatkredit mit irrefuehrendem Amortisationsfeld: bleibt konstant (Backend: is_mortgage-Gate).
  {position_type:'Custom', assignment:'Verbindlichkeit', current_value_rappen:20000000,
   mortgage_amortization_type:'Direkt', mortgage_amortization_rappen:9000000},
  {position_type:'Liquidität', assignment:'Verbindlichkeit', current_value_rappen:3000000},
  // nicht zu zaehlen: inaktiv, geloescht, keine Verbindlichkeit
  {position_type:'Custom', assignment:'Verbindlichkeit', current_value_rappen:7000000, is_active:0},
  {position_type:'Custom', assignment:'Verbindlichkeit', current_value_rappen:7000000, deleted_at:'2026-01-01'},
  {position_type:'Depot', assignment:'Beratungsvermögen', current_value_rappen:99000000}
];
process.stdout.write(JSON.stringify(mortgageLiabilityAndPledgedSeriesRappen(positions, 2)));
"""
    result = _run_node(tmp_path, script)
    # Jahr 0: 300k + 100k + 200k + 30k = 630k
    assert result["liability"] == [63_000_000, 62_000_000, 61_000_000]
    assert result["pledged"] == [0, 500_000, 1_000_000]


def _donut_script(html: str, total_allocation: dict, total_wealth: int) -> str:
    sync = _extract_js_function(html, "syncAllocationDonutFromStrategyState")
    return (
        """
const rc = {innerHTML:'', style:{display:'none'}};
const document = {
  getElementById(id){ return id === 'alloc-rein-context' ? rc : null; },
  querySelector(){ return null; }
};
const charts = {dn:{data:{labels:[],datasets:[{data:[],backgroundColor:[]}]}, update(){}}};
const alloc = [{n:'Aktien', soll:1, c:'#000', chfTarget:0}];
const TOTAL = 0;
function buildDLegend(){}
function escapeHtml(v){ return String(v); }
function fmtPct(v){ return String(v); }
function fmtLocaleCH(v){ return String(v); }
const strategyState = {allocation:{buckets:[{}], advisory_wealth_rappen:10000000,
  total_wealth_rappen:%s, total_allocation:%s}};
%s
syncAllocationDonutFromStrategyState();
process.stdout.write(JSON.stringify({html: rc.innerHTML}));
"""
        % (json.dumps(total_wealth), json.dumps(total_allocation), sync)
    )


def test_classic_context_shows_net_foundation(tmp_path):
    html = HTML_PATH.read_text(encoding="utf-8")
    # Immobilie 800k, Hypothek 300k (foundation_rappen 500k); Kredit 200k > Finanz 100k
    # -> 100k belasten das Fundament -> netto 400k.
    payload = {
        "foundation_rappen": 50_000_000,
        "foundation_in_net_wealth_rappen": 40_000_000,
        "net_wealth_non_positive": False,
        "uncovered_liabilities_rappen": 0,
        "total_base_rappen": 40_000_000,
    }
    out = _run_node(tmp_path, _donut_script(html, payload, 40_000_000))["html"]
    assert "Eigenheim-Fundament CHF 400000" in out, out
    assert "CHF 500000" not in out, out
    assert "ungedeckte" not in out, out


def test_classic_context_surfaces_uncovered_debt(tmp_path):
    html = HTML_PATH.read_text(encoding="utf-8")
    payload = {
        "foundation_rappen": 0,
        "foundation_in_net_wealth_rappen": 0,
        "net_wealth_non_positive": True,
        "uncovered_liabilities_rappen": 3_000_000,
        "total_base_rappen": 0,
    }
    out = _run_node(tmp_path, _donut_script(html, payload, 0))["html"]
    assert "Reinvermögen (gesamt, netto aller Verbindlichkeiten): <strong>CHF 0</strong>" in out, out
    assert "Verbindlichkeiten übersteigen die Aktiven" in out, out
    assert "ungedeckte Schulden CHF 30000" in out, out
