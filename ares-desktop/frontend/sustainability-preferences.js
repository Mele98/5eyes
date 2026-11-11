// E2a Nachhaltigkeitspraeferenzen im Risikoprofil-Flow (Dok. 106, Codex-
// Vertrag E2, Owner-Vorgaben 2026-11-08). Ausgelagerter Monolith-Teil
// (Budget-Toleranz 0), klassisches Skript als letzter Teil; nutzt die
// globalen Helfer des Monolithen erst beim Aufruf.
//
// Ablauf: zuerst nur Frage 1 (Ja / Nicht relevant / Keine Angabe). Nur bei
// "Ja" folgen Merkmal, Ausschlusswuensche, Verzicht (nur Anlageberatung) und
// Kenntnisnahme. Texte, Optionen, Version und Definitions-Hash liefert der
// Server (eine Quelle, Claim-Waechter-geprueft); welche Ausschluesse waehlbar
// sind, entscheidet der Server (nur Erfuellbares, sonst ausgegraut mit Grund).
// Keine Vorauswahl, kein Entwurf ueber Mandatsgrenzen, keine Wirkung auf
// Risikoprofil oder Strategie. Zustand (nicht erfasst / keine Praeferenz /
// keine Angabe / Praeferenz / Verzicht / veraltet) kommt vom Server.
var SUST={definition:null,defRequested:false,state:null,mandateId:null,busy:false,loadSeq:0};

function sustEsc(v){
  return String(v==null?'':v).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function sustMandateId(){
  try{return typeof getActiveMandateId==='function'?getActiveMandateId():null;}catch(e){return null;}
}

function sustIsRealMandate(mid){
  return !!mid&&!(typeof isDemoMandateId==='function'&&isDemoMandateId(mid));
}

function sustQuestion(key){
  var qs=(SUST.definition&&SUST.definition.questions)||[];
  for(var i=0;i<qs.length;i++){if(qs[i].key===key)return qs[i];}
  return {options:[]};
}

function sustCard(){
  var card=document.getElementById('sust-card');
  if(card)return card;
  var page=document.getElementById('page-rp');
  if(!page)return null;
  card=document.createElement('section');
  card.id='sust-card';
  card.className='card';
  card.setAttribute('aria-labelledby','sust-title');
  card.style.cssText='margin:0 24px 14px';
  var nav=page.querySelector(':scope > .cnav');
  if(nav)page.insertBefore(card,nav);else page.appendChild(card);
  return card;
}

var SUST_LBL='display:flex;gap:7px;align-items:flex-start;margin:4px 0;font-size:11px;color:var(--n7);cursor:pointer';
var SUST_LEG='font-size:11.5px;font-weight:600;color:var(--n8);margin-bottom:4px';
var SUST_FS='border:0;padding:0;margin:0 0 10px';

function sustRadio(name,value,label,id){
  return '<label style="'+SUST_LBL+'" for="'+id+'"><input type="radio" id="'+id+'" name="'+name+'" value="'+sustEsc(value)+'" style="margin-top:2px"> <span>'+sustEsc(label)+'</span></label>';
}

function sustExclusionOptions(){
  return (SUST.state&&SUST.state.exclusion_options)||[];
}

function sustRender(){
  var card=sustCard();
  var def=SUST.definition;
  if(!card||!def)return;
  var q1=sustQuestion('esg_relevance'),q2=sustQuestion('esg_characteristic'),q3=sustQuestion('exclusions'),q4=sustQuestion('preference_waived');
  var st=SUST.state||{};
  var html='<div class="chd"><span class="cht" id="sust-title" role="heading" aria-level="2">Nachhaltigkeitspräferenzen</span>'
    +'<span style="font-size:9px;color:var(--n5)">nach dem Risikoprofil · verändert das Risikoprofil nicht</span></div>'
    +'<div class="cbody">'
    +'<div id="sust-state" role="status" aria-live="polite" style="margin-bottom:10px;font-size:11px;color:var(--n7)"></div>'
    +'<div id="sust-result" style="display:none;margin-bottom:12px;padding:10px 12px;border:1px solid var(--b1);border-radius:var(--r2);background:var(--bg2,var(--bg))"></div>'
    +'<p style="font-size:11px;line-height:1.55;color:var(--n6);margin:0 0 10px">'+sustEsc(def.intro_text)+'</p>'
    +'<div id="sust-errors" role="alert" tabindex="-1" style="display:none;margin-bottom:8px;padding:8px 10px;border:1px solid var(--neg);border-radius:var(--r);font-size:11px;color:var(--neg)"></div>'
    +'<fieldset id="sust-q1" style="'+SUST_FS+'"><legend style="'+SUST_LEG+'">'+sustEsc(q1.text)+'</legend>';
  (q1.options||[]).forEach(function(o){html+=sustRadio('sust-q1',o.value,o.label,'sust-q1-'+o.value);});
  html+=sustRadio('sust-q1','declined',q1.declined_label||'Keine Angabe','sust-q1-declined')+'</fieldset>'
    +'<div id="sust-yes-block" hidden>'
    +'<p id="sust-info-text" style="font-size:10.5px;line-height:1.5;color:var(--n6);margin:0 0 10px">'+sustEsc(def.information_text)+'</p>'
    +'<fieldset id="sust-q2" style="'+SUST_FS+'"><legend style="'+SUST_LEG+'">'+sustEsc(q2.text)+'</legend>';
  (q2.options||[]).forEach(function(o){html+=sustRadio('sust-q2',o.value,o.label,'sust-q2-'+o.value);});
  html+='</fieldset><fieldset id="sust-q3" style="'+SUST_FS+'"><legend style="'+SUST_LEG+'">'+sustEsc(q3.text)+'</legend>';
  sustExclusionOptions().forEach(function(o){
    var id='sust-excl-'+o.key,why='sust-excl-why-'+o.key;
    html+='<div style="margin:3px 0"><label for="'+id+'" style="font-size:11px;color:'+(o.available?'var(--n7)':'var(--n5)')+';display:inline-flex;gap:6px;align-items:center;cursor:'+(o.available?'pointer':'not-allowed')+'">'
      +'<input type="checkbox" class="sust-excl" id="'+id+'" value="'+sustEsc(o.key)+'"'+(o.available?'':' disabled aria-describedby="'+why+'"')+'> '+sustEsc(o.label)+'</label>'
      +(o.available?'':' <span id="'+why+'" style="font-size:10px;color:var(--n6)">'+sustEsc(o.reason||'')+'</span>')+'</div>';
  });
  html+='</fieldset>';
  if(st.waiver_allowed){
    html+='<fieldset id="sust-q4" style="'+SUST_FS+'"><legend style="'+SUST_LEG+'">'+sustEsc(q4.text)+'</legend>'
      +'<label style="'+SUST_LBL+'" for="sust-waiver"><input type="checkbox" id="sust-waiver"> <span>'+sustEsc(def.waiver_text)+'</span></label>'
      +'<div id="sust-waiver-box" hidden><label for="sust-waiver-reason" style="font-size:10.5px;color:var(--n6)">Begründung des Verzichts (mind. 20 Zeichen)</label>'
      +'<textarea class="fi" id="sust-waiver-reason" maxlength="2000" rows="2" style="width:100%"></textarea></div></fieldset>';
  }
  html+='<label style="'+SUST_LBL+'" for="sust-info"><input type="checkbox" id="sust-info" aria-describedby="sust-info-text"> <span>Information zur Kenntnis genommen</span></label>'
    +'</div>'
    +'<div id="sust-finish" hidden>'
    +'<div style="display:flex;gap:8px;align-items:center;margin:8px 0;flex-wrap:wrap"><label for="sust-channel" style="font-size:11px;color:var(--n7)">Erhebungskanal</label>'
    +'<select class="fsel" id="sust-channel"><option value="">Bitte wählen</option>';
  Object.keys(def.capture_channels||{}).forEach(function(k){html+='<option value="'+sustEsc(k)+'">'+sustEsc(def.capture_channels[k])+'</option>';});
  html+='</select></div>'
    +'<label style="'+SUST_LBL+'" for="sust-confirm"><input type="checkbox" id="sust-confirm"> <span>Die Kundin bzw. der Kunde hat die Angaben bestätigt</span></label>'
    +'<div style="display:flex;justify-content:space-between;align-items:center;gap:10px;margin-top:10px;flex-wrap:wrap">'
    +'<span id="sust-policy" style="font-size:10px;color:var(--n6)"></span>'
    +'<button type="button" class="btn-g" id="btn-sust-save">Nachhaltigkeitspräferenzen speichern</button></div>'
    +'</div></div>';
  card.innerHTML=html;
  card.querySelectorAll('input[name="sust-q1"],#sust-waiver').forEach(function(el){el.addEventListener('change',sustSyncVisibility);});
  var btn=document.getElementById('btn-sust-save');
  if(btn)btn.addEventListener('click',function(){sustSave();});
  sustSyncVisibility();
  sustShowState();
}

function sustValue(name){
  var el=document.querySelector('#sust-card input[name="'+name+'"]:checked');
  return el?el.value:null;
}

function sustChecked(id){
  return !!(document.getElementById(id)||{}).checked;
}

function sustSelectedExclusions(){
  var out=[];
  document.querySelectorAll('#sust-card .sust-excl').forEach(function(cb){if(cb.checked&&!cb.disabled)out.push(cb.value);});
  return out;
}

function sustSyncVisibility(){
  var q1=sustValue('sust-q1');
  var yes=document.getElementById('sust-yes-block');
  if(yes)yes.hidden=q1!=='yes';
  var finish=document.getElementById('sust-finish');
  if(finish)finish.hidden=!q1;
  var box=document.getElementById('sust-waiver-box');
  if(box)box.hidden=!sustChecked('sust-waiver');
}

function sustShowState(){
  var st=SUST.state;
  var stateBox=document.getElementById('sust-state');
  var policy=document.getElementById('sust-policy');
  if(policy)policy.textContent=st?st.review_policy_label||'':'';
  if(stateBox){
    stateBox.dataset.state=st?st.state:'';
    stateBox.innerHTML=st?'<strong>Zustand: '+sustEsc(st.state_label)+'</strong>'+(st.state_notice?' · '+sustEsc(st.state_notice):''):'';
    stateBox.className=st&&(st.state==='stale'||st.state==='unreadable')?'al-banner-warning':'';
  }
  var result=document.getElementById('sust-result');
  if(!result)return;
  var cur=st&&st.current;
  if(!cur){result.style.display='none';result.innerHTML='';return;}
  var limits=(cur.limit_texts||[]).map(function(t){return '<li>'+sustEsc(t)+'</li>';}).join('');
  var ch=(SUST.definition&&SUST.definition.capture_channels)||{};
  result.innerHTML='<div style="font-size:9px;text-transform:uppercase;letter-spacing:0.06em;color:var(--n5);margin-bottom:3px">Erfasste Nachhaltigkeitspräferenz</div>'
    +'<div id="sust-result-text" style="font-size:11.5px;color:var(--n8);line-height:1.5">'+sustEsc(cur.profile_text)+'</div>'
    +(cur.preference_waived?'<div style="font-size:10.5px;color:var(--n6);margin-top:4px">Verzicht dokumentiert (Anlageberatung).</div>':'')
    +(limits?'<ul style="margin:6px 0 0 16px;padding:0;font-size:10.5px;color:var(--n6);line-height:1.45">'+limits+'</ul>':'')
    +'<div style="font-size:9.5px;color:var(--n6);margin-top:6px">Version '+sustEsc(cur.sequence_no)+' · '+sustEsc(cur.questionnaire_version)
    +' · erfasst '+sustEsc(String(cur.captured_at||'').slice(0,10))+' · '+sustEsc(ch[cur.capture_channel]||cur.capture_channel)
    +' · Überprüfung bis '+sustEsc(cur.review_due_on)+'</div>';
  result.style.display='';
}

// Fehlerzusammenfassung: jede Meldung verlinkt das betroffene Feld; Fokus
// auf die Zusammenfassung, aria-invalid an den Feldern.
function sustErrors(list){
  var box=document.getElementById('sust-errors');
  document.querySelectorAll('#sust-card [aria-invalid="true"]').forEach(function(el){el.removeAttribute('aria-invalid');});
  if(!box)return;
  if(!list.length){box.style.display='none';box.innerHTML='';return;}
  box.innerHTML='<strong id="sust-errors-title">Bitte prüfen:</strong><ul style="margin:4px 0 0 16px;padding:0">'
    +list.map(function(e){
      if(e.field){var f=document.getElementById(e.field);if(f)f.setAttribute('aria-invalid','true');}
      return '<li>'+(e.field?'<a href="#'+sustEsc(e.field)+'" data-sust-field="'+sustEsc(e.field)+'" style="color:inherit">'+sustEsc(e.text)+'</a>':sustEsc(e.text))+'</li>';
    }).join('')+'</ul>';
  box.style.display='';
  box.querySelectorAll('a[data-sust-field]').forEach(function(a){
    a.addEventListener('click',function(ev){
      ev.preventDefault();
      var f=document.getElementById(a.getAttribute('data-sust-field'));
      var target=f&&(f.matches('input,select,textarea')?f:f.querySelector('input:not([disabled]),select,textarea'));
      if(target)try{target.focus();}catch(e){}
    });
  });
  try{box.focus();}catch(e){}
}

function sustCollect(){
  var errors=[];
  var q1=sustValue('sust-q1');
  var yes=q1==='yes';
  var waived=yes&&sustChecked('sust-waiver');
  var body={
    questionnaire_version:SUST.definition.questionnaire_version,
    definition_hash:SUST.definition.definition_hash,
    response_status:q1==='declined'?'declined':'answered',
    esg_relevance:q1&&q1!=='declined'?q1:null,
    esg_characteristic:yes?sustValue('sust-q2'):null,
    exclusions:yes?sustSelectedExclusions():[],
    preference_waived:waived,
    waiver_reason:waived?String((document.getElementById('sust-waiver-reason')||{}).value||'').trim():null,
    information_acknowledged:yes&&sustChecked('sust-info'),
    client_confirmed:sustChecked('sust-confirm'),
    capture_channel:(document.getElementById('sust-channel')||{}).value||'',
    expected_current_id:SUST.state&&SUST.state.current?SUST.state.current.id:null
  };
  if(!q1)errors.push({field:'sust-q1',text:'Frage 1 beantworten (Ja, Nicht relevant oder Keine Angabe).'});
  if(yes&&!body.esg_characteristic)errors.push({field:'sust-q2',text:'Merkmal wählen.'});
  if(waived&&String(body.waiver_reason||'').length<20)errors.push({field:'sust-waiver-reason',text:'Begründung des Verzichts mit mindestens 20 Zeichen angeben.'});
  if(waived&&body.exclusions.length)errors.push({field:'sust-q3',text:'Verzicht und Ausschlusswünsche schliessen sich aus.'});
  if(yes&&!body.information_acknowledged)errors.push({field:'sust-info',text:'Kenntnisnahme der Information bestätigen.'});
  if(q1&&!body.capture_channel)errors.push({field:'sust-channel',text:'Erhebungskanal wählen.'});
  if(q1&&!body.client_confirmed)errors.push({field:'sust-confirm',text:'Bestätigung durch die Kundin bzw. den Kunden dokumentieren.'});
  return {body:body,errors:errors};
}

function sustServerError(e){
  var d=e&&e.detail;
  var msg=(d&&typeof d==='object'?d.message:d)||(e&&e.message)||'Speichern fehlgeschlagen.';
  var extra=d&&typeof d==='object'&&d.detail?' ('+d.detail+')':'';
  return {text:msg+extra};
}

function sustSave(){
  var mid=sustMandateId();
  if(SUST.busy||!SUST.definition||!sustIsRealMandate(mid)||String(SUST.mandateId||'')!==String(mid))return Promise.resolve(null);
  var c=sustCollect();
  sustErrors(c.errors);
  if(c.errors.length)return Promise.resolve(null);
  SUST.busy=true;
  var btn=document.getElementById('btn-sust-save');
  if(btn)btn.disabled=true;
  return Promise.resolve().then(function(){
    return API.post('/mandates/'+encodeURIComponent(mid)+'/sustainability-preferences',c.body);
  }).then(function(state){
    if(String(sustMandateId()||'')!==String(mid))return null;
    SUST.state=state;SUST.mandateId=mid;
    sustRender();
    return state;
  }).catch(function(e){
    if(String(sustMandateId()||'')===String(mid))sustErrors([sustServerError(e)]);
    return null;
  }).then(function(r){SUST.busy=false;var b=document.getElementById('btn-sust-save');if(b)b.disabled=false;return r;});
}

function sustLoadDefinition(){
  if(SUST.definition||SUST.defRequested||typeof API==='undefined'||!API)return Promise.resolve(SUST.definition);
  SUST.defRequested=true;
  return Promise.resolve().then(function(){return API.get('/sustainability-preferences/definition');})
    .then(function(d){SUST.definition=d||null;return SUST.definition;})
    .catch(function(){SUST.defRequested=false;return null;});
}

// Mandatswechsel: Karte sofort leeren und verbergen (kein Zustand, keine
// Antwort und kein Entwurf des vorigen Mandats), erst die Antwort fuer genau
// dieses Mandat rendert neu. Spaete Antworten anderer Mandate verfallen.
function sustLoad(mid){
  var seq=++SUST.loadSeq;
  SUST.state=null;SUST.mandateId=null;
  var old=document.getElementById('sust-card');
  if(old){old.innerHTML='';old.style.display='none';}
  if(!sustIsRealMandate(mid))return Promise.resolve(null);
  return sustLoadDefinition().then(function(def){
    if(!def)return null;
    return API.get('/mandates/'+encodeURIComponent(mid)+'/sustainability-preferences').then(function(state){
      if(seq!==SUST.loadSeq||String(sustMandateId()||'')!==String(mid))return null;
      SUST.state=state;SUST.mandateId=mid;
      sustRender();
      var card=document.getElementById('sust-card');if(card)card.style.display='';
      return state;
    });
  }).catch(function(e){console.warn('Nachhaltigkeitspräferenzen:',e);return null;});
}

var _sustBaseLoadRisk=null;
function sustInstallWrappers(){
  if(typeof loadCurrentRiskAssessment==='function'&&!_sustBaseLoadRisk){
    _sustBaseLoadRisk=loadCurrentRiskAssessment;
    loadCurrentRiskAssessment=function(mid,renderUi){
      var p=_sustBaseLoadRisk.apply(this,arguments);
      if(renderUi)sustLoad(mid);
      return p;
    };
  }
}

sustInstallWrappers();
