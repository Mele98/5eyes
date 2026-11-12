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
// der Stand nach dem letzten inklusiven Jahr (valid_until inklusiv). Angezeigt
// wird deshalb "Ende JJJJ" mit dem letzten inklusiven Jahr ("Ende 2060" wie
// "= bis 2060" der Horizont-Anzeige). H9 Nachtrag 2: EINE Hilfsfunktion fuer
// Vermoegensentwicklung UND Asset-Allocation-Seite.
function projectionEndOfYearText(label){
  var year=parseInt(String(label==null?'':label),10);
  return isFinite(year)?'Ende '+String(year-1):String(label==null?'':label);
}
// H9 Nachtrag N-892-04: die IST-Linie folgt immer dem IST-Horizont
// (Lebensende bzw. letzter Cashflow, Berater-Override vorrangig) -- mit und
// ohne Strategie gleich. Die verbesserte Linie existiert nur, soweit die
// Strategie-Simulation reicht; danach endet sie (keine Extrapolation).
function renderIstProjectionChart(targetSeries,advisoryCurrentSeries,simLabels){
  var c=(typeof charts!=='undefined'&&charts)?charts.ist:null;
  if(!c||!c.data)return;
  if(typeof ensureIstProjectionBasis==='function')ensureIstProjectionBasis(); // H9 Nachtrag 2
  var total=buildCurrentWealthProjection('total',null,null);
  if(total.unavailable){
    if(typeof renderIstProjectionUnavailable==='function')renderIstProjectionUnavailable();
    return;
  }
  var labels=total.labels||[];
  var totalSeries=total.seriesK||[];
  c.data.labels=labels;
  if(!Array.isArray(c.data.datasets)||!c.data.datasets.length){
    c.data.datasets=[{borderColor:'rgba(146,64,14,0.75)',backgroundColor:'rgba(146,64,14,0.08)',borderWidth:2,pointRadius:0,fill:false}];
  }
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
  setText('ub-opt-terminal-label',cmpEnd?'Verbessert '+cmpEnd:'Verbessert');
  setText('ub-delta-terminal-label',cmpEnd?'Mehrwert '+cmpEnd:'Mehrwert');
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
  var full=buildCurrentWealthProjection('total',null,null);
  if(full.unavailable){renderIstWithoutStrategy();return;}
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
  var fullLabels=full.labels||[];
  var istEnd=fullLabels.length?projectionEndOfYearText(fullLabels[fullLabels.length-1]):'';
  var cmpEnd=projectionHorizonYearLabel(sim);
  setText('ub-ist-terminal',formatCompactCHF(Number(full.projectedRappen||0)/100));
  setIstTileLabels(cmpEnd);
  var note=document.getElementById('ub-projection-note');
  if(note)note.textContent='Bis '+istEnd+' zeigt diese Seite die Ist-Situation des Gesamtvermögens aus heutigem Mix und künftigen Netto-Cashflows. Die verbesserte Situation reicht bis '+cmpEnd+' (Horizont der Strategie-Simulation) und übernimmt nur die optimierte Soll-Allokation auf dem Beratungsvermögen; der holistische Rest bleibt unverändert.';
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
  var valid=istProjectionStrategyValid();
  // N-892-05: auch ohne Grafik (noch nicht/neu aufgebaut) duerfen alte
  // Strategie-Kennzahlen im ungueltigen Zustand nicht stehen bleiben.
  if(!c||!c.data){
    if(!valid)renderIstWithoutStrategy();
    return;
  }
  var shown=istProjectionHasOverlay();
  if(valid&&!shown){
    updateProjectionChartsFromSimulation(strategyState.allocation);
    renderIstStrategyOverview(strategyState.allocation);
  }else if(!valid){
    // C-892-01 (Codex 61d8d69d): ungueltig -> Kennzahlen/Hinweis IMMER auf
    // IST zuruecksetzen, auch wenn die Grafik schon kein Overlay mehr hat
    // (neu aufgebaut, Mandatswechsel); nur das Kuerzen haengt von `shown` ab.
    if(shown){
      c.data.datasets=c.data.datasets.slice(0,1);
      if(c.options&&c.options.plugins&&c.options.plugins.legend)c.options.plugins.legend.display=false;
      c.update();
    }
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
// H9 Nachtrag 2: Kennzahlen/Hinweis der Vermoegensentwicklung (aus dem Monolithen
// verschoben, damit IST-Darstellung und Beschriftung an einer Stelle liegen).
function renderCurrentWealthOnlyProjectionSummary(projection){
  var safeProjection=projection||buildCurrentWealthProjection('total');
  var horizonLabel=(safeProjection.labels&&safeProjection.labels.length)?projectionEndOfYearText(safeProjection.labels[safeProjection.labels.length-1]):'';
  var unavailableReason=safeProjection.unavailableReason||(safeProjection.unavailable?istProjectionBasisUnavailableReason():'');
  setText('ub-ist-terminal',unavailableReason?'—':formatCompactCHF(Number(safeProjection.projectedRappen||0)/100));
  setText('ub-opt-terminal','—');
  setText('ub-cagr-ist',unavailableReason?'—':fmtPct((Number(safeProjection.expectedReturnBps||safeProjection.cagrBps||0)),1));
  setText('ub-cagr-opt','—');
  setText('ub-delta-terminal','—');
  var note=document.getElementById('ub-projection-note');
  if(note){
    note.style.color='var(--n6)';
    note.style.background='var(--bg)';
    note.style.borderColor='rgba(90,104,120,0.12)';
    note.textContent=unavailableReason?unavailableReason:(horizonLabel?'Bis '+horizonLabel+' zeigt':'Sobald Vermögen oder Cashflows erfasst sind, zeigt')+' diese Seite die Ist-Situation des Gesamtvermögens aus heutigem Mix und künftigen Netto-Cashflows. Die verbesserte Situation erscheint erst mit gültigem Risikoprofil und berechneter Anlagestrategie.';
  }
  setText('ub-return-rein','–');setText('ub-return-beratung','–'); // H9: ohne Strategie keine optimierten Renditen
  var overviewKpi=document.getElementById('kpi-card-projection');
  if(overviewKpi){
    var label=overviewKpi.querySelector('.kl');
    var value=overviewKpi.querySelector('.kv');
    var sub=overviewKpi.querySelector('.ks');
    if(label)label.innerHTML='Strategie-Mehrwert '+horizonLabel+' <span style="font-size:8px;color:var(--n3)">↗</span>';
    if(value)value.textContent='—';
    if(sub)sub.innerHTML='<span class="a">Erscheint nach Strategie-Berechnung</span>';
  }
}
function renderOverviewProjectionSummary(config){
  var currentProjectedRappen=Number(config&&config.currentProjectedRappen||0);
  var targetProjectedRappen=Number(config&&config.targetProjectedRappen||0);
  var currentCagrBps=Number(config&&config.currentCagrBps||0);
  var targetCagrBps=Number(config&&config.targetCagrBps||0);
  var currentAnnualNetCashflowRappen=Number(config&&config.currentAnnualNetCashflowRappen||0);
  var currentMixReturnBps=Number(config&&config.currentMixReturnBps||0);
  var horizonLabel=String(config&&config.horizonLabel||'Horizontende');
  var deltaChf=Math.round((targetProjectedRappen-currentProjectedRappen)/100);
  var tone=deltaChf>=0?'var(--pos)':'var(--warn)';
  setText('ub-ist-terminal',formatCompactCHF(currentProjectedRappen/100));
  setText('ub-opt-terminal',formatCompactCHF(targetProjectedRappen/100));
  setText('ub-cagr-ist',fmtPct((currentMixReturnBps||currentCagrBps||0),1));
  setText('ub-cagr-opt',fmtPct((targetCagrBps||0),1));
  setText('ub-delta-terminal',(deltaChf>=0?'+':'\u2212')+'CHF '+fmtLocaleCH(Math.abs(deltaChf)));
  var note=document.getElementById('ub-projection-note');
  if(note){
    note.style.color='var(--n6)';
    note.style.background='var(--bg)';
    note.style.borderColor='rgba(90,104,120,0.12)';
    note.textContent='Bis '+horizonLabel+' zeigt diese Seite die Ist-Situation des Gesamtvermögens aus heutigem Mix und künftigen Netto-Cashflows. Die verbesserte Situation übernimmt nur die optimierte Soll-Allokation auf dem Beratungsvermögen; der holistische Rest bleibt unverändert.';
  }
  var overviewKpi=document.getElementById('kpi-card-projection');
  if(overviewKpi){
    var label=overviewKpi.querySelector('.kl');
    var value=overviewKpi.querySelector('.kv');
    var sub=overviewKpi.querySelector('.ks');
    if(label)label.innerHTML='Strategie-Mehrwert '+horizonLabel+' <span style="font-size:8px;color:var(--n3)">↗</span>';
    if(value)value.textContent=(deltaChf>=0?'+':'\u2212')+'CHF '+fmtLocaleCH(Math.abs(deltaChf));
    if(sub)sub.innerHTML='<span style="color:'+tone+'">'+(deltaChf>=0?'Verbesserte Situation ueber Ist':'Ist liegt ueber Zielpfad')+'</span>';
  }
}
