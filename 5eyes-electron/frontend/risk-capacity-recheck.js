// RISK-CAPACITY-RECHECK-UI-001: Plausibilitaetspruefung Risikofaehigkeit laden
// und den ruhigen Hinweis "neu zu pruefen" (#rp-capacity-recheck) setzen.
// Ausgelagert aus 5eyes_v2.html (Monolith-Budget, Toleranz 0). Laedt als
// klassisches Skript und nutzt die globalen Helfer des Monolithen (API,
// escapeHtml, getActiveMandateId, isDemoMandateId,
// renderRiskCapacityPlausibility); diese werden erst beim Aufruf aufgeloest.
//
// bound_evaluation (GET /mandates/{id}/risk-capacity-plausibility) ist die
// zuletzt gebundene Bewertung; needs_recheck = sie entspricht nicht mehr der
// aktuellen Datenlage. Reiner Hinweis: blockiert nichts, aendert nichts.
var RISK_CAPACITY_RECHECK_FALLBACK_LABEL='neu zu prüfen';

function renderRiskCapacityRecheck(bound){
  var box=document.getElementById('rp-capacity-recheck');
  if(!box)return;
  if(!bound||bound.needs_recheck!==true){
    box.style.display='none';
    box.innerHTML='';
    box.dataset.recheckCode='';
    return;
  }
  var label=String(bound.recheck_label||RISK_CAPACITY_RECHECK_FALLBACK_LABEL);
  box.dataset.recheckCode=String(bound.recheck_code||'');
  box.innerHTML='<span style="display:inline-block;margin-right:6px;padding:0 6px;border:1px solid var(--b1);'
    +'border-radius:var(--r);font-weight:600;text-transform:uppercase;letter-spacing:.04em">'
    +escapeHtml(label)+'</span>'
    +(bound.recheck_text?escapeHtml(bound.recheck_text):'');
  box.style.display='block';
}

async function refreshRiskCapacityPlausibility(mid){
  var requested=String(mid||'');
  if(!requested||isDemoMandateId(requested)){
    renderRiskCapacityPlausibility(null);
    return null;
  }
  try{
    var res=await API.get('/mandates/'+requested+'/risk-capacity-plausibility');
    if(String(getActiveMandateId()||'')!==requested)return null;
    renderRiskCapacityPlausibility(res);
    return res;
  }catch(e){
    if(String(getActiveMandateId()||'')===requested)renderRiskCapacityPlausibility(null);
    return null;
  }
}
