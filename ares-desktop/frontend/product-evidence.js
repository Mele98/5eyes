/**
 * Produktnachweise (C-COMP-02) -- Erfassung und Freigabe durch eine zweite Person.
 *
 * Eigenes Modul neben dem Monolithen (Monolith-Budget, Toleranz 0); haengt sich
 * beim DOMContentLoaded selbst in Administration > Compliance ein. Die externe
 * Compliance-Person sieht dieselbe Ansicht unter ihrer Freigabe-Ansicht, ohne
 * Erfassung. Regeln, Status und Befunde kommen 1:1 vom Server
 * (GET /products/evidence/overview, GET/POST /products/{id}/evidence); es gibt
 * keine vorbelegten Werte, Fristen oder Gebuehren.
 */
(function(){
  'use strict';

  var KINDS = [
    ['instrument_identity', 'Produktidentität'], ['kid', 'Basisinformationsblatt'], ['costs', 'Kosten'],
    ['retrocession', 'Retrozession'], ['suitability', 'Eignung'], ['liquidity', 'Liquidität'],
    ['currency', 'Währung'], ['sustainability', 'Nachhaltigkeit'], ['price_source', 'Preisquelle']
  ];
  var RATE_KINDS = {costs: true, retrocession: true};
  var STATUS = {draft: 'Entwurf', approved: 'freigegeben', retired: 'stillgelegt', revoked: 'widerrufen'};
  // Kundenverstaendliche Kurztexte je Reason-Code (Katalog core/reason_codes.py).
  var REASONS = {
    PRODUCT_EVIDENCE_MISSING: 'Pflichtnachweis fehlt',
    PRODUCT_EVIDENCE_STALE: 'Nachweis abgelaufen, noch nicht gültig oder ersetzt',
    PRODUCT_EVIDENCE_CONFLICT: 'Nachweise widersprechen sich',
    PRODUCT_EVIDENCE_REVOKED: 'Nachweis widerrufen',
    PRODUCT_EVIDENCE_HASH_MISMATCH: 'Integrität nicht belegt',
    PRODUCT_EVIDENCE_SHARE_CLASS_MISMATCH: 'Andere Produkt- oder Anteilsklassenidentität',
    PRODUCT_EVIDENCE_KID_MISSING: 'Nachweis zum Basisinformationsblatt fehlt',
    PRODUCT_EVIDENCE_COST_MISSING: 'Kostennachweis fehlt',
    PRODUCT_EVIDENCE_RETROCESSION_MISSING: 'Retrozessionsnachweis fehlt',
    PRODUCT_EVIDENCE_SUITABILITY_MISSING: 'Eignungsnachweis fehlt',
    PRODUCT_EVIDENCE_STATE_INVALID: 'In diesem Zustand nicht möglich – bitte neu laden',
    PRODUCT_EVIDENCE_FOUR_EYES_REQUIRED: 'Freigabe durch eine andere Person nötig',
    PRODUCT_EVIDENCE_SUPERSEDED: 'durch neuen Nachweis ersetzt'
  };
  var state = {overview: [], product: null, items: [], epoch: 0};

  function esc(v){
    if (typeof escapeHtml === 'function') return escapeHtml(String(v == null ? '' : v));
    return String(v == null ? '' : v).replace(/[&<>"']/g, function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
    });
  }
  function reasonText(code){
    return Object.prototype.hasOwnProperty.call(REASONS, code) ? REASONS[code] : String(code || '');
  }
  function fail(e, fallback){
    var text = (typeof parseApiError === 'function') ? parseApiError(e, fallback) : fallback;
    if (typeof showAppError === 'function') showAppError(text);
  }
  function el(id){ return document.getElementById(id); }
  function val(id){ var node = el(id); return node ? String(node.value || '').trim() : ''; }
  function user(){ return (typeof currentUser !== 'undefined' && currentUser) ? currentUser : null; }
  function isReviewer(){ var u = user(); return !!(u && u.role === 'compliance_reviewer'); }
  function isAdmin(){ var u = user(); return !!(u && (u.role === 'admin' || u.role === 'super_admin')); }
  function body(){ return el('pe-reviewer-body') || el('sec-product-evidence'); }
  function kindLabel(kind){
    for (var i = 0; i < KINDS.length; i++) if (KINDS[i][0] === kind) return KINDS[i][1];
    return kind;
  }
  function identityOf(productId){
    for (var i = 0; i < state.overview.length; i++) if (state.overview[i].product_id === productId) return state.overview[i];
    return null;
  }

  function overviewHtml(){
    var rows = state.overview.map(function(p, i){
      var ok = p.status === 'verified';
      var open = (p.issues || []).map(function(x){ return esc(kindLabel(x.evidence_kind)) + ': ' + esc(reasonText(x.reason_code)); });
      return '<tr><td>' + esc(p.sub_asset_class || '–') + '</td><td>' + esc(p.product_name) + '</td>'
        + '<td><span class="tag ' + (ok ? 'tg' : 'ta') + '">' + (ok ? 'vollständig belegt' : 'gesperrt') + '</span></td>'
        + '<td style="font-size:10px">' + open.join('<br>') + '</td>'
        + '<td><button class="btn bs" data-pe-open="' + i + '">Nachweise</button></td></tr>';
    });
    return '<div class="card"><div style="font-weight:600;margin-bottom:6px">Produktnachweise</div>'
      + '<div style="font-size:11px;color:var(--n5);margin-bottom:8px">Ohne vollständige, freigegebene und gültige Nachweise '
      + 'wird keine Empfehlung mit dem Produkt gespeichert, publiziert oder ausgeliefert.</div>'
      + '<table class="tbl"><thead><tr><th>Anlageklasse</th><th>Produkt</th><th>Status</th><th>Offen</th><th></th></tr></thead><tbody>'
      + rows.join('') + '</tbody></table></div>';
  }

  function itemHtml(item, i){
    var actions = '';
    if (item.status === 'draft') actions = '<input type="checkbox" data-pe-seen="' + i + '" aria-label="Gesehen">';
    if (item.status === 'approved' && isAdmin()) {
      actions = '<button class="btn bs" data-pe-close="retire:' + i + '">Stilllegen</button> '
        + '<button class="btn bs" data-pe-close="revoke:' + i + '">Widerrufen</button>';
    }
    return '<tr><td>' + esc(kindLabel(item.evidence_kind)) + '</td><td>' + esc(STATUS[item.status] || item.status)
      + (item.reason_code ? ' (' + esc(reasonText(item.reason_code)) + ')' : '') + '</td><td>' + esc(item.valid_from) + ' – '
      + esc(item.valid_until || 'offen') + '</td><td style="font-size:10px">' + esc(item.source_document_title) + '<br>'
      + esc(item.source_reference) + '</td><td style="font-size:10px;word-break:break-all">' + esc(item.canonical_payload_json)
      + '<br>Prüfwert ' + esc(String(item.canonical_payload_hash).slice(0, 12)) + '</td><td>' + actions + '</td></tr>';
  }

  function field(id, label, attrs){
    return '<div><label style="font-size:9px;color:var(--n4);display:block" for="' + id + '">' + label + '</label>'
      + '<input class="fi" id="' + id + '" style="font-size:11px" ' + (attrs || '') + '></div>';
  }

  function formHtml(){
    if (!isAdmin()) return '';
    return '<div class="card"><div style="font-weight:600;margin-bottom:6px">Nachweis als Entwurf erfassen</div>'
      + '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px">'
      + '<div><label style="font-size:9px;color:var(--n4);display:block" for="pe-kind">Nachweisart</label><select class="fsel" id="pe-kind">'
      + KINDS.map(function(k){ return '<option value="' + k[0] + '">' + k[1] + '</option>'; }).join('') + '</select></div>'
      + field('pe-source-type', 'Quellentyp') + field('pe-reference', 'Quelle / Fundstelle') + field('pe-title', 'Dokumenttitel')
      + field('pe-version', 'Dokumentversion (optional)') + field('pe-docdate', 'Dokumentdatum (optional)', 'type="date"')
      + field('pe-sha', 'SHA-256 des Dokuments', 'maxlength="64"') + field('pe-asof', 'Stichtag', 'type="date"')
      + field('pe-from', 'Gültig ab', 'type="date"') + field('pe-until', 'Gültig bis (optional)', 'type="date"')
      + '<div><label style="font-size:9px;color:var(--n4);display:block" for="pe-status">Aussage</label><select class="fsel" id="pe-status">'
      + '<option value="">bitte wählen</option><option value="documented">belegt</option>'
      + '<option value="not_applicable">nicht anwendbar (laut Quelle)</option></select></div>'
      + field('pe-value', 'Satz in Bps p.a. (Kosten/Retrozession)', 'type="number" min="0" step="1"')
      + field('pe-note', 'Interne Notiz (optional)') + '</div>'
      + '<button class="btn bp" id="pe-create" style="margin-top:8px">Entwurf speichern</button></div>';
  }

  function detailHtml(){
    if (!state.product) return '';
    return '<div class="card"><div style="font-weight:600;margin-bottom:6px">' + esc(state.product.product_name) + '</div>'
      + '<div style="font-size:10px;color:var(--n5)">Identität: ' + esc(state.product.stable_instrument_id) + ' / Anteilsklasse: '
      + esc(state.product.share_class_id || 'keine') + '</div><table class="tbl"><thead><tr><th>Art</th><th>Status</th><th>Gültig</th>'
      + '<th>Quelle</th><th>Inhalt</th><th></th></tr></thead><tbody>' + state.items.map(itemHtml).join('') + '</tbody></table>'
      + field('pe-attestation', 'Begründung nur bei Einzelfreigabe (genau eine freigabeberechtigte Person)')
      + '<button class="btn bp" id="pe-approve" style="margin-top:8px">Angekreuzte Entwürfe freigeben</button></div>' + formHtml();
  }

  function render(){
    var host = body();
    if (!host) return;
    host.innerHTML = overviewHtml() + detailHtml();
    Array.prototype.forEach.call(host.querySelectorAll('[data-pe-open]'), function(node){
      node.addEventListener('click', function(){ openProduct(state.overview[Number(node.getAttribute('data-pe-open'))].product_id); });
    });
    Array.prototype.forEach.call(host.querySelectorAll('[data-pe-close]'), function(node){
      node.addEventListener('click', function(){
        var parts = node.getAttribute('data-pe-close').split(':');
        closeItem(state.items[Number(parts[1])], parts[0]);
      });
    });
    if (el('pe-approve')) el('pe-approve').addEventListener('click', approve);
    if (el('pe-create')) el('pe-create').addEventListener('click', create);
  }

  async function load(){
    try {
      state.overview = await API.get('/products/evidence/overview');
      if (state.product) state.product = identityOf(state.product.product_id);
      render();
    } catch (e) { fail(e, 'Produktnachweise konnten nicht geladen werden.'); }
  }
  async function openProduct(productId){
    var epoch = ++state.epoch;
    try {
      var items = await API.get('/products/' + encodeURIComponent(productId) + '/evidence');
      if (epoch !== state.epoch) return; // spaete Antwort eines anderen Produkts
      state.product = identityOf(productId);
      state.items = items;
      render();
    } catch (e) { fail(e, 'Nachweise konnten nicht geladen werden.'); }
  }
  async function reload(){
    var productId = state.product && state.product.product_id;
    await load();
    if (productId) await openProduct(productId);
  }

  function draftBody(product){
    var kind = val('pe-kind');
    var payload = {status: val('pe-status')};
    if (RATE_KINDS[kind] && payload.status !== 'not_applicable' && val('pe-value') !== '') {
      payload.value = Number(val('pe-value'));
      payload.unit = 'bps_per_year';
    }
    return {
      scope: 'tenant', stable_instrument_id: product.stable_instrument_id, share_class_id: product.share_class_id,
      jurisdiction: 'CH', evidence_kind: kind, source_type: val('pe-source-type'), source_reference: val('pe-reference'),
      source_document_title: val('pe-title'), source_document_version: val('pe-version') || null,
      source_document_date: val('pe-docdate') || null, retrieved_at: new Date().toISOString(),
      source_document_sha256: val('pe-sha').toLowerCase(), payload: payload, as_of: val('pe-asof'),
      valid_from: val('pe-from'), valid_until: val('pe-until') || null, note: val('pe-note') || null,
      supersedes_id: supersedes(product, kind)
    };
  }
  // Ein bereits freigegebener eigener Nachweis derselben Linie wird ersetzt.
  function supersedes(product, kind){
    for (var i = 0; i < state.items.length; i++) {
      var item = state.items[i];
      if (item.status === 'approved' && item.tenant_id && item.evidence_kind === kind && item.jurisdiction === 'CH'
          && item.stable_instrument_id === product.stable_instrument_id
          && (item.share_class_id || null) === (product.share_class_id || null)) return item.id;
    }
    return null;
  }
  async function create(){
    if (!val('pe-status')) { fail(null, 'Bitte die Aussage des Nachweises wählen.'); return; }
    try {
      await API.post('/products/' + encodeURIComponent(state.product.product_id) + '/evidence', draftBody(state.product));
      await reload();
    } catch (e) { fail(e, 'Der Entwurf konnte nicht gespeichert werden.'); }
  }
  // Gibt GENAU die angekreuzten, angezeigten Entwuerfe frei (ID + Pruefwert).
  async function approve(){
    var seen = [];
    Array.prototype.forEach.call(body().querySelectorAll('[data-pe-seen]'), function(node){
      if (node.checked) {
        var item = state.items[Number(node.getAttribute('data-pe-seen'))];
        seen.push({item_id: item.id, canonical_payload_hash: item.canonical_payload_hash});
      }
    });
    if (!seen.length) { fail(null, 'Bitte die gesehenen Entwürfe ankreuzen.'); return; }
    try {
      await API.post('/products/' + encodeURIComponent(state.product.product_id) + '/evidence/approve',
        {items: seen, attestation: val('pe-attestation') || null});
    } catch (e) { fail(e, 'Die Freigabe wurde abgelehnt.'); }
    await reload(); // auch nach 409: nie auf einem veralteten Stand weiterarbeiten
  }
  async function closeItem(item, action){
    var label = action === 'revoke' ? 'widerrufen' : 'stilllegen';
    var question = 'Nachweis «' + kindLabel(item.evidence_kind) + '» ' + label + '? Empfehlungen mit diesem Nachweis gelten danach als veraltet.';
    if (typeof uiConfirm !== 'function' || !(await uiConfirm(question))) return;
    try {
      await API.post('/products/evidence/' + encodeURIComponent(item.id) + '/' + action,
        {reason_code: action === 'revoke' ? 'REVOKED_BY_ADMIN' : 'RETIRED_BY_ADMIN'});
    } catch (e) { fail(e, 'Der Nachweis konnte nicht geschlossen werden.'); }
    await reload();
  }

  function mount(){
    var anchor = el('asec-owner-content') || el('asec-legal-profile') || el('asec-audit');
    if (anchor && !el('asec-product-evidence')) {
      var button = document.createElement('button');
      button.id = 'asec-product-evidence';
      button.className = 'admin-sec-btn';
      button.setAttribute('data-admin-category', 'compliance');
      button.textContent = 'Produktnachweise';
      button.addEventListener('click', function(){
        if (typeof adminShowSection === 'function') adminShowSection('sec-product-evidence');
        load();
      });
      anchor.parentNode.insertBefore(button, anchor.nextSibling);
    }
    var audit = el('sec-audit');
    if (audit && !el('sec-product-evidence')) {
      var panel = document.createElement('div');
      panel.id = 'sec-product-evidence';
      panel.className = 'admin-sec-panel';
      panel.style.display = 'none';
      panel.style.gap = '12px';
      audit.parentNode.insertBefore(panel, audit);
    }
    wrapReviewer();
  }
  function wrapReviewer(){
    if (typeof window.initApp !== 'function' || window.initApp.__pe) return;
    var original = window.initApp;
    var wrapped = async function(){
      var result = await original.apply(this, arguments);
      var view = el('krp-reviewer-view');
      if (isReviewer() && view && !el('pe-reviewer-body')) {
        var box = document.createElement('div');
        box.id = 'pe-reviewer-body';
        box.style.cssText = 'display:grid;gap:8px;margin-top:16px';
        view.appendChild(box);
        await load();
      }
      return result;
    };
    wrapped.__pe = true;
    window.initApp = wrapped;
  }

  window.productEvidenceReasonText = reasonText;
  window.loadProductEvidence = load;
  if (typeof document !== 'undefined' && document.addEventListener) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount);
    else mount();
  }
})();
