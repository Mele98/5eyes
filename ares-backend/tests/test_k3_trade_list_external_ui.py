"""K3 / N-915-06: Handelsliste und Erfassung der Titel ausserhalb der Empfehlung
(Classic, echtes Modul ``trade-list-preview.js`` in Node; Harness aus
test_frontend_trade_list_preview).

* Bei erfasstem Depot ohne Bestand fuehrt der Wegweiser jetzt auch zur
  Erfassung der Titel ausserhalb der Empfehlung (vorher: "lassen sich hier noch
  nicht erfassen" -- Sackgasse).
* Fremdzeilen sind als "ausserhalb der Empfehlung · Vorschlag" gekennzeichnet,
  mit Hinweis: Verkaufen oder Halten entscheidet der Kunde.
* Erfassung: Marktwert leer -> null (nicht bewertbar, kein Ersatzwert);
  Status des Servers wird angezeigt.
"""
from __future__ import annotations

from tests.test_frontend_trade_list_preview import FRONTEND, _run as _run_module
from tests.test_k2_trade_list_guidance import _DEPOT, _FAIL_TECH

# In ares.html laedt presentation-rounding.js (window.AresRounding) mit; der
# Erfassungsdialog nutzt dessen zentrale Speicher-/Anzeigeregeln (N-937-01).
_ROUNDING = (FRONTEND / "presentation-rounding.js").read_text(encoding="utf-8")


def _run(script: str) -> dict:
    return _run_module(_ROUNDING + "\n" + script)


def test_no_holdings_with_depot_offers_external_entry_instead_of_dead_end():
    body = _run(_DEPOT + _FAIL_TECH + "await openTradeList();")["DOM"]["m-tl-body"]["innerHTML"]
    assert "openExternalHoldingsEditor()" in body
    assert "noch nicht erfassen" not in body
    assert "confirmNoExistingHoldingsForTradeList" not in body


def test_external_rows_are_marked_as_proposal_with_customer_decision_note():
    script = (
        "API.get=async function(url){calls.gets.push(url);return {holdings_basis:'recorded_depot',trades:["
        "{product_name:'Aktie Inland',asset_class:'Aktien',rebalance_action:'Verkauf prüfen (Vorschlag)',"
        "rebalance_action_code:'REVIEW',holding_origin:'external_holding',current_market_value_rappen:40000000,"
        "target_amount_rappen:0,rebalance_amount_rappen:-40000000,target_weight_bps:0},"
        "{product_name:'Fonds A',asset_class:'Aktien',rebalance_action:'Aufbauen',rebalance_action_code:'BUY',"
        "holding_origin:'not_held',current_market_value_rappen:0,target_amount_rappen:40000000,"
        "rebalance_amount_rappen:40000000,target_weight_bps:10000}]};};await openTradeList();"
    )
    body = _run(script)["DOM"]["m-tl-body"]["innerHTML"]
    assert body.count("ausserhalb der Empfehlung · Vorschlag") == 1
    assert "entscheidet der Kunde" in body and "nichts automatisch verkauft" in body


def test_gegenprobe_without_external_rows_no_proposal_note():
    body = _run("await openTradeList();")["DOM"]["m-tl-body"]["innerHTML"]
    assert "ausserhalb der Empfehlung · Vorschlag" not in body
    assert "entscheidet der Kunde" not in body


def test_editor_amounts_and_status_rendering():
    script = (
        "calls.amounts=[externalAmountToMinor('120000.50','CHF'),externalAmountToMinor(\"1'000\",'CHF'),"
        "externalAmountToMinor('','CHF'),String(externalAmountToMinor('-5','CHF')),externalAmountToMinor('500','JPY'),String(externalAmountToMinor('1.005','CHF')),"
        "String(externalAmountToMinor('500.5','JPY')),externalAmountToMinor('0.1','CHF')];"
        "var fake={innerHTML:''};renderExternalHoldingsEditor(fake,'m-1',{depots:[{wealth_position_id:'wp-1',"
        "depot_label:'Depot',items:[{label:'Titel X',asset_class:'Obligationen',currency:'CHF',market_value_rappen:null,"
        "status:'missing_value',status_text:'nicht bewertbar – Marktwert fehlt'}]}]});calls.editor=fake.innerHTML;"
    )
    calls = _run(script)["calls"]
    # N-937-01: Speicherung immer mit Faktor 100 (auch JPY): JPY 500 -> 50000.
    assert calls["amounts"] == [12000050, 100000, None, "NaN", 50000, "NaN", "NaN", 10]
    assert "nicht bewertbar – Marktwert fehlt" in calls["editor"]
    assert 'data-wp="wp-1"' in calls["editor"] and "Titel X" in calls["editor"]
    assert "<option selected>Obligationen</option>" in calls["editor"]


def test_n937_01_storage_factor_100_for_every_currency_and_text_roundtrip():
    """N-937-01: Ares speichert jedes *_rappen-Feld mit Faktor 100 (N-894-01),
    auch JPY. Eingabe hoechstens min(ISO-Stellen, 2) Nachkommastellen; die
    Anzeige teilt immer durch 100. Gegenprobe: der alte Faktor 1 fuer JPY
    ergaebe 500 statt 50000 (100-mal zu klein)."""
    script = (
        "calls.toMinor=[externalAmountToMinor('500','JPY'),externalAmountToMinor(\"1'000'000\",'JPY'),"
        "String(externalAmountToMinor('500.5','JPY')),externalAmountToMinor('500','CHF'),"
        "externalAmountToMinor('12.34','EUR'),String(externalAmountToMinor('1.234','USD'))];"
        "calls.toText=[externalMinorToText(50000,'JPY'),externalMinorToText(12000050,'CHF'),"
        "externalMinorToText(null,'CHF')];"
        "calls.roundtrip=externalAmountToMinor(externalMinorToText(100000000,'JPY'),'JPY');"
        "calls.storage=AresRounding.STORAGE_EXPONENT;"
    )
    calls = _run(script)["calls"]
    assert calls["storage"] == 2
    assert calls["toMinor"] == [50000, 100000000, "NaN", 50000, 1234, "NaN"]
    assert calls["toText"] == ["500", "120'000.50", ""]
    assert calls["roundtrip"] == 100000000


def test_n937_01_dialog_has_no_own_currency_table():
    """Keine eigene Waehrungstabelle im Dialog: die Regeln kommen aus
    presentation-rounding.js (displayDecimals/STORAGE_EXPONENT)."""
    src = (FRONTEND / "trade-list-preview.js").read_text(encoding="utf-8")
    assert "JPY|KRW" not in src and "externalMinorDigits" not in src
    assert "AresRounding.displayDecimals" in src and "AresRounding.STORAGE_EXPONENT" in src
