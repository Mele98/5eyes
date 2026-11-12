/**
 * Datenschutz-Governance (DSG-Technikaudit 2026-11-11, Paket H10):
 * Bearbeitungsverzeichnis und Angaben des Verantwortlichen (C-DSG-01),
 * Betroffenenanfragen (C-DSG-02), ausgehende Kanaele (C-DSG-03) und
 * Sicherheitsvorfaelle (C-DSG-04).
 *
 * Ausgelagerter Monolith-Teil (EXTRACTED_MONOLITH_PARTS, eigenes Budget),
 * eingebunden am Ende von ares.html. Haengt sich selbst ein:
 * Administration > Compliance > "Datenschutz" (Button #asec-privacy-gov,
 * Panel #sec-privacy-gov, Laden ueber loadPrivacyGovernance()).
 *
 * Grundsaetze: keine Vorbelegung, Sperren und Gruende kommen 1:1 vom
 * Backend, keine erfundenen Werte.
 *
 * Monolith-Budget: renderAuditLogPagination() (Protokoll-Ansicht der
 * Administration, Teil der Nachvollziehbarkeit) ist unveraendert aus
 * ares.html hierher umgezogen, damit die Einbindung den Monolithen nicht
 * vergroessert.
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
    return String(v == null ? '' : v).replace(/[&<>"']/g, function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
    });
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
  var BTN = 'style="font-size:10px;padding:3px 10px"';

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

  // ── Uebersicht ───────────────────────────────────────────────────────────
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

  // ── Angaben des Verantwortlichen ─────────────────────────────────────────
  function renderOwnerFields(){
    var rows = state.fields.map(function(f, i){
      var blocking = f.blocking === 'customer_output' ? 'Pflicht (Auskunft)' : (f.blocking === 'channel' ? 'Pflicht für Kanal' : 'Information');
      return '<tr data-owner-field="' + esc(f.key) + '"><td style="padding:3px 6px">' + esc(f.label)
        + '<div style="font-size:8px;color:var(--n4)">' + esc(f.key) + ' &middot; ' + esc(blocking) + '</div></td>'
        + '<td style="padding:3px 6px">' + badge(f.status === 'CONFIRMED', 'bestätigt (Rev. ' + f.revision + ')', 'offen') + '</td>'
        + '<td style="padding:3px 6px"><input class="fi" id="pg-of-' + i + '" value="' + esc(f.value || '') + '" style="font-size:10px;width:100%"></td>'
        + '<td style="padding:3px 6px"><button class="btn-s" ' + BTN + ' onclick="savePrivacyOwnerField(' + i + ')">Speichern</button></td></tr>';
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

  async function approvePrivacyArtifact(kind){
    return run(function(){ return API.post('/privacy/' + kind + '/approve', {keys: []}); }, 'Neue Fassung freigegeben.');
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

  // ── Betroffenenanfragen ──────────────────────────────────────────────────
  function clientName(id){
    var c = state.clients.find(function(x){ return x.id === id; });
    return c ? ((c.first_name || '') + ' ' + (c.last_name || '')).trim() || c.client_number || id : id;
  }

  function nextStepForm(r){
    var id = esc(r.id);
    if (r.status === 'RECEIVED' || r.status === 'IDENTITY_FAILED') {
      return '<select class="fsel" id="pg-id-method-' + id + '" style="font-size:10px">' + opts(IDENTITY, 'Prüfmethode') + '</select> '
        + '<input class="fi" id="pg-id-ref-' + id + '" placeholder="Nachweis (z. B. Ausweis geprüft, Ablage)" style="font-size:10px"> '
        + '<button class="btn-s" ' + BTN + ' onclick="verifySubjectRequestIdentity(\'' + id + '\',\'VERIFIED\')">Identität bestätigt</button> '
        + '<button class="btn-s" ' + BTN + ' onclick="verifySubjectRequestIdentity(\'' + id + '\',\'FAILED\')">nicht bestätigt</button>'
        + (r.status === 'IDENTITY_FAILED' ? '<div style="margin-top:3px"><input class="fi" id="pg-dec-reason-' + id + '" placeholder="Begründung der Ablehnung" style="font-size:10px"> '
          + '<button class="btn-s" ' + BTN + ' onclick="decideSubjectRequest(\'' + id + '\',\'REFUSE\')">Ablehnen</button></div>' : '');
    }
    if (r.status === 'IDENTITY_VERIFIED') {
      return '<input class="fi" id="pg-dec-reason-' + id + '" placeholder="Begründung (Pflicht bei Einschränkung/Ablehnung)" style="font-size:10px"> '
        + '<input class="fi" id="pg-dec-scope-' + id + '" placeholder="Eingeschränkte Sektionen (kommagetrennt)" style="font-size:10px"> '
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
        html += '<input class="fi" id="pg-act-' + id + '" placeholder="' + (r.request_type === 'ERASURE' ? 'ID des ausgeführten Löschvorgangs' : 'Was wurde berichtigt?') + '" style="font-size:10px"> '
          + '<button class="btn-s" ' + BTN + ' onclick="recordSubjectRequestAction(\'' + id + '\')">Umsetzung erfassen</button> ';
      }
      html += '<div style="margin-top:3px"><input class="fi" type="date" id="pg-del-at-' + id + '" value="' + today() + '" style="font-size:10px"> '
        + '<select class="fsel" id="pg-del-ch-' + id + '" style="font-size:10px">' + opts(CHANNELS, 'Zustellkanal') + '</select> '
        + '<input class="fi" id="pg-del-ref-' + id + '" placeholder="Zustellnachweis (z. B. Einschreiben-Nr.)" style="font-size:10px"> '
        + '<button class="btn-p" ' + BTN + ' onclick="deliverSubjectRequest(\'' + id + '\')">Zustellung erfassen</button></div>';
      return html;
    }
    return '';
  }

  function renderRequests(){
    var rows = state.requests.map(function(r){
      var due = r.effective_due_at + (r.overdue ? ' <b style="color:var(--neg)">überfällig</b>' : (r.days_remaining != null ? ' (' + r.days_remaining + ' Tage)' : ''));
      return '<tr data-subject-request="' + esc(r.id) + '"><td style="padding:3px 6px">' + esc(REQUEST_TYPES[r.request_type] || r.request_type)
        + '<div style="font-size:8px;color:var(--n4)">' + esc(clientName(r.client_id)) + '</div></td>'
        + '<td style="padding:3px 6px">' + esc(String(r.received_at || '').slice(0, 10)) + '</td>'
        + '<td style="padding:3px 6px">' + due + '</td>'
        + '<td style="padding:3px 6px">' + esc(STATUS[r.status] || r.status) + (r.decision ? ' &middot; ' + esc(r.decision) : '') + '</td>'
        + '<td style="padding:3px 6px">' + nextStepForm(r) + '</td></tr>';
    }).join('') || '<tr><td style="font-size:10px;color:var(--n4)">Keine Anfragen erfasst.</td></tr>';
    var clientOptions = '<option value="">Kunde wählen</option>' + state.clients.map(function(c){
      return '<option value="' + esc(c.id) + '">' + esc(clientName(c.id)) + '</option>';
    }).join('');
    return '<div class="admin-section-title" style="margin-top:12px">Betroffenenanfragen</div>'
      + '<div style="font-size:9px;color:var(--n4);margin-bottom:4px">Frist: 30 Tage ab Eingang. Der Datenexport entsteht nur über die Anfrage.</div>'
      + '<div style="display:flex;flex-wrap:wrap;gap:6px;align-items:flex-end;margin-bottom:6px">'
      + '<div>' + L + 'Kunde</label><select class="fsel" id="pg-new-client" style="font-size:10px">' + clientOptions + '</select></div>'
      + '<div>' + L + 'Art</label><select class="fsel" id="pg-new-type" style="font-size:10px">' + opts(REQUEST_TYPES) + '</select></div>'
      + '<div>' + L + 'Eingang</label><input class="fi" type="date" id="pg-new-received" value="' + today() + '" style="font-size:10px"></div>'
      + '<div>' + L + 'Kanal</label><select class="fsel" id="pg-new-channel" style="font-size:10px">' + opts(CHANNELS) + '</select></div>'
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

  // ── Sicherheitsvorfaelle ─────────────────────────────────────────────────
  function incidentActions(i){
    var id = esc(i.id);
    var html = '';
    if (i.status === 'CLOSED') return '';
    if (!i.risk_level || i.status === 'ASSESSED' || i.status === 'OPEN') {
      html += '<select class="fsel" id="pg-inc-risk-' + id + '" style="font-size:10px">' + opts({LOW: 'kein hohes Risiko', HIGH: 'voraussichtlich hohes Risiko', UNKNOWN: 'noch unbekannt'}, 'Risiko') + '</select> '
        + '<input class="fi" id="pg-inc-rat-' + id + '" placeholder="Begründung" style="font-size:10px"> '
        + '<button class="btn-s" ' + BTN + ' onclick="assessSecurityIncident(\'' + id + '\')">Bewerten</button> ';
    }
    if (i.risk_level && !i.notification_decision) {
      html += '<div style="margin-top:3px"><input class="fi" id="pg-inc-dec-' + id + '" placeholder="Begründung (Pflicht bei keine Meldung)" style="font-size:10px"> '
        + '<button class="btn-p" ' + BTN + ' onclick="decideSecurityIncident(\'' + id + '\',\'NOTIFY\')">An EDÖB melden</button> '
        + (i.risk_level === 'LOW' ? '<button class="btn-s" ' + BTN + ' onclick="decideSecurityIncident(\'' + id + '\',\'NOT_REQUIRED\')">Keine Meldung</button>' : '') + '</div>';
    }
    if (i.notification_decision === 'NOTIFY' && !i.edoeb_notified_at) {
      html += '<div style="margin-top:3px"><input class="fi" id="pg-inc-ref-' + id + '" placeholder="Referenz/Quittung der Meldung" style="font-size:10px"> '
        + '<button class="btn-p" ' + BTN + ' onclick="recordSecurityIncidentNotification(\'' + id + '\')">Meldung erfolgt</button></div>';
    }
    if (i.risk_level && (!i.subject_notification_decision || i.subject_notification_decision === 'DEFERRED')) {
      html += '<div style="margin-top:3px"><input class="fi" id="pg-inc-sub-' + id + '" placeholder="Begründung (bei keine/aufgeschoben)" style="font-size:10px"> '
        + '<button class="btn-s" ' + BTN + ' onclick="decideSecurityIncidentSubjects(\'' + id + '\',\'NOTIFY\')">Betroffene informieren</button> '
        + '<button class="btn-s" ' + BTN + ' onclick="decideSecurityIncidentSubjects(\'' + id + '\',\'NOT_REQUIRED\')">Nicht nötig</button> '
        + '<button class="btn-s" ' + BTN + ' onclick="decideSecurityIncidentSubjects(\'' + id + '\',\'DEFERRED\')">Aufschieben</button></div>';
    }
    if (i.subject_notification_decision === 'NOTIFY' && !i.subjects_notified_at) {
      html += '<div style="margin-top:3px"><select class="fsel" id="pg-inc-sch-' + id + '" style="font-size:10px">' + opts(CHANNELS, 'Kanal') + '</select> '
        + '<input class="fi" id="pg-inc-sref-' + id + '" placeholder="Nachweis der Information" style="font-size:10px"> '
        + '<button class="btn-s" ' + BTN + ' onclick="recordSecurityIncidentSubjects(\'' + id + '\')">Information erfolgt</button></div>';
    }
    if (i.remediation_status !== 'DONE') {
      html += '<div style="margin-top:3px"><input class="fi" id="pg-inc-rem-' + id + '" placeholder="Behebung/Massnahmen" style="font-size:10px"> '
        + '<button class="btn-s" ' + BTN + ' onclick="recordSecurityIncidentRemediation(\'' + id + '\')">Behebung erfasst</button></div>';
    }
    html += '<div style="margin-top:3px"><input class="fi" id="pg-inc-close-' + id + '" placeholder="Abschlussnotiz" style="font-size:10px"> '
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
      return '<tr data-incident="' + esc(i.id) + '"><td style="padding:3px 6px">' + esc(i.reference)
        + '<div style="font-size:8px;color:var(--n4)">' + esc(INCIDENT_TYPES[i.incident_type] || i.incident_type) + ' &middot; ' + esc(String(i.discovered_at || '').slice(0, 16)) + '</div></td>'
        + '<td style="padding:3px 6px">' + esc(i.description) + '</td>'
        + '<td style="padding:3px 6px">' + esc(STATUS[i.status] || i.status) + (i.risk_level ? ' &middot; Risiko ' + esc({HIGH: 'hoch', UNKNOWN: 'unbekannt', LOW: 'nicht hoch'}[i.risk_level] || i.risk_level) : '') + '</td>'
        + '<td style="padding:3px 6px">' + incidentActions(i) + '</td></tr>';
    }).join('') || '<tr><td style="font-size:10px;color:var(--n4)">Keine Vorfälle erfasst.</td></tr>';
    var contact = gate.escalation_contact || {};
    return '<div class="admin-section-title" style="margin-top:12px">Sicherheitsvorfälle</div>'
      + '<div id="pg-incident-gate" data-blocked="' + (gate.blocked ? '1' : '0') + '" style="font-size:10px">'
      + (gate.blocked ? '<b style="color:var(--neg)">Meldepflicht offen: bei voraussichtlich hohem Risiko so rasch als möglich an den EDÖB melden.</b>' : 'Keine offene Meldepflicht.')
      + ' Eskalationskontakt: ' + (contact.status === 'CONFIRMED' ? esc(contact.value) : '<span style="color:var(--neg)">offen</span>')
      + (findings ? '<ul style="margin:4px 0 0 14px;padding:0">' + findings + '</ul>' : '') + '</div>'
      + '<div style="display:flex;flex-wrap:wrap;gap:6px;align-items:flex-end;margin:6px 0">'
      + '<div>' + L + 'Entdeckt am</label><input class="fi" type="datetime-local" id="pg-inc-new-at" style="font-size:10px"></div>'
      + '<div>' + L + 'Art</label><select class="fsel" id="pg-inc-new-type" style="font-size:10px">' + opts(INCIDENT_TYPES) + '</select></div>'
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

  // ── Ausgehende Verbindungen ──────────────────────────────────────────────
  function renderEgress(){
    var egress = state.egress || {};
    var runtime = egress.runtime || {channels: [], recent_blocked: []};
    var rows = (runtime.channels || []).map(function(c){
      var why = !c.approved ? 'gesperrt: Freigabe fehlt/veraltet' : (c.owner_block ? 'gesperrt: ' + c.owner_block : 'gesperrt');
      var allowed = c.allowed_now ? badge(true, 'erlaubt', '') : (c.configured ? badge(false, '', why) : '<span style="font-size:9px;color:var(--n4)">nicht konfiguriert</span>');
      return '<tr data-egress-channel="' + esc(c.id) + '"><td style="padding:3px 6px">' + esc(c.id) + '</td><td style="padding:3px 6px">' + esc(c['class'])
        + '</td><td style="padding:3px 6px">' + esc((c.hosts || []).join(', ')) + '</td><td style="padding:3px 6px">' + (c.personal_data ? 'ja' : 'nein')
        + '</td><td style="padding:3px 6px">' + allowed + '</td></tr>';
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

  // ── Protokoll-Ansicht (aus ares.html umgezogen, unveraendert) ────────────
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

  // ── Laden ────────────────────────────────────────────────────────────────
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
      host.innerHTML = renderSummary() + renderOwnerFields() + renderRequests() + renderIncidents() + renderEgress();
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
  if (typeof document !== 'undefined' && document.addEventListener) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mountPrivacyGovernance);
    else mountPrivacyGovernance();
  }

  window.renderAuditLogPagination = renderAuditLogPagination;
  window.loadPrivacyGovernance = loadPrivacyGovernance;
  window.savePrivacyOwnerField = savePrivacyOwnerField;
  window.exportProcessingRegister = exportProcessingRegister;
  window.approvePrivacyArtifact = approvePrivacyArtifact;
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
