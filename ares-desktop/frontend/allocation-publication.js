// CCX-P4 Allocation-Publish (2026-11-14): Publikationsstatus der Soll-Allokation
// und "Portfolio umsetzen" (aus ares.html ausgelagert, Monolith-Budget).
// "Portfolio umsetzen" haelt nur die publizierte, frische Soll-Allokation fest
// (Server-Gate POST /mandates/{id}/strategy-snapshots).

function syncPortfolioUmsetzenButtonVisibility(){
  // CCX-P4: "Portfolio umsetzen" nur fuer die publizierte Soll-Allokation.
  applyPortfolioUmsetzenVisibility();
  renderAllocationPublication();
  refreshAllocationPublication(false);
}

function openPortfolioUmsetzenModal(){
  var alloc=strategyState&&strategyState.allocation;
  if(!alloc||!Array.isArray(alloc.buckets)||!alloc.buckets.length){
    uiAlert({level:'warn',message:'Bitte zuerst Anlagestrategie berechnen.'});
    return;
  }
  var now=new Date();
  var todayLocal=[String(now.getFullYear()),String(now.getMonth()+1).padStart(2,'0'),String(now.getDate()).padStart(2,'0')].join('-');
  var dateEl=document.getElementById('pu-date');
  if(dateEl)dateEl.value=todayLocal;
  var mid=getActiveMandateId();
  var risk=currentPersistedRiskForMandate(mid)||(strategyState&&strategyState.risk)||null;
  var riskLabel=risk?(risk.override_profile||risk.final_profile||'Nicht definiert'):'Nicht definiert';
  var riskScore=risk&&((risk.override_score_x10!=null)||(risk.final_score_x10!=null))
    ?Math.round(Number(risk.override_score_x10!=null?risk.override_score_x10:risk.final_score_x10||0)/10)
    :null;
  var riskDisplay=document.getElementById('pu-risk-display');
  if(riskDisplay)riskDisplay.textContent=riskLabel+(riskScore!=null?' ('+riskScore+'/10)':'');
  var sumRows=document.getElementById('pu-summary-rows');
  if(sumRows){
    var ENGINE_LABELS={
      'Aktien':'Aktien',
      'Obligationen':'Obligationen',
      'Immobilien':'Immobilien',
      'Liquiditaet':'Liquidität',
      'Alternative':'Alternative'
    };
    var totalAdvisoryRappen=Math.round(Number(alloc.advisory_wealth_rappen||0));
    var rowsHtml=(alloc.buckets||[]).map(function(b){
      var label=ENGINE_LABELS[String(b.asset_class||'')]||String(b.asset_class||'');
      var pct=sollPct(b.asset_class,b.target_weight_bps,alloc.buckets);
      var targetRappen=Number(b.target_amount_rappen!=null?b.target_amount_rappen:Math.round(totalAdvisoryRappen*Number(b.target_weight_bps||0)/10000));
      var bandInfo=(b.band_min_bps!=null&&b.band_max_bps!=null)
        ?'Band: '+formatBpsPercent(b.band_min_bps)+'–'+formatBpsPercent(b.band_max_bps)
        :'Band: —';
      return '<div style="display:grid;grid-template-columns:1.2fr 60px 100px 1fr;gap:6px;align-items:center;padding:6px 12px;border-bottom:1px solid var(--b1)">'
        +'<div style="font-size:11px;font-weight:500;color:var(--n8)">'+escapeHtml(label)+'</div>'
        +'<div style="text-align:right;font-size:11px;font-weight:600;color:var(--n8)">'+escapeHtml(pct)+'</div>'
        +'<div style="text-align:right;font-size:10px;color:var(--n5)">'+escapeHtml(formatRappen(targetRappen))+'</div>'
        +'<div style="font-size:9px;color:var(--n4)">'+escapeHtml(bandInfo)+'</div>'
        +'</div>';
    }).join('');
    var totalHtml='<div style="display:flex;justify-content:space-between;padding:8px 12px;border-top:2px solid var(--b1);font-size:11px;font-weight:600;color:var(--n7)">'
      +'<span>Beratungsvermögen</span>'
      +'<span>'+escapeHtml(formatRappen(totalAdvisoryRappen))+'</span>'
      +'</div>';
    sumRows.innerHTML=rowsHtml+totalHtml;
  }
  var errEl=document.getElementById('pu-error');
  if(errEl){
    errEl.textContent='';
    errEl.style.display='none';
  }
  var noteEl=document.getElementById('pu-note');
  if(noteEl)noteEl.value='';
  om('m-pu');
}

async function savePortfolioUmsetzen(){
  var mid=getActiveMandateId();
  var errEl=document.getElementById('pu-error');
  var btn=document.getElementById('btn-pu-save');
  function showErr(msg){
    if(errEl){
      errEl.textContent=msg;
      errEl.style.display='';
    }
  }
  if(!mid||isDemoMandateId(mid)){
    cm('m-pu');
    printCurrentRubricPdf();
    return;
  }
  var alloc=strategyState&&strategyState.allocation;
  var risk=currentPersistedRiskForMandate(mid)||(strategyState&&strategyState.risk)||null;
  if(!alloc||!Array.isArray(alloc.buckets)||!alloc.buckets.length){
    showErr('Keine Strategie geladen. Bitte Anlagestrategie berechnen.');
    return;
  }
  var dateVal=(document.getElementById('pu-date')||{}).value;
  if(!dateVal){
    var now=new Date();
    dateVal=[String(now.getFullYear()),String(now.getMonth()+1).padStart(2,'0'),String(now.getDate()).padStart(2,'0')].join('-');
  }
  var noteVal=((document.getElementById('pu-note')||{}).value||'').trim()||null;
  function getBucket(engineKey){
    return (alloc.buckets||[]).find(function(x){return String(x.asset_class||'')===engineKey;})||null;
  }
  function getBps(engineKey){
    var b=getBucket(engineKey);
    return b?Number(b.target_weight_bps||0):0;
  }
  function getBandLo(engineKey){
    var b=getBucket(engineKey);
    return b&&b.band_min_bps!=null?Number(b.band_min_bps):null;
  }
  function getBandHi(engineKey){
    var b=getBucket(engineKey);
    return b&&b.band_max_bps!=null?Number(b.band_max_bps):null;
  }
  var bpsSum=getBps('Aktien')+getBps('Obligationen')+getBps('Immobilien')+getBps('Liquiditaet')+getBps('Alternative');
  if(Math.abs(bpsSum-10000)>50){
    showErr('BPS-Summe '+bpsSum+' weicht zu stark von 10000 ab. Bitte Strategie neu berechnen.');
    return;
  }
  var advRappen=Math.round(Number(alloc.advisory_wealth_rappen||0));
  var riskScoreX10=risk?Number(risk.override_score_x10!=null?risk.override_score_x10:risk.final_score_x10||0):0;
  var riskLabel=risk?(risk.override_profile||risk.final_profile||'Nicht definiert'):'Nicht definiert';
  var body={
    snapshot_date:dateVal,
    advisory_assets_rappen:advRappen,
    risk_profile_score:riskScoreX10,
    risk_profile_label:riskLabel,
    soll_equities_bps:getBps('Aktien'),
    soll_bonds_bps:getBps('Obligationen'),
    soll_real_estate_bps:getBps('Immobilien'),
    soll_liquidity_bps:getBps('Liquiditaet'),
    soll_alternatives_bps:getBps('Alternative'),
    band_equities_lo_bps:getBandLo('Aktien'),
    band_equities_hi_bps:getBandHi('Aktien'),
    band_bonds_lo_bps:getBandLo('Obligationen'),
    band_bonds_hi_bps:getBandHi('Obligationen'),
    band_real_estate_lo_bps:getBandLo('Immobilien'),
    band_real_estate_hi_bps:getBandHi('Immobilien'),
    band_liquidity_lo_bps:getBandLo('Liquiditaet'),
    band_liquidity_hi_bps:getBandHi('Liquiditaet'),
    band_alternatives_lo_bps:getBandLo('Alternative'),
    band_alternatives_hi_bps:getBandHi('Alternative'),
    advisor_note:noteVal
  };
  if(btn){
    btn.disabled=true;
    btn.textContent='Speichert…';
  }
  if(errEl)errEl.style.display='none';
  try{
    await API.post('/mandates/'+mid+'/strategy-snapshots',body);
    cm('m-pu');
    updateStrategyStatus('Strategie-Snapshot gespeichert. PDF wird geöffnet.',false);
    syncPortfolioUmsetzenButtonVisibility();
    if(String(document.body&&document.body.dataset.page||'')==='rv')loadReviewSpiegel(mid);
    printCurrentRubricPdf();
  }catch(e){
    showErr('Speichern fehlgeschlagen: '+(e&&e.detail?e.detail:(e&&e.message?e.message:String(e||'Unbekannter Fehler'))));
  }finally{
    if(btn){
      btn.disabled=false;
      btn.textContent='Strategie festlegen & PDF';
    }
  }
}

// CCX-P4 Allocation-Publish (Vertrag 2026-11-13 §7): Publikationsstatus der
// aktuellen Soll-Allokation -- ausschliesslich Serverwahrheit
// (GET /mandates/{id}/allocation-publication), nie im Browser berechnet.
// "Publizieren" ist nur aktiv, wenn der Server can_publish meldet; sonst steht
// ein kurzer Grund daneben (Owner-UX: nur Erfuellbares anbieten, keine
// Fehlerwand). "Portfolio umsetzen" erscheint erst fuer eine publizierte
// Soll-Allokation.
var allocationPublicationState=null;
var allocationPublicationKey='';
var allocationPublicationLoading=false;
var ALLOCATION_PUBLICATION_REASON_TEXT={
  CCX_ENVELOPE_MISSING:'Empfehlung noch nicht finalisiert (Portfolio › Empfehlung finalisieren)',
  CCX_BINDING_MISSING:'Empfehlung zu dieser Strategie noch nicht finalisiert (Portfolio › Empfehlung finalisieren)',
  CCX_INPUT_STALE:'Daten seit der Finalisierung geändert – bitte neu finalisieren',
  CCX_FRESHNESS_UNKNOWN:'Aktualität nicht belegt – bitte neu finalisieren',
  CCX_RESULT_SUPERSEDED:'Empfehlung wurde neu finalisiert',
  CCX_VALUATION_MISSING:'Bewertung des Bestands fehlt',
  CCX_VALUATION_INCOMPLETE:'Bewertung des Bestands unvollständig',
  CCX_ALLOCATION_SUM_INVALID:'Quoten ergeben nicht 100 %',
  CCX_ALLOCATION_BAND_VIOLATED:'Quote ausserhalb der Bandbreite',
  CCX_ALLOCATION_CONTEXT_INVALID:'Strategiedaten nicht konsistent – bitte neu berechnen',
  CCX_ENVELOPE_HASH_MISMATCH:'Beratungsentscheid nicht integer – bitte neu finalisieren',
  CLIENT_ONBOARDING_INCOMPLETE:'Kundeninformation oder KYC offen',
  FOUR_EYES_REQUIRED:'Freigabe durch eine zweite Person oder Einzelfreigabe als Ein-Personen-Firma nötig'
};
function allocationPublicationReason(code){
  if(!code)return '';
  if(ALLOCATION_PUBLICATION_REASON_TEXT[code])return ALLOCATION_PUBLICATION_REASON_TEXT[code];
  if(/^KYC_/.test(code))return 'KYC-Prüfung offen';
  if(/^SUSTAINABILITY_/.test(code))return 'Nachhaltigkeitspräferenz offen';
  if(/^RISK_/.test(code))return 'Risikoprofil oder Risikobudget offen';
  return 'Freigabevoraussetzung offen';
}
function allocationPublicationTaId(){
  var a=strategyState&&strategyState.allocation;
  return a&&a.target_allocation&&a.target_allocation.id?String(a.target_allocation.id):'';
}
function renderAllocationPublication(){
  var chip=document.getElementById('aa-publication-status');
  var btn=document.getElementById('btn-aa-publish');
  var s=allocationPublicationState;
  var hasTa=!!allocationPublicationTaId();
  if(chip){
    if(!hasTa||!s){chip.textContent='';chip.style.display='none';}
    else{
      var published=s.publication_status==='PUBLISHED';
      var reason=published?'':allocationPublicationReason((s.blocker_codes||[])[0]||(s.active_publication&&s.active_publication.reason_code));
      var single=published&&s.active_publication&&s.active_publication.approval_mode==='single_approver_attested';
      chip.textContent=published?('Publiziert'+(single?' · '+(s.active_publication.approval_mode_label||'Einzelfreigabe (eine berechtigte Person)'):'')):('Entwurf'+(reason&&!s.can_publish?' · '+reason:''));
      chip.title=published?'Diese Soll-Allokation ist freigegeben und publiziert.':'Diese Soll-Allokation ist ein Entwurf und noch nicht kundenwirksam.';
      chip.style.display='';
    }
  }
  if(btn){
    var canPublish=!!(hasTa&&s&&s.can_publish&&s.target_allocation_id===allocationPublicationTaId()&&!(strategyState&&strategyState.dirty));
    btn.style.display=hasTa&&s&&s.publication_status!=='PUBLISHED'?'':'none';
    btn.disabled=!canPublish;
    btn.title=canPublish?'Soll-Allokation freigeben und publizieren':allocationPublicationReason((s&&s.blocker_codes||[])[0])||'Noch nicht publizierbar';
    if(canPublish&&s.prepared_by&&typeof currentUser!=='undefined'&&currentUser&&String(s.prepared_by)===String(currentUser.id))btn.title='Sie haben selbst finalisiert: Freigabe durch eine zweite Person oder, als Ein-Personen-Firma, Einzelfreigabe mit Begründung';
  }
  if(typeof syncFinalizeShortcut==='function')syncFinalizeShortcut(hasTa?s:null);
}
async function refreshAllocationPublication(force){
  var mid=typeof getActiveMandateId==='function'?getActiveMandateId():null;
  var ta=allocationPublicationTaId();
  var key=String(mid||'')+'|'+ta;
  if(!mid||!ta||isDemoMandateId(mid)){allocationPublicationState=null;allocationPublicationKey=key;renderAllocationPublication();return;}
  if(allocationPublicationLoading||(!force&&key===allocationPublicationKey))return;
  allocationPublicationLoading=true;
  try{
    var state=await API.get('/mandates/'+mid+'/allocation-publication');
    if(String(getActiveMandateId()||'')===String(mid)){allocationPublicationState=state;allocationPublicationKey=key;}
  }catch(e){
    allocationPublicationState=null;allocationPublicationKey=key;
  }finally{
    allocationPublicationLoading=false;
  }
  renderAllocationPublication();
  applyPortfolioUmsetzenVisibility();
}
function allocationPublicationErrorCode(e){
  try{var parsed=JSON.parse(e&&e.body||'{}');return parsed&&parsed.detail&&parsed.detail.reason_code||'';}catch(_){return '';}
}
async function publishAllocation(){
  var mid=getActiveMandateId();
  var s=allocationPublicationState;
  if(!mid||!s||!s.can_publish)return;
  var body={target_allocation_id:s.target_allocation_id,validation_hash:s.validation_hash};
  try{
    await API.post('/mandates/'+mid+'/allocation-publication',body);
    updateStrategyStatus('Soll-Allokation publiziert.',false);
  }catch(e){
    if(allocationPublicationErrorCode(e)==='CCX_APPROVAL_BINDING_MISSING'){
      // K2/E2E-02: beide Wege nennen (zweite Person oder Ein-Personen-Firma), advisor-guidance.js.
      await publishFourEyesFlow(mid);
    }else{
      uiAlert({level:'warn',message:'Publizieren nicht möglich: '+allocationPublicationReason(allocationPublicationErrorCode(e))});
    }
  }
  await refreshAllocationPublication(true);
}
function applyPortfolioUmsetzenVisibility(){
  var btn=document.getElementById('btn-portfolio-umsetzen');
  if(!btn)return;
  var visible=!!(strategyState&&strategyState.allocation&&Array.isArray(strategyState.allocation.buckets)&&strategyState.allocation.buckets.length&&!strategyState.dirty
    &&allocationPublicationState&&allocationPublicationState.publication_status==='PUBLISHED'&&allocationPublicationState.target_allocation_id===allocationPublicationTaId());
  btn.style.display=visible?'':'none';
}
