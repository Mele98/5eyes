// GOAL-ANALYSIS-INTEGRITY-001 / SHADOW-ANALYSIS-INTEGRITY-001: ruhiger
// Berater-Hinweis, wenn die gespeicherte Zielanalyse oder der Shadow-Container
// der aktuellen Strategie ihren Integritaetsnachweis verletzen
// (GET /mandates/{id}/target-allocation/current/analysis-integrity). Reiner
// Hinweis: die Kanaele zeigen die Analyse dann ohnehin nicht; er sagt nur warum.
// Ausgelagert neben den Monolithen (Monolith-Budget, Toleranz 0), zusammen mit
// renderGoalAchievementSollIst (unveraendert verschoben). Klassisches Skript;
// die Monolith-Helfer (API, escapeHtml, getActiveMandateId, isDemoMandateId,
// fmtProbPct, fmtLocaleCH, GOAL_SUCCESS_PROBABILITY_TOOLTIP, goalAmpelLegendHtml)
// werden erst beim Aufruf aufgeloest.
var GOAL_ANALYSIS_INTEGRITY_BOX_ID='aa-goal-integrity';

function _goalAnalysisIntegrityBox(){
  var box=document.getElementById(GOAL_ANALYSIS_INTEGRITY_BOX_ID);
  if(box)return box;
  var anchor=document.getElementById('aa-goal-sollist');
  if(!anchor||!anchor.parentNode||typeof document.createElement!=='function')return null;
  box=document.createElement('div');
  box.id=GOAL_ANALYSIS_INTEGRITY_BOX_ID;
  box.setAttribute('role','status');
  box.style.display='none';
  box.style.margin='0 0 8px';
  box.style.fontSize='11px';
  box.style.color='var(--n5)';
  anchor.parentNode.insertBefore(box,anchor);
  return box;
}

function renderGoalAnalysisIntegrity(report){
  var box=_goalAnalysisIntegrityBox();
  if(!box)return;
  if(!report||report.needs_attention!==true){
    box.style.display='none';
    box.innerHTML='';
    box.dataset.integrity='';
    return;
  }
  box.dataset.integrity=[report.goal_analysis,report.shadow_analysis].join('|');
  box.innerHTML='<span style="display:inline-block;margin-right:6px;padding:0 6px;border:1px solid var(--b1);'
    +'border-radius:var(--r);font-weight:600;text-transform:uppercase;letter-spacing:.04em">'
    +escapeHtml(String(report.label||'Zielanalyse nicht verifizierbar'))+'</span>'
    +(report.text?escapeHtml(report.text):'');
  box.style.display='block';
}

async function refreshGoalAnalysisIntegrity(mid){
  var requested=String(mid||'');
  if(!requested||isDemoMandateId(requested)){
    renderGoalAnalysisIntegrity(null);
    return null;
  }
  try{
    var res=await API.get('/mandates/'+requested+'/target-allocation/current/analysis-integrity');
    if(String(getActiveMandateId()||'')!==requested)return null;
    renderGoalAnalysisIntegrity(res);
    return res;
  }catch(e){
    if(String(getActiveMandateId()||'')===requested)renderGoalAnalysisIntegrity(null);
    return null;
  }
}

// #36/PAR-3 (2026-06-15): Zielerreichung je Ziel SOLL vs IST. Liest result.goal_analysis
// (SOLL) + result.current_goal_analysis (IST, vom Backend deterministisch). Graceful:
// bleibt versteckt, solange das IST-Payload fehlt (kein Regress fuer Alt-Berechnungen).
function renderGoalAchievementSollIst(result){
  var el=document.getElementById('aa-goal-sollist'); if(!el)return;
  var soll=(result&&Array.isArray(result.goal_analysis))?result.goal_analysis:[];
  var ist=(result&&Array.isArray(result.current_goal_analysis))?result.current_goal_analysis:[];
  if(!soll.length||!ist.length){ el.style.display='none'; el.innerHTML=''; return; }
  var istById={}; ist.forEach(function(g){ if(g&&g.goal_id!=null) istById[String(g.goal_id)]=g; });
  var pct=function(v){ var n=Number(v); return isFinite(n)?fmtProbPct(Math.max(0,Math.min(100,Math.round(n)))):'—'; };
  var chf=function(r){ var n=Number(r||0); return n>0?('CHF '+fmtLocaleCH(Math.round(n/100))):'—'; };
  var tone=function(v){ var n=Number(v||0); return n>=70?'var(--pos)':(n>=45?'var(--warn)':'var(--neg)'); };
  // UX-1 (Befund 8): Primaerkennzahl = Erfolgswahrscheinlichkeit (path_success_rate_pct,
  // nur aus der Simulation; ohne Simulationswert '—', kein deterministischer 0/100-Ersatz).
  // Sekundaer: Erreichungsgrad im mittleren Szenario (median_achievement_pct = Median,
  // NICHT P25) und der Fehlbetrag im unguenstigen Szenario (P25-Pfad).
  var successOf=function(g){ return g&&g.path_success_rate_pct!=null?g.path_success_rate_pct:null; };
  var successCell=function(v,strong){ return '<td style="text-align:right;padding:6px 8px;'+(strong?'font-weight:600;':'')+'color:'+(v==null?'var(--n5)':tone(v))+'">'+(v==null?'—':pct(v))+'</td>'; };
  var rows=soll.map(function(g){
    var i=istById[String(g.goal_id)]||{};
    return '<tr style="border-bottom:1px solid var(--bg2)">'
      +'<td style="padding:6px 8px;font-family:var(--f);color:var(--n7)">'+escapeHtml(g.label||'Ziel')+'</td>'
      +successCell(successOf(g),true)
      +successCell(successOf(i),false)
      +'<td style="text-align:right;padding:6px 8px;color:var(--n6)" title="Erreichungsgrad im mittleren Szenario (Median), SOLL / IST">'+pct(g.median_achievement_pct)+' / '+pct(i.median_achievement_pct)+'</td>'
      +'<td style="text-align:right;padding:6px 8px;color:var(--n6)" title="Fehlbetrag im ung\u00fcnstigen Szenario (P25), SOLL / IST">'+chf(g.pessimistic_shortfall_rappen)+' / '+chf(i.pessimistic_shortfall_rappen)+'</td>'
      +'</tr>';
  }).join('');
  el.style.display='';
  el.innerHTML='<div style="border:1px solid var(--b1);border-radius:8px;overflow:hidden">'
    +'<div style="font-size:9px;text-transform:uppercase;letter-spacing:0.06em;color:var(--n4);font-weight:600;padding:8px 8px 4px">Erfolgswahrscheinlichkeit je Ziel — SOLL vs IST</div>'
    +'<table style="width:100%;border-collapse:collapse;font-size:11px"><thead>'
    +'<tr style="border-bottom:1px solid var(--b1)"><th style="text-align:left;padding:5px 8px;font-size:9px;text-transform:uppercase;color:var(--n4)">Ziel</th>'
    +'<th style="text-align:right;padding:5px 8px;font-size:10px;color:var(--soll)" title="'+escapeHtml(GOAL_SUCCESS_PROBABILITY_TOOLTIP)+' (SOLL-Strategie)">Erfolgs-Wkt. SOLL</th>'
    +'<th style="text-align:right;padding:5px 8px;font-size:10px;color:var(--n6)" title="'+escapeHtml(GOAL_SUCCESS_PROBABILITY_TOOLTIP)+' (heutige Anlage)">IST</th>'
    +'<th style="text-align:right;padding:5px 8px;font-size:9px;text-transform:uppercase;color:var(--n4)" title="Erreichungsgrad im mittleren Szenario (Median), SOLL / IST">Erreichungsgrad (Median) S/I</th>'
    +'<th style="text-align:right;padding:5px 8px;font-size:9px;text-transform:uppercase;color:var(--n4)" title="Fehlbetrag im ung\u00fcnstigen Szenario (P25), SOLL / IST">Fehlbetrag ung\u00fcnstig (P25) S/I</th></tr>'
    +'</thead><tbody style="font-family:var(--f-d)">'+rows+'</tbody></table>'
    +'<div style="padding:4px 8px 6px">'+goalAmpelLegendHtml()+'</div></div>';
}
