/* Ares -- Mandatsgebundene Anzeigen der Berateroberflaeche (KN-U, Dok. 117).
 * Teil des Monolith-Bundles (eigenes Budget). Haengt sich selbst ein und nutzt
 * die globalen Helfer des Monolithen erst beim Aufruf. Keine Fachlogik: Zahlen,
 * Freigaben und Umrechnungen bleiben Serverwahrheit.
 *
 * E2E2-01  Mandatswechsel bzw. keine Allokation: alle mandatsbezogenen Kacheln,
 *          HUDs, offenen Dialoge und Zwischenstaende werden zurueckgesetzt.
 * E2E2-02  Banner "Datenuebermittlung" unter der Kopfzeile (Kopfzeile bedienbar).
 * E2E2-05  Veraltete Soll-Allokation: dieselbe konkrete Ursache auf Asset
 *          Allokation, Portfolio und Review, ohne Neuladen. Quellen: 409-Text der
 *          Payload-Abrufe (heute) und kuenftige Statusfelder der Publikation
 *          (stale / stale_reason / stale_reason_code, Annahme ggue. KN-B).
 * E2E2-07, N-917-03, N-917-08  "Umrechnung offen" mit Ursache statt "keine
 *          Position" bzw. "--"; das Beratungsvermoegen erscheint, wenn die
 *          Kurse seiner Waehrungen belegt sind (heute: nur Basiswaehrung).
 * E2E-12   Review-Kachel ohne negative Vermoegenswerte (Verzehr/Finanzierungsluecke).
 * E2E2-14  Fachbegriffe statt Technikbegriffe in der Anzeige.
 * E2E2-15  Review ohne Strategie behauptet kein "alles im Band". */
(function(){
  'use strict';
  function byId(id){ return document.getElementById(id); }
  function up(v){ return String(v == null ? '' : v).toUpperCase().trim(); }
  function esc(v){ return typeof escapeHtml === 'function' ? escapeHtml(String(v == null ? '' : v)) : String(v == null ? '' : v); }
  function txt(id, v){ var el = byId(id); if (el) el.textContent = v; return el; }
  function g(name){ return typeof window[name] === 'function' ? window[name] : null; }
  function activeMid(){ var f = g('getActiveMandateId'); return f ? String(f() || '') : ''; }
  function baseCcy(){ var f = g('mandateCurrency'); return f ? up(f()) : ''; }
  function state(){ return typeof strategyState !== 'undefined' && strategyState ? strategyState : null; }
  function alloc(){ var s = state(); return s ? s.allocation || null : null; }
  function wrap(name, make){
    var o = window[name];
    if (typeof o !== 'function' || o.__knuHooked) return false;
    var w = make(o);
    w.__knuHooked = true;
    window[name] = w;
    return true;
  }
  function safe(f){ try { return f(); } catch(e){ try { console.warn('mandate-view', e); } catch(_){} return null; } }

  // ------------------------------------------------------------ Fachbegriffe (E2E2-14)
  function aresTerm(name){
    return String(name == null ? '' : name)
      .replace(/\s*\(CHF gehedgt\)|\s*_?Hedged\s*CHF\b/g, function(m){ var p = m.indexOf('(') >= 0; return (p ? ' (' : ' ') + 'währungsgesichert in CHF' + (p ? ')' : ''); })
      .replace(/\bHedged\b/g, 'währungsgesichert')
      .replace(/\bgehedgt\b/g, 'währungsgesichert')
      .replace(/\bIG\b/g, 'Investment Grade')
      .replace(/Gluecksspiel/g, 'Glücksspiel').replace(/laender/g, 'länder').replace(/Laender/g, 'Länder');
  }

  // ------------------------------------------------------------ Umrechnung offen (E2E2-07, N-917-03/-08)
  var FX_CAUSE = {CCX_FX_BASIS_MISSING: 'fehlt oder nur Ersatzkurs', CCX_FX_BASIS_STALE: 'abgelaufen', CCX_FX_BASIS_MISMATCH: 'Währungsbasis nicht eindeutig'};
  function positions(){ var f = g('activeClientWealthPositions'); return f ? (f() || []) : []; }
  function mixOf(items){ var f = g('wealthMixedTotals'); return f ? f(items) : null; }
  // Klartext "Umrechnung offen – Kurs USD fehlt oder nur Ersatzkurs" (nie 0, nie "keine Position").
  function fxOpenText(mix){
    var m = mix || mixOf(positions()) || {};
    var e = m.error || {};
    var base = baseCcy();
    var ccys = (e.currencies && e.currencies.length ? e.currencies : (m.currencies || []).filter(function(c){ return c !== '?' && up(c) !== base; })).map(up);
    if (m.pending) return 'Umrechnung wird geprüft …';
    return 'Umrechnung offen – Kurs ' + (ccys.length ? ccys.join(', ') + ' ' : '') + (FX_CAUSE[e.reason_code] || 'fehlt oder nur Ersatzkurs');
  }
  // Summe einer Positionsgruppe ohne Umrechnung: nur wenn alle Positionen in der
  // Basiswaehrung des Mandats liegen (gleiche Regel wie das PDF: belegt sind die
  // Kurse der eigenen Waehrungen; Basiswaehrung braucht keinen Kurs). Sonst null.
  function sameCurrencySum(list){
    var base = baseCcy();
    if (!base) return null;
    var sum = 0;
    for (var i = 0; i < (list || []).length; i++) {
      var p = list[i];
      if (!p) continue;
      if (up(p.currency) !== base) return null;
      var v = Math.max(0, Number(p.current_value_rappen || 0));
      sum += String(p.assignment || '') === 'Verbindlichkeit' ? -v : v;
    }
    return {rappen: sum, currency: base};
  }
  function advisoryOf(items){ return (items || []).filter(function(p){ return p && p.assignment === 'Beratungsvermögen'; }); }
  // N-917-03: Beratungsvermoegen trotz offener Kundensumme. Vorrang hat ein
  // kuenftiges Serverfeld (advisory_wealth_rappen neben amount_block_*, Annahme).
  function advisoryWhenBlocked(items, mix){
    if (mix && mix.srvAdvisoryRappen != null) return {rappen: Number(mix.srvAdvisoryRappen), currency: up(mix.srvAdvisoryCurrency) || baseCcy()};
    return sameCurrencySum(advisoryOf(items));
  }
  function formatAmount(rappen, ccy){ var f = g('formatRappen'); return f ? f(rappen, ccy) : String(rappen); }
  function aresBlockedTotal(mix, list){
    if (mix && mix.pending) return 'Umrechnung wird geprüft …';
    if (!(list || []).length) return 'nicht erfasst'; // E2E2-15: leere Gruppe, kein Nullbetrag
    var isAdvisory = (list || []).length > 0 && advisoryOf(list).length === list.length;
    var known = isAdvisory ? advisoryWhenBlocked(list, mix) : sameCurrencySum(list);
    return known ? formatAmount(known.rappen, known.currency) : 'Umrechnung offen';
  }
  function aresSnapshotAmount(snapshot, kind){
    var s = snapshot || {};
    if (s.fxOpen) {
      if (kind === 'advisory') {
        var items = positions();
        var known = advisoryWhenBlocked(items, mixOf(items));
        if (known) return formatAmount(known.rappen, known.currency);
      }
      return fxOpenText();
    }
    if (kind === 'advisory') return s.advisoryRappen ? formatAmount(s.advisoryRappen, s.wealthCurrency) : 'Noch kein Beratungsvermögen erfasst';
    return s.totalNetRappen ? formatAmount(s.totalNetRappen, s.wealthCurrency) : 'Noch keine Vermögensbasis';
  }
  // N-917-08: Gruppensummen ueber mehrere Waehrungen nie als "--".
  function aresCcySum(fmt, sum, list, sign){
    var f = g('positionsCurrency');
    var c = f ? f(list) : null;
    return c ? (sign || '') + fmt(sum, c) : 'Umrechnung offen';
  }
  function hookMixedTotals(){
    wrap('wealthMixedTotals', function(orig){
      return function(items){
        var r = orig.apply(this, arguments);
        if (r && r.blocked && !r.pending) {
          var adv = advisoryWhenBlocked(items, r);
          if (adv) { r.advisoryRappen = adv.rappen; r.advisoryCurrency = adv.currency; r.advisoryKnown = true; }
        }
        return r;
      };
    });
  }
  // KPI "Beratungsvermoegen" folgt derselben Regel wie die Vermoegensmaske.
  function syncAdvisoryKpi(){
    var k = byId('kpi-beratungsvermoegen');
    if (!k) return;
    var items = positions();
    var mix = items.length ? mixOf(items) : null;
    if (!mix || !mix.blocked || mix.pending) return;
    var known = advisoryWhenBlocked(items, mix);
    k.textContent = known ? formatAmount(known.rappen, known.currency) : 'Umrechnung offen';
    var card = k.closest ? k.closest('.kpi') : null;
    var sub = card ? card.querySelector('.ks') : null;
    if (sub) sub.textContent = known ? 'Beratungsvermögen belegt; Gesamtvermögen offen – ' + fxOpenText(mix).replace(/^Umrechnung offen – /, '') : fxOpenText(mix);
  }

  // ------------------------------------------------------------ Veraltete Strategie (E2E2-05)
  var stale = {mid: '', cause: ''};
  var ASCII = [[/geaendert/g, 'geändert'], [/Vermoegen/g, 'Vermögen'], [/Waehrung/g, 'Währung'], [/fuer/g, 'für'], [/ueber/g, 'über']];
  function deAscii(t){ ASCII.forEach(function(p){ t = t.replace(p[0], p[1]); }); return t; }
  // Konkrete Ursache aus dem 409-Text des Servers (core/fx_freshness.stale_allocation_message).
  function staleCauseFromText(text){
    var t = String(text || '');
    if (!/veraltet/i.test(t)) return '';
    var fx = t.match(/Wechselkurs(?:e)?\s+([A-Z]{3}(?:\s*,\s*[A-Z]{3})*)\s+(?:seit der Berechnung\s+)?ge(?:ae|ä)ndert/);
    if (fx) return 'Wechselkurs ' + fx[1].replace(/\s*,\s*/g, ', ') + ' geändert'; // Wortlaut wie KN-B freshness_cause
    if (/Berechnungsgrundlage aktualisiert/.test(t)) return 'Berechnungsgrundlage aktualisiert';
    if (/Vermoegen, Cashflows oder Ziele|Vermögen, Cashflows oder Ziele/.test(t)) return 'Vermögen, Cashflows oder Ziele seit der Berechnung geändert';
    var m = t.match(/veraltet:\s*([^.]+)/i);
    return m ? deAscii(m[1].trim()) : 'Eingaben seit der Berechnung geändert';
  }
  // Annahme KN-B: abgeleiteter Status "veraltet" mit Ursache (Feldnamen defensiv).
  // N-918-02: KN-B-Vertrag (r5/kn-backend): freshness {status:'STALE', causes:[{kind,text,currencies}], message}
  // und publication_status bzw. active_publication.status 'PUBLICATION_INVALID' (reason_code CCX_INPUT_STALE).
  function causeText(c){
    if (!c) return '';
    var ccys = Array.isArray(c.currencies) ? c.currencies.map(up).filter(Boolean) : [];
    if (c.kind === 'fx_rate' && ccys.length) return 'Wechselkurs ' + ccys.join(', ') + ' geändert';
    return String(c.text || '').trim();
  }
  function staleCauseFromStatus(s){
    if (!s || typeof s !== 'object') return '';
    var f = s.freshness;
    if (f && typeof f === 'object' && up(f.status) === 'STALE') {
      var seen = {}, texts = [];
      (Array.isArray(f.causes) ? f.causes : []).forEach(function(c){ var t = causeText(c); if (t && !seen[t]) { seen[t] = 1; texts.push(t); } });
      if (texts.length) return texts.join('; ');
      return f.message ? staleCauseFromText(f.message) : 'Beratungsdaten geändert';
    }
    var act = s.active_publication || {};
    if ((up(s.publication_status) === 'PUBLICATION_INVALID' || up(act.status) === 'PUBLICATION_INVALID')
      && /STALE/.test(up(act.reason_code || s.reason_code))) return 'Beratungsdaten geändert';
    var flagged = s.stale === true || /STALE|VERALTET|OUTDATED/i.test(String(s.publication_status || s.derived_status || s.status || '')) || !!s.stale_reason_code;
    if (!flagged) return '';
    var reason = String(s.stale_reason || s.stale_message || '');
    if (reason) return staleCauseFromText(/veraltet/i.test(reason) ? reason : 'veraltet: ' + reason);
    var ccys = Array.isArray(s.stale_currencies) ? s.stale_currencies.map(up).filter(Boolean) : [];
    if (ccys.length) return 'Wechselkurs ' + ccys.join(', ') + ' geändert';
    return 'Eingaben seit der Berechnung geändert';
  }
  function staleCause(){ return stale.mid && stale.mid === activeMid() ? stale.cause : ''; }
  function bannerText(c){ return c + ' – bitte «Anlagestrategie berechnen» klicken.'; }
  function statusText(c){ return 'Soll-Allokation veraltet: ' + c + '. Bitte «Anlagestrategie berechnen» ausführen.'; }
  function clearStale(mid){ if (!mid || stale.mid === String(mid)) { stale.mid = ''; stale.cause = ''; } }
  function errText(e){
    if (!e) return '';
    if (typeof e.detail === 'string' && e.detail) return e.detail;
    try { var p = JSON.parse(e.body || '{}'); var d = p && p.detail; return typeof d === 'string' ? d : (d && d.message) || ''; } catch(_){ return String(e.message || ''); }
  }
  var applying = false;
  function applyStale(mid, cause){
    if (!cause || !mid) return false;
    stale.mid = String(mid); stale.cause = cause;
    if (String(mid) !== activeMid() || applying) return true;
    applying = true;
    safe(function(){
      var s = state();
      if (s) { s.dirty = true; s.staleNotice = bannerText(cause); }
      // Keine alten Zahlen als "Publiziert": Ausgaben verwerfen, Ursache zeigen.
      var hv = g('hasVisibleStrategyOutputs');
      if (hv && hv() && g('invalidateStrategyOutputs')) invalidateStrategyOutputs();
      else if (g('syncStrategyStaleView')) syncStrategyStaleView();
      if (g('updateStrategyStatus')) updateStrategyStatus(statusText(cause), true);
      if (g('renderAllocationPublication')) renderAllocationPublication();
      if (g('applyPortfolioUmsetzenVisibility')) applyPortfolioUmsetzenVisibility();
      if (g('renderReviewHero') && typeof currentReviewState !== 'undefined') renderReviewHero(currentReviewState);
    });
    applying = false;
    return true;
  }
  // Erneute Pruefung der aktiven Soll-Allokation (nach einer Kursaenderung ohne Neuladen).
  async function revalidateActiveAllocation(){
    var mid = activeMid();
    var demo = g('isDemoMandateId');
    if (!mid || (demo && demo(mid)) || typeof API === 'undefined') return '';
    try {
      await API.get('/mandates/' + encodeURIComponent(mid) + '/target-allocation/current/payload');
      clearStale(mid);
      return 'fresh';
    } catch(e) {
      var cause = String(e && e.status) === '409' ? staleCauseFromText(errText(e)) : '';
      if (cause && activeMid() === mid) applyStale(mid, cause);
      return cause ? 'stale' : '';
    } finally {
      if (g('refreshAllocationPublication')) safe(function(){ refreshAllocationPublication(true); });
    }
  }
  var GENERIC_STATUS = /hydratisiert|Noch keine gespeicherte Strategie|Aktuelle Strategie konnte nicht geladen/;
  function hookStale(){
    wrap('loadCurrentAllocationResult', function(orig){
      return async function(mid){
        try {
          var r = await orig.apply(this, arguments);
          if (r) clearStale(mid);
          return r;
        } catch(e) {
          var cause = String(e && e.status) === '409' ? staleCauseFromText(errText(e)) : '';
          if (cause) applyStale(mid, cause);
          throw e;
        }
      };
    });
    wrap('finalizeStrategyOutputs', function(orig){
      return function(){ clearStale(activeMid()); return orig.apply(this, arguments); };
    });
    wrap('markStrategyDirty', function(orig){
      return function(message, inv){
        var c = staleCause();
        var generic = !message || (typeof STRATEGY_STALE_DEFAULT_NOTICE === 'string' && message === STRATEGY_STALE_DEFAULT_NOTICE);
        var args = Array.prototype.slice.call(arguments);
        if (c && generic) args[0] = bannerText(c);
        return orig.apply(this, args);
      };
    });
    wrap('updateStrategyStatus', function(orig){
      return function(message, isError){
        var m = String(message == null ? '' : message);
        var c = /Soll-Allokation ist veraltet/.test(m) ? staleCauseFromText(m) : '';
        if (c) { stale.mid = activeMid(); stale.cause = c; }
        else c = GENERIC_STATUS.test(m) ? staleCause() : '';
        return c ? orig.call(this, statusText(c), true) : orig.apply(this, arguments);
      };
    });
    wrap('renderAllocationPublication', function(orig){
      return function(){
        var r = orig.apply(this, arguments);
        safe(function(){
          var s = typeof allocationPublicationState !== 'undefined' ? allocationPublicationState : null;
          var fromStatus = staleCauseFromStatus(s);
          if (fromStatus && fromStatus !== staleCause()) { stale.cause = ''; applyStale(activeMid(), fromStatus); }
          var c = staleCause();
          if (!c) return;
          var chip = byId('aa-publication-status');
          if (chip) {
            chip.textContent = 'Veraltet · ' + c;
            chip.title = 'Die publizierte Soll-Allokation ist nicht mehr aktuell und darf nicht verwendet werden.';
            chip.style.display = '';
          }
          var btn = byId('btn-aa-publish');
          if (btn) { btn.style.display = 'none'; btn.disabled = true; }
          var ums = byId('btn-portfolio-umsetzen');
          if (ums) ums.style.display = 'none';
        });
        return r;
      };
    });
    wrap('applyPortfolioUmsetzenVisibility', function(orig){
      return function(){
        var r = orig.apply(this, arguments);
        if (staleCause()) { var b = byId('btn-portfolio-umsetzen'); if (b) b.style.display = 'none'; }
        return r;
      };
    });
    wrap('renderReviewHero', function(orig){
      return function(){
        var r = orig.apply(this, arguments);
        var c = staleCause();
        var hero = byId('rv-hero');
        if (c && hero) {
          hero.dataset.rvMask = 'stale';
          hero.style.cssText = 'background:#fff7ed;border:1px solid rgba(194,65,12,0.3);border-radius:var(--r2);padding:24px 28px;margin-bottom:14px';
          hero.innerHTML = '<div style="font-size:9px;font-weight:800;letter-spacing:0.12em;text-transform:uppercase;color:#9a3412;margin-bottom:10px">STRATEGIE VERALTET</div>'
            + '<div id="rv-stale-cause" style="font-size:15px;font-weight:700;color:var(--n8);margin-bottom:6px">' + esc(c) + '</div>'
            + '<div style="font-size:11px;color:var(--n6);line-height:1.65;margin-bottom:12px">Die publizierte Soll-Allokation ist nicht mehr aktuell. Bitte die Anlagestrategie neu berechnen, finalisieren und publizieren.</div>'
            + '<div><button class="btn btn-sm" type="button" onclick="go(\'al\')">Zur Asset Allokation</button></div>';
        }
        return r;
      };
    });
    // Kursaenderung im Schnelleditor oder in der Administration: aktive Strategie neu pruefen.
    ['saveFxQuickEditor', 'saveAdminFxRates'].forEach(function(name){
      wrap(name, function(orig){
        return async function(){
          var r = await orig.apply(this, arguments);
          if (r !== false) await revalidateActiveAllocation();
          if (name === 'saveFxQuickEditor' && r) await refreshFxQuickEditor();
          return r;
        };
      });
    });
  }

  // ------------------------------------------------------------ Schnelleditor nach dem Speichern (E2E2-15)
  async function refreshFxQuickEditor(){
    var status = byId('fxq-status');
    var msg = status ? status.textContent : '', color = status ? status.style.color : '';
    var ccys = Array.prototype.map.call(document.querySelectorAll('#fxq-grid .fxq-input'), function(el){ return el.getAttribute('data-currency'); });
    if (g('openFxQuickEditor')) await openFxQuickEditor(ccys);
    status = byId('fxq-status');
    if (status) { status.textContent = msg; status.style.color = color; }
  }

  // ------------------------------------------------------------ Mandatswechsel (E2E2-01)
  // Diese Dialoge sind nicht mandatsgebunden (bzw. steuern den Wechsel selbst).
  var KEEP = {'m-nc': 1, 'm-admin': 1, 'm-2fa': 1, 'm-force-pw': 1, 'm-team': 1, 'm-invite': 1, 'm-reset': 1,
    'm-cal-feed': 1, 'm-fund-approve': 1, 'm-prov': 1, 'm-ui-dialog': 1, 'm-firm-question': 1, 'm-strategy-calc': 1};
  function closeMandateOverlays(){
    Array.prototype.forEach.call(document.querySelectorAll('.overlay.open'), function(o){
      if (KEEP[o.id]) return;
      if (o.id && o.id !== 'm-ne' && g('cm')) cm(o.id);
      else o.classList.remove('open');
    });
  }
  var DASH = '—';
  function setRiskTiles(){
    var mid = activeMid();
    var f = g('currentPersistedRiskForMandate'), f2 = g('currentRiskAssessmentForOverride');
    var risk = (mid && f && f(mid)) || (mid && f2 && f2(mid)) || null;
    var score = risk && (risk.final_score_x10 != null) ? Number(risk.final_score_x10) / 10 : null;
    txt('sr-risk-score', score != null && g('fmtNumber') ? fmtNumber(score, 0) + ' / 10' : DASH);
    txt('sr-risk-profile', risk && risk.final_profile ? risk.final_profile : 'Risikoprofil noch nicht erfasst');
    var ovr = byId('sr-ovr-badge');
    if (ovr) ovr.style.display = risk && Number(risk.is_overridden || 0) ? 'block' : 'none';
    txt('sr-strategy-name', risk && risk.final_profile ? risk.final_profile : 'Nicht definiert');
    txt('sr-horizon', risk && risk.investment_horizon_years ? risk.investment_horizon_years + ' Jahre' : DASH);
    return risk;
  }
  // Review-Kacheln ohne Allokation: nur Werte des aktiven Mandats, sonst "--".
  function clearStrategySummaryForDirtyState(){
    var snapF = g('currentAllocationInputSnapshot');
    var snap = snapF ? (safe(snapF) || {}) : {};
    var advisory = Number(snap.advisoryRappen || 0), total = Number(snap.totalNetRappen || 0);
    if (snap.fxOpen) {
      var items = positions(), mix = mixOf(items), known = advisoryWhenBlocked(items, mix);
      txt('sr-wealth', known ? formatAmount(known.rappen, known.currency) : 'Umrechnung offen');
      txt('sr-wealth-share', 'Kein Anteil: ' + fxOpenText(mix));
    } else {
      txt('sr-wealth', advisory && g('formatCompactCHF') ? formatCompactCHF(advisory / 100, snap.wealthCurrency) : DASH);
      txt('sr-wealth-share', total && advisory && typeof AresRounding !== 'undefined'
        ? AresRounding.formatPercent(advisory / Math.max(1, total) * 100, 0, {typography: 'screen'}) + ' des Reinvermögens' : 'Strategie ausstehend');
    }
    if (g('setGoalSuccessTile')) setGoalSuccessTile(null); else txt('sr-goal-score', DASH);
    txt('sr-goal-sub', 'Bitte Strategie neu berechnen.');
    txt('kpi-goal-score', DASH);
    txt('kpi-goal-sub', 'Strategie ausstehend');
    var pv = txt('sr-proj-wealth', DASH);
    if (pv) pv.title = '';
    txt('sr-proj-sub', 'Bitte Strategie neu berechnen.');
    if (pv && pv.previousElementSibling) pv.previousElementSibling.textContent = 'Prognose';
    setRiskTiles();
    var bars = byId('sr-allocation-bars');
    if (bars) bars.innerHTML = '<div style="font-size:10px;color:var(--n5)">Soll-Allokation erscheint nach der nächsten Berechnung.</div>';
    var goals = byId('sr-goal-priority-list');
    if (goals) goals.innerHTML = '<div style="font-size:10px;color:var(--n5)">Zielauswertung erscheint nach der nächsten Berechnung.</div>';
  }
  function resetGlobals(){
    try { currentReviewState = {triggers: [], logs: [], documents: [], conflicts: [], suitability: [], allocation: null, recommendation: null}; } catch(_){}
    try { currentWealthSummary = null; } catch(_){}
    try { currentWealthPositions = []; } catch(_){}
    try { currentPortfolioPositions = []; } catch(_){}
    try { currentInflows = []; } catch(_){}
    try { goalRevisionEvidenceByGoal = {}; goalRevisionDialogState = null; } catch(_){}
    try { BT_LAST_RESULT = null; } catch(_){}
    try { _costDisclosureLastPayload = null; } catch(_){}
    try { _tlHandoffCtx = null; } catch(_){}
    try { allocationSuballocExpanded = {}; portfolioExpandedRows = {}; portfolioTechnicalExpandedRows = {}; } catch(_){}
    try { allocationPublicationState = null; allocationPublicationKey = ''; } catch(_){}
    try { if (typeof strategyState !== 'undefined' && strategyState) { strategyState.allocation = null; strategyState.recommendation = null; strategyState.pendingAllocation = null; strategyState.pendingRecommendation = null; strategyState.staleNotice = null; } } catch(_){}
  }
  // N-918-01: erst alle Ausgaben neutralisieren (AA, Portfolio-Kopf, Review), dann rendert der Ladepfad
  // neu; bricht ein Render-Pfad frueh ab (z. B. ohne Risikoprofil), bleibt nichts vom vorigen Mandat stehen.
  function resetOutputs(){
    if (g('invalidateStrategyOutputs')) safe(function(){ invalidateStrategyOutputs(); });
    if (g('renderPortfolioNeutralState')) safe(function(){ renderPortfolioNeutralState('Kein Portfolio für dieses Mandat geladen'); });
    if (g('renderPortfolioSections')) safe(function(){ renderPortfolioSections([]); });
    if (g('renderSrImplementationDecision')) safe(function(){ renderSrImplementationDecision(null); });
    if (g('renderOptimizerAchievability')) safe(function(){ renderOptimizerAchievability(null); });
    if (g('renderGoalAchievementSollIst')) safe(function(){ renderGoalAchievementSollIst(null); });
    // Ausgeblendete Kontext-Bloecke behalten sonst ihren Text im DOM (Reinvermoegen, Zielnamen, Rechenfakten).
    ['alloc-rein-context', 'aa-goal-sollist', 'opt-sensitivity-list'].forEach(function(id){
      var el = byId(id); if (el) el.innerHTML = '';
    });
    safe(function(){ var dnBody = document.querySelector('#ch-dn-table tbody'); if (dnBody) dnBody.innerHTML = ''; });
    safe(function(){
      var calc = byId('m-strategy-calc');
      if (calc && !calc.classList.contains('open')) { var facts = byId('strategy-calc-facts'); if (facts) facts.textContent = ''; }
    });
  }
  function resetDom(){
    resetOutputs();
    clearStrategySummaryForDirtyState();
    Array.prototype.forEach.call(document.querySelectorAll('.kpir .kv'), function(el){ el.textContent = DASH; });
    Array.prototype.forEach.call(document.querySelectorAll('.kpir .ks'), function(el){ el.textContent = ''; });
    var hud = byId('cf-projection');
    if (hud) { hud.style.display = 'none'; hud.innerHTML = ''; }
    var hero = byId('rv-hero');
    if (hero) { hero.innerHTML = ''; hero.removeAttribute('style'); }
    var chip = byId('aa-publication-status');
    if (chip) { chip.textContent = ''; chip.style.display = 'none'; }
    ['btn-aa-publish', 'btn-portfolio-umsetzen', 'btn-aa-goto-finalize'].forEach(function(id){ var b = byId(id); if (b) b.style.display = 'none'; });
    var steps = byId('sr-implementation-steps');
    if (steps) steps.innerHTML = '';
    txt('sr-decision-meta', '');
    var blocker = byId('aa-calc-blocker');
    if (blocker) blocker.style.display = 'none';
    ['po-status', 'aa-pref-status', 'recipe-status'].forEach(function(id){ var el = byId(id); if (el) { el.textContent = ''; if (id === 'po-status') el.style.display = 'none'; } });
  }
  function aresResetMandateView(){
    safe(closeMandateOverlays);
    safe(resetGlobals);
    safe(resetDom);
  }

  // Review ohne Allokation: keine Aussage "alles im Band" und kein "Empfehlung vom --".
  function hookReview(){
    wrap('renderStrategySummary', function(orig){
      return function(){
        if (!alloc()) { clearStrategySummaryForDirtyState(); return; }
        var r = orig.apply(this, arguments);
        safe(function(){ depletionTile(alloc()); });
        return r;
      };
    });
    wrap('renderSrApiSummary', function(orig){
      return function(risk, allocation){
        var r = orig.apply(this, arguments);
        var a = allocation || alloc();
        if (a) safe(function(){ depletionTile(a); }); else safe(setRiskTiles);
        return r;
      };
    });
    wrap('renderSrImplementationDecision', function(orig){
      return function(){
        var r = orig.apply(this, arguments);
        if (!alloc()) {
          var steps = byId('sr-implementation-steps');
          var c = staleCause();
          if (steps) steps.innerHTML = '<div style="grid-column:1/-1;border:1px solid var(--b1);border-radius:var(--r2);padding:12px;background:var(--bg)"><div style="font-size:11px;color:var(--n8);font-weight:500;margin-bottom:4px">'
            + (c ? 'Strategie veraltet' : 'Noch keine Soll-Allokation') + '</div><div style="font-size:10px;color:var(--n6)">'
            + esc(c ? c + '. Empfehlungen je Anlageklasse erscheinen nach «Anlagestrategie berechnen».' : 'Empfehlungen je Anlageklasse erscheinen nach «Anlagestrategie berechnen».') + '</div></div>';
        }
        var meta = byId('sr-decision-meta');
        if (meta && /—/.test(meta.textContent || '') && !/Handelsliste/.test(meta.textContent || '')) meta.textContent = 'Noch keine Empfehlung erfasst';
        return r;
      };
    });
  }

  // ------------------------------------------------------------ Verzehr in der Review-Kachel (E2E-12)
  function depletionInfo(a){
    var mc = g('monteCarloPayload') ? monteCarloPayload(a) : null;
    var sim = g('simulationPayload') ? simulationPayload(a) : null;
    var series = (mc && mc.target_p50_series_rappen) || (sim && sim.target_mix_series_rappen) || [];
    var labels = (mc && mc.year_labels) || (sim && sim.year_labels) || [];
    var year = null;
    for (var i = 0; i < series.length; i++) { if (Number(series[i]) < 0) { year = labels[i] != null ? String(labels[i]).slice(0, 4) : null; break; } }
    return {year: year, start: Number(series[0] || 0), sim: sim};
  }
  function depletionTile(a){
    var f = g('strategyMedianProjectionRappen');
    var projected = f ? Number(f(a)) : 0;
    if (!(projected < 0)) return null;
    var info = depletionInfo(a);
    var depleted = info.year && info.start > 0;
    var el = txt('sr-proj-wealth', depleted ? 'Aufgebraucht ab ' + info.year : 'Finanzierungslücke');
    if (el) el.title = 'Mittlerer Verlauf: Das Vermögen reicht nicht bis zum Ende der Prognose. Werte unter null werden als Finanzierungslücke ausgewiesen, nicht als Vermögen.';
    var horizon = g('projectionHorizonYearLabel') ? projectionHorizonYearLabel(info.sim) : '';
    if (el && el.previousElementSibling) el.previousElementSibling.textContent = horizon ? 'Prognose ' + horizon : 'Prognose';
    txt('sr-proj-sub', (depleted ? 'Vermögen aufgebraucht ab ' + info.year : (info.year ? 'Finanzierungslücke ab ' + info.year : 'Finanzierungslücke')) + ' (mittlerer Verlauf)');
    return info.year;
  }

  // ------------------------------------------------------------ Banner unter der Kopfzeile (E2E2-02)
  function mountBannerLayout(){
    if (byId('knu-banner-css') || !document.head) return;
    var st = document.createElement('style');
    st.id = 'knu-banner-css';
    st.textContent = '#pg-egress-banner{position:fixed!important;top:48px!important;left:0;right:0;z-index:150!important;max-height:40vh;overflow:auto}'
      + 'body.knu-banner .layout{margin-top:calc(48px + var(--knu-banner-h,0px));height:calc(100vh - 48px - var(--knu-banner-h,0px))}'
      // N-918-03: rechte Kopfzeilen-Knoepfe schrumpfen nie ueber die Schritte; schmal = Kompaktmodus
      // (inaktive Schritte nur Nummer, Name als title/Screenreader), Rueckfall Scrollleiste der .tnav.
      + '.topbar .tr{flex-shrink:0}'
      + '@media(max-width:1440px){#current-user-label{display:none}.topbar .tr{gap:5px;padding:0 8px}.topbar .tr .t-btn{padding:5px 8px}'
      + '.tstep:not(.active){font-size:0;gap:0;padding:0 6px}.tstep:not(.active) .sn{font-size:9px}}'
      + '@media(max-width:1180px){.logo{width:112px;min-width:112px;padding:0 10px}.logo-s{display:none}'
      + '#btn-presentation-mode-toggle{max-width:96px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}';
    document.head.appendChild(st);
    Array.prototype.forEach.call(document.querySelectorAll('.tnav .tstep'), function(el){
      if (!el.title) el.title = String(el.textContent || '').replace(/^\s*\d+\s*/, '').trim();
    });
    var observed = null;
    var ro = typeof ResizeObserver === 'function' ? new ResizeObserver(function(){ sync(); }) : null;
    function sync(){
      var b = byId('pg-egress-banner');
      var h = b && b.parentNode ? Math.ceil(b.getBoundingClientRect().height) : 0;
      document.body.classList.toggle('knu-banner', h > 0);
      document.body.style.setProperty('--knu-banner-h', h + 'px');
      if (ro && b !== observed) { if (observed) ro.unobserve(observed); if (b) ro.observe(b); observed = b; }
    }
    if (typeof MutationObserver === 'function') new MutationObserver(sync).observe(document.body, {childList: true});
    window.addEventListener('resize', sync);
    sync();
  }

  // ------------------------------------------------------------ Einhaengen
  function hookGo(){
    wrap('go', function(orig){
      return async function(p){
        var r = await orig.apply(this, arguments);
        if ((p === 'al' || p === 'po' || p === 'rv' || p === 'sr') && alloc() && g('refreshAllocationPublication')) safe(function(){ refreshAllocationPublication(true); });
        return r;
      };
    });
  }
  // N-918-04: Cashflow-HUD ohne erfasste Einnahmen/Ausgaben -- keine Nullaussage "CHF 0 · Ausgeglichen".
  function hookCashflowHud(){
    wrap('renderCashflowProjection', function(orig){
      return function(data){
        var r = orig.apply(this, arguments);
        safe(function(){
          var el = byId('cf-projection');
          var row = data && Array.isArray(data.years) ? data.years[0] : null;
          var parts = row && g('cashflowProjectionComponents') ? cashflowProjectionComponents(row) : null;
          if (!el || !parts || el.style.display === 'none') return;
          if (Number(parts.recurringIncomeRappen || 0) === 0 && Number(parts.recurringExpenseRappen || 0) === 0) {
            el.innerHTML = '<div class="cf-hud"><div class="cf-hud-head"><div><div class="cf-hud-kicker">Cashflow-HUD</div>'
              + '<div class="cf-hud-copy">Keine Cashflows erfasst</div></div></div>'
              + '<div class="cf-hud-hint" style="padding:6px 0">Erfassen Sie laufende Einnahmen und Ausgaben, damit Sparquote bzw. Vermögensverzehr berechnet werden.</div></div>';
          }
        });
        return r;
      };
    });
  }
  function hookWealth(){
    wrap('renderWealthPositions', function(orig){
      return function(){ var r = orig.apply(this, arguments); safe(syncAdvisoryKpi); return r; };
    });
  }
  function mountAll(){
    safe(mountBannerLayout);
    safe(hookMixedTotals);
    safe(hookStale);
    safe(hookReview);
    safe(hookWealth);
    safe(hookCashflowHud);
    safe(hookGo);
  }
  if (typeof document !== 'undefined' && document.addEventListener) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mountAll);
    else mountAll();
  }

  window.aresTerm = aresTerm;
  window.aresResetMandateView = aresResetMandateView;
  window.clearStrategySummaryForDirtyState = clearStrategySummaryForDirtyState;
  window.aresBlockedTotal = aresBlockedTotal;
  window.aresSnapshotAmount = aresSnapshotAmount;
  window.aresCcySum = aresCcySum;
  window.aresFxOpenText = fxOpenText;
  window.aresAdvisoryWhenBlocked = advisoryWhenBlocked;
  window.aresStaleCauseFromText = staleCauseFromText;
  window.aresStaleCauseFromStatus = staleCauseFromStatus;
  window.aresStaleCause = staleCause;
  window.aresApplyStale = applyStale;
  window.aresRevalidateActiveAllocation = revalidateActiveAllocation;
  window.aresDepletionTile = depletionTile;
})();
