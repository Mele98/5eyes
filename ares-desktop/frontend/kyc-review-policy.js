/**
 * KYC-Wiedervorlage-Policy (C-890-01 Nachtrag 1) -- Administration und
 * Freigabe durch eine zweite Person.
 *
 * Ausgelagerter Monolith-Teil (EXTRACTED_MONOLITH_PARTS, eigenes Budget),
 * eingebunden am Ende von ares.html; haengt sich beim DOMContentLoaded selbst
 * ein:
 *   - Administration > Compliance > "KYC-Wiedervorlage" (Button + Panel
 *     #sec-kyc-review-policy): Versionen mit Status, neue Version erfassen,
 *     Freigabe durch eine zweite Person mit Anzeige des Pruefwerts (Hash).
 *   - Rolle "compliance_reviewer" (externe Compliance-Person): nach der
 *     Anmeldung NUR diese Freigabe-Ansicht (initApp wird fuer diese Rolle nicht
 *     ausgefuehrt; der Server sperrt alle anderen Routen zentral).
 *   - Benutzerverwaltung: Rolle "Externe Compliance-Freigabe" waehlbar.
 *
 * Grundsaetze: keine Fristwerte vorbelegt; Status, Sperrgruende und die
 * Obergrenze kommen 1:1 vom Server (GET /compliance/kyc-review-policies).
 */
(function(){
  'use strict';

  var REVIEWER_ROLE = 'compliance_reviewer';
  var STATUS_LABELS = {
    entwurf: 'Entwurf – wartet auf Freigabe durch eine zweite Person',
    wirksam: 'wirksam',
    freigegeben_noch_nicht_wirksam: 'freigegeben, noch nicht wirksam',
    abgeloest: 'abgelöst durch neuere Version',
    abgelaufen: 'abgelaufen',
    gesperrt: 'gesperrt (Policy-Kette ungültig)'
  };
  var L = '<label style="font-size:9px;color:var(--n4);display:block;margin-bottom:2px">';

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
  function isReviewer(){ var u = me(); return !!(u && u.role === REVIEWER_ROLE); }
  function months(n){ return n == null ? '—' : esc(n) + ' Monate'; }

  function statusLabel(p){
    var label = STATUS_LABELS[p.status] || p.status;
    if ((p.status === 'wirksam' || p.status === 'freigegeben_noch_nicht_wirksam') && p.effective_from) {
      label += ' ab ' + esc(p.effective_from);
    }
    return label;
  }

  function bannerHtml(data){
    var eff = data.effective_policy;
    if (data.status === 'effective' && eff) {
      return '<div id="krp-banner" data-status="effective" style="font-size:11px;font-weight:600;color:var(--pos)">'
        + 'Wirksame Frist: Policy ' + esc(eff.policy_id) + ' Version ' + esc(eff.version) + ' (seit ' + esc(eff.effective_from) + ') – '
        + 'nächste KYC-Aktualisierung höchstens ' + months(eff.normal_max_months) + ' nach dem Formulardatum, bei PEP/erhöhtem Risiko höchstens '
        + months(eff.elevated_max_months == null ? eff.normal_max_months : eff.elevated_max_months) + '.</div>';
    }
    return '<div id="krp-banner" data-status="' + esc(data.status) + '" style="font-size:11px;font-weight:700;color:var(--neg)">'
      + 'Keine wirksame Frist – Kundenfreigaben gesperrt.</div>'
      + '<div style="font-size:9px;color:var(--n5)">Grund: ' + esc(data.reason_code || data.status) + '. Ares setzt keine eigene Frist; '
      + 'KYC-Bestätigungen, Finalisierung, Unterzeichnung, Weiterleitung und Kundendokumente bleiben gesperrt, bis eine Version erfasst und von einer zweiten Person freigegeben ist.</div>';
  }

  function approvalHtml(p){
    var u = me();
    if (u && String(p.created_by) === String(u.id)) {
      return '<div class="krp-self" style="font-size:9px;color:var(--warn)">Von Ihnen erfasst – die Freigabe muss eine zweite Person erteilen (Vier-Augen-Prinzip).</div>';
    }
    return '<div style="display:grid;gap:4px;margin-top:4px">'
      + '<div style="font-size:9px;color:var(--n5)">Prüfwert (Hash) dieser Version:<br><code id="krp-hash-' + esc(p.id) + '" style="font-size:9px;word-break:break-all">' + esc(p.policy_hash) + '</code></div>'
      + '<div>' + L + 'Freigabereferenz (z. B. Beschluss oder Vorgabe der Aufsichtsorganisation)</label><input class="fi" id="krp-ref-' + esc(p.id) + '" style="font-size:11px"></div>'
      + '<label style="font-size:10px"><input type="checkbox" id="krp-ok-' + esc(p.id) + '"> Ich habe Fristen, Gültigkeit, Quelle und Prüfwert geprüft und gebe diese Version frei.</label>'
      + '<div><button class="btn-p" id="krp-approve-' + esc(p.id) + '" style="font-size:10px;padding:3px 10px" onclick="activateKycReviewPolicy(\'' + esc(p.id) + '\')">Freigeben (zweite Person)</button></div>'
      + '</div>';
  }

  function versionsHtml(data){
    var rows = data.policies || [];
    if (!rows.length) return '<div style="font-size:10px;color:var(--n5)">Noch keine Version erfasst.</div>';
    var html = '<table style="width:100%;border-collapse:collapse;font-size:10px"><thead><tr style="color:var(--n4);text-align:left">'
      + '<th>Version</th><th>Policy-ID</th><th>Normalfrist</th><th>PEP/erhöht</th><th>Gültig</th><th>Quelle</th><th>Status</th></tr></thead><tbody>';
    rows.forEach(function(p){
      html += '<tr data-policy-status="' + esc(p.status) + '" style="border-top:1px solid var(--b1);vertical-align:top">'
        + '<td>' + esc(p.version) + '</td><td>' + esc(p.policy_id) + '</td><td>' + months(p.normal_max_months) + '</td>'
        + '<td>' + (p.elevated_max_months == null ? 'wie Normalfrist' : months(p.elevated_max_months)) + '</td>'
        + '<td>ab ' + esc(p.valid_from) + (p.valid_until ? ' bis ' + esc(p.valid_until) : '') + '</td>'
        + '<td>' + esc(p.source_reference) + '</td>'
        + '<td><span class="krp-status">' + statusLabel(p) + '</span>'
        + (p.approved_at ? '<div style="font-size:9px;color:var(--n5)">Freigabe ' + esc(String(p.approved_at).slice(0, 10)) + ' · Referenz ' + esc(p.approval_reference) + '</div>' : '')
        + (p.status === 'entwurf' ? approvalHtml(p) : '') + '</td></tr>';
    });
    return html + '</tbody></table>';
  }

  function createFormHtml(data){
    if (isReviewer()) return '';
    return '<div style="font-weight:600;font-size:10px;margin-top:10px">Neue Version erfassen</div>'
      + '<div style="font-size:9px;color:var(--n5);line-height:1.5">Tragen Sie die von Ihrer Geschäftsleitung bzw. Aufsichtsorganisation festgelegte Frist ein. '
      + 'Die Frist zählt in ganzen Monaten ab dem Datum des KYC-Formulars. Die Frist für PEP/erhöhtes Risiko darf nicht länger sein als die Normalfrist; leer = gleiche Frist. '
      + 'Erst nach der Freigabe durch eine zweite Person ist die Version wirksam.</div>'
      + '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-top:4px">'
      + '<div>' + L + 'Land (Sitz der Firma)</label><input class="fi" id="krp-jurisdiction" value="' + esc(data.jurisdiction || '') + '" maxlength="2" style="font-size:11px"></div>'
      + '<div>' + L + 'Policy-ID (Ihre Bezeichnung)</label><input class="fi" id="krp-policy-id" style="font-size:11px"></div>'
      + '<div>' + L + 'Normalfrist (Monate)</label><input class="fi" type="number" min="1" step="1" id="krp-normal" style="font-size:11px"></div>'
      + '<div>' + L + 'Frist PEP/erhöhtes Risiko (Monate, optional)</label><input class="fi" type="number" min="1" step="1" id="krp-elevated" style="font-size:11px"></div>'
      + '<div>' + L + 'Gültig ab</label><input class="fi" type="date" id="krp-valid-from" style="font-size:11px"></div>'
      + '<div>' + L + 'Gültig bis (optional)</label><input class="fi" type="date" id="krp-valid-until" style="font-size:11px"></div>'
      + '<div style="grid-column:1/-1">' + L + 'Quelle (z. B. Reglement der Aufsichtsorganisation, interne Weisung)</label><input class="fi" id="krp-source" style="font-size:11px"></div>'
      + '</div><button class="btn-p" id="btn-krp-create" style="margin-top:4px;font-size:10px;padding:3px 10px" onclick="createKycReviewPolicy()">Neue Version erfassen</button>';
  }

  function render(host, data){
    host.innerHTML = '<div class="admin-section-title">KYC-Wiedervorlage (maximale Frist bis zur nächsten KYC-Aktualisierung)</div>'
      + bannerHtml(data)
      + '<div style="font-weight:600;font-size:10px;margin-top:8px">Versionen</div>' + versionsHtml(data)
      + createFormHtml(data);
  }

  function hostEl(){ return document.getElementById('krp-reviewer-body') || document.getElementById('sec-kyc-review-policy'); }

  async function loadKycReviewPolicies(){
    var host = hostEl();
    if (!host) return;
    try {
      render(host, await API.get('/compliance/kyc-review-policies'));
    } catch(e) {
      host.innerHTML = '<div style="color:var(--neg);font-size:10px">' + esc(errText(e, 'KYC-Wiedervorlage konnte nicht geladen werden.')) + '</div>';
    }
  }

  async function createKycReviewPolicy(){
    var normal = val('krp-normal'), elevated = val('krp-elevated');
    var body = {
      jurisdiction: val('krp-jurisdiction'), policy_id: val('krp-policy-id'),
      normal_max_months: normal === '' ? null : Number(normal),
      elevated_max_months: elevated === '' ? null : Number(elevated),
      valid_from: val('krp-valid-from'), valid_until: val('krp-valid-until') || null,
      source_reference: val('krp-source')
    };
    if (!body.jurisdiction || !body.policy_id || body.normal_max_months == null || !body.valid_from || !body.source_reference) {
      notify('error', 'Bitte Land, Policy-ID, Normalfrist, Gültig ab und Quelle angeben.');
      return;
    }
    try {
      await API.post('/compliance/kyc-review-policies', body);
      notify('success', 'Version erfasst. Sie wird wirksam, sobald eine zweite Person sie freigibt.');
    } catch(e) {
      notify('error', errText(e, 'Version konnte nicht erfasst werden.'));
    }
    await loadKycReviewPolicies();
  }

  async function activateKycReviewPolicy(policyRowId){
    var ok = document.getElementById('krp-ok-' + policyRowId);
    var hashEl = document.getElementById('krp-hash-' + policyRowId);
    var ref = val('krp-ref-' + policyRowId);
    if (!ok || !ok.checked || !ref) {
      notify('error', 'Bitte Freigabereferenz angeben und die Prüfung bestätigen.');
      return;
    }
    try {
      await API.post('/compliance/kyc-review-policies/' + encodeURIComponent(policyRowId) + '/activate', {
        policy_hash: hashEl ? String(hashEl.textContent || '').trim() : '', approval_reference: ref
      });
      notify('success', 'Version freigegeben.');
    } catch(e) {
      notify('error', errText(e, 'Freigabe fehlgeschlagen.'));
    }
    await loadKycReviewPolicies();
  }

  // Zeigt die Rechte der gewaehlten Rolle live unter dem Rollen-Select
  // (aus ares.html hierher umgezogen, Monolith-Budget).
  function adminUpdateNewUserRoleHint(){
    var role = (document.getElementById('nu-role')||{value:'advisor'}).value;
    var hint = document.getElementById('nu-role-hint');
    if (hint) hint.textContent = (ADMIN_ROLE_META[role] && ADMIN_ROLE_META[role].rights) || '';
  }

  function reviewerOption(selected){
    return '<option value="' + REVIEWER_ROLE + '"' + (selected ? ' selected' : '') + '>Externe Compliance-Freigabe</option>';
  }

  function mountRoles(){
    if (typeof ADMIN_ROLE_META !== 'undefined' && !ADMIN_ROLE_META[REVIEWER_ROLE]) {
      ADMIN_ROLE_META[REVIEWER_ROLE] = {
        label: 'Externe Compliance-Freigabe', tone: 'warn',
        rights: 'Nur KYC-Wiedervorlage-Policy lesen und als zweite Person freigeben · kein Zugriff auf Kunden, Mandate oder Systemdaten'
      };
    }
    var sel = document.getElementById('nu-role');
    if (sel && !sel.querySelector('option[value="' + REVIEWER_ROLE + '"]')) sel.insertAdjacentHTML('beforeend', reviewerOption(false));
    if (typeof window.adminRenderUserTable === 'function' && !window.adminRenderUserTable.__krp) {
      var original = window.adminRenderUserTable;
      var wrapped = function(){
        var result = original.apply(this, arguments);
        var users = (typeof adminSystemState !== 'undefined' && Array.isArray(adminSystemState.users)) ? adminSystemState.users : [];
        users.forEach(function(u){
          var el = document.getElementById('ul-role-' + u.id);
          if (el && !el.querySelector('option[value="' + REVIEWER_ROLE + '"]')) {
            el.insertAdjacentHTML('beforeend', reviewerOption(u.role === REVIEWER_ROLE));
            if (u.role === REVIEWER_ROLE) el.value = REVIEWER_ROLE;
          }
        });
        return result;
      };
      wrapped.__krp = true;
      window.adminRenderUserTable = wrapped;
    }
  }

  function mountAdminPanel(){
    var anchorBtn = document.getElementById('asec-legal-profile') || document.getElementById('asec-audit');
    if (anchorBtn && !document.getElementById('asec-kyc-review-policy')) {
      var btn = document.createElement('button');
      btn.id = 'asec-kyc-review-policy';
      btn.className = 'admin-sec-btn';
      btn.setAttribute('data-admin-category', 'compliance');
      btn.textContent = 'KYC-Wiedervorlage';
      btn.addEventListener('click', function(){
        if (typeof adminShowSection === 'function') adminShowSection('sec-kyc-review-policy');
        loadKycReviewPolicies();
      });
      anchorBtn.parentNode.insertBefore(btn, anchorBtn.nextSibling);
    }
    var auditPanel = document.getElementById('sec-audit');
    if (auditPanel && !document.getElementById('sec-kyc-review-policy')) {
      var panel = document.createElement('div');
      panel.id = 'sec-kyc-review-policy';
      panel.className = 'admin-sec-panel';
      panel.style.display = 'none';
      panel.style.gap = '12px';
      auditPanel.parentNode.insertBefore(panel, auditPanel);
    }
  }

  // Rolle compliance_reviewer: eigene, schlanke Ansicht statt der App.
  function showReviewerView(){
    var view = document.getElementById('krp-reviewer-view');
    if (!view) {
      view = document.createElement('div');
      view.id = 'krp-reviewer-view';
      view.style.cssText = 'position:fixed;inset:0;z-index:9000;overflow:auto;background:var(--bg,#fff);padding:24px';
      document.body.appendChild(view);
    }
    var u = me() || {};
    view.innerHTML = '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">'
      + '<div style="font-size:14px;font-weight:700">Ares – Compliance-Freigabe</div>'
      + '<div style="font-size:10px">' + esc(u.full_name || u.username || '') + ' · <button class="btn btn-sm" id="krp-logout" onclick="kycReviewerLogout()">Abmelden</button></div></div>'
      + '<div style="font-size:10px;color:var(--n5);margin-bottom:8px">Dieses Konto darf nur die KYC-Wiedervorlage-Policy der Firma prüfen und als zweite Person freigeben.</div>'
      + '<div id="krp-reviewer-body" style="display:grid;gap:8px"></div>';
    return loadKycReviewPolicies();
  }

  async function kycReviewerLogout(){
    var view = document.getElementById('krp-reviewer-view');
    if (view && view.parentNode) view.parentNode.removeChild(view);
    if (typeof doLogout === 'function') await doLogout();
  }

  function wrapInitApp(){
    if (typeof window.initApp !== 'function' || window.initApp.__krp) return;
    var original = window.initApp;
    var wrapped = async function(){
      if (isReviewer()) return showReviewerView();
      return original.apply(this, arguments);
    };
    wrapped.__krp = true;
    window.initApp = wrapped;
  }

  function mountKycReviewPolicy(){
    mountRoles();
    mountAdminPanel();
  }
  wrapInitApp();
  if (typeof document !== 'undefined' && document.addEventListener) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mountKycReviewPolicy);
    else mountKycReviewPolicy();
  }

  window.adminUpdateNewUserRoleHint = adminUpdateNewUserRoleHint;
  window.loadKycReviewPolicies = loadKycReviewPolicies;
  window.createKycReviewPolicy = createKycReviewPolicy;
  window.activateKycReviewPolicy = activateKycReviewPolicy;
  window.kycReviewerLogout = kycReviewerLogout;
})();
