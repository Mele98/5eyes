/* Ares -- Wechselkurs-Editor (Administration).
 * CCX-P3-FX (N-909-11, 2026-11-18): aus ares.html ausgelagert (Monolith-Budget).
 * Ein Kurs gilt nur als belegt, wenn ihn jemand bewusst erfasst oder bestaetigt
 * hat. Ersatzkurse sind Platzhalter (kein vorbelegter Wert) und sichtbar als
 * "Ersatzkurs – nicht belegt" gekennzeichnet. Gesendet werden nur Zeilen, die
 * der Berater geaendert oder je Zeile ausdruecklich als "Kurs geprueft"
 * bestaetigt hat (Quelle Manual, Datum heute). Teil des Monolith-Bundles. */
function fxIsSubstituteSource(source){
  return String(source==null?'':source).trim().toLowerCase()==='default'||String(source==null?'':source).trim()==='';
}
// Reine Funktion: Zeilen {currency,value,original,confirmed} -> PUT-Payload.
// Unveraenderte, nicht bestaetigte Zeilen werden nie gesendet.
function fxRatesSavePayload(rows){
  var out=[];
  (rows||[]).forEach(function(row){
    var ccy=String(row&&row.currency||'').toUpperCase().trim();
    if(!ccy||ccy==='CHF')return;
    var raw=String(row.value==null?'':row.value).trim();
    if(!raw)return; // Platzhalter (Ersatzkurs) ohne Eingabe: nichts senden
    var rate=Number(raw);
    if(!isFinite(rate)||rate<=0)return;
    var original=String(row.original==null?'':row.original).trim();
    var changed=!original||Number(original)!==rate;
    var confirmed=row.confirmed===true;
    if(!changed&&!confirmed)return;
    var entry={currency:ccy,rate:rate,source:'Manual'};
    if(confirmed)entry.confirm_current=true;
    out.push(entry);
  });
  return {rates:out};
}
async function loadAdminFxRates(){
  var grid=document.getElementById('admin-fx-rates-grid');
  var status=document.getElementById('admin-fx-rates-status');
  if(!grid)return;
  grid.innerHTML='<div style="grid-column:span 4;font-size:10px;color:var(--n5);text-align:center;padding:8px">Laedt...</div>';
  if(status)status.textContent='';
  try{
    var rates=await API.get('/fx-rates/current');
    if(!Array.isArray(rates)){rates=[];}
    grid.innerHTML='';
    rates.forEach(function(entry){
      var ccy=String(entry.currency||'').toUpperCase();
      if(ccy==='CHF')return; // CHF nicht editierbar (immer 1.0)
      var rate=Number(entry.rate||0);
      var substitute=fxIsSubstituteSource(entry.source);
      var shown=rate>0?rate.toFixed(4):'';
      var hint=substitute
        ?'<span style="color:var(--neg);font-weight:600">Ersatzkurs – nicht belegt</span>'
        :'<span style="color:var(--n3);font-weight:400">('+escapeHtml(String(entry.source||''))+', '+escapeHtml(String(entry.valid_from||'').slice(0,10))+')</span>';
      var cell=document.createElement('div');
      cell.innerHTML='<label style="font-size:9px;color:var(--n4);display:block;margin-bottom:2px">'+escapeHtml(ccy)+' '+hint+'</label>'+
        '<input class="fi admin-fx-rate-input" data-currency="'+escapeHtml(ccy)+'" data-original="'+(substitute?'':escapeHtml(shown))+'" type="number" step="0.0001" min="0.0001" '+
        (substitute?'placeholder="'+escapeHtml(shown)+'" value=""':'value="'+escapeHtml(shown)+'"')+' style="font-size:11px">'+
        '<label style="font-size:9px;color:var(--n4);display:flex;gap:4px;align-items:center;margin-top:2px">'+
        '<input type="checkbox" class="admin-fx-rate-confirm" data-currency="'+escapeHtml(ccy)+'"> Kurs geprüft (Quelle Manual, Datum heute)</label>';
      grid.appendChild(cell);
    });
    if(status)status.textContent='Geladen: '+rates.length+' Wechselkurse. Ersatzkurse sind nur Platzhalter und werden nie gespeichert.';
  }catch(e){
    grid.innerHTML='<div style="grid-column:span 4;color:var(--neg);font-size:10px">Fehler beim Laden: '+escapeHtml(String(e&&(e.detail||e.message)||'?'))+'</div>';
  }
}
function adminFxRateRows(){
  var inputs=document.querySelectorAll('.admin-fx-rate-input');
  var confirms={};
  document.querySelectorAll('.admin-fx-rate-confirm').forEach(function(box){
    confirms[String(box.getAttribute('data-currency')||'')]=box.checked===true;
  });
  var rows=[];
  for(var i=0;i<inputs.length;i++){
    var el=inputs[i];
    var ccy=el.getAttribute('data-currency');
    rows.push({currency:ccy,value:el.value,original:el.getAttribute('data-original'),confirmed:confirms[ccy]===true});
  }
  return rows;
}
async function saveAdminFxRates(){
  var status=document.getElementById('admin-fx-rates-status');
  var payload=fxRatesSavePayload(adminFxRateRows());
  if(!payload.rates.length){
    if(status){status.textContent='Keine geaenderten oder als geprueft bestaetigten Kurse.';status.style.color='var(--neg)';}
    return;
  }
  if(status){status.textContent='Speichert...';status.style.color='var(--n5)';}
  try{
    await API.put('/fx-rates',payload);
    if(status){
      status.textContent='Gespeichert: '+payload.rates.length+' Kurse.';
      status.style.color='var(--pos)';
    }
    try{if(window.showAppSuccess)showAppSuccess('Wechselkurse gespeichert',{title:'FX-Rates'});}catch(noticeErr){}
    await loadAdminFxRates();
  }catch(e){
    var msg=parseApiError(e,'FX-Rates konnten nicht gespeichert werden.');
    if(status){status.textContent=msg;status.style.color='var(--neg)';}
    try{if(window.showAppError)showAppError(msg);}catch(noticeErr){}
  }
}
