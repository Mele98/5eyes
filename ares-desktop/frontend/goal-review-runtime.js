function goalFrequencyKey(value){
  return cashflowFrequencyKey(value||'jaehrlich')||'jaehrlich';
}
function isRecurringGoalType(type){
  return type==='Wiederkehrende_Ausgabe'||type==='Pensionsausgabe';
}
function isWealthGoalType(type){
  return type==='Kapitalerhalt'||type==='Verm\u00f6gensziel';
}
function isReturnGoalType(type){
  return type==='Renditeziel';
}
function isMaxGoalType(type){
  return type==='Maximierung';
}
function goalValueMode(value){
  return String(value||'nominal').toLowerCase()==='real'?'real':'nominal';
}
function goalHardnessTone(goal){
  var hardness=String(goal&&goal.hardness||'').toLowerCase();
  if(hardness.indexOf('hart')===0)return 'hart';
  if(hardness.indexOf('opportun')===0)return 'opp';
  return 'primaer';
}
function goalTypeDisplayLabel(type){
  if(type==='Kapitalerhalt')return 'Kapitalerhalt';
  if(type==='Verm\u00f6gensziel')return 'Verm\u00f6gensziel';
  if(type==='Wiederkehrende_Ausgabe')return 'Laufende Entnahme';
  if(type==='Pensionsausgabe')return 'Pensionsausgabe';
  if(type==='Einmalige_Ausgabe')return 'Einmalige Entnahme';
  if(type==='Renditeziel')return 'Renditeziel';
  if(type==='Maximierung')return 'Maximierung';
  return String(type||'Ziel');
}
function goalBadgeHtml(goal){
  var badges=[];
  var typeLabel=goalTypeDisplayLabel(goal&&goal.goal_type||'');
  if(typeLabel){
    badges.push('<span style="font-size:9px;color:var(--n5);background:var(--bg2);border-radius:999px;padding:2px 6px;white-space:nowrap">'+escapeHtml(typeLabel)+'</span>');
  }
  var hardness=goalHardnessTone(goal);
  if(hardness==='hart'){
    badges.push('<span style="font-size:9px;font-weight:700;color:#166534;background:rgba(22,101,52,0.10);border-radius:999px;padding:2px 6px;white-space:nowrap">HART</span>');
  }else if(hardness==='opp'){
    badges.push('<span style="font-size:9px;font-weight:600;color:var(--n5);background:var(--bg2);border-radius:999px;padding:2px 6px;white-space:nowrap">OPP.</span>');
  }else{
    badges.push('<span style="font-size:9px;font-weight:700;color:#9a3412;background:rgba(154,52,18,0.10);border-radius:999px;padding:2px 6px;white-space:nowrap">PRIM\u00c4R</span>');
  }
  if(isWealthGoalType(goal&&goal.goal_type||'')&&goalValueMode(goal&&goal.value_mode)==='real'){
    badges.push('<span style="font-size:9px;font-weight:700;color:#1d4ed8;background:rgba(29,78,216,0.08);border-radius:999px;padding:2px 6px;white-space:nowrap">REAL</span>');
  }
  var prob=goal&&goal.probability_pct;
  if(prob!=null&&Number(prob)<100){
    var probClamped=Math.max(0,Math.min(100,Number(prob)));
    badges.push('<span style="font-size:9px;font-weight:700;color:#7c2d12;background:rgba(234,88,12,0.10);border-radius:999px;padding:2px 6px;white-space:nowrap" title="Bedingtes Ziel: Reserve-Beitrag wird mit '+probClamped+'% gewichtet.">BEDINGT '+probClamped+'%</span>');
  }
  var pillar=goal&&goal.pension_pillar;
  if(pillar&&['AHV','BVG','3a','1e','FZG'].indexOf(String(pillar))>=0){
    var pillarTitle=pillar==='AHV'?'AHV: staatliche 1. Säule (ohne Leistungsnachweis wie normales Ausgabenziel behandelt)':'Vorsorge-Säule '+pillar;
    badges.push('<span style="font-size:9px;font-weight:700;color:#0c4a6e;background:rgba(14,116,144,0.10);border-radius:999px;padding:2px 6px;white-space:nowrap" title="'+escapeHtml(pillarTitle)+'">'+escapeHtml(pillar)+'</span>');
  }
  return badges.join('');
}
function goalDisplayFrequency(value){
  var map={
    monatlich:'monatlich',
    quartalsweise:'quartalsweise',
    halbjaehrlich:'halbj\u00e4hrlich',
    jaehrlich:'j\u00e4hrlich',
    einmalig:'einmalig'
  };
  return map[goalFrequencyKey(value)]||String(value||'');
}
function goalAmountLabel(type){
  if(isReturnGoalType(type))return 'Zielrendite p.a. (%) *';
  if(isWealthGoalType(type))return 'Zielverm\u00f6gen ('+(mandateCurrency()||'—')+') *';
  if(isRecurringGoalType(type))return 'Betrag pro Periode ('+(mandateCurrency()||'—')+') *';
  if(type==='Einmalige_Ausgabe')return 'Zielbetrag ('+(mandateCurrency()||'—')+') *';
  if(isMaxGoalType(type))return 'Kein fixer Zielbetrag';
  return 'Zielbetrag *';
}
var GOAL_TYPE_FIELDS={
  'Verm\u00f6gensziel':{show:['target-amount','target-date','duration-years','priority-rank','success-prob-min','value-mode'],required:['target-amount'],hardness_hart:true,hint:'Verm\u00f6gensziel: Zielbetrag und Horizont oder Datum definieren den Kapitalbedarf.'},
  'Kapitalerhalt':{show:['target-amount','target-date','duration-years','priority-rank','success-prob-min','value-mode'],required:['target-amount'],hardness_hart:true,hint:'Kapitalerhalt: Mindestverm\u00f6gen mit nominaler oder realer Wertbasis.'},
  'Einmalige_Ausgabe':{show:['target-amount','target-date','duration-years','priority-rank','success-prob-min'],required:['target-amount','target-date'],hardness_hart:true,hint:'Einmalige Entnahme: Betrag und F\u00e4lligkeit beschreiben den Bedarf.'},
  'Pensionsausgabe':{show:['target-amount','target-date','start-date','frequency','duration-years','ongoing','priority-rank','success-prob-min'],required:['target-amount','start-date','frequency'],hardness_hart:true,hint:'Pensionsausgabe: periodischer Bedarf mit Beginn, Frequenz und optionalem Ende.'},
  'Wiederkehrende_Ausgabe':{show:['target-amount','target-date','start-date','frequency','duration-years','ongoing','priority-rank','success-prob-min'],required:['target-amount','frequency'],hardness_hart:true,hint:'Laufende Entnahme: periodischer Cashflow, optional mit Enddatum.'},
  'Renditeziel':{show:['target-return-bps','target-date','duration-years','priority-rank','success-prob-min'],required:['target-return-bps'],hardness_hart:false,hardness_default:'2',hint:'Renditeziel: Wunsch-Rendite p.a.; echte Bedarfsziele bleiben separat hart priorisiert.'},
  'Maximierung':{show:['priority-rank'],required:[],hardness_hart:false,hardness_default:'3',hint:'Maximierung: kein fixer Zielbetrag, sondern Opportunit\u00e4tsziel innerhalb der Leitplanken.'}
};
function goalTypeVisibilityConfig(typeValue){
  return GOAL_TYPE_FIELDS[typeValue]||GOAL_TYPE_FIELDS['Verm\u00f6gensziel'];
}
function setGoalFieldVisible(name,visible,required){
  var selectors='[data-goal-field="'+name+'"]';
  var el=document.querySelector(selectors);
  if(!el)return;
  el.style.display=visible?'':'none';
  var input=el.querySelector('input,select,textarea');
  if(input)input.required=!!required;
}
function applyGoalTypeVisibility(typeValue){
  var cfg=goalTypeVisibilityConfig(typeValue);
  var names=['target-amount','target-return-bps','target-date','start-date','frequency','duration-years','ongoing','priority-rank','success-prob-min','value-mode'];
  names.forEach(function(name){
    setGoalFieldVisible(name,cfg.show.indexOf(name)>=0,cfg.required.indexOf(name)>=0);
  });
  var hartOpt=document.getElementById('nz-prio-hart-option');
  if(hartOpt)hartOpt.disabled=!cfg.hardness_hart;
  if(!cfg.hardness_hart&&getInputValue('nz-prio')==='1'){
    setSelectValue('nz-prio',cfg.hardness_default||'2');
  }
  var hint=document.getElementById('m-acf-family-hint');
  if(hint)hint.textContent=cfg.hint||'';
}
function goalEditorInitialRappen(){
  var allocation=strategyState&&strategyState.allocation?strategyState.allocation:null;
  var rappen=Number(allocation&&allocation.advisory_wealth_rappen||0);
  if(!(rappen>0)){
    try{rappen=Number(currentAllocationInputSnapshot().advisoryRappen||0);}catch(_err){rappen=0;}
  }
  return Math.max(0,Math.round(rappen||0));
}
function goalEditorHorizonYears(){
  var dateRaw=normalizeCashflowDateValue(getInputValue('nz-target-date'));
  if(dateRaw){
    var end=new Date(dateRaw+'T00:00:00');
    if(!isNaN(end.getTime())){
      // GOAL-PAST-DATE-UI-001: ein gesetztes Zieldatum ist die massgebliche
      // Quelle. Bei Datum in der Vergangenheit (years<=0) darf NICHT auf den
      // u.U. veralteten #nz-horizon-Rohwert zurueckgefallen werden -- das
      // taeuschte bisher einen plausiblen positiven Horizont vor (z.B. den
      // beim Modal-Reset gesetzten Default 10) fuer ein Ziel, dessen Datum
      // tatsaechlich in der Vergangenheit liegt. Live reproduziert: Zieldatum
      // 01.01.2025 speicherte horizon_years=10, obwohl das Datum laengst
      // vergangen war.
      var years=(end.getTime()-Date.now())/(365.25*24*60*60*1000);
      return years>0?years:0;
    }
  }
  var raw=parseFloat(getInputValue('nz-horizon').replace(',','.'));
  return isFinite(raw)&&raw>0?raw:0;
}
function bindGoalEditorTyping(){
  var modal=document.getElementById('m-nz');
  if(!modal)return;
  Array.prototype.forEach.call(modal.querySelectorAll('input,textarea,select'),function(field){
    if(field.dataset.goalTypingBound==='1')return;
    field.dataset.goalTypingBound='1';
    ['keydown','keypress','keyup'].forEach(function(eventName){
      field.addEventListener(eventName,function(event){
        event.stopPropagation();
      });
    });
  });
}
function updateGoalDerivedDiagnostics(){
  var hintEl=document.getElementById('m-acf-derived');
  if(!hintEl)return;
  var type=getInputValue('nz-type')||'Einmalige_Ausgabe';
  var initialRappen=goalEditorInitialRappen();
  var initial=Number(initialRappen||0)/100;
  var horizon=goalEditorHorizonYears();
  if(!(initial>0)||!(horizon>0)){
    hintEl.textContent='';
    return;
  }
  if(isReturnGoalType(type)){
    var rBps=parsePercentToBps(getInputValue('nz-target-return-bps'));
    if(rBps==null||!(rBps>0)){hintEl.textContent='';return;}
    var rate=Number(rBps||0)/10000;
    var impliedWealth=initial*Math.pow(1+rate,horizon);
    hintEl.innerHTML='<strong>'+escapeHtml(formatRappen(Math.round(impliedWealth*100),mandateCurrency()))+'</strong> impliziertes Zielverm\u00f6gen in '+fmtNumber(horizon,1)+' Jahren.';
  }else if(isWealthGoalType(type)||type==='Einmalige_Ausgabe'){
    var target=Number(parseCHF(getInputValue('nz-amount'))||0)/100;
    if(!(target>0)){hintEl.textContent='';return;}
    var required=Math.pow(target/Math.max(1,initial),1/horizon)-1;
    hintEl.innerHTML='<strong>'+escapeHtml(fmtPct(required*10000,1))+' p.a.</strong> notwendige Rendite als rechnerische Kennzahl, keine Zusage.';
  }else if(isRecurringGoalType(type)){
    var streamAmount=Number(parseCHF(getInputValue('nz-amount'))||0)/100;
    var dur=parseFloat(getInputValue('nz-horizon').replace(',','.'))||0;
    if(!(streamAmount>0)||!(dur>0)){hintEl.textContent='';return;}
    hintEl.innerHTML='Vereinfachter Kapitalbedarf des Stroms: <strong>'+escapeHtml(formatRappen(Math.round(streamAmount*dur*100),mandateCurrency()))+'</strong>. Die pr\u00e4zise Tragf\u00e4higkeit zeigt der Optimizer.';
  }else{
    hintEl.textContent='';
  }
}
function goalAmountSummary(goal){
  var type=goal&&goal.goal_type||'';
  if(isReturnGoalType(type)){
    return goal&&goal.target_return_bps!=null ? formatBpsPercent(goal.target_return_bps)+' p.a.' : 'Renditeziel';
  }
  if(isMaxGoalType(type))return 'Maximierung';
  if(isWealthGoalType(type))return formatRappen(goal&&goal.target_wealth_rappen||0,mandateCurrency())+(goalValueMode(goal&&goal.value_mode)==='real'?' (real)':'');
  return formatRappen(goal&&goal.target_amount_rappen||0,mandateCurrency());
}
function goalTimingLabel(goal){
  var direct=String(goal&&goal.timing_label||'').trim();
  if(direct){
    return direct
      .replace(/\s*\|\s*/g,' \u00b7 ')
      .replace(/halbjaehrlich/g,'halbj\u00e4hrlich')
      .replace(/jaehrlich/g,'j\u00e4hrlich')
      .replace(/Pruefen/g,'Pr\u00fcfen')
      .replace(/Gefaehrdet/g,'Gef\u00e4hrdet');
  }
  var type=goal&&goal.goal_type||'Einmalige_Ausgabe';
  var start=normalizeCashflowDateValue(goal&&goal.start_date);
  var target=normalizeCashflowDateValue(goal&&goal.target_date);
  var years=parseInt(goal&&goal.horizon_years,10)||0;
  if(isRecurringGoalType(type)){
    var parts=[goalDisplayFrequency(goal&&goal.frequency||'jaehrlich')];
    if(start)parts.push('ab '+start);
    if(Number(goal&&goal.is_ongoing||0))parts.push('laufend');
    else if(target)parts.push('bis '+target);
    else if(years>0)parts.push('Horizont '+years+' J.');
    return parts.join(' \u00b7 ');
  }
  if(type==='Einmalige_Ausgabe'&&(target||start))return 'am '+(target||start);
  if(target)return 'bis '+target;
  if(years>0)return years+' J.';
  return 'offen';
}
function syncGoalModalState(){
  var type=getInputValue('nz-type')||'Einmalige_Ausgabe';
  var amountInput=document.getElementById('nz-amount');
  var amountWrap=amountInput&&amountInput.closest?amountInput.closest('.fg'):null;
  var amountLabel=document.getElementById('nz-amount-label');
  var returnInput=document.getElementById('nz-target-return-bps');
  var successInput=document.getElementById('nz-success-prob-min');
  var startWrap=document.getElementById('nz-start-wrap');
  var startLabel=document.getElementById('nz-start-label');
  var targetWrap=document.getElementById('nz-target-wrap');
  var targetLabel=document.getElementById('nz-target-label');
  var frequencyWrap=document.getElementById('nz-frequency-wrap');
  var ongoingWrap=document.getElementById('nz-ongoing-wrap');
  var valueModeRow=document.getElementById('nz-value-mode-row');
  var hardnessWarn=document.getElementById('nz-hardness-warn');
  var hardnessHint=document.getElementById('nz-hardness-hint');
  if(!hardnessHint){
    var prioritySelect=document.getElementById('nz-prio');
    var priorityField=prioritySelect&&prioritySelect.closest?prioritySelect.closest('.fg'):null;
    if(priorityField){
      hardnessHint=document.createElement('div');
      hardnessHint.id='nz-hardness-hint';
      hardnessHint.style.cssText='font-size:10px;color:var(--n5);margin-top:3px;line-height:1.45';
      priorityField.appendChild(hardnessHint);
    }
  }
  var nominalRadio=document.getElementById('nz-vm-nominal');
  var hint=document.getElementById('nz-date-hint');
  var pensionPillarWrap=document.getElementById('nz-pension-pillar-wrap');
  var ongoing=getInputValue('nz-ongoing')==='true';
  var prioritySelect=document.getElementById('nz-prio');
  if(prioritySelect&&prioritySelect.options&&prioritySelect.options.length>=3){
    prioritySelect.options[0].textContent='Hart - muss erreicht werden';
    prioritySelect.options[1].textContent='Primaer - wichtiges Planungsziel';
    prioritySelect.options[2].textContent='Opportunistisch - Wunschziel';
  }
  applyGoalTypeVisibility(type);
  if(amountLabel)amountLabel.textContent=goalAmountLabel(type);
  if(returnInput)returnInput.required=isReturnGoalType(type);
  if(amountInput)amountInput.required=!isReturnGoalType(type)&&!isMaxGoalType(type);
  if(successInput)successInput.placeholder=isReturnGoalType(type)?'50':'80';
  if(pensionPillarWrap){
    pensionPillarWrap.style.display=type==='Pensionsausgabe'?'':'none';
    if(type!=='Pensionsausgabe')setSelectValue('nz-pension-pillar','');
  }
  if(amountWrap)amountWrap.style.display=(isMaxGoalType(type)||isReturnGoalType(type))?'none':'';
  if(startWrap)startWrap.style.display=isRecurringGoalType(type)?'':'none';
  if(startLabel)startLabel.textContent=isRecurringGoalType(type)?'Beginn *':'Start';
  if(frequencyWrap)frequencyWrap.style.display=isRecurringGoalType(type)?'':'none';
  if(ongoingWrap)ongoingWrap.style.display=isRecurringGoalType(type)?'':'none';
  if(valueModeRow)valueModeRow.style.display=isWealthGoalType(type)?'':'none';
  if(!isWealthGoalType(type)&&nominalRadio)nominalRadio.checked=true;
  if(targetWrap){
    if(type==='Einmalige_Ausgabe'||isWealthGoalType(type)||isReturnGoalType(type))targetWrap.style.display='';
    else if(isMaxGoalType(type))targetWrap.style.display='none';
    else targetWrap.style.display=ongoing?'none':'';
  }
  if(targetLabel){
    if(type==='Einmalige_Ausgabe')targetLabel.textContent='F\u00e4lligkeit / Zieldatum *';
    else if(isRecurringGoalType(type))targetLabel.textContent='Enddatum (optional)';
    else if(isWealthGoalType(type)||isReturnGoalType(type))targetLabel.textContent='Zieldatum (optional)';
    else if(isMaxGoalType(type))targetLabel.textContent='Review-/Zieldatum (optional)';
    else targetLabel.textContent='Zieldatum';
  }
  if(isRecurringGoalType(type)){
    if(!getInputValue('nz-frequency')||goalFrequencyKey(getInputValue('nz-frequency'))==='einmalig'){
      setSelectValue('nz-frequency',type==='Pensionsausgabe'?'monatlich':'jaehrlich');
    }
    if(hint)hint.textContent='Wiederkehrende Ziele werden mit Beginn, Frequenz und optionalem Enddatum erfasst.';
  }else if(type==='Einmalige_Ausgabe'){
    setSelectValue('nz-frequency','einmalig');
    setSelectValue('nz-ongoing','false');
    if(hint)hint.textContent='Einmalige Entnahmen erhalten ein klares F\u00e4lligkeitsdatum; der Zeithorizont wird daraus abgeleitet.';
  }else if(isWealthGoalType(type)){
    setSelectValue('nz-ongoing','false');
    if(hint)hint.textContent='Verm\u00f6gensziele k\u00f6nnen \u00fcber Datum oder Horizont terminiert werden.';
  }else if(isReturnGoalType(type)){
    setSelectValue('nz-ongoing','false');
    // 2026-08-06 (User-Direktive, Ziele-Audit): NUR den fachlich unzulaessigen
    // Zustand ('Hart', bei Renditezielen verboten) auf einen gueltigen Default
    // korrigieren -- vorher wurde 'nz-prio' bei JEDEM syncGoalModalState()-
    // Aufruf unconditional auf '3' (Opportunistisch) zurueckgesetzt, auch
    // NACHDEM der Nutzer bereits '2' (Primaer, fachlich fuer Renditeziele
    // ausdruecklich zulaessig, siehe nz-hardness-warn-Text) gewaehlt hatte --
    // 'Primaer' liess sich fuer ein neues Renditeziel dadurch nie speichern.
    if(!currentGoalEditId&&getInputValue('nz-prio')==='1')setSelectValue('nz-prio','3');
    if(hint)hint.textContent='Renditeziele speichern eine Zielrendite p.a. und optional ein Review-Datum.';
  }else if(isMaxGoalType(type)){
    setSelectValue('nz-ongoing','false');
    if(hint)hint.textContent='Maximierung hat keinen fixen Zielbetrag; relevant sind Priorit\u00e4t, Scope und Zeitfenster.';
  }
  if(hardnessWarn){
    var isRendite=isReturnGoalType(type);
    var isHart=getInputValue('nz-prio')==='1';
    hardnessWarn.style.display=(isRendite&&isHart)?'block':'none';
  }
  // Sprint 2026-06-08 Fix A: SAA-Info zeigen bei Renditeziel (wo User
  // typischerweise Allocation-Reaktion erwartet) und bei Edit-Mode (= bestehendes
  // Goal). Aufklaerung dass Renditeziel-Target die SAA nicht direkt beeinflusst.
  var saaInfo=document.getElementById('nz-saa-info');
  if(saaInfo){
    var isReturn=isReturnGoalType(type);
    var isEditing=!!currentGoalEditId;
    saaInfo.style.display=(isReturn||isEditing)?'block':'none';
  }
  if(hardnessHint){
    hardnessHint.textContent=isReturnGoalType(type)
      ? 'Rendite ist keine garantierbare Leistung und kann deshalb nur Primaer oder Opportunistisch sein.'
      : (isMaxGoalType(type)
        ? 'Maximierung ist ein Wunschziel und kein verbindlicher Mindestbedarf.'
        : 'Hart ist fuer echte Bedarfs-, Entnahme- und Vermoegensziele zulaessig.');
  }
  updateGoalDerivedDiagnostics();
}
function resetGoalModal(){
  currentGoalEditId=null;
  var modalTitle=document.querySelector('#m-nz .mtitle');
  if(modalTitle)modalTitle.textContent='Ziel erfassen';
  setInputValue('nz-label','');
  setInputValue('nz-notes','');
  setSelectValue('nz-type','Einmalige_Ausgabe');
  setSelectValue('nz-prio','2');
  setSelectValue('nz-scope','Beratungsverm\u00f6gen');
  setInputValue('nz-amount','');
  setInputValue('nz-target-return-bps','');
  setInputValue('nz-horizon','10');
  setInputValue('nz-start-date','');
  setInputValue('nz-target-date','');
  setSelectValue('nz-frequency','jaehrlich');
  setSelectValue('nz-ongoing','false');
  setInputValue('nz-probability','100');
  setInputValue('nz-success-prob-min','');
  setSelectValue('nz-pension-pillar','');
  var nominalRadio=document.getElementById('nz-vm-nominal');
  var realRadio=document.getElementById('nz-vm-real');
  if(nominalRadio)nominalRadio.checked=true;
  if(realRadio)realRadio.checked=false;
  var btn=document.getElementById('btn-nz-save');
  if(btn){btn.textContent='Speichern';btn.disabled=false;}
  var err=document.getElementById('nz-error');
  if(err){err.style.display='none';err.textContent='';}
  bindGoalEditorTyping();
  syncGoalModalState();
  onGoalDateGroupChange();
  setTimeout(function(){
    var labelInput=document.getElementById('nz-label');
    if(labelInput)labelInput.focus();
  },0);
}
function openGoalEditor(goalId){
  var goal=(currentGoals||[]).find(function(item){return String(item.id||'')===String(goalId||'');});
  if(!goal)return;
  currentGoalEditId=goal.id;
  var modalTitle=document.querySelector('#m-nz .mtitle');
  if(modalTitle)modalTitle.textContent='Ziel bearbeiten';
  var goalType=goal.goal_type||'Einmalige_Ausgabe';
  var priorityMap={'Hart':'1','Prim\u00e4r':'2','Primaer':'2','Opportunistisch':'3'};
  var storedPriority=priorityMap[goal.hardness]||'2';
  var legacyHardReturn=isReturnGoalType(goalType)&&storedPriority==='1';
  setInputValue('nz-label',goal.label||'');
  setInputValue('nz-notes',goal.notes||'');
  setSelectValue('nz-type',goalType);
  setSelectValue('nz-prio',legacyHardReturn?'2':storedPriority);
  setSelectValue('nz-scope',goal.goal_scope||'Beratungsverm\u00f6gen');
  if(isReturnGoalType(goalType))setInputValue('nz-amount','');
  else if(isWealthGoalType(goalType))setInputValue('nz-amount',formatInputCHF(goal.target_wealth_rappen));
  else if(isMaxGoalType(goalType))setInputValue('nz-amount','');
  else setInputValue('nz-amount',formatInputCHF(goal.target_amount_rappen));
  setInputValue('nz-target-return-bps',isReturnGoalType(goalType)?formatInputPercent(goal.target_return_bps):'');
  setInputValue('nz-horizon',goal.horizon_years==null?'10':goal.horizon_years);
  setInputValue('nz-start-date',normalizeCashflowDateValue(goal.start_date));
  setInputValue('nz-target-date',normalizeCashflowDateValue(goal.target_date));
  setSelectValue('nz-frequency',goalFrequencyKey(goal.frequency||'jaehrlich'));
  setSelectValue('nz-ongoing',Number(goal.is_ongoing||0)?'true':'false');
  setInputValue('nz-probability',goal.probability_pct==null?'100':String(goal.probability_pct));
  setInputValue('nz-success-prob-min',goal.success_probability_min_x100==null?'':String(Math.round(Number(goal.success_probability_min_x100||0)/100)));
  setSelectValue('nz-pension-pillar',goal.pension_pillar||'');
  var vm=goalValueMode(goal.value_mode);
  var vmRadio=document.getElementById('nz-vm-'+vm);
  if(vmRadio)vmRadio.checked=true;
  var btn=document.getElementById('btn-nz-save');
  if(btn){btn.textContent='Aktualisieren';btn.disabled=false;}
  var err=document.getElementById('nz-error');
  if(err){err.style.display='none';err.textContent='';}
  bindGoalEditorTyping();
  syncGoalModalState();
  onGoalDateGroupChange();
  if(legacyHardReturn){
    showModalFeedback(
      'nz-error',
      btn,
      'Dieses ältere Renditeziel war als Hart gespeichert. Für die Bearbeitung wird es regelkonform auf Primär gesetzt.',
      false
    );
  }
  var modal=document.getElementById('m-nz');
  if(modal)modal.classList.add('open');
}
function renderGoalList(items,isDemo){
  var zl=document.getElementById('zl');
  if(!zl)return;
  if(!Array.isArray(items)||!items.length){
    zl.innerHTML='';
    updateCashflowsAndGoalsKpis(currentCashflowSummary||{});
    applyGoalDerivedRiskHorizon(false);
    return;
  }
  var pc={'Hart':'p1','Prim\u00e4r':'p2','Primaer':'p2','Opportunistisch':'p3'};
  zl.innerHTML=items.map(function(goal,index){
    // GOAL-STATUS-BY-SUCCESS-001: nicht mehr Goal.achievement_score (DB, nie
    // geschrieben), sondern die Erfolgs-Wkt. der aktuellen Allokation, sonst '\u2014'.
    var successRow=isDemo?null:goalSuccessFromCurrentAllocation(goal.id);
    var successPct=goalSuccessPct(successRow);
    var scored=successPct!==null;
    var pct=scored?successPct:0;
    var tone=!scored?'fa':pct>=70?'fg':pct>=45?'fa':'fr';
    var tagTone=!scored?'tn':pct>=70?'tg':pct>=45?'ta':'tr2';
    var tagLabel=!scored?'Noch nicht bewertet':goalSuccessAmpel(pct).label;
    var meta=[goalAmountSummary(goal),goalTimingLabel(goal)];
    if(isDemo)meta.push('Demo');
    var badges=goalBadgeHtml(goal);
    var goalIncluded=goal.is_included!==0;
    var goalIncTitle=goalIncluded?'In Berechnungen eingeschlossen — Klick zum vorübergehenden Ausschliessen':'Von Berechnungen ausgeschlossen — Klick zum Wieder-Einschliessen';
    return '<div class="goal'+(goalIncluded?'':' is-excluded')+'" draggable="true" data-goalid="'+escapeHtml(goal.id||'')+'">'+
      '<div class="pd '+(pc[goal.hardness]||'p2')+'">'+(index+1)+'</div>'+
      '<div class="gi"><div class="gn" style="display:flex;align-items:center;gap:6px;flex-wrap:wrap"><span>'+escapeHtml(goal.label||'Ziel')+'</span>'+badges+'</div><div class="gd">'+escapeHtml(meta.filter(Boolean).join(' · '))+'</div>'+(goal.notes?'<div class="gd" style="margin-top:3px;color:var(--n5)">'+escapeHtml(goal.notes)+'</div>':'')+goalEvaluationNoteHtml(goal,true)+'</div>'+
      '<span class="tag '+tagTone+'">'+tagLabel+'</span>'+
      '<div class="gbw"><div class="gp" title="'+escapeHtml(scored?('Erfolgswahrscheinlichkeit: '+GOAL_SUCCESS_PROBABILITY_TOOLTIP+(goalSuccessIsEstimate(successRow)?(' \u2013 '+GOAL_SUCCESS_ESTIMATE_HINT):'')):'Noch keine aktuelle Strategie berechnet')+'">'+(scored?fmtProbPct(pct):'—')+'</div><div class="gb"><div class="gf '+tone+'" style="width:'+Math.max(0,Math.min(100,scored?Math.round(pct):0))+'%"></div></div></div>'+
      '<div class="goal-actions"><label class="inc-switch" draggable="false" title="'+goalIncTitle+'"><input type="checkbox" class="inc-switch-input goal-include-toggle"'+(goalIncluded?' checked':'')+'><span class="inc-switch-track"><span class="inc-switch-thumb"></span></span></label><button class="btn btn-sm goal-edit-action" type="button">Bearbeiten</button><button class="goal-delete-action" type="button">Entfernen</button></div></div>';
  }).join('');
  Array.prototype.forEach.call(zl.querySelectorAll('.goal[data-goalid] .goal-edit-action, .goal[data-goalid] .goal-delete-action'),function(btn){
    var card=btn.closest('.goal[data-goalid]');
    if(!card)return;
    if(btn.classList.contains('goal-edit-action')){
      btn.onclick=function(ev){
        if(ev)ev.preventDefault();
        openGoalEditor(card.getAttribute('data-goalid')||'');
      };
    }else if(btn.classList.contains('goal-delete-action')){
      btn.onclick=function(ev){
        if(ev)ev.preventDefault();
        dg(btn);
      };
    }
  });
  Array.prototype.forEach.call(zl.querySelectorAll('.goal[data-goalid] .goal-include-toggle'),function(input){
    input.onchange=function(){
      toggleGoalIncluded(input);
    };
  });
  setupDrag();
  updateCashflowsAndGoalsKpis(currentCashflowSummary||{});
  applyGoalDerivedRiskHorizon(false);
}
function buildDemoGoalRecord(goalId,payload,existingGoal){
  return Object.assign({},existingGoal||{},{
    id:goalId,
    goal_family:payload.goal_family,
    goal_type:payload.goal_type,
    label:payload.label,
    notes:payload.notes,
    rank:payload.rank,
    goal_scope:payload.goal_scope,
    value_mode:payload.value_mode,
    target_amount_rappen:payload.target_amount_rappen,
    target_wealth_rappen:payload.target_wealth_rappen,
    target_return_bps:payload.target_return_bps,
    success_probability_min_x100:payload.success_probability_min_x100,
    start_date:payload.start_date,
    horizon_years:payload.horizon_years,
    target_date:payload.target_date,
    is_ongoing:payload.is_ongoing?1:0,
    frequency:payload.frequency,
    hardness:payload.hardness,
    probability_pct:payload.probability_pct==null?100:payload.probability_pct,
    pension_pillar:payload.pension_pillar||null
  });
}
function upsertSavedGoal(savedGoal,fallbackId,payload){
  var resolvedId=String(savedGoal&&savedGoal.id||fallbackId||'');
  if(!resolvedId)return null;
  var existing=(currentGoals||[]).find(function(goal){
    return String(goal&&goal.id||'')===resolvedId;
  })||null;
  var normalized=Object.assign(
    {},
    buildDemoGoalRecord(resolvedId,payload,existing),
    savedGoal&&typeof savedGoal==='object'?savedGoal:{},
    {id:resolvedId}
  );
  currentGoals=(currentGoals||[]).filter(function(goal){
    return String(goal&&goal.id||'')!==resolvedId;
  });
  currentGoals.push(normalized);
  currentGoals.sort(function(a,b){return Number(a.rank||99)-Number(b.rank||99);});
  renderGoalList(currentGoals,false);
  syncAllocationPendingViews();
  return normalized;
}
function goalSaveErrorText(error){
  var detail=error&&error.detail!=null?error.detail:(error&&error.message!=null?error.message:error);
  if(Array.isArray(detail)){
    detail=detail.map(function(item){
      if(item&&typeof item==='object')return item.msg||item.message||JSON.stringify(item);
      return String(item);
    }).join(' | ');
  }else if(detail&&typeof detail==='object'){
    detail=detail.msg||detail.message||JSON.stringify(detail);
  }
  return String(detail||'Unbekannter Fehler beim Speichern.');
}
async function saveGoal(options){
  options=options||{};
  var label=getInputValue('nz-label').trim();
  var notes=getInputValue('nz-notes').trim();
  var type=getInputValue('nz-type')||'Einmalige_Ausgabe';
  var prio=getInputValue('nz-prio')||'2';
  var scope=getInputValue('nz-scope')||'Beratungsverm\u00f6gen';
  var amountRaw=getInputValue('nz-amount').trim();
  var returnRaw=getInputValue('nz-target-return-bps').trim();
  // GOAL-HORIZON-STALE-001 (2026-10-07): Horizont aus goalEditorHorizonYears() wie die
  // Live-Diagnose (Single Source of Truth), nicht der nie nachgefuehrte Rohwert aus #nz-horizon.
  var horizonFloat=goalEditorHorizonYears();
  var horizon=horizonFloat>0?Math.max(1,Math.round(horizonFloat)):null;
  var startDate=normalizeCashflowDateValue(getInputValue('nz-start-date'));
  var targetDate=normalizeCashflowDateValue(getInputValue('nz-target-date'));
  var frequency=goalFrequencyKey(getInputValue('nz-frequency')||'jaehrlich');
  var isOngoing=getInputValue('nz-ongoing')==='true';
  var btn=document.getElementById('btn-nz-save');
  var isEdit=!!currentGoalEditId;
  var goalIdBeforeSave=currentGoalEditId;
  var targetReturnBps=null;
  if(!label){showModalFeedback('nz-error',btn,'Bitte Bezeichnung eingeben.',true);return false;}
  if(!isMaxGoalType(type)){
    if(isReturnGoalType(type)){
      if(!returnRaw){showModalFeedback('nz-error',btn,'Bitte Zielrendite eingeben.',true);return false;}
      targetReturnBps=parsePercentToBps(returnRaw);
      if(targetReturnBps==null||targetReturnBps<=0){showModalFeedback('nz-error',btn,'Bitte positive Zielrendite p.a. eingeben.',true);return false;}
    }else if(!amountRaw||isNaN(parseFloat(amountRaw.replace(',','.')))){
      showModalFeedback('nz-error',btn,'Bitte g\u00fcltigen Betrag eingeben.',true);
      return false;
    }
  }
  if(isReturnGoalType(type)&&prio==='1'){
    showModalFeedback('nz-error',btn,'Renditeziele koennen nicht als Hart gespeichert werden. Bitte Primaer oder Opportunistisch waehlen.',true);
    return false;
  }
  if(type==='Einmalige_Ausgabe'){
    if(!targetDate&&!startDate){showModalFeedback('nz-error',btn,'Bitte F\u00e4lligkeitsdatum f\u00fcr die einmalige Entnahme eingeben.',true);return false;}
    if(!targetDate)targetDate=startDate;
    if(!startDate)startDate=targetDate;
    frequency='einmalig';
    isOngoing=false;
  }else if(isRecurringGoalType(type)){
    if(!startDate){showModalFeedback('nz-error',btn,'Bitte Beginn f\u00fcr das wiederkehrende Ziel eingeben.',true);return false;}
    if(isOngoing)targetDate='';
    if(targetDate&&targetDate<startDate){showModalFeedback('nz-error',btn,'Enddatum darf nicht vor dem Beginn liegen.',true);return false;}
  }else{
    startDate='';
    frequency='jaehrlich';
    isOngoing=false;
    if(isMaxGoalType(type))targetDate='';
  }
  // GOAL-PAST-DATE-UI-001: Zieldatum ist bei Zielen immer ein zukuenftiger
  // Faelligkeits-/Bewertungsanker (im Gegensatz zu Cashflows, deren
  // valid_until legitim in der Vergangenheit liegen darf). Live reproduziert:
  // ein Renditeziel mit Zieldatum 01.01.2025 wurde bisher klaglos gespeichert.
  if(targetDate&&targetDate<new Date().toISOString().slice(0,10)){
    showModalFeedback('nz-error',btn,'Zieldatum darf nicht in der Vergangenheit liegen.',true);
    return false;
  }
  var mid=getActiveMandateId();
  if(btn){btn._origText=isEdit?'Aktualisieren':'Speichern';btn.disabled=true;btn.textContent=isEdit?'Aktualisieren...':'Speichern...';}
  var hardnessMap={'1':'Hart','2':'Prim\u00e4r','3':'Opportunistisch'};
  var familyMap={
    'Einmalige_Ausgabe':'Cashflow',
    'Wiederkehrende_Ausgabe':'Cashflow',
    'Pensionsausgabe':'Cashflow',
    'Kapitalerhalt':'Verm\u00f6gen',
    'Verm\u00f6gensziel':'Verm\u00f6gen',
    'Renditeziel':'Rendite',
    'Maximierung':'Maximierung'
  };
  var payload={
    goal_family:familyMap[type]||'Cashflow',
    goal_type:type,
    label:label,
    notes:notes||null,
    rank:(function(){var own=isEdit?(currentGoals||[]).find(function(g){return String(g.id||'')===String(goalIdBeforeSave||'');}):null;if(own&&Number(own.rank)>0)return Number(own.rank);return (currentGoals||[]).reduce(function(m,g){return Math.max(m,Number(g.rank||0));},0)+1;})(),
    goal_scope:scope,
    value_mode:isWealthGoalType(type)?((document.querySelector('input[name=\"nz-value-mode\"]:checked')||{value:'nominal'}).value||'nominal'):'nominal',
    target_amount_rappen:null,
    target_wealth_rappen:null,
    target_return_bps:null,
    success_probability_min_x100:(function(){if(isMaxGoalType(type))return null;var raw=getInputValue('nz-success-prob-min').trim();if(!raw)return null;var pct=parseInt(raw,10);return isFinite(pct)?Math.max(0,Math.min(100,pct))*100:null;})(),
    start_date:startDate||null,
    horizon_years:horizon,
    target_date:targetDate||null,
    is_ongoing:isRecurringGoalType(type)?isOngoing:false,
    frequency:isRecurringGoalType(type)?frequency:null,
    hardness:hardnessMap[prio]||'Prim\u00e4r',
    probability_pct:(function(){var raw=parseInt(getInputValue('nz-probability'),10);return isFinite(raw)?Math.max(0,Math.min(100,raw)):100;})(),
    pension_pillar:(function(){var v=getInputValue('nz-pension-pillar')||'';return (type==='Pensionsausgabe'&&['AHV','BVG','3a','1e','FZG'].indexOf(v)>=0)?v:null;})()
  };
  if(isReturnGoalType(type))payload.target_return_bps=targetReturnBps;
  else if(isWealthGoalType(type))payload.target_wealth_rappen=parseCHF(amountRaw);
  else if(!isMaxGoalType(type))payload.target_amount_rappen=parseCHF(amountRaw);
  if(mid&&!isDemoMandateId(mid)){
    try{
      var savedGoal=isEdit
        ? await API.put('/mandates/'+mid+'/goals/'+goalIdBeforeSave,payload)
        : await API.post('/mandates/'+mid+'/goals',payload);
      upsertSavedGoal(savedGoal,goalIdBeforeSave,payload);
      showModalFeedback('nz-error',btn,isEdit?'OK: Ziel aktualisiert':'OK: Ziel gespeichert',false);
      currentGoalEditId=null;
      cm('m-nz');
      if(!options.deferRefresh)await refreshGoalsUI(mid);
      updateCfRiskContextSummary();
      markStrategyDirty(
        isEdit
          ? 'Ziel aktualisiert. Die angezeigte Soll-Allokation ist noch der alte Stand - bitte Anlagestrategie neu berechnen.'
          : 'Ziel gespeichert. Die angezeigte Soll-Allokation ist noch der alte Stand - bitte Anlagestrategie neu berechnen.',
        true
      );
      try{showAppSuccess(isEdit?'Ziel aktualisiert':'Ziel gespeichert');}catch(noticeErr){}
      return true;
    }catch(e){
      var goalErr='Fehler: '+goalSaveErrorText(e);
      showModalFeedback('nz-error',btn,goalErr,true);
      try{showAppError(goalErr,{title:'Ziel nicht gespeichert'});}catch(noticeErr){}
      return false;
    }
  } else {
    var localId=isEdit?currentGoalEditId:('demo-goal-'+Date.now());
    var existing=(currentGoals||[]).find(function(goal){return String(goal.id||'')===String(localId);})||null;
    var localGoal=buildDemoGoalRecord(localId,payload,existing);
    currentGoals=(currentGoals||[]).filter(function(goal){return String(goal.id||'')!==String(localId);});
    currentGoals.push(localGoal);
    currentGoals.sort(function(a,b){return Number(a.rank||99)-Number(b.rank||99);});
    renderGoalList(currentGoals,true);
    showModalFeedback('nz-error',btn,'\u2713 Demo-Modus: Ziel aktualisiert',false);
    currentGoalEditId=null;
    setTimeout(function(){cm('m-nz');},600);
    return true;
  }
}
var _goalsUiRefreshEpoch=0;
async function refreshGoalsUI(mid){
  // STALE-REFRESH-RACE-FIX: siehe identischer Kommentar auf
  // refreshCashflowsUI -- gleiches Muster fuer Ziel-Toggles.
  var __epoch=++_goalsUiRefreshEpoch;
  if(!mid||isDemoMandateId(mid)){
    if(__epoch!==_goalsUiRefreshEpoch)return;
    renderGoalList(currentGoals,true);
    syncAllocationPendingViews();
    _currentGoalsLoadedOnce=true;
    return;
  }
  try{
    var data=await API.get('/mandates/'+mid+'/goals');
    if(__epoch!==_goalsUiRefreshEpoch)return;
    var items=Array.isArray(data)?data:(data.items||[]);
    currentGoals=items.slice();
    renderGoalList(currentGoals,false);
    syncAllocationPendingViews();
    updateCfRiskContextSummary();
    _currentGoalsLoadedOnce=true;
  }catch(e){
    if(__epoch!==_goalsUiRefreshEpoch)return;
    console.warn('refreshGoalsUI:',e);
  }
}
async function loadPlanningAssumptions(){
  var mid=getActiveMandateId();
  var pctEl=document.getElementById('plan-inflation-pct');
  var fbEl=document.getElementById('plan-feedback');
  if(fbEl){fbEl.style.display='none';fbEl.textContent='';}
  if(pctEl&&!mid)pctEl.value='';
  if(!mid||isDemoMandateId(mid))return;
  try{
    var data=await API.get('/mandates/'+mid+'/planning-assumptions');
    var bps=data&&data.inflation_assumption_bps;
    if(pctEl)pctEl.value=bps!=null?(Number(bps)/100).toFixed(2):'';
  }catch(e){
    if(pctEl)pctEl.value='';
  }
}
async function savePlanningAssumptions(){
  var mid=getActiveMandateId();
  if(!mid||isDemoMandateId(mid))return;
  var btn=document.getElementById('btn-plan-save');
  var fbEl=document.getElementById('plan-feedback');
  var pctEl=document.getElementById('plan-inflation-pct');
  var raw=String((pctEl&&pctEl.value)||'').trim();
  var pctVal=raw===''?null:parseFloat(raw.replace(',','.'));
  if(raw!==''&&(isNaN(pctVal)||pctVal<0||pctVal>10)){
    if(fbEl){
      fbEl.textContent='Bitte gültigen Wert eingeben (0–10%).';
      fbEl.style.color='var(--neg)';
      fbEl.style.display='block';
    }
    return;
  }
  var bps=pctVal==null?null:Math.round(pctVal*100);
  if(btn){btn.disabled=true;btn.textContent='Speichert…';}
  try{
    await API.put('/mandates/'+mid+'/planning-assumptions',{inflation_assumption_bps:bps});
    if(fbEl){
      fbEl.textContent=pctVal==null
        ? '✓ Mandatsspezifische Inflationsannahme entfernt. Für reale Ziele gilt wieder der CMA-Fallback.'
        : ('✓ '+fmtPct(bps,2)+' = '+bps+' BPS gespeichert.');
      fbEl.style.color='var(--pos)';
      fbEl.style.display='block';
      setTimeout(function(){ if(fbEl)fbEl.style.display='none'; },3000);
    }
    await loadPlanningAssumptions();
    markStrategyDirty('Planungsannahmen aktualisiert: Reale Vermögensziele verwenden ab der nächsten Strategie-Berechnung die neue Inflationsannahme.', false);
  }catch(e){
    if(fbEl){
      fbEl.textContent='Fehler: '+((e&&e.detail)||(e&&e.message)||e);
      fbEl.style.color='var(--neg)';
      fbEl.style.display='block';
    }
  }finally{
    if(btn){btn.disabled=false;btn.textContent='Speichern';}
  }
}
var _cmGoalTiming=cm;
cm=function(id){
  if(id==='m-nz')currentGoalEditId=null;
  return _cmGoalTiming(id);
};
function strategyGoalTargetText(goal){
  var type=goal&&goal.goal_type||'';
  if(isReturnGoalType(type)){
    return goal&&goal.target_return_bps!=null ? formatBpsPercent(goal.target_return_bps)+' p.a.' : 'Renditeziel';
  }
  if(isMaxGoalType(type))return 'Maximierung';
  if(isWealthGoalType(type)&&goal&&goal.target_wealth_rappen!=null){
    return formatRappen(goal.target_wealth_rappen,mandateCurrency())+(goalValueMode(goal&&goal.value_mode)==='real'?' (real)':'');
  }
  return formatRappen(goal&&goal.target_amount_rappen||0,mandateCurrency());
}
function goalEvaluationNoteHtml(goal,compact){
  var note=String(goal&&goal.evaluation_note||'').trim();
  if(!note)return '';
  return '<div style="font-size:'+(compact?'9px':'10px')+';color:var(--n5);margin-top:4px;line-height:1.45;max-width:'+(compact?'360px':'420px')+'">'+escapeHtml(note)+'</div>';
}
function aaActionCardHtml(title,tagLabel,tagClass,body,accent){
  var accentClass=accent==='warn'?' warn':(accent==='good'?' good':'');
  return '<div class="action-list-row'+accentClass+'"><div><div class="action-list-title">'+escapeHtml(title)+'</div><div class="action-list-desc">'+escapeHtml(body)+'</div></div><span class="tag '+tagClass+'">'+escapeHtml(tagLabel)+'</span></div>';
}
function projectionRunwayInfo(seriesRappen,yearLabels){
  var series=Array.isArray(seriesRappen)?seriesRappen:[];
  var labels=Array.isArray(yearLabels)?yearLabels:[];
  if(series.length<2)return {label:'-',yearLabel:null,years:null,isDepleted:false};
  for(var idx=1;idx<series.length;idx++){
    if(Number(series[idx]||0)<=0){
      var yearLabel=labels[idx]!=null?String(labels[idx]):('Jahr '+idx);
      return {label:yearLabel+' / '+idx+' J.',yearLabel:yearLabel,years:idx,isDepleted:true};
    }
  }
  var lastLabel=labels.length?String(labels[labels.length-1]):'Horizont';
  return {label:'> '+lastLabel,yearLabel:lastLabel,years:labels.length?labels.length-1:series.length-1,isDepleted:false};
}
function currentCashflowCoverageInfo(){
  var rows=currentCashflowProjection&&Array.isArray(currentCashflowProjection.years)?currentCashflowProjection.years:[];
  var row=rows.length?rows[0]:null;
  var parts=row?cashflowProjectionComponents(row):null;
  var currentYear=Number(row&&row.year!=null?row.year:(new Date()).getFullYear());
  var recurringIncome=Number(
    parts&&parts.recurringIncomeRappen!=null
      ? parts.recurringIncomeRappen
      : (currentCashflowSummary&&currentCashflowSummary.recurring_income_rappen!=null
        ? currentCashflowSummary.recurring_income_rappen
        : Math.max(0,Number(currentCashflowSummary&&currentCashflowSummary.total_income_rappen||0)))
  );
  var recurringExpense=Number(
    parts&&parts.recurringExpenseRappen!=null
      ? parts.recurringExpenseRappen
      : (currentCashflowSummary&&currentCashflowSummary.recurring_expense_rappen!=null
        ? currentCashflowSummary.recurring_expense_rappen
        : Math.max(0,Number(currentCashflowSummary&&currentCashflowSummary.total_expense_rappen||0)))
  );
  var oneOffIncomeCurrentYear=Number(parts&&parts.capitalInflowsRappen||0)+Number(parts&&parts.pensionPayoutRappen||0);
  var oneOffExpenseCurrentYear=Number(parts&&parts.capitalOutflowsRappen||0);
  var net=recurringIncome-recurringExpense;
  var coveragePct=recurringExpense>0?recurringIncome/recurringExpense*100:null;
  return {
    year:String(currentYear),
    currency:ccyOf(parts?currentCashflowProjection.amount_currency:(currentCashflowSummary&&currentCashflowSummary.amount_currency)),  // G7 N4
    incomeRappen:recurringIncome,
    expenseRappen:recurringExpense,
    netRappen:net,
    coveragePct:coveragePct,
    oneOffIncomeCurrentYearRappen:oneOffIncomeCurrentYear,
    oneOffExpenseCurrentYearRappen:oneOffExpenseCurrentYear
  };
}
function decumulationCapitalBridgeRows(limit){
  var currentYear=(new Date()).getFullYear();
  return (Array.isArray(currentCashflows)?currentCashflows:[])
    .filter(function(cashflow){
      if(!cashflow)return false;
      if(String(cashflow.cashflow_type||'')!=='Income')return false;
      if(!(isOneOffCashflow(cashflow.frequency)||String(cashflow.nature||'').toLowerCase()==='einmalig'))return false;
      var year=parseInt(String(normalizeCashflowDateValue(cashflow.valid_from)||normalizeCashflowDateValue(cashflow.valid_until)||'').slice(0,4),10);
      return isFinite(year)&&year>currentYear;
    })
    .sort(function(a,b){
      var ay=parseInt(String(normalizeCashflowDateValue(a.valid_from)||normalizeCashflowDateValue(a.valid_until)||'').slice(0,4),10)||9999;
      var by=parseInt(String(normalizeCashflowDateValue(b.valid_from)||normalizeCashflowDateValue(b.valid_until)||'').slice(0,4),10)||9999;
      return ay-by;
    })
    .slice(0,limit||2)
    .map(function(cashflow){
      var year=parseInt(String(normalizeCashflowDateValue(cashflow.valid_from)||normalizeCashflowDateValue(cashflow.valid_until)||'').slice(0,4),10);
      return {
        year:String(year),
        label:String(cashflow.label||'Kapitalzufluss'),
        amountRappen:Number(cashflow.amount_rappen||0),
        currency:cashflow.currency
      };
    });
}
// ============================================================================
// Phase 6: Optimizer-Panel (Status, Reasoning, Stress-Tests, Sensitivity)
// ============================================================================
// V3 Sprint 1 Commit 4 (Plan §7.2): Klassen-basierter Status-Pill ohne Emoji.
// Erlaubt fuer Solver-Statuswerte 'converged', 'diverged', 'diverged_infeasible',
// 'fallback_house_matrix' sowie generische Comparison-Stati.
function setStatusPill(el,status,label){
  if(!el)return;
  var s=String(status||'').toLowerCase();
  el.className='status-pill';
  if(s==='converged'){
    el.className+=' ok';
    el.textContent=label||'Konvergiert';
  }else if(s==='converged_robustified'){
    // Bug-#3 (2026-06-07): Robustifiziert ist NICHT Fallback — Solver hat
    // eine feasible Loesung gefunden, allerdings ueber Multi-Start-
    // Stabilisierung. Eigener Status-Pill ohne Warn-Farbe.
    el.className+=' ok';
    el.textContent=label||'Konvergiert (robustifiziert)';
  }else if(s==='diverged'||s==='diverged_infeasible'||s==='fallback_house_matrix'){
    el.className+=' warn';
    el.textContent=label||'Fallback';
  }else if(s){
    el.textContent=label||status;
  }else{
    el.textContent=label||'';
  }
}

// V3 Sprint 1 Commit 4 (Plan §7.3): Methodenvergleich-Panel rendern.
// Quelle: result.allocation_method_comparison (nur im shadow_stochastic-Modus).
// Renderert House vs. Shadow Tabelle, advisory_note ohne Marketing-Sprache,
// Constraint-Slacks, Goal-Drivers und Audit-Footer.
function renderAllocationMethodComparison(result){
  var panel=document.getElementById('al-method-comparison-panel');
  if(!panel)return;
  var cmp=result&&result.allocation_method_comparison;
  if(!cmp){
    panel.style.display='none';
    return;
  }
  panel.style.display='';

  var pill=document.getElementById('method-comparison-pill');
  setStatusPill(
    pill,
    cmp.shadow_status||'',
    cmp.shadow_status==='converged'?'Vergleich konvergiert':'Vergleich'
  );

  var note=document.getElementById('method-comparison-note');
  if(note){
    note.textContent=cmp.advisory_note||'';
  }

  var tbody=document.querySelector('#method-comparison-table tbody');
  if(tbody){
    var bucketLabels={
      equities:'Aktien',
      bonds:'Obligationen',
      real_estate:'Immobilien',
      alternatives:'Alternative',
      liquidity:'Liquiditaet'
    };
    var active=cmp.active_weights_bps||{};
    var shadow=cmp.shadow_weights_bps||{};
    var deltas=cmp.weight_deltas_bps||{};
    var bucketOrder=['equities','bonds','real_estate','alternatives','liquidity'];
    tbody.innerHTML=bucketOrder.map(function(bucket){
      var d=Number(deltas[bucket]||0);
      var deltaClass=d>0?'delta-pos':(d<0?'delta-neg':'delta-flat');
      var deltaSign=d>0?'+':'';
      return '<tr>'
        +'<td>'+escapeHtml(bucketLabels[bucket]||bucket)+'</td>'
        +'<td>'+escapeHtml(formatBpsPercent(active[bucket]||0))+'</td>'
        +'<td>'+escapeHtml(formatBpsPercent(shadow[bucket]||0))+'</td>'
        +'<td class="'+deltaClass+'">'+escapeHtml(deltaSign+formatBpsPercent(d))+'</td>'
        +'</tr>';
    }).join('');
  }

  // Constraint-Slacks (V3 §5.3 Backend-Output)
  var constraints=Array.isArray(result.optimizer_constraints)?result.optimizer_constraints:[];
  var cBlock=document.getElementById('method-constraints-block');
  var cBody=document.querySelector('#method-constraints-table tbody');
  if(cBody&&cBlock){
    if(!constraints.length){
      cBlock.style.display='none';
    }else{
      cBlock.style.display='';
      cBody.innerHTML=constraints.map(function(c){
        var rowCls='';
        if(c.is_violated)rowCls=' class="is-violated"';
        else if(c.is_binding)rowCls=' class="is-binding"';
        var status=c.is_violated?'Verletzt':(c.is_binding?'Bindend':'Frei');
        var slack=Number(c.slack_bps||0);
        var slackSign=slack>0?'+':'';
        return '<tr'+rowCls+'>'
          +'<td>'+escapeHtml(c.label||c.code||'')+'</td>'
          +'<td>'+escapeHtml(formatBpsPercent(c.value_bps||0))+'</td>'
          +'<td>'+escapeHtml(formatBpsPercent(c.limit_bps||0))+'</td>'
          +'<td>'+escapeHtml(slackSign+formatBpsPercent(slack))+'</td>'
          +'<td>'+escapeHtml(status)+'</td>'
          +'</tr>';
      }).join('');
    }
  }

  // Goal-Drivers (V3 §5.4 Backend-Output)
  var drivers=Array.isArray(result.optimizer_goal_drivers)?result.optimizer_goal_drivers:[];
  var dBlock=document.getElementById('method-drivers-block');
  var dBody=document.querySelector('#method-drivers-table tbody');
  if(dBody&&dBlock){
    if(!drivers.length){
      dBlock.style.display='none';
    }else{
      dBlock.style.display='';
      dBody.innerHTML=drivers.map(function(d){
        // OPTIMIZER-OBJECTIVE-EVIDENCE-PRECISION-001 (2026-10-13): verlustfreier Dezimalstring statt
        // *1000-Fixed-Point; "nicht verfuegbar" != 0 != kleiner Beitrag. Bewusst ungerundet.
        var dec=d.weighted_objective_contribution_decimal;
        var contribText;
        if(dec==null||dec===''){
          contribText='— (nicht verfügbar)';
        }else if(Number(dec)===0){
          contribText='0 (erfüllt)';
        }else{
          contribText=String(dec);
        }
        return '<tr>'
          +'<td>'+escapeHtml(String(d.rank||'—'))+'</td>'
          +'<td>'+escapeHtml(d.label||d.goal_id||'')+'</td>'
          +'<td>'+escapeHtml(d.hardness_key||'')+'</td>'
          +'<td>'+escapeHtml(formatBpsPercent(d.weight_bps||0))+'</td>'
          +'<td>'+escapeHtml(contribText)+'</td>'
          +'</tr>';
      }).join('');
    }
  }

  var audit=document.getElementById('method-comparison-audit');
  if(audit){
    var bits=[
      'Gew\u00e4hlte Methode: '+(cmp.active_method||'—'),
      'Vergleichsmethode: '+(cmp.shadow_method||'—'),
      'Status: '+(cmp.shadow_status||'—')
    ];
    if(cmp.objective_delta_pct!=null){
      bits.push('Differenz Zielfunktion: '+AresRounding.formatPercent(Number(cmp.objective_delta_pct),2,{typography:'screen'}));
    }
    audit.textContent=bits.join(' | ');
  }
}

function renderOptimizerPanel(result){
  var panel=document.getElementById('al-optimizer-panel');
  if(!panel)return;
  var ta=(result&&result.target_allocation)||{};
  var method=ta.optimization_method||null;
  var status=ta.optimization_status||null;
  if(!method){
    panel.style.display='none';
    return;
  }
  panel.style.display='';
  var limitingBadge=document.getElementById('opt-limiting-factor-badge');
  if(limitingBadge){
    var factor=allocationMetaValue(result,'limiting_factor')||'';
    var meta=limitingFactorMeta(factor);
    limitingBadge.textContent=meta.label;
    limitingBadge.className='rv-limiting-badge '+(meta.tone==='danger'?'danger':meta.tone==='warn'?'warn':meta.tone==='good'?'good':'');
    limitingBadge.style.display=factor?'inline-flex':'none';
  }
  var pill=document.getElementById('opt-status-pill');
  if(pill){
    // V3 Sprint 1 Commit 4 (Plan §7.2): Klassen-basierter Status ohne Emoji.
    pill.style.background='';
    pill.style.color='';
    var labelMap={
      converged:'Konvergiert',
      converged_robustified:'Konvergiert (robustifiziert)',
      diverged:'Divergiert',
      diverged_infeasible:'Bandbreite verletzt',
      fallback_house_matrix:'Fallback House-Matrix'
    };
    setStatusPill(pill,status,labelMap[status]||status);
  }
  // Bug-#3 (2026-06-07): Banner-Text pro Status differenzieren. Vorher zeigte
  // jeder Warn-Status den gleichen 'House-Matrix-Default verwendet'-Text,
  // obwohl nur `fallback_house_matrix` tatsaechlich auf die House-Matrix-
  // Mitte zurueckfaellt. Bei `diverged_infeasible` wurden weiterhin die
  // berechneten (aber bandbreiten-verletzenden) Gewichte ausgewiesen —
  // Berater glaubten faelschlich der Fallback waere aktiv.
  var banner=document.getElementById('opt-fallback-banner');
  if(banner){
    var bannerMsg='';
    if(status==='fallback_house_matrix'){
      bannerMsg='Solver konvergierte nicht — Fallback auf House-Matrix-Mittelwert '
        +'(Bandbreiten-Default des Risikoprofils). Die Herleitung unten erkl\u00e4rt, warum.';
    }else if(status==='diverged_infeasible'){
      bannerMsg='Solver hat eine L\u00f6sung berechnet, die ausserhalb der '
        +'House-Matrix-Bandbreiten liegt (Grenzen verletzt). '
        +'Bitte Risikoprofil oder Renditeziel pr\u00fcfen — gezeigte Gewichte '
        +'sind kein g\u00fcltiger Anlagevorschlag.';
    }else if(status==='diverged'){
      bannerMsg='Solver konvergierte nicht. Keine optimale Allokation '
        +'gefunden — die Herleitung unten erkl\u00e4rt, warum. Bitte erneut '
        +'optimieren oder Eingabedaten anpassen.';
    }
    if(bannerMsg){
      banner.style.display='';
      banner.textContent=bannerMsg;
    }else{
      banner.style.display='none';
    }
  }
  var rlist=document.getElementById('opt-reasoning-list');
  if(rlist){
    var allReasoning=Array.isArray(result.reasoning)?result.reasoning:[];
    var solverLines=allReasoning.filter(function(line){
      var s=String(line||'');
      return /Solver|Stochastic|SLSQP|Best objective|iterations|Stress '|Multi-Start|Optimizer/i.test(s);
    });
    if(!solverLines.length)solverLines=allReasoning.slice(0,5);
    rlist.innerHTML=solverLines.map(function(line){
      return '<li style="margin-bottom:3px">'+escapeHtml(String(line))+'</li>';
    }).join('');
  }
  renderOptimizerAchievability(result);
  renderStressTable(result.stress_evaluations||null);
  renderSensitivitySlidersForResult(result);
  var footer=document.getElementById('opt-audit-footer');
  if(footer){
    var seed=ta.optimization_seed!=null?String(ta.optimization_seed):'—';
    var iter=ta.optimization_iterations!=null?String(ta.optimization_iterations):'—';
    var obj=ta.optimization_objective_value_milli!=null?(Number(ta.optimization_objective_value_milli)/1000).toExponential(3):'—';
    footer.textContent='Methode: '+method+' | Status: '+(status||'—')+' | Seed: '+seed+' | Iterationen: '+iter+' | Zielfunktionswert: '+obj;
  }
}
function renderStressTable(stressEvals){
  var block=document.getElementById('opt-stress-block');
  var tbody=document.querySelector('#opt-stress-table tbody');
  if(!block||!tbody){return;}
  tbody.innerHTML='';
  if(!stressEvals||typeof stressEvals!=='object'){
    block.style.display='none';
    return;
  }
  var nameMap={
    great_depression_1929:'Grosse Depression 1929',
    financial_crisis_2008:'Finanzkrise 2008',
    covid_inflation_2020_2022:'Covid + Inflation 2020/22'
  };
  var keys=Object.keys(stressEvals);
  if(!keys.length){
    block.style.display='none';
    return;
  }
  block.style.display='';
  // STRESS-SEMANTICS-001: Drawdown + kumulierte Rendite sind flussfreie
  // Portfolio-Kennzahlen; der Vermoegens-Effekt ist die Differenz zum
  // gleichen Verlauf ohne Krise. Aeltere persistierte Zeilen (ohne die neuen
  // Felder bzw. mit dem alten, flussbehafteten Drawdown) zeigen "—".
  function stressNum(v){
    if(v===null||v===undefined||v===''){return null;}
    var n=Number(v);
    return isFinite(n)?n:null;
  }
  function stressSigned(n,txt){return (n>0?'+':(n<0?'\u2212':''))+txt;}
  keys.forEach(function(name){
    var entry=stressEvals[name]||{};
    var cumBps=stressNum(entry.cumulative_return_bps);
    var impactR=stressNum(entry.crisis_impact_end_wealth_rappen);
    // Ohne cumulative_return_bps stammt max_drawdown_bps aus der alten
    // (flussbehafteten, bis >100 %) Berechnung -> nicht anzeigen.
    var ddBps=cumBps===null?null:stressNum(entry.max_drawdown_bps);
    var rowHighlight=(ddBps!==null&&ddBps>5000)?'background:rgba(220,53,69,0.08);':'';
    var cumTxt=cumBps===null?'—':stressSigned(cumBps,fmtPct(Math.abs(cumBps),1));
    var ddTxt=ddBps===null?'—':fmtPct(-Math.abs(ddBps),1);
    var impactTxt=impactR===null?'—':stressSigned(impactR,AresRounding.formatDecimal(Math.abs(impactR)/100,0,{typography:'screen'}));
    var label=nameMap[name]||String(name);
    var tr=document.createElement('tr');
    tr.style.cssText='border-bottom:1px solid var(--b1);'+rowHighlight;
    tr.innerHTML=''
      +'<td style="padding:5px 8px">'+escapeHtml(label)+'</td>'
      +'<td style="padding:5px 8px;text-align:right;font-family:var(--f-d)">'+escapeHtml(cumTxt)+'</td>'
      +'<td style="padding:5px 8px;text-align:right;font-family:var(--f-d)">'+escapeHtml(ddTxt)+'</td>'
      +'<td style="padding:5px 8px;text-align:right;font-family:var(--f-d)">'+escapeHtml(impactTxt)+'</td>';
    tbody.appendChild(tr);
  });
}
function renderSensitivitySlidersForResult(result){
  var wrap=document.getElementById('opt-sensitivity-list');
  var block=document.getElementById('opt-sensitivity-block');
  if(!wrap||!block){return;}
  wrap.innerHTML='';
  var goals=Array.isArray(result.goal_analysis)?result.goal_analysis:[];
  var mandateId=allocationPayloadMandateId(result);
  if(!goals.length||!mandateId){
    block.style.display='none';
    return;
  }
  block.style.display='';
  goals.forEach(function(g){
    var gid=g&&g.goal_id;
    var label=String(g&&(g.label||g.goal_type)||'Ziel');
    if(!gid)return;
    var row=document.createElement('div');
    row.style.cssText='border:1px solid var(--b1);border-radius:var(--r);padding:8px 10px;display:grid;gap:6px';
    row.innerHTML=''
      +'<div style="display:flex;justify-content:space-between;align-items:center">'
      +  '<span style="font-size:11px;font-weight:500">'+escapeHtml(label)+'</span>'
      +  '<span class="tag tn" style="font-size:9px">Was-w\u00e4re-wenn</span>'
      +'</div>'
      +'<div style="display:flex;gap:4px;flex-wrap:wrap">'
      +  ['-20','-10','0','10','20'].map(function(d){
           return '<button class="btn-p sens-btn" data-goal="'+escapeHtml(gid)+'" data-delta="'+d+'" data-mandate="'+escapeHtml(String(mandateId))+'" style="font-size:10px;padding:4px 10px;background:var(--bg2);color:var(--n6);min-width:0">'+(Number(d)>=0?'+':'')+d+'%</button>';
         }).join('')
      +'</div>'
      +'<div class="sens-result" style="font-size:10px;color:var(--n6);min-height:14px;font-family:var(--f-d)">—</div>';
    wrap.appendChild(row);
  });
  wrap.querySelectorAll('.sens-btn').forEach(function(btn){
    btn.addEventListener('click',function(){
      runSensitivityCall(btn);
    });
  });
}
function runSensitivityCall(btn){
  var gid=btn.getAttribute('data-goal');
  var delta=parseInt(btn.getAttribute('data-delta'),10);
  var mid=btn.getAttribute('data-mandate');
  var resEl=btn.parentElement&&btn.parentElement.parentElement&&btn.parentElement.parentElement.querySelector('.sens-result');
  if(!gid||!mid||isNaN(delta))return;
  if(resEl)resEl.textContent='Berechne…';
  var siblings=btn.parentElement?btn.parentElement.querySelectorAll('button'):[];
  siblings.forEach(function(b){b.disabled=true;});
  var url='/mandates/'+encodeURIComponent(mid)+'/target-allocation/sensitivity';
  API.post(url,{goal_id:gid,target_delta_pct:delta}).then(function(body){
    if(!resEl){return;}
    var dPct=body.delta_objective_pct;
    // GOAL-SENSITIVITY-PUBLICATION-001: Der Zieltyp entscheidet die Einheit.
    // Vorher wurde IMMER target_amount_rappen_new durch 100 geteilt und mit
    // 'CHF' praefixt -- ein Renditeziel von 600 bps erschien dadurch als
    // "CHF 6" statt "6.00% p.a.".
    var msg;
    var amtRappen=body.target_amount_rappen_new;
    if(amtRappen==null&&body.target_return_bps_new!=null){
      msg='Neues Renditeziel: '+fmtPct(Number(body.target_return_bps_new),2)+' p.a.';
    }else{
      msg='Neuer Zielwert: '+formatRappen(Number(amtRappen||0),mandateCurrency());
    }
    if(dPct!=null){
      var direction=Number(dPct)<0?' (besser erreichbar)':(Number(dPct)>0?' (schwerer erreichbar)':'');
      msg+=' | Zielabweichung '+AresRounding.formatPercent(Number(dPct),1,{typography:'screen',signed:true})+direction;
    }else if(body.delta_objective_unavailable_reason){
      // Ohne diesen Zweig blieb das Feld einfach leer -- von "0 %
      // Veraenderung" nicht zu unterscheiden.
      msg+=' | Keine Richtungsaussage: '+body.delta_objective_unavailable_reason;
    }
    resEl.textContent=msg;
  }).catch(function(err){
    if(resEl)resEl.textContent='Fehler: '+(err&&err.message||'unbekannt');
  }).finally(function(){
    siblings.forEach(function(b){b.disabled=false;});
  });
}
// KNOWLEDGE-GAP-ASSET-CLASS-001: SAA-Anlageklassen ohne dokumentierte
// Kenntnis/Aufklaerung (Backend: knowledge_asset_class_check). Reiner Hinweis,
// die Allokation wird dadurch nicht veraendert.
function aaKnowledgeGapCardBody(check,buckets){
  if(!check||check.status!=='gap'||!Array.isArray(check.findings)||!check.findings.length)return '';
  var actions=check.findings.map(function(f){
    var cls=f?(f.asset_class||f.label):'',bps=Number(f&&f.target_weight_bps||0),pct=sollPct(cls,bps,buckets);
    return String(f&&f.label||'Anlageklasse')+' ('+pct+'): '+String(f&&f.action||'');
  });
  return 'Fuer folgende Anlageklassen der Strategie sind weder Kenntnisse noch eine Aufklaerung dokumentiert: '+actions.join(' · ')+' Die Allokation wurde dadurch nicht veraendert.';
}
function renderActionCards(reasoning){
  var el=document.getElementById('aa-action-list');
  if(!el)return;
  var allocation=strategyState&&strategyState.allocation?strategyState.allocation:null;
  var risk=currentPersistedRiskForMandate(getActiveMandateId());
  var mc=allocation?monteCarloPayload(allocation):null;
  var items=[];
  var pushCard=function(title,tagLabel,tagClass,body,accent){
    if(!body)return;
    items.push(aaActionCardHtml(title,tagLabel,tagClass,body,accent));
  };
  if(risk||allocation){
    var profile=(risk&&risk.final_profile)||(allocation&&allocation.house_matrix_profile)||'Nicht definiert';
    var scoreText=risk&&risk.final_score_x10!=null?('Score '+Math.round(Number(risk.final_score_x10||0)/10)+' / 10'):'';
    var horizonText=risk&&risk.investment_horizon_years?('Horizont '+risk.investment_horizon_years+' Jahre'):'';
    var profileBits=[profile,scoreText,horizonText].filter(Boolean);
    var profileBody='Die Soll-Allokation wird vom Profil '+profileBits.join(' · ')+' getragen.';
    if(allocation&&allocation.house_matrix_profile)profileBody+=' Die House View startet aus '+allocation.house_matrix_profile+' und bleibt innerhalb der Risiko-Leitplanken.';
    pushCard('Risikoprofil & Horizont','Zentral','tr2',profileBody,'good');
  }
  if(allocation&&allocation.knowledge_asset_class_check){
    // Reason-Code KNOWLEDGE_GAP_ASSET_CLASS (siehe aaKnowledgeGapCardBody).
    pushCard('Kenntnisse & Anlageklassen','Hinweis','ta',aaKnowledgeGapCardBody(allocation.knowledge_asset_class_check,allocation.buckets),'warn');
  }
  if(allocation){
    var annualNet=allocationRecurringNetCashflowRappen(allocation);
    var reserveNeeded=Math.round(Number(allocation.reserve_needed_rappen||0)/100);
    var externalReserve=Math.round(Number(allocation.external_reserve_rappen||0)/100);
    var liqBucket=(allocation.buckets||[]).filter(function(bucket){return String(bucket.asset_class||'')==='Liquiditaet';})[0]||null;
    var liqTarget=liqBucket?sollPct(liqBucket.asset_class,liqBucket.target_weight_bps,allocation.buckets):'n/a';
    var targetRunwayInfo=projectionRunwayInfo(mc&&mc.target_p50_series_rappen,mc&&mc.year_labels);
    var currentRunwayInfo=projectionRunwayInfo(mc&&mc.current_p50_series_rappen,mc&&mc.year_labels);
    var targetRunway=targetRunwayInfo.label;
    var currentRunway=currentRunwayInfo.label;
    var runwayDeltaYears=targetRunwayInfo.years!=null&&currentRunwayInfo.years!=null?targetRunwayInfo.years-currentRunwayInfo.years:null;
    var cashflowInfo=currentCashflowCoverageInfo();
    var reliefRows=decumulationCapitalBridgeRows(2);
    if(annualNet<0||reserveNeeded>0||externalReserve>0){
      var reserveBody='Der Fall ist im Vermoegensverzehr: laufende Einkommen '+formatRappen(cashflowInfo.incomeRappen,cashflowInfo.currency)+' p.a., Ausgaben '+formatRappen(cashflowInfo.expenseRappen,cashflowInfo.currency)+' p.a., Finanzierungsluecke '+formatSignedRappen(cashflowInfo.netRappen,cashflowInfo.currency)+' p.a..';
      if(cashflowInfo.coveragePct!=null)reserveBody+=' Die laufenden Einkommen decken rund '+AresRounding.formatPercent(cashflowInfo.coveragePct,0,{typography:'screen'})+' der Ausgaben.';
      if(reliefRows.length)reserveBody+=' Einmalige Kapitalereignisse entlasten temporaer: '+reliefRows.map(function(row){return row.year+' '+row.label+' '+formatRappen(row.amountRappen,row.currency);}).join(' und ')+'.';
      reserveBody+=' Die strategische Liquiditaet im Mandat bleibt bei '+liqTarget+'.';
      if(externalReserve>0)reserveBody+=' Zusaetzlich werden '+formatRappen(allocation.external_reserve_rappen)+' als separate Reserve ausserhalb des Mandats empfohlen.';
      else if(reserveNeeded>0)reserveBody+=' Der kurzfristige Reservebedarf liegt bei rund '+formatRappen(allocation.reserve_needed_rappen)+'.';
      if(targetRunway!=='-'||currentRunway!=='-')reserveBody+=' Median-Reichweite: IST '+currentRunway+', SOLL '+targetRunway+'.';
      if(runwayDeltaYears!=null&&runwayDeltaYears>0)reserveBody+=' Die Strategie gewinnt im Median rund '+runwayDeltaYears+' Jahre Zeit.';
      else if(runwayDeltaYears!=null&&runwayDeltaYears===0&&targetRunway!=='-')reserveBody+=' Wichtig: Die Strategie puffert den Entnahmepfad, verlaengert die Reichweite in diesem Setup aber nicht wesentlich. Fuer mehr Reichweite braucht es weniger Entnahme, mehr Vermoegen oder zusaetzliche Einkommen.';
      pushCard('Entnahme & Reichweite','Zentral','tr2',reserveBody,(annualNet<0||externalReserve>0)?'warn':'good');
    }
  }
  if(allocation&&Array.isArray(allocation.goal_analysis)&&allocation.goal_analysis.length){
    var primaryGoal=allocation.goal_analysis.slice().sort(function(a,b){return Number(a.rank||99)-Number(b.rank||99);})[0];
    var goalBody='Prioritaet 1 ist "'+String(primaryGoal.label||'Ziel')+'": '+strategyGoalTargetText(primaryGoal)+' · '+goalTimingLabel(primaryGoal)+'.';
    // GOAL-STATUS-BY-SUCCESS-001: kritisch = Erfolgs-Wkt. < 45 % (Ampel 70/45), nicht Mischwert.
    var primarySuccess=goalSuccessPct(primaryGoal);
    var primaryCritical=primarySuccess!=null&&primarySuccess<45;
    if(primarySuccess!=null)goalBody+=' Aktuelle Erfolgswahrscheinlichkeit: '+fmtProbPct(primarySuccess)+' ('+goalSuccessAmpel(primarySuccess).label+(goalSuccessIsEstimate(primaryGoal)?(', '+GOAL_SUCCESS_ESTIMATE_HINT):'')+').';
    if(primaryGoal.evaluation_note)goalBody+=' '+String(primaryGoal.evaluation_note);
    else if(primaryCritical)goalBody+=' Das Ziel ist im aktuellen Setup kritisch und braucht eine explizite Besprechung im Review.';
    pushCard('Ziele & Timing','Relevant','ta',goalBody,primaryCritical?'warn':'good');
  }
  if(allocation){
    var expectedReturn=fmtPct((Number(allocation.expected_return_bps||0)),1);
    var expectedVol=fmtPct((Number(allocation.expected_volatility_bps||0)),1);
    var varText=formatRiskLossBps(mc&&mc.target_var_95_1y_bps);
    var ddText=formatRiskLossBps(mc&&mc.target_max_drawdown_p50_bps);
    var riskBody='Die Strategie rechnet langfristig mit rund '+expectedReturn+' p.a. bei einer Volatilitaet von '+expectedVol+'. In einem schwachen Jahr liegt der modellierte VaR 95% bei '+varText+', der mediane Max Drawdown bei '+ddText+'.';
    pushCard('Ertrag & Risiko','Relevant','ta',riskBody,'');
  }
  var leftoverReasoning=(Array.isArray(reasoning)?reasoning:[]).filter(function(text){
    var raw=String(text||'');
    return raw && !/Liquiditaet|Reserve|Cashflow|House Matrix fuer Score|Risky Fraction|Pfadsimulation|KNOWLEDGE_GAP_ASSET_CLASS/i.test(raw);
  }).slice(0,2);
  if(leftoverReasoning.length)pushCard('Leitplanken & Engine','Einordnung','tn',leftoverReasoning.join(' '),'');
  if(!items.length){
    items=[
      aaActionCardHtml('Risikoprofil & Horizont','Zentral','tr2','Die Soll-Allokation richtet sich nach Risikoprofil, Anlagehorizont und dem priorisierten Zielpfad.','good'),
      aaActionCardHtml('House View & Leitplanken','Relevant','ta','Bandbreiten, Restriktionen und Kapitalmarktannahmen begrenzen die Strategie bewusst und machen sie nachvollziehbar.',''),
      aaActionCardHtml('Naechster Schritt','Einordnung','tn','Vergleiche zur Umsetzung, Entscheidungen und die eigentliche Dokumentation erfolgen anschliessend im Review.','')
    ];
  }
  el.innerHTML=items.join('');
}
// 2026-07-24: Geschaeftsmodell-bewusste Formulierung fuer Band-Abweichungen.
// Zwei unabhaengige Achsen bestimmen die Sprache, NICHT nur eine:
// (a) illiquide Anlageklassen (aktuell: Immobilien) sind fuer NIEMANDEN per
//     Handelsliste rebalancierbar -- auch nicht fuer Vermoegensverwaltung.
// (b) reine Anlageberatung/Finanzplanung/Reporting-only hat keine
//     Ausfuehrungsbefugnis -- "Rebalancing erforderlich" impliziert faelschlich,
//     dass die Firma selbst handelt. Nur Vermoegensverwaltung bekommt die
//     operative Rebalancing-Sprache + Handelsliste.
function _reviewIsIlliquidAssetClass(assetKey){
  var k=String(assetKey||'').toLowerCase();
  return k.indexOf('immob')>=0;
}
function _reviewIsDiscretionaryMandate(){
  var mandateType=(currentMandateData&&currentMandateData.mandate_type)||'';
  var hasExecutionAuthority=mandateType==='Vermögensverwaltung';
  // HUD-Polish (2026-08-03, User-Direktive): der Wealthmanagement/Consulting-
  // Praesentationsmodus steuert zusaetzlich, ob die operative Rebalancing-/
  // Handelsliste-Sprache am Ende des Beratungsprozesses gezeigt wird.
  // mandate_type bleibt die COMPLIANCE-UNTERGRENZE -- eine Anlageberatung
  // ohne Ausfuehrungsbefugnis zeigt NIE eine Handelsliste, unabhaengig vom
  // Praesentationsmodus. Der Praesentationsmodus kann die operative Ansicht
  // zusaetzlich AUSBLENDEN (Consulting-Modus zeigt nur die Ziel-/SOLL-
  // Empfehlung, "wie es sein sollte"), aber nie Ausfuehrungsbefugnis
  // vortaeuschen, die real nicht besteht (daher UND, nicht ODER).
  return hasExecutionAuthority && getCurrentPresentationMode()==='wealthmanagement';
}
function reviewBandStateMeta(bucket,assetKey){
  var target=Number(bucket&&bucket.target_weight_bps||0);
  var current=Number(bucket&&bucket.current_weight_bps||0);
  var min=Number(bucket&&bucket.band_min_bps||0);
  var max=Number(bucket&&bucket.band_max_bps||0);
  var delta=current-target;
  var pointBand=max>0&&max===min, hasBand=max>min||pointBand; // Live-Test H6: Punktband (min==max>0) ist ein Band; 0/0 = kein Band
  var illiquid=_reviewIsIlliquidAssetClass(assetKey);
  var discretionary=_reviewIsDiscretionaryMandate();
  if(hasBand&&(current<min||current>max)){
    return {
      label:'Verletzt',
      tagClass:'tr2',
      tone:'var(--neg)',
      action: illiquid ? 'Bei naechster Transaktion/Gespraech beruecksichtigen'
        : (discretionary ? 'Rebalancing erforderlich' : 'Empfehlung anpassen')
    };
  }
  var bandSpan=hasBand?(max-min):1000;
  var edgeBuffer=Math.max(100,Math.round(bandSpan*0.2));
  var nearEdge=hasBand?Math.min(Math.abs(current-min),Math.abs(max-current)):9999;
  if(hasBand&&!pointBand&&nearEdge<=edgeBuffer&&Math.abs(delta)>=50){ // "Band eng" nur bei echter Abweichung vom Ziel (Live-Test H6)
    return {
      label:'Band eng',
      tagClass:'ta',
      tone:'var(--warn)',
      action: illiquid ? 'Beobachten'
        : (discretionary ? 'Rebalancing prüfen' : 'Beobachten und im Gespräch ansprechen')
    };
  }
  return {
    label:'Im Band',
    tagClass:'tg',
    tone:'var(--pos)',
    action:Math.abs(delta)>=200?'Beobachten':'Keine Aktion'
  };
}
function reviewLiveDriftsBackedByHoldings(live){return !!live&&Number(live.holding_positions_count||0)>0&&Number(live.implied_positions_count||0)===0;} // Live-Test H6: ohne echte Bestaende ist Live-IST = Zielbetrag ("implied_from_target")
function reviewStrategyComparisonRows(allocation){
  var live=liveRebalancingPayload(allocation), liveBuckets=(reviewLiveDriftsBackedByHoldings(live)&&Array.isArray(live.bucket_drifts))?live.bucket_drifts:[];
  if(liveBuckets.length){
    return liveBuckets.map(function(bucket){
      return {
        assetKey:String(bucket.asset_class||'').toLowerCase(),
        assetClass:assetDisplayName(bucket.asset_class||'Anlageklasse'),
        currentWeightBps:Number(bucket.current_weight_bps||0),
        targetWeightBps:Number(bucket.target_weight_bps||0),
        deltaWeightBps:Number(bucket.delta_weight_bps||0),
        currentRappen:Number(bucket.current_market_value_rappen||0),
        targetRappen:Number(bucket.target_market_value_rappen||0),
        bandMinBps:Number(bucket.band_min_bps||0),
        bandMaxBps:Number(bucket.band_max_bps||0)
      };
    }).sort(function(a,b){
      return reviewAssetClassSortKey(a.assetKey)-reviewAssetClassSortKey(b.assetKey);
    });
  }
  var buckets=allocation&&Array.isArray(allocation.buckets)?allocation.buckets:[];
  return buckets.map(function(bucket){
    return {
      assetKey:String(bucket.asset_class||'').toLowerCase(),
      assetClass:assetDisplayName(bucket.asset_class||'Anlageklasse'),
      currentWeightBps:Number(bucket.current_weight_bps||0),
      targetWeightBps:Number(bucket.target_weight_bps||0),
      deltaWeightBps:Number(bucket.current_weight_bps||0)-Number(bucket.target_weight_bps||0),
      currentRappen:Number(bucket.current_amount_rappen||0),
      targetRappen:Number(bucket.target_amount_rappen||0),
      bandMinBps:Number(bucket.band_min_bps||0),
      bandMaxBps:Number(bucket.band_max_bps||0)
    };
  }).sort(function(a,b){
    return reviewAssetClassSortKey(a.assetKey)-reviewAssetClassSortKey(b.assetKey);
  });
}
function reviewImplementationHotspots(recommendation){
  var positions=recommendation&&Array.isArray(recommendation.positions)?recommendation.positions:[];
  if(!positions.length)return [];
  var totalCurrent=positions.reduce(function(sum,row){return sum+portfolioMarketValueRappen(row);},0);
  var totalTarget=positions.reduce(function(sum,row){return sum+Number(row&&row.target_amount_rappen||0);},0);
  var denominator=Math.max(1,totalCurrent||totalTarget);
  var groups={};
  positions.forEach(function(row){
    var label=String(row.sub_asset_class||row.asset_class||row.product_name||'Umsetzung');
    if(!groups[label]){
      groups[label]={
        label:label,
        assetClass:assetDisplayName(row.asset_class||'Baustein'),
        currentRappen:0,
        targetRappen:0
      };
    }
    groups[label].currentRappen+=portfolioMarketValueRappen(row);
    groups[label].targetRappen+=Number(row.target_amount_rappen||0);
  });
  return Object.keys(groups).map(function(key){
    var item=groups[key];
    item.currentWeightBps=Math.round(item.currentRappen/denominator*10000);
    item.targetWeightBps=Math.round(item.targetRappen/denominator*10000);
    item.deltaWeightBps=item.currentWeightBps-item.targetWeightBps;
    return item;
  }).filter(function(item){
    return Math.abs(Number(item.deltaWeightBps||0))>=200;
  }).sort(function(a,b){
    return Math.abs(Number(b.deltaWeightBps||0))-Math.abs(Number(a.deltaWeightBps||0));
  }).slice(0,3);
}
function reviewAllocationPortraitHtml(rows){
  if(!rows||!rows.length)return '';
  function getColor(key){ return assetClassCssVar(key); }
  var totalIst=rows.reduce(function(s,r){return s+Math.max(0,Number(r.currentWeightBps||0));},0)||10000;
  var totalSoll=rows.reduce(function(s,r){return s+Math.max(0,Number(r.targetWeightBps||0));},0)||10000;
  var pm=function(f){return AresRounding.bucketPctMap(rows.map(function(r){return {asset_class:r.assetKey,target_weight_bps:Math.max(0,Number(r[f]||0))};}),{typography:'screen'});},sollM=pm('targetWeightBps'),istM=pm('currentWeightBps');
  // AA-UX-COLORS-001: Textfarbe je Klassenflaeche (WCAG AA), nicht pauschal Weiss
  // (Weiss auf Gold/Grau waere < 3:1).
  function seg(bps,total,key,label,m){
    var pct=Math.max(0,bps/total*100);
    if(pct<0.3)return '';
    return '<div style="width:'+pct.toFixed(2)+'%;background:'+getColor(key)+';display:flex;align-items:center;justify-content:center;overflow:hidden" title="'+escapeHtml(label)+': '+escapeHtml(m[key]||formatBpsPercent(bps))+'">'
      +(pct>=9?'<span style="font-size:8px;color:'+assetClassTextOn(key)+';font-weight:700;white-space:nowrap;font-variant-numeric:tabular-nums">'+escapeHtml(m[key]||formatBpsPercent(bps))+'</span>':'')
      +'</div>';
  }
  var sollBar=rows.map(function(r){return seg(Math.max(0,Number(r.targetWeightBps||0)),totalSoll,r.assetKey,r.assetClass,sollM);}).join('');
  var istBar=rows.map(function(r){return seg(Math.max(0,Number(r.currentWeightBps||0)),totalIst,r.assetKey,r.assetClass,istM);}).join('');
  var legend=rows.map(function(r){
    var meta=r.meta;
    var hasIssue=meta&&meta.tagClass&&meta.tagClass!=='tg';
    return '<div style="display:flex;align-items:center;gap:4px">'
      +'<div style="width:8px;height:8px;border-radius:2px;background:'+getColor(r.assetKey)+';flex-shrink:0"></div>'
      +'<span style="font-size:9px;color:var(--n6)">'+escapeHtml(r.assetClass)+'</span>'
      +(hasIssue?'<span class="tag '+meta.tagClass+'" style="font-size:8px;padding:1px 5px;line-height:14px">'+escapeHtml(meta.label)+'</span>':'')
      +'</div>';
  }).join('');
  return '<div style="margin-bottom:14px;padding:12px 14px;background:var(--bg);border:1px solid var(--b1);border-radius:var(--r2)">'
    +'<div style="font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;color:var(--n4);margin-bottom:10px">Allokation — IST vs. SOLL</div>'
    +'<div style="display:flex;align-items:center;gap:8px;margin-bottom:5px">'
    +'<span style="font-size:9px;color:var(--n5);width:28px;flex-shrink:0;text-align:right">SOLL</span>'
    +'<div style="flex:1;height:30px;display:flex;border-radius:4px;overflow:hidden;border:1px solid rgba(15,23,42,0.1)">'+sollBar+'</div>'
    +'</div>'
    +'<div style="display:flex;align-items:center;gap:8px;margin-bottom:10px">'
    +'<span style="font-size:9px;color:var(--n5);width:28px;flex-shrink:0;text-align:right">IST</span>'
    +'<div style="flex:1;height:30px;display:flex;border-radius:4px;overflow:hidden;border:1px solid rgba(15,23,42,0.1)">'+istBar+'</div>'
    +'</div>'
    +'<div style="display:flex;flex-wrap:wrap;gap:6px 16px;padding-left:36px">'+legend+'</div>'
    +'</div>';
}
var _rvSpiegelChart=null;
var _rvSpiegelLoadToken=0;

async function loadReviewSpiegel(_mandateId){
  // Bug-#11 (2026-06-07): No-op. Strategie-Spiegel-Card aus dem Review-Tab
  // entfernt; Loader macht nichts mehr. Backend-Drift-Endpoint bleibt fuer
  // Aggregator/PDFs verfuegbar (siehe ADR-009 / Aggregator-Statement-PM).
}
function renderReviewStrategyComparison(_state){
  // Bug-#9 (2026-06-07): No-op. Portfolio-Check-Card im Review-Tab
  // entfaellt (Rebalancing-/IST-vs-SOLL-Logik raus). Zielerreichung
  // wird vom Cockpit (rv-goal-achievability-list) gerendert; Beratungs-
  // protokoll bleibt im Dokumente-Hub.
  var root=document.getElementById('rv-strategy-compare');
  if(root){root.innerHTML='';}
  return;
}
var _renderStrategySummaryGoalTiming=renderStrategySummary;
renderStrategySummary=function(){
  _renderStrategySummaryGoalTiming();
  var allocation=strategyState.allocation;
  var goals=document.getElementById('sr-goal-priority-list');
  if(goals&&allocation){
    goals.innerHTML=(allocation.goal_analysis||[]).slice(0,4).map(function(goal){
      var success=goalSuccessPct(goal);
      var ampel=goalSuccessAmpel(success);
      var score=success==null?0:success;
      var tone=ampel.tone;
      var statusLabel=ampel.label;
      var bgColor=ampel.bg;
      return '<div>'
        +'<div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:5px">'
        +'<div><span style="font-size:9px;font-weight:600;color:var(--n5);margin-right:5px">RANG '+escapeHtml(String(goal.rank||'—'))+'</span><span style="font-size:11px;font-weight:500;color:var(--n8)">'+escapeHtml(goal.label||'Ziel')+'</span></div>'
        +'<div style="display:flex;align-items:center;gap:7px"><span style="font-size:12px;font-weight:700;color:'+tone+'" title="'+escapeHtml(GOAL_SUCCESS_PROBABILITY_TOOLTIP+(goalSuccessIsEstimate(goal)?(' \u2013 '+GOAL_SUCCESS_ESTIMATE_HINT):''))+'">'+(success==null?'\u2014':fmtProbPct(success))+(goalSuccessIsEstimate(goal)?'*':'')+'</span>'
        +'<span style="font-size:9px;color:'+tone+';background:'+bgColor+';border-radius:999px;padding:2px 7px">'+escapeHtml(statusLabel)+'</span>'
        +'</div></div>'
        +'<div style="position:relative;height:6px;background:var(--bg2);border-radius:999px;margin-bottom:2px">'
        +'<div style="position:absolute;left:0;top:0;height:100%;width:'+score+'%;background:'+tone+';border-radius:999px;transition:width 0.4s"></div>'
        +'</div></div>';
    }).join('');
  }
  // Update allocation bars with asset class colors
  var srBars=document.getElementById('sr-allocation-bars');
  if(srBars&&allocation){
    function srAcColor2(ac){return assetClassCssVar(ac);}
    srBars.innerHTML=(allocation.buckets||[]).map(function(bucket){
      var pct=Math.max(0,Math.min(100,Math.round(Number(bucket.target_weight_bps||0)/100)));
      var targetValue=formatRappen(Number(bucket.target_amount_rappen||0));
      var color=srAcColor2(bucket.asset_class);
      return '<div style="display:grid;grid-template-columns:8px 94px 1fr 54px 86px;gap:6px;align-items:center">'
        +'<div style="width:8px;height:8px;border-radius:2px;background:'+color+';flex-shrink:0"></div>'
        +'<span style="font-size:10px;color:var(--n6)">'+escapeHtml(assetDisplayName(bucket.asset_class))+'</span>'
        +'<div style="height:7px;background:var(--bg2);border-radius:3px"><div style="width:'+pct+'%;height:100%;background:'+color+';border-radius:3px;opacity:0.85"></div></div>'
        +'<span style="font-size:10px;font-weight:600;color:var(--n7);text-align:right">'+sollPct(bucket.asset_class,bucket.target_weight_bps,allocation.buckets)+'</span>'
        +'<span style="font-size:10px;color:var(--n5);text-align:right">'+escapeHtml(targetValue)+'</span>'
        +'</div>';
    }).join('');
  }
  // Always refresh the implementation steps so Massnahmen card is never empty
  if(typeof renderSrImplementationDecision==='function')renderSrImplementationDecision(null);
};
document.addEventListener('DOMContentLoaded',function(){
  var rpPage=document.getElementById('page-rp');
  if(rpPage&&rpPage.dataset.riskDirtyBound!=='1'){
    rpPage.dataset.riskDirtyBound='1';
    rpPage.addEventListener('click',function(event){
      var box=event&&event.target&&event.target.closest?event.target.closest('.qcb'):null;
      if(!box||!rpPage.contains(box))return;
      riskAssessmentUiDirty=true;
      if(typeof calcRiskScore==='function')calcRiskScore();
    });
    ['rp-income-annual','rp-obligations-annual'].forEach(function(id){
      var field=document.getElementById(id);
      if(!field||field.dataset.riskDirtyBound==='1')return;
      field.dataset.riskDirtyBound='1';
      field.addEventListener('input',function(){riskAssessmentUiDirty=true;});
      field.addEventListener('change',function(){riskAssessmentUiDirty=true;});
    });
  }
  syncGoalModalState();
  syncPortfolioUmsetzenButtonVisibility();
  normalizeReviewLayout();
  normalizeVisibleMojibake(document.body);
});
