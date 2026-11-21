// HANDOFF-PREVIEW-PARITY-001 / HANDOFF-NEWMONEY-UI-001: Handelsliste (#m-tl).
// Ausgelagert aus ares.html (Monolith-Budget, Toleranz 0). Laedt als
// klassisches Skript und nutzt die globalen Helfer des Monolithen (API, om,
// uiConfirm, escapeHtml, formatRappen, formatBpsPercent, formatCompactCHFAmount,
// strategyState, getActiveMandateId, renderPortfolioHandoffSection,
// _tlHandoffCtx); diese werden erst beim Aufruf aufgeloest.
//
// Die Liste wird NICHT mehr clientseitig aus live_rebalancing gerechnet,
// sondern ist die read-only Vorschau des Servers: dieselbe Funktion wie der
// Snapshot einer Weiterleitung (services/portfolio_handoff.py::snapshot_handoff),
// also dieselben Zeilen inkl. Kaeufen nicht gehaltener Produkte und Liquiditaet.
var TRADE_LIST_NO_HOLDINGS_REASON='NO_HOLDINGS_CONFIRMATION_REQUIRED';

function tradeListPreviewUrl(mandateId,runId,confirmNoHoldings){
  return '/mandates/'+encodeURIComponent(mandateId)+'/recommendations/'+encodeURIComponent(runId)
    +'/portfolio-handoff-preview?confirm_no_existing_holdings='+(confirmNoHoldings?'true':'false');
}

function tradeListErrorDetail(e){
  var parsed=null;
  try{parsed=e&&e.body?JSON.parse(e.body):null;}catch(parseErr){parsed=null;}
  var detail=parsed&&parsed.detail;
  if(detail&&typeof detail==='object'&&detail.reason_code){
    return {reason_code:String(detail.reason_code),message:String(detail.message||'')};
  }
  return {reason_code:null,message:String((e&&e.detail)||(e&&e.message)||'Handelsliste konnte nicht geladen werden.')};
}

async function openTradeList(confirmNoHoldings){
  var body=document.getElementById('m-tl-body');
  if(!body)return;
  var result=strategyState.recommendation;
  var runId=result&&result.run&&result.run.id?String(result.run.id):null;
  var mandateId=getActiveMandateId();
  var confirmed=confirmNoHoldings===true;
  _tlHandoffCtx={mandateId:mandateId,runId:runId,confirmNoHoldings:confirmed};
  if(!mandateId||!runId){
    body.innerHTML='<div style="font-size:11px;color:var(--n5);padding:12px">Keine Handelsliste verfügbar.</div>';
    om('m-tl');
    return;
  }
  body.innerHTML='<div style="font-size:11px;color:var(--n5);padding:12px">Handelsliste wird berechnet…</div>';
  om('m-tl');
  var preview;
  try{
    preview=await API.get(tradeListPreviewUrl(mandateId,runId,confirmed));
  }catch(e){
    renderTradeListUnavailable(body,tradeListErrorDetail(e));
    return;
  }
  renderTradeListPreview(body,preview);
  renderPortfolioHandoffSection();
}

// K2/E2E-09: Ist im Vermoegen ein Wertschriftendepot (Beratungsvermoegen) erfasst,
// ist Neugeld fachlich falsch -- angeboten wird die Bestandserfassung. Preis-
// Sperren nennen den Weg zu Preisen. Technische Parameternamen nie im Text.
function tradeListAdvisoryDepots(){
  var list=typeof currentWealthPositions!=='undefined'&&Array.isArray(currentWealthPositions)?currentWealthPositions:[];
  return list.filter(function(p){return p&&p.position_type==='Depot'&&p.assignment==='Beratungsvermögen';});
}
function tradeListGuideButton(label,action){
  return '<button class="btn btn-sm" type="button" onclick="'+action+'">'+escapeHtml(label)+'</button>';
}
function renderTradeListUnavailable(body,detail){
  var msg=String(detail.message||'Keine Handelsliste verfügbar.').replace(/\s*\(confirm_no_existing_holdings\)/g,'');
  var html='<div style="font-size:11px;color:var(--n6);padding:12px">'+escapeHtml(msg)+'</div>';
  var guide='';
  if(detail.reason_code===TRADE_LIST_NO_HOLDINGS_REASON){
    var depots=tradeListAdvisoryDepots();
    if(depots.length){
      guide='<b>Umschichtung eines bestehenden Depots.</b> Im Vermögen ist ein Wertschriftendepot im Beratungsvermögen erfasst ('
        +escapeHtml(depots.map(function(p){return p.label||'Depot';}).join(', '))+'). Erfassen Sie die gehaltenen Titel als Bestand '
        +'(Stück oder Marktwert mit Stichtag); erst dann rechnet die Handelsliste Käufe und Verkäufe aus dem echten Bestand. '
        +'Titel, die nicht in der Empfehlung stehen, erfassen Sie als «Titel ausserhalb der Empfehlung» (Marktwert mit Stichtag).'
        +'<div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap">'+tradeListGuideButton('Bestand erfassen',"cm('m-tl');openPortfolioPositionHelper()")
        +tradeListGuideButton('Titel ausserhalb der Empfehlung erfassen','openExternalHoldingsEditor()')+'</div>';
    }else{
      html+='<div style="padding:0 12px 12px"><button class="btn" id="tl-confirm-no-holdings" onclick="confirmNoExistingHoldingsForTradeList()">Kein bestehender Bestand (Neugeld) bestätigen</button></div>';
    }
  }else if(/ausserhalb der Empfehlung/.test(msg)){
    guide='<b>Titel ausserhalb der Empfehlung nicht bewertbar.</b> Ohne Marktwert, Stichtag und Wechselkurs gibt es keine Handelsliste.'
      +'<div style="margin-top:8px">'+tradeListGuideButton('Titel ausserhalb der Empfehlung bearbeiten','openExternalHoldingsEditor()')+'</div>';
  }else if(/Marktpreis|Preise/.test(msg)){
    guide='<b>Preise fehlen oder sind veraltet.</b> So kommen Preise ins System: '
      +'1. Datenübermittlung an die Kursquellen freigeben (Administration › Compliance › Datenschutz, nur Admin). '
      +'2. Portfolio › ⋯ › Live-Preise abrufen. Danach die Handelsliste neu öffnen.'
      +'<div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap">'
      +tradeListGuideButton('Live-Preise abrufen',"cm('m-tl');refreshLivePricesForMandate()")
      +(typeof currentUser!=='undefined'&&currentUser&&currentUser.role==='admin'?tradeListGuideButton('Datenschutz-Freigabe öffnen',"cm('m-tl');openAdminModal();adminShowSection('sec-privacy-gov');loadPrivacyGovernance()"):'')
      +'</div>';
  }
  if(guide)html+='<div id="tl-guide" role="note" style="margin:0 12px 12px;padding:10px 12px;border:1px solid var(--b1);border-radius:var(--r);background:var(--bg);font-size:11px;line-height:1.5;color:var(--n7)">'+guide+'</div>';
  body.innerHTML=html;
}

// HANDOFF-NEWMONEY-UI-001: ausdrueckliche Bestaetigung ueber den Dialog-
// Service (kein nativer Dialog). Erst danach rechnet der Server alle Zeilen
// als Kauf mit IST = 0; dieselbe Bestaetigung geht mit der Weiterleitung mit.
async function confirmNoExistingHoldingsForTradeList(){
  var ok=await uiConfirm({
    title:'Kein bestehender Bestand',
    message:'Bestätigen Sie, dass für dieses Mandat kein bestehendes Depot und kein Wertschriftenbestand existiert (Neugeld). Alle Positionen werden dann als Kauf mit IST = 0 auf Basis des investierbaren Beratungsvermögens ausgewiesen.',
    okLabel:'Bestätigen',
    cancelLabel:'Abbrechen'
  });
  if(ok!==true)return;
  await openTradeList(true);
}

function renderTradeListPreview(body,preview){
  var trades=Array.isArray(preview&&preview.trades)?preview.trades:[];
  var totalBuy=0,totalSell=0;
  trades.forEach(function(p){
    var amt=p.rebalance_amount_rappen||0;
    if(p.rebalance_action_code==='BUY')totalBuy+=amt;
    else if(p.rebalance_action_code==='SELL')totalSell+=amt;
  });
  var actionColor=function(action){
    if(action==='BUY')return 'var(--pos)';
    if(action==='SELL')return 'var(--neg)';
    return 'var(--n5)';
  };
  var fmtDelta=function(rappen){
    var chf=Math.abs(rappen||0)/100,ccy=typeof appCurrency==='function'?appCurrency():null;
    if(!ccy)return '—';  // G7 N4: Waehrung unbekannt -> keine geratene Einheit
    var sign=(rappen||0)<0?'−':'+';
    if(chf>=1000000)return sign+ccy+' '+formatCompactCHFAmount(chf);
    if(chf>=1000)return sign+ccy+' '+fmtNumber(chf/1000,0)+'k';
    return sign+ccy+' '+fmtNumber(chf,0);
  };
  var hasExternal=trades.some(isExternalTradeRow);
  var rows=trades.map(function(p){
    var color=actionColor(p.rebalance_action_code);
    var outside=isExternalTradeRow(p)?'<div style="font-size:9px;font-weight:600;color:var(--n5)">ausserhalb der Empfehlung · Vorschlag</div>':'';
    return '<tr style="border-bottom:1px solid var(--b1)">'
      +'<td style="padding:6px 8px;font-size:11px;font-weight:500">'+escapeHtml(p.product_name||'')+outside+'</td>'
      +'<td style="padding:6px 8px;font-size:10px;color:var(--n5)">'+escapeHtml(p.sub_asset_class||p.asset_class||'')+'</td>'
      +'<td style="padding:6px 8px;font-size:10px;font-weight:700;color:'+color+'">'+escapeHtml(p.rebalance_action||'')+'</td>'
      +'<td style="padding:6px 8px;font-size:10px;text-align:right">'+escapeHtml(formatRappen(p.current_market_value_rappen))+'</td>'
      +'<td style="padding:6px 8px;font-size:10px;text-align:right">'+escapeHtml(formatRappen(p.target_amount_rappen))+'</td>'
      +'<td style="padding:6px 8px;font-size:10px;text-align:right;font-weight:600;color:'+color+'">'+escapeHtml(fmtDelta(p.rebalance_amount_rappen))+'</td>'
      +'<td style="padding:6px 8px;font-size:10px;text-align:right">'+escapeHtml(formatBpsPercent(p.target_weight_bps))+'</td>'
      +'</tr>';
  }).join('');
  var basisLabel=preview&&preview.holdings_basis==='confirmed_no_holdings'
    ?'Basis: bestätigtes Neugeld (kein bestehender Bestand)'
    :'Basis: erfasster Depotbestand inkl. bewerteter Liquidität';
  var thS='padding:6px 8px;text-align:left;font-size:9px;font-weight:600;letter-spacing:0.07em;text-transform:uppercase;color:var(--n4);border-bottom:2px solid var(--b1)';
  var thR=thS+';text-align:right';
  body.innerHTML='<div style="margin-bottom:10px;font-size:11px;color:var(--n5)">'
    +escapeHtml(String(trades.length))+' Positionen'
    +' &middot; Kaufvolumen: <span style="color:var(--pos)">'+escapeHtml(formatRappen(totalBuy))+'</span>'
    +' &middot; Verkaufsvolumen: <span style="color:var(--neg)">'+escapeHtml(formatRappen(totalSell))+'</span>'
    +' &middot; '+escapeHtml(basisLabel)
    +'</div>'
    +'<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse">'
    +'<thead><tr>'
    +'<th style="'+thS+'">Wertpapier</th>'
    +'<th style="'+thS+'">Anlageklasse</th>'
    +'<th style="'+thS+'">Aktion</th>'
    +'<th style="'+thR+'">IST-Wert</th>'
    +'<th style="'+thR+'">SOLL-Wert</th>'
    +'<th style="'+thR+'">Delta</th>'
    +'<th style="'+thR+'">Soll-%</th>'
    +'</tr></thead>'
    +'<tbody>'+rows+'</tbody>'
    +'</table></div>'
    +(hasExternal?'<div role="note" style="margin-top:8px;font-size:11px;color:var(--n6);line-height:1.5">'
      +'Titel ausserhalb der Empfehlung: «Verkauf prüfen» ist ein Vorschlag. Verkaufen oder halten entscheidet der Kunde; '
      +'es wird nichts automatisch verkauft. Ihr Wert zählt zum erfassten Depot (IST), ihr SOLL ist 0.</div>':'')
    +'<div style="margin-top:8px">'+tradeListGuideButton('Titel ausserhalb der Empfehlung bearbeiten','openExternalHoldingsEditor()')+'</div>'
    +'<div id="m-tl-handoff"></div>';
}

// K3 / N-915-06: Titel ausserhalb der Empfehlung (Fremdbestand) am Depot im
// Beratungsvermoegen erfassen. Server: GET/PUT /mandates/{id}/external-holdings.
// Fehlt Marktwert oder Stichtag, bleibt der Titel "nicht bewertbar" (kein
// Ersatzwert). Speichern aendert den Bestand: die Empfehlung muss danach neu
// finalisiert und publiziert werden (keine automatische Neuberechnung).
function isExternalTradeRow(p){return !!p&&p.holding_origin==='external_holding';}
var EXTERNAL_ASSET_CLASSES=['Aktien','Obligationen','Immobilien','Alternative Anlagen','Liquidität'];
function externalMinorDigits(ccy){return /^(JPY|KRW|CLP|ISK)$/.test(String(ccy||'').toUpperCase())?0:2;}
function externalAmountToMinor(text,ccy){
  var raw=String(text||'').replace(/['\s]/g,'').replace(',','.');
  if(!raw)return null;
  // Exakt aus dem Text (keine Gleitkomma-Rundung bei Geldbetraegen): mehr
  // Nachkommastellen als die Waehrung hat -> ungueltig, nie still gerundet.
  var m=/^(\d+)(?:\.(\d+))?$/.exec(raw),digits=externalMinorDigits(ccy);
  if(!m||(m[2]||'').length>digits)return NaN;
  var frac=(m[2]||'');while(frac.length<digits)frac+='0';
  var minor=parseInt(m[1]+frac,10);
  return minor>0&&minor<=Number.MAX_SAFE_INTEGER?minor:NaN;
}
function externalMinorToText(minor,ccy){
  if(minor===null||minor===undefined)return '';
  return String(minor/Math.pow(10,externalMinorDigits(ccy)));
}
function externalHoldingRowHtml(item){
  item=item||{};
  var opts=EXTERNAL_ASSET_CLASSES.map(function(c){return '<option'+(item.asset_class===c?' selected':'')+'>'+escapeHtml(c)+'</option>';}).join('');
  var st=item.status&&item.status!=='ok'?'<div style="font-size:10px;color:var(--neg)">'+escapeHtml(item.status_text||'nicht bewertbar')+'</div>':'';
  var inp='padding:3px 4px;font-size:11px;border:1px solid var(--b1);border-radius:4px';
  return '<tr class="ext-row">'
    +'<td><input class="ext-label" aria-label="Bezeichnung" style="'+inp+';width:140px" value="'+escapeHtml(item.label||'')+'">'+st+'</td>'
    +'<td><input class="ext-isin" aria-label="ISIN (optional)" style="'+inp+';width:110px" value="'+escapeHtml(item.isin||'')+'"></td>'
    +'<td><select class="ext-class" aria-label="Anlageklasse" style="'+inp+'">'+opts+'</select></td>'
    +'<td><input class="ext-ccy" aria-label="Währung" style="'+inp+';width:44px" value="'+escapeHtml(item.currency||(typeof appCurrency==='function'&&appCurrency())||'')+'"></td>'
    +'<td><input class="ext-value" aria-label="Marktwert" style="'+inp+';width:90px;text-align:right" value="'+escapeHtml(externalMinorToText(item.market_value_rappen,item.currency))+'"></td>'
    +'<td><input class="ext-date" type="date" aria-label="Stichtag" style="'+inp+'" value="'+escapeHtml(item.valuation_date||'')+'"></td>'
    +'<td><button class="btn btn-sm" type="button" data-ext-action="remove" aria-label="Titel entfernen">×</button></td>'
    +'</tr>';
}
function readExternalHoldingRows(table){
  var items=[],errors=[];
  Array.prototype.forEach.call(table.querySelectorAll('tr.ext-row'),function(tr,i){
    var get=function(cls){var el=tr.querySelector('.'+cls);return el?String(el.value||'').trim():'';};
    var label=get('ext-label'),ccy=get('ext-ccy').toUpperCase(),value=externalAmountToMinor(get('ext-value'),ccy);
    if(!label&&!get('ext-value')&&!get('ext-isin'))return;
    if(!label)errors.push('Zeile '+(i+1)+': Bezeichnung fehlt.');
    if(!/^[A-Z]{3}$/.test(ccy))errors.push('Zeile '+(i+1)+': Währung als dreistelliger Code (ISO 4217).');
    if(value!==value)errors.push('Zeile '+(i+1)+': Marktwert als positive Zahl (höchstens so viele Nachkommastellen wie die Währung) erfassen oder leer lassen.');
    items.push({label:label,isin:get('ext-isin')||null,asset_class:get('ext-class'),currency:ccy,
      market_value_rappen:value===value?value:null,valuation_date:get('ext-date')||null});
  });
  return {items:items,errors:errors};
}
async function openExternalHoldingsEditor(){
  var body=document.getElementById('m-tl-body');
  var mandateId=getActiveMandateId();
  if(!body||!mandateId)return;
  om('m-tl');
  body.innerHTML='<div style="font-size:11px;color:var(--n5);padding:12px">Titel ausserhalb der Empfehlung werden geladen…</div>';
  var data;
  try{data=await API.get('/mandates/'+encodeURIComponent(mandateId)+'/external-holdings');}
  catch(e){body.innerHTML='<div style="font-size:11px;color:var(--n6);padding:12px">'+escapeHtml(tradeListErrorDetail(e).message)+'</div>';return;}
  renderExternalHoldingsEditor(body,mandateId,data);
}
function renderExternalHoldingsEditor(body,mandateId,data,notice){
  var depots=(data&&data.depots)||[];
  var th='padding:4px;text-align:left;font-size:9px;font-weight:600;text-transform:uppercase;color:var(--n4)';
  var head='<tr><th style="'+th+'">Bezeichnung</th><th style="'+th+'">ISIN</th><th style="'+th+'">Anlageklasse</th>'
    +'<th style="'+th+'">Währung</th><th style="'+th+'">Marktwert</th><th style="'+th+'">Stichtag</th><th></th></tr>';
  var html='<div style="font-size:11px;line-height:1.5;color:var(--n7);margin-bottom:8px"><b>Titel ausserhalb der Empfehlung.</b> '
    +'Gehaltene Titel, die nicht in der Empfehlung stehen, mit Marktwert und Stichtag aus dem Depotauszug. '
    +'Ohne Marktwert oder Stichtag bleibt ein Titel «nicht bewertbar» – dann gibt es keine Handelsliste und keine Bandaussage. '
    +'Titel der Empfehlung erfassen Sie bei der Empfehlungsposition.</div>';
  if(notice)html+='<div role="status" style="font-size:11px;margin-bottom:8px;color:var(--n7)">'+escapeHtml(notice)+'</div>';
  if(!depots.length){
    body.innerHTML=html+'<div style="font-size:11px;color:var(--n6)">Im Vermögen ist kein aktives Wertschriftendepot im Beratungsvermögen erfasst.</div>';
    return;
  }
  depots.forEach(function(d,idx){
    html+='<div style="margin-top:10px;font-size:11px;font-weight:600">'+escapeHtml(d.depot_label||'Depot')+'</div>'
      +'<div style="overflow-x:auto"><table class="ext-table" data-idx="'+idx+'" data-wp="'+escapeHtml(d.wealth_position_id)+'" style="border-collapse:collapse">'
      +'<thead>'+head+'</thead><tbody>'+((d.items||[]).map(externalHoldingRowHtml).join('')||externalHoldingRowHtml({}))+'</tbody></table></div>'
      +'<div style="margin-top:6px;display:flex;gap:6px;flex-wrap:wrap">'
      +'<button class="btn btn-sm" type="button" data-ext-action="add" data-idx="'+idx+'">Titel hinzufügen</button>'
      +'<button class="btn btn-sm" type="button" data-ext-action="save" data-idx="'+idx+'">Speichern</button></div>';
  });
  body.innerHTML=html;
  body.onclick=function(ev){
    var btn=ev.target&&ev.target.closest?ev.target.closest('[data-ext-action]'):null;
    if(!btn)return;
    var action=btn.getAttribute('data-ext-action');
    if(action==='remove'){btn.closest('tr').remove();return;}
    var table=body.querySelector('table.ext-table[data-idx="'+btn.getAttribute('data-idx')+'"]');
    if(!table)return;
    if(action==='add')table.querySelector('tbody').insertAdjacentHTML('beforeend',externalHoldingRowHtml({}));
    if(action==='save')saveExternalHoldings(body,mandateId,table);
  };
}
async function saveExternalHoldings(body,mandateId,table){
  var read=readExternalHoldingRows(table);
  if(read.errors.length){uiAlert({level:'warn',message:read.errors.join(' ')});return;}
  var data;
  try{
    data=await API.put('/mandates/'+encodeURIComponent(mandateId)+'/external-holdings/'
      +encodeURIComponent(table.getAttribute('data-wp')),{items:read.items});
  }catch(e){uiAlert({level:'warn',message:tradeListErrorDetail(e).message});return;}
  var notice='Gespeichert. Der Bestand hat sich geändert: Empfehlung neu finalisieren und publizieren, danach die Handelsliste öffnen.'
    +(data&&data.unvalued_count?' '+data.unvalued_count+' Titel nicht bewertbar.':'');
  renderExternalHoldingsEditor(body,mandateId,data,notice);
}
