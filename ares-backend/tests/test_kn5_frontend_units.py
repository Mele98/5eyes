"""KN5 (H-176-Pruefung): Review-Reserve (N-917R4-02) und Portfolio-Apportionierung
mit Toleranzschranke (N-917R4-05) -- echte Funktionen aus dem Bundle in Node.

* N-917R4-02  Ist die Reserve ausserhalb der Strategie groesser als die Liquiditaet
  (Persona C aus H-174: Beratungsvermoegen 399'000, Strategiebasis 230'970, Reserve
  168'030, Liquiditaet 35'000), zeigte die Review «-57.6 %» ohne Erklaerung, und
  Ist-% (Strategieanteil) stand neben Ist-CHF (Bestand). Jetzt: Ist-CHF = Strategie-
  anteil wie Ist-%, Bestand und «davon Reserve ausserhalb der Strategie» getrennt,
  die negative Liquiditaet als Reservelücke erklaert (Karte + Kopfzeile).
* N-917R4-05  Portfolio-Zeilen werden nur apportioniert, wenn die Abweichung zur
  AA-Klassensumme je Produkt hoechstens eine Rundungseinheit (1 Franken) betraegt
  und die Klasse keinen Live-Bestand enthaelt; sonst Rohwerte + Hinweis.
Gegenproben: Mutationen in H-177 (alle rot).
"""
from __future__ import annotations

from tests.livetest_monolith_js import run_js
from tests.monolith_source import FRONTEND_DIR

KN4 = (FRONTEND_DIR / "kn4-ui.js").read_text(encoding="utf-8")
MOUNT = "window=globalThis;document.readyState='complete';document.addEventListener=function(){};\n"
KN5 = (FRONTEND_DIR / "kn5-ui.js").read_text(encoding="utf-8")
# Wie im Browser: kn4-ui.js, dann kn5-ui.js (KN5 haengt sich ueber die KN4-Wrapper).
IIFE = KN4[KN4.index("(function(){"):] + "\n" + KN5[KN5.index("(function(){"):]

# Persona C (H-174), Buckets wie aus portfolio_engine_payload._bucket_rows / Response-Schema.
PERSONA_C = """
var allocation={advisory_wealth_rappen:39900000,strategy_base_rappen:23097000,buckets:[
  {asset_class:'Obligationen',current_weight_bps:10954,current_amount_rappen:25300000,current_strategy_amount_rappen:25300000,
   target_weight_bps:9200,target_amount_rappen:21249240,delta_weight_bps:-1754,band_min_bps:8000,band_max_bps:10000,comparison_basis:'strategy'},
  {asset_class:'Alternative',current_weight_bps:4806,current_amount_rappen:11100000,current_strategy_amount_rappen:11100000,
   target_weight_bps:280,target_amount_rappen:646716,delta_weight_bps:-4526,band_min_bps:0,band_max_bps:500,comparison_basis:'strategy'},
  {asset_class:'Liquiditaet',current_weight_bps:-5760,current_amount_rappen:3500000,current_strategy_amount_rappen:-13303000,
   target_weight_bps:520,target_amount_rappen:1201044,delta_weight_bps:6280,band_min_bps:0,band_max_bps:1000,comparison_basis:'strategy',
   reserve_rappen:16803000,reserve_funded_rappen:3500000,reserve_gap_rappen:13303000}]};
"""
NO_RESERVE = """
var allocation={advisory_wealth_rappen:50000000,strategy_base_rappen:50000000,buckets:[
  {asset_class:'Obligationen',current_weight_bps:6000,current_amount_rappen:30000000,current_strategy_amount_rappen:30000000,
   target_weight_bps:5000,target_amount_rappen:25000000,delta_weight_bps:-1000,band_min_bps:4000,band_max_bps:6000,comparison_basis:'advisory_wealth'},
  {asset_class:'Liquiditaet',current_weight_bps:4000,current_amount_rappen:20000000,current_strategy_amount_rappen:20000000,
   target_weight_bps:5000,target_amount_rappen:25000000,delta_weight_bps:1000,band_min_bps:0,band_max_bps:6000,comparison_basis:'advisory_wealth',
   reserve_rappen:0,reserve_funded_rappen:0,reserve_gap_rappen:0}]};
"""
REVIEW_FNS = ("reviewStrategyComparisonRows", "reviewLiveDriftsBackedByHoldings", "aresReviewReserveBasis",
              "aresReviewReserveBucket", "aresReviewReserveNote", "aresReviewPct", "formatBpsPercent", "fmtPct", "formatRappen",
              "_ccyArg", "ccyOf")
REVIEW_PRELUDE = """
function liveRebalancingPayload(){return null;}
function assetDisplayName(k){return String(k);}
function reviewAssetClassSortKey(){return 0;}
function aresBandNumber(v){return v==null?null:Number(v);}
function appCurrency(){return 'CHF';}
function reviewBandStateMeta(){return {};}
function _rvHeroCommonChips(a,rows){return [String(rows.length)+'/'+String(rows.length)+' Anlageklassen im Band'];}
function renderSrImplementationDecision(){document.getElementById('sr-implementation-steps').innerHTML='<div>Karte</div>';}
var strategyState={allocation:null};
"""


def _norm(value):
    return value.replace(" ", " ").replace("\xa0", " ").replace("−", "-") if isinstance(value, str) else value


def test_n917r4_02_review_ist_chf_and_percent_on_strategy_basis_reserve_separate():
    out = run_js(REVIEW_FNS, PERSONA_C + """
      strategyState.allocation=allocation;
      var rows=reviewStrategyComparisonRows(allocation), liq=rows.filter(function(r){return r.assetKey==='liquiditaet';})[0];
      renderSrImplementationDecision();
      return {liqCurrent:liq.currentRappen, liqBps:liq.currentWeightBps, holding:liq.holdingRappen, reserve:liq.reserveRappen,
        funded:liq.reserveFundedRappen, gap:liq.reserveGapRappen,
        sameBasis:rows.map(function(r){return Math.round(r.currentRappen/allocation.strategy_base_rappen*10000)-r.currentWeightBps;}),
        ist:aresReviewPct(rows,'liquiditaet','ist'), note:aresReviewReserveNote(allocation),
        card:document.getElementById('sr-implementation-steps').innerHTML,
        chips:_rvHeroCommonChips(allocation,rows,[],[])};
    """, prelude=REVIEW_PRELUDE + MOUNT + IIFE)
    # Ist-CHF = Strategieanteil (Bestand 35'000 - Reserve 168'030), dieselbe Basis wie Ist-%.
    assert out["liqCurrent"] == -13303000 and out["liqBps"] == -5760, out
    assert all(abs(d) <= 1 for d in out["sameBasis"]), out
    assert (out["holding"], out["reserve"], out["funded"], out["gap"]) == (3500000, 16803000, 3500000, 13303000), out
    note = _norm(out["note"])
    assert "davon Reserve ausserhalb der Strategie CHF 35'000" in note, note
    assert "nicht gedeckt" in note and "CHF 133'030" in note and "-57.6 %" in note, note
    assert "Strategieanteil" in note and "Bestand CHF 35'000" in note, note
    assert _norm(out["ist"]) == "-57.6 %", out  # nicht stillschweigend 0.0 %
    assert "data-kn5-reserve-note" in out["card"] and "nicht gedeckt" in _norm(out["card"]), out
    assert any("Liquiditätsreserve ausserhalb der Strategie CHF 168'030" in _norm(c) for c in out["chips"]), out


def test_n917r4_02_without_reserve_nothing_changes():
    out = run_js(REVIEW_FNS, NO_RESERVE + """
      strategyState.allocation=allocation;
      var rows=reviewStrategyComparisonRows(allocation);
      renderSrImplementationDecision();
      return {current:rows.map(function(r){return r.currentRappen;}), extra:rows.filter(function(r){return 'reserveRappen' in r;}).length,
        note:aresReviewReserveNote(allocation), card:document.getElementById('sr-implementation-steps').innerHTML,
        chips:_rvHeroCommonChips(allocation,rows,[],[])};
    """, prelude=REVIEW_PRELUDE + MOUNT + IIFE)
    assert out == {"current": [30000000, 20000000], "extra": 0, "note": "", "card": "<div>Karte</div>",
                   "chips": ["2/2 Anlageklassen im Band"]}, out


def test_n917r4_02_response_schema_carries_reserve_fields():
    from schemas.allocation import AllocationBucketResponse

    fields = set(AllocationBucketResponse.model_fields)
    assert {"comparison_basis", "current_strategy_amount_rappen", "reserve_rappen",
            "reserve_funded_rappen", "reserve_gap_rappen"} <= fields
    row = {"asset_class": "Liquiditaet", "current_weight_bps": -5760, "current_amount_rappen": 3500000,
           "current_strategy_amount_rappen": -13303000, "target_weight_bps": 520, "target_amount_rappen": 1201044,
           "delta_weight_bps": 6280, "band_min_bps": 0, "band_max_bps": 1000, "comparison_basis": "strategy",
           "reserve_rappen": 16803000, "reserve_funded_rappen": 3500000, "reserve_gap_rappen": 13303000,
           "current_amount_total_rappen": 3500000}
    dumped = AllocationBucketResponse(**row).model_dump()
    assert dumped["reserve_gap_rappen"] == 13303000 and dumped["comparison_basis"] == "strategy"
    generated = (FRONTEND_DIR / "reporting" / "src" / "api" / "generated" / "openapi.ts").read_text(encoding="utf-8")
    assert "reserve_gap_rappen?: number | null;" in generated


# ---------------------------------------------------------------- N-917R4-05
APPORTION_FNS = ("aresPortfolioDisplayPositions", "allocationReserveBreakdown", "assetDisplayName")
ALLOC = """var allocation={advisory_wealth_rappen:39900000,strategy_base_rappen:23097000,buckets:[
  {asset_class:'Obligationen',target_weight_bps:9200},{asset_class:'Liquiditaet',target_weight_bps:520},{asset_class:'Alternative',target_weight_bps:280}]};"""


def test_n917r4_05_rounding_rest_is_still_apportioned():
    out = run_js(APPORTION_FNS, ALLOC + """
      var pos=[{asset_class:'Obligationen',target_amount_rappen:12811450},{asset_class:'Obligationen',target_amount_rappen:8437800}];
      var shown=aresPortfolioDisplayPositions(pos,allocation);
      return {sum:shown[0].target_amount_rappen+shown[1].target_amount_rappen, notes:shown.apportionNotes};
    """)
    assert out["notes"] == [] and out["sum"] % 100 == 0, out


def test_n917r4_05_large_deviation_or_mixed_class_is_not_apportioned():
    out = run_js(APPORTION_FNS, ALLOC + """
      // Teilabdeckung: nur ein Obligationen-Produkt (128'114 statt 212'492) -> keine Aufblaehung.
      var partial=aresPortfolioDisplayPositions([{asset_class:'Obligationen',target_amount_rappen:12811450}],allocation);
      // Gemischte Klasse: Live-Zeile + Zielzeile.
      var mixed=aresPortfolioDisplayPositions([{asset_class:'Obligationen',target_amount_rappen:12811450,current_market_value_rappen:12000000},
        {asset_class:'Obligationen',target_amount_rappen:8437800}],allocation);
      return {partial:partial[0].target_amount_rappen, partialNotes:partial.apportionNotes,
        mixed:mixed[1].target_amount_rappen, mixedNotes:mixed.apportionNotes};
    """)
    assert out == {"partial": 12811450, "partialNotes": ["Obligationen"],
                   "mixed": 8437800, "mixedNotes": ["Obligationen"]}, out


def test_n917r4_05_portfolio_shows_hint_when_not_apportioned():
    out = run_js(APPORTION_FNS, ALLOC + """
      strategyState.allocation=allocation;
      renderPortfolioSections([{asset_class:'Obligationen',target_amount_rappen:12811450}]);
      return {html:document.getElementById('po-portfolio-sections').innerHTML, shown:SHOWN[0][0].target_amount_rappen};
    """, prelude="""
      var SHOWN=[],currentPortfolioPositions=[];var strategyState={allocation:null};
      function renderPortfolioSections(p){SHOWN.push(p);document.getElementById('po-portfolio-sections').innerHTML='<div>Zeilen</div>';}
      function aresTerm(n){return n;}
    """ + MOUNT + IIFE)
    assert out["shown"] == 12811450, out
    assert "data-kn5-apportion-note" in out["html"] and "Rundungsabgleich nicht angewendet (Obligationen)" in out["html"], out
