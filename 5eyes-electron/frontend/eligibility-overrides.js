// ELIG-OVERRIDE-UI-001: Produkt-Override beantragen und freigeben, dort wo
// die Eignungsblockade erscheint (Finalisierung des Anlagerezepts, #m-ums).
// Ausgelagert neben den Monolithen (Monolith-Budget, Toleranz 0). Laedt als
// klassisches Skript und nutzt die globalen Helfer des Monolithen (API,
// uiPrompt, uiConfirm, escapeHtml); diese werden erst beim Aufruf aufgeloest.
//
// Backend: routers/eligibility_overrides.py. Antrag (Begruendung >= 20
// Zeichen), Freigabe durch eine zweite Person (Vier-Augen) oder -- nur wenn
// die Verwaltung genau eine freigabeberechtigte Person hat -- Einzelfreigabe
// mit Attestierung (ELIG-OVERRIDE-SINGLE-APPROVER-001), angezeigt als
// "allein attestiert". Keine nativen Dialoge.
var ELIG_OVERRIDE_MISSING_CODE='OVERRIDE_EVIDENCE_MISSING';
var ELIG_OVERRIDE_MIN_REASON=20;
var eligOverrideState={mandateId:null,runId:null,data:null};

function eligOverrideBase(){
  return '/mandates/'+encodeURIComponent(eligOverrideState.mandateId)+'/recommendations/'
    +encodeURIComponent(eligOverrideState.runId)+'/eligibility-overrides';
}

function eligOverrideErrorText(e,fallback){
  var parsed=null;
  try{parsed=e&&e.body?JSON.parse(e.body):null;}catch(parseErr){parsed=null;}
  var detail=parsed&&parsed.detail;
  if(detail&&typeof detail==='object'&&detail.message)return String(detail.message);
  return String((e&&e.detail)||(e&&e.message)||fallback);
}

function eligOverrideIsBlocked(e){
  var text=String((e&&e.body)||'')+' '+String((e&&e.detail)||'')+' '+String((e&&e.message)||'');
  return text.indexOf(ELIG_OVERRIDE_MISSING_CODE)>=0;
}

function eligOverridePanel(){
  var panel=document.getElementById('elig-override-panel');
  if(panel)return panel;
  var anchor=document.getElementById('recipe-status');
  if(!anchor||!anchor.parentNode||!document.createElement)return null;
  panel=document.createElement('div');
  panel.id='elig-override-panel';
  panel.style.marginTop='8px';
  anchor.parentNode.insertBefore(panel,anchor.nextSibling||null);
  return panel;
}

// Beim Oeffnen des Rezepts: keine Anzeige eines frueheren Mandats/Laufs.
function eligOverrideReset(){
  eligOverrideState={mandateId:null,runId:null,data:null};
  var panel=document.getElementById('elig-override-panel');
  if(panel)panel.innerHTML='';
}

// Aufruf aus confirmImplementationRecipe(), wenn Finalize scheitert.
async function eligOverrideOnFinalizeBlocked(mandateId,runId,e){
  if(!mandateId||!runId||!eligOverrideIsBlocked(e))return;
  eligOverrideState={mandateId:String(mandateId),runId:String(runId),data:null};
  await eligOverrideRender();
}

function eligOverrideShowError(message){
  var box=document.getElementById('elig-override-error');
  if(box){box.style.display='block';box.textContent=message;}
}

function eligOverrideRowLabel(row){
  if(row.state==='valid'){
    var mode=row.approval_mode==='single_approver_attested'?'allein attestiert':'Vier-Augen-Freigabe';
    return 'Override gültig bis '+String(row.expires_at||'').slice(0,10)+' ('+mode+')';
  }
  if(row.state==='pending')return 'Antrag offen, Freigabe ausstehend';
  return '';
}

function eligOverrideItemHtml(item,i,data){
  var rows=Array.isArray(item.overrides)?item.overrides:[];
  var valid=rows.filter(function(r){return r.state==='valid';})[0]||null;
  var pendingIndex=-1;
  rows.forEach(function(r,j){if(pendingIndex<0&&r.state==='pending')pendingIndex=j;});
  var html='<div style="border-top:1px solid var(--b1);padding:6px 0">'
    +'<div style="font-size:11px;font-weight:600;color:var(--n8)">'+escapeHtml(item.product_name||item.product_id||'')+'</div>';
  if(valid){
    return html+'<div style="font-size:10px;color:var(--pos)">'+escapeHtml(eligOverrideRowLabel(valid))+'</div></div>';
  }
  if(pendingIndex>=0){
    var pending=rows[pendingIndex];
    html+='<div style="font-size:10px;color:var(--n6)">'+escapeHtml(eligOverrideRowLabel(pending))+'</div>';
    if(String(pending.requested_by)!==String(data.current_user_id)){
      html+='<button class="btn" style="margin-top:4px" onclick="eligOverrideApprove('+i+','+pendingIndex+')">Override freigeben</button>';
    }else if(data.current_user_is_sole_approver===true){
      html+='<button class="btn" style="margin-top:4px" onclick="eligOverrideAttest('+i+','+pendingIndex+')">Allein attestieren</button>';
    }else{
      html+='<div style="font-size:10px;color:var(--n5)">Die Freigabe muss eine andere freigabeberechtigte Person erteilen (Vier-Augen-Prinzip).</div>';
    }
    return html+'</div>';
  }
  return html+'<div style="font-size:10px;color:var(--n6)">Die Eignungsregel verlangt einen dokumentierten Override.</div>'
    +'<button class="btn" style="margin-top:4px" onclick="eligOverrideRequest('+i+')">Override beantragen</button></div>';
}

async function eligOverrideRender(){
  var panel=eligOverridePanel();
  if(!panel||!eligOverrideState.mandateId)return;
  var data;
  try{
    data=await API.get(eligOverrideBase());
  }catch(e){
    panel.innerHTML='<div style="font-size:10px;color:var(--neg)">'+escapeHtml(eligOverrideErrorText(e,'Override-Status konnte nicht geladen werden.'))+'</div>';
    return;
  }
  eligOverrideState.data=data;
  var items=Array.isArray(data&&data.items)?data.items:[];
  if(!items.length){panel.innerHTML='';return;}
  panel.innerHTML='<div style="border:1px solid var(--b1);border-radius:var(--r);padding:8px 10px">'
    +'<div style="font-size:11px;font-weight:600;color:var(--n8);margin-bottom:2px">Produkt-Override erforderlich</div>'
    +'<div style="font-size:10px;color:var(--n5);margin-bottom:4px">Danach das Rezept erneut finalisieren.</div>'
    +items.map(function(item,i){return eligOverrideItemHtml(item,i,data);}).join('')
    +'<div id="elig-override-error" role="alert" style="display:none;font-size:10px;color:var(--neg);margin-top:6px"></div>'
    +'</div>';
}

function eligOverrideItem(i){
  var data=eligOverrideState.data;
  return data&&Array.isArray(data.items)?data.items[i]||null:null;
}

async function eligOverrideRequest(i){
  var item=eligOverrideItem(i);
  if(!item)return;
  var reason=await uiPrompt({
    title:'Override beantragen',
    message:'Begründung für den Override von '+(item.product_name||item.product_id)+' (mindestens '+ELIG_OVERRIDE_MIN_REASON+' Zeichen). Der Antrag wirkt erst nach der Freigabe.',
    required:true,
    minLength:ELIG_OVERRIDE_MIN_REASON,
    okLabel:'Beantragen',
    cancelLabel:'Abbrechen'
  });
  if(reason==null)return;
  try{
    await API.post(eligOverrideBase(),{product_id:item.product_id,reason_text:String(reason).trim(),expected_decision_hash:item.decision_hash});
  }catch(e){
    eligOverrideShowError(eligOverrideErrorText(e,'Override konnte nicht beantragt werden.'));
    return;
  }
  await eligOverrideRender();
}

async function eligOverrideApprove(i,j){
  var item=eligOverrideItem(i);
  var row=item&&item.overrides?item.overrides[j]:null;
  if(!row)return;
  var ok=await uiConfirm({
    title:'Override freigeben',
    message:'Sie geben den Override für '+(item.product_name||item.product_id)+' als zweite Person frei (Vier-Augen-Prinzip).\n\nBegründung des Antrags: '+String(row.reason_text||''),
    okLabel:'Freigeben',
    cancelLabel:'Abbrechen'
  });
  if(ok!==true)return;
  await eligOverrideSubmitApproval(row.id,{});
}

async function eligOverrideAttest(i,j){
  var item=eligOverrideItem(i);
  var row=item&&item.overrides?item.overrides[j]:null;
  if(!row)return;
  var ok=await uiConfirm({
    title:'Allein attestieren',
    message:'Sie sind in dieser Verwaltung die einzige freigabeberechtigte Person. Die Freigabe Ihres eigenen Antrags wird als "allein attestiert" gekennzeichnet und protokolliert.',
    okLabel:'Weiter',
    cancelLabel:'Abbrechen'
  });
  if(ok!==true)return;
  var reason=await uiPrompt({
    title:'Begründung der Einzelfreigabe',
    message:'Warum ist keine zweite Person verfügbar, und was haben Sie selbst geprüft? (mindestens '+ELIG_OVERRIDE_MIN_REASON+' Zeichen)',
    required:true,
    minLength:ELIG_OVERRIDE_MIN_REASON,
    okLabel:'Allein attestieren',
    cancelLabel:'Abbrechen'
  });
  if(reason==null)return;
  await eligOverrideSubmitApproval(row.id,{single_approver_attestation:true,attestation_reason:String(reason).trim()});
}

async function eligOverrideSubmitApproval(overrideId,body){
  try{
    await API.post(eligOverrideBase()+'/'+encodeURIComponent(overrideId)+'/approve',body);
  }catch(e){
    eligOverrideShowError(eligOverrideErrorText(e,'Freigabe fehlgeschlagen.'));
    return;
  }
  await eligOverrideRender();
}
