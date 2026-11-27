/*
 * H-180 Paket ROL (ROL-04/-05/-06): Rollenanzeige der Classic-Oberflaeche.
 *
 * Nachgeladen aus desktop-api.js (wie build-info.js), nicht im Monolithen
 * (Groessenbudget von ares.html). Der Server sperrt unabhaengig davon; hier wird
 * nur nichts angeboten, was die Rolle nicht ausfuehren darf (Owner-UX: nur
 * Erfuellbares anbieten).
 *
 *   - readonly ("Lesend"): firmenweite Lesesicht -- alle Schreibknoepfe der
 *     Beratungskette (Speichern, Anlegen, Loeschen, Berechnen, Finalisieren,
 *     Publizieren, Signieren, Editoren) sind ausgeblendet.
 *   - portfolio_management: Referenzdaten-Rolle ohne Kundensicht -- keine
 *     Kundenmaske (Kundenliste, Beratungsschritte, Seiten), dazu ein Hinweis.
 *   - admin / compliance_reviewer: Knopf "Freigaben" mit der Freigabe-Inbox der
 *     Vier-Augen-Publikation (nur vorgelegte Akten, datenminimiert; ROL-b: mit
 *     Mandatsnummer und Kundenname).
 *   - ROL-b: compliance_reviewer sieht in ihrer Freigabe-Ansicht die offenen
 *     Produkt-Eignungsregeln der Firma und gibt sie als zweite Person frei
 *     (Erfassen bleibt beim Admin; der Server sperrt alles andere).
 */
(function () {
  'use strict';
  if (typeof document === 'undefined') return;

  var WRITE_SELECTOR = [
    'save', 'delete', 'create', 'submit', 'sign', 'publish', 'finaliz', 'openNew', 'calculateInvestmentStrategy',
    'refreshPortfolioFromStoredState', 'openPortfolioUmsetzenModal', 'markPortfolioHandoffExecuted',
    'openWealthPositionEditor', 'openWealthInflowEditor', 'openCashflowEditor', 'openGoalsEditor',
    'openProfilingEditor', 'openMandateEditor', 'openCrmEditor', 'openStammdatenModal', "om('m-"
  ].map(function (name) {
    return 'body.ares-role-readonly [onclick*="' + name.replace(/"/g, '\\"') + '"]';
  }).concat(['body.ares-role-readonly .sb-add']).join(',\n');
  var CSS = WRITE_SELECTOR + '{display:none !important;}\n'
    + 'body.ares-role-pm .sidebar, body.ares-role-pm .tnav, body.ares-role-pm main.content .page'
    + '{display:none !important;}\n'
    + '#ares-role-pm-note{display:none;padding:24px;font-size:12px;color:var(--n5);}\n'
    + 'body.ares-role-pm #ares-role-pm-note{display:block;}\n';

  function role() {
    try {
      /* global currentUser */
      return (typeof currentUser !== 'undefined' && currentUser && currentUser.role) || '';
    } catch (_err) {
      return '';
    }
  }

  function ensureStyle() {
    if (document.getElementById('ares-role-ui-style')) return;
    var style = document.createElement('style');
    style.id = 'ares-role-ui-style';
    style.textContent = CSS;
    (document.head || document.documentElement).appendChild(style);
  }

  function ensurePmNote() {
    var main = document.querySelector('main.content');
    if (!main || document.getElementById('ares-role-pm-note')) return;
    var note = document.createElement('div');
    note.id = 'ares-role-pm-note';
    note.textContent = 'Portfolio Management: Diese Rolle verwaltet Referenzdaten '
      + '(Kapitalmarktannahmen) und hat keine Kundensicht.';
    main.insertBefore(note, main.firstChild);
  }

  function escapeText(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  async function apiCall(path, options) {
    /* global API */
    if (typeof API === 'undefined' || !API || typeof API.fetch !== 'function') throw new Error('API fehlt');
    return API.fetch(path, options || {});
  }

  var BUCKET_LABELS = { equities: 'Aktien', bonds: 'Obligationen', real_estate: 'Immobilien',
    alternatives: 'Alternative', liquidity: 'Liquidität' };

  function itemHtml(item) {
    var targets = Object.keys(BUCKET_LABELS).map(function (key) {
      var bps = (item.targets_bps || {})[key];
      return BUCKET_LABELS[key] + ' ' + (bps == null ? '–' : (bps / 100).toFixed(2) + ' %');
    }).join(' · ');
    var action = item.can_publish
      ? '<button class="btn btn-sm" data-inbox-approve="' + escapeText(item.mandate_id) + '">Freigeben</button>'
      : '<span style="font-size:10px;color:var(--n4)">Noch nicht freigebbar (Prüfung offen)</span>';
    return '<div class="card mb" style="padding:8px">'
      + '<div style="font-size:11px;font-weight:600">Mandat ' + escapeText(item.mandate_number || item.mandate_id)
      + (item.client_name ? ' · ' + escapeText(item.client_name) : '')
      + (item.mandate_type ? ' · ' + escapeText(item.mandate_type) : '') + '</div>'
      + '<div style="font-size:10px;color:var(--n4)">Vorbereitet von ' + escapeText(item.prepared_by_name || '–')
      + (item.sealed_at ? ' am ' + escapeText(String(item.sealed_at).slice(0, 10)) : '') + '</div>'
      + '<div style="font-size:10px;margin:4px 0">' + escapeText(targets) + '</div>' + action + '</div>';
  }

  async function openInbox() {
    var panel = document.getElementById('ares-publication-inbox');
    if (!panel) {
      panel = document.createElement('div');
      panel.id = 'ares-publication-inbox';
      panel.setAttribute('role', 'dialog');
      panel.setAttribute('aria-label', 'Freigaben');
      panel.style.cssText = 'position:fixed;top:60px;right:20px;width:380px;max-height:70vh;overflow:auto;'
        + 'background:var(--bg,#fff);border:1px solid var(--n3,#ccc);border-radius:6px;padding:12px;z-index:9999;'
        + 'box-shadow:0 6px 24px rgba(0,0,0,.18)';
      document.body.appendChild(panel);
      panel.addEventListener('click', onPanelClick);
    }
    panel.style.display = 'block';
    panel.innerHTML = '<div style="font-size:12px;font-weight:600;margin-bottom:6px">Freigaben (Vier-Augen-Publikation)'
      + '<button class="btn btn-sm" data-inbox-close="1" style="float:right">Schliessen</button></div>'
      + '<div id="ares-publication-inbox-body" style="font-size:10px">Wird geladen…</div>';
    var body = document.getElementById('ares-publication-inbox-body');
    try {
      var items = await apiCall('/publication-inbox');
      panel._items = items || [];
      body.innerHTML = panel._items.length
        ? panel._items.map(itemHtml).join('')
        : 'Keine zur Freigabe vorgelegten Akten.';
    } catch (err) {
      body.textContent = 'Freigaben konnten nicht geladen werden: ' + (err && err.message ? err.message : err);
    }
  }

  async function onPanelClick(event) {
    var target = event.target;
    if (!target || !target.getAttribute) return;
    if (target.getAttribute('data-inbox-close')) {
      document.getElementById('ares-publication-inbox').style.display = 'none';
      return;
    }
    var mandateId = target.getAttribute('data-inbox-approve');
    if (!mandateId) return;
    var panel = document.getElementById('ares-publication-inbox');
    var item = (panel._items || []).find(function (i) { return i.mandate_id === mandateId; });
    if (!item) return;
    target.disabled = true;
    try {
      await apiCall('/publication-inbox/' + encodeURIComponent(mandateId) + '/approve', {
        method: 'POST',
        body: JSON.stringify({ target_allocation_id: item.target_allocation_id, validation_hash: item.validation_hash })
      });
      await openInbox();
    } catch (err) {
      target.disabled = false;
      target.insertAdjacentText('afterend', ' Freigabe abgelehnt: ' + (err && err.message ? err.message : err));
    }
  }

  function ensureInboxButton(show, current) {
    var btn = document.getElementById('btn-publication-inbox');
    if (!btn && show) {
      // Admin: in der Administration (Compliance) -- die Kopfzeile bleibt frei
      // (Schritte bei 1024 px klickbar, N-918-03). Pruefperson: Kopfzeile.
      var anchor = (current === 'admin' && document.getElementById('asec-audit')) || document.getElementById('btn-logout');
      if (!anchor || !anchor.parentNode) return;
      btn = document.createElement('button');
      btn.id = 'btn-publication-inbox';
      btn.className = anchor.className || 'btn';
      btn.type = 'button';
      btn.textContent = 'Freigaben';
      btn.title = 'Zur Freigabe vorgelegte Akten (Vier-Augen-Publikation)';
      btn.addEventListener('click', openInbox);
      anchor.parentNode.insertBefore(btn, anchor);
    }
    if (btn) btn.style.display = show ? '' : 'none';
  }

  // ROL-b: offene Produkt-Eignungsregeln in der Freigabe-Ansicht der Pruefperson.
  function ruleText(rule) {
    var parts = ['Risikoprofil ' + escapeText(rule.profile_from) + '–' + escapeText(rule.profile_to)];
    if (rule.prohibited) parts.push('gesperrt');
    if (rule.requires_suitability) parts.push('Eignungsprüfung nötig');
    if (rule.requires_appropriateness) parts.push('Angemessenheitsprüfung nötig');
    if (rule.requires_override) parts.push('nur mit Ausnahmebewilligung');
    if (rule.max_position_bps != null) parts.push('max. ' + (rule.max_position_bps / 100).toFixed(2) + ' % je Position');
    if ((rule.service_modes || []).length) parts.push('Dienstleistung: ' + rule.service_modes.map(escapeText).join(', '));
    if ((rule.client_classifications || []).length) {
      parts.push('Kundensegment: ' + rule.client_classifications.map(escapeText).join(', '));
    }
    if (rule.jurisdiction) parts.push('Rechtsraum ' + escapeText(rule.jurisdiction));
    if ((rule.requires_knowledge_categories || []).length) {
      parts.push('Kenntnisse: ' + rule.requires_knowledge_categories.map(escapeText).join(', '));
    }
    if (rule.minimum_experience_level) parts.push('Mindesterfahrung ' + escapeText(rule.minimum_experience_level));
    return parts.join(' · ') + ' · Prüfwert ' + escapeText(String(rule.rule_hash || '').slice(0, 12));
  }

  function draftHtml(draft) {
    var title = escapeText(draft.product_name || draft.product_id)
      + (draft.isin ? ' · ' + escapeText(draft.isin) : '')
      + (draft.asset_class ? ' · ' + escapeText(draft.asset_class) : '');
    var action = draft.authored_by_current_user
      ? '<span style="font-size:10px;color:var(--n4)">Selbst erfasst – Freigabe durch eine andere Person</span>'
      : '<button class="btn btn-sm" data-elig-approve="' + escapeText(draft.product_id) + '">Freigeben</button>';
    return '<div class="card mb" style="padding:8px">'
      + '<div style="font-size:11px;font-weight:600">' + title + '</div>'
      + '<div style="font-size:10px;color:var(--n4)">Erfasst von ' + escapeText((draft.authored_by_names || []).join(', ') || '–')
      + '</div>'
      + (draft.rules || []).map(function (r) { return '<div style="font-size:10px;margin:4px 0">' + ruleText(r) + '</div>'; }).join('')
      + action + '</div>';
  }

  // N-939-02: genau die zuletzt dargestellte Fassung je Produkt (rule_id, rule_hash);
  // sie wird unveraendert mitgesendet -- kein zweites Laden vor der Freigabe.
  var shownRules = {};

  async function loadEligibilityDrafts(notice) {
    var box = document.getElementById('elig-reviewer-body');
    if (!box) return;
    box.innerHTML = '<div style="font-size:12px;font-weight:600">Produkt-Eignungsregeln (Freigabe als zweite Person)</div>'
      + '<div id="elig-reviewer-list" style="font-size:10px">Wird geladen…</div>';
    var list = document.getElementById('elig-reviewer-list');
    try {
      var res = await apiCall('/products/eligibility-drafts');
      var drafts = (res && res.drafts) || [];
      var shown = {};
      drafts.forEach(function (d) {
        shown[d.product_id] = (d.rules || []).map(function (r) { return { rule_id: r.rule_id, rule_hash: r.rule_hash }; });
      });
      var html = drafts.length ? drafts.map(draftHtml).join('') : 'Keine offenen Eignungsregeln.';
      list.innerHTML = (notice ? '<div role="alert" style="color:#9E4747">' + escapeText(notice) + '</div>' : '') + html;
      shownRules = shown;
    } catch (err) {
      shownRules = {};
      list.textContent = 'Eignungsregeln konnten nicht geladen werden: ' + (err && err.message ? err.message : err);
    }
  }

  async function onEligibilityClick(event) {
    var target = event.target;
    var productId = target && target.getAttribute && target.getAttribute('data-elig-approve');
    if (!productId) return;
    target.disabled = true;
    try {
      await apiCall('/products/' + encodeURIComponent(productId) + '/eligibility-rule/approve', {
        method: 'POST', body: JSON.stringify({ seen_rules: shownRules[productId] || [] })
      });
      await loadEligibilityDrafts();
    } catch (err) {
      var message = 'Freigabe abgelehnt: ' + (err && err.message ? err.message : err);
      if (err && (err.status === 409 || err.status === 404)) return loadEligibilityDrafts(message);
      target.disabled = false;
      target.insertAdjacentText('afterend', ' ' + message);
    }
  }

  function ensureEligibilityReviewerBox(current) {
    var view = document.getElementById('krp-reviewer-view');
    if (current !== 'compliance_reviewer' || !view || document.getElementById('elig-reviewer-body')) return;
    var box = document.createElement('div');
    box.id = 'elig-reviewer-body';
    box.style.cssText = 'display:grid;gap:8px;margin-top:16px';
    box.addEventListener('click', onEligibilityClick);
    view.appendChild(box);
    loadEligibilityDrafts();
  }

  var lastRole = null;
  function apply() {
    var current = role();
    if (current === lastRole) return;
    lastRole = current;
    ensureStyle();
    ensurePmNote();
    document.body.classList.toggle('ares-role-readonly', current === 'readonly');
    document.body.classList.toggle('ares-role-pm', current === 'portfolio_management');
    ensureInboxButton(current === 'admin' || current === 'compliance_reviewer', current);
  }

  window.AresRoleUi = {
    apply: apply, openInbox: openInbox, writeSelector: WRITE_SELECTOR, loadEligibilityDrafts: loadEligibilityDrafts
  };
  function tick() {
    apply();
    ensureEligibilityReviewerBox(role());
  }
  function start() {
    tick();
    setInterval(tick, 1000);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
