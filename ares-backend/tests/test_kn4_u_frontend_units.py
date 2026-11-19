"""KN4-U (Dok. 119 / H-172-Pruefung): Logik-Tests der Classic-Berateroberflaeche ohne Browser.

Echte Funktionen aus dem Bundle (inkl. ``kn3-ui.js``/``kn4-ui.js``) laufen in Node;
Gegenproben je Test bzw. als Mutationen (H-175).

* E2E4-01   ein Reset fuer Kundenwechsel und neues Mandat (TOTAL, Torte, Tortenmitte).
* N-917R3-01  nach jedem await abbrechen, wenn der Kunde gewechselt hat.
* N-917R3-02  KYC-Wiederherstellung nur fuer den eigenen POST, gleicher Kunde und Mandat.
* N-917R3-05  fehlendes Ist = nicht bewertbar (Karte, Kopfzeile).
* E2E4-06   eine Rundungsquelle je Zahl (Review-Prozent, Portfolio-Zeilen = AA-Betrag).
* E2E4-08/09/14  Cashflow-Text bei belegten Kursen, Portfolio bei "veraltet", leere Achse.
* N-917R3-08  Depot-Aufteilung exakt 100.0 % nach Rundung auf 0.1 %.
"""
from __future__ import annotations

from tests.livetest_monolith_js import run_js
from tests.monolith_source import FRONTEND_DIR, read_monolith_bundle

KN3 = (FRONTEND_DIR / "kn3-ui.js").read_text(encoding="utf-8")
KN4 = (FRONTEND_DIR / "kn4-ui.js").read_text(encoding="utf-8")
# Die IIFEs der Teile haengen sich ueber window[...] ein: window = globalThis (wie im Browser).
MOUNT = "window=globalThis;document.readyState='complete';document.addEventListener=function(){};\n"


def _iife(src: str) -> str:
    return src[src.index("(function(){"):]


# ---------------------------------------------------------------- E2E4-01
def test_e2e4_01_reset_clears_previous_client_amount_and_pie():
    out = run_js(("aresBandOf",), """
      aresResetMandateView();
      return {total:TOTAL, ccy:TOTAL_CCY, alloc:alloc.length, donut:DONUT, calls:RESET};
    """, prelude="""
      var TOTAL=399000, TOTAL_CCY='CHF', alloc=[{n:'Aktien',ist:40}], DONUT=0, RESET=0;
      function aresResetMandateView(){RESET++;}
      function syncAllocationDonutFromStrategyState(){DONUT++;}
      var strategyState={allocation:null};
    """ + MOUNT + _iife(KN4))
    assert out == {"total": 0, "ccy": None, "alloc": 0, "donut": 1, "calls": 1}, out


def test_e2e4_01_both_paths_use_the_same_reset():
    html = read_monolith_bundle()
    load = html[html.index("async function loadClientById("):html.index("async function loadClientById(") + 400]
    new = html[html.index("function showNewClientScreen("):html.index("function showNewClientScreen(") + 900]
    assert "aresResetMandateView" in load and "aresResetMandateView" in new
    assert "wrap('aresResetMandateView'" in KN4 and "TOTAL = 0" in KN4


# ---------------------------------------------------------------- N-917R3-01
def test_n917r3_01_late_wealth_answer_for_previous_client_writes_nothing():
    out = run_js(("refreshWealthUI", "clientScopedSummary"), """
      var p=refreshWealthUI('A');
      currentClientId='B';             // schneller Wechsel waehrend der verzoegerten Antwort
      release();
      return p.then(function(){return {kpi:document.getElementById('kpi-reinvermoegen').textContent,
        summary:currentWealthSummary, rendered:RENDERED};});
    """, prelude="""
      var currentClientId='A', currentWealthSummary={client_id:'B',net_worth_chf:500000}, RENDERED=[];
      document.getElementById('kpi-reinvermoegen').textContent='CHF 500000';
      var release;var gate=new Promise(function(r){release=r;});
      var API={get:function(url){return gate.then(function(){return /wealth-summary/.test(url)
        ?{client_id:'A',net_worth_chf:987654,advisory_wealth_chf:987654,amount_currency:'CHF'}:[{id:'pa',client_id:'A'}];});}};
      function wealthSummaryUrl(cid){return '/clients/'+cid+'/wealth-summary';}
      function renderWealthPositions(p){RENDERED.push(p);}
      function fmtCHF(v,c){return c+' '+v;}
      function syncAllocationPendingViews(){}
      var strategyState={allocation:null};
    """)
    assert out == {"kpi": "CHF 500000", "summary": {"client_id": "B", "net_worth_chf": 500000}, "rendered": []}, out


def test_n917r3_01_kn3_wrapper_stops_after_switch():
    out = run_js(("aresBandOf",), """
      var p=refreshWealthUI('A');currentClientId='B';release();
      return p.then(function(){return LOG;});
    """, prelude="""
      var currentClientId='A', LOG=[];var release;var gate=new Promise(function(r){release=r;});
      function refreshWealthUI(cid){return gate;}
      function refreshCashflowsUI(cid){LOG.push('cashflows:'+cid);}
      function getActiveMandateId(){return 'M';}
      function buildDLegend(){LOG.push('legend');}
      function renderWealthPositions(){}
      var strategyState={allocation:null};
    """ + MOUNT + _iife(KN3))
    assert out == [], out


# ---------------------------------------------------------------- N-917R3-02
KYC_PRELUDE = """
  var currentClientId='A', currentMandateId='MA', ERR=[];
  function getActiveMandateId(){return currentMandateId;}
  function showAppError(m){ERR.push(m);}
  var IDS=['kyc-form','kyc-date','kyc-ref','kyc-risk','kyc-pep','kyc-review','kyc-ident-date'];
  IDS.forEach(function(id){document.getElementById(id).value='v-'+id;document.getElementById(id).type='text';});
  var ok=document.getElementById('kyc-ident-ok');ok.type='checkbox';ok.checked=true;
  document.getElementById('sd-client-compliance').querySelectorAll=function(){return IDS.map(function(id){return document.getElementById(id);}).concat([ok]);};
  var API={post:function(url){return Promise.reject(new Error('API 422'));}};
  function clearForm(){IDS.forEach(function(id){document.getElementById(id).value='';});ok.checked=false;}
"""


def _kyc(orig_body: str):
    return run_js(("aresBandOf",), """
      return createKycConfirmation().then(function(){return IDS.map(function(id){return document.getElementById(id).value;}).concat([ok.checked]);});
    """, prelude=KYC_PRELUDE + "async function createKycConfirmation(){" + orig_body + "}\n" + MOUNT + _iife(KN3))


def test_n917r3_02_own_failed_post_same_client_restores():
    out = _kyc("try{await API.post('/clients/A/kyc-confirmations',{});}catch(e){} clearForm();")
    assert out[0] == "v-kyc-form" and out[-1] is True, out


def test_n917r3_02_client_switch_during_post_does_not_restore_into_new_client():
    out = _kyc("try{await API.post('/clients/A/kyc-confirmations',{});}catch(e){} currentClientId='B';currentMandateId='MB';clearForm();")
    assert out == [""] * 7 + [False], out


def test_n917r3_02_foreign_failed_post_is_not_counted():
    out = _kyc("try{await API.post('/mandates/MA/something-else',{});}catch(e){} clearForm();")
    assert out == [""] * 7 + [False], out


# ---------------------------------------------------------------- N-917R3-05
NE_FUNCS = ("reviewBandStateMeta", "reviewStrategyComparisonRows", "_reviewIsIlliquidAssetClass", "_reviewIsDiscretionaryMandate",
            "liveRebalancingPayload", "reviewAssetClassSortKey", "assetDisplayName", "formatBpsPercent", "aresBandOf",
            "aresBandStatus", "aresBandNumber", "_rvHeroCommonChips", "reviewLiveDriftsBackedByHoldings")


def test_n917r3_05_missing_current_is_not_evaluable_on_card_and_header():
    out = run_js(NE_FUNCS, """
      var a={buckets:[{asset_class:'Aktien',current_weight_bps:null,target_weight_bps:0,band_min_bps:0,band_max_bps:0},
                      {asset_class:'Obligationen',current_weight_bps:5000,target_weight_bps:5000,band_min_bps:4000,band_max_bps:6000}]};
      var rows=reviewStrategyComparisonRows(a).map(function(item){item.meta=reviewBandStateMeta({current_weight_bps:item.currentWeightBps,
        target_weight_bps:item.targetWeightBps,band_min_bps:item.bandMinBps,band_max_bps:item.bandMaxBps},item.assetKey);return item;});
      var violated=rows.filter(function(r){return r.meta.tagClass==='tr2';}),tight=rows.filter(function(r){return r.meta.tagClass==='ta';});
      return {labels:rows.map(function(r){return r.meta.label;}),chips:_rvHeroCommonChips(a,rows,violated,tight)};
    """, prelude="""
      var currentMandateData={mandate_type:'Anlageberatung'};function getCurrentPresentationMode(){return 'consulting';}
      var REVIEW_ASSET_CLASS_ORDER=['equities','bonds','real_estate','alternatives','liquidity'];
      function strategyMedianProjectionRappen(){return 0;}function projectionHorizonYearLabel(){return '';}function monteCarloPayload(){return null;}
    """ + MOUNT + _iife(KN4))
    assert out["labels"] == ["Nicht bewertbar", "Im Band"], out
    assert out["chips"][0] == "1/2 Anlageklassen im Band · 1 nicht bewertbar", out


# ---------------------------------------------------------------- E2E4-06
A_ROWS = """var rows=[{assetKey:'obligationen',currentWeightBps:4444,targetWeightBps:9314},
  {assetKey:'alternative',currentWeightBps:0,targetWeightBps:443},{assetKey:'liquiditaet',currentWeightBps:5556,targetWeightBps:243}];"""


def test_e2e4_06_review_percent_uses_the_same_apportioned_value_as_aa():
    out = run_js(("aresReviewPct", "formatBpsPercent", "sollPct"), A_ROWS + """
      var buckets=rows.map(function(r){return {asset_class:r.assetKey,target_weight_bps:r.targetWeightBps};});
      return {review:aresReviewPct(rows,'obligationen','soll'), aa:sollPct('obligationen',9314,buckets), raw:AresRounding.formatPercentBps(9314,1,{typography:'screen'}),
        ist:aresReviewPct(rows,'obligationen','ist')};
    """)
    norm = {k: v.replace(" ", " ").replace("\xa0", " ") for k, v in out.items()}
    assert norm["review"] == norm["aa"] == "93.2 %", out  # Ausgleich auf 100.0 % wie AA/PDF
    assert norm["raw"] == "93.1 %", out                   # Gegenprobe: alte Einzelrundung der Review-Karte
    assert norm["ist"] == "44.4 %", out


def test_e2e4_06_portfolio_rows_sum_to_aa_class_amount():
    out = run_js(("aresPortfolioDisplayPositions", "allocationReserveBreakdown", "assetDisplayName"), """
      var allocation={advisory_wealth_rappen:39900000,strategy_base_rappen:23097000,buckets:[
        {asset_class:'Obligationen',target_weight_bps:9200},{asset_class:'Liquiditaet',target_weight_bps:520},{asset_class:'Alternative',target_weight_bps:280}]};
      var pos=[{asset_class:'Obligationen',target_amount_rappen:12811450},{asset_class:'Obligationen',target_amount_rappen:8437800},
               {asset_class:'Liquiditaet',target_amount_rappen:1201044},{asset_class:'Alternative',target_amount_rappen:646716}];
      var shown=aresPortfolioDisplayPositions(pos,allocation);
      var rb=allocationReserveBreakdown(allocation);
      var pa=AresRounding.presentationAmounts(rb.advisoryRappen,rb.strategyBaseRappen,[9200,520,280],['Obligationen','Liquiditaet','Alternative'],2);
      var obl=shown[0].target_amount_rappen+shown[1].target_amount_rappen;
      var total=shown.reduce(function(a,r){return a+r.target_amount_rappen;},0);
      var rawRounded=pos.reduce(function(a,r){return a+Math.round(r.target_amount_rappen/100);},0);
      return {obl:obl/100, aaObl:pa.buckets[0], total:total/100, aaTotal:pa.buckets[0]+pa.buckets[1]+pa.buckets[2], untouched:pos[0].target_amount_rappen,
        rawRowsSum:rawRounded};
    """)
    assert out["obl"] == out["aaObl"], out
    assert out["total"] == out["aaTotal"] == 230970, out
    assert out["untouched"] == 12811450, out  # Rohdaten bleiben unveraendert (Kopie)


# ---------------------------------------------------------------- E2E4-08 / E2E4-09 / E2E4-14
def test_e2e4_08_no_umrechnung_offen_when_rates_are_covered():
    out = run_js(("aresBandOf",), """
      var covered=istProjectionBasisUnavailableReason();MIX={blocked:true};var missing=istProjectionBasisUnavailableReason();
      return [covered,missing];
    """, prelude="""
      var MIX={currency:'CHF',advisoryRappen:1};
      function istProjectionBasisUnavailableReason(){return 'Ist-Vermögenspfad und Ist-Gewichte: Positionen in mehreren Währungen (CHF, USD). Umrechnung offen – die Anlagestrategie rechnet mit belegten Kursen (Asset Allokation).';}
      function activeClientWealthPositions(){return [{currency:'CHF'},{currency:'USD'}];}
      function wealthMixedTotals(){return MIX;}
    """ + MOUNT + _iife(KN4))
    assert "Umrechnung offen" not in out[0] and "Kurse sind belegt" in out[0], out
    assert "Umrechnung offen" in out[1], out


def test_e2e4_09_stale_portfolio_shows_cause_locked_and_no_zero():
    out = run_js(("aresBandOf",), """
      return refreshPortfolioFromStoredState().then(function(r){return {r:r,called:CALLED,
        html:document.getElementById('po-portfolio-sections').innerHTML,sub:document.getElementById('po-price-quality-sub').textContent,
        fin:document.getElementById('btn-po-finalize').disabled,sync:SYNC};});
    """, prelude="""
      var CALLED=0,SYNC=0;var strategyState={allocation:null};
      async function refreshPortfolioFromStoredState(){CALLED++;return true;}
      function aresStaleCause(){return 'Wechselkurs USD geändert';}
      function aresSyncAmountViews(){SYNC++;}
    """ + MOUNT + _iife(KN4))
    assert out["r"] is False and out["called"] == 0, out  # kein Generierversuch -> kein "konnte nicht generiert werden"
    assert "Strategie veraltet" in out["html"] and "Wechselkurs USD geändert" in out["html"] and "CHF 0" not in out["html"], out
    assert "gesperrt" in out["sub"] and out["fin"] is True and out["sync"] == 1, out


def test_e2e4_14_empty_projection_hides_axis_and_strategy_restores_it():
    out = run_js(("aresBandOf",), """
      syncAllocationPendingViews();var hidden=charts.opt.options.scales.y.display;
      strategyState.allocation={buckets:[1]};updateProjectionChartsFromSimulation({});
      return [hidden,charts.opt.options.scales.y.display];
    """, prelude="""
      var charts={opt:{options:{scales:{y:{}}},update:function(){}}};var strategyState={allocation:null};
      function syncAllocationPendingViews(){} function updateProjectionChartsFromSimulation(){} function upgradeFanChartWithMonteCarlo(){}
    """ + MOUNT + _iife(KN4))
    assert out == [False, True], out


# ---------------------------------------------------------------- N-917R3-08
def test_n917r3_08_depot_split_exactly_100_after_rounding_to_tenth():
    def run(values):
        return run_js(("buildWealthPositionPayload",), f"""
          var v={values};var ids=['sc-akt','sc-obl','sc-imm','sc-liq','sc-alt'];
          try{{buildWealthPositionPayload('Depot','Beratungsvermögen','');return 'ok';}}catch(e){{return String(e.message);}}
        """, prelude=f"""
          var V={values};
          function getInputValue(id){{var i=['sc-akt','sc-obl','sc-imm','sc-liq','sc-alt'].indexOf(id);if(i>=0)return String(V[i]);
            if(id==='maw-depot-label')return 'Depot';if(id==='maw-depot-value')return '1000';return '';}}
          var AresRounding={{formatPercent:function(v){{return String(v)+' %';}}}};
          var currentWealthEditId=null,currentWealthPositions=[];function newRecordCurrency(){{return 'CHF';}}
          function parseCHF(v){{return Number(v)*100;}} function parsePercentToBps(){{return null;}} function joinNotes(a){{return a.join(' ');}}
        """)
    assert run("[33.33,33.33,33.34,0,0]") == "ok"
    assert run("[33.33,33.33,33.33,0,0]") == "ok"       # 99.99 % -> 100.0 % nach Rundung (wie Server KN4-B)
    assert run("[50,49.9,0,0,0]").startswith("Allokation muss 100%")   # 99.9 % (alte Toleranz 0.5 % liess das durch)
    assert run("[50,50.4,0,0,0]").startswith("Allokation muss 100%")


def test_ci_runs_kn4u_livetest_in_its_own_job():
    from pathlib import Path
    wf = (Path(__file__).resolve().parents[2] / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    job = wf[wf.index("kn4u-livetest:"):]
    assert "test_livetest_kn4_u_ui.py" in job[:3000] and "ARES_REQUIRE_PLAYWRIGHT" in job[:3000]


def test_n917r3_05_aa_chart_draws_zero_band_as_line():
    out = run_js(("aaChartBandHtml", "aaChartPctText", "aaChartEsc"), """
      return [aaChartBandHtml({min:0,max:0},0,'Aktien'), aaChartBandHtml(null,0,'Aktien')];
    """)
    assert out[1] == "", out
    assert "aa-band-range" in out[0] and "width:0.6%" in out[0] and "Bandbreite 0" in out[0], out
    src = (FRONTEND_DIR / "aa-chart.js").read_text(encoding="utf-8")
    assert "aresBandOf(b.band_min_bps,b.band_max_bps)" in src and "band.max>0" not in src


def test_e2e4_06_review_card_and_hero_use_the_single_percent_source():
    html = read_monolith_bundle()
    dec = html[html.index("function renderSrImplementationDecision("):html.index("function renderSrApiSummary(")]
    assert "aresReviewPct(reviewStrategyComparisonRows(allocation),item.assetKey,'soll')" in dec
    assert "Ziel '+escapeHtml(formatBpsPercent(item.targetWeightBps))" not in dec
    assert "aresReviewPct(rows,topInfo.assetKey,'soll')" in html and "aresReviewPct(rows,top.assetKey,'ist')" in html
