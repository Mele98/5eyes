/* Ares -- Kernkette CH: Berater-Fuehrung bis "Portfolio generieren" (K2, Dok. 115).
 * Teil des Monolith-Bundles (eigenes Budget). Haengt sich selbst in die
 * bestehenden Masken ein und nutzt die globalen Helfer des Monolithen (API, om,
 * cm, uiConfirm, uiPrompt, escapeHtml, adminShowSection ...), aufgeloest erst
 * beim Aufruf. Keine Fachlogik: alle Zahlen und Freigaben bleiben Serverwahrheit.
 *
 * E2E-02/13  Administration > Firma: Schalter "Ein-Personen-Firma" (PUT /tenants/me,
 *            serverseitig auditiert); Vier-Augen-Sperre nennt beide Wege.
 * E2E-01     Waehrung je Vermoegensposition (Liste der Kurstabelle des Servers).
 * E2E-04     Sichtbare Sperre bei fehlendem/abgelaufenem Kurs + Kurseditor im Ablauf.
 * E2E-05     Vermoegenssummen bei Fremdwaehrung nur umgerechnet (Server), sonst
 *            gekennzeichnet; nie Anteile aus gemischten Waehrungen.
 * E2E-06     Sichtbarer Schritt "Empfehlung finalisieren" vor dem Publizieren.
 * E2E-07     Warnung bei Musterprodukten ohne belegte Stammdaten.
 * E2E-10     Depotbank neutral bzw. aus den eigenen Daten des Kunden.
 * E2E-12     Negative Prognose als Verzehr ("Vermoegen aufgebraucht ab ...").
 * E2E-14     Pensionierungsjahr im Schritt Cashflows & Ziele. */
(function(){
  'use strict';
  function esc(v){ return typeof escapeHtml === 'function' ? escapeHtml(String(v == null ? '' : v)) : String(v == null ? '' : v); }
  function up(v){ return String(v == null ? '' : v).toUpperCase().trim(); }
  function byId(id){ return document.getElementById(id); }
  function detailOf(e){ try { var p = JSON.parse((e && e.body) || '{}'); return p && p.detail; } catch(_){ return null; } }
  function errorText(e, fallback){
    var d = detailOf(e);
    if (d && typeof d === 'object' && d.message) return String(d.message);
    if (typeof d === 'string' && d) return d;
    return String((e && (e.detail || e.message)) || fallback);
  }
  function isAdmin(){ return !!(typeof currentUser !== 'undefined' && currentUser && currentUser.role === 'admin'); }
  function baseCcy(){ return (typeof mandateCurrency === 'function' && mandateCurrency()) || 'Basiswährung'; }
  function notice(level, message){ try { if (typeof showAppNotice === 'function') showAppNotice({level: level, message: message}); } catch(_){} }

  // ---------------------------------------------------------------- Firma (E2E-02/13)
  var FIRM_EXPLAIN = 'Freigeben (publizieren) darf jede aktive Person mit Rolle «Admin» oder «Berater». '
    + 'Ein Berater sieht nur die eigenen Kunden; die zweite Person ist deshalb in der Regel ein Admin. '
    + 'Die Rolle «Compliance-Prüfung» gibt keine Soll-Allokation frei.';

  function mountAdminFirm(){
    var anchor = byId('asec-users');
    if (anchor && !byId('asec-firm')) {
      var btn = document.createElement('button');
      btn.id = 'asec-firm';
      btn.className = 'admin-sec-btn';
      btn.setAttribute('data-admin-category', 'zugriff');
      btn.textContent = 'Firma';
      btn.addEventListener('click', function(){ openAdminFirmSection(false); });
      anchor.parentNode.insertBefore(btn, anchor);
    }
    var usersPanel = byId('sec-users');
    if (usersPanel && !byId('sec-firm')) {
      var panel = document.createElement('div');
      panel.id = 'sec-firm';
      panel.className = 'admin-sec-panel';
      panel.style.display = 'none';
      panel.style.gap = '12px';
      usersPanel.parentNode.insertBefore(panel, usersPanel);
    }
  }

  function renderFirm(host, t){
    var on = Number(t.single_person_firm || 0) === 1;
    var lic = t.max_users == null ? 'ohne Begrenzung' : (String(t.max_users) + ' Benutzer');
    host.innerHTML = '<div class="card"><div class="chd"><span class="cht">Firma</span></div><div class="cbody" style="font-size:12px;line-height:1.6">'
      + '<div><b>' + esc(t.display_name || '') + '</b> · Land ' + esc(t.home_jurisdiction || '') + ' · Lizenz ' + esc(lic) + '</div>'
      + '<fieldset style="border:1px solid var(--b1);border-radius:var(--r);padding:10px 12px;margin-top:10px">'
      + '<legend style="font-weight:600;padding:0 4px">Freigabe der Soll-Allokation</legend>'
      + '<label for="firm-single-person" style="display:flex;gap:8px;align-items:flex-start;cursor:pointer">'
      + '<input type="checkbox" id="firm-single-person" aria-describedby="firm-single-person-help"' + (on ? ' checked' : '') + '>'
      + '<span><b>Ein-Personen-Firma (Einzelfreigabe mit Begründung)</b></span></label>'
      + '<div id="firm-single-person-help" style="color:var(--n6);margin:6px 0 0 24px">'
      + 'Nur einschalten, wenn in Ihrer Firma genau eine Person Empfehlungen freigibt. Dann publizieren Sie eine selbst finalisierte '
      + 'Soll-Allokation mit einer kurzen Begründung (mindestens 20 Zeichen); die Freigabe wird als «Einzelfreigabe» gekennzeichnet. '
      + 'Ausgeschaltet gilt das Vier-Augen-Prinzip. Jede Änderung wird im Protokoll festgehalten.</div>'
      + '<div style="color:var(--n5);margin:6px 0 0 24px">' + esc(FIRM_EXPLAIN) + '</div>'
      + '<div style="margin:10px 0 0 24px"><button class="btn-p" type="button" id="btn-firm-save" onclick="saveAdminFirm()">Speichern</button></div>'
      + '<div id="firm-status" role="status" style="margin:6px 0 0 24px;font-size:12px"></div>'
      + '</fieldset></div></div>';
  }

  async function loadAdminFirm(){
    var host = byId('sec-firm');
    if (!host) return null;
    host.innerHTML = '<div class="admin-risk-note">Firmenangaben werden geladen …</div>';
    try {
      var t = await API.get('/tenants/me');
      renderFirm(host, t);
      return t;
    } catch(e) {
      host.innerHTML = '<div style="color:var(--neg);font-size:12px">' + esc(errorText(e, 'Firmenangaben konnten nicht geladen werden.')) + '</div>';
      return null;
    }
  }

  async function saveAdminFirm(){
    var box = byId('firm-single-person');
    var status = byId('firm-status');
    if (!box) return false;
    var want = box.checked === true;
    var ok = await uiConfirm({
      title: want ? 'Ein-Personen-Firma einschalten' : 'Vier-Augen-Prinzip einschalten',
      message: want
        ? 'Sie bestätigen, dass in Ihrer Firma genau eine Person Empfehlungen freigibt. Selbst finalisierte Soll-Allokationen publizieren Sie danach mit Begründung als Einzelfreigabe. Die Änderung wird protokolliert.'
        : 'Ab jetzt muss eine zweite berechtigte Person jede selbst finalisierte Soll-Allokation freigeben. Die Änderung wird protokolliert.',
      okLabel: 'Bestätigen', cancelLabel: 'Abbrechen'
    });
    if (ok !== true) { box.checked = !want; return false; }
    try {
      await API.put('/tenants/me', {single_person_firm: want});
      markFirmQuestionAnswered({id: 'main'});
      if (status) { status.textContent = want ? 'Gespeichert: Ein-Personen-Firma (Einzelfreigabe mit Begründung).' : 'Gespeichert: Vier-Augen-Prinzip.'; status.style.color = 'var(--pos)'; }
      return true;
    } catch(e) {
      box.checked = !want;
      // H12 plausibilisiert serverseitig (genau eine aktive freigabeberechtigte Person); 409 im Klartext.
      var msg = errorText(e, 'Die Einstellung konnte nicht gespeichert werden.');
      if (e && e.status === 409) msg = 'Nicht möglich: ' + msg + ' Eine Ein-Personen-Firma setzt voraus, dass genau eine aktive Person freigeben darf (Rolle Admin oder Berater). Deaktivieren Sie weitere Konten unter Benutzer & Zugriff oder lassen Sie das Vier-Augen-Prinzip eingeschaltet.';
      if (status) { status.textContent = msg; status.style.color = 'var(--neg)'; }
      return false;
    }
  }

  async function openAdminFirmSection(openModal){
    if (openModal && typeof openAdminModal === 'function') { try { openAdminModal(); } catch(_){} }
    mountAdminFirm();
    if (typeof adminShowSection === 'function') adminShowSection('sec-firm');
    return loadAdminFirm();
  }

  // Erst-Einrichtung: bei einer Lizenz fuer genau einen Benutzer wird die Frage
  // ausdruecklich gestellt (Ja/Nein, beide Antworten gehen ueber PUT /tenants/me
  // und damit ins Protokoll). Nie still gesetzt.
  // N-915-08: eigener Dialog mit drei Ausgaengen -- Ja, Nein, Schliessen/Esc (= spaeter,
  // nichts gespeichert, die Frage bleibt offen und kommt beim naechsten Start wieder).
  var firmAskedThisSession = false;
  function firmQuestionKey(t){ return 'ares.firmQuestionAnswered.' + String((t && t.id) || 'main'); }
  function firmQuestionAnswered(t){ try { return localStorage.getItem(firmQuestionKey(t)) === '1'; } catch(_) { return false; } }
  function markFirmQuestionAnswered(t){ try { localStorage.setItem(firmQuestionKey(t), '1'); } catch(_) {} }
  function firmQuestionDialog(){
    return new Promise(function(resolve){
      var old = byId('m-firm-question');
      if (old && old.parentNode) old.parentNode.removeChild(old);
      var wrap = document.createElement('div');
      wrap.id = 'm-firm-question';
      wrap.className = 'overlay open';
      wrap.dataset.locked = '1';
      wrap.style.zIndex = '9500';
      wrap.innerHTML = '<div class="modal" role="dialog" aria-modal="true" aria-labelledby="firmq-title" aria-describedby="firmq-msg" style="max-width:480px">'
        + '<div class="mhd"><div class="mtitle" id="firmq-title">Arbeiten Sie allein?</div><button class="mx" type="button" id="firmq-later" aria-label="Schliessen, später entscheiden">&#10005;</button></div>'
        + '<div class="mbody"><div id="firmq-msg" style="font-size:12px;color:var(--n7);line-height:1.5">'
        + '<p style="margin:0 0 8px">Ihre Lizenz umfasst einen Benutzer.</p>'
        + '<p style="margin:0 0 8px"><b>Ja:</b> Ein-Personen-Firma. Sie publizieren selbst finalisierte Soll-Allokationen mit einer kurzen Begründung (Einzelfreigabe mit Begründung).</p>'
        + '<p style="margin:0 0 8px"><b>Nein:</b> Vier-Augen-Prinzip. Eine zweite berechtigte Person gibt frei.</p>'
        + '<p style="margin:0">Die Antwort wird protokolliert und ist unter Administration › Firma jederzeit änderbar. Schliessen Sie den Dialog, bleibt die Frage offen.</p></div></div>'
        + '<div class="mfooter"><button class="btn" type="button" id="firmq-no">Nein, Vier-Augen-Prinzip</button><button class="btn-p" type="button" id="firmq-yes">Ja, Ein-Personen-Firma</button></div></div>';
      document.body.appendChild(wrap);
      function done(v){ document.removeEventListener('keydown', onKey, true); if (wrap.parentNode) wrap.parentNode.removeChild(wrap); resolve(v); }
      function onKey(ev){ if (ev.key === 'Escape') { ev.preventDefault(); done(null); } }
      document.addEventListener('keydown', onKey, true);
      byId('firmq-yes').addEventListener('click', function(){ done('yes'); });
      byId('firmq-no').addEventListener('click', function(){ done('no'); });
      byId('firmq-later').addEventListener('click', function(){ done(null); });
      try { byId('firmq-yes').focus(); } catch(_){}
    });
  }
  // Bei einer Lizenz fuer genau einen Benutzer ausdruecklich fragen; Ja/Nein gehen ueber
  // PUT /tenants/me ins Protokoll. Nie still gesetzt. Rueckgabe true/false, null = offen.
  async function askSinglePersonFirmAfterBootstrap(){
    var t;
    try { t = await API.get('/tenants/me'); } catch(_) { return null; }
    if (!t || Number(t.max_users) !== 1 || Number(t.single_person_firm || 0) === 1) return null;
    firmAskedThisSession = true;
    var answer = await firmQuestionDialog();
    if (answer === null) return null;
    try {
      await API.put('/tenants/me', {single_person_firm: answer === 'yes'});
      markFirmQuestionAnswered(t);
    } catch(e) { notice('warn', 'Einstellung Ein-Personen-Firma nicht gespeichert: ' + errorText(e, '?') + ' Bitte unter Administration › Firma nachholen.'); }
    return answer === 'yes';
  }
  // Offene Frage beim naechsten Start erneut stellen (nur Admin, einmal je Sitzung).
  async function askSinglePersonFirmIfOpen(){
    if (!isAdmin() || firmAskedThisSession) return null;
    var t;
    try { t = await API.get('/tenants/me'); } catch(_) { return null; }
    if (!t || firmQuestionAnswered(t)) return null;
    return askSinglePersonFirmAfterBootstrap();
  }
  function hookInitApp(){
    var original = window.initApp;
    if (typeof original !== 'function' || original.__k2Hooked) return;
    var wrapped = async function(){
      var result = await original.apply(this, arguments);
      askSinglePersonFirmIfOpen();
      return result;
    };
    wrapped.__k2Hooked = true;
    window.initApp = wrapped;
  }

  // Vier-Augen-Sperre beim Publizieren (aus allocation-publication.js aufgerufen).
  async function publishFourEyesFlow(mid){
    var tenant = null;
    if (isAdmin()) { try { tenant = await API.get('/tenants/me'); } catch(_) { tenant = null; } }
    if (tenant && Number(tenant.single_person_firm || 0) === 1) {
      var reason = await uiPrompt({title: 'Einzelfreigabe (Ein-Personen-Firma)', message: 'Sie haben die Empfehlung selbst finalisiert. Begründen Sie die Einzelfreigabe kurz (mindestens 20 Zeichen):', required: true, minLength: 20});
      if (!reason || !reason.trim()) return false;
      try {
        var again = await API.get('/mandates/' + mid + '/allocation-publication');
        await API.post('/mandates/' + mid + '/allocation-publication', {target_allocation_id: again.target_allocation_id, validation_hash: again.validation_hash, single_approver_attestation: true, attestation_reason: reason.trim()});
        if (typeof updateStrategyStatus === 'function') updateStrategyStatus('Soll-Allokation publiziert (Einzelfreigabe).', false);
        return true;
      } catch(e2) {
        await uiAlert({level: 'warn', modal: true, title: 'Einzelfreigabe nicht möglich', message: errorText(e2, 'Publizieren nicht möglich.') + '\n\nDie Einzelfreigabe setzt voraus, dass genau eine aktive Person freigeben darf. Sind weitere Admins oder Berater aktiv, muss eine davon freigeben.'});
        return false;
      }
    }
    var goFirm = await uiConfirm({
      title: 'Freigabe durch eine zweite Person nötig',
      message: 'Sie haben die Empfehlung selbst finalisiert. Es gibt zwei Wege:\n\n1. Eine zweite berechtigte Person meldet sich an und publiziert: ein Admin oder der zuständige Berater dieses Kunden (Berater sehen nur die eigenen Kunden).\n\n2. Arbeiten Sie allein, schalten Sie unter Administration › Firma «Ein-Personen-Firma (Einzelfreigabe mit Begründung)» ein und publizieren danach mit Begründung.'
        + (isAdmin() ? '' : '\n\nDie Firmeneinstellung ändert ein Admin.'),
      okLabel: isAdmin() ? 'Zu Administration › Firma' : 'OK', cancelLabel: 'Schliessen'
    });
    if (goFirm === true && isAdmin()) await openAdminFirmSection(true);
    return false;
  }

  // ---------------------------------------------------------------- Wechselkurse (E2E-01/04/05)
  var fxCache = null;
  async function fxRates(force){
    if (!fxCache || force) { try { fxCache = await API.get('/fx-rates/current'); } catch(_) { fxCache = null; } }
    return Array.isArray(fxCache) ? fxCache : [];
  }
  // Einheit der Kurstabelle (Kurs je Einheit, immer 1.0): die Zeile, die der Editor nie sendet.
  function fxIsUnit(ccy){
    return typeof fxRatesSavePayload === 'function' && fxRatesSavePayload([{currency: ccy, value: '1', original: '', confirmed: true}]).rates.length === 0;
  }
  function fxState(ccy, rows, status){
    var row = (rows || []).filter(function(r){ return up(r.currency) === up(ccy); })[0];
    if (up(status) === 'STALE') return 'Kurs abgelaufen';
    if (!row) return 'Kurs fehlt';
    if (typeof fxIsSubstituteSource === 'function' && fxIsSubstituteSource(row.source)) return 'Ersatzkurs – nicht bestätigt';
    return up(status) === 'MISSING' ? 'Kurs fehlt' : 'Kurs belegt';
  }

  function ensureFxModal(){
    var m = byId('m-fx-quick');
    if (m) return m;
    m = document.createElement('div');
    m.className = 'overlay';
    m.id = 'm-fx-quick';
    m.innerHTML = '<div class="modal" role="dialog" aria-modal="true" aria-labelledby="fxq-title" style="max-width:540px">'
      + '<div class="mhd"><div class="mtitle" id="fxq-title">Wechselkurse erfassen</div><button class="mx" type="button" aria-label="Schliessen" onclick="cm(\'m-fx-quick\')">&#10005;</button></div>'
      + '<div class="mbody"><div style="font-size:12px;color:var(--n6);line-height:1.5;margin-bottom:8px">Ein Kurs gilt erst als belegt, wenn Sie ihn erfassen oder als geprüft bestätigen. Ersatzkurse werden nie kundenwirksam verwendet. '
      + 'Dieselben Kurse stehen in der Administration unter Kapitalmarkt-Annahmen › Rendite &amp; Vol. › Wechselkurse.</div>'
      + '<div id="fxq-grid" style="display:grid;grid-template-columns:repeat(2,1fr);gap:10px"></div>'
      + '<div id="fxq-status" role="status" style="font-size:12px;color:var(--n5);margin-top:8px"></div></div>'
      + '<div class="mfooter"><button class="btn" type="button" onclick="cm(\'m-fx-quick\')">Schliessen</button>'
      + '<button class="btn-p" type="button" id="btn-fxq-save" onclick="saveFxQuickEditor()">Kurse speichern</button></div></div>';
    document.body.appendChild(m);
    return m;
  }

  async function openFxQuickEditor(focus){
    ensureFxModal();
    var grid = byId('fxq-grid'), status = byId('fxq-status');
    grid.textContent = 'Lädt …';
    if (status) { status.textContent = ''; status.style.color = 'var(--n5)'; }
    om('m-fx-quick');
    var rows = await fxRates(true);
    var unit = (rows.filter(function(r){ return fxIsUnit(up(r.currency)); })[0] || {}).currency || '';
    var want = (Array.isArray(focus) ? focus : (focus ? [focus] : [])).map(up).filter(Boolean);
    var list = rows.filter(function(r){ return !fxIsUnit(up(r.currency)) && (!want.length || want.indexOf(up(r.currency)) >= 0); });
    if (!list.length) { grid.textContent = 'Keine Wechselkurse verfügbar.'; return false; }
    grid.innerHTML = list.map(function(r){
      var ccy = up(r.currency), sub = typeof fxIsSubstituteSource === 'function' && fxIsSubstituteSource(r.source);
      var shown = Number(r.rate) > 0 ? String(Number(r.rate)) : '';
      return '<div><label class="fl" for="fxq-rate-' + esc(ccy) + '">1 ' + esc(ccy) + (unit ? ' in ' + esc(unit) : '') + ' · '
        + (sub ? '<span style="color:var(--neg);font-weight:600">Ersatzkurs – nicht belegt</span>' : esc(fxSourceText(r.source) + ', ' + String(r.valid_from || '').slice(0, 10))) + '</label>'
        + '<input class="fi fxq-input" id="fxq-rate-' + esc(ccy) + '" type="number" step="0.0001" min="0.0001" data-currency="' + esc(ccy) + '" data-original="' + (sub ? '' : esc(shown)) + '"'
        + (sub ? ' placeholder="' + esc(shown) + '" value=""' : ' value="' + esc(shown) + '"') + '>'
        + '<label style="font-size:12px;color:var(--n5);display:flex;gap:4px;align-items:center;margin-top:3px"><input type="checkbox" class="fxq-confirm" data-currency="' + esc(ccy) + '"> Kurs geprüft (Quelle manuell, Datum heute)</label></div>';
    }).join('');
    try { var first = grid.querySelector('.fxq-input'); if (first) first.focus(); } catch(_){}
    return true;
  }

  async function saveFxQuickEditor(){
    var status = byId('fxq-status');
    var confirms = {};
    document.querySelectorAll('#fxq-grid .fxq-confirm').forEach(function(b){ confirms[b.getAttribute('data-currency')] = b.checked === true; });
    var rows = Array.prototype.map.call(document.querySelectorAll('#fxq-grid .fxq-input'), function(el){
      var ccy = el.getAttribute('data-currency');
      return {currency: ccy, value: el.value, original: el.getAttribute('data-original'), confirmed: confirms[ccy] === true};
    });
    var payload = fxRatesSavePayload(rows);
    if (!payload.rates.length) {
      if (status) { status.textContent = 'Bitte einen Kurs eintragen oder «Kurs geprüft» bestätigen.'; status.style.color = 'var(--neg)'; }
      return false;
    }
    try {
      await API.put('/fx-rates', payload);
      fxCache = null;
      if (status) { status.textContent = 'Gespeichert: ' + payload.rates.map(function(r){ return r.currency; }).join(', ') + '. Bitte die Anlagestrategie neu berechnen.'; status.style.color = 'var(--pos)'; }
      showStrategyBlocker(null);
      resetWealthSummaryCache();
      if (typeof currentClientId !== 'undefined' && currentClientId && typeof refreshWealthUI === 'function') refreshWealthUI(currentClientId);
      return true;
    } catch(e) {
      if (status) { status.textContent = errorText(e, 'Wechselkurse konnten nicht gespeichert werden.'); status.style.color = 'var(--neg)'; }
      return false;
    }
  }

  // Sichtbare Sperre auf der Asset-Allokation-Seite (statt nur in versteckten Statuszeilen).
  function ensureBlocker(){
    var el = byId('aa-calc-blocker');
    var anchor = byId('al-dirty-banner');
    if (!anchor || !anchor.parentNode) return el;
    if (!el) {
      el = document.createElement('div');
      el.id = 'aa-calc-blocker';
      el.className = 'al-banner-conflict';
      el.setAttribute('role', 'alert');
      el.style.display = 'none';
    }
    // Die Seite verschiebt ihre Banner ueber die Strategiebausteine; die Sperre folgt ihnen.
    if (el.nextElementSibling !== anchor) anchor.parentNode.insertBefore(el, anchor);
    return el;
  }

  async function showStrategyBlocker(e){
    var el = ensureBlocker();
    if (!el) return null;
    if (!e) { el.style.display = 'none'; el.innerHTML = ''; return null; }
    var d = detailOf(e) || {};
    var code = String((d && d.reason_code) || '');
    var title = 'Anlagestrategie nicht berechnet', body = errorText(e, 'Unbekannter Fehler.'), action = '';
    if (code.indexOf('CCX_FX_BASIS') === 0) {
      var ccys = (Array.isArray(d.currencies) ? d.currencies : []).map(up).filter(Boolean);
      var rows = await fxRates(true);
      title = 'Wechselkurs nicht belegt';
      body = 'Für jede Fremdwährung braucht die Berechnung einen belegten, aktuellen Kurs. '
        + (ccys.length ? 'Offen: ' + ccys.map(function(c){ return c + ' (' + fxState(c, rows, d.fx_status) + ')'; }).join(', ') + '. ' : '')
        + 'Ersatzkurse werden nie kundenwirksam verwendet.';
      action = '<button class="btn-g" type="button" id="btn-aa-fx-fix" data-ccy="' + esc(ccys.join(',')) + '" onclick="openFxQuickEditor(this.getAttribute(\'data-ccy\').split(\',\'))">Wechselkurs erfassen</button>';
    }
    el.innerHTML = '<div class="al-banner-icon">!</div><div class="al-banner-content"><div class="al-banner-title">' + esc(title)
      + '</div><div class="al-banner-body">' + esc(body) + '</div></div>' + action;
    el.style.display = 'flex';
    el.setAttribute('data-reason-code', code);
    try { if (el.scrollIntoView) el.scrollIntoView({block: 'nearest'}); } catch(_){}
    return code;
  }

  // Waehrungsfeld der Vermoegensposition.
  function mountWealthCurrency(){
    var cat = byId('maw-cat');
    if (!cat || byId('maw-currency')) return;
    var row = cat.closest ? cat.closest('.frow') : null;
    if (!row) return;
    var fg = document.createElement('div');
    fg.className = 'fg';
    fg.innerHTML = '<label class="fl" for="maw-currency">Währung</label><select class="fsel" id="maw-currency" aria-describedby="maw-currency-hint" onchange="syncWealthCurrency(this.value)"></select>'
      + '<div id="maw-currency-hint" style="font-size:12px;color:var(--n5);margin-top:2px"></div>';
    row.appendChild(fg);
  }
  function fillCurrencyOptions(sel, codes, selected){
    var seen = {}, list = [];
    codes.concat([selected]).map(up).forEach(function(c){ if (c && !seen[c]) { seen[c] = 1; list.push(c); } });
    sel.innerHTML = list.map(function(c){ return '<option value="' + esc(c) + '">' + esc(c) + '</option>'; }).join('');
    sel.value = selected;
  }
  function setWealthCurrency(ccy){
    mountWealthCurrency();
    var sel = byId('maw-currency');
    var want = up(ccy) || (typeof newRecordCurrency === 'function' ? newRecordCurrency() : '');
    if (!sel) return want;
    fillCurrencyOptions(sel, [], want);
    syncWealthCurrency(want);
    fxRates(false).then(function(rows){
      if (sel.value !== want) return;
      fillCurrencyOptions(sel, rows.map(function(r){ return r.currency; }), want);
    });
    return want;
  }
  function syncWealthCurrency(ccy){
    var c = up(ccy);
    if (typeof syncCcy === 'function') syncCcy(c, byId('m-aw'));
    var hint = byId('maw-currency-hint');
    var base = typeof mandateCurrency === 'function' ? mandateCurrency() : null;
    if (hint) {
      hint.innerHTML = base && c && c !== base
        ? 'Betrag in ' + esc(c) + ' erfassen. Umgerechnet wird mit dem belegten Kurs <a href="#" onclick="openFxQuickEditor([\'' + esc(c) + '\']);return false;">(Kurs prüfen)</a>.'
        : '';
    }
  }

  // Kundensummen bei Positionen in mehreren Waehrungen: nur die umgerechneten
  // Summen des Servers (GET wealth-summary?mandate_id=...); ohne belegten Kurs
  // gekennzeichnet. Annahme ggue. K1/CK-01: mandate_id -> amount_currency =
  // Mandatswaehrung, fehlender Kurs -> 409 CCX_FX_BASIS_* mit currencies.
  var wealthSummaryState = {key: '', data: null, error: null, loading: false};
  function wealthSummaryUrl(cid){
    var mid = typeof getActiveMandateId === 'function' ? getActiveMandateId() : null;
    return '/clients/' + encodeURIComponent(cid) + '/wealth-summary' + (mid ? '?mandate_id=' + encodeURIComponent(mid) : '');
  }
  function resetWealthSummaryCache(){ wealthSummaryState.key = ''; }
  function wealthCurrencies(items){
    var seen = {};
    (items || []).forEach(function(p){ seen[up(p && p.currency) || '?'] = 1; });
    return Object.keys(seen);
  }
  function wealthMixedTotals(items){
    var ccys = wealthCurrencies(items);
    if (ccys.length < 2) return null;
    var cid = typeof currentClientId !== 'undefined' ? currentClientId : null;
    if (!cid || (typeof isDemoClientId === 'function' && isDemoClientId(cid))) return {blocked: true, currencies: ccys};
    var sig = (items || []).map(function(p){ return [p.id, p.currency, p.current_value_rappen, p.assignment].join(':'); }).join('|');
    var key = wealthSummaryUrl(cid) + '#' + sig, s = wealthSummaryState;
    if (s.key !== key) {
      s.key = key; s.data = null; s.error = null; s.loading = true;
      API.get(wealthSummaryUrl(cid)).then(function(d){ s.data = d; }, function(e){ s.error = detailOf(e) || {message: errorText(e, '?')}; })
        .then(function(){ s.loading = false; if (s.key === key && String(currentClientId) === String(cid) && typeof renderWealthPositions === 'function') renderWealthPositions(currentWealthPositions); });
    }
    // K1/CK-01: fehlender Kurs = 200 ohne Betrag mit amount_block_*; aelter: 409 CCX_FX_BASIS_*.
    if (!s.loading && s.data && s.data.amount_block_reason_code) {
      return {blocked: true, currencies: ccys, srvAdvisoryRappen: s.data.advisory_wealth_rappen, error: {reason_code: s.data.amount_block_reason_code,
        currencies: s.data.amount_block_currencies || [], message: s.data.amount_block_message || ''}};
    }
    if (!s.loading && s.data && s.data.amount_currency && s.data.gross_wealth_rappen != null) {
      var d = s.data;
      return {currency: up(d.amount_currency), advisoryRappen: d.advisory_wealth_rappen, grossRappen: d.gross_wealth_rappen,
        liabilitiesRappen: d.liabilities_rappen, advisory: d.advisory_wealth_rappen / 100, gross: d.gross_wealth_rappen / 100,
        liabilities: d.liabilities_rappen / 100, net: d.net_worth_rappen / 100, other: (d.gross_wealth_rappen - d.advisory_wealth_rappen) / 100};
    }
    return {blocked: true, pending: s.loading, currencies: ccys, error: s.error};
  }
  // N-915-02: Ist-Pfad, Ist-Gewichte und Hypothekenserie rechnet der Browser nicht ueber Waehrungen.
  function wealthFxOpenReason(){
    var items = typeof activeClientWealthPositions === 'function' ? activeClientWealthPositions() : [];
    var ccys = wealthCurrencies(items).filter(function(c){ return c !== '?'; });
    if (ccys.length < 2) return '';
    return 'Ist-Vermögenspfad und Ist-Gewichte: Positionen in mehreren Währungen (' + ccys.join(', ') + '). Umrechnung offen – '
      + 'die Anlagestrategie rechnet mit belegten Kursen (Asset Allokation).';
  }
  function hookIstReason(){
    var original = window.istProjectionBasisUnavailableReason;
    if (typeof original !== 'function' || original.__k2Hooked) return;
    var wrapped = function(){ return wealthFxOpenReason() || original.apply(this, arguments); };
    wrapped.__k2Hooked = true;
    window.istProjectionBasisUnavailableReason = wrapped;
  }
  // N-913-03 (aus K1-Pruefung): typisierte Sperre einer Serversumme (amount_block_*) als
  // Klartext. '' = nicht gesperrt. Nie 0 oder 0 % anstelle einer gesperrten Summe.
  var BLOCK_CAUSE = {CCX_FX_BASIS_MISSING: 'fehlt oder nur Ersatzkurs', CCX_FX_BASIS_STALE: 'abgelaufen',
    CCX_FX_BASIS_MISMATCH: 'Währungsbasis nicht eindeutig'};
  function wealthBlockText(d){
    var code = d && d.amount_block_reason_code;
    if (!code) return '';
    var ccys = (d.amount_block_currencies || []).map(up).filter(Boolean);
    return 'Umrechnung offen – Kurs ' + (ccys.length ? ccys.join(', ') + ' ' : '') + (BLOCK_CAUSE[code] || 'nicht belegt') + '.';
  }
  function wealthMixedNotice(mix){
    if (!mix || !mix.blocked) return '';
    var foreign = (mix.currencies || []).filter(function(c){ return c !== '?' && c !== up(baseCcy()); });
    var err = mix.error || {};
    var why = mix.pending ? 'Umrechnung wird geprüft …'
      : (String(err.reason_code || '').indexOf('CCX_FX_BASIS') === 0
        ? 'Kurs nicht belegt: ' + ((err.currencies || foreign).map(up).join(', ')) + (up(err.fx_status) === 'STALE' || err.reason_code === 'CCX_FX_BASIS_STALE' ? ' (abgelaufen)' : ' (fehlt oder nur Ersatzkurs)') + '.'
        : 'Eine umgerechnete Summe liegt nicht vor.');
    return '<div data-wealth-fx-notice="1" role="status" style="margin-bottom:10px;padding:9px 11px;border:1px solid rgba(194,65,12,0.25);background:#fff7ed;border-radius:var(--r2);font-size:12px;line-height:1.5;color:var(--n7)">'
      + '<b>Positionen in mehreren Währungen (' + esc((mix.currencies || []).filter(function(c){ return c !== '?'; }).join(', ')) + ').</b> '
      + 'Summen und Anteile werden nur in ' + esc(baseCcy()) + ' mit belegten Kursen gezeigt. ' + esc(why) + ' '
      + '<a href="#" onclick="openFxQuickEditor(' + esc(JSON.stringify(foreign)).replace(/"/g, '&quot;') + ');return false;">Wechselkurs erfassen</a></div>';
  }

  // ---------------------------------------------------------------- Finalisieren (E2E-06)
  var FINALIZE_CODES = ['CCX_ENVELOPE_MISSING', 'CCX_BINDING_MISSING', 'CCX_INPUT_STALE', 'CCX_FRESHNESS_UNKNOWN', 'CCX_RESULT_SUPERSEDED', 'CCX_ENVELOPE_HASH_MISMATCH'];
  function mountFinalizeButton(){
    var refresh = byId('btn-po-refresh');
    if (!refresh || byId('btn-po-finalize')) return;
    var btn = document.createElement('button');
    btn.className = 'btn-p';
    btn.id = 'btn-po-finalize';
    btn.type = 'button';
    btn.textContent = 'Empfehlung finalisieren';
    btn.title = 'Prüft die Empfehlung, bestätigt die Bewertungen und hält sie fest. Danach kann die Soll-Allokation publiziert werden.';
    btn.addEventListener('click', function(){ if (typeof openImplementationRecipe === 'function') openImplementationRecipe(); });
    refresh.parentNode.insertBefore(btn, refresh.nextSibling);
    var hint = document.createElement('button');
    hint.className = 'btn';
    hint.id = 'po-finalize-hint';
    hint.type = 'button';
    hint.textContent = 'Zuerst Anlagestrategie berechnen →';
    hint.title = 'Ohne Soll-Allokation gibt es nichts zu finalisieren (Asset Allokation › Anlagestrategie berechnen).';
    hint.addEventListener('click', function(){ if (typeof go === 'function') go('al'); });
    btn.parentNode.insertBefore(hint, btn.nextSibling);
    syncFinalizeButton();
  }
  // N-915-11: "Empfehlung finalisieren" nur mit einer Soll-Allokation (sonst Wegweiser).
  function syncFinalizeButton(){
    var btn = byId('btn-po-finalize'), hint = byId('po-finalize-hint');
    if (!btn) return false;
    var a = typeof strategyState !== 'undefined' && strategyState ? strategyState.allocation : null;
    var ready = !!(a && a.target_allocation && a.target_allocation.id);
    btn.disabled = !ready;
    btn.setAttribute('aria-disabled', ready ? 'false' : 'true');
    if (hint) hint.style.display = ready ? 'none' : '';
    return ready;
  }
  function goFinalize(){
    if (typeof go === 'function') go('po');
    setTimeout(function(){ var b = byId('btn-po-finalize'); if (b) { try { b.focus(); } catch(_){} } }, 400);
  }
  // Aus renderAllocationPublication: Wegweiser neben "Publizieren", wenn Finalisieren fehlt.
  function syncFinalizeShortcut(state){
    var chip = byId('aa-publication-status');
    if (!chip || !chip.parentNode) return false;
    var link = byId('btn-aa-goto-finalize');
    var codes = (state && state.publication_status !== 'PUBLISHED' && Array.isArray(state.blocker_codes)) ? state.blocker_codes : [];
    var need = codes.some(function(c){ return FINALIZE_CODES.indexOf(String(c)) >= 0; });
    if (!need) { if (link) link.style.display = 'none'; return false; }
    if (!link) {
      link = document.createElement('button');
      link.className = 'btn';
      link.id = 'btn-aa-goto-finalize';
      link.type = 'button';
      link.textContent = 'Zum Finalisieren →';
      link.title = 'Portfolio › Empfehlung finalisieren';
      link.addEventListener('click', goFinalize);
      chip.parentNode.insertBefore(link, chip.nextSibling);
    }
    link.style.display = '';
    return true;
  }

  // ---------------------------------------------------------------- Depotbank (E2E-10)
  function populateRecipeDepotBanks(){
    var sel = byId('recipe-depot-bank');
    if (!sel) return [];
    var keep = sel.value || '';
    var seen = {}, banks = [];
    function add(v){ v = String(v || '').trim(); if (v && !seen[v.toLowerCase()]) { seen[v.toLowerCase()] = 1; banks.push(v); } }
    add(typeof currentMandateData !== 'undefined' && currentMandateData && currentMandateData.depot_bank);
    (typeof currentWealthPositions !== 'undefined' ? currentWealthPositions : []).forEach(function(p){ if (p && p.position_type === 'Depot') add(p.depot_bank); });
    sel.innerHTML = '<option value="">Ohne Angabe (neutral)</option>' + banks.map(function(b){ return '<option value="' + esc(b) + '">' + esc(b) + '</option>'; }).join('');
    sel.value = banks.indexOf(keep) >= 0 ? keep : '';
    return banks;
  }

  // ---------------------------------------------------------------- Musterprodukte (E2E-07)
  // Musterprodukt = ohne ISIN (wie im Portfolio-PDF); echte Produkte kommen mit ISIN ins Fonds-Universum.
  function isSampleProduct(p){ return !!p && !String(p.isin || '').trim(); }
  function sampleProductText(positions){
    var list = Array.isArray(positions) ? positions : [];
    var n = list.filter(isSampleProduct).length;
    if (!n) return '';
    return n + ' von ' + list.length + ' Positionen sind Musterprodukte ohne belegte Stammdaten (keine ISIN). '
      + 'Musterprodukt – nicht zur Umsetzung. Belegte Produkte erfassen Sie im Fonds-Universum (Administration › Daten & Marktdaten › Fonds-Universum).';
  }
  function renderSampleProductWarning(positions){
    var wrap = byId('po-portfolio-sections');
    if (!wrap || !wrap.parentNode) return '';
    var el = byId('po-sample-warning');
    if (!el) {
      el = document.createElement('div');
      el.id = 'po-sample-warning';
      el.setAttribute('role', 'alert');
      el.style.cssText = 'display:none;background:#fff7ed;border:1px solid rgba(194,65,12,0.3);border-radius:var(--r);padding:10px 12px;margin-bottom:10px;font-size:12px;line-height:1.5;color:#7c2d12';
      wrap.parentNode.insertBefore(el, wrap);
    }
    syncFinalizeButton();
    var txt = sampleProductText(positions);
    el.innerHTML = txt ? '<b>Musterkatalog – nicht zur Umsetzung.</b> ' + esc(txt) : '';
    el.style.display = txt ? '' : 'none';
    var ums = byId('recipe-sample-warning');
    if (ums) { ums.textContent = txt; ums.style.display = txt ? '' : 'none'; }
    return txt;
  }

  // ---------------------------------------------------------------- Prognose-Verzehr (E2E-12)
  // Erstes Jahr unter null (N-915-05: strikt < 0; ein Startwert 0 ist kein Verzehr).
  function depletionYear(labels, series){
    for (var i = 0; i < (series || []).length; i++) { if (Number(series[i]) < 0) return labels && labels[i] != null ? String(labels[i]).slice(0, 4) : null; }
    return null;
  }
  // "aufgebraucht" nur, wenn zuvor Vermoegen da war; sonst (Start <= 0) Finanzierungsluecke.
  function depletionPhrase(series, year){
    return Number((series || [])[0]) > 0 ? 'Vermögen aufgebraucht ab ' + year : 'Finanzierungslücke ab ' + year;
  }
  // Satz unter dem Faecher, wenn die Prognose ins Negative laeuft (Berechnung unveraendert).
  // Massgeblich ist der schwaechste negative Verlauf: P90 < 0 vor P50 < 0 vor P10 < 0.
  function fanDepletionSentence(labels, p10, p50, p90){
    var last = Math.min((p10 || []).length, (p50 || []).length, (p90 || []).length) - 1;
    if (last < 0 || !(Number(p10[last]) < 0)) return '';
    var tail = ' Werte unter null zeigen die Finanzierungslücke.';
    var mid = depletionYear(labels, p50), low = depletionYear(labels, p10), high = depletionYear(labels, p90);
    if (Number(p90[last]) < 0 && mid) {
      return depletionPhrase(p50, mid) + ' (mittlerer Verlauf); auch im günstigen Verlauf (9 von 10) ab ' + high + '.' + tail;
    }
    if (Number(p50[last]) < 0 && mid) {
      return depletionPhrase(p50, mid) + ' (mittlerer Verlauf, in mehr als der Hälfte der Verläufe).' + tail;
    }
    return low ? 'Im ungünstigen Verlauf (1 von 10): ' + depletionPhrase(p10, low) + '.' + tail : '';
  }
  // Kennzahl "Prognose <Jahr>": negativer Endwert wird als Verzehr beschriftet.
  function markProjectionDepletion(valueId, projectedRappen, result){
    var el = byId(valueId);
    if (!el || !el.previousElementSibling || !(Number(projectedRappen) < 0)) return null;
    var mc = typeof monteCarloPayload === 'function' ? monteCarloPayload(result) : null;
    var sim = typeof simulationPayload === 'function' ? simulationPayload(result) : null;
    var series = (mc && mc.target_p50_series_rappen) || (sim && sim.target_mix_series_rappen) || [];
    var labels = (mc && mc.year_labels) || (sim && sim.year_labels) || [];
    var year = depletionYear(labels, series);
    el.previousElementSibling.textContent = year ? depletionPhrase(series, year) : 'Finanzierungslücke';
    el.title = 'Finanzierungslücke am Ende der Prognose (Wert unter null).';
    return year;
  }

  // ---------------------------------------------------------------- Pensionierungsjahr (E2E-14)
  function mountRetirementCard(){
    var pad = document.querySelector('#page-cf .pad');
    if (!pad || byId('cf-retirement')) return;
    var card = document.createElement('div');
    card.id = 'cf-retirement';
    card.setAttribute('role', 'group');
    card.setAttribute('aria-label', 'Pensionierung');
    card.style.cssText = 'display:none;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:10px;padding:8px 12px;border:1px solid var(--b1);border-radius:var(--r2);background:var(--bg);font-size:12px';
    card.innerHTML = '<span style="font-weight:600">Pensionierung:</span> <span id="cf-retirement-text"></span>'
      + '<label for="cf-retirement-year" style="margin-left:auto;font-size:12px;color:var(--n5)">Pensionierungsjahr</label>'
      + '<input class="fi" id="cf-retirement-year" type="number" min="2000" max="2100" placeholder="z.B. 2031" style="width:90px;font-size:12px">'
      + '<button class="btn btn-sm" type="button" id="btn-cf-retirement-save" onclick="saveRetirementYear()">Speichern</button>';
    pad.insertBefore(card, pad.firstChild);
  }
  function renderRetirementCard(){
    mountRetirementCard();
    var card = byId('cf-retirement');
    if (!card) return;
    var m = typeof currentMandateData !== 'undefined' ? currentMandateData : null;
    if (!m || !m.id) { card.style.display = 'none'; return; }
    card.style.display = 'flex';
    var y = m.retirement_year ? String(m.retirement_year) : '';
    var by = m.client_birth_year ? Number(m.client_birth_year) : null;
    var txt = byId('cf-retirement-text');
    if (txt) {
      txt.textContent = y ? ('Jahr ' + y + (by ? ' (Alter ' + (Number(y) - by) + ')' : ''))
        : 'nicht erfasst – bestimmt Beginn der Rentenphase und Vorsorgebezug in Prognose und Strategie.';
      txt.style.color = y ? 'var(--n7)' : 'var(--neg)';
    }
    var inp = byId('cf-retirement-year');
    if (inp && document.activeElement !== inp) inp.value = y;
  }
  async function saveRetirementYear(){
    var m = typeof currentMandateData !== 'undefined' ? currentMandateData : null;
    var inp = byId('cf-retirement-year');
    if (!m || !m.id || !inp) return false;
    var raw = String(inp.value || '').trim();
    var year = raw ? parseInt(raw, 10) : null;
    if (raw && !(year >= 2000 && year <= 2100)) { notice('error', 'Bitte ein Pensionierungsjahr zwischen 2000 und 2100 eingeben.'); return false; }
    try {
      var saved = await API.put('/mandates/' + encodeURIComponent(m.id), {retirement_year: year});
      m.retirement_year = saved && saved.retirement_year !== undefined ? saved.retirement_year : year;
      renderRetirementCard();
      if (typeof markStrategyDirty === 'function') markStrategyDirty('Pensionierungsjahr geändert: Strategie neu berechnen.', false);
      notice('success', 'Pensionierungsjahr gespeichert.');
      return true;
    } catch(e) {
      notice('error', errorText(e, 'Pensionierungsjahr konnte nicht gespeichert werden.'));
      return false;
    }
  }
  function hookGo(){
    var original = window.go;
    if (typeof original !== 'function' || original.__k2Hooked) return;
    var wrapped = async function(p){
      var result = await original.apply(this, arguments);
      if (p === 'cf' || p === 'ub') renderRetirementCard();
      if (p === 'po') { mountFinalizeButton(); syncFinalizeButton(); }
      return result;
    };
    wrapped.__k2Hooked = true;
    window.go = wrapped;
  }

  function mountAll(){
    mountAdminFirm();
    mountWealthCurrency();
    mountFinalizeButton();
    mountRetirementCard();
    ensureBlocker();
    hookGo();
    hookIstReason();
    hookInitApp();
  }
  if (typeof document !== 'undefined' && document.addEventListener) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mountAll);
    else mountAll();
  }

  window.loadAdminFirm = loadAdminFirm;
  window.saveAdminFirm = saveAdminFirm;
  window.openAdminFirmSection = openAdminFirmSection;
  window.askSinglePersonFirmAfterBootstrap = askSinglePersonFirmAfterBootstrap;
  window.askSinglePersonFirmIfOpen = askSinglePersonFirmIfOpen;
  window.syncFinalizeButton = syncFinalizeButton;
  window.publishFourEyesFlow = publishFourEyesFlow;
  window.openFxQuickEditor = openFxQuickEditor;
  window.saveFxQuickEditor = saveFxQuickEditor;
  window.showStrategyBlocker = showStrategyBlocker;
  window.setWealthCurrency = setWealthCurrency;
  window.syncWealthCurrency = syncWealthCurrency;
  window.wealthSummaryUrl = wealthSummaryUrl;
  window.wealthMixedTotals = wealthMixedTotals;
  window.resetWealthSummaryCache = resetWealthSummaryCache;
  window.wealthMixedNotice = wealthMixedNotice;
  window.wealthBlockText = wealthBlockText;
  window.wealthFxOpenReason = wealthFxOpenReason;
  window.syncFinalizeShortcut = syncFinalizeShortcut;
  window.goFinalize = goFinalize;
  window.populateRecipeDepotBanks = populateRecipeDepotBanks;
  window.isSampleProduct = isSampleProduct;
  window.renderSampleProductWarning = renderSampleProductWarning;
  window.fanDepletionSentence = fanDepletionSentence;
  window.markProjectionDepletion = markProjectionDepletion;
  window.renderRetirementCard = renderRetirementCard;
  window.saveRetirementYear = saveRetirementYear;
})();
