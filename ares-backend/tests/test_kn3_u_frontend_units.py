"""KN3-U (Dok. 118 / H-167 R2): Logik-Tests der Classic-Berateroberflaeche ohne Browser.

Echte Funktionen aus dem Monolithen bzw. aus ``mandate-view.js`` laufen in Node
gegen ein minimales DOM. Die Gegenproben stehen je Test (alte Regel bzw.
fehlender Aufruf muss rot werden); zusaetzlich sind sie als Mutationen in H-171
dokumentiert.

* E2E3-01  EINE Bandlogik: Band 0/0 ist eine Obergrenze 0; nur fehlende
           Bandangaben = kein Band (Karte, Kopfzeile, Grafik, Trigger).
* E2E3-02  Kurs-/Vermoegensaenderung laedt Vermoegen, Cashflows und Strategiebasis neu.
* E2E3-05/06, N-917R2-06  Ursache aus der Status-API vor dem 409-Text; nach dem
           Speichern der Stammdaten entscheidet der Server ueber "veraltet".
* E2E3-07  Cashflow-Seite laedt nach jeder Vermoegensaenderung neu (refreshWealthUI).
* E2E3-10/13/14, N-917R2-03  Achse, Amortisationsende, kein "veraltet" ohne
           Strategie, Banner-Reset.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from tests.livetest_monolith_js import run_js
from tests.monolith_source import FRONTEND_DIR, read_monolith_bundle
from tests.test_kn_u_frontend_units import _run

# ---------------------------------------------------------------- E2E3-01 Bandlogik
BAND_PRELUDE = """
var currentMandateData={mandate_type:'Anlageberatung'};
var REVIEW_ASSET_CLASS_ORDER=['equities','bonds','real_estate','alternatives','liquidity'];
function getCurrentPresentationMode(){return 'consulting';}
function _rvSuitabilityPreflightSummary(){return {headline:'',note:''};}
function strategyMedianProjectionRappen(){return 0;}
function projectionHorizonYearLabel(){return '';}
function monteCarloPayload(){return null;}
function fmtPct(v,d){return (Number(v)/100).toFixed(d==null?1:d)+' %';}
"""
BAND_FUNCS = (
    "aresBandOf", "aresBandStatus", "aresBandNumber", "reviewBandStateMeta", "reviewStrategyComparisonRows",
    "_reviewIsIlliquidAssetClass", "_reviewIsDiscretionaryMandate", "liveRebalancingPayload",
    "reviewAssetClassSortKey", "assetDisplayName", "formatBpsPercent", "_rvHeroConsultingHtml",
    "_rvHeroCommonChips", "_rvHeroChipsHtml", "reviewLiveDriftsBackedByHoldings", "aresReviewPct",
)
# Persona A (Dok. 118): Kapitalschutz, Ist 35.6 % Aktien, Aktien- und Immobilienband 0/0.
PERSONA_A = """
var buckets=[
 {asset_class:'Aktien',current_weight_bps:3556,target_weight_bps:0,band_min_bps:0,band_max_bps:0,current_amount_rappen:16000000,target_amount_rappen:0},
 {asset_class:'Obligationen',current_weight_bps:4444,target_weight_bps:9330,band_min_bps:8500,band_max_bps:10000,current_amount_rappen:20000000,target_amount_rappen:41976000},
 {asset_class:'Immobilien',current_weight_bps:0,target_weight_bps:0,band_min_bps:0,band_max_bps:0,current_amount_rappen:0,target_amount_rappen:0},
 {asset_class:'Alternative',current_weight_bps:0,target_weight_bps:310,band_min_bps:0,band_max_bps:500,current_amount_rappen:0,target_amount_rappen:1408500},
 {asset_class:'Liquiditaet',current_weight_bps:2000,target_weight_bps:360,band_min_bps:0,band_max_bps:1000,current_amount_rappen:9000000,target_amount_rappen:1615500}];
var allocation={buckets:buckets,expected_return_bps:180};
function scenario(){
  var rows=reviewStrategyComparisonRows(allocation).map(function(item){
    item.meta=reviewBandStateMeta({current_weight_bps:item.currentWeightBps,target_weight_bps:item.targetWeightBps,band_min_bps:item.bandMinBps,band_max_bps:item.bandMaxBps},item.assetKey);
    return item;});
  var violated=rows.filter(function(r){return r.meta.tagClass==='tr2'&&!_reviewIsIlliquidAssetClass(r.assetKey);});
  var tight=rows.filter(function(r){return r.meta.tagClass==='ta'||(r.meta.tagClass==='tr2'&&_reviewIsIlliquidAssetClass(r.assetKey));});
  var hero=_rvHeroConsultingHtml(rows,violated,tight,allocation,{});
  var labels={};rows.forEach(function(r){labels[r.assetKey]=[r.meta.label,r.meta.action];});
  return {labels:labels,html:hero.html};
}
"""


def test_e2e3_01_point_band_zero_is_a_band_card_and_header_agree():
    out = run_js(BAND_FUNCS, PERSONA_A + """
      var now=scenario();
      // Gegenprobe: alte Regel (0/0 = kein Band) liefert den Befund "Im Band · Beobachten".
      aresBandOf=function(mn,mx){mn=Number(mn||0);mx=Number(mx||0);return (mx>mn||(mx>0&&mx===mn))?{min:mn,max:mx,point:mn===mx}:null;};
      var old=scenario();
      return {now:now,old:old};
    """, prelude=BAND_PRELUDE)
    now, old = out["now"], out["old"]
    assert now["labels"]["aktien"] == ["Verletzt", "Empfehlung anpassen"], now["labels"]
    assert now["labels"]["immobilien"] == ["Im Band", "Keine Aktion"], now["labels"]  # 0 % bei Obergrenze 0
    # Kopfzeile zaehlt dieselbe Bewertung: Aktien, Obligationen, Liquiditaet verletzt, Alternative eng.
    assert "4 Anlageklassen weichen von der Zielallokation ab" in now["html"], now["html"]
    assert "1/5 Anlageklassen im Band" in now["html"], now["html"]
    plain = now["html"].replace(" ", " ").replace(" ", " ")
    assert "Obligationen: aktuell 44.4 % / Ziel 93.3 %" in plain, now["html"]
    # Gegenprobe rot: der Befund aus Dok. 118 (Karte "Im Band · Beobachten", Kopfzeile 2/5).
    assert old["labels"]["aktien"] == ["Im Band", "Beobachten"], old["labels"]
    assert "2/5 Anlageklassen im Band" in old["html"], old["html"]


def test_e2e3_01_missing_band_is_no_band_and_h6_point_band_still_violated():
    out = run_js(BAND_FUNCS, """
      function meta(cur,tgt,mn,mx){return reviewBandStateMeta({current_weight_bps:cur,target_weight_bps:tgt,band_min_bps:mn,band_max_bps:mx},'aktien');}
      var rows=reviewStrategyComparisonRows({buckets:[{asset_class:'Aktien',current_weight_bps:3556,target_weight_bps:0},
        {asset_class:'Obligationen',current_weight_bps:0,target_weight_bps:0,band_min_bps:0,band_max_bps:0}]});
      return {missing:meta(3556,0,undefined,undefined).label, nul:meta(3556,0,null,null).label, empty:meta(3556,0,'','').label,
        zero:meta(3556,0,0,0).label, zeroOk:meta(0,0,0,0).label, h6:meta(10000,320,320,320).label, h6ok:meta(320,320,320,320).label,
        inverted:meta(3556,0,500,100).label, statusNone:aresBandStatus(10,null,5), statusIn:aresBandStatus(0,0,0),
        statusOut:aresBandStatus(1,0,0), rowBands:rows.map(function(r){return [r.assetKey,r.bandMinBps,r.bandMaxBps];})};
    """, prelude=BAND_PRELUDE)
    assert out["missing"] == out["nul"] == out["empty"] == "Im Band", out  # fehlende Angaben = kein Band
    assert out["zero"] == "Verletzt" and out["zeroOk"] == "Im Band", out
    assert out["h6"] == "Verletzt" and out["h6ok"] == "Im Band", out  # Live-Test H6 bleibt erhalten
    assert out["inverted"] == "Im Band", out  # ungueltiges Band (max < min) = kein Band
    assert (out["statusNone"], out["statusIn"], out["statusOut"]) == ("none", "in", "violated"), out
    # "fehlt" bleibt null, "0" bleibt 0 (keine Vermischung mehr ueber Number(x||0)).
    assert out["rowBands"] == [["aktien", None, None], ["obligationen", 0, 0]], out


def test_kn4_review_band_visual_removed_dead_code():
    """KN4-U: reviewBandVisualHtml hatte seit dem Rebrand keinen Aufrufer (keine Bandgrafik in der Review) -> entfernt."""
    assert "reviewBandVisualHtml(" not in read_monolith_bundle()


def test_e2e3_01_every_band_evaluation_uses_the_shared_logic():
    src = read_monolith_bundle()
    runtime = (FRONTEND_DIR / "goal-review-runtime.js").read_text(encoding="utf-8")
    assert "pointBand=max>0&&max===min" not in src, "alte Sonderregel 0/0 = kein Band"
    kn3 = (FRONTEND_DIR / "kn3-ui.js").read_text(encoding="utf-8")
    assert src.count("function aresBandOf(") == 1 and kn3.count("\nfunction aresBandOf(") == 1
    assert "function aresBandOf(" not in runtime
    meta = src[src.index("function reviewBandStateMeta("):src.index("function reviewLiveDriftsBackedByHoldings(")]
    assert "aresBandOf(bucket&&bucket.band_min_bps,bucket&&bucket.band_max_bps)" in meta and "hasBand=!!band" in meta
    trigger = src[src.index("function renderTriggerBucket("):src.index("function renderTriggerBucket(") + 2500]
    assert "aresBandStatus(liveDrift.current_weight_bps,liveDrift.band_min_bps,liveDrift.band_max_bps)" in trigger
    assert "bandMinBps:Number(bucket.band_min_bps||0)" not in src
    # Alle Bewertungsstellen der Review laufen ueber reviewBandStateMeta.
    assert src.count("item.meta=reviewBandStateMeta(") == 3 and src.count("reviewBandStateMeta({") >= 1


# ---------------------------------------------------------------- E2E3-02 / E2E3-07 Betraege
AMOUNT_STUBS = r"""
var LOG=[];
globalThis.currentClientId='C1';
globalThis.isDemoClientId=function(){return false;};
globalThis.resetWealthSummaryCache=function(){LOG.push('reset');};
globalThis.refreshWealthUI=async function(cid){LOG.push('wealth:'+cid);SNAP.advisoryRappen=49000000;SNAP.fxOpen=false;};
globalThis.refreshCashflowsUI=async function(cid){LOG.push('cashflows:'+cid);};
globalThis.buildDLegend=function(){LOG.push('legend:'+SNAP.advisoryRappen);};
"""


def _amount_run(script: str):
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
        fh.write(AMOUNT_STUBS)
        stubs = Path(fh.name)
    try:
        return _run(script, extra_sources=(stubs,))
    finally:
        stubs.unlink(missing_ok=True)


def test_e2e3_02_fx_save_reloads_amounts_before_revalidating():
    out = _amount_run("""
      SNAP.advisoryRappen=48800000;
      strategyState.allocation=null;
      globalThis.API={get:async function(url){LOG.push('GET '+url.replace(/^.*\\/mandates\\/[^/]+/,''));
        if(/payload$/.test(url)){var e=new Error('API 409');e.status=409;e.detail='Die gespeicherte Soll-Allokation ist veraltet: Wechselkurs USD seit der Berechnung geaendert.';throw e;}
        return {publication_status:'PUBLICATION_INVALID',freshness:{status:'STALE',causes:[{kind:'fx_rate',text:'Wechselkurs USD geändert',currencies:['USD']}]}};}};
      await saveAdminFxRates();
      return {log:LOG, po:EL['po-advisory-wealth'].textContent, cause:aresStaleCause()};
    """)
    log = out["log"]
    assert log[:3] == ["reset", "wealth:C1", "cashflows:C1"], log
    assert log.index("cashflows:C1") < log.index("GET /target-allocation/current/payload"), log
    assert "GET /allocation-publication" in log, log
    assert "legend:49000000" in log and "legend:48800000" not in log, log
    assert out["po"] == "CHF 490000", out  # Portfolio-Kopf ohne Allokation: aktueller Stand
    assert out["cause"] == "Wechselkurs USD geändert", out


def test_e2e3_02_counterproof_without_hook_amount_stays_old():
    """Gegenprobe: ohne Neuladen (alter Hook) bleibt der Betrag auf dem alten Stand."""
    src = (FRONTEND_DIR / "mandate-view.js").read_text(encoding="utf-8")
    assert "if (r !== false) { if (g('aresRefreshMandateAmounts')) await aresRefreshMandateAmounts(); await revalidateActiveAllocation();" in src
    out = _amount_run("""
      SNAP.advisoryRappen=48800000;strategyState.allocation=null;
      globalThis.API={get:async function(){return {};}};
      await aresRevalidateActiveAllocation();  // alter Ablauf: nur neu pruefen
      return {log:LOG};
    """)
    assert "wealth:C1" not in out["log"] and "reset" not in out["log"], out


def test_e2e3_07_wealth_refresh_reloads_derived_cashflow_rows():
    out = _amount_run("""
      await refreshWealthUI('C1');
      var afterWealth=LOG.slice();
      LOG.length=0;
      await refreshWealthUI('ANDERER');  // anderer Kunde: Cashflow-Seite des aktiven Kunden bleibt
      return {afterWealth:afterWealth, other:LOG.slice()};
    """)
    assert out["afterWealth"][:2] == ["wealth:C1", "cashflows:C1"], out
    assert "cashflows:ANDERER" not in out["other"] and "cashflows:C1" not in out["other"], out


# ---------------------------------------------------------------- E2E3-06 / N-917R2-06 Ursache
COARSE = ("Die gespeicherte Soll-Allokation ist veraltet: Vermoegen, Cashflows oder Ziele haben sich seit "
          "der Berechnung geaendert.")


def _status_cause_script(causes: list[dict], status: str = "STALE") -> str:
    return f"""
      var err=new Error('API 409');err.status=409;err.detail={json.dumps(COARSE)};
      globalThis.API={{get:async function(url){{if(/payload$/.test(url))throw err;
        return {{publication_status:'PUBLICATION_INVALID',freshness:{{status:{json.dumps(status)},causes:{json.dumps(causes)}}}}};}}}};
      globalThis.PAYLOAD_ERR=err;
      try{{await loadCurrentAllocationResult('B');}}catch(e){{}}
      await new Promise(function(r){{setTimeout(r,0);}});
      var first=aresStaleCause();
      // spaeterer 409-Text (z. B. erneuter Payload-Abruf / Statuszeile) ueberschreibt die Statusursache nicht --
      // auch wenn die Status-API dann gerade nicht antwortet (Vorrang, keine erneute Abfrage noetig).
      var keep=API.get;API.get=async function(url){{if(/allocation-publication$/.test(url))throw new Error('offline');return keep(url);}};
      updateStrategyStatus({json.dumps(COARSE)},true);
      try{{await loadCurrentAllocationResult('B');}}catch(e){{}}
      await new Promise(function(r){{setTimeout(r,0);}});
      renderAllocationPublication();renderReviewHero(currentReviewState);
      return {{first:first, later:aresStaleCause(), chip:EL['aa-publication-status'].textContent, hero:EL['rv-hero'].innerHTML,
        status:STATUS[STATUS.length-1][0]}};
    """


def test_e2e3_06_birthdate_cause_comes_from_freshness_causes():
    out = _run(_status_cause_script([{"kind": "client", "text": "Stammdaten des Kunden geändert", "currencies": []},
                                     {"kind": "inputs", "text": "Vermögen, Cashflows oder Ziele geändert", "currencies": []}]))
    cause = "Stammdaten des Kunden geändert; Vermögen, Cashflows oder Ziele geändert"
    assert out["first"] == out["later"] == cause, out
    assert out["chip"] == "Veraltet · " + cause and cause in out["hero"] and cause in out["status"], out


def test_n917r2_06_mortgage_rate_prefers_status_api_over_409_text():
    out = _run(_status_cause_script([{"kind": "positions", "text": "Vermögen geändert", "currencies": []}]))
    assert out["first"] == out["later"] == "Vermögen geändert", out


def test_n917r2_06_counterproof_without_status_answer_409_text_remains():
    out = _run(_status_cause_script([], status="FRESH").replace("publication_status:'PUBLICATION_INVALID'", "publication_status:'PUBLISHED'"))
    assert out["first"] == out["later"] == "Vermögen, Cashflows oder Ziele seit der Berechnung geändert", out


def test_e2e3_05_client_save_asks_server_instead_of_marking_stale():
    html = read_monolith_bundle()
    save = html[html.index("async function saveClientData("):html.index("function openStammdatenModal(")]
    live = save[save.index("await API.put('/clients/'+cid,payload);"):save.index("} else {", save.index("await API.put('/clients/'+cid,payload);"))]
    assert "markStrategyDirty('Anlagehorizont angepasst" not in live, "lokale Heuristik widerspricht dem Serverstatus"
    assert "aresRevalidateActiveAllocation()" in live
    # Server FRESH (Payload 200): keine Ursache, kein Banner, Publikation bleibt.
    out = _run("""
      strategyState.allocation={buckets:[1],target_allocation:{id:'ta'}};strategyState.dirty=false;strategyState.staleNotice=null;
      allocationPublicationState={publication_status:'PUBLISHED',freshness:{status:'FRESH',causes:[]}};
      globalThis.API={get:async function(url){return /payload$/.test(url)?{target_allocation:{id:'ta'}}:allocationPublicationState;}};
      await aresRevalidateActiveAllocation();
      renderAllocationPublication();
      return {cause:aresStaleCause(), notice:strategyState.staleNotice, chip:EL['aa-publication-status'].textContent, inv:INVALIDATED};
    """)
    assert out == {"cause": "", "notice": None, "chip": "Publiziert", "inv": 0}, out


# ---------------------------------------------------------------- E2E3-14 kein "veraltet" ohne Strategie
def test_e2e3_14_no_stale_banner_when_server_has_no_allocation():
    out = _run("""
      var nf=new Error('API 404');nf.status=404;
      globalThis.PAYLOAD_ERR=nf;
      try{await loadCurrentAllocationResult('B');}catch(e){}
      strategyState.allocation=null;
      markStrategyDirty('Risikoprofil gespeichert: Strategie neu berechnen.',true);
      var none=strategyState.staleNotice;
      // Gegenprobe: mit gespeicherter (veralteter) Allokation bleibt der Hinweis.
      globalThis.PAYLOAD_ERR=null;await loadCurrentAllocationResult('B');strategyState.allocation=null;
      markStrategyDirty('Risikoprofil gespeichert: Strategie neu berechnen.',true);
      return [none, strategyState.staleNotice, strategyState.dirty];
    """)
    assert out == [None, "Risikoprofil gespeichert: Strategie neu berechnen.", True], out


# ---------------------------------------------------------------- N-917R2-03 Banner im Reset
def test_n917r2_03_reset_clears_message_banner_dom():
    out = _run("""
      var calls=[];
      globalThis.renderAllocationMessageBanner=function(r){calls.push(['al',r]);};
      globalThis.renderReviewMessageBanner=function(r){calls.push(['rv',r]);};
      var dep=mk('aa-proj-depletion');dep.innerHTML='100 % (ab 2042)';var cdep=mk('aa-proj-current-depletion');cdep.innerHTML='98 % (ab 2043)';
      aresResetMandateView();
      return {calls:calls, dep:[dep.innerHTML,cdep.innerHTML]};
    """)
    # Beide Banner werden im Reset mit "keine Meldung" gezeichnet (die Renderer leeren dabei den Text,
    # siehe test_n917r2_03_banner_renderers_clear_text_when_hidden); Verzehr-Kennzahlen leer.
    assert out["calls"] == [["al", None], ["rv", None]], out
    assert out["dep"] == ["", ""], out


def test_n917r2_03_banner_renderers_clear_text_when_hidden():
    out = run_js(("renderAllocationMessageBanner", "renderReviewMessageBanner", "allocationMessages",
                  "firstVisibleAllocationMessage", "messageActionLabel"), """
      var kids={};function el(id){var e=document.getElementById(id);return e;}
      ['al-message-banner','rv-message-banner'].forEach(function(id){var b=el(id);b.querySelectorAll=function(sel){
        return sel.split(',').map(function(s){var k=id+s;if(!kids[k]){kids[k]=__mkEl(k);kids[k].textContent='Zielname alt';}return kids[k];});};
        b.querySelector=function(s){return b.querySelectorAll(s)[0];};});
      document.getElementById('al-message-banner').querySelectorAll('.al-banner-title,.al-banner-body,.al-banner-actions');
      document.getElementById('rv-message-banner').querySelectorAll('.rv-message-title,.rv-message-body');
      renderAllocationMessageBanner(null);renderReviewMessageBanner({messages:[]});
      return Object.keys(kids).map(function(k){return kids[k].textContent;});
    """)
    assert out and all(t == "" for t in out), out


# ---------------------------------------------------------------- NIEDRIG: E2E3-10 / E2E3-13 / E2E3-12 / E2E3-08
def test_e2e3_10_empty_projection_resets_previous_axis():
    out = run_js(("syncAaProjectionAxisScales", "projectionChartValues"), """
      syncAaProjectionAxisScales();
      var empty=[charts.opt.options.scales.y.min,charts.opt.options.scales.y.max,charts.aaCurrent.options.scales.y.max];
      // Gegenprobe: mit Werten wird die gemeinsame Skala gesetzt.
      charts.opt.data.datasets[0].data=[200,900];syncAaProjectionAxisScales();
      return {empty:empty, filled:[charts.opt.options.scales.y.min,charts.aaCurrent.options.scales.y.max]};
    """, prelude="""
      function mkChart(){return {data:{labels:['2026'],datasets:[{data:[]}]},options:{scales:{y:{type:'linear',min:100,max:5700}}},update:function(){}};}
      var charts={opt:mkChart(),aaCurrent:mkChart()};
      function chartUpdateSettled(){}
      function arrMin(a){return Math.min.apply(null,a);} function arrMax(a){return Math.max.apply(null,a);}
      function _projAxisConfig(a,b){return {type:'linear',min:a,max:b};}
    """)
    assert out["empty"] == [None, None, None], out  # JSON: undefined -> null
    assert out["filled"] == [200, 900], out


def test_e2e3_13_amortization_shows_end_instead_of_unbefristet():
    out = run_js(("derivedAmortizationEndLabel", "cashflowTimingLabel", "normalizeCashflowDateValue", "isOneOffCashflow",
                  "cashflowDisplayFrequency", "cashflowCapitalMetaLabel", "cashflowFrequencyKey", "normalizeFrequencyValue"), """
      currentMandateData={retirement_year:2045};
      function cf(pid){return {id:'derived:mortgage_amortization:'+pid,origin_position_id:pid,frequency:'jaehrlich'};}
      var a=cashflowTimingLabel(cf('h1')), b=cashflowTimingLabel(cf('h2'));
      currentMandateData={};var c=cashflowTimingLabel(cf('h1'));
      var other=cashflowTimingLabel({id:'derived:mortgage_interest:h1',frequency:'jaehrlich'});
      return [a,b,c,other];
    """, optional=("formatDateSwiss",), prelude="""
      var currentWealthPositions=[{id:'h1',mortgage_amortization_type:'Indirekt (Säule 3a)'},{id:'h2',mortgage_amortization_type:'Direkt'}];
      var currentMandateData={};
    """)
    assert "bis und mit Pensionierungsjahr 2045" in out[0] and "unbefristet" not in out[0], out
    assert "bis die Hypothek getilgt ist" in out[1], out
    assert "bis Ende des Planungshorizonts" in out[2], out
    assert "unbefristet" in out[3], out  # Hypothekarzins laeuft weiter (keine Aenderung)


def test_e2e3_12_and_e2e3_08_static_contracts():
    html = read_monolith_bundle()
    kn3 = (FRONTEND_DIR / "kn3-ui.js").read_text(encoding="utf-8")
    hook = kn3[kn3.index("function hookSidebarSearch()"):kn3.index("// ------------------------------------------------------------ KYC-Formular")]
    assert "wrap('createNewMandate'" in hook and "el.dataset.search" in hook and "el.dataset.letter" in hook and "'sb-prompt'" in hook
    assert "automatisch 60% Aktien" not in html and "alle Felder auf 0 lassen" not in html
    assert "replace(/^Value error,\\s*/, '')" in html
    assert "wrap('pensionTransferGuardMessage'" in kn3 and "wrap('createKycConfirmation'" in kn3


def test_ci_runs_kn3u_livetest_in_its_own_job():
    workflow = (Path(__file__).resolve().parents[2] / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    assert "test_livetest_kn3_u_ui.py" in workflow
    job = workflow[workflow.index("kn3u-livetest:"):]
    job = job[:job.index("\n  vitest:")] if "\n  vitest:" in job else job
    assert "test_livetest_kn3_u_ui.py" in job and "ARES_REQUIRE_PLAYWRIGHT" in job
