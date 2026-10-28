// HANDOFF-PREVIEW-PARITY-001 / HANDOFF-NEWMONEY-UI-001: Handelsliste (#m-tl).
// Ausgelagert aus 5eyes_v2.html (Monolith-Budget, Toleranz 0). Laedt als
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

function renderTradeListUnavailable(body,detail){
  var html='<div style="font-size:11px;color:var(--n6);padding:12px">'+escapeHtml(detail.message||'Keine Handelsliste verfügbar.')+'</div>';
  if(detail.reason_code===TRADE_LIST_NO_HOLDINGS_REASON){
    html+='<div style="padding:0 12px 12px"><button class="btn" id="tl-confirm-no-holdings" onclick="confirmNoExistingHoldingsForTradeList()">Kein bestehender Bestand (Neugeld) bestätigen</button></div>';
  }
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
    var chf=Math.round(Math.abs(rappen||0)/100);
    var sign=(rappen||0)<0?'−':'+';
    if(chf>=1000000)return sign+'CHF '+formatCompactCHFAmount(chf);
    if(chf>=1000)return sign+'CHF '+Math.round(chf/1000)+'k';
    return sign+'CHF '+chf;
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
