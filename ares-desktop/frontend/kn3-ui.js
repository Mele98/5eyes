/* Ares -- Kernkette Runde 3, Classic-Berateroberflaeche (KN3-U, Dok. 118 / H-167 R2).
 * Teil des Monolith-Bundles (eigenes Budget, direkt nach mandate-view.js). Haengt
 * sich selbst ein und nutzt die globalen Helfer erst beim Aufruf. Zahlen, Baender,
 * Freigaben und Frische bleiben Serverwahrheit; hier wird nur bewertet/neu geladen.
 *
 * E2E3-01  EINE Bandlogik (aresBandOf/aresBandStatus) fuer Karte, Kopfzeile,
 *          Umsetzungsschritte, Bandgrafik und Markt-Trigger. "Kein Band" nur, wenn
 *          die Bandangaben fehlen (null/undefined/leer). Der Server liefert
 *          band_min_bps/band_max_bps als Pflicht-Integer (Bucket- und Live-Antwort,
 *          DB-Spalten NOT NULL): "fehlt" und "0" sind unterscheidbar, 0/0 ist eine
 *          echte Obergrenze 0 (vom Profil ausgeschlossene Klasse). Das Punktband
 *          min==max>0 (Live-Test H6) bleibt ein Band.
 * E2E3-02  Nach Kurs- oder Vermoegensaenderung: Vermoegen, Cashflows, Strategiebasis
 *          der AA, Portfolio-Kopf und Review-Kacheln ohne Mandatswechsel neu.
 * E2E3-07  Cashflow-Seite nach jeder Vermoegensaenderung sofort neu (automatische
 *          Hypothekarzins- und Amortisationszeilen; refreshWealthUI ist der gemeinsame Pfad).
 * E2E3-08  Strukturierte Servermeldung ohne technischen Code anzeigen.
 * E2E3-09  KYC-Bestaetigung: Pflichtfelder vorab; bei einem Fehler bleiben alle
 *          Eingaben stehen (das Panel zeichnet sich mit dem Serverstand neu).
 * E2E3-12  Neu angelegtes Mandat sofort ueber Suche und Buchstaben auffindbar.
 * E2E3-13  Automatische Amortisation mit Ende statt "unbefristet".
 * E2E3-14  Ohne je berechnete Strategie (Server 404) kein "Strategie veraltet".
 * Umgezogen aus mandate-view.js (Budget): aresTerm (E2E2-14), Cashflow-HUD
 * ohne Cashflows (N-918-04); aus ares.html: reviewBandVisualHtml. */

function aresBandOf(minBps,maxBps){
  if(minBps==null||maxBps==null||minBps===''||maxBps==='')return null;
  var min=Number(minBps),max=Number(maxBps);
  if(!isFinite(min)||!isFinite(max)||max<min)return null;
  return {min:min,max:max,point:min===max};
}
function aresBandStatus(currentBps,minBps,maxBps){
  var band=aresBandOf(minBps,maxBps);
  if(!band)return 'none';
  var current=Number(currentBps||0);
  return (current<band.min||current>band.max)?'violated':'in';
}
function aresBandNumber(value){return value==null||value===''?null:Number(value);}
function reviewBandVisualHtml(item,meta){
  var band=aresBandOf(item.bandMinBps,item.bandMaxBps); // 0/0 = Punktband bei 0, ohne Angaben Hilfszone Ziel +/- 5 %
  var min=band?band.min:Math.max(0,Number(item.targetWeightBps||0)-500);
  var max=band?band.max:Math.min(10000,Number(item.targetWeightBps||0)+500);
  var target=Math.max(0,Math.min(10000,Number(item.targetWeightBps||0)));
  var current=Math.max(0,Math.min(10000,Number(item.currentWeightBps||0)));
  var zoneLeft=(min/100).toFixed(2);
  var zoneWidth=Math.max(1,(max-min)/100).toFixed(2);
  var targetLeft=(target/100).toFixed(2);
  var currentLeft=(current/100).toFixed(2);
  var zoneTone=meta.tagClass==='tr2'?'rgba(139,30,30,0.16)':'rgba(42,74,112,0.14)';
  var shellTone=meta.tagClass==='tr2'?'rgba(139,30,30,0.08)':'transparent';
  return '<div style="min-width:170px"><div style="position:relative;height:24px;border:1px solid var(--b1);border-radius:999px;background:'+shellTone+'">'
    +'<div style="position:absolute;left:5px;right:5px;top:11px;height:2px;background:var(--bg2);border-radius:999px"></div>'
    +'<div style="position:absolute;left:'+zoneLeft+'%;width:'+zoneWidth+'%;top:7px;height:10px;background:'+zoneTone+';border-radius:999px"></div>'
    +'<div style="position:absolute;left:'+targetLeft+'%;top:4px;width:2px;height:16px;background:var(--pri);transform:translateX(-1px)"></div>'
    +'<div style="position:absolute;left:'+currentLeft+'%;top:5px;width:12px;height:12px;border-radius:50%;background:'+meta.tone+';border:2px solid #fff;box-shadow:0 0 0 1px rgba(15,23,42,0.12);transform:translateX(-6px)"></div>'
    +'</div><div style="display:flex;justify-content:space-between;gap:6px;margin-top:4px;font-size:9px;color:var(--n4)"><span>'+escapeHtml(formatBpsPercent(min))+'</span><span>Ziel '+escapeHtml(formatBpsPercent(target))+'</span><span>'+escapeHtml(formatBpsPercent(max))+'</span></div></div>';
}
// E2E3-13: Rechnung der Engine (K1): direkt bis die Schuld getilgt ist, indirekt bis und
// mit dem Pensionierungsjahr (ohne Pensionierungsjahr ueber den Planungshorizont).
function derivedAmortizationEndLabel(cashflow){
  var id=String(cashflow&&cashflow.id||'');
  if(id.indexOf('derived:mortgage_amortization:')!==0)return '';
  var pid=String(cashflow.origin_position_id||id.slice('derived:mortgage_amortization:'.length));
  var pos=(Array.isArray(currentWealthPositions)?currentWealthPositions:[]).find(function(p){return p&&String(p.id||'')===pid;})||null;
  var type=String(pos&&pos.mortgage_amortization_type||'');
  if(type.indexOf('Indirekt')===0){
    var ry=currentMandateData&&currentMandateData.retirement_year?Number(currentMandateData.retirement_year):null;
    return ry?('bis und mit Pensionierungsjahr '+ry):'bis Ende des Planungshorizonts (kein Pensionierungsjahr erfasst)';
  }
  if(type==='Direkt')return 'bis die Hypothek getilgt ist';
  return 'bis die Hypothek getilgt ist bzw. bis zur Pensionierung';
}

(function(){
  'use strict';
  function byId(id){ return document.getElementById(id); }
  function g(name){ return typeof window[name] === 'function' ? window[name] : null; }
  function txt(id, v){ var el = byId(id); if (el) el.textContent = v; return el; }
  function safe(f){ try { return f(); } catch(e){ try { console.warn('kn3-ui', e); } catch(_){} return null; } }
  function wrap(name, make){
    var o = window[name];
    if (typeof o !== 'function' || o.__kn3Hooked) return false;
    var w = make(o);
    w.__kn3Hooked = true;
    window[name] = w;
    return true;
  }
  function activeMid(){ var f = g('getActiveMandateId'); return f ? String(f() || '') : ''; }
  function activeCid(){ return typeof currentClientId !== 'undefined' && currentClientId ? String(currentClientId) : ''; }
  function state(){ return typeof strategyState !== 'undefined' && strategyState ? strategyState : null; }
  function alloc(){ var s = state(); return s ? s.allocation || null : null; }

  // ------------------------------------------------------------ Fachbegriffe (E2E2-14, aus mandate-view.js)
  function aresTerm(name){
    return String(name == null ? '' : name)
      .replace(/\s*\(CHF gehedgt\)|\s*_?Hedged\s*CHF\b/g, function(m){ var p = m.indexOf('(') >= 0; return (p ? ' (' : ' ') + 'währungsgesichert in CHF' + (p ? ')' : ''); })
      .replace(/\bHedged\b/g, 'währungsgesichert')
      .replace(/\bgehedgt\b/g, 'währungsgesichert')
      .replace(/\bIG\b/g, 'Investment Grade')
      .replace(/Gluecksspiel/g, 'Glücksspiel').replace(/laender/g, 'länder').replace(/Laender/g, 'Länder');
  }

  // ------------------------------------------------------------ Cashflow-HUD ohne Cashflows (N-918-04, aus mandate-view.js)
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

  // ------------------------------------------------------------ Betraege sofort nachziehen (E2E3-02, E2E3-07)
  async function refreshMandateAmounts(){
    var cid = activeCid();
    var demo = g('isDemoClientId');
    if (!cid || (demo && demo(cid))) return false;
    if (g('resetWealthSummaryCache')) safe(function(){ resetWealthSummaryCache(); }); // Servercache der Mischwaehrungssumme
    if (g('refreshWealthUI')) { try { await refreshWealthUI(cid); } catch(_){} }      // laedt (gehookt) auch die Cashflow-Seite
    return true;
  }
  // Ohne geladene Soll-Allokation zeigen Torte/Leerzustand ("Strategiebasis aktuell"),
  // Portfolio-Kopf und Review-Kacheln den aktuellen Eingabestand; mit Allokation gelten
  // deren eigene (berechnete) Betraege.
  function syncAmountViews(){
    if (alloc() || !activeMid()) return;
    var snapF = g('currentAllocationInputSnapshot');
    var snap = snapF ? (safe(snapF) || {}) : {};
    var adv = Number(snap.advisoryRappen || 0), ok = adv > 0 && !snap.fxOpen;
    // Tortenmitte "Beratungsvermoegen" (globales TOTAL des Monolithen).
    try { if (typeof TOTAL !== 'undefined') { TOTAL = ok ? Math.round(adv / 100) : 0; TOTAL_CCY = ok ? (snap.wealthCurrency || null) : null; } } catch(_){}
    if (g('buildDLegend')) safe(function(){ buildDLegend(); });
    if (g('clearStrategySummaryForDirtyState')) safe(function(){ clearStrategySummaryForDirtyState(); });
    var text = ok && g('formatRappen') ? formatRappen(adv, snap.wealthCurrency) : '—';
    txt('po-advisory-wealth', text);
    txt('po-total-footer', text);
  }
  function hookAmounts(){
    wrap('refreshWealthUI', function(orig){
      return async function(cid){
        var r = await orig.apply(this, arguments);
        if (cid && String(cid) === activeCid() && g('refreshCashflowsUI')) { try { await refreshCashflowsUI(cid); } catch(_){} }
        safe(syncAmountViews);
        return r;
      };
    });
    // Die Mischwaehrungssumme kommt asynchron (Servercache); danach zeichnet der Monolith
    // die Positionen neu -- die betragsabhaengigen Anzeigen ziehen mit.
    wrap('renderWealthPositions', function(orig){
      return function(){ var r = orig.apply(this, arguments); safe(syncAmountViews); return r; };
    });
  }

  // ------------------------------------------------------------ Kein "veraltet" ohne Strategie (E2E3-14)
  var serverAlloc = {}; // Mandat -> Soll-Allokation beim Server: true (200/409), false (404), unbekannt
  function hookNoStrategy(){
    wrap('loadCurrentAllocationResult', function(orig){
      return async function(mid){
        try { var r = await orig.apply(this, arguments); if (r) serverAlloc[String(mid)] = true; return r; }
        catch(e) { var st = String(e && e.status); if (st === '404') serverAlloc[String(mid)] = false; else if (st === '409') serverAlloc[String(mid)] = true; throw e; }
      };
    });
    wrap('finalizeStrategyOutputs', function(orig){
      return function(){ var mid = activeMid(); if (mid) serverAlloc[mid] = true; return orig.apply(this, arguments); };
    });
    wrap('markStrategyDirty', function(orig){
      return function(){
        var r = orig.apply(this, arguments);
        safe(function(){
          var s = state(), cause = g('aresStaleCause') ? aresStaleCause() : '';
          if (serverAlloc[activeMid()] !== false || alloc() || !s || s.pendingAllocation || cause) return;
          s.staleNotice = null; // Leerzustand nennt den Grund ("noch nicht berechnet")
          if (g('syncStrategyStaleView')) syncStrategyStaleView();
        });
        return r;
      };
    });
  }

  // ------------------------------------------------------------ Neues Mandat auffindbar (E2E3-12)
  function hookSidebarSearch(){
    wrap('createNewMandate', function(orig){
      return async function(){
        var r = await orig.apply(this, arguments);
        safe(function(){
          var sbl = byId('sbl');
          var list = typeof liveClients !== 'undefined' && Array.isArray(liveClients) ? liveClients : [];
          if (!sbl) return;
          Array.prototype.forEach.call(sbl.querySelectorAll('.client'), function(el){
            if (el.dataset.search) return;
            var c = list.filter(function(x){ return x && String(x.id) === String(el.dataset.cid); })[0];
            if (!c) return;
            var letter = g('_clientLetter') ? _clientLetter(c) : '#';
            el.dataset.letter = letter;
            el.dataset.search = ((c.first_name || '') + ' ' + (c.last_name || '') + ' ' + (c.client_number || c.id)).trim().toLowerCase();
            var az = document.querySelector('#sb-az .az[data-l="' + letter + '"]');
            if (az && az.classList.contains('az-off')) { az.classList.remove('az-off'); az.onclick = function(){ selectRegisterLetter(letter); }; }
          });
          txt('sb-prompt', sbl.querySelectorAll('.client').length + ' Mandate · Buchstaben wählen oder suchen');
        });
        return r;
      };
    });
  }

  // ------------------------------------------------------------ KYC-Formular bleibt gefuellt (E2E3-09)
  var KYC_REQUIRED = [['kyc-form', 'Formular'], ['kyc-date', 'Formular erstellt am'], ['kyc-ref', 'Referenz'], ['kyc-risk', 'Risikokategorie'],
    ['kyc-pep', 'PEP'], ['kyc-review', 'Nächste Aktualisierung'], ['kyc-ident-date', 'Identifizierung der Vertragspartei am']];
  function val(id){ var el = byId(id); return el ? String(el.value || '').trim() : ''; }
  function captureForm(){
    var host = byId('sd-client-compliance'), out = {};
    if (host) Array.prototype.forEach.call(host.querySelectorAll('input[id],select[id],textarea[id]'), function(el){
      out[el.id] = el.type === 'checkbox' || el.type === 'radio' ? {checked: !!el.checked} : {value: el.value};
    });
    return out;
  }
  function restoreForm(saved){
    Object.keys(saved).forEach(function(id){ var el = byId(id); if (el) { if ('checked' in saved[id]) el.checked = saved[id].checked; else el.value = saved[id].value; } });
  }
  function hookKycForm(){
    wrap('createKycConfirmation', function(orig){
      return async function(){
        var missing = KYC_REQUIRED.filter(function(f){ return !val(f[0]); }).map(function(f){ return f[1]; });
        if (!(byId('kyc-ident-ok') || {}).checked) missing.push('Identifizierung ist erfolgt');
        if (missing.length) { if (g('showAppError')) showAppError('Bitte ausfüllen: ' + missing.join(', ') + '.'); return; }
        // Fehler der Erfassung erkennen (run() zeichnet das Panel in jedem Fall neu und leert es).
        var saved = captureForm(), failed = false, post = API.post;
        API.post = async function(){ try { return await post.apply(this, arguments); } catch(e){ failed = true; throw e; } };
        try { await orig.apply(this, arguments); } finally { API.post = post; }
        if (failed) restoreForm(saved);
      };
    });
  }

  // ------------------------------------------------------------ Servermeldung statt Code (E2E3-08)
  function hookServerMessage(){
    wrap('pensionTransferGuardMessage', function(orig){
      return function(e){
        var out = orig.apply(this, arguments), d = null;
        try { d = e && e.body ? JSON.parse(e.body).detail : null; } catch(_){}
        // Nur der generische Rueckfall ("Fehler: <Text> [CODE]") wird ersetzt; bekannte Hinweise bleiben.
        return /^Fehler: /.test(out) && d && typeof d === 'object' && !Array.isArray(d) && typeof d.message === 'string' && d.message ? 'Fehler: ' + d.message : out;
      };
    });
  }

  function mountAll(){
    safe(hookCashflowHud);
    safe(hookAmounts);
    safe(hookNoStrategy);
    safe(hookSidebarSearch);
    safe(hookKycForm);
    safe(hookServerMessage);
  }
  if (typeof document !== 'undefined' && document.addEventListener) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mountAll);
    else mountAll();
  }

  window.aresTerm = aresTerm;
  window.aresRefreshMandateAmounts = refreshMandateAmounts;
  window.aresSyncAmountViews = syncAmountViews;
})();
