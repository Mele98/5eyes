"""Kern-Integration R4: Depot-/Vorsorge-Aufteilung, Oberflaeche = Server.

N-917R3-08 (CTO-Entscheid): die Summe der Aufteilung muss nach kaufmaennischer
Rundung auf 0.1 % genau 100.0 % sein. Die UI-Pruefung in
``buildWealthPositionPayload`` (ares.html, unveraendert extrahiert, in Node)
und ``schemas.wealth.allocation_total_is_100`` (auf die bps, die die UI
tatsaechlich sendet) muessen fuer jede Eingabe dasselbe Urteil faellen --
fuer Depot und fuer Vorsorge (Vorsorge zusaetzlich: ganz leer ist gueltig).
"""
from __future__ import annotations

import json
import random

from schemas.wealth import allocation_total_is_100
from tests.livetest_monolith_js import run_js

FIELDS = ("alloc_equities_bps", "alloc_bonds_bps", "alloc_real_estate_bps",
          "alloc_liquidity_bps", "alloc_alternatives_bps")

PRELUDE = """
  var V=[0,0,0,0,0];
  var IDS=['sc-akt','sc-obl','sc-imm','sc-liq','sc-alt'];
  function getInputValue(id){var i=IDS.indexOf(id);if(i>=0)return String(V[i]);
    if(/label$/.test(id))return 'Position';if(/value$/.test(id))return '1000';return '';}
  function getCheckboxValue(){return false;}
  var AresRounding={formatPercent:function(v){return String(v)+' %';}};
  var currentWealthEditId=null,currentWealthPositions=[];function newRecordCurrency(){return 'CHF';}
  function parseCHF(v){return Number(v||0)*100;} function parsePercentToBps(){return null;}
  function joinNotes(a){return a.filter(Boolean).join(' ');}
"""

# Grenzfaelle: 99.95/100.04 (gueltig), 99.94/100.05 (ungueltig), Gleitkomma-
# Summen, die knapp unter x.x5 landen (33.32+33.32+33.31 = 99.95), 3 x 33.33.
EDGE = [
    [33.33, 33.33, 33.34, 0, 0], [33.33, 33.33, 33.33, 0, 0], [33.32, 33.32, 33.31, 0, 0],
    [33.32, 33.32, 33.30, 0, 0], [50, 49.95, 0, 0, 0], [50, 49.94, 0, 0, 0],
    [50, 50.04, 0, 0, 0], [50, 50.05, 0, 0, 0], [50, 49.9, 0, 0, 0], [50, 50.4, 0, 0, 0],
    [19.99, 20.01, 19.98, 20.0, 19.97], [20.01, 20.01, 20.01, 20.01, 20.0],
    [10.1, 20.2, 30.3, 39.35, 0], [10.1, 20.2, 30.3, 39.45, 0], [100, 0, 0, 0, 0],
    [0.01, 0, 0, 0, 0], [99.95, 0, 0, 0, 0], [100.05, 0, 0, 0, 0],
]


def _random_cases(n=400, seed=917):
    rnd = random.Random(seed)
    out = []
    for _ in range(n):
        target = rnd.choice([9990, 9994, 9995, 9996, 9999, 10000, 10001, 10004, 10005, 10006])
        cuts = sorted(rnd.randint(0, target) for _ in range(4))
        parts = [b - a for a, b in zip([0] + cuts, cuts + [target])]
        out.append([p / 100 for p in parts])
    return out


def _ui_verdicts(cat, cases):
    js = (
        "var C=" + json.dumps(cases) + ";var out=[];"
        "for(var k=0;k<C.length;k++){V=C[k];"
        " try{var p=buildWealthPositionPayload('" + cat + "','Beratungsvermögen','');"
        "  out.push({ok:true,bps:[p.alloc_equities_bps,p.alloc_bonds_bps,p.alloc_real_estate_bps,"
        "   p.alloc_liquidity_bps,p.alloc_alternatives_bps]});}"
        " catch(e){out.push({ok:false,msg:String(e.message)});}}"
        "return out;"
    )
    return run_js(("buildWealthPositionPayload", "aresSplitIs100"), js, prelude=PRELUDE)


def _bps(values):
    # wie die UI sendet: Math.round(x*100) je Feld (Werte hier ohne .5-Bruchteile)
    return [int(round(v * 100)) for v in values]


def _assert_parity(cat, cases, *, empty_ok):
    ui = _ui_verdicts(cat, cases)
    mismatches = []
    for values, verdict in zip(cases, ui):
        if not verdict["ok"]:
            assert "100%" in verdict["msg"], (values, verdict["msg"])  # nur die Aufteilungsregel
        total = sum(_bps(values))
        server_ok = (empty_ok and total == 0) or allocation_total_is_100(total)
        if verdict["ok"] != server_ok:
            mismatches.append((values, total, verdict))
    assert not mismatches, mismatches[:5]


def test_depot_split_ui_equals_server_on_edge_cases():
    _assert_parity("Depot", EDGE, empty_ok=True)  # Depot leer: UI ohne Pruefung, Server: KN3-B-Regel separat


def test_depot_split_ui_equals_server_on_random_sums():
    _assert_parity("Depot", _random_cases(), empty_ok=True)


def test_pension_split_ui_equals_server_on_edge_and_random_sums():
    _assert_parity("Vorsorge", EDGE + _random_cases(seed=4) + [[0, 0, 0, 0, 0]], empty_ok=True)


def test_server_rule_boundaries():
    assert [allocation_total_is_100(t) for t in (9994, 9995, 10000, 10004, 10005)] == [
        False, True, True, True, False]
