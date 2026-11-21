"""P5c Fixrunde 1 (CTO-Entscheid 9, 2026-11-21): Strategietreue ohne Ausnahme.

Der alte Entwickler-Schalter Auto-Recompute (``AUTO_RECOMPUTE_ENABLED`` bzw.
localStorage ``'auto_recompute'='1'``, ``scheduleAutoRecompute`` aus
``markStrategyDirty``) ist entfernt. Eine neue Strategie entsteht nur durch den
ausdruecklichen Klick «Anlagestrategie berechnen» (bzw. bei 404 = noch nie
berechnet). Vorher pinnte diese Datei das Gegenteil (Schalter vorhanden,
markStrategyDirty ruft scheduleAutoRecompute).

Gegenprobe: alter Stand (Schalter vorhanden) -> ``test_auto_recompute_switch_is_gone``
rot; mit ``localStorage auto_recompute=1`` auf Seite ``al`` loeste
``markStrategyDirty`` nach 800 ms ``calculateInvestmentStrategy`` aus.
"""
from __future__ import annotations

import re

from tests.livetest_monolith_js import has_function, html, run_js


def test_auto_recompute_switch_is_gone():
    src = html()
    assert not has_function("scheduleAutoRecompute", src)
    for token in ("scheduleAutoRecompute", "AUTO_RECOMPUTE_ENABLED", "AUTO_RECOMPUTE_DEBOUNCE_MS",
                  "_autoRecomputeTimer"):
        assert token not in src, token
    assert not re.search(r"Storage\s*\.\s*getItem\(\s*['\"]auto_recompute['\"]", src)


def test_mark_strategy_dirty_never_starts_a_recompute():
    """Echtes ``markStrategyDirty`` in Node: selbst mit dem alten Schalter
    (localStorage ``auto_recompute=1``) auf der Seite Asset-Allokation startet
    es weder einen Timer noch ``calculateInvestmentStrategy`` noch generate."""
    prelude = r"""
var calls=[];
var localStorage={getItem:function(k){return k==='auto_recompute'?'1':null;},setItem:function(){},removeItem:function(){}};
var AUTO_RECOMPUTE_ENABLED=true;
var strategyState={loading:false,dirty:false,staleNotice:null};
function setTimeout(fn){calls.push(['timer']);fn();return 1;}
function clearTimeout(){}
function getActiveMandateId(){return 'm1';}
function isDemoMandateId(){return false;}
function activePageKey(){return 'al';}
function calculateInvestmentStrategy(){calls.push(['calculate']);}
function refreshStrategyData(){calls.push(['refresh']);return Promise.resolve(true);}
var API={post:function(u){calls.push(['post',String(u)]);return Promise.resolve({});}};
function clearPendingStrategyOutputs(){}
function hasVisibleStrategyOutputs(){return true;}
function invalidateStrategyOutputs(){}
function syncPortfolioUmsetzenButtonVisibility(){}
function updateStrategyStatus(){}
function syncStrategyStaleView(){}
"""
    out = run_js(["markStrategyDirty"], r"""
markStrategyDirty('Bandbreiten geändert',true);
markStrategyDirty('Präferenzen geändert',false);
return {calls:calls, dirty:strategyState.dirty, notice:strategyState.staleNotice};
""", prelude=prelude)
    assert out["calls"] == [], out
    assert out["dirty"] is True and out["notice"] == "Präferenzen geändert", out
