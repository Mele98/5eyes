/* Ares -- P5c (H-186, CTO-Entscheide 2026-11-21). Teil des Monolith-Bundles.
 * N-930-01: goalStatusView -- einzige Anzeige-Hilfe fuer den Zielstatus (M-3).
 * N-930-02: loadStrategyOnly -- Klicks mit anderer Absicht rechnen nie neu. */
// P5c / N-930-01 (CTO 2026-11-21): M-3 ist die einzige Quelle des Zielstatus.
// Wort und Farbe kommen vom Server (status_label/status_color/status_bg/status_tone
// aus core/goal_metric_contract.GOAL_STATUS_DISPLAY); fehlen sie: "nicht bewertbar"
// (fail-closed), nie eine Ampel aus der Erfolgswahrscheinlichkeit.
function goalStatusView(item){
  var T={good:['tg','fg','\u25cf'],warn:['ta','fa','\u25d0'],bad:['tr2','fr','\u25cb'],neutral:['tn','fa','\u25cb']};
  var ok=!!(item&&item.status&&item.status_label&&item.status_color);
  var ui=T[ok?String(item.status_tone||''):'neutral']||T.neutral;
  var color=ok?String(item.status_color):'var(--n5)';
  return {key:ok?String(item.status):'nicht_bewertbar',label:ok?String(item.status_label):'nicht bewertbar',
    tone:color,color:color,bg:ok?String(item.status_bg||'var(--bg2)'):'var(--bg2)',tag:ui[0],bar:ui[1],icon:ui[2]};
}
/* P5c / N-930-02 (CTO 2026-11-21): Bestand speichern/loeschen und Empfehlung
 * finalisieren laden nur die aktuelle Strategie (nie target-allocation/generate
 * ausser bei 404 = noch nie berechnet). 409 (veraltet): Abbruch, dirty, Hinweis
 * "Veraltet - Ursache" aus mandate-view.js; Finalisieren erst nach "Anlagestrategie
 * berechnen". Ausstehende lokale Aenderungen (dirty) bleiben markiert. */
async function loadStrategyOnly(withRec){
  var was=!!strategyState.dirty,note=strategyState.staleNotice,ok=false;
  strategyState.dirty=false;strategyState.lastGeneratedAt=0;
  try{ok=await refreshStrategyData(false,withRec);}
  finally{if(was&&!strategyState.dirty){strategyState.dirty=true;strategyState.staleNotice=note;if(typeof syncStrategyStaleView==='function')syncStrategyStaleView();}}
  return ok;
}
