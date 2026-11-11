/**
 * Kundeninformation (Art. 8/9 FIDLEG), KYC-Bestaetigung (GwG, Abklaerung im
 * SRO-/Fremdprozess) und Vertretung (ZGB) -- Paket H8, Compliance-Audit
 * 2026-11-07 (Luecken 2, 5, 7, 10).
 *
 * Ausgelagerter Monolith-Teil (EXTRACTED_MONOLITH_PARTS, eigenes Budget),
 * eingebunden am Ende von ares.html. ares.html bleibt unveraendert bis auf die
 * Einbindung; die Masken haengt dieses Modul beim DOMContentLoaded selbst ein:
 *   - Administration > Compliance > "Rechtliche Angaben" (Button + Panel
 *     #sec-legal-profile, Laden ueber loadAdminLegalProfile())
 *   - Stammdaten: Karte #sd-client-compliance vor "Dokumente"; neu geladen,
 *     sobald das Dokumenten-Archiv (#sd-output-hub) neu gerendert wird
 *     (Mandatswechsel/Review-Zustand).
 *   - Audit-Tabelle: renderAuditLogTable() ist hierher umgezogen (Monolith-
 *     Budget) und zeigt Feldnamen ueber auditFieldLabel() (N-873-09).
 *
 * Grundsaetze: keine Vorbelegung (leere Auswahl = nicht beantwortet), keine
 * erfundenen Werte, Sperrgruende und Owner-Hinweise kommen 1:1 vom Backend
 * (GET /mandates/{id}/client-onboarding/status).
 */
(function(){
  'use strict';

  var AUDIT_FIELD_LABELS = {
    // N-873-09: Ziel-Reihenfolge -- der gewuenschte Rang wird protokolliert,
    // aber nicht uebernommen.
    rank_requested: 'Gewünschter Rang (nicht übernommen)',
    kyc_confirmation: 'KYC-Bestätigung',
    kyc_second_approval: 'KYC-Freigabe (zweite Person)',
    representation_type: 'Vertretung erfasst',
    revoked_at: 'Widerruf',
    delivered_at: 'Kundeninformation übergeben',
    legal_name: 'Firma',
    address_street: 'Adresse: Strasse',
    address_postal_code: 'Adresse: PLZ',
    address_city: 'Adresse: Ort',
    address_country: 'Adresse: Land',
    business_activity: 'Tätigkeitsfeld',
    supervision_type: 'Aufsichtsstatus',
    supervisory_authority: 'Aufsichtsbehörde',
    supervisory_organisation: 'Aufsichtsorganisation',
    license_reference: 'Bewilligung / Register',
    ombudsman_name: 'Ombudsstelle',
    ombudsman_address: 'Ombudsstelle: Adresse',
    contact_phone: 'Kontakt: Telefon',
    contact_email: 'Kontakt: E-Mail',
    contact_website: 'Kontakt: Website'
  };

  function auditFieldLabel(fieldName){
    var key = String(fieldName == null ? '' : fieldName);
    return Object.prototype.hasOwnProperty.call(AUDIT_FIELD_LABELS, key) ? AUDIT_FIELD_LABELS[key] : key;
  }

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
  var L = '<label style="font-size:9px;color:var(--n4);display:block;margin-bottom:2px">';

  // -------------------------------------------------------------------------
  // Administration > Rechtliche Angaben (Kundeninformation FIDLEG)
  // -------------------------------------------------------------------------
  var LEGAL_FIELDS = [
    ['legal_name', 'text'], ['address_street', 'text'], ['address_postal_code', 'text'],
    ['address_city', 'text'], ['address_country', 'text'], ['business_activity', 'textarea'],
    ['supervision_type', 'select'], ['supervisory_authority', 'text'], ['supervisory_organisation', 'text'],
    ['license_reference', 'text'], ['ombudsman_name', 'text'], ['ombudsman_address', 'textarea'],
    ['contact_phone', 'text'], ['contact_email', 'text'], ['contact_website', 'text']
  ];

  function renderLegalProfile(host, data){
    var labels = data.field_labels || {};
    var missing = data.missing_fields || [];
    var html = '<div class="admin-section-title">Rechtliche Angaben (Kundeninformation Art. 8 FIDLEG)</div>'
      + '<div class="admin-risk-note" style="font-size:10px;line-height:1.6">Diese Angaben erscheinen in der Kundeninformation, die jeder Kunde vor Vertragsabschluss erhält. '
      + 'Ares belegt keinen Wert vor. Solange eine Pflichtangabe fehlt, sind Kundeninformation, Finalisierung und Vertragsunterzeichnung gesperrt. '
      + 'Jede Änderung wird im Audit-Log festgehalten.</div>';
    if (missing.length) {
      html += '<div id="lp-missing" style="font-size:10px;color:var(--neg)">Es fehlen: ' + esc((data.missing_labels || missing).join(', ')) + '</div>';
    } else {
      html += '<div id="lp-missing" style="font-size:10px;color:var(--pos)">Vollständig (Revision ' + esc(data.revision) + ').</div>';
    }
    html += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">';
    LEGAL_FIELDS.forEach(function(f){
      var name = f[0], kind = f[1];
      var label = (labels[name] || name) + (missing.indexOf(name) >= 0 ? ' *' : '');
      var current = data[name] == null ? '' : String(data[name]);
      var cell = '<div' + (kind === 'textarea' ? ' style="grid-column:1/-1"' : '') + '>' + L + esc(label) + '</label>';
      if (kind === 'select') {
        cell += '<select class="fsel" id="lp-' + name + '" style="font-size:11px"><option value="">nicht erfasst</option>';
        var opts = data.supervision_labels || {};
        Object.keys(opts).forEach(function(key){
          cell += '<option value="' + esc(key) + '"' + (current === key ? ' selected' : '') + '>' + esc(opts[key]) + '</option>';
        });
        cell += '</select>';
      } else if (kind === 'textarea') {
        cell += '<textarea class="fi" id="lp-' + name + '" rows="2" style="font-size:11px">' + esc(current) + '</textarea>';
      } else {
        cell += '<input class="fi" id="lp-' + name + '" value="' + esc(current) + '" style="font-size:11px">';
      }
      html += cell + '</div>';
    });
    html += '</div><div style="display:flex;gap:8px;align-items:center">'
      + '<button class="btn-p" id="btn-lp-save" onclick="saveAdminLegalProfile()" style="font-size:10px;padding:3px 10px">Speichern</button>'
      + '<span style="font-size:9px;color:var(--n4)">Nur Firmen-Admins. Leeres Feld = Angabe entfernen.</span></div>';
    host.innerHTML = html;
  }

  async function loadAdminLegalProfile(){
    var host = document.getElementById('sec-legal-profile');
    if (!host) return;
    host.innerHTML = '<div class="admin-risk-note">Rechtliche Angaben werden geladen...</div>';
    try {
      renderLegalProfile(host, await API.get('/compliance/legal-profile'));
    } catch(e) {
      host.innerHTML = '<div style="color:var(--neg);font-size:10px">' + esc(errText(e, 'Rechtliche Angaben konnten nicht geladen werden.')) + '</div>';
    }
  }

  async function saveAdminLegalProfile(){
    var host = document.getElementById('sec-legal-profile');
    var body = {};
    LEGAL_FIELDS.forEach(function(f){ body[f[0]] = val('lp-' + f[0]); });
    try {
      var data = await API.put('/compliance/legal-profile', body);
      if (host) renderLegalProfile(host, data);
      notify('success', 'Rechtliche Angaben gespeichert.');
    } catch(e) {
      notify('error', errText(e, 'Rechtliche Angaben konnten nicht gespeichert werden.'));
    }
  }

  // -------------------------------------------------------------------------
  // Mandat: Kundeninformation, KYC-Bestaetigung, Vertretung
  // -------------------------------------------------------------------------
  var REP_LABELS = {vollmacht: 'Vollmacht', vorsorgeauftrag: 'Vorsorgeauftrag', beistandschaft: 'Beistandschaft', gemeinschaftsdepot: 'Gemeinschaftsdepot'};

  function findingsHtml(status){
    var findings = status.findings || [];
    if (!findings.length) {
      return '<div class="tag tn" style="display:inline-block">Kundeninformation und KYC: bereit für Vertragsabschluss</div>';
    }
    var html = '<div style="font-size:10px;color:var(--neg);font-weight:600;margin-bottom:4px">Gesperrt für Finalisierung und Vertragsunterzeichnung</div><ul style="margin:0;padding-left:16px;font-size:10px;line-height:1.6">';
    findings.forEach(function(f){
      html += '<li data-reason-code="' + esc(f.reason_code) + '">' + esc(f.message) + '<br><span style="color:var(--n5)">Zu tun: ' + esc(f.owner_action) + '</span></li>';
    });
    return html + '</ul>';
  }

  function deliveryHtml(status){
    var doc = status.latest_document;
    var html = '<div style="font-weight:600;font-size:10px;margin-top:10px">Kundeninformation (Art. 8/9 FIDLEG)</div>';
    html += '<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:4px 0">'
      + '<button class="btn btn-sm" onclick="downloadClientInformationPdf()">PDF erstellen</button>';
    if (doc) {
      html += '<span style="font-size:9px;color:var(--n5)">Fassung v' + esc(doc.version) + ' · SHA-256 ' + esc(String(doc.checksum_sha256 || '').slice(0, 12)) + '…'
        + (doc.current ? '' : ' · <span style="color:var(--neg)">veraltet, bitte neu erstellen</span>') + '</span>';
    }
    html += '</div>';
    (status.deliveries || []).forEach(function(d){
      html += '<div style="font-size:9px;color:var(--n5)">Übergeben ' + esc(d.delivered_at) + ' (' + esc(d.delivery_channel) + ') · erfasst ' + esc(d.recorded_at) + ' · Fassung ' + esc(String(d.pdf_sha256 || '').slice(0, 12)) + '…'
        + (d.delivery_timing === 'nachtraeglich' ? ' · <span style="color:var(--neg)">nachträglich übergeben (nach Vertragsabschluss)</span>' : '')
        + (d.archive_verified && d.seal_verified ? '' : ' · <span style="color:var(--neg)">Nachweis ungültig</span>') + '</div>';
    });
    if (doc && doc.current) {
      html += '<div style="display:flex;gap:6px;flex-wrap:wrap;align-items:flex-end;margin-top:4px">'
        + '<div>' + L + 'Übergeben am (Zeitpunkt)</label><input class="fi" type="datetime-local" id="ci-delivered-at" style="font-size:11px"></div>'
        + '<div>' + L + 'Kanal</label><select class="fsel" id="ci-channel" style="font-size:11px"><option value="">bitte wählen</option>'
        + '<option value="persoenlich_papier">persönlich (Papier)</option><option value="post">Post</option><option value="email">E-Mail</option><option value="kundenportal">Kundenportal</option></select></div>'
        + '<div style="flex:1;min-width:220px">' + L + 'Begründung (Pflicht, wenn die Übergabe mehr als 24 h zurückliegt)</label><input class="fi" id="ci-backdating" style="font-size:11px"></div>'
        + '<button class="btn btn-sm" onclick="recordClientInformationDelivery(\'' + esc(doc.id) + '\')">Übergabe erfassen</button></div>';
    }
    return html;
  }

  function kycHtml(status, dd){
    var c = status.kyc_confirmation;
    var answered = !!(dd && dd.acting_for_own_account_answered);
    var html = '<div style="font-weight:600;font-size:10px;margin-top:10px">GwG-Abklärung (im SRO-/Fremdprozess) – Bestätigung</div>'
      + '<div style="font-size:9px;color:var(--n5);line-height:1.5">Ares führt die GwG-Abklärung nicht selbst. Erfasst wird, dass sie im Prozess der Selbstregulierungs- bzw. Aufsichtsorganisation oder im Fremdsystem erfolgt ist.</div>';
    html += '<div style="display:flex;gap:6px;flex-wrap:wrap;align-items:flex-end;margin:4px 0">'
      + '<div>' + L + 'Handelt der Kunde auf eigene Rechnung?</label><select class="fsel" id="kyc-own-account" style="font-size:11px">'
      + '<option value=""' + (answered ? '' : ' selected') + '>nicht beantwortet</option>'
      + '<option value="true"' + (answered && dd.acting_for_own_account === true ? ' selected' : '') + '>ja</option>'
      + '<option value="false"' + (answered && dd.acting_for_own_account === false ? ' selected' : '') + '>nein (Dritter wirtschaftlich berechtigt)</option></select></div>'
      + '<div>' + L + 'Wirtschaftlich berechtigte Person (bei nein)</label><input class="fi" id="kyc-bo-name" value="' + esc(dd && dd.beneficial_owner_name || '') + '" style="font-size:11px"></div>'
      + '<button class="btn btn-sm" onclick="saveOwnAccountAnswer()">Antwort speichern</button></div>';
    // C-890-01: Wiedervorlage-Policy der Firma (Server berechnet die Obergrenze).
    var rp = status.kyc_review_policy || {}, rpp = rp.policy;
    html += '<div style="font-size:9px;color:var(--n5)" data-kyc-review-status="' + esc(rp.status || '') + '">Wiedervorlage: '
      + (rpp && rp.policy_status === 'effective' ? 'Policy ' + esc(rpp.policy_id) + ' v' + esc(rpp.version) + ', nächste Aktualisierung höchstens ' + esc(rpp.normal_max_months) + ' Monate (PEP/erhöht ' + esc(rpp.elevated_max_months == null ? rpp.normal_max_months : rpp.elevated_max_months) + ') nach dem Formulardatum'
        : '<span style="color:var(--neg)">keine wirksame, freigegebene Policy der Firma – Erfassung gesperrt</span>') + '</div>';
    if (c) {
      var needs = status.kyc_requires_second_approval;
      html += '<div style="font-size:9px;color:var(--n5)">Letzte Bestätigung: Formular ' + esc(c.form_type) + ' vom ' + esc(c.form_completed_on)
        + ', Referenz ' + esc(c.external_reference) + ', Risiko ' + esc(c.risk_category) + ', PEP ' + (Number(c.is_pep) ? 'ja' : 'nein')
        + ', nächste Aktualisierung ' + esc(c.next_review_due)
        + (needs ? (c.approval_by ? ' · freigegeben' : ' · <span style="color:var(--neg)">Freigabe durch zweite Person fehlt</span> <button class="btn btn-sm" onclick="approveKycConfirmation(\'' + esc(c.id) + '\')">Freigeben (Admin)</button>') : '')
        + '</div>';
    }
    html += '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-top:4px">'
      + '<div>' + L + 'Formular</label><select class="fsel" id="kyc-form" style="font-size:11px"><option value="">bitte wählen</option><option value="A">A (wirtschaftlich Berechtigter)</option><option value="K">K (Kontrollinhaber)</option><option value="S">S (Stiftungen/ähnliche)</option><option value="T">T (Trusts)</option></select></div>'
      + '<div>' + L + 'Formular erstellt am</label><input class="fi" type="date" id="kyc-date" style="font-size:11px"></div>'
      + '<div>' + L + 'Referenz (SRO-/Fremdsystem)</label><input class="fi" id="kyc-ref" style="font-size:11px"></div>'
      + '<div>' + L + 'Risikokategorie</label><select class="fsel" id="kyc-risk" style="font-size:11px"><option value="">bitte wählen</option><option value="normal">normal</option><option value="erhoeht">erhöht</option></select></div>'
      + '<div>' + L + 'PEP</label><select class="fsel" id="kyc-pep" style="font-size:11px"><option value="">bitte wählen</option><option value="false">nein</option><option value="true">ja</option></select></div>'
      + '<div>' + L + 'Nächste Aktualisierung</label><input class="fi" type="date" id="kyc-review" style="font-size:11px"></div>'
      + '<div>' + L + 'Identifizierung der Vertragspartei am (GwG Art. 3)</label><input class="fi" type="date" id="kyc-ident-date" style="font-size:11px"></div>'
      + '<div style="grid-column:span 2;font-size:10px;padding-top:12px"><label><input type="checkbox" id="kyc-ident-ok"> Identifizierung der Vertragspartei ist erfolgt (GwG Art. 3)</label></div>'
      + '</div><button class="btn btn-sm" style="margin-top:4px" onclick="createKycConfirmation()">KYC-Bestätigung erfassen</button>';
    return html;
  }

  function representationsHtml(reps){
    var html = '<div style="font-weight:600;font-size:10px;margin-top:10px">Vertretung und Verfügungsberechtigung (ZGB)</div>';
    (reps || []).forEach(function(r){
      html += '<div style="font-size:9px;color:var(--n5)">' + esc(REP_LABELS[r.representation_type] || r.representation_type) + ': ' + esc(r.representative_name)
        + ' · Umfang ' + esc(r.scope) + ' · Beleg ' + esc(r.evidence_reference)
        + (r.effective_from ? ' · wirksam ab ' + esc(r.effective_from) : '') + (r.disposal_rule ? ' · Verfügung ' + esc(r.disposal_rule) : '')
        + (r.revoked_at ? ' · <em>widerrufen ' + esc(r.revoked_at.slice(0, 10)) + '</em>' : ' <button class="btn btn-sm" onclick="revokeRepresentation(\'' + esc(r.id) + '\')">Widerrufen</button>')
        + '</div>';
    });
    html += '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-top:4px">'
      + '<div>' + L + 'Art</label><select class="fsel" id="rep-type" style="font-size:11px"><option value="">bitte wählen</option><option value="vollmacht">Vollmacht</option><option value="vorsorgeauftrag">Vorsorgeauftrag</option><option value="beistandschaft">Beistandschaft</option><option value="gemeinschaftsdepot">Gemeinschaftsdepot</option></select></div>'
      + '<div>' + L + 'Person (bevollmächtigt / Beistand / Mitinhaber)</label><input class="fi" id="rep-name" style="font-size:11px"></div>'
      + '<div>' + L + 'Umfang</label><input class="fi" id="rep-scope" style="font-size:11px"></div>'
      + '<div>' + L + 'Beleg</label><input class="fi" id="rep-evidence" style="font-size:11px"></div>'
      + '<div>' + L + 'Wirksam ab (Pflicht bei Vorsorgeauftrag/Beistandschaft)</label><input class="fi" type="date" id="rep-from" style="font-size:11px"></div>'
      + '<div>' + L + 'Verfügung (nur Gemeinschaftsdepot)</label><select class="fsel" id="rep-disposal" style="font-size:11px"><option value="">—</option><option value="einzeln">einzeln</option><option value="gemeinsam">gemeinsam</option></select></div>'
      + '<div style="grid-column:1/-1">' + L + 'Widerrufsgrund (für «Widerrufen», mind. 5 Zeichen)</label><input class="fi" id="rep-revoke-reason" style="font-size:11px"></div>'
      + '</div><button class="btn btn-sm" style="margin-top:4px" onclick="createRepresentation()">Vertretung erfassen</button>';
    return html;
  }

  async function renderClientCompliancePanel(){
    var host = document.getElementById('sd-client-compliance');
    var mid = (typeof currentMandateId !== 'undefined') ? currentMandateId : null;
    var cid = (typeof currentClientId !== 'undefined') ? currentClientId : null;
    if (!host) return;
    if (!mid || !cid) { host.innerHTML = '<div style="font-size:10px;color:var(--n4)">Kein Mandat geöffnet.</div>'; return; }
    try {
      var status = await API.get('/mandates/' + encodeURIComponent(mid) + '/client-onboarding/status');
      var dd = status.due_diligence || null;
      var reps = await API.get('/clients/' + encodeURIComponent(cid) + '/representations');
      host.innerHTML = findingsHtml(status) + deliveryHtml(status) + kycHtml(status, dd) + representationsHtml(reps);
      host.setAttribute('data-release-ready', status.release_ready ? '1' : '0');
    } catch(e) {
      host.innerHTML = '<div style="color:var(--neg);font-size:10px">' + esc(errText(e, 'Kundeninformation/KYC-Status konnte nicht geladen werden.')) + '</div>';
    }
  }

  async function run(action, okMessage){
    try { await action(); if (okMessage) notify('success', okMessage); }
    catch(e) { notify('error', errText(e, 'Aktion fehlgeschlagen.')); }
    await renderClientCompliancePanel();
  }

  function downloadClientInformationPdf(){
    var mid = currentMandateId;
    if (!mid || typeof _fetchAndSavePdf !== 'function') return;
    return run(function(){
      return _fetchAndSavePdf('/mandates/' + encodeURIComponent(mid) + '/reports/kundeninformation.pdf', 'kundeninformation');
    });
  }

  function recordClientInformationDelivery(docId){
    var local = val('ci-delivered-at'), channel = val('ci-channel');
    if (!local || !channel) { notify('error', 'Zeitpunkt und Kanal der Übergabe angeben.'); return; }
    var at = new Date(local);
    return run(function(){
      return API.post('/mandates/' + encodeURIComponent(currentMandateId) + '/client-information/deliveries', {
        contract_document_id: docId, delivered_at: at.toISOString(), delivery_channel: channel,
        backdating_reason: val('ci-backdating') || null
      });
    }, 'Übergabe der Kundeninformation erfasst.');
  }

  function saveOwnAccountAnswer(){
    var cid = currentClientId;
    var answer = val('kyc-own-account');
    return run(async function(){
      // Bestehende Erfassung uebernehmen (PUT ersetzt alle Felder); ohne
      // Erfassung (404) wird eine neue angelegt.
      var dd = {};
      var status = await API.get('/mandates/' + encodeURIComponent(currentMandateId) + '/client-onboarding/status');
      if (status.due_diligence) dd = await API.get('/clients/' + encodeURIComponent(cid) + '/due-diligence');
      var body = {
        pep_status: !!Number(dd.pep_status || 0), pep_details: dd.pep_details || null,
        acting_for_own_account: answer === '' ? null : answer === 'true',
        beneficial_owner_name: val('kyc-bo-name') || null, source_of_wealth: dd.source_of_wealth || null,
        id_document_type: dd.id_document_type || null, id_document_number: dd.id_document_number || null,
        id_document_issuing_country: dd.id_document_issuing_country || null,
        id_document_expiry: dd.id_document_expiry || null,
        fatca_crs_self_certified: !!Number(dd.fatca_crs_self_certified || 0)
      };
      return API.put('/clients/' + encodeURIComponent(cid) + '/due-diligence', body);
    }, 'Antwort gespeichert.');
  }

  function createKycConfirmation(){
    var pep = val('kyc-pep'), risk = val('kyc-risk');
    var body = {
      mandate_id: currentMandateId, form_type: val('kyc-form'), form_completed_on: val('kyc-date'),
      external_reference: val('kyc-ref'), risk_category: risk, is_pep: pep === '' ? null : pep === 'true',
      next_review_due: val('kyc-review'),
      identification_confirmed: !!(document.getElementById('kyc-ident-ok') || {}).checked,
      identification_date: val('kyc-ident-date')
    };
    return run(function(){
      return API.post('/clients/' + encodeURIComponent(currentClientId) + '/kyc-confirmations', body);
    }, 'KYC-Bestätigung erfasst.');
  }

  function approveKycConfirmation(confirmationId){
    return run(function(){
      return API.post('/clients/' + encodeURIComponent(currentClientId) + '/kyc-confirmations/' + encodeURIComponent(confirmationId) + '/approve', {});
    }, 'KYC-Bestätigung freigegeben.');
  }

  function createRepresentation(){
    var body = {
      mandate_id: currentMandateId, representation_type: val('rep-type'), representative_name: val('rep-name'),
      scope: val('rep-scope'), evidence_reference: val('rep-evidence'), effective_from: val('rep-from') || null,
      disposal_rule: val('rep-disposal') || null
    };
    return run(function(){
      return API.post('/clients/' + encodeURIComponent(currentClientId) + '/representations', body);
    }, 'Vertretung erfasst.');
  }

  function revokeRepresentation(repId){
    var reason = val('rep-revoke-reason');
    if (reason.length < 5) { notify('error', 'Bitte den Widerrufsgrund angeben.'); return; }
    return run(function(){
      return API.post('/clients/' + encodeURIComponent(currentClientId) + '/representations/' + encodeURIComponent(repId) + '/revoke',
        {reason: reason});
    }, 'Vertretung widerrufen.');
  }

  // -------------------------------------------------------------------------
  // Einhaengen in die bestehenden Masken (ohne Aenderung an ares.html)
  // -------------------------------------------------------------------------
  function mountAdminLegalProfile(){
    var anchorBtn = document.getElementById('asec-audit');
    if (anchorBtn && !document.getElementById('asec-legal-profile')) {
      var btn = document.createElement('button');
      btn.id = 'asec-legal-profile';
      btn.className = 'admin-sec-btn';
      btn.setAttribute('data-admin-category', 'compliance');
      btn.textContent = 'Rechtliche Angaben';
      btn.addEventListener('click', function(){
        if (typeof adminShowSection === 'function') adminShowSection('sec-legal-profile');
        loadAdminLegalProfile();
      });
      anchorBtn.parentNode.insertBefore(btn, anchorBtn.nextSibling);
    }
    var auditPanel = document.getElementById('sec-audit');
    if (auditPanel && !document.getElementById('sec-legal-profile')) {
      var panel = document.createElement('div');
      panel.id = 'sec-legal-profile';
      panel.className = 'admin-sec-panel';
      panel.style.display = 'none';
      panel.style.gap = '12px';
      auditPanel.parentNode.insertBefore(panel, auditPanel);
    }
  }

  var _panelTimer = null;
  function schedulePanelRefresh(){
    if (_panelTimer) clearTimeout(_panelTimer);
    _panelTimer = setTimeout(function(){ _panelTimer = null; renderClientCompliancePanel(); }, 150);
  }

  function mountClientCompliancePanel(){
    var hub = document.getElementById('sd-output-hub');
    var docsCard = hub && hub.closest ? hub.closest('.card') : null;
    if (!docsCard || document.getElementById('sd-client-compliance')) return;
    var card = document.createElement('div');
    card.className = 'card';
    card.style.marginTop = '14px';
    card.innerHTML = '<div class="chd"><span class="cht">Kundeninformation, KYC &amp; Vertretung</span>'
      + '<span style="font-size:9px;color:var(--n4);margin-left:8px">Art. 8/9 FIDLEG &middot; GwG &middot; ZGB &middot; Voraussetzung f&uuml;r Vertragsabschluss</span></div>'
      + '<div class="cbody"><div id="sd-client-compliance"><div style="font-size:10px;color:var(--n4)">Kein Mandat ge&ouml;ffnet.</div></div></div>';
    docsCard.parentNode.insertBefore(card, docsCard);
    if (typeof MutationObserver === 'function') {
      new MutationObserver(schedulePanelRefresh).observe(hub, {childList: true});
    }
  }

  function mountClientCompliance(){
    mountAdminLegalProfile();
    mountClientCompliancePanel();
  }
  if (typeof document !== 'undefined' && document.addEventListener) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mountClientCompliance);
    else mountClientCompliance();
  }

  window.auditFieldLabel = auditFieldLabel;
  window.loadAdminLegalProfile = loadAdminLegalProfile;
  window.saveAdminLegalProfile = saveAdminLegalProfile;
  window.renderClientCompliancePanel = renderClientCompliancePanel;
  window.downloadClientInformationPdf = downloadClientInformationPdf;
  window.recordClientInformationDelivery = recordClientInformationDelivery;
  window.saveOwnAccountAnswer = saveOwnAccountAnswer;
  window.createKycConfirmation = createKycConfirmation;
  window.approveKycConfirmation = approveKycConfirmation;
  window.createRepresentation = createRepresentation;
  window.revokeRepresentation = revokeRepresentation;
})();

// Audit-Log-Tabelle der Administration (aus ares.html hierher umgezogen,
// unveraendert bis auf die Feldbezeichnung ueber auditFieldLabel, N-873-09).
function renderAuditLogTable(entries, container) {
  if (!container) return;
  if (!entries.length) {
    container.textContent = 'Keine Einträge.';
    return;
  }
  var html = '<table style="width:100%;border-collapse:collapse;font-size:10px">'
    + '<thead><tr style="border-bottom:1px solid var(--b2);color:var(--n4)">'
    + '<th style="text-align:left;padding:3px 6px;font-weight:500">Zeitpunkt</th>'
    + '<th style="text-align:left;padding:3px 6px;font-weight:500">Benutzer</th>'
    + '<th style="text-align:left;padding:3px 6px;font-weight:500">Tabelle</th>'
    + '<th style="text-align:left;padding:3px 6px;font-weight:500">Aktion</th>'
    + '<th style="text-align:left;padding:3px 6px;font-weight:500">ID</th>'
    + '<th style="text-align:left;padding:3px 6px;font-weight:500">Feld / Wert</th>'
    + '</tr></thead><tbody>';
  entries.forEach(function(entry) {
    var rawTs = String(entry.created_at || '');
    var ts = rawTs ? (typeof formatIsoLocal === 'function' ? formatIsoLocal(rawTs) : rawTs.slice(0, 16).replace('T', ' ')) : '—';
    var rawId = String(entry.record_id || '');
    var shortId = escapeHtml(rawId.slice(0, 8)) + (rawId.length > 8 ? '…' : '');
    var fieldVal = entry.field_name
      ? escapeHtml(auditFieldLabel(entry.field_name)) + (entry.new_value ? ' → ' + escapeHtml(String(entry.new_value).slice(0, 30)) : '')
      : '';
    var actionColor = {CREATE:'var(--pos)',UPDATE:'var(--warn)',DELETE:'var(--neg)',LOGIN:'var(--g4)',PASSWORD_RESET:'var(--warn)',EXPORT:'var(--n6)'}[entry.action] || 'var(--n6)';
    html += '<tr style="border-bottom:1px solid var(--b1)">'
      + '<td style="padding:3px 6px;color:var(--n5)">' + escapeHtml(ts) + '</td>'
      + '<td style="padding:3px 6px">' + escapeHtml(entry.user_name || '—') + '</td>'
      + '<td style="padding:3px 6px;color:var(--n4)">' + escapeHtml(entry.table_name || '—') + '</td>'
      + '<td style="padding:3px 6px;font-weight:500;color:' + actionColor + '">' + escapeHtml(entry.action || '—') + '</td>'
      + '<td style="padding:3px 6px;color:var(--n4);font-family:monospace">' + shortId + '</td>'
      + '<td style="padding:3px 6px;color:var(--n4)">' + fieldVal + '</td>'
      + '</tr>';
  });
  html += '</tbody></table>';
  container.innerHTML = html;
}
