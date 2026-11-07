// H5 Risikoprofil (Dok. 105, Entscheide E1-E7): Ergaenzungen der Risikoprofil-
// Maske. Ausgelagert aus ares.html (Monolith-Budget, Toleranz 0); wird als
// klassisches synchrones Skript direkt nach goal-review-runtime.js geladen und
// nutzt die globalen Helfer des Monolithen erst beim Aufruf.
//
// Fragen 1-11 bleiben wortgleich und mit ihren Punkten unveraendert (Owner-
// Regel: Risikoprofil nach Vorlage, kein UX-Refactoring). Dieses Modul ergaenzt
// nur die beschlossenen Teile im Stil der bestehenden Fragen.
//
// H5a: Fussnote zu Frage 10 (Bandbreite ~80 % ueber ein Jahr). Rein textlich,
// ohne Score-Wirkung. Wortgleich zu services/pdf/components/eignungspruefung.py
// (Q10_BAND_FOOTNOTE); test_frontend_risk_questionnaire_v2.py prueft die Paritaet.
var RISK_Q10_BAND_FOOTNOTE='Hinweis zu Frage 10: Die genannte Bandbreite umfasst rund 80 % der zu '
  +'erwartenden Wertentwicklungen innerhalb eines Jahres. Mit je rund 10 % '
  +'Wahrscheinlichkeit fällt das Ergebnis besser bzw. schlechter aus – ein '
  +'Verlust kann also auch grösser sein als die untere Grenze der Bandbreite.';

function riskV2Sections(){
  return document.querySelectorAll('#r-rb .qsec');
}

function riskV2AddQ10Footnote(){
  var q10=riskV2Sections()[1];
  if(!q10||q10.querySelector('.rp-q10-note'))return;
  var note=document.createElement('div');
  note.className='rp-q10-note';
  note.style.cssText='padding-left:24px;margin-top:6px;font-size:9.5px;line-height:1.45;color:var(--n5)';
  note.textContent=RISK_Q10_BAND_FOOTNOTE;
  q10.appendChild(note);
}

riskV2AddQ10Footnote();

// ── H5b: Fragebogen v2 (hinter Feature-Flag, Default aus) ───────────────────
// Fragen 12-14 und der Q11-Knock-out kappen nur die Risikobereitschaft (nie
// anheben): will_v2 = MIN(will_core, Kappungen), final = MIN(Faehigkeit,
// will_v2). Texte, Optionen und Grenzwerte liefert der Server
// (GET /risk-questionnaire/policy); ohne Freigabe (v2_enabled=false) bleibt die
// Maske exakt beim Standard-Fragebogen (v1) und der Payload unveraendert.
// Konsistenz-Flags K1-K5 (K6 erst mit P11) aendern das Profil nie und
// blockieren nichts, verlangen aber eine Beraternotiz.
var RISK_V2={policy:null,requested:false,lastSaved:null,inBase:false};
var RISK_V2_GROWTH_PROFILES=['Wachstumsorientiert','Dynamisch','Aktien'];
var RISK_V2_Q12_PCT=[5,10,20,20];

function riskV2Active(){
  return !!(RISK_V2.policy&&RISK_V2.policy.v2_enabled===true&&Array.isArray(RISK_V2.policy.questions));
}

function riskV2LoadPolicy(){
  if(RISK_V2.requested||typeof API==='undefined'||!API||typeof API.get!=='function')return;
  RISK_V2.requested=true;
  Promise.resolve().then(function(){return API.get('/risk-questionnaire/policy');}).then(function(p){
    RISK_V2.policy=p||null;
    riskV2Render();
    if(RISK_V2.lastSaved)riskV2Hydrate(RISK_V2.lastSaved);
    if(typeof calcRiskScore==='function')calcRiskScore();
  }).catch(function(){RISK_V2.requested=false;});
}

function riskV2Esc(v){
  return String(v==null?'':v).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function riskV2Render(){
  var rb=document.getElementById('r-rb');
  if(!rb)return;
  var block=document.getElementById('rp-v2-block');
  if(!riskV2Active()){
    if(block)block.style.display='none';
    return;
  }
  if(!block){
    block=document.createElement('div');
    block.id='rp-v2-block';
    block.style.cssText='margin-top:14px';
    var html='';
    RISK_V2.policy.questions.forEach(function(q){
      html+='<div class="qsec" id="rp-v2-q'+q.number+'"><div class="ql"><span class="qnum">'+q.number+'</span><span>'
        +riskV2Esc(q.text)+'</span></div><div class="qopts">';
      q.options.forEach(function(opt,i){
        html+='<div class="qopt" onclick="sq(this,\'q'+q.number+'\')"><div class="qrad"></div><span class="qtxt">'
          +riskV2Esc(opt)+'</span>'+(q.number===12?'<em class="rp-v2-amt" data-idx="'+i+'" style="margin-left:6px;font-size:9.5px;color:var(--n5)"></em>':'')+'</div>';
      });
      html+='</div></div>';
    });
    html+='<div id="rp-v2-cap-info" style="display:none;margin:8px 0 0 24px;font-size:10px;line-height:1.45;color:var(--n6)"></div>'
      +'<div id="rp-v2-consistency" style="display:none;margin:10px 0 0 24px;padding:9px 11px;border:1px dashed var(--b1);border-radius:var(--r)">'
      +'<div style="font-weight:600;font-size:10.5px;color:var(--n8);margin-bottom:4px">Konsistenzhinweise (ändern das Profil nicht)</div>'
      +'<div id="rp-v2-flags" style="font-size:10px;line-height:1.45;color:var(--n6)"></div>'
      +'<label style="display:block;margin-top:7px;font-size:10px;color:var(--n7)">Beraternotiz zum Gespräch (Pflicht)'
      +'<textarea id="rp-v2-note" rows="3" oninput="riskAssessmentUiDirty=true" style="display:block;width:100%;margin-top:4px;font-size:10.5px"></textarea></label></div>';
    block.innerHTML=html;
    rb.appendChild(block);
  }
  block.style.display='';
  riskV2UpdateAmounts();
}

function riskV2FormatAmount(chf){
  var n=Math.round(Number(chf)||0);
  if(typeof fmtLocaleCH==='function')return fmtLocaleCH(n);
  return String(n).replace(/\B(?=(\d{3})+(?!\d))/g,"'");
}

function riskV2AdvisoryChf(){
  try{
    var snap=typeof currentAllocationInputSnapshot==='function'?currentAllocationInputSnapshot():null;
    var rappen=snap?Number(snap.advisoryRappen||0):0;
    return rappen>0?rappen/100:0;
  }catch(e){return 0;}
}

function riskV2Currency(){
  return (typeof currentMandateData!=='undefined'&&currentMandateData&&currentMandateData.base_currency)||'CHF';
}

function riskV2AmountSuffix(idx){
  var total=riskV2AdvisoryChf();
  if(!(total>0)||idx<0||idx>3)return '';
  var cur=riskV2Currency();
  return (idx<3?'bis':'über')+' ca. '+cur+' '+riskV2FormatAmount(total*RISK_V2_Q12_PCT[idx]/100)
    +' bei '+cur+' '+riskV2FormatAmount(total)+' Anlagebetrag';
}

function riskV2UpdateAmounts(){
  var sec=document.getElementById('rp-v2-q12');
  if(!sec)return;
  sec.querySelectorAll('.rp-v2-amt').forEach(function(el){
    var sfx=riskV2AmountSuffix(Number(el.getAttribute('data-idx')));
    el.textContent=sfx?'('+sfx+')':'';
  });
}

function riskV2SelectedIndex(q){
  var sec=document.getElementById('rp-v2-q'+q);
  if(!sec)return -1;
  var opts=Array.prototype.slice.call(sec.querySelectorAll('.qopt'));
  for(var i=0;i<opts.length;i++){if(opts[i].classList.contains('sel'))return i;}
  return -1;
}

function riskV2Caps(policy,behavPoints,opts){
  var caps=[], ko=policy.q11_knockout||{};
  if(behavPoints===ko.q_risk_behavior_points)caps.push({source:'Q11',option_index:behavPoints-1,max_score_x10:ko.max_score_x10});
  policy.questions.forEach(function(q){
    var m=q.max_score_x10[opts[q.number]];
    if(m<100)caps.push({source:'Q'+q.number,option_index:opts[q.number],max_score_x10:m});
  });
  var cap=100;
  caps.forEach(function(c){cap=Math.min(cap,c.max_score_x10);});
  return {caps:caps,cap:cap};
}

function riskV2InstrumentDocumented(instruments,row){
  var v=instruments&&instruments[row];
  return !!(v&&(v.known===1||v.experienced===1||v.informed===1));
}

function riskV2Flags(policy,q9,q10,q11,q13,effectiveProfile,instruments){
  var flags=[];
  if(q9===1&&q10>=3)flags.push('K1');
  if(q10>=3&&q11<=2)flags.push('K2');
  if(Math.max(q9,q10,q11)-Math.min(q9,q10,q11)>=2)flags.push('K3');
  var growth=RISK_V2_GROWTH_PROFILES.indexOf(effectiveProfile)>=0;
  if(growth&&q13===policy.q13_not_invested_option)flags.push('K4');
  if(growth&&!riskV2InstrumentDocumented(instruments,'Aktien'))flags.push('K5');
  return flags;
}

function riskV2NoteText(){
  var el=document.getElementById('rp-v2-note');
  return el?String(el.value||'').replace(/\s+/g,' ').trim():'';
}

function riskV2NoteOk(){
  var t=riskV2NoteText(), min=(RISK_V2.policy&&RISK_V2.policy.consistency_note_min_chars)||20;
  return t.length>=min&&t.split(' ').length>=3;
}

function riskV2Evaluate(result){
  var policy=RISK_V2.policy, opts={}, complete=true;
  policy.questions.forEach(function(q){opts[q.number]=riskV2SelectedIndex(q.number);if(opts[q.number]<0)complete=false;});
  if(!complete)return {complete:false,opts:opts};
  var p=result.payload, core=result.willScore;
  var c=riskV2Caps(policy,p.q_risk_behavior_points,opts);
  var effective=Math.min(core,c.cap);
  var instruments={};
  try{instruments=JSON.parse(p.knowledge_instruments_json||'{}');}catch(e){}
  var flags=riskV2Flags(policy,p.q_investment_goal_points,p.q_risk_preference_points,p.q_risk_behavior_points,
    opts[13],riskWillingnessProfile(effective),instruments);
  return {complete:true,opts:opts,core:core,cap:c.cap,caps:c.caps,effective:effective,flags:flags};
}

function riskV2ApplyToResult(result,v2){
  var policy=RISK_V2.policy, p=result.payload;
  p.questionnaire_version='v2';
  p.questionnaire_v2_answers=policy.questions.map(function(q){
    var label=q.options[v2.opts[q.number]];
    var sfx=q.number===12?riskV2AmountSuffix(v2.opts[12]):'';
    return {question_number:q.number,answer_label:sfx?label+' · '+sfx:label};
  });
  p.consistency_note=riskV2NoteText()||null;
  result.v2=v2;
  result.willScore=v2.effective;
  result.willProfile=riskWillingnessProfile(v2.effective);
  var fin=Math.min(result.capScore,v2.effective);
  var mt=(typeof currentMandateData!=='undefined'&&currentMandateData&&currentMandateData.mandate_type)||null;
  if(mt==='FZK')fin=Math.min(fin,75);
  result.finalScore=fin;
  result.finalProfile=riskScoreToProfile(fin);
  return result;
}

function riskV2RenderStatus(v2){
  var info=document.getElementById('rp-v2-cap-info');
  var box=document.getElementById('rp-v2-consistency');
  var list=document.getElementById('rp-v2-flags');
  var binding=v2&&v2.complete?v2.caps.filter(function(c){return c.max_score_x10<v2.core;}):[];
  if(info){
    info.style.display=binding.length?'':'none';
    info.textContent=binding.length?'Begrenzung der Risikobereitschaft auf höchstens «'
      +riskWillingnessProfile(v2.effective)+'» durch: '+binding.map(function(c){
        return 'Frage '+c.source.slice(1);}).join(', ')+'.':'';
  }
  var flags=v2&&v2.complete?v2.flags:[];
  if(box)box.style.display=flags.length?'':'none';
  if(list){
    var msgs={};
    ((RISK_V2.policy&&RISK_V2.policy.consistency_flags)||[]).forEach(function(f){msgs[f.code]=f.message;});
    list.innerHTML=flags.map(function(code){return '<div>'+riskV2Esc(code+': '+(msgs[code]||''))+'</div>';}).join('');
  }
}

function riskV2Hydrate(saved){
  RISK_V2.lastSaved=saved||null;
  var note=document.getElementById('rp-v2-note');
  if(note)note.value=(saved&&saved.questionnaire_version==='v2'&&saved.consistency_note)||'';
  if(!saved||saved.questionnaire_version!=='v2'||!saved.willingness_v2_json)return;
  var ev={};
  try{ev=JSON.parse(saved.willingness_v2_json)||{};}catch(e){return;}
  (ev.answers||[]).forEach(function(row){
    var sec=document.getElementById('rp-v2-q'+row.question_number);
    if(!sec)return;
    Array.prototype.slice.call(sec.querySelectorAll('.qopt')).forEach(function(o,i){
      o.classList[i===row.option_index?'add':'remove']('sel');
    });
  });
}

function riskV2Issues(){
  if(!riskV2Active())return [];
  var issues=[];
  RISK_V2.policy.questions.forEach(function(q){
    if(riskV2SelectedIndex(q.number)<0)issues.push('Frage '+q.number+': '+String(q.text).split(' – ')[0]);
  });
  if(!issues.length){
    var r=riskV2BaseResult();
    var v2=r?riskV2Evaluate(r):null;
    if(v2&&v2.complete&&v2.flags.length&&!riskV2NoteOk())issues.push('Beraternotiz zu den Konsistenzhinweisen');
  }
  return issues;
}

// Der Basis-Builder ruft collectRiskAssessmentUiIssues(state) selbst auf; dort
// duerfen die v2-Hinweise nicht greifen (sonst Rekursion bzw. Vorschau leer).
function riskV2BaseResult(args){
  RISK_V2.inBase=true;
  try{return _riskV2BaseBuild.apply(null,args||[]);}finally{RISK_V2.inBase=false;}
}

var _riskV2BaseBuild=null, _riskV2BaseIssues=null, _riskV2BaseSave=null, _riskV2BaseHydrate=null;

// Spaete Overrides (wie goal-review-runtime.js): die Laufzeitfunktionen des
// Monolithen werden umhuellt; Aufrufer im Monolithen loesen den Namen erst beim
// Aufruf auf. Fehlt eine Funktion (Harness), bleibt sie unberuehrt.
function riskV2InstallWrappers(){
  if(typeof buildRiskAssessmentPayloadFromUI==='function'&&!_riskV2BaseBuild){
    _riskV2BaseBuild=buildRiskAssessmentPayloadFromUI;
    buildRiskAssessmentPayloadFromUI=function(){
      var result=riskV2BaseResult(arguments);
      if(!result||!riskV2Active())return result;
      var v2=riskV2Evaluate(result);
      riskV2RenderStatus(v2);
      if(!v2.complete)return null;
      return riskV2ApplyToResult(result,v2);
    };
  }
  if(typeof collectRiskAssessmentUiIssues==='function'&&!_riskV2BaseIssues){
    _riskV2BaseIssues=collectRiskAssessmentUiIssues;
    collectRiskAssessmentUiIssues=function(){
      var base=_riskV2BaseIssues.apply(this,arguments);
      return RISK_V2.inBase?base:base.concat(riskV2Issues());
    };
  }
  if(typeof saveRiskProfile==='function'&&!_riskV2BaseSave){
    _riskV2BaseSave=saveRiskProfile;
    saveRiskProfile=function(){
      if(riskV2Issues().length){
        showRiskSaveFeedback(formatRiskAssessmentIssues(collectRiskAssessmentUiIssues()),true);
        return Promise.resolve(false);
      }
      return _riskV2BaseSave.apply(this,arguments);
    };
  }
  if(typeof hydrateRiskQuestionnaire==='function'&&!_riskV2BaseHydrate){
    _riskV2BaseHydrate=hydrateRiskQuestionnaire;
    hydrateRiskQuestionnaire=function(saved){
      var out=_riskV2BaseHydrate.apply(this,arguments);
      riskV2LoadPolicy();
      riskV2UpdateAmounts();
      riskV2Hydrate(saved);
      riskKeLegacyHint(saved);
      return out;
    };
  }
}

riskV2InstallWrappers();

// ── H5c: Kenntnisse und Erfahrung getrennt (Angemessenheit, Art. 11 FIDLEG) ──
// Rein dokumentarisch, kein Score. Beide Tabellen (Fragen 1 und 2) erhalten die
// Spalte "Erfahrung vorhanden" (data-col="experienced"); die Instrumentliste
// wird um die Kategorien ergaenzt, die Ares allokieren oder empfehlen kann.
// Fragetexte bleiben unveraendert. Altprofile tragen den Schluessel
// "experienced" nicht: ihr Wert bleibt unveraendert gespeichert (keine
// Umschreibung gebundener Evidenz); die Maske weist darauf hin, dass
// "Kenntnisse vorhanden" dort Kenntnisse und Erfahrung gemeinsam umfasste.
// Zeilenschluessel (data-row) = services/knowledge_asset_class_gap.py
// QUESTIONNAIRE_INSTRUMENT_ROWS (Paritaetstest).
var RISK_KE_EXPERIENCE_HEADER='Erfahrung vorhanden';
var RISK_KE_EXTRA_INSTRUMENTS=[
  ['ETF','Börsengehandelte Indexfonds (ETF)'],
  ['Strukturierte Produkte','Strukturierte Produkte / Zertifikate'],
  ['Derivate','Derivate (Optionen, Futures, Optionsscheine)'],
  ['Alternative Anlagen','Alternative Anlagen (Hedgefonds, Liquid Alternatives)'],
  ['Private Equity','Private Equity / Private Markets'],
  ['Rohstoffe','Rohstoffe'],
  ['Fremdwährungsanlagen','Fremdwährungsanlagen']
];
var RISK_KE_CHECK_STYLE='accent-color:var(--g4);width:14px;height:14px;cursor:pointer';
var RISK_KE_LEGACY_HINT='Altbestand: «Kenntnisse vorhanden» umfasste bisher Kenntnisse und Erfahrung gemeinsam. '
  +'Bitte die Erfahrung getrennt bestätigen; der gespeicherte Stand bleibt unverändert.';

function riskKeCell(style,child,text){
  var d=document.createElement('div');
  d.style.cssText=style;
  if(child)d.appendChild(child);
  if(text)d.textContent=text;
  return d;
}

function riskKeCheckbox(cls,row,col){
  var cb=document.createElement('input');
  cb.type='checkbox';
  cb.className=cls;
  cb.setAttribute('data-row',row);
  cb.setAttribute('data-col',col);
  cb.style.cssText=RISK_KE_CHECK_STYLE;
  return cb;
}

function riskKeInsertAfter(parent,node,ref){
  var next=ref.nextSibling;
  if(next)parent.insertBefore(node,next);else parent.appendChild(node);
}

function riskKeInputs(cls,col){
  return Array.prototype.slice.call(document.querySelectorAll('input.'+cls)).filter(function(cb){
    return cb.getAttribute('data-col')===col;
  });
}

function riskKeExtendTable(cls,extraRows){
  var known=riskKeInputs(cls,'known');
  if(!known.length)return;
  var grid=known[0].parentNode.parentNode;
  if(!grid||grid.getAttribute('data-ke-ext')==='1')return;
  grid.setAttribute('data-ke-ext','1');
  grid.style.gridTemplateColumns='1fr 110px 110px 110px';
  var hdr=grid.children[1];
  if(hdr)riskKeInsertAfter(grid,riskKeCell(hdr.style.cssText,null,RISK_KE_EXPERIENCE_HEADER),hdr);
  known.forEach(function(cb){
    var cell=cb.parentNode;
    riskKeInsertAfter(grid,riskKeCell(cell.style.cssText,riskKeCheckbox(cls,cb.getAttribute('data-row'),'experienced')),cell);
  });
  if(!extraRows.length)return;
  var border='1px solid var(--b1)';
  var cells=grid.children;
  for(var i=Math.max(0,cells.length-4);i<cells.length;i++)cells[i].style.borderBottom=border;
  var ck='padding:7px 8px;text-align:center;border-bottom:'+border+';border-left:'+border;
  extraRows.forEach(function(r,idx){
    var last=idx===extraRows.length-1;
    var c=last?'padding:7px 8px;text-align:center;border-left:'+border:ck;
    grid.appendChild(riskKeCell('padding:7px 8px;color:var(--n8)'+(last?'':';border-bottom:'+border),null,r[1]));
    ['known','experienced','informed'].forEach(function(col){
      grid.appendChild(riskKeCell(c,riskKeCheckbox(cls,r[0],col)));
    });
  });
}

function riskKeHasLegacyRows(raw){
  var tbl={};
  try{tbl=JSON.parse(raw||'{}')||{};}catch(e){return false;}
  var rows=Object.keys(tbl);
  return rows.length>0&&rows.some(function(r){
    return tbl[r]&&typeof tbl[r]==='object'&&!('experienced' in tbl[r])&&Number(tbl[r].known)===1;
  });
}

function riskKeLegacyHint(saved){
  var known=riskKeInputs('ke-ins','known');
  var grid=known.length?known[0].parentNode.parentNode:null;
  if(!grid||!grid.parentNode)return;
  var hint=document.getElementById('rp-ke-legacy-hint');
  if(!hint){
    hint=document.createElement('div');
    hint.id='rp-ke-legacy-hint';
    hint.style.cssText='margin-top:6px;font-size:9.5px;line-height:1.45;color:var(--n5)';
    hint.textContent=RISK_KE_LEGACY_HINT;
    grid.parentNode.appendChild(hint);
  }
  var legacy=!!saved&&(riskKeHasLegacyRows(saved.knowledge_services_json)||riskKeHasLegacyRows(saved.knowledge_instruments_json));
  hint.style.display=legacy?'':'none';
}

riskKeExtendTable('ke-svc',[]);
riskKeExtendTable('ke-ins',RISK_KE_EXTRA_INSTRUMENTS);
