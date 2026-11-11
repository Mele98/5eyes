// H9 Nachtrag (N-892-02, Vertragskriterium 7 Mandats-/Tenantreinheit):
// Sitzungsgrenze. Beim Abmelden und bei der Anmeldung eines ANDEREN Benutzers
// darf kein mandatsbezogener Zustand der vorigen Sitzung (Mandant, Strategie-/
// Stale-Status, Grafiken, Kacheln, Banner, Entwuerfe im DOM) sichtbar bleiben.
// Statt jede Ansicht einzeln zurueckzusetzen (fehleranfaellig, die Maske hat
// hunderte mandatsbezogene Felder) wird die Seite neu geladen: das ist
// beweisbar derselbe Zustand wie ein frischer Start. Die Tokens sind vorher
// geraeumt (Logout) bzw. bereits fuer den neuen Benutzer gesetzt (Wechsel) --
// der Start fuehrt dann zur Anmeldung bzw. laedt erst danach die Daten des
// neuen Benutzers. Das Intro laeuft je Sitzung nur einmal (sessionStorage).
// Ausgelagerter Monolith-Teil (Bundle, Budget, Verbots-Guards).
var aresSessionPrincipal=null;
function aresPrincipalKey(user){
  if(!user)return null;
  var id=String(user.id||user.username||'');
  if(!id)return null;
  return id+'|'+String(user.tenant_id==null?'main':user.tenant_id);
}
function markAresSessionPrincipal(user){
  aresSessionPrincipal=aresPrincipalKey(user);
}
function aresSessionPrincipalChanged(user){
  var key=aresPrincipalKey(user);
  return !!(aresSessionPrincipal&&key&&key!==aresSessionPrincipal);
}
function aresHardResetSession(){
  aresSessionPrincipal=null;
  try{window.location.reload();return true;}catch(e){return false;}
}
