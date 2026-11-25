/* Ares -- L2d / N-938-01 (CTO 2026-11-22). Teil des Monolith-Bundles.
 * Massnahme eines Interessenkonflikts ist eine Kategorie, kein Freitext.
 * Dieselbe Liste wie die CHECK-Regel (ares_schema.sql) und die API
 * (schemas/review.py ConflictMitigationAction); Details gehoeren in die
 * versiegelte Beschreibung. Leer = noch keine Massnahme (null an die API). */
var CONFLICT_MITIGATION_ACTIONS=['Weitergabe an Kunden','Ablehnung','Offenlegung ohne Mitigation','Strukturelle Massnahme'];
function fillConflictMitigationSelect(sel){
  if(!sel||sel.tagName!=='SELECT')return;
  sel.innerHTML='';
  [''].concat(CONFLICT_MITIGATION_ACTIONS).forEach(function(v){
    var o=document.createElement('option');o.value=v;o.textContent=v||'Noch keine Massnahme';sel.appendChild(o);
  });
}
fillConflictMitigationSelect(document.getElementById('nco-mitigation'));
