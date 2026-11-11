// H9 (Owner-UX 2026-11-08): Vermoegensentwicklung "heute" (Cashflow-Schritt,
// Grafik #ch-ist) zeigt die verbesserte/optimierte Kurve NUR, wenn fuer das
// Mandat eine gueltige, nicht veraltete Strategie existiert:
//   - berechnete Soll-Allokation mit Simulation (strategyState.allocation),
//   - aktuelles, strategietaugliches Risikoprofil (strategyState.risk),
//   - kein offener Stale-Hinweis (dirty + staleNotice wie das AA-Badge),
//   - H9 Nachtrag N-892-01: der Server bestaetigt beim Oeffnen der Seite und
//     beim Zurueckkehren ins Fenster, dass genau diese Soll-Allokation noch
//     die aktuelle ist (waehrend der Pruefung und bei Fehler: nur IST).
// Ohne Strategie nur die IST-Entwicklung; keine Annahmen erfinden (kein
// Default-Profil, keine pauschale Mehrrendite). Ausgelagerter Monolith-Teil
// (Bundle, Budget, Verbots-Guards); nutzt die globalen Helfer des Monolithen,
// die erst beim Aufruf aufgeloest werden.
var istServerCheck={mid:null,pending:false,invalidId:null,seq:0};
function istProjectionActiveMandate(){
  return (typeof getActiveMandateId==='function')?String(getActiveMandateId()||''):'';
}
function istProjectionAllocationIdentity(a){
  var ta=a&&(a.target_allocation||a);
  if(!ta)return '';
  return String(ta.id||ta.target_allocation_id||'')+'|'+String(ta.set_at||ta.created_at||'');
}
function istProjectionStrategyValid(){
  var s=(typeof strategyState!=='undefined')?strategyState:null;
  var a=s&&s.allocation;
  if(!a||!Array.isArray(a.buckets)||!a.buckets.length)return false;
  var sim=a.simulation;
  if(!sim||!Array.isArray(sim.target_mix_series_rappen)||!sim.target_mix_series_rappen.length)return false;
  if(!s.risk)return false;
  if(s.dirty&&s.staleNotice)return false;
  if(istServerCheck.mid&&istServerCheck.mid===istProjectionActiveMandate()){
    if(istServerCheck.pending)return false;
    if(istServerCheck.invalidId!==null&&istServerCheck.invalidId===istProjectionAllocationIdentity(a))return false;
  }
  return true;
}
function istProjectionHasOverlay(){
  var c=(typeof charts!=='undefined'&&charts)?charts.ist:null;
  return !!(c&&c.data&&Array.isArray(c.data.datasets)&&c.data.datasets.length>1);
}
// Projektionslabels markieren den Stand zu Jahresbeginn; der letzte Punkt ist
// der Stand nach dem letzten Cashflow-Jahr (valid_until inklusiv). Angezeigt
// wird deshalb das letzte Cashflow-Jahr ("Ende 2060" wie "= bis 2060" oben).
function istProjectionEndYearLabel(label){
  var year=parseInt(String(label==null?'':label),10);
  return isFinite(year)?String(year-1):String(label==null?'':label);
}
// H9 Nachtrag N-892-04: die IST-Linie folgt immer dem IST-Horizont
// (Lebensende bzw. letzter Cashflow, Berater-Override vorrangig) -- mit und
// ohne Strategie gleich. Die verbesserte Linie existiert nur, soweit die
// Strategie-Simulation reicht; danach endet sie (keine Extrapolation).
function renderIstProjectionChart(targetSeries,advisoryCurrentSeries,simLabels){
  var c=(typeof charts!=='undefined'&&charts)?charts.ist:null;
  if(!c||!c.data||!Array.isArray(c.data.datasets)||!c.data.datasets.length)return;
  var total=buildCurrentWealthProjection('total',null,null);
  var labels=total.labels||[];
  var totalSeries=total.seriesK||[];
  c.data.labels=labels;
  c.data.datasets=c.data.datasets.slice(0,1);
  var ds=c.data.datasets[0];
  ds.label='Ist-Situation (Gesamtvermögen)';
  ds.data=totalSeries;
  ds.tension=0;
  ds.stepped=false;
  // "verbesserte Situation" = Gesamt_IST(t) + (advisory_SOLL(t) - advisory_IST(t))
  // auf DERSELBEN Gesamtvermoegens-Basis (bei t=0 identisch).
  if(Array.isArray(targetSeries)&&targetSeries.length&&Array.isArray(advisoryCurrentSeries)&&advisoryCurrentSeries.length&&istProjectionStrategyValid()){
    var simIndex={};
    (Array.isArray(simLabels)?simLabels:[]).forEach(function(l,i){simIndex[String(l)]=i;});
    var improved=labels.map(function(l,i){
      var j=Object.prototype.hasOwnProperty.call(simIndex,String(l))?simIndex[String(l)]:(Array.isArray(simLabels)&&simLabels.length?-1:i);
      if(j<0||j>=targetSeries.length||j>=advisoryCurrentSeries.length||i>=totalSeries.length)return null;
      return Math.round(Number(totalSeries[i]||0)+(Number(targetSeries[j]||0)-Number(advisoryCurrentSeries[j]||0)));
    });
    c.data.datasets[1]={
      label:'Verbesserte Situation (SOLL)',
      data:improved,
      borderColor:sollColor(),
      backgroundColor:sollColor(0.06),
      _sollTone:{border:null,bg:0.06},
      borderWidth:2,
      borderDash:[5,4],
      pointRadius:0,
      pointHoverRadius:4,
      fill:false,
      spanGaps:false,
      tension:0,
      stepped:false
    };
    if(c.options&&c.options.plugins&&c.options.plugins.legend){
      c.options.plugins.legend.display=true;
      if(!c.options.plugins.legend.labels)c.options.plugins.legend.labels={};
      c.options.plugins.legend.labels.boxWidth=18;
      c.options.plugins.legend.labels.font={size:9};
    }
  }
  applyDepletionMarkerToDataset(ds,total);
  syncIstProjectionAxisScale();
  refreshIstGoalMarkers();
  c.update();
}
// Die IST-Kachel behaelt ihre Beschriftung (Cashflow-Layout: "Aktuelle
// Prognose"); ihr Jahr nennt der Hinweis ("Bis Ende ..."). Verbessert/Mehrwert
// nennen das Vergleichsjahr, weil es vom IST-Horizontende abweichen kann.
function setIstTileLabels(cmpEnd){
  setText('ub-opt-terminal-label',cmpEnd?'Verbessert Ende '+cmpEnd:'Verbessert');
  setText('ub-delta-terminal-label',cmpEnd?'Mehrwert Ende '+cmpEnd:'Mehrwert');
}
// Kennzahlen unter der Grafik (Reinvermoegen/Beratungsvermoegen optimiert) und
// die Uebersichts-Kachel "Strategie-Mehrwert" -- nur mit gueltiger Strategie.
// "Ist" bezieht sich wie die Linie immer auf das IST-Horizontende; "Verbessert"
// und "Mehrwert" vergleichen am Ende der Strategie-Simulation (gleiches Jahr).
function renderIstStrategyOverview(result){
  if(!istProjectionStrategyValid()||!result){
    renderIstWithoutStrategy();
    return;
  }
  var sim=simulationPayload(result);
  var years=sim&&sim.year_labels?sim.year_labels.length-1:null;
  var labels=sim&&sim.year_labels;
  var base=buildCurrentWealthProjection('total',years,labels);
  var improved=buildImprovedTotalProjectionFromStrategy(result,years,labels);
  var advisoryCagrBps=sim?simulationCagrBps(sim.target_mix_series_rappen):Number(result.expected_return_bps||0);
  renderOverviewProjectionSummary({
    currentProjectedRappen:base.projectedRappen,
    targetProjectedRappen:improved.projectedRappen,
    currentRecurringNetCashflowRappen:base.recurringNetCashflowRappen,
    currentCapitalNetCashflowRappen:base.capitalNetCashflowRappen,
    currentAnnualNetCashflowRappen:base.annualNetCashflowRappen,
    currentMixReturnBps:base.expectedReturnBps,
    currentCagrBps:base.cagrBps,
    targetCagrBps:improved.cagrBps,
    horizonLabel:projectionHorizonYearLabel(sim)
  });
  var full=buildCurrentWealthProjection('total',null,null);
  var fullLabels=full.labels||[];
  var istEnd=fullLabels.length?istProjectionEndYearLabel(fullLabels[fullLabels.length-1]):'';
  var cmpEnd=istProjectionEndYearLabel(projectionHorizonYearLabel(sim));
  setText('ub-ist-terminal',formatCompactCHF(Number(full.projectedRappen||0)/100));
  setIstTileLabels(cmpEnd);
  var note=document.getElementById('ub-projection-note');
  if(note)note.textContent='Bis Ende '+istEnd+' zeigt diese Seite die Ist-Situation des Gesamtvermögens aus heutigem Mix und künftigen Netto-Cashflows. Die verbesserte Situation reicht bis Ende '+cmpEnd+' (Horizont der Strategie-Simulation) und übernimmt nur die optimierte Soll-Allokation auf dem Beratungsvermögen; der holistische Rest bleibt unverändert.';
  setText('ub-return-rein',fmtPct(Number(improved.cagrBps||0),1));
  setText('ub-return-beratung',fmtPct(Number(advisoryCagrBps||0),1));
}
function renderIstWithoutStrategy(){
  var c=(typeof charts!=='undefined'&&charts)?charts.ist:null;
  var labels=(c&&c.data&&Array.isArray(c.data.labels))?c.data.labels:[];
  var projection=buildCurrentWealthProjection('total',labels.length?labels.length-1:null,labels.length?labels:null);
  renderCurrentWealthOnlyProjectionSummary(projection);
  setIstTileLabels('');
}
// Nach jedem Wechsel des Strategie-Status (syncStrategyStaleView, Hydration,
// Server-Pruefung): veraltet/fehlend -> Overlay weg + reine IST-Kennzahlen;
// wieder gueltig -> Overlay und Kennzahlen aus der bestehenden Strategie.
function syncIstProjectionStrategyGate(){
  var c=(typeof charts!=='undefined'&&charts)?charts.ist:null;
  if(!c||!c.data)return;
  var valid=istProjectionStrategyValid();
  var shown=istProjectionHasOverlay();
  if(valid&&!shown){
    updateProjectionChartsFromSimulation(strategyState.allocation);
    renderIstStrategyOverview(strategyState.allocation);
  }else if(!valid&&shown){
    c.data.datasets=c.data.datasets.slice(0,1);
    if(c.options&&c.options.plugins&&c.options.plugins.legend)c.options.plugins.legend.display=false;
    c.update();
    renderIstWithoutStrategy();
  }
}
// H9 Nachtrag N-892-01: Server-Wahrheit statt nur Sitzungs-dirty. Aenderungen
// ueber einen anderen Kanal (zweiter Berater, anderer Tab, API) machen die
// Soll-Allokation serverseitig ungueltig (Payload 409/404) oder ersetzen sie.
// Waehrend der Pruefung fail-closed (nur IST); 404/409 -> Strategie als
// veraltet markieren; andere Strategie am Server -> diese uebernehmen.
async function recheckIstProjectionWithServer(){
  var s=(typeof strategyState!=='undefined')?strategyState:null;
  var mid=istProjectionActiveMandate();
  if(!mid||(typeof isDemoMandateId==='function'&&isDemoMandateId(mid))||!s||!s.allocation)return null;
  var seq=++istServerCheck.seq;
  istServerCheck.mid=mid;
  istServerCheck.pending=true;
  istServerCheck.invalidId=null;
  syncIstProjectionStrategyGate();
  var payload=null,status=0;
  try{payload=await API.get('/mandates/'+mid+'/target-allocation/current/payload');}
  catch(e){status=Number(e&&e.status||0)||-1;}
  if(seq!==istServerCheck.seq||istProjectionActiveMandate()!==mid)return null;
  istServerCheck.pending=false;
  var current=strategyState&&strategyState.allocation;
  if(payload&&istProjectionAllocationIdentity(payload)===istProjectionAllocationIdentity(current)){
    syncIstProjectionStrategyGate();
    return 'ok';
  }
  if(payload){
    istServerCheck.invalidId=istProjectionAllocationIdentity(current);
    syncIstProjectionStrategyGate();
    if(typeof loadCurrentAllocationResult==='function'){
      try{await loadCurrentAllocationResult(mid);}catch(e2){}
      if(seq===istServerCheck.seq&&istProjectionActiveMandate()===mid)syncIstProjectionStrategyGate();
    }
    return 'replaced';
  }
  istServerCheck.invalidId=istProjectionAllocationIdentity(current);
  if((status===404||status===409)&&typeof markStrategyDirty==='function'){
    markStrategyDirty('Eingaben wurden ausserhalb dieser Ansicht geändert — bitte «Anlagestrategie berechnen» klicken.',false);
  }
  syncIstProjectionStrategyGate();
  return 'invalid';
}
function istProjectionRecheckIfVisible(){
  try{
    if(typeof activePageKey==='function'&&activePageKey()==='cf')recheckIstProjectionWithServer();
  }catch(e){}
}
if(typeof window!=='undefined'&&window&&typeof window.addEventListener==='function'){
  window.addEventListener('focus',istProjectionRecheckIfVisible);
}
