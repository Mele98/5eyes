"""Live-Test 2026-11 H6 -- Review-Empfehlung nannte die falsche Klasse.

Befund: IST zu 100 % Konto-Liquiditaet (0 % in allen Risikoklassen). Der
Review zeigte trotzdem "Immobilien weicht von der Zielallokation ab.
Immobilien: aktuell 5.0 % / Ziel 5.0 %" und "4/5 Anlageklassen im Band".

Ursache (ares.html):
1. ``reviewStrategyComparisonRows`` bevorzugte ``live_rebalancing.bucket_drifts``.
   Ohne erfasste Bestaende bewertet die Live-Sicht jede Position
   "implied_from_target" (IST = Zielbetrag), d.h. IST == SOLL -- die Band-
   Pruefung lief gegen die Empfehlung statt gegen den echten IST.
2. ``reviewBandStateMeta`` behandelte ein Punktband (min == max, z.B.
   Liquiditaet 3.2-3.2 %) als "kein Band" und meldete 100 % vs. 3.2 % als
   "Im Band".

Soll: Band-Pruefung gegen die echten IST-Quoten (Vermoegenspositionen aus
``allocation.buckets``); die Live-Sicht nur, wenn sie vollstaendig auf echten
Bestaenden beruht.
"""
from __future__ import annotations

from tests.livetest_monolith_js import run_js

PRELUDE = """
var currentMandateData={mandate_type:'Anlageberatung'};
var REVIEW_ASSET_CLASS_ORDER=['equities','bonds','real_estate','alternatives','liquidity'];
function getCurrentPresentationMode(){return 'consulting';}
function simulationTerminalRappen(){return 0;}
function _rvSuitabilityPreflightSummary(){return {headline:'',note:''};}
function strategyMedianProjectionRappen(){return 0;}
function projectionHorizonYearLabel(){return '';}
function monteCarloPayload(){return null;}
"""

BUCKETS = """
var buckets=[
 {asset_class:'Aktien',current_weight_bps:0,target_weight_bps:4780,band_min_bps:4000,band_max_bps:5500,current_amount_rappen:0,target_amount_rappen:6739800},
 {asset_class:'Obligationen',current_weight_bps:0,target_weight_bps:3900,band_min_bps:2500,band_max_bps:4500,current_amount_rappen:0,target_amount_rappen:5499000},
 {asset_class:'Immobilien',current_weight_bps:0,target_weight_bps:500,band_min_bps:500,band_max_bps:2000,current_amount_rappen:0,target_amount_rappen:705000},
 {asset_class:'Alternative',current_weight_bps:0,target_weight_bps:500,band_min_bps:300,band_max_bps:800,current_amount_rappen:0,target_amount_rappen:705000},
 {asset_class:'Liquiditaet',current_weight_bps:10000,target_weight_bps:320,band_min_bps:320,band_max_bps:320,current_amount_rappen:15000000,target_amount_rappen:451200}];
// Live-Sicht ohne Bestaende: IST implizit = SOLL
var drifts=buckets.map(function(b){return {asset_class:b.asset_class,current_weight_bps:b.target_weight_bps,target_weight_bps:b.target_weight_bps,
  delta_weight_bps:0,band_min_bps:b.band_min_bps,band_max_bps:b.band_max_bps,current_market_value_rappen:b.target_amount_rappen,target_market_value_rappen:b.target_amount_rappen};});
var allocation={buckets:buckets,expected_return_bps:423,
  live_rebalancing:{bucket_drifts:drifts,holding_positions_count:0,implied_positions_count:9,position_drifts:[]}};
function rowsFor(a){return reviewStrategyComparisonRows(a).map(function(item){
  item.meta=reviewBandStateMeta({current_weight_bps:item.currentWeightBps,target_weight_bps:item.targetWeightBps,band_min_bps:item.bandMinBps,band_max_bps:item.bandMaxBps},item.assetKey);
  return item;});}
"""

FUNCS = (
    "reviewStrategyComparisonRows", "reviewBandStateMeta", "_reviewIsIlliquidAssetClass",
    "_reviewIsDiscretionaryMandate", "liveRebalancingPayload", "reviewAssetClassSortKey",
    "assetDisplayName", "formatBpsPercent", "_rvHeroConsultingHtml", "_rvHeroCommonChips",
    "_rvHeroChipsHtml",
)


def _scenario(extra: str = "") -> dict:
    return run_js(FUNCS, BUCKETS + extra + """
      var rows=rowsFor(allocation);
      var violated=rows.filter(function(r){return r.meta.tagClass==='tr2'&&!_reviewIsIlliquidAssetClass(r.assetKey);});
      var tight=rows.filter(function(r){return r.meta.tagClass==='ta'||(r.meta.tagClass==='tr2'&&_reviewIsIlliquidAssetClass(r.assetKey));});
      var hero=_rvHeroConsultingHtml(rows,violated,tight,allocation,{});
      return {rows:rows.map(function(r){return [r.assetKey,r.currentWeightBps,r.meta.label];}),html:hero.html};
    """, prelude=PRELUDE, optional=("reviewLiveDriftsBackedByHoldings",))


def test_review_checks_bands_against_real_ist_without_holdings():
    out = _scenario()
    current = {key: bps for key, bps, _label in out["rows"]}
    assert current.get("liquiditaet") == 10000, out["rows"]
    labels = {key: label for key, _bps, label in out["rows"]}
    assert labels["aktien"] == "Verletzt"
    assert labels["liquiditaet"] == "Verletzt", "Punktband 3.2-3.2 % bei 100 % IST nicht als verletzt erkannt"
    assert "5 Anlageklassen weichen von der Zielallokation ab" in out["html"]
    assert "Immobilien weicht" not in out["html"]
    assert "0/5 Anlageklassen im Band" in out["html"]


def test_live_view_used_when_fully_backed_by_real_holdings():
    out = _scenario("""
      allocation.live_rebalancing.holding_positions_count=9;
      allocation.live_rebalancing.implied_positions_count=0;
    """)
    current = {key: bps for key, bps, _label in out["rows"]}
    assert current.get("liquiditaet") == 320
    assert "Alle 5 Anlageklassen liegen im empfohlenen Band" in out["html"]
