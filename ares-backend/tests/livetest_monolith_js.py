"""Hilfen fuer die Live-Test-2026-11-Regressionstests: echte Funktionen aus
dem Monolithen (ares.html) in Node ausfuehren, mit minimalem DOM-Ersatz.

Bewusst wie ``test_aa_view_numbers_and_labels._run``: die Funktionen werden
aus dem aktuellen Quelltext extrahiert, nicht nachgebaut.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from tests.monolith_source import read_monolith_bundle  # H3/I-04: inkl. ausgelagerter Teile

HTML_PATH = Path(__file__).resolve().parents[2] / "ares-desktop" / "frontend" / "ares.html"


def html() -> str:
    return read_monolith_bundle()


def has_function(name: str, src: str | None = None) -> bool:
    return re.search(r"\n(?:async )?function " + re.escape(name) + r"\(", src or html()) is not None


def extract_function(src: str, name: str) -> str:
    match = re.search(r"\n(?:async )?function " + re.escape(name) + r"\(", src)
    assert match, f"Funktion {name} fehlt im Monolithen"
    start = match.start() + 1
    i = src.index("{", start)
    depth, j = 1, i + 1
    in_str = None
    while depth:
        ch = src[j]
        if in_str:
            if ch == "\\":
                j += 2
                continue
            if ch == in_str:
                in_str = None
        elif ch in ("'", '"'):
            in_str = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        j += 1
    return src[start:j]


FAKE_DOM = r"""
var __els={};
function __mkEl(id){
  return {id:id,textContent:'',innerHTML:'',title:'',style:{},className:'',dataset:{},disabled:false,
    previousElementSibling:null,
    classList:{add:function(){},remove:function(){},toggle:function(){},contains:function(){return false;}},
    setAttribute:function(k,v){this['attr_'+k]=String(v);},
    getAttribute:function(k){return this['attr_'+k]==null?null:this['attr_'+k];},
    querySelector:function(){return null;},querySelectorAll:function(){return [];}};
}
var document={
  getElementById:function(id){if(!__els[id])__els[id]=__mkEl(id);return __els[id];},
  querySelector:function(sel){return document.getElementById('qs:'+sel);},
  querySelectorAll:function(){return [];}
};
var window={};
function escapeHtml(s){return String(s==null?'':s);}
function setText(id,v){document.getElementById(id).textContent=String(v);}
function fmtLocaleCH(n){var s=String(Math.round(Math.abs(Number(n)||0)));return (Number(n)<0?'-':'')+s.replace(/\B(?=(\d{3})+(?!\d))/g,"'");}
function formatRappen(r){return 'CHF '+fmtLocaleCH(Number(r||0)/100);}
function formatCompactCHF(chf){return 'CHF '+fmtLocaleCH(chf);}
function fmtPct(v,d){return Number(v).toFixed(d==null?1:d)+' %';}
"""


def run_js(names, scenario_js: str, *, prelude: str = "", optional: tuple[str, ...] = ()):
    if shutil.which("node") is None:
        pytest.skip("node not available")
    src = html()
    parts = [extract_function(src, n) for n in names]
    parts += [extract_function(src, n) for n in optional if has_function(n, src)]
    script = (FAKE_DOM + prelude + "\n" + "\n".join(parts)
              + "\nvar __out=(function(){" + scenario_js + "})();\n"
              + "Promise.resolve(__out).then(function(v){process.stdout.write(JSON.stringify(v));})"
              + ".catch(function(e){console.error(e&&e.stack||e);process.exit(3);});")
    proc = subprocess.run(["node", "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)
