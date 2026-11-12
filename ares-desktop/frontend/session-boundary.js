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
var aresSessionHardResetInProgress=false;
function aresHardResetSession(){
  aresSessionPrincipal=null;
  aresSessionHardResetInProgress=true; // beforeunload-Warnung nicht beim gewollten Neustart
  try{window.location.reload();return true;}catch(e){return false;}
}
// H9 Nachtrag 4: Logout aus dem Monolithen hierher verschoben (Sitzungsgrenze an
// einer Stelle: Rueckfrage bei ungesicherten Eingaben, Tokens raeumen, Neustart).
async function doLogout() {
  // H9 N-892-06: ungesicherte Eingaben nicht stillschweigend verwerfen.
  if (typeof aresConfirmDiscardBeforeLogout === 'function' && !(await aresConfirmDiscardBeforeLogout())) return;
  try { await API.post('/auth/logout', {}); } catch(e) { console.error('[ares] logout:', e); }
  await API.setToken(null);
  await API.setRefreshToken(null);
  currentUser = null;
  // H9 N-892-02: kein mandatsbezogener Zustand ueber die Sitzungsgrenze.
  if (typeof aresHardResetSession === 'function' && aresHardResetSession()) return;
  const label = document.getElementById('current-user-label');
  if (label) label.textContent = '';
  const logoutBtn = document.getElementById('btn-logout');
  if (logoutBtn) logoutBtn.style.display = 'none';
  const adminBtn = document.getElementById('btn-admin-open');
  if (adminBtn) adminBtn.style.display = 'none';
  ensureFoundationExampleButton();
  const status = await checkBootstrapStatus();
  if (status && status.setup_required) showBootstrap();
  else showLogin();
}
