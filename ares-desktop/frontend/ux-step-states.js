/* Ares -- UX-L0 (Codex-UX-Audit 25.11.2026, UX-CH-02). Teil des Monolith-Bundles.
 * Die Schrittanzeige leitete "OK" allein aus der Position ab: jeder zurueck-
 * liegende Schritt galt als erledigt, auch mit sichtbar fehlenden Stammdaten.
 * Jetzt drei getrennte Zustaende:
 *   current  -- aktuelle Seite;
 *   visited  -- zurueckliegend, Nummer bleibt, KEIN Haken (nur besucht);
 *   complete -- nur wenn dieselbe Pruefung, die auf der Seite den Vollstaendig-
 *               keitsstatus anzeigt, den Schritt als vollstaendig belegt. Ohne
 *               solche Pruefung bleibt ein Schritt fail-closed "besucht". */
var STEP_COMPLETENESS={
  sd:function(){return computeStammdatenCompleteness().complete===true;}
};
function stepIsComplete(stepKey){
  var check=STEP_COMPLETENESS[stepKey];
  if(!check)return false;
  try{return check()===true;}catch(e){return false;}
}
var _currentStepPage='sd';
function renderStepStates(p){
  if(p)_currentStepPage=p;
  if(!document.getElementById('ux-step-states-css')&&document.head){
    var st=document.createElement('style');
    st.id='ux-step-states-css';
    st.textContent='.tstep.visited{color:rgba(255,255,255,0.7);}'
      +'.tstep.visited .sn{background:transparent;border:1px solid rgba(255,255,255,0.45);color:rgba(255,255,255,0.8);}';
    document.head.appendChild(st);
  }
  var idx=pages[_currentStepPage];
  document.querySelectorAll('.tnav .tstep').forEach(function(s,i){
    s.classList.remove('active','done','visited');
    var sn=s.querySelector('.sn');
    var stepKey=s.dataset.page||Object.keys(pages)[i];
    var stepIdx=pages[stepKey];
    var complete=stepIdx!==idx&&stepIsComplete(stepKey);
    if(stepIdx===idx){s.classList.add('active');if(sn)sn.textContent=i+1;}
    else if(complete){s.classList.add('done');if(sn)sn.textContent='OK';}
    else if(stepIdx<idx){s.classList.add('visited');if(sn)sn.textContent=i+1;}
    else if(sn){sn.textContent=i+1;}
    s.dataset.stepState=stepIdx===idx?'current':(complete?'complete':(stepIdx<idx?'visited':'open'));
    // A11Y-GP-001: aria-selected folgt dem sichtbaren aktiven Schritt.
    s.setAttribute('aria-selected',stepIdx===idx?'true':'false');
  });
}
