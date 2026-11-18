// H9 Nachtrag 2 (Entscheid Owner-Vertretung 2026-11-12): EINE Quelle fuer die
// IST-Vermoegensprojektion. Renditeannahmen (wirksame CMA-Version, dieselbe
// Aufloesung wie der Allokationspfad) und die FX-normalisierte Gesamt-
// vermoegens-Basis kommen vom Server (GET /mandates/{id}/ist-projection-basis),
// unabhaengig davon, ob eine Strategie berechnet ist. Keine Client-Konstanten
// als Rechengrundlage: solange die Basis fehlt (laedt, kein Mandat, keine
// wirksame CMA), gibt es keine IST-Projektion, sondern einen Leerzustand mit
// Grund (fail-closed). Ausgelagerter Monolith-Teil (Bundle, Budget, Guards).
var istProjectionBasisState={mid:null,key:null,data:null,status:'idle',reason:'',seq:0};
function istProjectionBasisActiveMandate(){
  return (typeof getActiveMandateId==='function')?String(getActiveMandateId()||''):'';
}
// Fingerprint der Eingaben (Positionen, Cashflows, Horizont): aendert er sich,
// wird die Basis neu geladen.
function istProjectionBasisKey(mid){
  var pos=(typeof activeClientWealthPositions==='function')?activeClientWealthPositions():[];
  var cf=(typeof activeClientCashflowSummary==='function')?activeClientCashflowSummary():null;
  var h=istProjectionBasisHorizon();
  try{
    return mid+'|'+h+'|'+JSON.stringify((Array.isArray(pos)?pos:[]).map(function(p){
      return [p&&p.id,p&&p.current_value_rappen,p&&p.currency,p&&p.assignment,p&&p.position_type,p&&(p.updated_at||'')];
    }))+'|'+JSON.stringify(cf||null);
  }catch(e){return mid+'|'+h;}
}
function istProjectionBasisHorizon(){
  var h=(typeof projectionHorizonYears==='function')?Number(projectionHorizonYears(null,null)):NaN;
  return isFinite(h)?Math.max(1,Math.min(80,Math.round(h))):null;
}
// Basis fuer wealthProjectionInputs -- nur fuer das aktive Mandat, sonst null.
function istProjectionServerBasisFor(){
  var mid=istProjectionBasisActiveMandate();
  var st=istProjectionBasisState;
  if(!mid||st.mid!==mid||!st.data||st.status!=='ok')return null;
  return st.data;
}
function istProjectionBasisUnavailableReason(){
  var st=istProjectionBasisState;
  if(st.status==='unavailable')return st.reason||'Ist-Projektion nicht verfügbar: keine wirksamen Kapitalmarktannahmen.';
  if(st.status==='loading')return 'Ist-Projektion wird mit den aktuellen Kapitalmarktannahmen berechnet …';
  return 'Ist-Projektion erscheint, sobald ein Mandat mit Vermögensdaten geladen ist.';
}
function istProjectionRerender(){
  if(typeof refreshBaselineChartFromClientDataForced==='function')refreshBaselineChartFromClientDataForced();
  if(typeof istProjectionStrategyValid==='function'&&istProjectionStrategyValid()&&typeof strategyState!=='undefined'&&strategyState){
    updateProjectionChartsFromSimulation(strategyState.allocation);
    renderIstStrategyOverview(strategyState.allocation);
  }
}
async function ensureIstProjectionBasis(){
  var mid=istProjectionBasisActiveMandate();
  var st=istProjectionBasisState;
  if(!mid||(typeof isDemoMandateId==='function'&&isDemoMandateId(mid))){
    if(st.mid!==mid){st.mid=mid||null;st.key=null;st.data=null;st.status='idle';st.reason='';}
    return null;
  }
  var key=istProjectionBasisKey(mid);
  if(st.mid===mid&&st.key===key&&st.status!=='idle')return st.status;
  var seq=++st.seq;
  if(st.mid!==mid)st.data=null; // nie die Basis eines anderen Mandats zeigen
  st.mid=mid;st.key=key;st.status='loading';st.reason='';
  var h=istProjectionBasisHorizon();
  var res=null,err=null;
  try{res=await API.get('/mandates/'+mid+'/ist-projection-basis'+(h?'?horizon_years='+h:''));}
  catch(e){err=e;}
  if(seq!==st.seq||istProjectionBasisActiveMandate()!==mid)return null;
  if(res&&String(res.mandate_id||'')===mid&&res.expected_return_bps){
    st.data=res;st.status='ok';
  }else{
    var detail=null;
    try{detail=JSON.parse(String(err&&err.body||'')).detail;}catch(_){detail=null;}
    st.data=null;st.status='unavailable';
    st.reason=(detail&&detail.reason_code==='IST_PROJECTION_BASIS_UNAVAILABLE'&&detail.message)
      ?'Ist-Projektion nicht verfügbar: '+String(detail.message)
      :'Ist-Projektion nicht verfügbar: Die Kapitalmarktannahmen konnten nicht geladen werden.';
  }
  istProjectionRerender();
  return st.status;
}
// Leerzustand mit Grund statt erfundener Projektion.
function renderIstProjectionUnavailable(){
  var c=(typeof charts!=='undefined'&&charts)?charts:null;
  ['ist','aaCurrent'].forEach(function(k){
    var ch=c&&c[k];
    if(ch&&ch.data){ch.data.labels=[];ch.data.datasets=[];ch.update();}
  });
  renderCurrentWealthOnlyProjectionSummary({labels:[],projectedRappen:0,expectedReturnBps:0,unavailableReason:istProjectionBasisUnavailableReason()});
}
