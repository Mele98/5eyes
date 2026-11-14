// H9 Nachtrag 4 (N-892-06, Entscheid Owner-Vertretung): zentrale Erkennung
// ungesicherter Eingaben in den Kundenmasken: vor dem Logout-Neustart fragt
// Ares nach, beforeunload warnt; bei Sitzungsablauf mit Benutzerwechsel KEIN
// Dialog (Datenschutz), nach dem Neustart ein Hinweis auf verworfene Eingaben.
// Ausgelagerter Monolith-Teil (Bundle, Budget, Verbots-Guards).
//
// Erkennung (ein dirty-Flag je Quelle):
//  - Risikoprofil-Fragebogen: bestehendes riskAssessmentUiDirty.
//  - Formular-Dialoge der Kundenmasken (Stammdaten, Mandat, Vermoegen,
//    Cashflow, Zufluss, Ziele, Ereignisse, Risiko-Override, Mandats-
//    einstellungen): Eingabe markiert, schliessen/neu oeffnen setzt zurueck.
//  - ESG (E2): Karte #sust-card (kein Dialog); Neuaufbau setzt zurueck.
var ARES_CUSTOMER_FORM_MODALS={
  'm-es':'Stammdaten','m-nc':'Mandat','m-mandate-settings':'Mandat-Einstellungen',
  'm-aw':'Vermögensposition','m-edit-depot':'Vermögensposition','m-edit-hypo':'Hypothek/Kredit',
  'm-edit-custom':'Vermögensposition','m-edit-immo':'Immobilie','m-awi':'Vermögenszufluss',
  'm-acf':'Cashflow','m-nz':'Ziel','m-goalrev':'Ziel','m-ev':'Lebensereignis',
  'm-overr':'Risikoprofil-Override'
};
var aresUnsavedModals={},aresUnsavedEsgEl=null;
var ARES_DISCARD_NOTICE_KEY='ares.unsavedDiscarded';
function aresModalIsOpen(id){
  var el=(typeof document!=='undefined'&&document.getElementById)?document.getElementById(id):null;
  return !!(el&&el.classList&&el.classList.contains('open'));
}
function aresUnsavedModalOpened(id){if(id)delete aresUnsavedModals[id];}
function aresMarkUnsavedFromEvent(ev){
  var t=ev&&ev.target;
  var c=t&&typeof t.closest==='function',modal=c?t.closest('.overlay'):null;
  if(modal&&modal.id&&Object.prototype.hasOwnProperty.call(ARES_CUSTOMER_FORM_MODALS,modal.id))aresUnsavedModals[modal.id]=true;
  if(c&&t.closest('#sust-card'))aresUnsavedEsgEl=t;
}
// Quellen mit ungesicherten Eingaben (Bezeichnungen fuer den Dialog).
function aresUnsavedSources(){
  var out=[];
  if(typeof riskAssessmentUiDirty!=='undefined'&&riskAssessmentUiDirty)out.push('Risikoprofil-Fragebogen');
  Object.keys(aresUnsavedModals).forEach(function(id){
    if(aresUnsavedModals[id]&&aresModalIsOpen(id)){
      var label=ARES_CUSTOMER_FORM_MODALS[id];
      if(out.indexOf(label)<0)out.push(label);
    }
  });
  if(aresUnsavedEsgEl&&aresUnsavedEsgEl.isConnected)out.push('Nachhaltigkeit');
  return out;
}
function hasAresUnsavedChanges(){return aresUnsavedSources().length>0;}
// Logout: nachfragen, wenn ungesicherte Eingaben offen sind. true = abmelden.
async function aresConfirmDiscardBeforeLogout(){
  var sources=aresUnsavedSources();
  if(!sources.length)return true;
  var msg='Ungespeicherte Änderungen gehen verloren – trotzdem abmelden? (Betroffen: '+sources.join(', ')+')';
  if(typeof uiConfirm==='function'){
    try{return !!(await uiConfirm({title:'Ungespeicherte Änderungen',message:msg,okLabel:'Trotzdem abmelden',cancelLabel:'Abbrechen'}));}
    catch(e){return false;}
  }
  return false; // ohne Dialog-Service nicht stillschweigend verwerfen
}
// Sitzungsablauf mit Benutzerwechsel: kein Dialog, nur Merker fuer den Hinweis.
function aresRememberDiscardedForNotice(){
  if(!hasAresUnsavedChanges())return;
  try{sessionStorage.setItem(ARES_DISCARD_NOTICE_KEY,'1');}catch(e){}
}
function aresShowDiscardNoticeIfAny(){
  var flagged=false;
  try{flagged=sessionStorage.getItem(ARES_DISCARD_NOTICE_KEY)==='1';sessionStorage.removeItem(ARES_DISCARD_NOTICE_KEY);}catch(e){}
  if(!flagged)return false;
  var text='Ungesicherte Eingaben der vorherigen Sitzung wurden beim Benutzerwechsel aus Datenschutzgründen verworfen.';
  if(typeof showAppNotice==='function'){
    try{showAppNotice({level:'warning',title:'Eingaben verworfen',message:text,durationMs:15000});return true;}catch(e){}
  }
  if(typeof uiAlert==='function'){try{uiAlert({title:'Eingaben verworfen',message:text,modal:true});}catch(e){}}
  return true;
}
function aresBeforeUnloadGuard(ev){
  if(typeof aresSessionHardResetInProgress!=='undefined'&&aresSessionHardResetInProgress)return undefined;
  if(!hasAresUnsavedChanges())return undefined;
  if(ev){ev.preventDefault();ev.returnValue='';}
  return '';
}
if(typeof document!=='undefined'&&document&&typeof document.addEventListener==='function'){
  document.addEventListener('input',aresMarkUnsavedFromEvent,true);
  document.addEventListener('change',aresMarkUnsavedFromEvent,true);
}
if(typeof window!=='undefined'&&window&&typeof window.addEventListener==='function'){
  window.addEventListener('beforeunload',aresBeforeUnloadGuard);
}
