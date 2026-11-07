// E2 Nachhaltigkeitspraeferenzen (Dok. 106, Entscheid E0): Kundenmaske direkt
// nach dem Risikoprofil (Customer Journey). Ausgelagert aus ares.html
// (Monolith-Budget, Toleranz 0); klassisches synchrones Skript nach
// risk-questionnaire-v2.js, nutzt die globalen Helfer des Monolithen erst
// beim Aufruf. Im Monolithen nur die Einbindung.
//
// Texte, Optionen, Version und Definitions-Hash liefert der Server
// (GET /sustainability-preferences/definition, Quelle
// core/sustainability_preference.py). Keine Vorauswahl, keine Wirkung auf den
// Risikoscore und keine Engine-Wirkung. Das Ergebnis heisst "erfasste
// Nachhaltigkeitspraeferenz"; Produkte/Portfolio werden nie als nachhaltig
// bezeichnet (Claim-Waechter). Ausschlusswuensche wirken als Untergrenze der
// Strategiebausteine (Server: 422 beim Generieren); harte Ausschluesse sind
// bis E4/E5 gesperrt. Abgelaufene Review-Frist (Hauspolitik) -> Hinweis
// "Eignungspruefung faellig", kein Sperren.
var SUST={definition:null,defRequested:false,state:null,mandateId:null,busy:false};

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
  return null;
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

function sustRadio(name,value,label){
  return '<label style="display:flex;gap:7px;align-items:flex-start;margin:4px 0;font-size:11px;color:var(--n7);cursor:pointer">'
    +'<input type="radio" name="'+name+'" value="'+sustEsc(value)+'" style="margin-top:2px"> <span>'+sustEsc(label)+'</span></label>';
}

function sustRender(){
  var card=sustCard();
  var def=SUST.definition;
  if(!card||!def)return;
  var q1=sustQuestion('esg_relevance')||{options:[]};
  var q2=sustQuestion('esg_characteristic')||{options:[]};
  var q3=sustQuestion('exclusions')||{options:[]};
  var st=SUST.state||{};
  var html='<div class="chd"><span class="cht" id="sust-title">Nachhaltigkeitspräferenzen</span>'
    +'<span style="font-size:9px;color:var(--n4)">nach dem Risikoprofil · verändert das Risikoprofil nicht</span></div>'
    +'<div class="cbody">'
    +'<div id="sust-review" role="status" style="display:none;margin-bottom:10px" class="al-banner-warning"></div>'
    +'<div id="sust-result" style="display:none;margin-bottom:12px;padding:10px 12px;border:1px solid var(--b1);border-radius:var(--r2);background:var(--bg2,var(--bg))"></div>'
    +'<p style="font-size:11px;line-height:1.55;color:var(--n6);margin:0 0 6px">'+sustEsc(def.intro_text)+'</p>'
    +'<p style="font-size:10.5px;line-height:1.5;color:var(--n5);margin:0 0 10px">'+sustEsc(def.information_text)+'</p>'
    +'<div id="sust-errors" role="alert" tabindex="-1" style="display:none;margin-bottom:8px;padding:8px 10px;border:1px solid var(--neg);border-radius:var(--r);font-size:11px;color:var(--neg)"></div>'
    +'<fieldset id="sust-q1" style="border:0;padding:0;margin:0 0 10px"><legend style="font-size:11.5px;font-weight:600;color:var(--n8);margin-bottom:4px">1 · '+sustEsc(q1.text)+'</legend>';
  (q1.options||[]).forEach(function(o){html+=sustRadio('sust-q1',o.value,o.label);});
  html+=sustRadio('sust-q1','declined',q1.declined_label||'Keine Angabe')+'</fieldset>'
    +'<div id="sust-yes-block" style="display:none">'
    +'<fieldset id="sust-q2" style="border:0;padding:0;margin:0 0 10px"><legend style="font-size:11.5px;font-weight:600;color:var(--n8);margin-bottom:4px">2 · '+sustEsc(q2.text)+'</legend>';
  (q2.options||[]).forEach(function(o){html+=sustRadio('sust-q2',o.value,o.label);});
  html+='</fieldset><fieldset id="sust-q3" style="border:0;padding:0;margin:0 0 10px"><legend style="font-size:11.5px;font-weight:600;color:var(--n8);margin-bottom:4px">3 · '+sustEsc(q3.text)+'</legend>'
    +'<div style="display:flex;flex-wrap:wrap;gap:4px 14px">';
  (q3.options||[]).forEach(function(o){
    html+='<label style="font-size:11px;color:var(--n7);display:inline-flex;gap:5px;align-items:center;cursor:pointer">'
      +'<input type="checkbox" class="sust-excl" value="'+sustEsc(o.value)+'"> '+sustEsc(o.label)+'</label>';
  });
  html+='</div><label style="display:flex;gap:6px;align-items:flex-start;margin-top:8px;font-size:10.5px;color:var(--n5)">'
    +'<input type="checkbox" id="sust-hard" disabled aria-describedby="sust-hard-note"> <span>Als harten, am Produkt belegten Ausschluss vereinbaren (gesperrt)</span></label>'
    +'<div id="sust-hard-note" style="font-size:10px;color:var(--n5);line-height:1.45;margin:2px 0 0 20px">'+sustEsc(st.hard_exclusion_locked_note||def.hard_exclusion_locked_note)+'</div>'
    +'<div id="sust-waivers" style="display:none;margin-top:8px"></div>'
    +'</fieldset></div>'
    +'<label style="display:flex;gap:7px;align-items:flex-start;margin:6px 0;font-size:11px;color:var(--n7)"><input type="checkbox" id="sust-info"> <span>Information zu Nachhaltigkeitspräferenzen (SDGs, ESG-Faktoren, Grenzen der Aussage) abgegeben und zur Kenntnis genommen</span></label>'
    +'<label style="display:flex;gap:7px;align-items:flex-start;margin:6px 0;font-size:11px;color:var(--n7)"><input type="checkbox" id="sust-confirm"> <span>Die Kundin bzw. der Kunde hat die Angaben bestätigt</span></label>'
    +'<div style="display:flex;justify-content:space-between;align-items:center;gap:10px;margin-top:10px;flex-wrap:wrap">'
    +'<span id="sust-policy" style="font-size:10px;color:var(--n5)">'+sustEsc(st.review_policy_label||'')+'</span>'
    +'<button type="button" class="btn-g" id="btn-sust-save">Nachhaltigkeitspräferenzen speichern</button></div>'
    +'</div>';
  card.innerHTML=html;
  card.querySelectorAll('input[name="sust-q1"],.sust-excl').forEach(function(el){el.addEventListener('change',sustSyncVisibility);});
  var btn=document.getElementById('btn-sust-save');
  if(btn)btn.addEventListener('click',function(){sustSave();});
  sustHydrate(st.current);
  sustShowState();
}

// Neue Version startet mit den Antworten der aktuellen (Kundenangaben, keine
// Vorauswahl durch Ares); Information und Bestaetigung sind je Version neu.
function sustHydrate(cur){
  if(!cur)return;
  var q1=cur.response_status==='declined'?'declined':cur.esg_relevance;
  var pick=function(name,value){
    var el=value&&document.querySelector('#sust-card input[name="'+name+'"][value="'+value+'"]');
    if(el)el.checked=true;
  };
  pick('sust-q1',q1);
  pick('sust-q2',cur.esg_characteristic);
  document.querySelectorAll('#sust-card .sust-excl').forEach(function(cb){
    cb.checked=(cur.exclusions||[]).indexOf(cb.value)>=0;
  });
  sustSyncVisibility();
}

function sustValue(name){
  var el=document.querySelector('input[name="'+name+'"]:checked');
  return el?el.value:null;
}

function sustSelectedExclusions(){
  var out=[];
  document.querySelectorAll('#sust-card .sust-excl').forEach(function(cb){if(cb.checked)out.push(cb.value);});
  return out;
}

function sustExclusionLabel(key){
  var q3=sustQuestion('exclusions')||{options:[]};
  for(var i=0;i<q3.options.length;i++){if(q3.options[i].value===key)return q3.options[i].label;}
  return key;
}

function sustSyncVisibility(){
  var yes=sustValue('sust-q1')==='yes';
  var block=document.getElementById('sust-yes-block');
  if(block)block.style.display=yes?'':'none';
  var box=document.getElementById('sust-waivers');
  var st=SUST.state||{};
  if(!box)return;
  var excl=yes?sustSelectedExclusions():[];
  if(!st.waiver_allowed||!excl.length){box.style.display='none';return;}
  var keep={};
  box.querySelectorAll('input.sust-waiver').forEach(function(i){keep[i.dataset.key]=i.value;});
  var html='<div style="font-size:10.5px;color:var(--n6);margin-bottom:4px">Kundenverzicht (nur Anlageberatung, optional): Begründung, falls die Kundin bzw. der Kunde auf einen Ausschluss verzichtet (mind. 20 Zeichen).</div>';
  excl.forEach(function(key){
    html+='<input class="fi sust-waiver" data-key="'+sustEsc(key)+'" maxlength="2000" aria-label="Kundenverzicht '+sustEsc(sustExclusionLabel(key))+'" placeholder="Verzicht '+sustEsc(sustExclusionLabel(key))+' – Begründung" value="'+sustEsc(keep[key]||'')+'" style="width:100%;margin-bottom:4px">';
  });
  box.innerHTML=html;
  box.style.display='';
}

function sustShowState(){
  var st=SUST.state;
  var result=document.getElementById('sust-result');
  var review=document.getElementById('sust-review');
  var policy=document.getElementById('sust-policy');
  if(policy&&st)policy.textContent=st.review_policy_label||'';
  if(review){
    review.style.display=st&&st.review_status==='due'&&st.review_notice?'':'none';
    review.textContent=st&&st.review_notice?st.review_notice:'';
  }
  if(!result)return;
  var cur=st&&st.current;
  if(!cur){result.style.display='none';result.innerHTML='';return;}
  var limits=(cur.limit_texts||[]).map(function(t){return '<li>'+sustEsc(t)+'</li>';}).join('');
  var excl=(cur.exclusions||[]).map(sustExclusionLabel).join(', ');
  result.innerHTML='<div style="font-size:9px;text-transform:uppercase;letter-spacing:0.06em;color:var(--n4);margin-bottom:3px">Erfasste Nachhaltigkeitspräferenz</div>'
    +'<div id="sust-result-text" style="font-size:11.5px;color:var(--n8);line-height:1.5">'+sustEsc(cur.profile_text)+'</div>'
    +(excl?'<div style="font-size:10.5px;color:var(--n6);margin-top:4px">Ausschlusswünsche: '+sustEsc(excl)+'</div>':'')
    +(limits?'<ul style="margin:6px 0 0 16px;padding:0;font-size:10.5px;color:var(--n6);line-height:1.45">'+limits+'</ul>':'')
    +'<div style="font-size:9.5px;color:var(--n4);margin-top:6px">Version '+sustEsc(cur.sequence_no)+' · '+sustEsc(cur.questionnaire_version)
    +' · erfasst '+sustEsc(String(cur.captured_at||'').slice(0,10))+' · Bestätigung '+(cur.client_confirmed?'erfolgt':'ausstehend')
    +' · Überprüfung bis '+sustEsc(cur.review_due_on)+'</div>';
  result.style.display='';
}

function sustErrors(list){
  var box=document.getElementById('sust-errors');
  if(!box)return;
  if(!list.length){box.style.display='none';box.innerHTML='';return;}
  box.innerHTML='<strong>Bitte prüfen:</strong><ul style="margin:4px 0 0 16px;padding:0">'
    +list.map(function(m){return '<li>'+sustEsc(m)+'</li>';}).join('')+'</ul>';
  box.style.display='';
  try{box.focus();}catch(e){}
}

function sustCollect(){
  var errors=[];
  var q1=sustValue('sust-q1');
  var body={
    questionnaire_version:SUST.definition.questionnaire_version,
    definition_hash:SUST.definition.definition_hash,
    response_status:q1==='declined'?'declined':'answered',
    esg_relevance:q1&&q1!=='declined'?q1:null,
    esg_characteristic:null,exclusions:[],waivers:{},hard_exclusion_requested:false,
    information_acknowledged:!!(document.getElementById('sust-info')||{}).checked,
    client_confirmed:!!(document.getElementById('sust-confirm')||{}).checked,
    expected_current_id:SUST.state&&SUST.state.current?SUST.state.current.id:null
  };
  if(!q1)errors.push('Frage 1 beantworten (oder «Keine Angabe» wählen).');
  if(q1==='yes'){
    body.esg_characteristic=sustValue('sust-q2');
    if(!body.esg_characteristic)errors.push('Frage 2 beantworten.');
    body.exclusions=sustSelectedExclusions();
    document.querySelectorAll('#sust-waivers input.sust-waiver').forEach(function(i){
      var t=String(i.value||'').trim();
      if(t)body.waivers[i.dataset.key]=t;
    });
  }
  if(!body.information_acknowledged)errors.push('Information zur Kenntnisnahme bestätigen.');
  return {body:body,errors:errors};
}

function sustSave(){
  var mid=sustMandateId();
  if(SUST.busy||!SUST.definition||!sustIsRealMandate(mid))return Promise.resolve(null);
  var c=sustCollect();
  sustErrors(c.errors);
  if(c.errors.length)return Promise.resolve(null);
  SUST.busy=true;
  var btn=document.getElementById('btn-sust-save');
  if(btn)btn.disabled=true;
  return Promise.resolve().then(function(){
    return API.post('/mandates/'+encodeURIComponent(mid)+'/sustainability-preferences',c.body);
  }).then(function(state){
    SUST.state=state;SUST.mandateId=mid;
    sustErrors([]);sustRender();
    if(btn)btn.disabled=false;
    return state;
  }).catch(function(e){
    sustErrors([(e&&e.detail)||(e&&e.message)||'Speichern fehlgeschlagen.']);
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

function sustLoad(mid){
  if(!sustIsRealMandate(mid)){
    var old=document.getElementById('sust-card');if(old)old.style.display='none';
    return Promise.resolve(null);
  }
  return sustLoadDefinition().then(function(def){
    if(!def)return null;
    return API.get('/mandates/'+encodeURIComponent(mid)+'/sustainability-preferences').then(function(state){
      if(String(sustMandateId()||'')!==String(mid))return null;
      SUST.state=state;SUST.mandateId=mid;
      sustRender();
      var card=document.getElementById('sust-card');if(card)card.style.display='';
      return state;
    });
  }).catch(function(e){console.warn('Nachhaltigkeitspräferenzen:',e);return null;});
}

// E3: Kundenausschluesse als Untergrenze im Block Strategiebausteine sichtbar
// machen (Herkunft "Kundenpraeferenz"); der Server prueft verbindlich.
function sustActiveExclusions(){
  var cur=SUST.state&&SUST.state.current;
  if(!cur||String(SUST.mandateId||'')!==String(sustMandateId()||''))return [];
  var waived=cur.waived_exclusions||[];
  return (cur.exclusions||[]).filter(function(k){return waived.indexOf(k)<0;});
}

function sustApplyFloorToStrategyBlocks(){
  var active=sustActiveExclusions();
  ['fossil','defense','tobacco','alcohol','gaming','nuclear'].forEach(function(key){
    var sel=document.getElementById('aa-tilt-'+key);
    if(!sel)return;
    var badge=document.getElementById('sust-floor-'+key);
    var on=active.indexOf(key)>=0;
    if(on&&!badge&&sel.parentNode){
      badge=document.createElement('span');
      badge.id='sust-floor-'+key;
      badge.className='tag';
      badge.textContent='Kundenpräferenz';
      badge.title='Ausschlusswunsch aus den Nachhaltigkeitspräferenzen: Untergrenze «Ausschliessen/Untergewichten»; Lockern nur mit dokumentiertem Kundenverzicht.';
      badge.style.cssText='margin-left:4px;font-size:9px';
      sel.parentNode.insertBefore(badge,sel.nextSibling);
    }
    if(badge)badge.style.display=on?'':'none';
    if(on&&sel.value!=='exclude'&&sel.value!=='underweight'){
      sel.value='exclude';
      try{sel.dispatchEvent(new Event('change',{bubbles:true}));}catch(e){}
    }
  });
}

var _sustBaseLoadRisk=null;
var _sustBaseOpenPrefs=null;
function sustInstallWrappers(){
  if(typeof loadCurrentRiskAssessment==='function'&&!_sustBaseLoadRisk){
    _sustBaseLoadRisk=loadCurrentRiskAssessment;
    loadCurrentRiskAssessment=function(mid,renderUi){
      var p=_sustBaseLoadRisk.apply(this,arguments);
      if(renderUi)sustLoad(mid);
      return p;
    };
  }
  if(typeof openAllocationPreferencesModal==='function'&&!_sustBaseOpenPrefs){
    _sustBaseOpenPrefs=openAllocationPreferencesModal;
    openAllocationPreferencesModal=function(){
      var r=_sustBaseOpenPrefs.apply(this,arguments);
      var mid=sustMandateId();
      if(sustIsRealMandate(mid)&&String(SUST.mandateId||'')!==String(mid))sustLoad(mid).then(sustApplyFloorToStrategyBlocks);
      else sustApplyFloorToStrategyBlocks();
      return r;
    };
  }
}

sustInstallWrappers();
