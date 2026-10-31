"""HANDOFF-PREVIEW-PARITY-001 / HANDOFF-NEWMONEY-UI-001 -- Handelsliste im Monolithen.

Die Handelsliste rechnete clientseitig aus ``live_rebalancing.position_drifts``
und zeigte nicht gehaltene Produkte ohne Kauf, waehrend der Snapshot der
Weiterleitung den Kauf enthielt. Jetzt zeigt sie nur die read-only
Server-Vorschau (dieselbe Funktion wie der Snapshot). Fehlt bei Neugeld die
Bestaetigung "kein bestehender Bestand", fragt der Dialog-Service (kein
nativer Dialog) danach; die Bestaetigung geht mit der Weiterleitung mit.

Die Logik liegt als Skriptmodul neben dem Monolithen (Monolith-Budget,
Toleranz 0). Das Modul laeuft hier in Node gegen ein minimales DOM.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND = REPO_ROOT / "ares-desktop" / "frontend"
HTML_PATH = FRONTEND / "ares.html"
MODULE_PATH = FRONTEND / "trade-list-preview.js"
PACKAGE_JSON = REPO_ROOT / "ares-desktop" / "package.json"

HARNESS = r"""
var calls={native:0,gets:[],om:[],confirms:[],handoffSections:0};
var window={confirm:function(){calls.native++;return true;}};
function confirm(){calls.native++;return true;}
var DOM={};
function el(id){if(!DOM[id])DOM[id]={id:id,innerHTML:''};return DOM[id];}
var document={getElementById:function(id){return el(id);}};
function om(id){calls.om.push(id);}
function escapeHtml(v){return String(v==null?'':v);}
function formatRappen(v){return 'R'+String(v);}
function formatBpsPercent(v){return 'B'+String(v);}
function formatCompactCHFAmount(v){return String(v);}
function getActiveMandateId(){return 'm-1';}
function renderPortfolioHandoffSection(){calls.handoffSections++;}
var _tlHandoffCtx=null;
// Clientseitige Live-Drifts duerfen NICHT mehr die Anzeige bestimmen.
var strategyState={recommendation:{run:{id:'r-1'},live_rebalancing:{live_total_value_rappen:1000000,
  position_drifts:[{product_name:'CLIENT-DRIFT',rebalance_amount_rappen:500000,rebalance_action_code:'BUY'}]}}};
var CONFIRM_RESULT=true;
async function uiConfirm(opts){calls.confirms.push(opts);return CONFIRM_RESULT;}
var PREVIEW={recommendation_run_id:'r-1',holdings_basis:'recorded_depot',confirm_no_existing_holdings:false,
  live_total_value_rappen:1000000,position_count:2,snapshot_sha256:'x',
  trades:[{product_name:'Neues Produkt C',rebalance_action_code:'BUY',rebalance_action:'Aufbauen',current_market_value_rappen:0,target_amount_rappen:200000,rebalance_amount_rappen:200000,target_weight_bps:2000},
          {product_name:'Produkt A',rebalance_action_code:'SELL',rebalance_action:'Reduzieren',current_market_value_rappen:600000,target_amount_rappen:500000,rebalance_amount_rappen:-100000,target_weight_bps:5000}]};
var FAIL_UNCONFIRMED=false;
var API={get:async function(url){calls.gets.push(url);
  if(FAIL_UNCONFIRMED&&url.indexOf('confirm_no_existing_holdings=false')>=0){
    var err=new Error('API 409');err.status=409;
    err.body=JSON.stringify({detail:{reason_code:'NO_HOLDINGS_CONFIRMATION_REQUIRED',message:'Kein erfasster Depotbestand.'}});
    throw err;}
  return PREVIEW;}};
"""


def _run(script: str) -> dict:
    if shutil.which("node") is None:
        pytest.skip("node binary not available")
    code = HARNESS + MODULE_PATH.read_text(encoding="utf-8") + "\n" + (
        "(async function(){\n" + script
        + "\nconsole.log(JSON.stringify({calls:calls,DOM:DOM,ctx:_tlHandoffCtx}));})()"
        + ".catch(function(e){console.error(e&&e.stack||e);process.exit(1);});"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as handle:
        handle.write(code)
        path = handle.name
    out = subprocess.run(["node", path], capture_output=True, text=True, encoding="utf-8", timeout=60)
    Path(path).unlink(missing_ok=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_trade_list_shows_only_server_preview_rows():
    result = _run("await openTradeList();")
    assert result["calls"]["gets"] == [
        "/mandates/m-1/recommendations/r-1/portfolio-handoff-preview?confirm_no_existing_holdings=false"
    ]
    body = result["DOM"]["m-tl-body"]["innerHTML"]
    assert "Neues Produkt C" in body and "Produkt A" in body
    assert "CLIENT-DRIFT" not in body
    assert 'id="m-tl-handoff"' in body
    assert result["calls"]["handoffSections"] == 1
    assert result["ctx"] == {"mandateId": "m-1", "runId": "r-1", "confirmNoHoldings": False}


def test_new_money_requires_dialog_confirmation_then_reloads_confirmed_preview():
    result = _run(
        "FAIL_UNCONFIRMED=true;await openTradeList();"
        "var before=DOM['m-tl-body'].innerHTML;calls.before=before;"
        "await confirmNoExistingHoldingsForTradeList();"
    )
    calls = result["calls"]
    assert "confirmNoExistingHoldingsForTradeList()" in calls["before"]
    assert "Kein erfasster Depotbestand." in calls["before"]
    assert calls["native"] == 0
    assert len(calls["confirms"]) == 1 and calls["confirms"][0]["title"] == "Kein bestehender Bestand"
    assert calls["gets"][-1].endswith("confirm_no_existing_holdings=true")
    assert result["ctx"]["confirmNoHoldings"] is True
    assert "Neues Produkt C" in result["DOM"]["m-tl-body"]["innerHTML"]


def test_declined_confirmation_sends_nothing():
    result = _run(
        "FAIL_UNCONFIRMED=true;CONFIRM_RESULT=false;await openTradeList();"
        "await confirmNoExistingHoldingsForTradeList();"
    )
    assert len(result["calls"]["gets"]) == 1
    assert result["ctx"]["confirmNoHoldings"] is False


def test_other_rejections_show_reason_without_confirmation_offer():
    result = _run(
        "API.get=async function(url){calls.gets.push(url);var e=new Error('x');"
        "e.body=JSON.stringify({detail:{reason_code:'HOLDINGS_VALUATION_INCOMPLETE',message:'Preis veraltet.'}});throw e;};"
        "await openTradeList();"
    )
    body = result["DOM"]["m-tl-body"]["innerHTML"]
    assert "Preis veraltet." in body
    assert "confirmNoExistingHoldingsForTradeList" not in body
    assert result["calls"]["handoffSections"] == 0


def test_monolith_loads_module_and_forwards_confirmation():
    html = HTML_PATH.read_text(encoding="utf-8")
    assert '<script src="./trade-list-preview.js"></script>' in html
    assert "function openTradeList(" not in html
    start = html.index("async function submitPortfolioHandoff()")
    body = html[start:html.index("function _handoffStatusColor(status)", start)]
    assert "confirm_no_existing_holdings:!!(_tlHandoffCtx&&_tlHandoffCtx.confirmNoHoldings)" in body
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "window.confirm" not in source and "confirm(" not in source.replace("uiConfirm(", "")
    assert "frontend/trade-list-preview.js" in json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))["build"]["files"]
