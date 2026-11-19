"""KN-U (Dok. 117, Classic-Berateroberflaeche): reine Logik von
``mandate-view.js`` (und den mitgeaenderten Teilen) in Node gegen ein minimales DOM.

* E2E2-01: Mandatswechsel bzw. fehlende Allokation setzt alle mandatsbezogenen
  Kacheln, HUDs, offenen Dialoge und Zwischenstaende zurueck.
* E2E2-05: veraltete Soll-Allokation -- dieselbe konkrete Ursache aus dem 409-Text
  bzw. aus kuenftigen Statusfeldern; Publikations-Chip nie "Publiziert".
* E2E2-07 / N-917-03 / N-917-08 / N-917-09: "Umrechnung offen" mit Ursache als
  Unit-Test (nicht nur Playwright); Beratungsvermoegen, wenn belegt.
* E2E-12: Review-Kachel ohne negative Vermoegenswerte.
* E2E2-08: Ist-Projektion nennt den typisierten Grund des Servers.
* E2E2-14/15: Fachbegriffe; Kursquelle "manuell".
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[2] / "ares-desktop" / "frontend"
MODULE = FRONTEND / "mandate-view.js"

DOM = r"""
var window=globalThis;
function El(id){var cls={};this.id=id;this.textContent='';this.innerHTML='';this.title='';this.style={};this.dataset={};this.attrs={};
  this.previousElementSibling=null;this._card=null;this._q={};
  this.classList={add:function(c){cls[c]=1;},remove:function(c){delete cls[c];},contains:function(c){return !!cls[c];},
    toggle:function(c,on){if(on===undefined)on=!cls[c];if(on)cls[c]=1;else delete cls[c];}};}
El.prototype.removeAttribute=function(k){delete this.attrs[k];};
El.prototype.setAttribute=function(k,v){this.attrs[k]=String(v);};
El.prototype.getAttribute=function(k){return this.attrs[k]==null?null:this.attrs[k];};
El.prototype.closest=function(){return this._card;};
El.prototype.querySelector=function(s){return this._q[s]||null;};
var EL={},OVERLAYS=[],KV=[],KS=[];
function mk(id){var e=new El(id);EL[id]=e;return e;}
function overlay(id,open){var e=mk(id);if(open)e.classList.add('open');OVERLAYS.push(e);return e;}
var document={readyState:'complete',addEventListener:function(){},head:null,
  body:{classList:new El('body').classList,style:{setProperty:function(){}}},
  getElementById:function(id){return EL[id]||null;},
  querySelectorAll:function(s){
    if(s==='.overlay.open')return OVERLAYS.filter(function(o){return o.classList.contains('open');});
    if(s==='.kpir .kv')return KV; if(s==='.kpir .ks')return KS; return [];}};
globalThis.document=document;
var CALLS=[];
globalThis.cm=function(id){var e=EL[id];if(e)e.classList.remove('open');CALLS.push('cm:'+id);};
globalThis.escapeHtml=function(s){return String(s).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});};
globalThis.fmtNumber=function(n){return String(Math.round(n));};
globalThis.formatRappen=function(r,c){return c?c+' '+String(Math.round(Number(r)/100)):'—';};
globalThis.formatCompactCHF=function(v,c){return (c||'CHF')+' '+String(Math.round(v));};
globalThis.positionsCurrency=function(list){var seen={};(list||[]).forEach(function(p){seen[String(p&&p.currency||'?').toUpperCase()]=1;});var k=Object.keys(seen);return k.length===1&&k[0]!=='?'?k[0]:null;};
globalThis.MANDATE={id:'B',base_currency:'CHF'};
globalThis.getActiveMandateId=function(){return MANDATE.id;};
globalThis.mandateCurrency=function(){return MANDATE.base_currency;};
globalThis.isDemoMandateId=function(){return false;};
globalThis.RISK={};
globalThis.currentPersistedRiskForMandate=function(mid){return RISK[mid]||null;};
globalThis.currentRiskAssessmentForOverride=function(){return null;};
globalThis.POS=[];
globalThis.activeClientWealthPositions=function(){return POS;};
globalThis.MIX=null;
globalThis.wealthMixedTotals=function(items){return MIX?JSON.parse(JSON.stringify(MIX)):null;};
globalThis.currentAllocationInputSnapshot=function(){return SNAP;};
globalThis.SNAP={advisoryRappen:0,totalNetRappen:0,fxOpen:false,wealthCurrency:'CHF'};
globalThis.setGoalSuccessTile=function(s){var e=EL['sr-goal-score'];if(e)e.textContent=s?'x':'—';};
globalThis.strategyState={allocation:null,recommendation:null,dirty:true,staleNotice:null};
globalThis.currentReviewState={logs:[{id:'alt'}],allocation:{x:1}};
globalThis.allocationPublicationState=null;globalThis.allocationPublicationKey='';
globalThis.currentWealthPositions=[{id:'alt'}];globalThis.currentWealthSummary={client_id:'A'};
globalThis.STATUS=[];
globalThis.updateStrategyStatus=function(m,e){STATUS.push([m,!!e]);};
globalThis.STRATEGY_STALE_DEFAULT_NOTICE='Eingaben haben sich seit der letzten Berechnung geändert — bitte «Anlagestrategie berechnen» klicken.';
globalThis.markStrategyDirty=function(m){strategyState.dirty=true;strategyState.staleNotice=m;};
globalThis.hasVisibleStrategyOutputs=function(){return !!(strategyState.allocation&&strategyState.allocation.buckets);};
globalThis.INVALIDATED=0;
globalThis.invalidateStrategyOutputs=function(){INVALIDATED++;strategyState.allocation=null;};
globalThis.syncStrategyStaleView=function(){};
globalThis.allocationPublicationTaId=function(){var a=strategyState.allocation;return a&&a.target_allocation?a.target_allocation.id:'';};
globalThis.renderAllocationPublication=function(){var chip=EL['aa-publication-status'];var s=allocationPublicationState;
  if(chip){if(!s){chip.textContent='';chip.style.display='none';}else{chip.textContent=s.publication_status==='PUBLISHED'?'Publiziert':'Entwurf';chip.style.display='';}}};
globalThis.applyPortfolioUmsetzenVisibility=function(){var b=EL['btn-portfolio-umsetzen'];if(b)b.style.display=allocationPublicationState&&allocationPublicationState.publication_status==='PUBLISHED'?'':'none';};
globalThis.monteCarloPayload=function(r){return r&&r.monte_carlo||null;};
globalThis.simulationPayload=function(r){return r&&r.simulation||null;};
globalThis.strategyMedianProjectionRappen=function(r){var s=r&&r.monte_carlo&&r.monte_carlo.target_p50_series_rappen||[];return s.length?s[s.length-1]:0;};
globalThis.projectionHorizonYearLabel=function(sim){var l=sim&&sim.year_labels||[];return l.length?'Ende '+(Number(l[l.length-1])-1):'';};
globalThis.renderStrategySummary=function(){var a=strategyState.allocation;if(!a)return;EL['sr-risk-score'].textContent='9 / 10';
  EL['sr-proj-wealth'].textContent='CHF '+String(strategyMedianProjectionRappen(a)/100);};
globalThis.renderSrApiSummary=function(){};globalThis.renderSrImplementationDecision=function(){};
globalThis.renderReviewHero=function(){var h=EL['rv-hero'];if(h)h.innerHTML='<div>Normal</div>';};
globalThis.loadCurrentAllocationResult=async function(mid){if(globalThis.PAYLOAD_ERR)throw PAYLOAD_ERR;return {target_allocation:{id:'ta'}};};
globalThis.finalizeStrategyOutputs=function(){};
globalThis.saveFxQuickEditor=async function(){return true;};globalThis.saveAdminFxRates=async function(){};
globalThis.openFxQuickEditor=async function(){return true;};
globalThis.refreshAllocationPublication=function(){};
globalThis.renderWealthPositions=function(){};
globalThis.go=async function(){};
"""

IDS = ["sr-risk-score", "sr-risk-profile", "sr-ovr-badge", "sr-wealth", "sr-wealth-share", "sr-goal-score", "sr-goal-sub",
       "kpi-goal-score", "kpi-goal-sub", "sr-proj-sub", "sr-strategy-name", "sr-horizon", "sr-allocation-bars",
       "sr-goal-priority-list", "cf-projection", "rv-hero", "aa-publication-status", "btn-aa-publish",
       "btn-portfolio-umsetzen", "sr-implementation-steps", "sr-decision-meta", "po-status", "kpi-beratungsvermoegen"]


def _run(script: str, extra_sources: tuple[Path, ...] = ()):
    if shutil.which("node") is None:
        pytest.skip("node binary not available")
    setup = "".join(f"mk('{i}');" for i in IDS)
    setup += "var _pl=mk('sr-proj-label');var _pv=mk('sr-proj-wealth');_pv.previousElementSibling=_pl;"
    setup += "var _kc=new El('kpi-card');_kc._q['.ks']=mk('kpi-sub');EL['kpi-beratungsvermoegen']._card=_kc;"
    code = DOM + setup + "".join(p.read_text(encoding="utf-8") + "\n" for p in extra_sources)
    code += MODULE.read_text(encoding="utf-8")
    code += "\n(async function(){var out=await (async function(){" + script + "})();console.log(JSON.stringify(out));})();"
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
        fh.write(code)
        path = fh.name
    out = subprocess.run(["node", path], capture_output=True, text=True, encoding="utf-8", timeout=60)
    Path(path).unlink(missing_ok=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


# ---------------------------------------------------------------- E2E2-01
def test_mandate_switch_resets_tiles_hud_dialogs_and_caches():
    out = _run("""
      // Zustand von Kunde A (mit Strategie) steht noch im DOM.
      EL['sr-risk-score'].textContent='2 / 10';EL['sr-risk-profile'].textContent='Kapitalschutz';
      EL['sr-wealth'].textContent='CHF 450000';EL['sr-goal-score'].textContent='22 %';
      EL['sr-proj-wealth'].textContent='CHF -803336';EL['sr-strategy-name'].textContent='Kapitalschutz';
      EL['cf-projection'].innerHTML='Einnahmen CHF 150000';EL['cf-projection'].style.display='';
      EL['aa-publication-status'].textContent='Publiziert';allocationPublicationState={publication_status:'PUBLISHED'};
      var tl=overlay('m-tl',true), dlg=overlay('m-ui-dialog',true), nc=overlay('m-nc',true);
      MANDATE.id='C'; // neues Mandat ohne Risikoprofil und ohne Strategie
      aresResetMandateView();
      return {risk:EL['sr-risk-score'].textContent, profile:EL['sr-risk-profile'].textContent, wealth:EL['sr-wealth'].textContent,
        goal:EL['sr-goal-score'].textContent, proj:EL['sr-proj-wealth'].textContent, strat:EL['sr-strategy-name'].textContent,
        hud:EL['cf-projection'].style.display, hudHtml:EL['cf-projection'].innerHTML, chip:EL['aa-publication-status'].style.display,
        tl:tl.classList.contains('open'), dlg:dlg.classList.contains('open'), nc:nc.classList.contains('open'),
        review:currentReviewState.logs.length, pub:allocationPublicationState, pos:currentWealthPositions.length, ws:currentWealthSummary};
    """)
    assert out["risk"] == "—" and out["profile"] == "Risikoprofil noch nicht erfasst", out
    assert out["wealth"] == "—" and out["goal"] == "—" and out["proj"] == "—" and out["strat"] == "Nicht definiert", out
    assert out["hud"] == "none" and out["hudHtml"] == "" and out["chip"] == "none", out
    assert out["tl"] is False, "Handelsliste des vorigen Kunden bleibt offen"
    assert out["dlg"] is True and out["nc"] is True, "System-/Wechseldialoge duerfen nicht geschlossen werden"
    assert out["review"] == 0 and out["pub"] is None and out["pos"] == 0 and out["ws"] is None, out


def test_summary_without_allocation_shows_active_mandate_risk_not_previous_client():
    out = _run("""
      EL['sr-risk-score'].textContent='2 / 10';EL['sr-risk-profile'].textContent='Kapitalschutz';
      RISK['B']={final_score_x10:90,final_profile:'Dynamisch',investment_horizon_years:15};
      strategyState.allocation=null;
      renderStrategySummary();
      var a={risk:EL['sr-risk-score'].textContent,profile:EL['sr-risk-profile'].textContent,horizon:EL['sr-horizon'].textContent};
      // Gegenprobe: mit Allokation zeichnet die Originalfunktion.
      strategyState.allocation={buckets:[1],monte_carlo:{target_p50_series_rappen:[100,200]}};
      renderStrategySummary();
      a.withAlloc=EL['sr-risk-score'].textContent;
      return a;
    """)
    assert out == {"risk": "9 / 10", "profile": "Dynamisch", "horizon": "15 Jahre", "withAlloc": "9 / 10"}, out


# ---------------------------------------------------------------- E2E2-05
MSG_409 = ("Die gespeicherte Soll-Allokation ist veraltet: Wechselkurs USD seit der Berechnung geaendert. "
           "Bitte Strategie neu berechnen; alte Targets werden nicht mit einer aktuellen Analyse kombiniert.")


def test_stale_cause_from_server_text_and_future_status_fields():
    out = _run(f"""
      return [aresStaleCauseFromText({json.dumps(MSG_409)}),
        aresStaleCauseFromText('Die gespeicherte Soll-Allokation ist veraltet: Wechselkurs USD, GBP seit der Berechnung geaendert.'),
        aresStaleCauseFromText('Die gespeicherte Soll-Allokation ist veraltet: Vermoegen, Cashflows oder Ziele haben sich seit der Berechnung geaendert.'),
        aresStaleCauseFromText('Bitte zuerst ein aktuelles Risikoprofil speichern.'),
        aresStaleCauseFromStatus({{publication_status:'PUBLISHED',stale:true,stale_reason_code:'FX_RATE_CHANGED',stale_reason:'Wechselkurs USD seit der Berechnung geaendert'}}),
        aresStaleCauseFromStatus({{publication_status:'STALE',stale_currencies:['usd']}}),
        aresStaleCauseFromStatus({{publication_status:'PUBLISHED',blocker_codes:[]}})];
    """)
    assert out[0] == out[4] == out[5] == "Wechselkurs USD seit der Berechnung geändert", out
    assert out[1] == "Wechselkurs USD, GBP seit der Berechnung geändert", out
    assert out[2] == "Vermögen, Cashflows oder Ziele seit der Berechnung geändert", out
    assert out[3] == "" and out[6] == "", out


def test_fx_change_without_reload_marks_publication_stale_everywhere():
    out = _run(f"""
      strategyState.allocation={{buckets:[1],target_allocation:{{id:'ta'}}}};strategyState.dirty=false;
      allocationPublicationState={{publication_status:'PUBLISHED',target_allocation_id:'ta'}};
      renderAllocationPublication();applyPortfolioUmsetzenVisibility();
      var before=EL['aa-publication-status'].textContent;
      // Server antwortet nach der Kursaenderung mit 409 (heutiges Signal).
      var err=new Error('API 409');err.status=409;err.detail={json.dumps(MSG_409)};
      globalThis.API={{get:async function(){{throw err;}}}};
      await saveAdminFxRates();
      return {{before:before, chip:EL['aa-publication-status'].textContent, invalidated:INVALIDATED,
        notice:strategyState.staleNotice, status:STATUS[STATUS.length-1], umsetzen:EL['btn-portfolio-umsetzen'].style.display,
        hero:EL['rv-hero'].innerHTML.indexOf('Wechselkurs USD seit der Berechnung geändert')>=0}};
    """)
    cause = "Wechselkurs USD seit der Berechnung geändert"
    assert out["before"] == "Publiziert", out
    assert out["chip"] == "Veraltet · " + cause, out
    assert out["invalidated"] == 1, "alte Zahlen bleiben sichtbar"
    assert out["notice"].startswith(cause) and out["status"] == [f"Soll-Allokation veraltet: {cause}. Bitte «Anlagestrategie berechnen» ausführen.", True], out
    assert out["umsetzen"] == "none" and out["hero"] is True, out


def test_future_status_field_alone_marks_stale_and_generic_texts_name_the_cause():
    out = _run("""
      strategyState.allocation={buckets:[1],target_allocation:{id:'ta'}};
      allocationPublicationState={publication_status:'PUBLISHED',stale:true,stale_reason:'Wechselkurs USD seit der Berechnung geaendert'};
      renderAllocationPublication();
      var chip=EL['aa-publication-status'].textContent;
      markStrategyDirty(STRATEGY_STALE_DEFAULT_NOTICE,false);
      var notice=strategyState.staleNotice;
      updateStrategyStatus('Strategie kann nicht hydratisiert werden — Eingaben unvollständig.',false);
      var st=STATUS[STATUS.length-1][0];
      MANDATE.id='A'; // anderes Mandat: keine Ursache von B
      return {chip:chip, notice:notice, st:st, other:aresStaleCause()};
    """)
    assert out["chip"] == "Veraltet · Wechselkurs USD seit der Berechnung geändert", out
    assert out["notice"].startswith("Wechselkurs USD seit der Berechnung geändert"), out
    assert "Wechselkurs USD" in out["st"] and "hydratisiert" not in out["st"], out
    assert out["other"] == "", out


def test_payload_409_on_load_sets_cause_and_fresh_load_clears_it():
    out = _run(f"""
      var err=new Error('API 409');err.status=409;err.detail={json.dumps(MSG_409)};
      globalThis.PAYLOAD_ERR=err;
      try{{await loadCurrentAllocationResult('B');}}catch(e){{}}
      var c1=aresStaleCause();
      globalThis.PAYLOAD_ERR=null;
      await loadCurrentAllocationResult('B');
      return [c1, aresStaleCause()];
    """)
    assert out == ["Wechselkurs USD seit der Berechnung geändert", ""], out


# ---------------------------------------------------------------- Umrechnung offen (E2E2-07, N-917-03/-08/-09)
def test_umrechnung_offen_texts_never_zero_or_dash():
    out = _run("""
      MIX={blocked:true,currencies:['CHF','USD'],error:{reason_code:'CCX_FX_BASIS_MISSING',currencies:['USD']}};
      POS=[{assignment:'Beratungsvermögen',currency:'USD',current_value_rappen:10000000},{assignment:'Beratungsvermögen',currency:'CHF',current_value_rappen:40000000}];
      var fmt=function(r,c){return c+' '+r;};
      return {
        aaAdv:aresSnapshotAmount({fxOpen:true,advisoryRappen:0},'advisory'),
        aaNet:aresSnapshotAmount({fxOpen:true,totalNetRappen:0},'net'),
        aaEmpty:aresSnapshotAmount({fxOpen:false,advisoryRappen:0},'advisory'),
        grpMixed:aresCcySum(fmt,500,[{currency:'CHF'},{currency:'USD'}],'+'),
        grpOne:aresCcySum(fmt,500,[{currency:'CHF'},{currency:'CHF'}],'−'),
        totalMixed:aresBlockedTotal(MIX,POS),
        totalEmpty:aresBlockedTotal(MIX,[]),
        totalOtherChf:aresBlockedTotal(MIX,[{assignment:'Anderes Vermögen',currency:'CHF',current_value_rappen:500},{assignment:'Verbindlichkeit',currency:'CHF',current_value_rappen:200}])};
    """)
    open_text = "Umrechnung offen – Kurs USD fehlt oder nur Ersatzkurs"
    assert out["aaAdv"] == open_text and out["aaNet"] == open_text, out
    assert out["aaEmpty"] == "Noch kein Beratungsvermögen erfasst", out
    assert out["grpMixed"] == "Umrechnung offen" and out["grpOne"] == "−CHF 500", out
    assert out["totalMixed"] == "Umrechnung offen", out
    assert out["totalEmpty"] == "nicht erfasst", "kein anderes Vermoegen erfasst: weder 'Umrechnung offen' noch ein Nullbetrag"
    assert out["totalOtherChf"] == "CHF 3", out


def test_advisory_wealth_shown_when_its_currencies_are_covered():
    out = _run("""
      // EUR liegt nur im anderen Vermoegen ohne Kurs; Beratung nur in CHF.
      MIX={blocked:true,currencies:['CHF','EUR'],error:{reason_code:'CCX_FX_BASIS_MISSING',currencies:['EUR']}};
      POS=[{assignment:'Beratungsvermögen',currency:'CHF',current_value_rappen:48800000},{assignment:'Anderes Vermögen',currency:'EUR',current_value_rappen:5000000}];
      var mix=wealthMixedTotals(POS);
      var adv=aresSnapshotAmount({fxOpen:true},'advisory');
      renderWealthPositions(POS);
      var kpi=EL['kpi-beratungsvermoegen'].textContent, sub=EL['kpi-sub'].textContent;
      SNAP={fxOpen:true,advisoryRappen:48800000,totalNetRappen:0};
      clearStrategySummaryForDirtyState();
      var tile=EL['sr-wealth'].textContent, share=EL['sr-wealth-share'].textContent;
      // Gegenprobe: Beratung enthaelt USD ohne Kurs -> offen.
      POS=[{assignment:'Beratungsvermögen',currency:'USD',current_value_rappen:1}];
      MIX={blocked:true,currencies:['CHF','USD'],error:{reason_code:'CCX_FX_BASIS_MISSING',currencies:['USD']}};
      var openAdv=aresSnapshotAmount({fxOpen:true},'advisory');
      // Kuenftiges Serverfeld hat Vorrang (Annahme KN-B/N-917-03).
      var srv=aresAdvisoryWhenBlocked(POS,{srvAdvisoryRappen:12300,blocked:true});
      return {known:mix.advisoryKnown, rappen:mix.advisoryRappen, adv:adv, kpi:kpi, sub:sub, tile:tile, share:share, openAdv:openAdv, srv:srv};
    """)
    assert out["known"] is True and out["rappen"] == 48800000, out
    assert out["adv"] == "CHF 488000" and out["kpi"] == "CHF 488000" and out["tile"] == "CHF 488000", out
    assert "Gesamtvermögen offen" in out["sub"] and "EUR" in out["sub"], out
    assert out["share"].startswith("Kein Anteil: Umrechnung offen – Kurs EUR"), out
    assert out["openAdv"] == "Umrechnung offen – Kurs USD fehlt oder nur Ersatzkurs", out
    assert out["srv"] == {"rappen": 12300, "currency": "CHF"}, out


def test_wealth_block_text_unit_without_playwright():
    """N-917-09: Entfernt man wealthBlockText (M8), wird dieser Test rot."""
    if shutil.which("node") is None:
        pytest.skip("node binary not available")
    harness = ("var document={readyState:'complete',addEventListener:function(){},getElementById:function(){return null;},"
               "querySelector:function(){return null;},querySelectorAll:function(){return [];}};var window={};")
    code = harness + (FRONTEND / "advisor-guidance.js").read_text(encoding="utf-8") + (
        "\nconsole.log(JSON.stringify([window.wealthBlockText({amount_block_reason_code:'CCX_FX_BASIS_MISSING',amount_block_currencies:['usd']}),"
        "window.wealthBlockText({amount_block_reason_code:'CCX_FX_BASIS_STALE',amount_block_currencies:[]}),"
        "window.wealthBlockText({amount_currency:'CHF'})]));")
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
        fh.write(code)
        path = fh.name
    out = subprocess.run(["node", path], capture_output=True, text=True, encoding="utf-8", timeout=60)
    Path(path).unlink(missing_ok=True)
    assert out.returncode == 0, out.stderr
    res = json.loads(out.stdout.strip().splitlines()[-1])
    assert res == ["Umrechnung offen – Kurs USD fehlt oder nur Ersatzkurs.", "Umrechnung offen – Kurs abgelaufen.", ""], res


# ---------------------------------------------------------------- E2E-12 / E2E2-15
def test_review_tile_shows_depletion_instead_of_negative_wealth():
    out = _run("""
      strategyState.allocation={buckets:[1],monte_carlo:{target_p50_series_rappen:[45000000,1000,-500,-80333600],year_labels:[2026,2044,2045,2055]},
        simulation:{year_labels:[2026,2044,2045,2055]}};
      renderStrategySummary();
      var a={v:EL['sr-proj-wealth'].textContent,l:EL['sr-proj-label'].textContent,s:EL['sr-proj-sub'].textContent};
      strategyState.allocation.monte_carlo.target_p50_series_rappen=[0,-1,-2,-3];
      renderStrategySummary();
      a.v0=EL['sr-proj-wealth'].textContent;a.s0=EL['sr-proj-sub'].textContent;
      strategyState.allocation.monte_carlo.target_p50_series_rappen=[1,2,3,400];
      renderStrategySummary();
      a.pos=EL['sr-proj-wealth'].textContent;
      return a;
    """)
    assert out["v"] == "Aufgebraucht ab 2045" and out["l"] == "Prognose Ende 2054", out
    assert out["s"] == "Vermögen aufgebraucht ab 2045 (mittlerer Verlauf)", out
    assert out["v0"] == "Finanzierungslücke" and out["s0"] == "Finanzierungslücke ab 2044 (mittlerer Verlauf)", out
    assert "−" not in out["v"] + out["v0"] and "-" not in out["v"] + out["v0"], out
    assert out["pos"] == "CHF 4", "positiver Verlauf unveraendert"


def test_review_without_strategy_claims_no_band_status():
    out = _run("""
      EL['sr-implementation-steps'].innerHTML='Alle Anlageklassen im Band';
      EL['sr-decision-meta'].textContent='Empfehlung vom —';
      strategyState.allocation=null;
      renderSrImplementationDecision();
      return {steps:EL['sr-implementation-steps'].innerHTML, meta:EL['sr-decision-meta'].textContent};
    """)
    assert "im Band" not in out["steps"] and "Noch keine Soll-Allokation" in out["steps"], out
    assert out["meta"] == "Noch keine Empfehlung erfasst", out


# ---------------------------------------------------------------- E2E2-14 / E2E2-15 / E2E2-08
def test_display_terms_and_fx_source_label():
    out = _run("return [aresTerm('Obligationen Global Hedged'),aresTerm('Obligationen Welt IG (CHF gehedgt)'),"
               "aresTerm('Aktien Schwellenlaender'),aresTerm('Thema Gluecksspiel'),fxSourceText('Manual'),fxSourceText('SNB')];",
               extra_sources=(FRONTEND / "fx-rates-editor.js",))
    assert out == ["Obligationen Global währungsgesichert", "Obligationen Welt Investment Grade (währungsgesichert in CHF)",
                   "Aktien Schwellenländer", "Thema Glücksspiel", "manuell", "SNB"], out


def test_ist_projection_names_typed_server_reason():
    if shutil.which("node") is None:
        pytest.skip("node binary not available")
    detail = {"reason_code": "MORTGAGE_INTEREST_RATE_MISSING",
              "message": "Für die Hypothek Hypothek C ist kein Zinssatz erfasst."}
    harness = (
        "var window=globalThis;var document={getElementById:function(){return null;}};"
        "globalThis.getActiveMandateId=function(){return 'M1';};globalThis.isDemoMandateId=function(){return false;};"
        "globalThis.activeClientWealthPositions=function(){return [];};globalThis.activeClientCashflowSummary=function(){return null;};"
        "globalThis.projectionHorizonYears=function(){return 10;};globalThis.renderCurrentWealthOnlyProjectionSummary=function(){};"
        "globalThis.API={get:async function(){var e=new Error('409');e.status=409;e.body=" + json.dumps(json.dumps({"detail": detail})) + ";throw e;}};"
    )
    code = harness + (FRONTEND / "ist-projection-basis.js").read_text(encoding="utf-8") + (
        "\n(async function(){globalThis.istProjectionRerender=function(){};var r=await ensureIstProjectionBasis();"
        "console.log(JSON.stringify([r,istProjectionBasisState.reason]));})();")
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
        fh.write(code)
        path = fh.name
    out = subprocess.run(["node", path], capture_output=True, text=True, encoding="utf-8", timeout=60)
    Path(path).unlink(missing_ok=True)
    assert out.returncode == 0, out.stderr
    status, reason = json.loads(out.stdout.strip().splitlines()[-1])
    assert status == "unavailable", (status, reason)
    assert reason == "Ist-Projektion nicht verfügbar: " + detail["message"], reason
    assert "Kapitalmarktannahmen" not in reason
