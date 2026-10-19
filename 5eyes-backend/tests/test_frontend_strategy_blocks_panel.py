"""STRATEGY-BLOCKS-PANEL-001 (UX-Audit Befund 9 + Nutzerwunsch 2026-10-19).

"Und wo sind die Tilts hin? Am schoensten waere ein sauberer Balken ueber der
Assetallocation [...], der sauber aufklappt, wo man wirklich im Detail
auswaehlen kann."

Vorher lagen die Strategie-Eingaben in einem Header-Dialog ("Anlage-
praeferenzen") plus einem versteckten zweiten Schritt ("Restriktionen &
Tilts") -- teils doppelt und widerspruechlich:

* Universum-Dropdown vs. Checkboxen "Nur Fonds/ETFs" / "Nur kotierte Titel"
  (Default-Widerspruch: "listed_only" + angehakte "Nur Fonds/ETFs").
* Absicherungs-Dropdown (inkl. "Nur CHF-Instrumente") vs. Checkboxen
  "FX-Absicherung obligatorisch" / "Nur CHF-Instrumente".
* Zwei Reserve-Eingaben ("Min. Reserve" und "Reserve (CHF)").

Jetzt: EIN einklappbarer Balken "Strategiebausteine" direkt ueber der Asset
Allocation, je Thema genau eine Steuerung. Die Datei prueft Struktur,
Ein-/Ausklappen, Zusammenfassungs-Chips, keine Dubletten und -- zentral --
dass der Balken fuer typische Kombinationen EXAKT dieselben prefs erzeugt
wie der alte Dialog (eingefrorene Referenz: fixtures/
legacy_collect_allocation_preferences.js). Die echten Monolith-Funktionen
laufen in Node (DOM/localStorage gefaked) und die Ausgabe zusaetzlich durch
die echte Backend-Validierung (_normalize_preferences) und den echten
Produktfilter (_product_matches_constraints).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy.orm import configure_mappers  # noqa: E402

from models import (  # noqa: E402,F401
    allocation, clients, mandates, profiling, review, snapshots, users, wealth,
)
import models.tenant  # noqa: E402,F401
import models.client_login  # noqa: E402,F401
import models.protocol_bausteine  # noqa: E402,F401

configure_mappers()

from models.review import Product  # noqa: E402
from services.portfolio_engine import _normalize_preferences  # noqa: E402
from services.portfolio_engine_payload import _product_matches_constraints  # noqa: E402

HTML_PATH = BACKEND_DIR.parent / "5eyes-electron" / "frontend" / "5eyes_v2.html"
LEGACY_COLLECT = Path(__file__).resolve().parent / "fixtures" / "legacy_collect_allocation_preferences.js"

PANEL_SECTIONS = (
    "Aktien",
    "Obligationen",
    "Immobilien & Alternative",
    "Währung & Universum",
    "Nachhaltigkeit",
    "Restriktionen & Reserve",
)
RADIO_GROUPS = ("aa-equities-geo", "aa-bonds-duration", "aa-realestate-market", "aa-liquidity-instrument")
# Die frueheren Zweit-Steuerungen: duerfen als Eingabe nicht mehr existieren.
REMOVED_DUPLICATE_IDS = (
    "aa-product-funds-only",
    "aa-product-listed-only",
    "aa-geo-chf-only",
    "aa-geo-hedging-required",
    "aa-liquidity-reserve-target",
)


def _html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def _panel(src: str) -> str:
    start = src.index('<section class="sbb" id="aa-strategy-blocks"')
    return src[start:src.index("</section>", start) + len("</section>")]


def _extract_function(src: str, name: str) -> str:
    match = re.search(r"\n(?:async )?function " + re.escape(name) + r"\(", src)
    assert match, f"Monolith-Funktion {name} nicht gefunden"
    start = match.start() + 1
    i = src.index("{", start)
    depth, j = 1, i + 1
    while depth:
        depth += {"{": 1, "}": -1}.get(src[j], 0)
        j += 1
    return src[start:j]


def _extract_global(src: str, name: str) -> str | None:
    match = re.search(r"\nvar " + re.escape(name) + r"=[^\n]*;", src)
    return match.group(0).strip() if match else None


def _radio_options(src: str) -> dict[str, list[str]]:
    return {
        name: re.findall(r'<input type="radio" name="%s" value="([^"]*)"' % re.escape(name), src)
        for name in RADIO_GROUPS
    }


def _product(**overrides) -> Product:
    data = {
        "id": "p-test", "product_name": "Test", "provider": "X", "product_type": "ETF",
        "asset_class": "Aktien", "sub_asset_class": "Aktien Global", "currency": "CHF",
        "ter_bps": 20, "sfdr_class": "8", "is_active": 1,
        "created_at": "2026-01-01", "updated_at": "2026-01-01",
    }
    data.update(overrides)
    return Product(**data)


# ---------------------------------------------------------------------------
# Node-Harness: echte Monolith-Funktionen, gefakter DOM
# ---------------------------------------------------------------------------

_FUNCTIONS = (
    "cloneJSON",
    "buildDefaultAllocationPreferences",
    "mergeAllocationPreferences",
    "loadAllocationPreferences",
    "persistAllocationPreferences",
    "getInputValue",
    "getCheckboxValue",
    "getRadioValue",
    "setSelectValue",
    "setCheckboxValue",
    "setRadioValue",
    "collectAllocationPreferencesFromUI",
    "applyAllocationPreferencesToUI",
    "collectTiltReasonsFromUI",
    "syncTiltReasonVisibility",
    "stripLegacySimulationHorizon",
    "sbbFormatPctInput",
    # AA-UX-FORMAT-001: zentrale Format-Helfer (#658)
    "fmtLocaleCH",
    "normalizeNumberInputCH",
    "fmtNumber",
    "fmtPct",
    "fmtCHF",
    "sbbParseAmount",
    "findStrategyBlockConflicts",
    "buildStrategyBlockChips",
    "renderStrategyBlocksSummary",
    "setStrategyBlocksPanelOpen",
    "toggleStrategyBlocksPanel",
    "strategyBlockDirtyMessage",
)
_GLOBALS = ("LEGACY_SIMULATION_HORIZON_KEYS", "STRATEGY_BLOCK_CHIP_LIMIT")

_HARNESS = r"""
var __ls={};
var localStorage={
  getItem:function(k){return Object.prototype.hasOwnProperty.call(__ls,k)?__ls[k]:null;},
  setItem:function(k,v){__ls[k]=String(v);},
  removeItem:function(k){delete __ls[k];}
};
var __attrs={};
function __mkEl(id){
  var el={id:id,style:{display:''},textContent:'',innerHTML:'',title:'',value:'',checked:false,hidden:false,required:false,
    _cls:{},
    addEventListener:function(){},
    focus:function(){__focused=id;},
    setAttribute:function(k,v){this['@'+k]=String(v);},
    getAttribute:function(k){return Object.prototype.hasOwnProperty.call(this,'@'+k)?this['@'+k]:null;}};
  el.classList={
    add:function(c){el._cls[c]=true;},remove:function(c){delete el._cls[c];},
    contains:function(c){return !!el._cls[c];}
  };
  return el;
}
var __focused=null;
var __els={};
var __radios={};       // name -> gewaehlter Wert
function __radioEls(name){
  return (__RADIO_OPTIONS[name]||[]).map(function(value){
    var o={value:value};
    Object.defineProperty(o,'checked',{
      get:function(){return __radios[name]===value;},
      set:function(v){if(v)__radios[name]=value;else if(__radios[name]===value)delete __radios[name];}
    });
    return o;
  });
}
var document={
  getElementById:function(id){if(!__els[id])__els[id]=__mkEl(id);return __els[id];},
  querySelector:function(sel){
    var m=/^input\[name="([^"]+)"\]:checked$/.exec(sel);
    if(m){return Object.prototype.hasOwnProperty.call(__radios,m[1])?{value:__radios[m[1]]}:null;}
    return null;
  },
  querySelectorAll:function(sel){
    var m=/^input\[name="([^"]+)"\]$/.exec(sel);
    if(m)return __radioEls(m[1]);
    return [];
  },
  createElement:function(){return {value:'',textContent:''};}
};
function escapeHtml(v){return String(v==null?'':v).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
var currentPersona=null;
var allocationPreferencesCache={};
var allocationPreferenceStoragePrefix='5eyes.allocprefs.';
var strategyState={dirty:false,allocation:null};
function getAllocationPreferenceKey(){return 'mandate:M1';}
function hasCanonicalBandBaseline(){return false;}
function collectBandOverridesFromModal(){return null;}
function countBandOverrides(b){return Object.keys(b||{}).length;}
function updateAllocationPreferencesEntryButton(){}
function updateBandOverrideStatus(){}
function renderAllocationPreferenceSummary(){}
function __setUi(ui){
  __els={};__radios={};
  Object.keys(ui.values||{}).forEach(function(id){document.getElementById(id).value=String(ui.values[id]);});
  Object.keys(ui.checks||{}).forEach(function(id){document.getElementById(id).checked=!!ui.checks[id];});
  Object.keys(ui.radios||{}).forEach(function(n){__radios[n]=ui.radios[n];});
}
"""


def _run(scenario_js: str) -> object:
    if shutil.which("node") is None:
        pytest.skip("node not available")
    src = _html()
    parts = [g for g in (_extract_global(src, n) for n in _GLOBALS) if g]
    parts += [_extract_function(src, name) for name in _FUNCTIONS]
    parts.append(LEGACY_COLLECT.read_text(encoding="utf-8"))
    script = (
        "var __RADIO_OPTIONS=" + json.dumps(_radio_options(src)) + ";\n"
        + _HARNESS
        + "\n".join(parts)
        + "\nconsole.log(JSON.stringify((function(){" + scenario_js + "})()));\n"
    )
    res = subprocess.run(
        ["node", "-"], input=script,
        capture_output=True, text=True, timeout=30, check=False, encoding="utf-8",
    )
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout.strip().splitlines()[-1])


# Gemeinsame Basis: unberuehrte Defaults beider Oberflaechen.
_BASE_VALUES = {
    "aa-policy-esg": "none", "aa-policy-universe": "funds_only",
    "aa-policy-home-bias": "ch_focus", "aa-policy-hedging": "none",
    "aa-tilt-fossil": "neutral", "aa-tilt-defense": "neutral", "aa-tilt-tobacco": "neutral",
    "aa-tilt-alcohol": "neutral", "aa-tilt-gaming": "neutral", "aa-tilt-nuclear": "neutral",
    "aa-sim-stress": "1.0", "aa-sim-rebalance": "bands", "aa-sim-mc-runs": "750",
}
_BASE_CHECKS = {
    "aa-equities-large-cap": True, "aa-bonds-investment-grade": True,
    "aa-realestate-funds": True, "aa-alts-gold": True,
}
_BASE_RADIOS = {
    "aa-equities-geo": "Schweiz Fokus", "aa-bonds-duration": "Langfristig",
    "aa-realestate-market": "Schweiz", "aa-liquidity-instrument": "Geldmarktfonds",
}

# (name, alter Dialog-Zustand, neuer Balken-Zustand) -- typische, im alten
# Dialog widerspruchsfrei gesetzte Kombinationen.
COMBOS = [
    (
        "defaults",
        {"checks": {"aa-product-funds-only": True}},
        {},
    ),
    (
        "listed_chf_only_best_in_class_tobacco",
        {
            "values": {"aa-policy-universe": "listed_only", "aa-policy-hedging": "chf_only",
                       "aa-policy-esg": "best_in_class", "aa-tilt-tobacco": "exclude",
                       "aa-liquidity-min-reserve": "50'000"},
            "checks": {"aa-product-listed-only": True, "aa-geo-chf-only": True},
        },
        {
            "values": {"aa-policy-universe": "listed_only", "aa-policy-hedging": "chf_only",
                       "aa-policy-esg": "best_in_class", "aa-tilt-tobacco": "exclude",
                       "aa-liquidity-min-reserve": "50'000"},
        },
    ),
    (
        "standard_hedging_required_global_allow_reason",
        {
            "values": {"aa-policy-universe": "standard", "aa-policy-hedging": "hedged",
                       "aa-policy-esg": "negative_screening", "aa-tilt-defense": "allow",
                       "aa-tilt-reason-defense": "Kunde arbeitet in der Branche, bewusst dokumentiert.",
                       "aa-limit-single-position": "15"},
            "checks": {"aa-geo-hedging-required": True, "aa-geo-no-usd": True,
                       "aa-product-no-derivatives": True, "aa-equities-smid": True},
            "radios": {"aa-equities-geo": "Global", "aa-bonds-duration": "Gemischt"},
        },
        {
            "values": {"aa-policy-universe": "standard", "aa-policy-hedging": "required",
                       "aa-policy-esg": "negative_screening", "aa-tilt-defense": "allow",
                       "aa-tilt-reason-defense": "Kunde arbeitet in der Branche, bewusst dokumentiert.",
                       "aa-limit-single-position": "15"},
            "checks": {"aa-geo-no-usd": True, "aa-product-no-derivatives": True,
                       "aa-equities-smid": True},
            "radios": {"aa-equities-geo": "Global", "aa-bonds-duration": "Gemischt"},
        },
    ),
    (
        "extended_risk_budget_impact_underweight_alts",
        {
            "values": {"aa-policy-universe": "extended", "aa-policy-hedging": "risk_budget",
                       "aa-policy-esg": "impact", "aa-tilt-alcohol": "underweight",
                       "aa-tilt-fossil": "overweight", "aa-liquidity-max-illiquid": "10",
                       "aa-liquidity-min-reserve": "120000"},
            "checks": {"aa-geo-no-em": True, "aa-alts-pe": True, "aa-alts-crypto": True,
                       "aa-realestate-direct": True, "aa-bonds-high-yield": True},
            "radios": {"aa-realestate-market": "Gemischt", "aa-liquidity-instrument": "Festgeld"},
        },
        {
            "values": {"aa-policy-universe": "extended", "aa-policy-hedging": "risk_budget",
                       "aa-policy-esg": "impact", "aa-tilt-alcohol": "underweight",
                       "aa-tilt-fossil": "overweight", "aa-liquidity-max-illiquid": "10",
                       "aa-liquidity-min-reserve": "120000"},
            "checks": {"aa-geo-no-em": True, "aa-alts-pe": True, "aa-alts-crypto": True,
                       "aa-realestate-direct": True, "aa-bonds-high-yield": True},
            "radios": {"aa-realestate-market": "Gemischt", "aa-liquidity-instrument": "Festgeld"},
        },
    ),
    (
        "hedged_preferred_europe",
        {
            "values": {"aa-policy-hedging": "hedged", "aa-policy-home-bias": "europe_focus"},
            "checks": {"aa-product-funds-only": True, "aa-product-no-structured": True},
            "radios": {"aa-equities-geo": "Europa"},
        },
        {
            "values": {"aa-policy-hedging": "hedged", "aa-policy-home-bias": "europe_focus"},
            "checks": {"aa-product-no-structured": True},
            "radios": {"aa-equities-geo": "Europa"},
        },
    ),
]


def _ui(state: dict) -> dict:
    return {
        "values": {**_BASE_VALUES, **state.get("values", {})},
        "checks": {**_BASE_CHECKS, **state.get("checks", {})},
        "radios": {**_BASE_RADIOS, **state.get("radios", {})},
    }


def _collect_both(old_state: dict, new_state: dict) -> dict:
    return _run(
        "__setUi(" + json.dumps(_ui(old_state)) + ");"
        "var oldPrefs=legacyCollectAllocationPreferencesFromUI();"
        "__ls={};allocationPreferencesCache={};"
        "__setUi(" + json.dumps(_ui(new_state)) + ");"
        "var newPrefs=collectAllocationPreferencesFromUI();"
        # Roundtrip: gespeicherte Alt-prefs -> Balken (apply) -> collect.
        "__ls={};allocationPreferencesCache={};__setUi({values:{},checks:{},radios:{}});"
        "applyAllocationPreferencesToUI(oldPrefs);"
        "var roundtrip=collectAllocationPreferencesFromUI();"
        "return {old:oldPrefs,new:newPrefs,roundtrip:roundtrip};"
    )


# ---------------------------------------------------------------------------
# 1. Payload-Gleichheit alter Dialog <-> Balken
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name,old_state,new_state", COMBOS, ids=[c[0] for c in COMBOS])
def test_panel_produces_exactly_the_same_prefs_as_the_old_dialog(name, old_state, new_state):
    out = _collect_both(old_state, new_state)
    assert out["new"] == out["old"], name
    assert _normalize_preferences(out["new"]) == _normalize_preferences(out["old"])
    # Gespeicherte Alt-Praeferenzen ueberleben den Weg durch den Balken unveraendert.
    assert out["roundtrip"] == out["old"], name


def test_payload_keeps_every_preference_key():
    out = _collect_both(*COMBOS[0][1:])
    for section, keys in {
        "product": {"noDerivatives", "noLeverage", "noStructured", "listedOnly", "fundsOnly"},
        "geo": {"chFocus", "noEm", "hedgingRequired", "chfOnly", "noUsd"},
        "limits": {"singlePosition", "singleIssuer", "minReserve", "maxIlliquid"},
        "policy": {"esg", "universe", "homeBias", "hedging"},
    }.items():
        assert keys <= set(out["new"][section]), section
    assert "liquidityReserveTarget" in out["new"]["assetClasses"]


def test_required_hedging_is_one_ui_choice_mapped_to_existing_keys():
    out = _run(
        "__setUi(" + json.dumps(_ui({"values": {"aa-policy-hedging": "required"}})) + ");"
        "return collectAllocationPreferencesFromUI();"
    )
    assert out["policy"]["hedging"] == "hedged"  # nur Schema-Werte im Payload
    assert out["geo"]["hedgingRequired"] is True and out["geo"]["chfOnly"] is False
    _normalize_preferences(out)  # schema-gueltig


# ---------------------------------------------------------------------------
# 2. Altbestaende mit widerspruechlichen Doppel-Eingaben: gleiche Wirkung
# ---------------------------------------------------------------------------


def _effective_filters(prefs: dict) -> tuple:
    normalized = _normalize_preferences(prefs)
    probes = [
        _product(product_type="Einzeltitel"),
        _product(product_type="ETF", currency="USD", sub_asset_class="Aktien Global"),
        _product(product_type="Fonds", currency="CHF"),
        _product(product_type="Anleihe", asset_class="Obligationen", sub_asset_class="Obligationen CHF"),
    ]
    return tuple(_product_matches_constraints(p, normalized, 8) for p in probes)


@pytest.mark.parametrize(
    "legacy",
    [
        # Universum "Standard", aber Checkbox "Nur Fonds/ETFs" angehakt (Alt-Default-Widerspruch).
        {"policy": {"universe": "standard"}, "product": {"fundsOnly": True}},
        {"policy": {"universe": "extended"}, "product": {"fundsOnly": False, "listedOnly": True}},
        # Absicherung "Keine Vorgabe", aber Checkbox "Nur CHF-Instrumente".
        {"policy": {"hedging": "none"}, "geo": {"chfOnly": True}},
        # Absicherung "Keine Vorgabe", aber Checkbox "FX-Absicherung obligatorisch".
        {"policy": {"hedging": "none"}, "geo": {"hedgingRequired": True}},
    ],
)
def test_legacy_double_inputs_map_to_one_control_without_changing_the_filter(legacy):
    out = _run(
        "var d=buildDefaultAllocationPreferences();"
        "var legacy=" + json.dumps(legacy) + ";"
        "Object.keys(legacy).forEach(function(s){Object.assign(d[s],legacy[s]);});"
        "__setUi({values:{},checks:{},radios:{}});"
        "applyAllocationPreferencesToUI(d);"
        "return {legacy:d,panel:collectAllocationPreferencesFromUI(),"
        "universe:document.getElementById('aa-policy-universe').value,"
        "hedging:document.getElementById('aa-policy-hedging').value};"
    )
    assert _effective_filters(out["panel"]) == _effective_filters(out["legacy"])


def test_legacy_second_reserve_is_shown_in_the_single_reserve_input():
    out = _run(
        "var d=buildDefaultAllocationPreferences();"
        "d.assetClasses.liquidityReserveTarget=\"80'000\";d.limits.minReserve='50000';"
        "__setUi({values:{},checks:{},radios:{}});"
        "applyAllocationPreferencesToUI(d);"
        "return collectAllocationPreferencesFromUI();"
    )
    assert out["limits"]["minReserve"] == "80'000"
    assert out["assetClasses"]["liquidityReserveTarget"] == ""


# ---------------------------------------------------------------------------
# 3. Zusammenfassungs-Chips (eingeklappter Zustand)
# ---------------------------------------------------------------------------


def _chips(mutation_js: str = "") -> list[dict]:
    return _run(
        "var p=buildDefaultAllocationPreferences();" + mutation_js + "return buildStrategyBlockChips(p);"
    )


def test_default_chips_are_calm_and_complete():
    labels = [c["label"] for c in _chips()]
    assert labels == [
        "Aktien Schweiz-Fokus",
        "Heimmarkt CH bevorzugt",
        "Obligationen langfristig",
        "Immobilien Schweiz",
        "Alternative: Gold",
        "Nur Fonds/ETFs",
    ]


def test_chips_summarise_active_building_blocks():
    labels = [c["label"] for c in _chips(
        "p.assetClasses.equitiesGeo='Global';p.policy.hedging='hedged';p.geo.hedgingRequired=true;"
        "p.policy.esg='esg_integration';p.tilts.tobacco='exclude';p.tilts.gaming='exclude';"
        "p.limits.minReserve=\"50'000\";p.product.noLeverage=true;p.geo.noUsd=true;"
    )]
    for expected in (
        "Aktien global", "Währung abgesichert (obligatorisch)", "ESG: SFDR 8/9",
        "Ausschluss: Tabak, Glücksspiel", "Mindestreserve CHF 50'000", "Ohne Hebel", "Kein USD",
    ):
        assert expected in labels, (expected, labels)


def test_esg_chips_state_criteria_not_claims():
    for esg in ("esg_integration", "best_in_class", "impact", "net_zero", "negative_screening"):
        label = [c["label"] for c in _chips("p.policy.esg='%s';" % esg) if c["label"].startswith("ESG")][0]
        assert re.search(r"SFDR|Screening", label), label
        for claim in ("nachhaltig", "grün", "klimaneutral", "sauber", "verantwortungsvoll"):
            assert claim not in label.lower(), label


def test_contradiction_shows_warning_chip_and_alert():
    out = _run(
        "var p=buildDefaultAllocationPreferences();p.geo.noEm=true;p.assetClasses.bondsEmerging=true;"
        "renderStrategyBlocksSummary(p);"
        "return {chips:buildStrategyBlockChips(p),"
        "alert:document.getElementById('sbb-conflict').textContent,"
        "hidden:document.getElementById('sbb-conflict').hidden};"
    )
    assert out["chips"][0] == {"label": "Widerspruch prüfen", "tone": "warn"}
    assert out["hidden"] is False and "Emerging Markets" in out["alert"]


def test_summary_caps_visible_chips_with_more_counter():
    html = _run(
        "var p=buildDefaultAllocationPreferences();"
        "['fossil','defense','tobacco','alcohol'].forEach(function(k,i){p.tilts[k]=['exclude','underweight','allow','overweight'][i];});"
        "p.geo.noUsd=true;p.geo.noEm=true;p.product.noDerivatives=true;p.limits.singleIssuer='5';"
        "renderStrategyBlocksSummary(p);return document.getElementById('sbb-summary').innerHTML;"
    )
    assert html.count('class="sbb-chip') == 10  # 9 sichtbar + Zaehler
    assert re.search(r"\+\d+ weitere", html)


# ---------------------------------------------------------------------------
# 4. Ein-/Ausklappen + ARIA
# ---------------------------------------------------------------------------


def test_toggle_flips_aria_expanded_hidden_and_label():
    out = _run(
        "var t=document.getElementById('sbb-toggle');t.setAttribute('aria-expanded','false');"
        "document.getElementById('sbb-body').hidden=true;"
        "var s=[];"
        "toggleStrategyBlocksPanel();"
        "s.push([t.getAttribute('aria-expanded'),document.getElementById('sbb-body').hidden,"
        "document.getElementById('sbb-toggle-label').textContent,"
        "document.getElementById('aa-strategy-blocks').classList.contains('is-open')]);"
        "toggleStrategyBlocksPanel();"
        "s.push([t.getAttribute('aria-expanded'),document.getElementById('sbb-body').hidden,"
        "document.getElementById('sbb-toggle-label').textContent,"
        "document.getElementById('aa-strategy-blocks').classList.contains('is-open'),__focused]);"
        "toggleStrategyBlocksPanel(true);toggleStrategyBlocksPanel(true);"
        "s.push(t.getAttribute('aria-expanded'));"
        "return s;"
    )
    assert out[0] == ["true", False, "Einklappen", True]
    assert out[1] == ["false", True, "Bearbeiten", False, "sbb-toggle"]
    assert out[2] == "true"  # forceOpen ist idempotent


def test_dirty_message_names_the_changed_building_block():
    out = _run(
        "var el={closest:function(){return {querySelector:function(){return {textContent:'Nachhaltigkeit'};}};}};"
        "return [strategyBlockDirtyMessage(el),strategyBlockDirtyMessage(null)];"
    )
    assert out[0] == "Strategiebaustein «Nachhaltigkeit» geändert: Strategie neu berechnen."
    assert "Strategie neu berechnen" in out[1]


# ---------------------------------------------------------------------------
# 5. Struktur + keine Dubletten (statisch)
# ---------------------------------------------------------------------------


def test_panel_sits_directly_above_the_allocation_grid_and_starts_collapsed():
    src = _html()
    panel = _panel(src)
    after = src[src.index(panel) + len(panel):]
    assert after.lstrip().startswith('<div class="alloc-top-grid">')
    assert re.search(r'id="sbb-toggle"[^>]*aria-expanded="false"[^>]*aria-controls="sbb-body"', panel)
    assert re.search(r'<button type="button" class="sbb-head" id="sbb-toggle"', panel)
    assert re.search(r'id="sbb-body"[^>]*hidden>', panel)
    assert ">Strategiebausteine<" in panel
    # Layout-Umbau haelt den Balken ueber dem Grid.
    layout = _extract_function(src, "normalizeAllocationLayout")
    assert "mainGrid.parentNode.insertBefore(blocksPanel,mainGrid)" in layout


def test_panel_has_the_six_sections_in_order():
    legends = re.findall(r'<legend class="sbb-sec-t">(.*?)</legend>', _panel(_html()))
    texts = [re.sub(r"<[^>]+>", "", l).replace("&amp;", "&") for l in legends]
    assert texts == list(PANEL_SECTIONS)


def test_asset_class_sections_and_chips_use_central_class_colour_tokens():
    src = _html()
    panel = _panel(src)
    legends = dict(
        (re.sub(r"<[^>]+>", "", l).replace("&amp;", "&"), l)
        for l in re.findall(r'<legend class="sbb-sec-t">(.*?)</legend>', panel)
    )
    assert 'sbb-ac-eq' in legends["Aktien"]
    assert 'sbb-ac-bd' in legends["Obligationen"]
    assert 'sbb-ac-re' in legends["Immobilien & Alternative"] and 'sbb-ac-alt' in legends["Immobilien & Alternative"]
    for key in ("eq", "bd", "re", "alt", "liq"):
        assert ".sbb-ac-%s{background:var(--ac-%s);}" % (key, key) in src
    # Keine eigenen Hex-Farben im Balken-CSS; Gold bleibt SOLL vorbehalten.
    css = "\n".join(l for l in src.splitlines() if l.startswith(".sbb"))
    assert not re.search(r"#[0-9a-fA-F]{3,6}\b", css)
    assert "var(--g4)" not in css.replace("outline:2px solid var(--g4)", "")
    chips = _chips("p.limits.minReserve=\"50'000\";")
    by_label = {c["label"]: c.get("ac") for c in chips}
    assert by_label["Aktien Schweiz-Fokus"] == "eq"
    assert by_label["Obligationen langfristig"] == "bd"
    assert by_label["Immobilien Schweiz"] == "re"
    assert by_label["Alternative: Gold"] == "alt"
    assert by_label["Mindestreserve CHF 50'000"] == "liq"
    html = _run(
        "var p=buildDefaultAllocationPreferences();renderStrategyBlocksSummary(p);"
        "return document.getElementById('sbb-summary').innerHTML;"
    )
    assert '<span class="sbb-ac sbb-ac-eq" aria-hidden="true"></span>Aktien Schweiz-Fokus' in html


def test_chip_numbers_use_central_format_helpers():
    labels = [c["label"] for c in _chips(
        "p.limits.minReserve='1250000';p.limits.singlePosition='15';p.limits.maxIlliquid='7.5';"
    )]
    assert "Mindestreserve CHF 1'250'000" in labels  # gerades Apostroph (AA-UX-FORMAT-001)
    assert "Einzelposition ≤ 15\u00a0%" in labels
    assert "Illiquid ≤ 7.5\u00a0%" in labels
    body = _extract_function(_html(), "buildStrategyBlockChips")
    assert "fmtCHF(" in body and "sbbFormatPctInput(" in body
    assert "toLocaleString" not in body


def test_every_bound_control_lives_once_inside_the_panel():
    src = _html()
    panel = _panel(src)
    bind = _extract_function(src, "bindAllocationPreferenceControls")
    ids = re.findall(r"'#(aa-[a-z0-9-]+)'", bind)
    sim_ids = {i for i in ids if i.startswith("aa-sim-")}
    for el_id in ids:
        assert src.count('id="%s"' % el_id) == 1, el_id
        if el_id not in sim_ids:  # Simulation bleibt im Parameter-Modal
            assert 'id="%s"' % el_id in panel, el_id
    for name in RADIO_GROUPS:
        assert src.count('name="%s"' % name) == panel.count('name="%s"' % name) >= 3, name
    # Jede Eingabe im Balken ist auch gebunden (sonst wuerde sie nie persistiert).
    for el_id in re.findall(r'<(?:input|select)[^>]*\bid="(aa-[a-z0-9-]+)"', panel):
        assert el_id in ids, el_id


def test_removed_duplicates_and_old_dialog_are_gone():
    src = _html()
    for el_id in REMOVED_DUPLICATE_IDS:
        assert 'id="%s"' % el_id not in src, el_id
        assert "'#%s'" % el_id not in src, el_id
    assert 'id="m-aa-pref"' not in src
    assert 'id="aa-preferences-card"' not in src and 'id="aa-restrictions-card"' not in src
    assert "toggleAllocationRestrictionsPanel" not in src
    # Genau eine Reserve-Eingabe.
    assert len(re.findall(r'<label[^>]*>(?:<span[^>]*></span>)*[^<]*reserve[^<]*\(CHF\)</label>', src, re.I)) == 1
    assert re.findall(r'<input[^>]*\bid="(aa-[a-z-]*reserve[a-z-]*)"', src) == ["aa-liquidity-min-reserve"]
    # Header-Button bleibt (Header-Kontrakt) und oeffnet den Balken, keinen Dialog.
    opener = _extract_function(src, "openAllocationPreferencesModal")
    assert "toggleStrategyBlocksPanel(true)" in opener and "om(" not in opener


def test_select_labels_are_associated_with_their_controls():
    panel = _panel(_html())
    for sel_id in re.findall(r'<select[^>]*\bid="([^"]+)"', panel):
        assert 'for="%s"' % sel_id in panel, sel_id
    for inp_id in re.findall(r'<input class="fi[^"]*"[^>]*\bid="([^"]+)"', panel):
        assert ('for="%s"' % inp_id in panel) or re.search(r'id="%s"[^>]*aria-label=' % inp_id, panel), inp_id


def test_panel_uses_no_third_party_brand_names():
    panel = _panel(_html()).lower()
    for brand in ("swiss life", "3eyes", "ubs", "credit suisse", "msci", "blackrock", "ishares"):
        assert brand not in panel, brand
