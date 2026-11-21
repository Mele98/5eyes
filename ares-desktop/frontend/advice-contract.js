/**
 * Beratungsvertrag in der Classic-Vertragsmaske (L2b, H-190; CTO-Entscheid 3
 * zu H-179). Ausgelagerter Monolith-Teil (EXTRACTED_MONOLITH_PARTS, eigenes
 * Budget), eingebunden nach owner-content.js; haengt sich selbst ein.
 *
 *   - Review & Abschluss > Dokumente: Knopf "Beratungsvertrag" (je Mandatstyp
 *     Vermoegensverwaltung / Anlageberatung / Finanzplanung, Vorlage vom Server).
 *   - Maske: Mandatstyp und Status der Vertragsvorlage, Ort der Unterzeichnung
 *     (Pflicht, kein Vorgabewert), Datum, Sondervereinbarungen (optional).
 *   - Vorschau: Vertrags-PDF; solange Vorlage/Vertragsschicht nicht frei ist,
 *     ein Entwurf mit Wasserzeichen (Server, X-Ares-Draft) -- die Gruende stehen
 *     auf Deutsch in der Maske. Ein finaler Vertrag wird vom Server archiviert
 *     und ueber den bestehenden Signaturpfad unterzeichnet (Vertragsschicht-Gate).
 *   - Rollen: Berater/Admin erstellen; "Lesend" sieht den Status, schreibt nicht.
 *
 * Ares formuliert keinen Vertragstext: Klauseln kommen aus der freigegebenen
 * Vertragsvorlage der Firma (Administration > Compliance > Vertragsschicht).
 *
 * Ausserdem (Monolith-Budget): saveContractDocumentDraft (Anlagestrategie-
 * Entwurf) unveraendert aus ares.html hierher umgezogen.
 */
async function saveContractDocumentDraft(){
  var title=getInputValue('contract-title').trim();
  var intro=getInputValue('contract-intro').trim();
  var disclaimer=getInputValue('contract-disclaimer').trim();
  var special=getInputValue('contract-special').trim();
  var place=getInputValue('contract-place').trim();
  var signDate=getInputValue('contract-date')||new Date().toISOString().slice(0,10);
  var btn=document.getElementById('btn-contract-save');
  var mid=getActiveMandateId();
  if(!title){showModalFeedback('contract-error',btn,'Bitte Dokumenttitel eingeben.',true);return;}
  var payload={
    document_type:'Anlagestrategie',
    title:title,
    content_json:JSON.stringify({
      intro:intro,
      disclaimer:disclaimer,
      special:special,
      place:place,
      sign_date:signDate,
      client_name:currentPersona?((currentPersona.first_name||currentPersona.name||'')+' '+(currentPersona.last_name||'')).trim():null
    })
  };
  if(btn){btn.disabled=true;btn.textContent='Speichern...';}
  if(mid&&!isDemoMandateId(mid)){
    try{
      await API.post('/mandates/'+mid+'/documents',payload);
      showModalFeedback('contract-error',btn,'✓ Dokument-Entwurf gespeichert',false);
      await refreshReviewUI(mid);
      try{showAppSuccess('Dokument-Entwurf gespeichert',{title:'Anlagestrategie-Dokument'});}catch(noticeErr){}
      setTimeout(function(){cm('m-contract-edit');},500);
    }catch(e){
      var docErr='Fehler: '+(e.detail||e.message||'?');
      showModalFeedback('contract-error',btn,docErr,true);
      try{showAppError(docErr,{title:'Dokument-Entwurf nicht gespeichert'});}catch(noticeErr){}
    }
  } else {
    currentReviewState.documents=[{
      id:'demo-doc-'+Date.now(),
      document_type:'Anlagestrategie',
      title:title,
      status:'Entwurf',
      signed_by_advisor:0
    }].concat(currentReviewState.documents||[]);
    renderReviewState(currentReviewState);
    showModalFeedback('contract-error',btn,'✓ Demo-Modus: Dokument ergänzt',false);
    setTimeout(function(){cm('m-contract-edit');},700);
  }
}

(function(){
  'use strict';

  var DOC_TYPE = 'Beratungsvertrag';
  var WRITE_ROLES = { admin: true, advisor: true };
  var CODE_TEXT = {
    CONTRACT_PLACE_MISSING: 'Der Ort der Unterzeichnung fehlt. Er ist Pflicht und hat keinen Vorgabewert. Bitte erfassen und den Vertrag neu speichern.',
    CONTRACT_TEMPLATE_UNAPPROVED: 'Die Vertragsvorlage für diesen Mandatstyp ist noch nicht freigegeben (Administration > Compliance > Vertragsschicht, Freigabe durch eine zweite Person).',
    CONTRACT_TEMPLATE_CLAUSE_MISSING: 'In der Vertragsvorlage fehlen freigegebene Pflichtklauseln.',
    CONTRACT_TEMPLATE_OUTDATED: 'Der Vertrag beruht nicht auf der aktuell freigegebenen Vertragsvorlage. Bitte das Vertrags-PDF neu erstellen; der neue Vertrag trägt die aktuelle Vorlage.',
    CONTRACT_LAYER_INCOMPLETE: 'Vertragsabschluss gesperrt: Die Vertragsschicht ist unvollständig.'
  };
  var state = { mandateId: null, layer: null, docId: null };

  function esc(v){
    if (typeof escapeHtml === 'function') return escapeHtml(String(v == null ? '' : v));
    return String(v == null ? '' : v).replace(/[&<>"']/g, function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
    });
  }
  function el(id){ return document.getElementById(id); }
  function val(id){ var e = el(id); return e ? String(e.value || '').trim() : ''; }
  function role(){ return (typeof currentUser !== 'undefined' && currentUser) ? String(currentUser.role || '') : ''; }
  function canWrite(){ return !!WRITE_ROLES[role()]; }
  function mid(){ return (typeof getActiveMandateId === 'function') ? getActiveMandateId() : null; }
  function isDemo(id){ return typeof isDemoMandateId === 'function' && isDemoMandateId(id); }
  function today(){ return new Date().toISOString().slice(0, 10); }
  function apiError(e, fallback){ return (typeof parseApiError === 'function') ? parseApiError(e, fallback) : fallback; }

  // Deutsche Ursache eines strukturierten Fehlers (detail.reason_code/findings).
  function parsedDetail(e){
    try { var p = e && e.body ? JSON.parse(e.body) : null; return p && p.detail; } catch(x) { return null; }
  }
  function findingLines(findings){
    return (findings || []).map(function(f){
      var text = f.message || CODE_TEXT[f.reason_code] || f.reason_code;
      return '• ' + text + (f.owner_action ? ' (' + f.owner_action + ')' : '');
    });
  }
  function contractErrorText(e){
    var d = parsedDetail(e);
    if (!d || typeof d !== 'object' || !CODE_TEXT[d.reason_code]) return null;
    var lines = findingLines(d.findings);
    return CODE_TEXT[d.reason_code] + (lines.length ? '\n' + lines.join('\n') : '');
  }

  function modalHtml(){
    return '<div class="modal" style="width:620px;max-height:84vh;overflow-y:auto">'
      + '<div class="mhd"><div class="mtitle">Beratungsvertrag</div><button class="mx" onclick="cm(\'m-advice-contract\')">✕</button></div>'
      + '<div class="mbody">'
      + '<div id="ac-template" style="background:var(--bg);border:1px solid var(--b1);border-radius:var(--r2);padding:10px;margin-bottom:10px;font-size:11px;color:var(--n6)">Lädt…</div>'
      + '<div id="ac-readonly" style="display:none;font-size:11px;color:var(--warn);margin-bottom:8px">Nur Lesen: Ihre Rolle kann keinen Beratungsvertrag erstellen oder unterzeichnen.</div>'
      + '<div class="frow"><div class="fg"><label class="fl" for="ac-place">Ort der Unterzeichnung (Pflicht)</label><input class="fi" id="ac-place" autocomplete="off"></div>'
      + '<div class="fg"><label class="fl" for="ac-date">Datum</label><input class="fi" type="date" id="ac-date"></div></div>'
      + '<div class="frow"><div class="fg"><label class="fl" for="ac-special">Sondervereinbarungen (optional)</label>'
      + '<textarea class="fi" id="ac-special" rows="2" style="resize:vertical;min-height:50px"></textarea></div></div>'
      + '<div id="ac-error" role="alert" style="display:none;white-space:pre-line;font-size:11px;color:var(--neg);margin-top:6px"></div>'
      + '<div id="ac-result" style="display:none;white-space:pre-line;font-size:11px;margin-top:6px"></div>'
      + '</div><div class="mfooter">'
      + '<button class="btn" onclick="cm(\'m-advice-contract\')">Schliessen</button>'
      + '<button class="btn-p" id="btn-ac-save" onclick="saveAdviceContract()">Entwurf speichern</button>'
      + '<button class="btn-g" id="btn-ac-preview" onclick="previewAdviceContract()" disabled>Vorschau (PDF)</button>'
      + '</div></div>';
  }
  function ensureModal(){
    var m = el('m-advice-contract');
    if (m) return m;
    m = document.createElement('div');
    m.className = 'overlay';
    m.id = 'm-advice-contract';
    m.innerHTML = modalHtml();
    document.body.appendChild(m);
    return m;
  }
  function show(id, text, color){
    var e = el(id);
    if (!e) return;
    e.textContent = text || '';
    if (color) e.style.color = color;
    e.style.display = text ? 'block' : 'none';
  }

  function templateHtml(layer){
    var tpl = (layer && layer.contract_template) || {};
    var type = tpl.mandate_type || '–';
    if (!tpl.supported) {
      return '<b>Mandatstyp: ' + esc(type) + '</b><div style="color:var(--neg);margin-top:4px">Für diesen Mandatstyp gibt es keine Vertragsvorlage. Ein Beratungsvertrag ist nur für Vermögensverwaltung, Anlageberatung oder Finanzplanung möglich.</div>';
    }
    var html = '<b>Mandatstyp: ' + esc(type) + '</b>';
    if (tpl.template_hash) {
      html += '<div id="ac-template-ok" style="color:var(--pos);margin-top:4px">Vertragsvorlage freigegeben · Prüfwert ' + esc(String(tpl.template_hash).slice(0, 12)) + '</div>';
    } else {
      var clauses = tpl.clauses || [];
      var open = clauses.filter(function(c){ return c.status !== 'freigegeben'; }).length;
      html += '<div id="ac-template-draft" style="color:var(--warn);margin-top:4px">Vertragsvorlage nicht freigegeben (' + open + ' von ' + clauses.length
        + ' Klauseln offen). Die Vorschau ist ein Entwurf mit Wasserzeichen; unterzeichnen ist erst nach der Freigabe möglich.</div>';
    }
    var lines = findingLines(layer && layer.findings);
    if (lines.length) {
      html += '<div id="ac-findings" style="margin-top:6px;font-size:10px;color:var(--n6)"><b>Offen für den Vertragsabschluss:</b><br>' + lines.map(esc).join('<br>') + '</div>';
    }
    return html;
  }

  async function loadLayer(id){
    try {
      state.layer = await API.get('/mandates/' + encodeURIComponent(id) + '/contract-layer');
    } catch(e) {
      state.layer = null;
      el('ac-template').innerHTML = '<span style="color:var(--neg)">' + esc(apiError(e, 'Status der Vertragsvorlage konnte nicht geladen werden.')) + '</span>';
      return;
    }
    el('ac-template').innerHTML = templateHtml(state.layer);
  }

  function supported(){ return !!(state.layer && state.layer.contract_template && state.layer.contract_template.supported); }
  function syncButtons(){
    var write = canWrite() && supported();
    var save = el('btn-ac-save'), prev = el('btn-ac-preview');
    if (save) { save.disabled = !write; save.style.display = canWrite() ? '' : 'none'; }
    if (prev) { prev.disabled = !(write && state.docId); prev.style.display = canWrite() ? '' : 'none'; }
    ['ac-place', 'ac-date', 'ac-special'].forEach(function(id){ var e = el(id); if (e) e.disabled = !write; });
    el('ac-readonly').style.display = canWrite() ? 'none' : 'block';
  }

  async function openAdviceContractModal(docId){
    var id = mid();
    if (!id || isDemo(id)) { if (typeof showAppError === 'function') showAppError('Der Beratungsvertrag ist nur für ein gespeichertes Mandat möglich.'); return; }
    ensureModal();
    state.mandateId = id;
    state.docId = docId || null;
    el('ac-place').value = '';
    el('ac-date').value = today();
    el('ac-special').value = '';
    show('ac-error', '');
    show('ac-result', '');
    el('ac-template').textContent = 'Lädt…';
    if (typeof om === 'function') om('m-advice-contract'); else el('m-advice-contract').classList.add('open');
    await loadLayer(id);
    syncButtons();
  }

  async function saveAdviceContract(){
    if (!canWrite() || !supported()) return;
    var place = val('ac-place');
    show('ac-result', '');
    if (!place) { show('ac-error', CODE_TEXT.CONTRACT_PLACE_MISSING); el('ac-place').focus(); return; }
    show('ac-error', '');
    var tpl = state.layer.contract_template;
    var special = val('ac-special');
    el('btn-ac-save').disabled = true;
    try {
      var doc = await API.post('/mandates/' + encodeURIComponent(state.mandateId) + '/documents', {
        document_type: DOC_TYPE,
        title: 'Beratungsvertrag – ' + tpl.mandate_type,
        content_json: JSON.stringify({
          ort_unterzeichnung: place, vereinbarungs_datum: val('ac-date') || today(),
          sondervereinbarungen: special || null
        })
      });
      state.docId = doc && doc.id;
      syncButtons();
      show('ac-result', 'Entwurf gespeichert. Mit «Vorschau (PDF)» erstellen Sie den Vertrag.', 'var(--pos)');
      if (typeof refreshReviewUI === 'function') await refreshReviewUI(state.mandateId);
    } catch(e) {
      show('ac-error', contractErrorText(e) || ('Entwurf nicht gespeichert: ' + apiError(e, '?')));
    } finally {
      syncButtons();
    }
  }

  async function savePdf(res, blob){
    var filename = 'vertrag_' + today().replace(/-/g, '') + '.pdf';
    var match = (res.headers.get('Content-Disposition') || '').match(/filename="?([^";]+)"?/i);
    if (match && match[1]) filename = match[1];
    if (window.desktop && typeof window.desktop.savePdfFile === 'function' && typeof blobToBase64 === 'function') {
      await window.desktop.savePdfFile({ filename: filename, base64: await blobToBase64(blob) });
      return;
    }
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url; a.download = filename; a.style.display = 'none';
    document.body.appendChild(a); a.click();
    setTimeout(function(){ try { document.body.removeChild(a); URL.revokeObjectURL(url); } catch(x) {} }, 60000);
  }

  async function archivedContractIds(id){
    var docs = await API.get('/mandates/' + encodeURIComponent(id) + '/documents');
    return (Array.isArray(docs) ? docs : []).filter(function(d){ return d && d.document_type === DOC_TYPE && d.has_pdf; })
      .map(function(d){ return String(d.id); });
  }

  // Vorschau = Vertrags-PDF des gespeicherten Entwurfs. Der Server entscheidet
  // Entwurf (Wasserzeichen) oder final (archiviert). Final heisst: danach liegt
  // ein neues archiviertes PDF in der Dokumentliste -- das gilt auch in der
  // Desktop-App, in der die X-Ares-Header (CORS) nicht lesbar sind.
  async function previewAdviceContract(docId){
    var docRef = docId || state.docId;
    var id = state.mandateId || mid();
    if (!canWrite() || !docRef || !id) return;
    var btn = el('btn-ac-preview');
    if (btn) btn.disabled = true;
    show('ac-error', '');
    try {
      var before = await archivedContractIds(id);
      var token = await API.getToken();
      var res = await fetch((await API.baseUrl()) + '/mandates/' + encodeURIComponent(id) + '/reports/vertrag.pdf?document_id=' + encodeURIComponent(docRef),
        { headers: token ? { Authorization: 'Bearer ' + token } : {} });
      if (!res.ok) {
        var body = await res.text();
        var text = contractErrorText({ body: body });
        if (!text) { try { var d = JSON.parse(body).detail; text = typeof d === 'string' ? d : (d && d.message) || body; } catch(x) { text = body; } }
        show('ac-error', 'Vorschau nicht erstellt (HTTP ' + res.status + '): ' + String(text).slice(0, 800));
        return;
      }
      var reasons = (res.headers.get('X-Ares-Draft-Reasons') || '').split(',').filter(Boolean);
      var blob = await res.blob();
      var archived = (await archivedContractIds(id)).filter(function(x){ return before.indexOf(x) < 0; });
      await loadLayer(id);
      if (!archived.length) {
        var byCode = {};
        ((state.layer && state.layer.findings) || []).forEach(function(f){ byCode[f.reason_code] = f.message; });
        if (!reasons.length) reasons = Object.keys(byCode);
        var lines = reasons.map(function(c){ return '• ' + (CODE_TEXT[c] || byCode[c] || c); });
        show('ac-result', 'Entwurf (Wasserzeichen «Entwurf»): nicht signierbar, nicht archiviert.' + (lines.length ? '\n' + lines.join('\n') : ''), 'var(--warn)');
      } else {
        show('ac-result', 'Vertrag final erstellt und archiviert. Unterzeichnen Sie ihn in der Dokumentliste (Berater signieren / Kunde signieren).', 'var(--pos)');
        if (typeof refreshReviewUI === 'function') await refreshReviewUI(id);
      }
      await savePdf(res, blob);
    } catch(e) {
      show('ac-error', 'Vorschau nicht erstellt: ' + ((e && e.message) || '?'));
    } finally {
      syncButtons();
    }
  }

  // Dokumente-Karte: Einstieg "Beratungsvertrag" und Vorschau je gespeichertem
  // Entwurf (Quelldokument ohne PDF).
  function decorateGrid(documents){
    var grid = el('rv-doc-grid');
    if (!grid || el('btn-rv-advice-contract')) return;
    var actions = grid.querySelector('.rv-output-item .rv-output-actions');
    if (actions) {
      var b = document.createElement('button');
      b.className = 'btn btn-sm';
      b.id = 'btn-rv-advice-contract';
      b.textContent = 'Beratungsvertrag';
      b.onclick = function(ev){ if (ev) ev.preventDefault(); openAdviceContractModal(); };
      actions.appendChild(b);
    }
    var docs = Array.isArray(documents) ? documents : [];
    Array.prototype.forEach.call(grid.querySelectorAll('.doc-card'), function(card, idx){
      var doc = docs[idx];
      if (!doc || doc.document_type !== DOC_TYPE || doc.has_pdf || !canWrite()) return;
      var p = document.createElement('button');
      p.className = 'btn btn-sm';
      p.setAttribute('data-doc-action', 'advice-contract-preview');
      p.textContent = 'Vertrag erstellen (PDF)';
      p.onclick = function(ev){
        if (ev) ev.preventDefault();
        openAdviceContractModal(doc.id).then(function(){ return previewAdviceContract(doc.id); });
      };
      var box = card.querySelector('.rv-output-actions');
      if (box) box.appendChild(p);
    });
  }
  function wrapRenderDocumentGrid(){
    if (typeof window.renderDocumentGrid !== 'function' || window.renderDocumentGrid.__ac) return;
    var original = window.renderDocumentGrid;
    var wrapped = function(documents){
      var result = original.apply(this, arguments);
      try { decorateGrid(documents); } catch(e) { if (window.console) console.warn('Beratungsvertrag:', e); }
      return result;
    };
    wrapped.__ac = true;
    window.renderDocumentGrid = wrapped;
  }
  // Signatur: Vertragsschicht-Sperren mit deutscher Ursache und Handlung zeigen.
  function wrapReleaseGateMessage(){
    if (typeof window.releaseGateMessage !== 'function' || window.releaseGateMessage.__ac) return;
    var original = window.releaseGateMessage;
    var wrapped = function(e){ return contractErrorText(e) || original.apply(this, arguments); };
    wrapped.__ac = true;
    window.releaseGateMessage = wrapped;
  }
  // releaseGateMessage kommt aus wealth-inflows.js (spaeter eingebunden).
  function wrapAll(){ wrapRenderDocumentGrid(); wrapReleaseGateMessage(); }
  wrapAll();
  if (typeof document !== 'undefined' && document.readyState === 'loading') document.addEventListener('DOMContentLoaded', wrapAll);

  window.openAdviceContractModal = openAdviceContractModal;
  window.saveAdviceContract = saveAdviceContract;
  window.previewAdviceContract = previewAdviceContract;
  window.adviceContractErrorText = contractErrorText;
})();
