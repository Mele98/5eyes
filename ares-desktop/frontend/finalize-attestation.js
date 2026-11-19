/* Ares -- Finalisierung der Umsetzung mit Bestaetigung "Bewertung aktuell".
 * CCX-P3 (N-909-07, 2026-11-14): aus ares.html ausgelagert (Monolith-Budget). Ohne
 * Owner-Frist fuer manuelle Bewertungen bestaetigt der Berater bei jeder Finalisierung,
 * dass die erfassten Bewertungen aktuell sind; der Server bindet die Bestaetigung im
 * Bewertungs-Snapshot und im Audit. Teil des Monolith-Bundles. */
async function confirmImplementationRecipe(){
  var ok=await refreshStrategyData(true,true);
  if(!ok)return;
  var mid=getActiveMandateId();
  var runId=strategyState&&strategyState.recommendation&&strategyState.recommendation.run?strategyState.recommendation.run.id:null;
  try{
    if(mid&&runId&&!isDemoMandateId(mid)){
      // CCX-P3 (N-909-07): ohne Owner-Frist bestaetigt der Berater bei jeder
      // Finalisierung, dass die erfassten Bewertungen aktuell sind (auditiert).
      var attested=await uiConfirm({title:'Bewertungen bestätigen',message:'Ich bestätige, dass die erfassten Bewertungen (Wert und Stichtag je Vermögensposition) aktuell sind.'});
      if(!attested)return;
      await API.fetch('/mandates/'+mid+'/recommendations/'+runId+'/finalize?confirm_valuations_current=true',{method:'PUT'});
      updateStrategyStatus('Empfehlung finalisiert. Nächster Schritt: Asset Allokation › Publizieren.',false);refreshAllocationPublication(true);
    }else{
      updateStrategyStatus('Umsetzungsplan aufgebaut, er kann jetzt gedruckt werden.',false);
    }
    cm('m-ums');
    printPortfolioPlan();
  }catch(e){
    updateStrategyStatus('Empfehlung konnte nicht finalisiert werden: '+finalizeErrorText(e),true);if(typeof eligOverrideOnFinalizeBlocked==='function')eligOverrideOnFinalizeBlocked(mid,runId,e);
  }
}
