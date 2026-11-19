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
        +'Titel, die nicht in der Empfehlung stehen, lassen sich hier noch nicht erfassen – die Liste ist dann keine Handelsinstruktion.'
        +'<div style="margin-top:8px">'+tradeListGuideButton('Bestand erfassen',"cm('m-tl');openPortfolioPositionHelper()")+'</div>';
    }else{
      html+='<div style="padding:0 12px 12px"><button class="btn" id="tl-confirm-no-holdings" onclick="confirmNoExistingHoldingsForTradeList()">Kein bestehender Bestand (Neugeld) bestätigen</button></div>';
    }
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
  var rows=trades.map(function(p){
    var color=actionColor(p.rebalance_action_code);
    return '<tr style="border-bottom:1px solid var(--b1)">'
      +'<td style="padding:6px 8px;font-size:11px;font-weight:500">'+escapeHtml(p.product_name||'')+'</td>'
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
    +'<div id="m-tl-handoff"></div>';
}
