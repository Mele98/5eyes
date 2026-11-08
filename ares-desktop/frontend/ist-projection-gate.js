// H9 (Owner-UX 2026-11-08): Vermoegensentwicklung "heute" (Cashflow-Schritt,
// Grafik #ch-ist) zeigt die verbesserte/optimierte Kurve NUR, wenn fuer das
// Mandat eine gueltige, nicht veraltete Strategie existiert:
//   - berechnete Soll-Allokation mit Simulation (strategyState.allocation),
//   - aktuelles, strategietaugliches Risikoprofil (strategyState.risk),
//   - kein offener Stale-Hinweis (dirty + staleNotice wie das AA-Badge).
// Ohne Strategie nur die IST-Entwicklung; keine Annahmen erfinden (kein
// Default-Profil, keine pauschale Mehrrendite). Ausgelagerter Monolith-Teil
// (Bundle, Budget, Verbots-Guards); nutzt die globalen Helfer des Monolithen,
// die erst beim Aufruf aufgeloest werden.
function istProjectionStrategyValid(){
  var s=(typeof strategyState!=='undefined')?strategyState:null;
  var a=s&&s.allocation;
  if(!a||!Array.isArray(a.buckets)||!a.buckets.length)return false;
  var sim=a.simulation;
  if(!sim||!Array.isArray(sim.target_mix_series_rappen)||!sim.target_mix_series_rappen.length)return false;
  if(!s.risk)return false;
  if(s.dirty&&s.staleNotice)return false;
  return true;
}
function istProjectionHasOverlay(){
  var c=(typeof charts!=='undefined'&&charts)?charts.ist:null;
  return !!(c&&c.data&&Array.isArray(c.data.datasets)&&c.data.datasets.length>1);
}
// Kennzahlen unter der Grafik (Reinvermoegen/Beratungsvermoegen optimiert) und
// die Uebersichts-Kachel "Strategie-Mehrwert" -- nur mit gueltiger Strategie.
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
  setText('ub-return-rein',fmtPct(Number(improved.cagrBps||0),1));
  setText('ub-return-beratung',fmtPct(Number(advisoryCagrBps||0),1));
}
function renderIstWithoutStrategy(){
  var c=(typeof charts!=='undefined'&&charts)?charts.ist:null;
  var labels=(c&&c.data&&Array.isArray(c.data.labels))?c.data.labels:[];
  var projection=buildCurrentWealthProjection('total',labels.length?labels.length-1:null,labels.length?labels:null);
  renderCurrentWealthOnlyProjectionSummary(projection);
}
// Nach jedem Wechsel des Strategie-Status (syncStrategyStaleView, Hydration):
// veraltet/fehlend -> Overlay weg + reine IST-Kennzahlen; wieder gueltig ->
// Overlay und Kennzahlen aus der bestehenden Strategie neu aufbauen.
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
