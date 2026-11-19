"""K2 / E2E-09 (Dok. 115): Handelsliste bei bestehendem Depot.

* Ist im Vermoegen ein Wertschriftendepot im Beratungsvermoegen erfasst, wird
  die fachlich falsche Neugeld-Bestaetigung nicht angeboten, sondern die
  Bestandserfassung (Umschichtung). Gegenprobe: ohne Depot bleibt Neugeld.
* Preis-Sperren nennen den Weg zu Preisen (Datenschutz-Freigabe, Live-Preise).
* Technische Parameternamen erscheinen nicht im Text.

Laeuft ueber das echte Modul ``trade-list-preview.js`` in Node (Harness aus
test_frontend_trade_list_preview).
"""
from __future__ import annotations

from tests.test_frontend_trade_list_preview import _run

_DEPOT = ("globalThis.currentWealthPositions=[{position_type:'Depot',assignment:'Beratungsvermögen',label:'Depot Testbank'},"
          "{position_type:'Liquidität',assignment:'Beratungsvermögen',label:'Konto'}];")
_FAIL_TECH = ("API.get=async function(url){calls.gets.push(url);var e=new Error('x');e.body=JSON.stringify({detail:"
              "{reason_code:'NO_HOLDINGS_CONFIRMATION_REQUIRED',message:'Kein erfasster Depotbestand: Bitte erfassen oder "
              "ausdruecklich bestaetigen (confirm_no_existing_holdings).'}});throw e;};")


def test_recorded_advisory_depot_offers_holdings_entry_not_new_money():
    result = _run(_DEPOT + _FAIL_TECH + "await openTradeList();")
    body = result["DOM"]["m-tl-body"]["innerHTML"]
    assert "confirmNoExistingHoldingsForTradeList" not in body
    assert "Umschichtung eines bestehenden Depots" in body and "Depot Testbank" in body
    assert "openPortfolioPositionHelper()" in body
    assert "confirm_no_existing_holdings" not in body  # kein technischer Parametername
    assert "Kein erfasster Depotbestand" in body


def test_gegenprobe_without_depot_new_money_stays_available():
    result = _run("globalThis.currentWealthPositions=[{position_type:'Liquidität',assignment:'Beratungsvermögen'}];"
                  + _FAIL_TECH + "await openTradeList();")
    body = result["DOM"]["m-tl-body"]["innerHTML"]
    assert "confirmNoExistingHoldingsForTradeList()" in body
    assert "Umschichtung" not in body
    assert "confirm_no_existing_holdings" not in body


def test_missing_prices_block_names_the_way_to_prices():
    result = _run(
        "API.get=async function(url){calls.gets.push(url);var e=new Error('x');"
        "e.body=JSON.stringify({detail:{reason_code:'HOLDINGS_VALUATION_INCOMPLETE',"
        "message:'Die Live-Bewertung ist nicht vollstaendig belegt: 10 Position(en) ohne aktuellen Marktpreis.'}});throw e;};"
        "await openTradeList();"
    )
    body = result["DOM"]["m-tl-body"]["innerHTML"]
    assert "10 Position(en) ohne aktuellen Marktpreis" in body
    assert "Datenschutz" in body and "Live-Preise" in body
    assert "refreshLivePricesForMandate()" in body
    assert "confirmNoExistingHoldingsForTradeList" not in body


def test_gegenprobe_other_rejections_get_no_price_guide():
    result = _run(
        "API.get=async function(url){calls.gets.push(url);var e=new Error('x');"
        "e.body=JSON.stringify({detail:{reason_code:'HOLDINGS_NOT_CARRIED_OVER',message:'Bestand nur im frueheren Lauf.'}});throw e;};"
        "await openTradeList();"
    )
    body = result["DOM"]["m-tl-body"]["innerHTML"]
    assert "Bestand nur im frueheren Lauf." in body
    assert "tl-guide" not in body
