/**
 * Datenschutz-Governance (DSG-Technikaudit 2026-11-11, H10): Verzeichnis und
 * Angaben des Verantwortlichen (C-DSG-01), Betroffenenanfragen (C-DSG-02),
 * ausgehende Kanaele (C-DSG-03), Sicherheitsvorfaelle (C-DSG-04).
 *
 * Ausgelagerter Monolith-Teil (eigenes Budget), am Ende von ares.html; haengt sich ein:
 * Administration > Compliance > "Datenschutz" (Button #asec-privacy-gov,
 * Panel #sec-privacy-gov, Laden ueber loadPrivacyGovernance()).
 *
 * Keine Vorbelegung, Sperren/Gruende 1:1 vom Backend. renderAuditLogPagination()
 * ist unveraendert aus ares.html umgezogen (Monolith-Budget).
 */
(function(){
  'use strict';

  var REQUEST_TYPES = {ACCESS: 'Auskunft', PORTABILITY: 'Herausgabe', RECTIFICATION: 'Berichtigung', ERASURE: 'Löschung'};
  var CHANNELS = {EMAIL: 'E-Mail', LETTER: 'Brief', IN_PERSON: 'Persönlich', PORTAL: 'Kundenportal', OTHER: 'Andere'};
  var IDENTITY = {ID_DOCUMENT_IN_PERSON: 'Ausweis vor Ort', KNOWN_PERSON_IN_PERSON: 'Persönlich bekannt (vor Ort)',
    CERTIFIED_COPY: 'Beglaubigte Kopie', VIDEO_IDENTIFICATION: 'Video-Identifikation', OTHER: 'Andere'};
  var STATUS = {RECEIVED: 'Eingegangen', IDENTITY_VERIFIED: 'Identität bestätigt', IDENTITY_FAILED: 'Identität nicht bestätigt',
    DECIDED: 'Entschieden', COMPLETED: 'Abgeschlossen', WITHDRAWN: 'Zurückgezogen',
    OPEN: 'Offen', ASSESSED: 'Bewertet', CLOSED: 'Abgeschlossen'};
  var INCIDENT_TYPES = {CONFIDENTIALITY: 'Vertraulichkeit', INTEGRITY: 'Integrität', AVAILABILITY: 'Verfügbarkeit'};

  var state = {fields: [], clients: [], requests: [], incidents: [], gate: null, egress: null, register: null};

  function esc(v){
    if (typeof escapeHtml === 'function') return escapeHtml(String(v == null ? '' : v));
    return String(v == null ? '' : v).replace(/[&<>"']/g, function(c){ return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; });
  }
  function errText(e, fallback){ return (typeof parseApiError === 'function') ? parseApiError(e, fallback) : fallback; }
  function notify(level, message){
    if (level === 'error' && typeof showAppError === 'function') return showAppError(message);
    if (typeof showAppNotice === 'function') return showAppNotice({level: level, message: message});
  }
  function val(id){ var el = document.getElementById(id); return el ? String(el.value || '').trim() : ''; }
  function opts(map, empty){
    return '<option value="">' + esc(empty || 'bitte wählen') + '</option>' + Object.keys(map).map(function(k){
      return '<option value="' + esc(k) + '">' + esc(map[k]) + '</option>';
    }).join('');
  }
  function today(){ return new Date().toISOString().slice(0, 10); }
  function badge(ok, yes, no){
    return '<span style="font-size:9px;padding:1px 6px;border-radius:8px;background:' + (ok ? 'var(--pos-bg,#e7f6ec)' : 'var(--neg-bg,#fdecec)')
      + ';color:' + (ok ? 'var(--pos)' : 'var(--neg)') + '">' + esc(ok ? yes : no) + '</span>';
  }
  var L = '<label style="font-size:9px;color:var(--n4);display:block;margin-bottom:2px">';
  var BTN = 'style="font-size:10px;padding:3px 10px"', TD = '<td style="padding:3px 6px">', FS = 'style="font-size:10px"';

  async function run(action, success){
    try {
      var result = await action();
      if (success) notify('success', success);
      await loadPrivacyGovernance();
      return result;
    } catch (e) {
      notify('error', errText(e, 'Aktion fehlgeschlagen.'));
      return null;
    }
  }

  // ── Uebersicht ──
  function renderSummary(){
    var reg = state.register || {};
    var gate = state.gate || {};
    var overdue = state.requests.filter(function(r){ return r.overdue; }).length;
    var open = (reg.open_blocking_fields || []);
    return '<div class="admin-section-title">Datenschutz</div>'
      + '<div class="admin-risk-note" style="font-size:10px;line-height:1.6">Verzeichnis der Bearbeitungstätigkeiten, Angaben des Verantwortlichen, '
      + 'Betroffenenanfragen, Sicherheitsvorfälle und ausgehende Verbindungen. Ares belegt keine Angabe des Verantwortlichen vor; '
      + 'solange eine Pflichtangabe fehlt, ist die Auskunft an betroffene Personen gesperrt. Keine Rechtsberatung.</div>'
      + '<div id="pg-summary" style="display:flex;flex-wrap:wrap;gap:10px;font-size:10px">'
      + '<div>Verzeichnis: ' + badge(reg.complete, 'vollständig', 'unvollständig') + '</div>'
      + '<div>Auskunft ausgeben: ' + badge(reg.customer_output_ready, 'bereit', 'gesperrt (' + open.length + ' Angaben offen)') + '</div>'
      + '<div>Sicherheitsvorfälle: ' + badge(!gate.blocked, 'keine offene Meldepflicht', 'Meldeentscheid/Meldung offen') + '</div>'
      + '<div>Anfragen überfällig: ' + badge(overdue === 0, '0', String(overdue)) + '</div>'
      + '<div>Freigabe: ' + badge(!(reg.approval_reason_codes || []).length, 'wirksam', (reg.approval_reason_codes || []).join(', ') || 'offen') + '</div>'
      + '<button class="btn-p" ' + BTN + ' onclick="approvePrivacyArtifact(\'processing-register\')">Verzeichnis freigeben</button>'
      + '<button class="btn-s" ' + BTN + ' onclick="exportProcessingRegister()">Verzeichnis exportieren (JSON)</button>'
      + '</div>';
  }

  // ── Angaben des Verantwortlichen ──
  function renderOwnerFields(){
    var rows = state.fields.map(function(f, i){
      var blocking = f.blocking === 'customer_output' ? 'Pflicht (Auskunft)' : (f.blocking === 'channel' ? 'Pflicht für Kanal' : 'Information');
      return '<tr data-owner-field="' + esc(f.key) + '">' + TD + esc(f.label)
        + '<div style="font-size:8px;color:var(--n4)">' + esc(f.key) + ' &middot; ' + esc(blocking) + '</div></td>'
        + TD + badge(f.status === 'CONFIRMED', 'bestätigt (Rev. ' + f.revision + ')', 'offen') + '</td>'
        + TD + '<input class="fi" id="pg-of-' + i + '" value="' + esc(f.value || '') + '" style="font-size:10px;width:100%"></td>'
        + TD + '<button class="btn-s" ' + BTN + ' onclick="savePrivacyOwnerField(' + i + ')">Speichern</button></td></tr>';
    }).join('');
    return '<div class="admin-section-title" style="margin-top:12px">Angaben des Verantwortlichen</div>'
      + '<div style="font-size:9px;color:var(--n4);margin-bottom:4px">Je Zeile den Wert der Firma eintragen und speichern. Jede Änderung wird versioniert und im Audit-Log festgehalten.</div>'
      + '<table id="pg-owner-fields" style="width:100%;border-collapse:collapse;font-size:10px">' + rows + '</table>';
  }

  async function savePrivacyOwnerField(index){
    var field = state.fields[index];
    if (!field) return;
    var value = val('pg-of-' + index);
    if (!value) { notify('error', 'Bitte einen Wert eintragen.'); return; }
    return run(function(){
      return API.put('/privacy/owner-fields/' + encodeURIComponent(field.key), {value: value});
    }, 'Angabe gespeichert.');
  }

  function approvalRows(kind){
    var rows = kind === 'egress-manifest' ? ((state.egress || {}).approval || []) : ((state.register || {}).approval || []);
    return rows.map(function(r){
      var key = r.channel_id || r.activity_key;
      var eff = r.effective ? String(r.effective.content_sha256 || '').slice(0, 12) : '–';
      return '<tr><td style="padding:2px 6px">' + esc(key) + '</td><td style="padding:2px 6px;font-family:monospace">'
        + esc(String(r.current_sha256 || '').slice(0, 12)) + '</td><td style="padding:2px 6px;font-family:monospace">' + esc(eff)
        + '</td><td style="padding:2px 6px">' + esc(r.reason_code || 'wirksam') + '</td></tr>';
    }).join('');
  }

  // Zweistufig: erst Hash-Uebersicht, dann Bestaetigung (keine nativen Dialoge).
  async function approvePrivacyArtifact(kind, confirmed){
    if (!confirmed) {
      var box = document.getElementById('pg-approve-confirm');
      if (box) {
        box.innerHTML = '<div class="admin-risk-note" ' + FS + '>Neue Fassung freigeben: '
          + esc(kind === 'egress-manifest' ? 'Egress-Manifest' : 'Verzeichnis der Bearbeitungen')
          + '. Neuer Hash je Eintrag (aktuell / bisher freigegeben):</div><table style="font-size:9px">' + approvalRows(kind) + '</table>'
          + '<button class="btn-p" ' + BTN + ' onclick="approvePrivacyArtifact(\'' + kind + '\', true)">Freigabe bestätigen</button>';
      }
      return null;  // ohne Bestaetigung nie freigeben
    }
    var result = await run(function(){ return API.post('/privacy/' + kind + '/approve', {keys: []}); }, 'Neue Fassung freigegeben.');
    refreshEgressBanner();
    return result;
  }

  // ── Banner: Datenuebermittlung gesperrt (jede Seite) ──
  async function openPrivacyApproval(field){
    var btn = document.querySelector('#pg-egress-banner button'), label = btn && btn.textContent; // H11: Ladehinweis
    if (btn) { btn.disabled = true; btn.textContent = 'Wird geladen …'; }
    try {
      if (typeof openAdminModal === 'function') await openAdminModal();
      if (typeof adminShowSection === 'function') adminShowSection('sec-privacy-gov');
      await loadPrivacyGovernance(); // N-899-17: "Angaben ergaenzen" fuehrt direkt zum Feld
      var input = field && document.querySelector('[data-owner-field="' + field + '"] input'); if (input) { if (input.scrollIntoView) input.scrollIntoView({block: 'center'}); input.focus(); }
    } finally { if (btn) { btn.disabled = false; btn.textContent = label; } }
  }

  async function refreshEgressBanner(){
    var status;
    try { status = await API.get('/privacy/egress-status'); } catch (e) { return null; }
    var el = document.getElementById('pg-egress-banner');
    if (!status || status.approved) {
      if (el && el.parentNode && el.parentNode.removeChild) el.parentNode.removeChild(el);
      if (el) el.innerHTML = '';
      return status;
    }
    if (!el) {
      if (!document.body) return status;
      el = document.createElement('div');
      el.id = 'pg-egress-banner';
      el.setAttribute('role', 'alert');
      el.style.cssText = 'position:sticky;top:0;z-index:9999;background:var(--neg-bg,#fdecec);color:var(--neg,#a00);padding:6px 12px;font-size:11px;border-bottom:1px solid var(--neg,#a00)';
      document.body.insertBefore(el, document.body.firstChild);
    }
    // N-899-16: Klartext vorne; Kanal-IDs/Reason-Codes nur in den Details.
    var act = status.action || {}, asOf = status.data_as_of || {}, lines = (status.plain_summary || []).length ? status.plain_summary : [status.message || 'Datenübermittlung pausiert'];
    var stand = ' <span ' + FS + '>Datenstand Kurse: ' + esc(asOf.product_prices || asOf.asset_class_prices || 'unbekannt') + ' (' + esc(status.market_data_message || 'nicht aktualisiert') + ').'
      + (asOf.fx_message ? ' Devisen: ' + esc(asOf.fx_message) + '.' : '') + '</span>';
    var details = (status.blocked_channels || []).map(function(c){ return '<li>' + esc(c.channel_id) + ' – gesperrt: ' + esc(c.reason || c.reason_code) + ' (' + esc(c.reason_code) + ')</li>'; }).join('');
    el.innerHTML = '<b>' + lines.map(esc).join(' ') + '</b> ' + (status.is_admin ? '<button class="btn-p" ' + BTN + ' onclick="openPrivacyApproval(\'' + esc(act.field || '') + '\')">' + esc(act.label || 'Jetzt freigeben') + '</button>' : esc(status.advisor_hint || 'Bitte Administrator informieren.'))
      + stand + (details ? ' <details style="display:inline-block;font-size:10px"><summary style="cursor:pointer">Details</summary><ul style="margin:2px 0 0 14px;padding:0">' + details + '</ul></details>' : '');
    return status;
  }

  async function exportProcessingRegister(){
    try {
      var doc = await API.get('/privacy/processing-register/export');
      var blob = new Blob([JSON.stringify(doc, null, 2)], {type: 'application/json'});
      var a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'bearbeitungsverzeichnis-' + (doc.register_version || 'export') + '.json';
      a.click();
    } catch (e) { notify('error', errText(e, 'Export fehlgeschlagen.')); }
  }

  // ── Betroffenenanfragen ──
  function clientName(id){
    var c = state.clients.find(function(x){ return x.id === id; });
    return c ? ((c.first_name || '') + ' ' + (c.last_name || '')).trim() || c.client_number || id : id;
  }

  function nextStepForm(r){
    var id = esc(r.id);
    if (r.status === 'RECEIVED' || r.status === 'IDENTITY_FAILED') {
      return '<select class="fsel" id="pg-id-method-' + id + '" ' + FS + '>' + opts(IDENTITY, 'Prüfmethode') + '</select> '
        + '<input class="fi" id="pg-id-ref-' + id + '" placeholder="Nachweis (z. B. Ausweis geprüft, Ablage)" ' + FS + '> '
        + '<button class="btn-s" ' + BTN + ' onclick="verifySubjectRequestIdentity(\'' + id + '\',\'VERIFIED\')">Identität bestätigt</button> '
        + '<button class="btn-s" ' + BTN + ' onclick="verifySubjectRequestIdentity(\'' + id + '\',\'FAILED\')">nicht bestätigt</button>'
        + (r.status === 'IDENTITY_FAILED' ? '<div style="margin-top:3px"><input class="fi" id="pg-dec-reason-' + id + '" placeholder="Begründung der Ablehnung" ' + FS + '> '
          + '<button class="btn-s" ' + BTN + ' onclick="decideSubjectRequest(\'' + id + '\',\'REFUSE\')">Ablehnen</button></div>' : '');
    }
    if (r.status === 'IDENTITY_VERIFIED') {
      return '<input class="fi" id="pg-dec-reason-' + id + '" placeholder="Begründung (Pflicht bei Einschränkung/Ablehnung)" ' + FS + '> '
        + '<input class="fi" id="pg-dec-scope-' + id + '" placeholder="Eingeschränkte Sektionen (kommagetrennt)" ' + FS + '> '
        + '<button class="btn-s" ' + BTN + ' onclick="decideSubjectRequest(\'' + id + '\',\'FULFILL\')">Erfüllen</button> '
        + '<button class="btn-s" ' + BTN + ' onclick="decideSubjectRequest(\'' + id + '\',\'RESTRICT\')">Einschränken</button> '
        + '<button class="btn-s" ' + BTN + ' onclick="decideSubjectRequest(\'' + id + '\',\'REFUSE\')">Ablehnen</button>';
    }
    if (r.status === 'DECIDED') {
      var html = '';
      var exportable = (r.request_type === 'ACCESS' || r.request_type === 'PORTABILITY') && r.decision !== 'REFUSE';
      if (exportable) {
        html += '<button class="btn-s" ' + BTN + ' onclick="exportSubjectRequest(\'' + id + '\')">' + (r.export_sha256 ? 'Export erneut laden' : 'Export erstellen') + '</button> ';
      } else if (r.decision === 'FULFILL' && !r.action_completed_at) {
        html += '<input class="fi" id="pg-act-' + id + '" placeholder="' + (r.request_type === 'ERASURE' ? 'ID des ausgeführten Löschvorgangs' : 'Was wurde berichtigt?') + '" ' + FS + '> '
          + '<button class="btn-s" ' + BTN + ' onclick="recordSubjectRequestAction(\'' + id + '\')">Umsetzung erfassen</button> ';
      }
      html += '<div style="margin-top:3px"><input class="fi" type="date" id="pg-del-at-' + id + '" value="' + today() + '" ' + FS + '> '
        + '<select class="fsel" id="pg-del-ch-' + id + '" ' + FS + '>' + opts(CHANNELS, 'Zustellkanal') + '</select> '
        + '<input class="fi" id="pg-del-ref-' + id + '" placeholder="Zustellnachweis (z. B. Einschreiben-Nr.)" ' + FS + '> '
        + '<button class="btn-p" ' + BTN + ' onclick="deliverSubjectRequest(\'' + id + '\')">Zustellung erfassen</button></div>';
      return html;
    }
    return '';
  }

  function renderRequests(){
    var rows = state.requests.map(function(r){
      var due = r.effective_due_at + (r.overdue ? ' <b style="color:var(--neg)">überfällig</b>' : (r.days_remaining != null ? ' (' + r.days_remaining + ' Tage)' : ''));
      return '<tr data-subject-request="' + esc(r.id) + '">' + TD + esc(REQUEST_TYPES[r.request_type] || r.request_type)
        + '<div style="font-size:8px;color:var(--n4)">' + esc(clientName(r.client_id)) + '</div></td>'
        + TD + esc(String(r.received_at || '').slice(0, 10)) + '</td>'
        + TD + due + '</td>'
        + TD + esc(STATUS[r.status] || r.status) + (r.decision ? ' &middot; ' + esc(r.decision) : '') + '</td>'
        + TD + nextStepForm(r) + '</td></tr>';
    }).join('') || '<tr><td style="font-size:10px;color:var(--n4)">Keine Anfragen erfasst.</td></tr>';
    var clientOptions = '<option value="">Kunde wählen</option>' + state.clients.map(function(c){
      return '<option value="' + esc(c.id) + '">' + esc(clientName(c.id)) + '</option>';
    }).join('');
    return '<div class="admin-section-title" style="margin-top:12px">Betroffenenanfragen</div>'
      + '<div style="font-size:9px;color:var(--n4);margin-bottom:4px">Frist: 30 Tage ab Eingang. Der Datenexport entsteht nur über die Anfrage.</div>'
      + '<div style="display:flex;flex-wrap:wrap;gap:6px;align-items:flex-end;margin-bottom:6px">'
      + '<div>' + L + 'Kunde</label><select class="fsel" id="pg-new-client" ' + FS + '>' + clientOptions + '</select></div>'
      + '<div>' + L + 'Art</label><select class="fsel" id="pg-new-type" ' + FS + '>' + opts(REQUEST_TYPES) + '</select></div>'
      + '<div>' + L + 'Eingang</label><input class="fi" type="date" id="pg-new-received" value="' + today() + '" ' + FS + '></div>'
      + '<div>' + L + 'Kanal</label><select class="fsel" id="pg-new-channel" ' + FS + '>' + opts(CHANNELS) + '</select></div>'
      + '<button class="btn-p" ' + BTN + ' onclick="openSubjectRequest()">Anfrage erfassen</button></div>'
      + '<table id="pg-requests" style="width:100%;border-collapse:collapse;font-size:10px">' + rows + '</table>';
  }

  async function openSubjectRequest(){
    var body = {client_id: val('pg-new-client'), request_type: val('pg-new-type'), received_at: val('pg-new-received'),
      received_channel: val('pg-new-channel')};
    if (!body.client_id || !body.request_type || !body.received_channel) { notify('error', 'Kunde, Art und Kanal wählen.'); return; }
    return run(function(){ return API.post('/privacy/subject-requests', body); }, 'Anfrage erfasst.');
  }
  async function verifySubjectRequestIdentity(id, outcome){
    var body = {outcome: outcome, method: val('pg-id-method-' + id), evidence_reference: val('pg-id-ref-' + id)};
    if (outcome === 'FAILED') body.failure_reason = body.evidence_reference;
    return run(function(){ return API.post('/privacy/subject-requests/' + encodeURIComponent(id) + '/identity', body); }, 'Identitätsprüfung erfasst.');
  }
  async function decideSubjectRequest(id, decision){
    var scope = val('pg-dec-scope-' + id).split(',').map(function(s){ return s.trim(); }).filter(Boolean);
    var body = {decision: decision, reason: val('pg-dec-reason-' + id) || null, scope: decision === 'RESTRICT' ? scope : []};
    return run(function(){ return API.post('/privacy/subject-requests/' + encodeURIComponent(id) + '/decision', body); }, 'Entscheid erfasst.');
  }
  async function exportSubjectRequest(id){
    var doc = await run(function(){ return API.post('/privacy/subject-requests/' + encodeURIComponent(id) + '/export', {}); }, 'Export erstellt.');
    if (!doc) return;
    try {
      var blob = new Blob([JSON.stringify(doc, null, 2)], {type: 'application/json'});
      var a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'auskunft-' + id + '.json';
      a.click();
    } catch (e) { notify('error', errText(e, 'Download fehlgeschlagen.')); }
  }
  async function recordSubjectRequestAction(id){
    var value = val('pg-act-' + id);
    var r = state.requests.find(function(x){ return x.id === id; }) || {};
    var body = r.request_type === 'ERASURE' ? {erasure_case_id: value} : {completion_note: value};
    return run(function(){ return API.post('/privacy/subject-requests/' + encodeURIComponent(id) + '/action', body); }, 'Umsetzung erfasst.');
  }
  async function deliverSubjectRequest(id){
    var body = {delivered_at: val('pg-del-at-' + id), delivery_channel: val('pg-del-ch-' + id), delivery_reference: val('pg-del-ref-' + id)};
    return run(function(){ return API.post('/privacy/subject-requests/' + encodeURIComponent(id) + '/delivery', body); }, 'Zustellung erfasst.');
  }

  // ── Sicherheitsvorfaelle ──
  function incidentActions(i){
    var id = esc(i.id);
    var html = '';
    if (i.status === 'CLOSED') return '';
    if (!i.risk_level || i.status === 'ASSESSED' || i.status === 'OPEN') {
      html += '<select class="fsel" id="pg-inc-risk-' + id + '" ' + FS + '>' + opts({LOW: 'kein hohes Risiko', HIGH: 'voraussichtlich hohes Risiko', UNKNOWN: 'noch unbekannt'}, 'Risiko') + '</select> '
        + '<input class="fi" id="pg-inc-rat-' + id + '" placeholder="Begründung" ' + FS + '> '
        + '<button class="btn-s" ' + BTN + ' onclick="assessSecurityIncident(\'' + id + '\')">Bewerten</button> ';
    }
    if (i.risk_level && !i.notification_decision) {
      html += '<div style="margin-top:3px"><input class="fi" id="pg-inc-dec-' + id + '" placeholder="Begründung (Pflicht bei keine Meldung)" ' + FS + '> '
        + '<button class="btn-p" ' + BTN + ' onclick="decideSecurityIncident(\'' + id + '\',\'NOTIFY\')">An EDÖB melden</button> '
        + (i.risk_level === 'LOW' ? '<button class="btn-s" ' + BTN + ' onclick="decideSecurityIncident(\'' + id + '\',\'NOT_REQUIRED\')">Keine Meldung</button>' : '') + '</div>';
    }
    if (i.notification_decision === 'NOTIFY' && !i.edoeb_notified_at) {
      html += '<div style="margin-top:3px"><input class="fi" id="pg-inc-ref-' + id + '" placeholder="Referenz/Quittung der Meldung" ' + FS + '> '
        + '<button class="btn-p" ' + BTN + ' onclick="recordSecurityIncidentNotification(\'' + id + '\')">Meldung erfolgt</button></div>';
    }
    if (i.risk_level && (!i.subject_notification_decision || i.subject_notification_decision === 'DEFERRED')) {
      html += '<div style="margin-top:3px"><input class="fi" id="pg-inc-sub-' + id + '" placeholder="Begründung (bei keine/aufgeschoben)" ' + FS + '> '
        + '<button class="btn-s" ' + BTN + ' onclick="decideSecurityIncidentSubjects(\'' + id + '\',\'NOTIFY\')">Betroffene informieren</button> '
        + '<button class="btn-s" ' + BTN + ' onclick="decideSecurityIncidentSubjects(\'' + id + '\',\'NOT_REQUIRED\')">Nicht nötig</button> '
        + '<button class="btn-s" ' + BTN + ' onclick="decideSecurityIncidentSubjects(\'' + id + '\',\'DEFERRED\')">Aufschieben</button></div>';
    }
    if (i.subject_notification_decision === 'NOTIFY' && !i.subjects_notified_at) {
      html += '<div style="margin-top:3px"><select class="fsel" id="pg-inc-sch-' + id + '" ' + FS + '>' + opts(CHANNELS, 'Kanal') + '</select> '
        + '<input class="fi" id="pg-inc-sref-' + id + '" placeholder="Nachweis der Information" ' + FS + '> '
        + '<button class="btn-s" ' + BTN + ' onclick="recordSecurityIncidentSubjects(\'' + id + '\')">Information erfolgt</button></div>';
    }
    if (i.remediation_status !== 'DONE') {
      html += '<div style="margin-top:3px"><input class="fi" id="pg-inc-rem-' + id + '" placeholder="Behebung/Massnahmen" ' + FS + '> '
        + '<button class="btn-s" ' + BTN + ' onclick="recordSecurityIncidentRemediation(\'' + id + '\')">Behebung erfasst</button></div>';
    }
    html += '<div style="margin-top:3px"><input class="fi" id="pg-inc-close-' + id + '" placeholder="Abschlussnotiz" ' + FS + '> '
      + '<button class="btn-s" ' + BTN + ' onclick="closeSecurityIncident(\'' + id + '\')"' + (i.close_problems && i.close_problems.length ? ' title="' + esc(i.close_problems.join('; ')) + '"' : '') + '>Abschliessen</button></div>';
    return html;
  }

  function renderIncidents(){
    var gate = state.gate || {findings: []};
    var findings = (gate.findings || []).map(function(f){
      return '<li style="color:' + (f.blocking ? 'var(--neg)' : 'var(--n4)') + '">' + esc(f.reference) + ': ' + esc(f.message)
        + ' (' + esc(f.hours_since_discovery) + ' h seit Entdeckung)</li>';
    }).join('');
    var rows = state.incidents.map(function(i){
      return '<tr data-incident="' + esc(i.id) + '">' + TD + esc(i.reference)
        + '<div style="font-size:8px;color:var(--n4)">' + esc(INCIDENT_TYPES[i.incident_type] || i.incident_type) + ' &middot; ' + esc(String(i.discovered_at || '').slice(0, 16)) + '</div></td>'
        + TD + esc(i.description) + '</td>'
        + TD + esc(STATUS[i.status] || i.status) + (i.risk_level ? ' &middot; Risiko ' + esc({HIGH: 'hoch', UNKNOWN: 'unbekannt', LOW: 'nicht hoch'}[i.risk_level] || i.risk_level) : '') + '</td>'
        + TD + incidentActions(i) + '</td></tr>';
    }).join('') || '<tr><td style="font-size:10px;color:var(--n4)">Keine Vorfälle erfasst.</td></tr>';
    var contact = gate.escalation_contact || {};
    return '<div class="admin-section-title" style="margin-top:12px">Sicherheitsvorfälle</div>'
      + '<div id="pg-incident-gate" data-blocked="' + (gate.blocked ? '1' : '0') + '" ' + FS + '>'
      + (gate.blocked ? '<b style="color:var(--neg)">Meldepflicht offen: bei voraussichtlich hohem Risiko so rasch als möglich an den EDÖB melden.</b>' : 'Keine offene Meldepflicht.')
      + ' Eskalationskontakt: ' + (contact.status === 'CONFIRMED' ? esc(contact.value) : '<span style="color:var(--neg)">offen</span>')
      + (findings ? '<ul style="margin:4px 0 0 14px;padding:0">' + findings + '</ul>' : '') + '</div>'
      + '<div style="display:flex;flex-wrap:wrap;gap:6px;align-items:flex-end;margin:6px 0">'
      + '<div>' + L + 'Entdeckt am</label><input class="fi" type="datetime-local" id="pg-inc-new-at" ' + FS + '></div>'
      + '<div>' + L + 'Art</label><select class="fsel" id="pg-inc-new-type" ' + FS + '>' + opts(INCIDENT_TYPES) + '</select></div>'
      + '<div style="flex:1;min-width:200px">' + L + 'Beschreibung (ohne Personendaten)</label><input class="fi" id="pg-inc-new-desc" style="font-size:10px;width:100%"></div>'
      + '<button class="btn-p" ' + BTN + ' onclick="recordSecurityIncident()">Vorfall erfassen</button></div>'
      + '<table id="pg-incidents" style="width:100%;border-collapse:collapse;font-size:10px">' + rows + '</table>';
  }

  function incidentPost(id, path, body, message){
    return run(function(){ return API.post('/privacy/incidents/' + encodeURIComponent(id) + path, body); }, message);
  }
  async function recordSecurityIncident(){
    var at = val('pg-inc-new-at');
    var body = {discovered_at: at ? new Date(at).toISOString() : '', incident_type: val('pg-inc-new-type'),
      description: val('pg-inc-new-desc'), affected_data_categories: []};
    if (!body.discovered_at || !body.incident_type || !body.description) { notify('error', 'Zeitpunkt, Art und Beschreibung erfassen.'); return; }
    return run(function(){ return API.post('/privacy/incidents', body); }, 'Vorfall erfasst.');
  }
  function assessSecurityIncident(id){ return incidentPost(id, '/assessment', {risk_level: val('pg-inc-risk-' + id), rationale: val('pg-inc-rat-' + id)}, 'Bewertung erfasst.'); }
  function decideSecurityIncident(id, decision){ return incidentPost(id, '/notification-decision', {decision: decision, reason: val('pg-inc-dec-' + id) || null}, 'Meldeentscheid erfasst.'); }
  function recordSecurityIncidentNotification(id){ return incidentPost(id, '/edoeb-notification', {notified_at: new Date().toISOString(), reference: val('pg-inc-ref-' + id)}, 'Meldung erfasst.'); }
  function decideSecurityIncidentSubjects(id, decision){ return incidentPost(id, '/subject-notification-decision', {decision: decision, reason: val('pg-inc-sub-' + id) || null}, 'Entscheid erfasst.'); }
  function recordSecurityIncidentSubjects(id){ return incidentPost(id, '/subject-notification', {notified_at: new Date().toISOString(), channel: val('pg-inc-sch-' + id), reference: val('pg-inc-sref-' + id)}, 'Information erfasst.'); }
  function recordSecurityIncidentRemediation(id){ return incidentPost(id, '/remediation', {note: val('pg-inc-rem-' + id)}, 'Behebung erfasst.'); }
  function closeSecurityIncident(id){ return incidentPost(id, '/close', {note: val('pg-inc-close-' + id)}, 'Vorfall abgeschlossen.'); }

  // ── Ausgehende Verbindungen ──
  function renderEgress(){
    var egress = state.egress || {};
    var runtime = egress.runtime || {channels: [], recent_blocked: []};
    var rows = (runtime.channels || []).map(function(c){
      var why = !c.approved ? 'gesperrt: Freigabe fehlt/veraltet' : (c.owner_block ? 'gesperrt: ' + c.owner_block : 'gesperrt');
      var allowed = c.allowed_now ? badge(true, 'erlaubt', '') : (c.configured ? badge(false, '', why) : '<span style="font-size:9px;color:var(--n4)">nicht konfiguriert</span>');
      return '<tr data-egress-channel="' + esc(c.id) + '">' + TD + esc(c.id) + '</td>' + TD + esc(c['class'])
        + '</td>' + TD + esc((c.hosts || []).join(', ')) + '</td>' + TD + (c.personal_data ? 'ja' : 'nein')
        + '</td>' + TD + allowed + '</td></tr>';
    }).join('');
    var blocked = (runtime.recent_blocked || []).slice(-10).map(function(b){
      return '<li>' + esc(b.at) + ' &middot; ' + esc(b.host) + ' &middot; ' + esc(b.reason_code) + '</li>';
    }).join('');
    return '<div class="admin-section-title" style="margin-top:12px">Ausgehende Verbindungen</div>'
      + '<div style="font-size:9px;color:var(--n4);margin-bottom:4px">Nur Kanäle aus dem Egress-Manifest sind erlaubt; alles andere wird blockiert. '
      + 'Laufzeitschutz: ' + (runtime.active ? 'aktiv' : '<b style="color:var(--neg)">inaktiv</b>') + '. Jeder Kanal braucht eine freigegebene Fassung. '
      + '<button class="btn-p" ' + BTN + ' onclick="approvePrivacyArtifact(\'egress-manifest\')">Manifest freigeben</button></div>'
      + '<table id="pg-egress" style="width:100%;border-collapse:collapse;font-size:10px">' + rows + '</table>'
      + (blocked ? '<div style="font-size:9px;margin-top:4px">Zuletzt blockiert:<ul style="margin:2px 0 0 14px;padding:0">' + blocked + '</ul></div>' : '');
  }

  // ── Protokoll-Ansicht (aus ares.html umgezogen, unveraendert) ──
  function renderAuditLogPagination(container) {
    if (!container) return;
    var from = _auditLogTotal > 0 ? (_auditLogOffset + 1) : 0;
    var to = _auditLogTotal > 0 ? Math.min(_auditLogOffset + _auditLogLimit, _auditLogTotal) : 0;
    var label = _auditLogTotal > 0
      ? ('Einträge ' + from + '–' + to + ' von ' + _auditLogTotal)
      : 'Keine Einträge';
    var prevDisabled = _auditLogOffset <= 0;
    var nextDisabled = (_auditLogOffset + _auditLogLimit) >= _auditLogTotal;
    container.innerHTML = '<button class="btn" style="font-size:10px;padding:2px 8px"' + (prevDisabled ? ' disabled' : '') + ' onclick="loadAdminAuditLog(' + Math.max(0, _auditLogOffset - _auditLogLimit) + ')">&larr; Zurück</button>'
      + '<span style="padding:0 6px">' + escapeHtml(label) + '</span>'
      + '<button class="btn" style="font-size:10px;padding:2px 8px"' + (nextDisabled ? ' disabled' : '') + ' onclick="loadAdminAuditLog(' + (_auditLogOffset + _auditLogLimit) + ')">Weiter &rarr;</button>';
  }

  // ── Laden ──
  async function loadPrivacyGovernance(){
    var host = document.getElementById('sec-privacy-gov');
    if (!host) return;
    try {
      var results = await Promise.all([
        API.get('/privacy/processing-register'), API.get('/privacy/owner-fields'), API.get('/privacy/subject-requests'),
        API.get('/privacy/incidents'), API.get('/privacy/incidents/gate'), API.get('/privacy/egress-manifest'),
        API.get('/clients').catch(function(){ return []; })
      ]);
      state.register = results[0]; state.fields = results[1] || []; state.requests = results[2] || [];
      state.incidents = results[3] || []; state.gate = results[4]; state.egress = results[5];
      state.clients = Array.isArray(results[6]) ? results[6] : ((results[6] && results[6].items) || []);
      host.innerHTML = renderSummary() + '<div id="pg-approve-confirm"></div>' + renderOwnerFields() + renderRequests() + renderIncidents() + renderEgress();
    } catch (e) {
      host.innerHTML = '<div style="font-size:10px;color:var(--neg)">' + esc(errText(e, 'Datenschutz-Angaben konnten nicht geladen werden.')) + '</div>';
    }
  }

  function mountPrivacyGovernance(){
    var anchorBtn = document.getElementById('asec-audit');
    if (anchorBtn && !document.getElementById('asec-privacy-gov')) {
      var btn = document.createElement('button');
      btn.id = 'asec-privacy-gov';
      btn.className = 'admin-sec-btn';
      btn.setAttribute('data-admin-category', 'compliance');
      btn.textContent = 'Datenschutz';
      btn.addEventListener('click', function(){
        if (typeof adminShowSection === 'function') adminShowSection('sec-privacy-gov');
        loadPrivacyGovernance();
      });
      anchorBtn.parentNode.insertBefore(btn, anchorBtn.nextSibling);
    }
    var auditPanel = document.getElementById('sec-audit');
    if (auditPanel && !document.getElementById('sec-privacy-gov')) {
      var panel = document.createElement('div');
      panel.id = 'sec-privacy-gov';
      panel.className = 'admin-sec-panel';
      panel.style.display = 'none';
      panel.style.gap = '12px';
      auditPanel.parentNode.insertBefore(panel, auditPanel);
    }
  }
  // N-899-04: direkt nach Login und App-Start (initApp des Monolithen).
  function hookInitApp(){
    var original = (typeof window !== 'undefined') ? window.initApp : null;
    if (typeof original !== 'function' || original.__egressBannerHooked) return;
    var wrapped = async function(){
      var result = await original.apply(this, arguments);
      refreshEgressBanner();
      return result;
    };
    wrapped.__egressBannerHooked = true;
    window.initApp = wrapped;
  }
  hookInitApp();

  function startEgressBanner(){
    refreshEgressBanner();
    var timer = (typeof setInterval === 'function') ? setInterval(refreshEgressBanner, 300000) : null;
    if (timer && timer.unref) timer.unref();
  }
  if (typeof document !== 'undefined' && document.addEventListener) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mountPrivacyGovernance);
    else mountPrivacyGovernance();
  }
  var startTimer = (typeof setTimeout === 'function') ? setTimeout(startEgressBanner, 1500) : null;
  if (startTimer && startTimer.unref) startTimer.unref();

  window.renderAuditLogPagination = renderAuditLogPagination;
  window.loadPrivacyGovernance = loadPrivacyGovernance;
  window.savePrivacyOwnerField = savePrivacyOwnerField;
  window.exportProcessingRegister = exportProcessingRegister;
  window.approvePrivacyArtifact = approvePrivacyArtifact;
  window.refreshEgressBanner = refreshEgressBanner;
  window.openPrivacyApproval = openPrivacyApproval;
  window.openSubjectRequest = openSubjectRequest;
  window.verifySubjectRequestIdentity = verifySubjectRequestIdentity;
  window.decideSubjectRequest = decideSubjectRequest;
  window.exportSubjectRequest = exportSubjectRequest;
  window.recordSubjectRequestAction = recordSubjectRequestAction;
  window.deliverSubjectRequest = deliverSubjectRequest;
  window.recordSecurityIncident = recordSecurityIncident;
  window.assessSecurityIncident = assessSecurityIncident;
  window.decideSecurityIncident = decideSecurityIncident;
  window.recordSecurityIncidentNotification = recordSecurityIncidentNotification;
  window.decideSecurityIncidentSubjects = decideSecurityIncidentSubjects;
  window.recordSecurityIncidentSubjects = recordSecurityIncidentSubjects;
  window.recordSecurityIncidentRemediation = recordSecurityIncidentRemediation;
  window.closeSecurityIncident = closeSecurityIncident;
})();
