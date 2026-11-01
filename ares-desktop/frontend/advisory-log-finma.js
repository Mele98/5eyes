// ADVISORY-LOG-FINMA-FIELDS (AUDIT-FIX 2026-11-01): Beratungsprotokoll des
// Monolithen (#m-ne) -- Payload-Bau, Vorbefuellung aus Ereignis-Erfassung /
// Entscheidungsvorlage und Speichern. Ausgelagert aus ares.html (Monolith-
// Budget, Toleranz 0). Laedt als klassisches Skript und nutzt die globalen
// Helfer des Monolithen (API, getInputValue, setInputValue, setSelectValue,
// setCheckboxValue, getCheckboxValue, showModalFeedback, showAppWarn/Error/
// Success, parseApiError, normalizeAdvisoryDecision, inferAdvisoryEntryType,
// refreshReviewUI, renderReviewState, renderSrImplementationDecision, cm, go,
// strategyState, currentReviewState, getActiveMandateId, isDemoMandateId);
// diese werden erst beim Aufruf aufgeloest.
//
// Seit U-FINMA-2.1 (#99)
// verlangt schemas/review.py::AdvisoryLogCreate u. a. entry_datetime,
// duration_minutes, communication_channel, topics (>=1, je >=3 Zeichen),
// cost_disclosure_given und description >= 30 Zeichen. Die drei Monolith-
// Aufrufer (Formular "Protokolleintrag", Ereignis-Erfassung, Entscheidungs-
// vorlage) sendeten diese Felder nie und bekamen 422. Alle drei bauen den
// Payload jetzt NUR noch hier -- und zwar ausschliesslich aus Berater-
// Eingaben bzw. sachlich ableitbaren Werten. Nichts wird aufgefuellt oder
// erfunden: fehlt eine Pflichtangabe, liefert der Builder Fehlertexte statt
// eines Payloads. Nur Felder, die AdvisoryLogCreate kennt (extra="forbid"
// kompatibel). Gespiegelt in tests/test_monolith_advisory_log_finma_fields.py.
var ADVISORY_LOG_ENTRY_TYPES=['Jahresreview','Quartalscheck','Strategie-Anpassung','Override-Entscheid','Ereignis-Reaktion','Drift-Entscheid','Zieländerung','Restriktionsänderung','Initialer Beratungsabschluss','Eignungsprüfung','Sonstiges'];
var ADVISORY_LOG_CHANNELS=['persoenlich','video','telefon','schriftlich','hybrid'];
function parseAdvisoryLogTopics(raw){
  var items=Array.isArray(raw)?raw:String(raw==null?'':raw).split(/[\r\n;]+/);
  var seen={};
  var out=[];
  items.forEach(function(item){
    var t=String(item==null?'':item).trim();
    if(!t)return;
    var key=t.toLowerCase();
    if(seen[key])return;
    seen[key]=true;
    out.push(t);
  });
  return out;
}
// Zeitpunkt des Gespraechs = Datumsfeld + Uhrzeitfeld des Formulars (lokale
// Zeit des Beraters; Uhrzeit beim Oeffnen mit der aktuellen Uhrzeit
// vorbelegt, sichtbar und editierbar). Ausgabe im selben ISO-Format wie der
// React-Editor (YYYY-MM-DDTHH:MM:SS.000Z). Ungueltig -> null.
function advisoryLogEntryDatetimeIso(dateStr,timeStr){
  var dm=/^(\d{4})-(\d{2})-(\d{2})$/.exec(String(dateStr||'').trim());
  var tm=/^(\d{2}):(\d{2})(?::(\d{2}))?$/.exec(String(timeStr||'').trim());
  if(!dm||!tm)return null;
  var y=+dm[1],mo=+dm[2],d=+dm[3],h=+tm[1],mi=+tm[2],se=tm[3]?+tm[3]:0;
  if(h>23||mi>59||se>59)return null;
  var dt=new Date(y,mo-1,d,h,mi,se,0);
  if(isNaN(dt.getTime())||dt.getFullYear()!==y||dt.getMonth()!==mo-1||dt.getDate()!==d)return null;
  return dt.toISOString().replace(/\.\d+Z$/,'.000Z');
}
function buildAdvisoryLogCreatePayload(input){
  input=input||{};
  var errors=[];
  var entryType=String(input.entryType||'').trim();
  var title=String(input.title||'').trim();
  var description=String(input.description||'').trim();
  var contextNotes=(input.contextNotes||[]).map(function(n){return String(n==null?'':n).trim();}).filter(Boolean);
  var topics=parseAdvisoryLogTopics(input.topics);
  var durationRaw=String(input.durationMinutes==null?'':input.durationMinutes).trim();
  var channel=String(input.channel||'').trim();
  var entryDate=String(input.entryDate||'').trim();
  var entryDatetime=advisoryLogEntryDatetimeIso(entryDate,input.entryTime);
  if(ADVISORY_LOG_ENTRY_TYPES.indexOf(entryType)<0)errors.push('Unbekannter Eintragstyp "'+entryType+'".');
  if(title.length<3)errors.push('Anlass / Titel: mindestens 3 Zeichen.');
  else if(title.length>200)errors.push('Anlass / Titel: höchstens 200 Zeichen.');
  if(description.length<30)errors.push('Gesprächsinhalt / Begründung: mindestens 30 Zeichen (FINMA-Nachvollziehbarkeit), aktuell '+description.length+'.');
  if(!entryDatetime)errors.push('Datum und Uhrzeit des Gesprächs angeben.');
  if(!/^\d+$/.test(durationRaw)||+durationRaw<1||+durationRaw>600)errors.push('Dauer des Gesprächs in Minuten angeben (1–600).');
  if(ADVISORY_LOG_CHANNELS.indexOf(channel)<0)errors.push('Kommunikationskanal wählen.');
  if(!topics.length)errors.push('Mindestens ein Thema angeben.');
  else if(topics.some(function(t){return t.length<3;}))errors.push('Jedes Thema muss mindestens 3 Zeichen lang sein.');
  else if(topics.length>20)errors.push('Höchstens 20 Themen.');
  if(typeof input.costDisclosureGiven!=='boolean')errors.push('Angabe zur Ex-ante-Kostenkommunikation fehlt.');
  var fullDescription=contextNotes.length?contextNotes.concat([description]).join(' | '):description;
  if(fullDescription.length>20000)errors.push('Gesprächsinhalt zu lang (max. 20000 Zeichen).');
  if(errors.length)return {ok:false,errors:errors,payload:null};
  return {ok:true,errors:[],payload:{
    entry_type:entryType,
    title:title,
    description:fullDescription,
    decision:input.decision||null,
    trigger_id:input.triggerId||null,
    recommendation_run_id:input.recommendationRunId||null,
    entry_date:entryDate,
    entry_datetime:entryDatetime,
    duration_minutes:+durationRaw,
    communication_channel:channel,
    language:'de',
    topics:topics,
    cost_disclosure_given:input.costDisclosureGiven
  }};
}
// Ereignis-Erfassung: sachlich ableitbar sind nur Eintragstyp, Titel, Thema
// (= der gewaehlte Ereignistyp), Ereignisdatum, gewaehlte Massnahme und die
// vom Berater selbst getippten Details. Dauer, Kanal, Kostenangabe und
// Gespraechszeitpunkt sind es NICHT -> das Protokollformular wird damit
// vorbefuellt geoeffnet und der Berater ergaenzt den Rest.
function buildEventAdvisoryLogPrefill(ev){
  ev=ev||{};
  var typ=String(ev.type||'').trim();
  var notes=[];
  if(ev.eventDate)notes.push('Ereignisdatum: '+ev.eventDate);
  if(ev.actionLabel)notes.push('Massnahme: '+ev.actionLabel);
  return {
    origin:'event',
    entryType:/ziel/i.test(typ)?'Zieländerung':'Ereignis-Reaktion',
    title:'Ereignis: '+typ,
    description:String(ev.details||'').trim(),
    contextNotes:notes,
    topics:typ?[typ]:[],
    decision:ev.action==='document'?'Kein Handlungsbedarf':null,
    triggerId:ev.triggerId||null,
    resolveTrigger:false,
    afterSave:ev.action||null,
    notice:'Ereignis "'+typ+'" übernommen'+(ev.triggerId?' (Review-Trigger angelegt)':'')+'. Für den Protokolleintrag fehlen noch Gesprächsinhalt, Uhrzeit, Dauer, Kanal und die Angabe zur Kostenkommunikation. Ohne Speichern wird KEIN Protokolleintrag angelegt.'
  };
}
// Entscheidungsvorlage (Drift): Vorlagentext ist KEIN Gespraechsinhalt --
// er geht als Kontext ("Vorlage: ...") in die Beschreibung, die >= 30
// Zeichen muss der Berater selbst schreiben.
function buildDecisionTemplateAdvisoryLogPrefill(meta,triggerId){
  meta=meta||{};
  return {
    origin:'decision-template',
    entryType:'Drift-Entscheid',
    title:'Entscheidungsvorlage – '+String(meta.title||''),
    description:'',
    contextNotes:meta.detail?['Vorlage: '+meta.detail]:[],
    topics:['Portfolio-Drift'],
    decision:meta.decision||null,
    triggerId:triggerId||null,
    resolveTrigger:true,
    afterSave:null,
    notice:'Vorlage "'+String(meta.title||'')+'" übernommen. Bitte Gesprächsinhalt (Kundenposition, Argumente), Uhrzeit, Dauer, Kanal und die Angabe zur Kostenkommunikation ergänzen. Ohne Speichern wird KEIN Protokolleintrag angelegt.'
  };
}
// ReviewTriggerResolve.decision kennt nur Erledigt / Massnahme eingeleitet /
// Kein Handlungsbedarf / Vertagt (schemas/review.py::ReviewTriggerDecision).
// Vorher wurden Protokoll-Entscheide bzw. Vorlagentitel direkt gesendet -> 422.
function advisoryDecisionToTriggerDecision(decision){
  var d=String(decision||'');
  if(d==='Kein Handlungsbedarf')return 'Kein Handlungsbedarf';
  if(d==='Transaktion empfohlen'||d==='Strategie angepasst'||d==='Profil angepasst')return 'Massnahme eingeleitet';
  return 'Erledigt';
}

// Vorbefuellung des Protokollformulars aus Ereignis-Erfassung bzw.
// Entscheidungsvorlage (siehe openAdvisoryLogModalPrefilled). null = normales,
// leeres Formular.
var advisoryLogPrefill=null;

// Teil von resetAdvisoryLogModal(): Datum + Uhrzeit (lokal, jetzt; sichtbar und
// editierbar) und die FINMA-Pflichtfelder leeren -- keine Vorauswahl.
function resetAdvisoryLogFinmaFields(){
  var nowLocal=new Date();
  var pad2=function(n){return (n<10?'0':'')+n;};
  setInputValue('ne-date',nowLocal.getFullYear()+'-'+pad2(nowLocal.getMonth()+1)+'-'+pad2(nowLocal.getDate()));
  setInputValue('ne-time',pad2(nowLocal.getHours())+':'+pad2(nowLocal.getMinutes()));
  setInputValue('ne-duration','');
  setSelectValue('ne-channel','');
  setInputValue('ne-topics','');
  setCheckboxValue('ne-cost',false);
  setInputValue('ne-entry-type','');
  var ctx=document.getElementById('ne-context');
  if(ctx){ctx.style.display='none';ctx.textContent='';}
}

// Aus cleanupModalAfterClose('m-ne'): ein vorbefuellter Protokolleintrag
// (Ereignis / Entscheidungsvorlage), der ohne Speichern geschlossen wird, darf
// nie unbemerkt fehlen -> dauerhafter Hinweis.
function advisoryLogCloseCheck(){
  var neModal=document.getElementById('m-ne');
  if(neModal)delete neModal.dataset.locked;
  var pending=advisoryLogPrefill;
  advisoryLogPrefill=null;
  if(pending&&!pending.saved){
    var what=pending.origin==='event'?'Das Ereignis':'Der Entscheid aus der Vorlage';
    var msg=what+' wurde NICHT im Beratungsprotokoll erfasst ("'+pending.title+'").'
      +(pending.origin==='event'&&pending.triggerId?' Der Review-Trigger ist angelegt, der Protokolleintrag fehlt.':'')
      +' Bitte über "Entscheid protokollieren" nachholen.';
    try{showAppWarn(msg,{title:'Protokolleintrag fehlt',durationMs:0});}catch(noticeErr){}
  }
}

// ADVISORY-LOG-FINMA-FIELDS: oeffnet das Protokollformular mit den sachlich
// ableitbaren Werten (buildEventAdvisoryLogPrefill /
// buildDecisionTemplateAdvisoryLogPrefill). Der Rest bleibt leer und wird
// vom Builder als Pflichtangabe eingefordert. Backdrop-Klick schliesst das
// Formular nicht (data-locked), damit der Entwurf nicht still verschwindet.
function openAdvisoryLogModalPrefilled(prefill){
  var hidden=document.getElementById('ne-trigger-id');
  if(hidden)hidden.value=prefill.triggerId||'';
  resetAdvisoryLogModal();
  advisoryLogPrefill=Object.assign({saved:false},prefill);
  setInputValue('ne-entry-type',prefill.entryType||'');
  setInputValue('ne-title',prefill.title||'');
  setInputValue('ne-description',prefill.description||'');
  setInputValue('ne-topics',(prefill.topics||[]).join('\n'));
  var sel=document.getElementById('ne-decision');
  if(sel){
    var dv=prefill.decision||'';
    var has=Array.prototype.some.call(sel.options,function(o){return o.value===dv;});
    if(!has){var opt=document.createElement('option');opt.value=dv;opt.textContent=dv;sel.appendChild(opt);}
    sel.value=dv;
  }
  var ctx=document.getElementById('ne-context');
  if(ctx){
    var lines=[prefill.notice||''].concat((prefill.contextNotes||[]).map(function(n){return 'Wird übernommen: '+n;}));
    ctx.textContent=lines.filter(Boolean).join(' · ');
    ctx.style.display='';
  }
  var modal=document.getElementById('m-ne');
  if(modal){modal.dataset.locked='1';modal.classList.add('open');}
}

async function saveAdvisoryLogEntry(){
  var prefill=advisoryLogPrefill;
  var title=getInputValue('ne-title').trim();
  // "Noch offen – kein Entscheid" (value '') -> decision null statt eines
  // stillschweigend unterstellten "Keine Transaktion".
  var decisionRaw=getInputValue('ne-decision');
  var decision=decisionRaw?normalizeAdvisoryDecision(decisionRaw):null;
  var triggerId=getInputValue('ne-trigger-id')||null;
  var btn=document.getElementById('btn-ne-save');
  var mid=getActiveMandateId();
  var currentRunId=(strategyState&&strategyState.recommendation&&strategyState.recommendation.run
    ?strategyState.recommendation.run.id:null)||null;
  var contextNotes=(prefill&&prefill.contextNotes?prefill.contextNotes.slice():[]);
  if(decisionRaw&&decisionRaw!==decision)contextNotes.push('Operative Ausprägung: '+decisionRaw);
  var built=buildAdvisoryLogCreatePayload({
    entryType:getInputValue('ne-entry-type')||inferAdvisoryEntryType(title,decision),
    title:title,
    description:getInputValue('ne-description'),
    contextNotes:contextNotes,
    decision:decision,
    triggerId:triggerId,
    recommendationRunId:currentRunId,
    entryDate:getInputValue('ne-date'),
    entryTime:getInputValue('ne-time'),
    durationMinutes:getInputValue('ne-duration'),
    channel:getInputValue('ne-channel'),
    topics:getInputValue('ne-topics'),
    costDisclosureGiven:getCheckboxValue('ne-cost')
  });
  if(!built.ok){
    showModalFeedback('ne-error',btn,'Bitte ergänzen: '+built.errors.join(' '),true);
    if(btn)btn.textContent='Speichern';
    return;
  }
  var payload=built.payload;
  var resolveTrigger=!!payload.trigger_id&&!(prefill&&prefill.resolveTrigger===false);
  var afterSave=prefill?prefill.afterSave:null;
  function runAfterSave(){
    if(afterSave==='risk')go('rp');
    if(afterSave==='goals')go('cf');
  }
  if(btn){btn.disabled=true;btn.textContent='Speichern...';}
  if(mid&&!isDemoMandateId(mid)){
    try{
      await API.post('/mandates/'+mid+'/advisory-log',payload);
      if(prefill)prefill.saved=true;
      var triggerResolveFailed=false;
      var triggerResolveErr=null;
      if(resolveTrigger){
        try{
          await API.put('/mandates/'+mid+'/triggers/'+payload.trigger_id+'/resolve',
            {decision:advisoryDecisionToTriggerDecision(payload.decision),triggered_notes:payload.title});
        }catch(e){
          triggerResolveFailed=true;
          triggerResolveErr=e;
          console.warn('Trigger-Resolve:',e);
        }
      }
      await refreshReviewUI(mid);
      renderSrImplementationDecision(null);
      if(triggerResolveFailed){
        var trigErrMsg='Protokolleintrag wurde gespeichert, aber der Compliance-Trigger konnte NICHT als erledigt markiert werden ('+parseApiError(triggerResolveErr,'unbekannter Fehler')+'). Bitte erneut versuchen oder eskalieren.';
        showModalFeedback('ne-error',btn,'⚠ '+trigErrMsg,true);
        try{showAppError(trigErrMsg,{title:'Compliance-Trigger nicht aufgelöst'});}catch(noticeErr){}
      } else {
        showModalFeedback('ne-error',btn,'✓ Protokolleintrag gespeichert',false);
        try{showAppSuccess('Protokolleintrag gespeichert',{title:'Review-Entscheid dokumentiert'});}catch(noticeErr){}
        setTimeout(function(){cm('m-ne');runAfterSave();},500);
      }
    }catch(e){
      var alErr='Fehler: '+(e.detail||e.message||'?');
      showModalFeedback('ne-error',btn,alErr,true);
      try{showAppError(alErr,{title:'Protokolleintrag nicht gespeichert'});}catch(noticeErr){}
    }
  } else {
    if(prefill)prefill.saved=true;
    currentReviewState.logs=[Object.assign({id:'demo-log-'+Date.now(),status:'Empfohlen'},payload)].concat(currentReviewState.logs||[]);
    if(resolveTrigger){
      currentReviewState.triggers=(currentReviewState.triggers||[]).map(function(trigger){
        if(String(trigger.id||'')!==String(payload.trigger_id))return trigger;
        return Object.assign({},trigger,{status:'Erledigt',triggered_notes:payload.title});
      });
    }
    renderReviewState(currentReviewState);
    renderSrImplementationDecision(currentReviewState.logs[0]||null);
    showModalFeedback('ne-error',btn,'✓ Demo-Modus: Eintrag ergänzt',false);
    setTimeout(function(){cm('m-ne');runAfterSave();},700);
  }
}
