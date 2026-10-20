"""STALE-RESULT-DISPLAY-001 (UX-Audit Befund 12).

Nach einer Eingabeaenderung (markStrategyDirty) duerfen die noch sichtbaren
Ergebnisse der Asset-Allokation nicht gueltig aussehen:
- Ergebnis-Karten gedimmt (Klasse ``aa-stale`` auf #page-al),
- je Karte ein Badge "Stand: <Datum Uhrzeit> – nicht mehr aktuell",
- das Banner zeigt die konkrete Meldung des Aufrufers (nicht statisch),
- es gibt nur EINE Banner-Komponente (al-banner-warning, kein .strip-w).
Die Funktionen laufen hier echt in Node gegen ein Mini-DOM.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HTML_PATH = REPO_ROOT / "5eyes-electron" / "frontend" / "5eyes_v2.html"


def _function(src: str, signature: str) -> str:
    start = src.index(signature)
    i = src.index("{", start + len(signature) - 1)
    depth, j = 1, i + 1
    while depth:
        depth += {"{": 1, "}": -1}.get(src[j], 0)
        j += 1
    return src[start:j]


def _run(scenario: str) -> dict:
    if shutil.which("node") is None:
        pytest.skip("node binary not available to execute extracted JS")
    src = HTML_PATH.read_text(encoding="utf-8")
    fns = [
        _function(src, n)
        for n in (
            "function markStrategyDirty(",
            "function finalizeStrategyOutputs(",
            "function hasVisibleStrategyOutputs(",
            "function clearPendingStrategyOutputs(",
            "function strategyResultStampMs(",
            "function strategyStaleBadgeText(",
            "function syncStrategyStaleView(",
        )
    ]
    default_notice = [l for l in src.splitlines() if l.startswith("var STRATEGY_STALE_DEFAULT_NOTICE=")]
    assert len(default_notice) == 1
    harness = default_notice[0] + r"""
function el(cls){
  var node={children:[],style:{},textContent:'',
    set className(v){this.classList._s={};var cl=this.classList;String(v||'').split(' ').forEach(function(c){if(c)cl._s[c]=1;});},
    classList:{_s:{},contains:function(c){return !!this._s[c];},toggle:function(c,on){if(on)this._s[c]=1;else delete this._s[c];}},
    insertBefore:function(child){child.parentNode=node;node.children.unshift(child);},
    remove:function(){var p=this.parentNode;p.children=p.children.filter(function(x){return x!==node;});},
    set innerHTML(v){this.children=[];if(v==='<span></span>'){var s=el('');s.parentNode=node;this.children.push(s);}},
    get firstChild(){return this.children[0];}};
  (cls||'').split(' ').forEach(function(c){if(c)node.classList._s[c]=1;});
  return node;
}
var page=el('page');
var cards=[el('card alloc-donut-card'),el('card'),el('card')];
var banner=el('al-banner-warning'); var body=el('al-banner-body');
var document={
  getElementById:function(id){return id==='page-al'?page:id==='al-dirty-banner'?banner:id==='al-dirty-banner-body'?body:null;},
  createElement:function(){return el('');}
};
page.querySelectorAll=function(){return cards;};
var strategyState={allocation:null,dirty:false,lastGeneratedAt:0};
function syncPortfolioUmsetzenButtonVisibility(){}
function updateStrategyStatus(){}
function scheduleAutoRecompute(){}
function invalidateStrategyOutputs(){strategyState.allocation=null;}
function applyAllocationEngineResult(r){strategyState.allocation=r;}
function applyRecommendationEngineResult(){}
function badges(){return cards.map(function(c){var b=c.children.filter(function(x){return x.classList.contains('aa-stale-badge');})[0];return b?b.firstChild.textContent:null;});}
function snap(){return {dimmed:page.classList.contains('aa-stale'),banner:banner.style.display,body:body.textContent,badges:badges()};}
"""
    script = "\n".join(fns) + "\n" + harness + scenario
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
        fh.write(script)
        path = fh.name
    res = subprocess.run(
        ["node", path], capture_output=True, text=True, encoding="utf-8", timeout=30,
        env={"TZ": "Europe/Zurich", **__import__("os").environ},
    )
    Path(path).unlink(missing_ok=True)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout.strip().splitlines()[-1])


ALLOC = "{buckets:[{asset_class:'Aktien'}],target_allocation:{set_at:'2026-10-14T07:12:00.000Z'}}"


def test_dirty_with_visible_results_dims_cards_and_shows_caller_message():
    out = _run(
        "finalizeStrategyOutputs(" + ALLOC + ",null,false,null);\n"
        "var before=snap();\n"
        "markStrategyDirty('Bandbreiten aktualisiert: Strategie neu berechnen.');\n"
        "console.log(JSON.stringify({before:before,after:snap()}));\n"
    )
    assert out["before"]["dimmed"] is False
    assert out["before"]["banner"] == "none"
    assert out["before"]["badges"] == [None, None, None]
    after = out["after"]
    assert after["dimmed"] is True
    assert after["banner"] == "flex"
    # Text kommt aus dem message-Parameter, nicht aus einem statischen Sammeltext.
    assert after["body"] == "Bandbreiten aktualisiert: Strategie neu berechnen."
    # Stand = Zeitpunkt der angezeigten Berechnung (UTC 07:12 -> 09:12 Zuerich).
    assert after["badges"] == ["Stand: 14.10.2026 09:12 – nicht mehr aktuell"] * 3


def test_recalculation_clears_dimming_badges_and_banner():
    out = _run(
        "finalizeStrategyOutputs(" + ALLOC + ",null,false,null);\n"
        "markStrategyDirty('Risikoprofil gespeichert: Strategie neu berechnen.', true);\n"
        "finalizeStrategyOutputs(" + ALLOC + ",null,false,null);\n"
        "console.log(JSON.stringify(snap()));\n"
    )
    assert out == {"dimmed": False, "banner": "none", "body": "Risikoprofil gespeichert: Strategie neu berechnen.", "badges": [None, None, None]}


def test_dirty_without_visible_results_shows_banner_but_nothing_to_dim():
    out = _run(
        "markStrategyDirty('');\n"
        "console.log(JSON.stringify(snap()));\n"
    )
    assert out["banner"] == "flex"
    assert out["dimmed"] is False
    assert out["body"] == "Eingaben haben sich seit der letzten Berechnung geändert — bitte «Anlagestrategie berechnen» klicken."


def test_mandate_switch_drops_previous_stale_notice():
    out = _run(
        "finalizeStrategyOutputs(" + ALLOC + ",null,false,null);\n"
        "markStrategyDirty('Ziel gelöscht: Soll-Allokation bei Bedarf separat aktualisieren.', false);\n"
        "strategyState={allocation:null,recommendation:null,dirty:true,lastGeneratedAt:0};\n"
        "syncStrategyStaleView();\n"
        "console.log(JSON.stringify(snap()));\n"
    )
    assert out["banner"] == "none"
    assert out["dimmed"] is False


def test_single_banner_component_and_scoped_dim_css():
    html = HTML_PATH.read_text(encoding="utf-8")
    assert "strip-w" not in html
    banner = html.split('<div id="al-dirty-banner"', 1)[1].split(">", 1)[0]
    assert 'class="al-banner-warning' in banner
    assert 'id="al-dirty-banner-body"' in html
    assert "#page-al.aa-stale .alloc-top-grid>.card>:not(.aa-stale-badge)" in html
    assert "opacity:.5;filter:grayscale(.6)" in html
    # Planungsannahmen sind eine Eingabe, kein Ergebnis -> nicht gedimmt.
    assert ".g2>.card:not(#al-planning-card)" in html
    # Jeder Reset des Strategie-Zustands (Mandatswechsel) synchronisiert die Ansicht.
    resets = [l for l in html.splitlines() if l.strip().startswith("strategyState={allocation:null")]
    assert resets
    lines = html.splitlines()
    for idx, line in enumerate(lines):
        if line.strip().startswith("strategyState={allocation:null"):
            assert "syncStrategyStaleView()" in lines[idx + 1], line[:80]
