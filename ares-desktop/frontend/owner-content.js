/**
 * Vertragsschicht (H-179, L2/L3) -- Owner-Inhalte pflegen und freigeben.
 *
 * Ausgelagerter Monolith-Teil (EXTRACTED_MONOLITH_PARTS, eigenes Budget),
 * eingebunden am Ende von ares.html; haengt sich beim DOMContentLoaded selbst
 * ein: Administration > Compliance > "Vertragsschicht" (#sec-owner-content).
 *
 *   - Katalog der Owner-Inhalte (Vertragsklauseln je Mandatstyp, Abschnitt
 *     Datenbearbeitung der Kundeninformation, W033-Texte, Mindesthorizont,
 *     Zuwendungen der Depotbank) mit Status vom Server.
 *   - Neue Version erfassen (Firmen-Admin); Freigabe durch eine ZWEITE Person
 *     mit Anzeige und Bestaetigung des Pruefwerts (Muster KYC-Wiedervorlage).
 *   - Mandat pruefen: Status der Vertragsschicht, Gruende der Empfehlung
 *     (Art. 15 FIDLEG) und W033-Bestaetigungen des Kunden erfassen.
 *   - N-927-01: Rolle compliance_reviewer (externe Prueferson einer
 *     Ein-Personen-Firma) sieht in ihrer Freigabe-Ansicht nur Katalog und
 *     offene Entwuerfe zum Freigeben -- kein Erfassen, keine Mandate.
 *
 * Grundsaetze: Ares belegt keinen Text und keinen Wert vor; Status und
 * Sperrgruende kommen 1:1 vom Server.
 */
(function(){
  'use strict';

  var STATUS_LABELS = {
    fehlt: 'fehlt – Text bzw. Wert der Firma ausstehend',
    nicht_freigegeben: 'Entwurf – wartet auf Freigabe durch eine zweite Person',
    freigegeben: 'freigegeben',
    kette_ungueltig: 'gesperrt (Freigabekette ungültig)'
  };
  var GROUP_LABELS = {
    vertrag: 'Vertragsvorlage (Pflichtklauseln)',
    datenschutz: 'Kundeninformation – Datenbearbeitung (Art. 19 DSG)',
    w033: 'Eignungsprüfung (W033)',
    depotbank: 'Zuwendungen der Depotbank',
    protokoll: 'Beratungsprotokoll (Art. 15 FIDLEG)'
  };
  var L = '<label style="font-size:12px;color:var(--n4);display:block;margin-bottom:2px">';
  var state = { items: [], mandate: null };

  function esc(v){
    if (typeof escapeHtml === 'function') return escapeHtml(String(v == null ? '' : v));
    return String(v == null ? '' : v).replace(/[&<>"']/g, function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
    });
  }
  function errText(e, fallback){
    return (typeof parseApiError === 'function') ? parseApiError(e, fallback) : fallback;
  }
  function notify(level, message){
    if (level === 'error' && typeof showAppError === 'function') return showAppError(message);
    if (typeof showAppNotice === 'function') return showAppNotice({level: level, message: message});
  }
  function val(id){ var el = document.getElementById(id); return el ? String(el.value || '').trim() : ''; }
  function me(){ return (typeof currentUser !== 'undefined' && currentUser) ? currentUser : null; }
  function isReviewer(){ var u = me(); return !!(u && u.role === 'compliance_reviewer'); }
  function hostEl(){ return document.getElementById('oc-reviewer-body') || document.getElementById('sec-owner-content'); }
  function short(text){ var t = String(text || ''); return t.length > 160 ? t.slice(0, 160) + ' …' : t; }

  function approvalHtml(item){
    var u = me();
    var id = esc(item.draft_row_id);
    if (u && item.draft_created_by === u.id) {
      return '<div class="oc-self" style="font-size:12px;color:var(--warn)">Von Ihnen erfasst – freigeben muss eine zweite Person.</div>';
    }
    return '<div style="font-size:12px;color:var(--n5)">Prüfwert: <code id="oc-hash-' + id + '" style="font-size:12px;word-break:break-all">' + esc(item.draft_content_hash) + '</code></div>'
      + '<input class="fi" id="oc-ref-' + id + '" placeholder="Freigabereferenz" style="font-size:12px;width:60%"> '
      + '<label style="font-size:12px"><input type="checkbox" id="oc-ok-' + id + '"> Inhalt und Prüfwert geprüft</label> '
      + '<button class="btn-p" id="oc-approve-' + id + '" style="font-size:12px;padding:2px 8px" onclick="approveOwnerContent(\'' + id + '\')">Freigeben</button>';
  }

  function itemHtml(item){
    var effective = item.effective_body_text || item.effective_value_json;
    var draft = item.draft_body_text || item.draft_value_json;
    return '<tr data-owner-key="' + esc(item.key) + '" data-owner-status="' + esc(item.status) + '" style="border-top:1px solid var(--b1);vertical-align:top">'
      + '<td>' + esc(item.label) + '<div style="font-size:12px;color:var(--n5)">' + esc(item.key) + ' · ' + esc(item.placeholder) + '</div>'
      + '<div class="oc-where" style="font-size:12px;color:var(--n5)">Erscheint in: ' + esc(item.visible_in) + '</div></td>'
      + '<td>' + esc(STATUS_LABELS[item.status] || item.status)
      + (effective ? '<div style="font-size:12px">Version ' + esc(item.effective_version) + ': ' + esc(short(effective)) + '</div>' : '')
      + (item.draft_row_id ? '<div style="font-size:12px;margin-top:4px">Entwurf Version ' + esc(item.draft_version) + ': ' + esc(short(draft)) + '</div>' + approvalHtml(item) : '')
      + '</td></tr>';
  }

  function catalogHtml(data){
    var groups = {};
    (data.items || []).forEach(function(i){ (groups[i.group] = groups[i.group] || []).push(i); });
    var html = '';
    Object.keys(GROUP_LABELS).forEach(function(g){
      var rows = groups[g] || [];
      if (!rows.length && g !== 'depotbank') return;
      html += '<div style="font-weight:600;font-size:12px;margin-top:10px">' + esc(GROUP_LABELS[g]) + '</div>';
      if (g === 'vertrag') {
        html += '<div style="font-size:12px;color:var(--n5)">Je Klausel genügt ein gemeinsamer Text für alle Mandatstypen; ein Text für einen bestimmten Mandatstyp hat Vorrang.</div>';
      }
      if (!rows.length) { html += '<div style="font-size:12px;color:var(--n5)">Noch keine Depotbank erfasst.</div>'; return; }
      html += '<table style="width:100%;border-collapse:collapse;font-size:12px"><tbody>' + rows.map(itemHtml).join('') + '</tbody></table>';
    });
    return html;
  }

  // L2b: beim Erfassen zeigen, wo der Text erscheint (Dokument/Abschnitt) und
  // was die Firma liefert -- beides 1:1 aus dem Katalog des Servers.
  function firstKey(data){ var i = (data.items || []).filter(function(x){ return x.group !== 'depotbank'; })[0]; return i ? i.key : ''; }
  function keyHintHtml(key){
    var item = (state.items || []).filter(function(i){ return i.key === key; })[0];
    if (!item) return '';
    return 'Erscheint in: <b>' + esc(item.visible_in) + '</b><br>Die Firma liefert: ' + esc(item.owner_input) + ' · Platzhalter ' + esc(item.placeholder);
  }
  function ownerContentKeyHint(){ var el = document.getElementById('oc-key-hint'); if (el) el.innerHTML = keyHintHtml(val('oc-key')); }

  function createFormHtml(data){
    var options = (data.items || []).filter(function(i){ return i.group !== 'depotbank'; }).map(function(i){
      return '<option value="' + esc(i.key) + '" data-kind="' + esc(i.kind) + '">' + esc(i.label) + '</option>';
    }).join('');
    return '<div style="font-weight:600;font-size:12px;margin-top:12px">Neue Version erfassen</div>'
      + '<div style="font-size:12px;color:var(--n5);line-height:1.5">Erfassen Sie den von Geschäftsleitung bzw. Compliance freigegebenen Text der Firma. Ares schlägt keinen Text vor. '
      + 'Erst nach der Freigabe durch eine zweite Person ist die Version wirksam.</div>'
      + '<div style="display:grid;grid-template-columns:repeat(2,1fr);gap:6px;margin-top:4px">'
      + '<div>' + L + 'Inhalt</label><select class="fi" id="oc-key" style="font-size:12px" onchange="ownerContentKeyHint()">' + options + '</select></div>'
      + '<div>' + L + 'Quelle (Dokument-ID, Freigabe der Geschäftsleitung)</label><input class="fi" id="oc-source" style="font-size:12px"></div>'
      + '<div id="oc-key-hint" style="grid-column:1/-1;font-size:12px;color:var(--n5);line-height:1.5">' + keyHintHtml(firstKey(data)) + '</div>'
      + '<div style="grid-column:1/-1">' + L + 'Text der Firma bzw. ganze Zahl (Mindesthorizont in Jahren)</label><textarea class="fi" id="oc-text" rows="4" style="font-size:12px"></textarea></div>'
      + '</div><button class="btn-p" id="btn-oc-create" style="margin-top:4px;font-size:12px;padding:3px 10px" onclick="createOwnerContent()">Version erfassen</button>'
      + '<div style="font-weight:600;font-size:12px;margin-top:12px">Zuwendungen einer Depotbank erfassen</div>'
      + '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-top:4px">'
      + '<div>' + L + 'Depotbank (wie im Mandat)</label><input class="fi" id="oc-bank" style="font-size:12px"></div>'
      + '<div>' + L + 'Angabe</label><select class="fi" id="oc-bank-status" style="font-size:12px"><option value="keine">keine Zuwendungen</option><option value="satz">Satz und Basis</option><option value="verzicht">Verzicht mit Bandbreite</option></select></div>'
      + '<div>' + L + 'Satz (Basispunkte)</label><input class="fi" type="number" min="0" id="oc-bank-rate" style="font-size:12px"></div>'
      + '<div>' + L + 'Bemessungsbasis</label><input class="fi" id="oc-bank-basis" style="font-size:12px"></div>'
      + '<div>' + L + 'Bandbreite min (bp)</label><input class="fi" type="number" min="0" id="oc-bank-min" style="font-size:12px"></div>'
      + '<div>' + L + 'Bandbreite max (bp)</label><input class="fi" type="number" min="0" id="oc-bank-max" style="font-size:12px"></div>'
      + '<div>' + L + 'Gültig ab</label><input class="fi" type="date" id="oc-bank-from" style="font-size:12px"></div>'
      + '<div>' + L + 'Gültig bis (optional)</label><input class="fi" type="date" id="oc-bank-until" style="font-size:12px"></div>'
      + '<div style="grid-column:1/-1">' + L + 'Beleg (Dokument-Referenz)</label><input class="fi" id="oc-bank-evidence" style="font-size:12px"></div>'
      + '</div><button class="btn btn-sm" id="btn-oc-bank" style="margin-top:4px" onclick="createDepotBankInducement()">Angabe erfassen</button>';
  }

  function mandateHtml(){
    return '<div class="admin-section-title" style="font-size:12px;margin-top:14px">Mandat prüfen</div>'
      + '<div style="display:flex;gap:6px"><input class="fi" id="oc-mandate-id" placeholder="Mandats-ID" style="font-size:12px">'
      + '<button class="btn btn-sm" id="btn-oc-mandate" onclick="loadContractLayerStatus()">Status laden</button></div>'
      + '<div id="oc-mandate-body" style="margin-top:6px"></div>';
  }

  function mandateBodyHtml(s){
    var findings = s.findings || [];
    var html = findings.length
      ? '<div id="oc-mandate-blocked" style="font-size:12px;font-weight:700;color:var(--neg)">Vertragsabschluss und Finalisierung gesperrt:</div>'
        + findings.map(function(f){ return '<div style="font-size:12px">• ' + esc(f.message) + '<div style="font-size:12px;color:var(--n5)">' + esc(f.owner_action) + '</div></div>'; }).join('')
      : '<div id="oc-mandate-ready" style="font-size:12px;font-weight:600;color:var(--pos)">Vertragsschicht vollständig.</div>';
    var tpl = s.contract_template || {};
    html += '<div style="font-size:12px;color:var(--n5);margin-top:4px">Vertragsvorlage ' + esc(tpl.mandate_type) + ': '
      + (tpl.template_hash ? 'Prüfwert ' + esc(String(tpl.template_hash).slice(0, 12)) : 'nicht freigegeben') + '</div>';
    if (s.latest_run_id) {
      html += '<div style="font-weight:600;font-size:12px;margin-top:8px">Gründe der Empfehlung (Art. 15 FIDLEG)</div>'
        + '<div>' + L + 'Bedürfnisse des Kunden</label><textarea class="fi" id="oc-needs" rows="2" style="font-size:12px"></textarea></div>'
        + '<div>' + L + 'Gründe der Empfehlung</label><textarea class="fi" id="oc-reasons" rows="3" style="font-size:12px"></textarea></div>'
        + '<button class="btn btn-sm" id="btn-oc-rationale" onclick="saveAdviceRationale(\'' + esc(s.latest_run_id) + '\')">Gründe speichern</button>';
    }
    var w = s.w033 || {};
    if (w.assessment_id) {
      html += '<div style="font-weight:600;font-size:12px;margin-top:8px">Bestätigungen des Kunden zum Risikoprofil (W033)</div>';
      if (w.declaration_text) {
        html += '<div style="font-size:12px">' + esc(w.declaration_text) + '</div>'
          + (w.declaration_confirmed ? '<div style="font-size:12px;color:var(--pos)">bestätigt</div>'
            : '<button class="btn btn-sm" id="btn-oc-w033-decl" onclick="recordW033Declaration(\'angaben_wahr_meldepflicht\')">Bestätigung des Kunden erfassen</button>');
      }
      if (w.advice_required && w.advice_text) {
        html += '<div style="font-size:12px;margin-top:4px">' + esc(w.advice_text) + '</div>'
          + (w.advice_confirmed ? '<div style="font-size:12px;color:var(--pos)">bestätigt</div>'
            : '<button class="btn btn-sm" id="btn-oc-w033-advice" onclick="recordW033Declaration(\'horizont_abraten\')">Bestätigung des Kunden erfassen</button>');
      }
      html += '<div>' + L + 'Kanal der Bestätigung</label><select class="fi" id="oc-w033-channel" style="font-size:12px"><option value="persoenlich_papier">persönlich (Papier)</option><option value="vor_ort">vor Ort</option><option value="kundenportal">Kundenportal</option></select></div>';
    }
    return html;
  }

  async function loadOwnerContent(){
    var host = hostEl();
    if (!host) return;
    try {
      var data = await API.get('/compliance/owner-content');
      state.items = data.items || [];
      host.innerHTML = '<div class="admin-section-title">Vertragsschicht (Texte und Werte der Firma)</div>'
        + '<div style="font-size:12px;color:var(--n5)">Ohne freigegebene Inhalte sperrt Ares Vertragsabschluss, Signatur, Finalisierung und die Kundeninformation. Katalog ' + esc(data.catalog_version) + '.</div>'
        + catalogHtml(data) + (isReviewer() ? '' : createFormHtml(data) + mandateHtml());
    } catch(e) {
      host.innerHTML = '<div style="color:var(--neg);font-size:12px">' + esc(errText(e, 'Vertragsschicht konnte nicht geladen werden.')) + '</div>';
    }
  }

  async function createOwnerContent(){
    var key = val('oc-key');
    var item = state.items.find(function(i){ return i.key === key; }) || {};
    var raw = val('oc-text');
    var body = { content_key: key, source_reference: val('oc-source') };
    if (item.kind === 'integer') body.value = raw === '' ? null : Number(raw); else body.body_text = raw;
    if (!key || !raw || !body.source_reference) { notify('error', 'Bitte Inhalt, Text bzw. Wert und Quelle angeben.'); return; }
    try {
      await API.post('/compliance/owner-content', body);
      notify('success', 'Version erfasst. Sie wird wirksam, sobald eine zweite Person sie freigibt.');
    } catch(e) { notify('error', errText(e, 'Version konnte nicht erfasst werden.')); }
    await loadOwnerContent();
  }

  function bankSlug(name){
    return String(name || '').trim().toLowerCase().replace(/ä/g, 'ae').replace(/ö/g, 'oe').replace(/ü/g, 'ue').replace(/ß/g, 'ss')
      .normalize('NFKD').replace(/[̀-ͯ]/g, '').replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  }

  async function createDepotBankInducement(){
    var bank = val('oc-bank');
    var num = function(id){ var v = val(id); return v === '' ? null : Number(v); };
    var value = {
      depot_bank: bank, status: val('oc-bank-status'), rate_bps: num('oc-bank-rate'), basis: val('oc-bank-basis') || null,
      range_min_bps: num('oc-bank-min'), range_max_bps: num('oc-bank-max'), evidence_reference: val('oc-bank-evidence'),
      valid_from: val('oc-bank-from'), valid_until: val('oc-bank-until') || null
    };
    if (!bank || !value.evidence_reference || !value.valid_from) { notify('error', 'Bitte Depotbank, Beleg und Gültig ab angeben.'); return; }
    try {
      await API.post('/compliance/owner-content', {
        content_key: 'depotbank_zuwendung.' + bankSlug(bank), value: value, source_reference: value.evidence_reference
      });
      notify('success', 'Angabe erfasst. Sie wird wirksam, sobald eine zweite Person sie freigibt.');
    } catch(e) { notify('error', errText(e, 'Angabe konnte nicht erfasst werden.')); }
    await loadOwnerContent();
  }

  async function approveOwnerContent(rowId){
    var ok = document.getElementById('oc-ok-' + rowId);
    var hashEl = document.getElementById('oc-hash-' + rowId);
    var ref = val('oc-ref-' + rowId);
    if (!ok || !ok.checked || !ref) { notify('error', 'Bitte Freigabereferenz angeben und die Prüfung bestätigen.'); return; }
    try {
      await API.post('/compliance/owner-content/' + encodeURIComponent(rowId) + '/approve', {
        content_hash: hashEl ? String(hashEl.textContent || '').trim() : '', approval_reference: ref
      });
      notify('success', 'Version freigegeben.');
    } catch(e) { notify('error', errText(e, 'Freigabe fehlgeschlagen.')); }
    await loadOwnerContent();
  }

  async function loadContractLayerStatus(){
    var id = val('oc-mandate-id');
    var box = document.getElementById('oc-mandate-body');
    if (!id || !box) return;
    try {
      state.mandate = await API.get('/mandates/' + encodeURIComponent(id) + '/contract-layer');
      box.innerHTML = mandateBodyHtml(state.mandate);
    } catch(e) {
      box.innerHTML = '<div style="color:var(--neg);font-size:12px">' + esc(errText(e, 'Status konnte nicht geladen werden.')) + '</div>';
    }
  }

  async function saveAdviceRationale(runId){
    var body = { client_needs: val('oc-needs'), recommendation_reasons: val('oc-reasons') };
    if (!body.client_needs || !body.recommendation_reasons) { notify('error', 'Bitte Bedürfnisse und Gründe angeben.'); return; }
    try {
      await API.post('/mandates/' + encodeURIComponent(state.mandate.mandate_id) + '/recommendations/' + encodeURIComponent(runId) + '/advice-rationale', body);
      notify('success', 'Gründe der Empfehlung gespeichert.');
    } catch(e) { notify('error', errText(e, 'Gründe konnten nicht gespeichert werden.')); }
    await loadContractLayerStatus();
  }

  async function recordW033Declaration(kind){
    var w = (state.mandate || {}).w033 || {};
    var hash = kind === 'horizont_abraten' ? w.advice_content_hash : w.declaration_content_hash;
    try {
      await API.post('/mandates/' + encodeURIComponent(state.mandate.mandate_id) + '/w033-declarations', {
        declaration_kind: kind, capture_channel: val('oc-w033-channel') || 'persoenlich_papier',
        confirmed_at: new Date().toISOString().slice(0, 10), content_hash: hash || ''
      });
      notify('success', 'Bestätigung des Kunden erfasst.');
    } catch(e) { notify('error', errText(e, 'Bestätigung konnte nicht erfasst werden.')); }
    await loadContractLayerStatus();
  }

  function mountOwnerContent(){
    var anchorBtn = document.getElementById('asec-kyc-review-policy') || document.getElementById('asec-legal-profile') || document.getElementById('asec-audit');
    if (anchorBtn && !document.getElementById('asec-owner-content')) {
      var btn = document.createElement('button');
      btn.id = 'asec-owner-content';
      btn.className = 'admin-sec-btn';
      btn.setAttribute('data-admin-category', 'compliance');
      btn.textContent = 'Vertragsschicht';
      btn.addEventListener('click', function(){
        if (typeof adminShowSection === 'function') adminShowSection('sec-owner-content');
        loadOwnerContent();
      });
      anchorBtn.parentNode.insertBefore(btn, anchorBtn.nextSibling);
    }
    var auditPanel = document.getElementById('sec-audit');
    if (auditPanel && !document.getElementById('sec-owner-content')) {
      var panel = document.createElement('div');
      panel.id = 'sec-owner-content';
      panel.className = 'admin-sec-panel';
      panel.style.display = 'none';
      panel.style.gap = '12px';
      auditPanel.parentNode.insertBefore(panel, auditPanel);
    }
  }
  // N-927-01: Freigabe-Ansicht der Prueferson unter der KYC-Freigabe-Ansicht.
  function wrapInitAppForReviewer(){
    if (typeof window.initApp !== 'function' || window.initApp.__oc) return;
    var original = window.initApp;
    var wrapped = async function(){
      var result = await original.apply(this, arguments);
      var view = document.getElementById('krp-reviewer-view');
      if (isReviewer() && view && !document.getElementById('oc-reviewer-body')) {
        var box = document.createElement('div');
        box.id = 'oc-reviewer-body';
        box.style.cssText = 'display:grid;gap:8px;margin-top:16px';
        view.appendChild(box);
        await loadOwnerContent();
      }
      return result;
    };
    wrapped.__oc = true;
    window.initApp = wrapped;
  }
  wrapInitAppForReviewer();
  if (typeof document !== 'undefined' && document.addEventListener) {
    // nach kyc-review-policy.js (Anker-Button), deshalb erst nach DOMContentLoaded.
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mountOwnerContent);
    else mountOwnerContent();
  }

  window.loadOwnerContent = loadOwnerContent;
  window.createOwnerContent = createOwnerContent;
  window.createDepotBankInducement = createDepotBankInducement;
  window.approveOwnerContent = approveOwnerContent;
  window.ownerContentKeyHint = ownerContentKeyHint;
  window.loadContractLayerStatus = loadContractLayerStatus;
  window.saveAdviceRationale = saveAdviceRationale;
  window.recordW033Declaration = recordW033Declaration;
})();
