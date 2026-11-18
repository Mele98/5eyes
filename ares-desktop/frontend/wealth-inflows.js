/* Ares -- Vermoegenszufluesse (Roadmap #54) als ausgelagerter Monolith-Teil.
 * CCX-P3-FX (2026-11-14): aus ares.html ausgelagert (Monolith-Budget); jeder Zufluss
 * traegt seine erfasste Waehrung (Pflichtfeld, nie geraten), Anzeige in dieser Waehrung.
 * Teil des Monolith-Bundles (scripts/audit_html_monolith.py EXTRACTED_MONOLITH_PARTS). */
// CCX-P3-FX: Cashflow-Summen im Mandatskontext in der Mandatswaehrung (Server
// rechnet mit gebundener FX-Basis um; ohne Mandat nur bei einheitlicher Waehrung).
function cashflowSummaryQuery(mid){return mid?('?mandate_id='+encodeURIComponent(mid)):'';}
// ---------------------------------------------------------------------------
// Roadmap #54: Dedizierte Vermoegenszufluesse (einmalige Wealth-Inflows).
// ADDITIV — die bestehenden Cashflow-Funktionen bleiben unberuehrt. Eigenes
// State (currentInflows), eigenes Modal (m-awi), eigener Container (#inflow-rows).
// ---------------------------------------------------------------------------
var currentInflows=[];
var currentInflowEditId=null;
// Deutsche Labels fuer die 5 source_types (Backend-Werte exakt beibehalten).
var INFLOW_SOURCE_LABELS={Erbschaft:'Erbschaft',Bonus:'Bonus',Saeule3b:'Säule 3b',Verkaufserloes:'Verkaufserlös',Andere:'Andere'};
function inflowSourceLabel(v){return INFLOW_SOURCE_LABELS[String(v||'')]||String(v||'');}
// VORSORGE-PROJECTION-001: Auswahl der externen Vorsorge-Positionen, aus denen
// ein Zufluss stammen kann (Backend validiert dieselbe Regel).
function populateInflowLinkedPositionOptions(selectedId){
  var sel=document.getElementById('awi-linked-position');
  if(!sel)return;
  var list=(typeof currentWealthPositions!=='undefined'&&Array.isArray(currentWealthPositions))?currentWealthPositions:[];
  var html='<option value="">Keine (neues Vermögen)</option>';
  var found=false;
  list.forEach(function(pos){
    if(!isExternalPensionPosition(pos))return;
    var id=String(pos.id||'');
    if(id===String(selectedId||''))found=true;
    html+='<option value="'+escapeHtml(id)+'">'+escapeHtml(String(pos.label||'Vorsorge')+(pos.pension_type?' ('+pos.pension_type+')':''))+'</option>';
  });
  if(selectedId&&!found)html+='<option value="'+escapeHtml(String(selectedId))+'">Verknüpfte Vorsorge-Position</option>';
  sel.innerHTML=html;
  sel.value=selectedId?String(selectedId):'';
}
function resetInflowModal(){
  currentInflowEditId=null;
  setInputValue('awi-label','');
  setSelectValue('awi-source-type','Erbschaft');
  setInputValue('awi-amount','');
  setSelectValue('awi-currency',mandateCurrency()||'');
  setInputValue('awi-year','');
  setSelectValue('awi-value-mode','nominal');
  var rec=document.getElementById('awi-recurring');if(rec)rec.checked=false;
  setSelectValue('awi-frequency','einmalig');
  setInputValue('awi-duration','');
  setInputValue('awi-notes','');
  populateInflowLinkedPositionOptions('');
  setSelectValue('awi-certainty','sicher');
  var btn=document.getElementById('btn-awi-save');
  if(btn){btn.textContent='Speichern';btn.disabled=false;}
  var err=document.getElementById('awi-error');
  if(err){err.style.display='none';err.textContent='';}
  syncInflowModalState();
}
// Frequenz-/Dauer-Felder nur bei wiederkehrendem Zufluss anzeigen.
function syncInflowModalState(){
  var rec=document.getElementById('awi-recurring');
  var wrap=document.getElementById('awi-recurring-wrap');
  // PENSION-TRANSFER-LEDGER-001: ein verknuepfter Vorsorgebezug ist ein
  // einmaliger, nominaler Vollbezug (Backend lehnt sonst mit 422 ab).
  var linkedSel=document.getElementById('awi-linked-position');
  var isLinked=!!(linkedSel&&linkedSel.value);
  var valueModeSel=document.getElementById('awi-value-mode');
  if(rec){if(isLinked)rec.checked=false;rec.disabled=isLinked;}
  if(valueModeSel){if(isLinked)valueModeSel.value='nominal';valueModeSel.disabled=isLinked;}
  // INFLOW-CERTAINTY-001: verknuepfter Vorsorgebezug ist immer sicher.
  var certaintySel=document.getElementById('awi-certainty');
  if(certaintySel){if(isLinked)certaintySel.value='sicher';certaintySel.disabled=isLinked;}
  var isRec=!!(rec&&rec.checked);
  if(wrap)wrap.style.display=isRec?'':'none';
  if(isRec){
    // Wiederkehrend erfordert eine echte Frequenz — 'einmalig' waere invalide.
    if(getInputValue('awi-frequency')==='einmalig')setSelectValue('awi-frequency','jaehrlich');
  }
}
function openNewInflow(){
  resetInflowModal();
  var modal=document.getElementById('m-awi');
  if(modal)modal.classList.add('open');
}
function openInflowEditor(inflowId){
  var inflow=(currentInflows||[]).find(function(item){return String(item.id||'')===String(inflowId||'');});
  if(!inflow)return;
  currentInflowEditId=inflow.id;
  setInputValue('awi-label',inflow.label||'');
  setSelectValue('awi-source-type',inflow.source_type||'Erbschaft');
  setInputValue('awi-amount',formatInputCHF(inflow.amount_rappen));
  setSelectValue('awi-currency',ccyOf(inflow.currency)||'');
  setInputValue('awi-year',inflow.expected_year!=null?String(inflow.expected_year):'');
  setSelectValue('awi-value-mode',inflow.value_mode||'nominal');
  var rec=document.getElementById('awi-recurring');if(rec)rec.checked=!!(inflow.is_recurring);
  setSelectValue('awi-frequency',inflow.frequency||'einmalig');
  setInputValue('awi-duration',inflow.duration_years!=null?String(inflow.duration_years):'');
  setInputValue('awi-notes',inflow.notes||'');
  populateInflowLinkedPositionOptions(inflow.linked_position_id||'');
  setSelectValue('awi-certainty',inflow.certainty==='unsicher'?'unsicher':'sicher');
  var btn=document.getElementById('btn-awi-save');
  if(btn){btn.textContent='Aktualisieren';btn.disabled=false;}
  var err=document.getElementById('awi-error');
  if(err){err.style.display='none';err.textContent='';}
  syncInflowModalState();
  var modal=document.getElementById('m-awi');
  if(modal)modal.classList.add('open');
}
async function saveInflow(){
  var label=(document.getElementById('awi-label')||{value:''}).value.trim();
  var sourceType=(document.getElementById('awi-source-type')||{value:'Erbschaft'}).value;
  var amount=(document.getElementById('awi-amount')||{value:''}).value;
  var yearRaw=(document.getElementById('awi-year')||{value:''}).value;
  var valueMode=(document.getElementById('awi-value-mode')||{value:'nominal'}).value;
  var isRecurring=!!(document.getElementById('awi-recurring')&&document.getElementById('awi-recurring').checked);
  var frequency=(document.getElementById('awi-frequency')||{value:'einmalig'}).value;
  var durationRaw=(document.getElementById('awi-duration')||{value:''}).value;
  var btn=document.getElementById('btn-awi-save');
  var isEdit=!!currentInflowEditId;
  if(!label){showModalFeedback('awi-error',btn,'Bitte Bezeichnung eingeben.',true);return;}
  if(!amount||isNaN(parseFloat(amount))){showModalFeedback('awi-error',btn,'Bitte gültigen Betrag eingeben.',true);return;}
  var amountRappen=parseCHF(amount);
  if(amountRappen<=0){showModalFeedback('awi-error',btn,'Betrag muss grösser als 0 sein.',true);return;}
  var year=parseInt(yearRaw,10);
  if(!isFinite(year)||year<1900||year>2200){showModalFeedback('awi-error',btn,'Bitte gültiges Jahr (1900–2200) eingeben.',true);return;}
  var durationYears=durationRaw!==''?parseInt(durationRaw,10):null;
  var linkedPositionId=(document.getElementById('awi-linked-position')||{value:''}).value||null;
  if(linkedPositionId&&(isRecurring||valueMode!=='nominal')){
    showModalFeedback('awi-error',btn,'Ein mit einer Vorsorge-Position verknüpfter Zufluss ist ein einmaliger Kapitalbezug (nominal, nicht wiederkehrend).',true);
    return;
  }
  // Spiegelt die Backend-Regel: is_recurring=1 verlangt frequency in
  // {jaehrlich,monatlich} UND duration_years — sonst 422.
  if(isRecurring){
    if(frequency==='einmalig'){showModalFeedback('awi-error',btn,'Wiederkehrender Zufluss benötigt eine Frequenz (jährlich oder monatlich).',true);return;}
    if(!durationYears||durationYears<1||durationYears>99){showModalFeedback('awi-error',btn,'Wiederkehrender Zufluss benötigt eine Dauer (1–99 Jahre).',true);return;}
  }
  // CCX-P3-FX: Betrag und Waehrung sind untrennbar; die Waehrung wird nie geraten.
  var inflowCurrency=ccyOf((document.getElementById('awi-currency')||{value:''}).value);
  if(!inflowCurrency){showModalFeedback('awi-error',btn,'Bitte die Währung des Zuflusses wählen.',true);return;}
  var payload={
    label:label,
    source_type:sourceType,
    amount_rappen:amountRappen,
    currency:inflowCurrency,
    expected_year:year,
    is_recurring:isRecurring?1:0,
    value_mode:valueMode
  };
  if(isRecurring){
    payload.frequency=frequency;
    payload.duration_years=durationYears;
  }
  var notes=(document.getElementById('awi-notes')||{value:''}).value.trim();
  if(notes)payload.notes=notes;
  payload.linked_position_id=linkedPositionId;
  // INFLOW-CERTAINTY-001: 'unsicher' senkt weder Reserve noch fliesst er in die Simulation.
  var certainty=(document.getElementById('awi-certainty')||{value:'sicher'}).value;
  payload.certainty=(linkedPositionId||certainty!=='unsicher')?'sicher':'unsicher';
  var cid=getActiveClientId();
  if(!cid||isDemoClientId(cid)){
    showModalFeedback('awi-error',btn,'Bitte zuerst einen echten Mandanten auswählen.',true);
    return;
  }
  if(btn){btn._origText=isEdit?'Aktualisieren':'Speichern';btn.disabled=true;btn.textContent=isEdit?'Aktualisieren...':'Speichern...';}
  try{
    if(isEdit)await API.put('/wealth-inflows/'+currentInflowEditId,payload);
    else await API.post('/clients/'+cid+'/wealth-inflows',payload);
    showModalFeedback('awi-error',btn,isEdit?'OK: Zufluss aktualisiert':'OK: Zufluss gespeichert',false);
    cm('m-awi');
    await refreshInflowsUI(cid);
    refreshIstGoalMarkers();
    try{showAppSuccess(isEdit?'Vermögenszufluss aktualisiert':'Vermögenszufluss gespeichert');}catch(noticeErr){}
  }catch(e){
    var wiErr=pensionTransferGuardMessage(e);
    showModalFeedback('awi-error',btn,wiErr,true);
    try{showAppError(wiErr,{title:'Vermögenszufluss nicht gespeichert'});}catch(noticeErr){}
  }
}
// PENSION-TRANSFER-LEDGER-001: verstaendliche Meldungen fuer die Transfer-
// Guards (409/422 mit reason_code) statt "API 409: ... [CODE]".
var PENSION_TRANSFER_GUARD_HINTS={
  PENSION_SOURCE_LINKED:'Diese Vorsorge-Position ist mit einem Kapitalbezug verknüpft. Löschen, deaktivieren oder entknüpfen Sie zuerst den Vermögenszufluss.',
  PENSION_SOURCE_ALREADY_LINKED:'Diese Vorsorge-Position ist bereits mit einem aktiven Kapitalbezug verknüpft. Bitte den bestehenden Zufluss bearbeiten.'
};
function pensionTransferGuardMessage(e){
  var parsed=null;
  try{parsed=e&&e.body?JSON.parse(e.body):null;}catch(parseErr){parsed=null;}
  var detail=parsed&&parsed.detail;
  if(detail&&typeof detail==='object'&&PENSION_TRANSFER_GUARD_HINTS[detail.reason_code]){
    return detail.message||PENSION_TRANSFER_GUARD_HINTS[detail.reason_code];
  }
  return 'Fehler: '+((e&&(e.detail||e.message))||'?');
}
// RISK-BUDGET-RELEASE-GATE (2026-10-21): Handoff und Signatur von
// Empfehlungsdokumenten werden serverseitig blockiert (409 + reason_code),
// wenn die Soll-Allokation ihr Risikobudget verletzt oder der Nachweis
// fehlt. Verstaendliche Meldung statt "API 409: ... [CODE]".
var RELEASE_GATE_HINTS={
  RISK_BUDGET_VIOLATED:'Die Soll-Allokation überschreitet das Risikobudget des Risikoprofils. Bitte Risikoprofil oder Bausteine anpassen und die Allokation neu generieren.',SIGNATURE_ARTIFACT_MISSING:'Signiert wird nur ein archiviertes PDF. Bitte das Dokument zuerst erzeugen.',SIGNATURE_ARTIFACT_HASH_MISMATCH:'Die archivierten PDF-Bytes passen nicht zur Prüfsumme. Bitte das Dokument neu erzeugen.',
  RISK_BUDGET_EVIDENCE_MISSING:'Für die aktuelle Soll-Allokation fehlt der Nachweis, dass das Risikobudget eingehalten ist. Bitte die Allokation neu generieren.',
  RELEASE_ALLOCATION_MISSING:'Die Empfehlung ist keiner gültigen Soll-Allokation zugeordnet. Bitte die Allokation neu generieren.',HANDOFF_ALREADY_OPEN:'Für diese Handelsliste besteht bereits eine offene Weiterleitung.',CLIENT_SIGNATURE_REQUIRES_CLIENT_PRINCIPAL:'Die Kundenunterschrift kann nicht im Berater-Login erfasst werden (kundeneigener Faktor nötig; Vor-Ort-Signatur noch nicht freigegeben).'
};
function releaseGateMessage(e){
  var parsed=null;
  try{parsed=e&&e.body?JSON.parse(e.body):null;}catch(parseErr){parsed=null;}
  var detail=parsed&&parsed.detail;
  if(detail&&typeof detail==='object'&&RELEASE_GATE_HINTS[detail.reason_code]){
    return detail.message||RELEASE_GATE_HINTS[detail.reason_code];
  }
  return null;
}
async function deleteInflow(inflowId){
  if(!inflowId)return;
  try{
    await API.delete('/wealth-inflows/'+inflowId);
    var cid=getActiveClientId();
    await refreshInflowsUI(cid);
    refreshIstGoalMarkers();
    try{showAppSuccess('Vermögenszufluss gelöscht');}catch(noticeErr){}
  }catch(e){
    try{showAppError('Fehler beim Löschen: '+(e.detail||e.message||'?'),{title:'Vermögenszufluss nicht gelöscht'});}catch(noticeErr){}
  }
}
async function refreshInflowsUI(cid){
  cid=cid||getActiveClientId();
  var host=document.getElementById('inflow-rows');
  if(!cid||isDemoClientId(cid)){
    currentInflows=[];
    if(host)host.innerHTML=journeyEmptyHint('Noch keine erwarteten Vermögenszuflüsse. Erfassen Sie z.B. eine Erbschaft, einen Bonus oder einen Verkaufserlös.');
    return;
  }
  try{
    var items=await API.get('/clients/'+cid+'/wealth-inflows');
    if(String(cid)!==String(currentClientId||''))return;
    if(!Array.isArray(items))items=(items&&items.items)||[];
    currentInflows=Array.isArray(items)?items.slice():[];
    var fmtR=function(r,c){return formatRappen(Number(r||0),ccyOf(c));};  // CCX-P3-FX: Zufluss in seiner erfassten Waehrung (unbekannt -> —)
    if(!host)return;
    if(!currentInflows.length){
      host.innerHTML=journeyEmptyHint('Noch keine erwarteten Vermögenszuflüsse. Erfassen Sie z.B. eine Erbschaft, einen Bonus oder einen Verkaufserlös.');
      return;
    }
    host.innerHTML=currentInflows.map(function(inflow){
      var sub=escapeHtml(inflowSourceLabel(inflow.source_type)+' · '+(inflow.expected_year||'')+(inflow.certainty==='unsicher'?' · unsicher, nicht eingerechnet':''));
      return '<div class="cf-row" data-inflowid="'+escapeHtml(inflow.id||'')+'">'+
        '<div class="cfn"><div class="cfna">'+escapeHtml(inflow.label||'Zufluss')+'</div><div class="cfnd">'+sub+'</div></div>'+
        '<div class="cfa ci">+'+fmtR(inflow.amount_rappen||0,inflow.currency)+'</div>'+
        '<div><button class="btn-ico e" type="button" title="Bearbeiten" aria-label="Vermögenszufluss bearbeiten">&#9998;</button><button class="btn-ico d" type="button" title="Löschen" aria-label="Vermögenszufluss löschen">&#10005;</button></div></div>';
    }).join('');
    Array.prototype.forEach.call(host.querySelectorAll('.cf-row[data-inflowid] .btn-ico'),function(btn){
      var row=btn.closest('.cf-row[data-inflowid]');
      if(!row)return;
      var inflowId=row.getAttribute('data-inflowid')||'';
      btn.onclick=function(ev){
        if(ev)ev.preventDefault();
        if(btn.classList.contains('e'))openInflowEditor(inflowId);
        else deleteInflow(inflowId);
      };
    });
  }catch(e){
    if(String(cid)!==String(currentClientId||''))return;
    console.warn('refreshInflowsUI:',e);
    currentInflows=[];
    if(host)host.innerHTML=journeyEmptyHint('Vermögenszuflüsse konnten nicht geladen werden.');
  }
}
// Chart-Marker fuer Vermoegenszufluesse (gruen, mirror von buildGoalTimelineMarkers).
function buildWealthInflowMarkers(labels){
  if(!Array.isArray(labels)||!labels.length)return [];
  var inflows=(typeof currentInflows!=='undefined'&&Array.isArray(currentInflows))?currentInflows:[];
  if(!inflows.length)return [];
  var fmtR=function(r){return fmtNumber(Number(r||0)/100,0);};
  var markers=[];
  inflows.forEach(function(inflow){
    if(!inflow)return;
    if(Object.prototype.hasOwnProperty.call(inflow,'is_active')&&inflow.is_active===0)return;
    var idx=labels.indexOf(String(inflow.expected_year));
    if(idx<0)return;
    var nm=String(inflow.label||inflowSourceLabel(inflow.source_type)||'Zufluss');
    if(inflow.certainty==='unsicher')nm+=' – unsicher, nicht eingerechnet';
    markers.push({index:idx,year:inflow.expected_year,label:nm+' ('+formatRappen(inflow.amount_rappen,ccyOf(inflow.currency))+')',shortLabel:inflowSourceLabel(inflow.source_type),type:'inflow'});
  });
  return markers;
}
