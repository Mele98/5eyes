/* Ares -- Kernkette Runde 4, Classic-Berateroberflaeche (KN4-U, Dok. 119 / H-172-Pruefung).
 * Teil des Monolith-Bundles (eigenes Budget, direkt nach kn3-ui.js). Haengt sich selbst
 * ein und nutzt die globalen Helfer erst beim Aufruf. Zahlen, Baender und Frische bleiben
 * Serverwahrheit; hier wird nur zurueckgesetzt, gerundet (eine Quelle) und angezeigt.
 *
 * E2E4-01  "+ Mandat" bei offenem Kunden: EIN Reset (aresResetMandateView) fuer
 *          Kundenwechsel und neues Mandat setzt auch Tortenmitte/TOTAL, Torte und
 *          IST-Quoten des Vorkunden zurueck.
 * E2E4-06  Eine Rundungsquelle je Zahl: Review-Prozente wie AA/PDF (apportioniert,
 *          AresRounding.bucketPctMap); Portfolio-Zeilen auf den AA-Klassenbetrag
 *          apportioniert (Zeilen = Klassenbetrag = Total).
 * E2E4-08  Cashflow-Seite: bei belegten Kursen kein "Umrechnung offen".
 * E2E4-09  Portfolio bei veralteter Strategie: Ursache, gesperrt, kein "CHF 0" und kein
 *          "konnte nicht generiert werden".
 * E2E4-14  Leere Soll-Prognose ohne Achsenbeschriftung ("1k 1k ... 0k").
 * N-917R3-05  Review-Karte und Kopfzeile: fehlendes Ist = "nicht bewertbar", nie im Band.
 * DEMO-B1  Portfolio: Sub-Anlageklassen/Produktnamen aus den Daten ueber aresTerm (Umlaute).
 * DEMO-B4  Preisstatus (Admin-Route) nur fuer die Rolle admin abfragen (kein 403 fuer Berater).
 * Umgezogen aus ares.html (Budget): normalizeCashflowProjectionLabels. */

function normalizeCashflowProjectionLabels(){
  var el=document.getElementById('cf-projection');
  if(!el)return;
  var walker=document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null);
  var node;
  while((node=walker.nextNode())){
    node.nodeValue=String(node.nodeValue||'')
      .replace(/KapitalzuflÃ¼sse/g,'Kapitalzuflüsse').replace(/ZuflÃ¼sse/g,'Zuflüsse').replace(/VermÃ¶gen/g,'Vermögen')
      .replace(/NÃ¤chstes/g,'Nächstes').replace(/kÃ¼nftigen/g,'künftigen').replace(/Ã¼bernimmt/g,'übernimmt')
      .replace(/unverÃ¤ndert/g,'unverändert').replace(/Â·/g,'·').replace(/â€”/g,'-').replace(/â†’/g,'->').replace(/âˆ’/g,'-');
  }
}
// E2E4-06: Prozent einer Anlageklasse aus der Review-Zeilenliste, apportioniert ueber alle
// Klassen (dieselbe Regel wie AA-Legende, SOLL-Quoten und PDF). field: 'ist' | 'soll'.
function aresReviewPct(rows,key,field){
  var list=(rows||[]).map(function(r){return {asset_class:r.assetKey||r.assetClass,target_weight_bps:field==='ist'?r.currentWeightBps:r.targetWeightBps};});
  var m=AresRounding.bucketPctMap(list,{typography:'screen'}),k=AresRounding.assetClassKey(key);
  return m[k]||m[String(key)]||formatBpsPercent(0);
}
// E2E4-06: Zielbetraege der Portfolio-Zeilen je Anlageklasse auf den Klassenbetrag der AA
// (presentationAmounts, ganze Franken) apportionieren (groesster Rest). Gibt eine Kopie zurueck.
function aresPortfolioDisplayPositions(positions,allocation){
  var rows=(positions||[]).map(function(r){return Object.assign({},r);});
  if(!allocation||!Array.isArray(allocation.buckets)||typeof allocationReserveBreakdown!=='function')return rows;
  var rb=allocationReserveBreakdown(allocation),pos=allocation.buckets.filter(function(b){return Number(b.target_weight_bps)>0;});
  var pa=AresRounding.presentationAmounts(rb.advisoryRappen,rb.strategyBaseRappen,pos.map(function(b){return b.target_weight_bps;}),pos.map(function(b){return b.asset_class;}),2);
  var classChf={};
  pos.forEach(function(b,i){classChf[assetDisplayName(b.asset_class)]=Number(pa.buckets[i]||0);});
  var groups={};
  rows.forEach(function(r){
    if(r.current_market_value_rappen!=null||r.target_amount_rappen==null)return;
    var g=assetDisplayName(r.asset_class||'Portfolio');(groups[g]=groups[g]||[]).push(r);
  });
  Object.keys(groups).forEach(function(g){
    var list=groups[g],raw=list.reduce(function(a,r){return a+Number(r.target_amount_rappen||0);},0),total=classChf[g];
    if(!(total>0)||!(raw>0))return;
    var parts=list.map(function(r){var exact=Number(r.target_amount_rappen||0)/raw*total;return {r:r,chf:Math.floor(exact),frac:exact-Math.floor(exact)};});
    var rest=total-parts.reduce(function(a,p){return a+p.chf;},0);
    parts.slice().sort(function(a,b){return b.frac-a.frac;}).forEach(function(p){if(rest>0){p.chf+=1;rest-=1;}});
    parts.forEach(function(p){p.r.target_amount_rappen=p.chf*100;});
  });
  return rows;
}

(function(){
  'use strict';
  function byId(id){ return document.getElementById(id); }
  function g(name){ return typeof window[name] === 'function' ? window[name] : null; }
  function safe(f){ try { return f(); } catch(e){ try { console.warn('kn4-ui', e); } catch(_){} return null; } }
  function wrap(name, make){
    var o = window[name];
    if (typeof o !== 'function' || o.__kn4Hooked) return false;
    var w = make(o);
    w.__kn4Hooked = true;
    window[name] = w;
    return true;
  }
  function state(){ return typeof strategyState !== 'undefined' && strategyState ? strategyState : null; }
  function curAlloc(){ var s = state(); return s ? s.allocation || null : null; }
  function staleCause(){ return g('aresStaleCause') ? aresStaleCause() : ''; }
  function esc(v){ return g('escapeHtml') ? escapeHtml(String(v)) : String(v); }

  // ------------------------------------------------------------ E2E4-01 ein Reset fuer Wechsel und neues Mandat
  function resetAmounts(){
    try { if (typeof TOTAL !== 'undefined') { TOTAL = 0; TOTAL_CCY = null; } } catch(_){}
    try { alloc = []; } catch(_){} // IST-Quoten der Torte (globales let alloc des Monolithen)
    if (g('syncAllocationDonutFromStrategyState')) safe(function(){ syncAllocationDonutFromStrategyState(); });
    var dcv = document.querySelector ? document.querySelector('.dcv') : null;
    if (dcv) dcv.innerHTML = '—';
    var ctx = byId('cf-risk-context-summary'); // kopierte KPI-Texte des Vorkunden ("Reinvermoegen: CHF …")
    if (ctx) ctx.innerHTML = '';
  }
  function hookReset(){
    wrap('aresResetMandateView', function(orig){
      return function(){ var r = orig.apply(this, arguments); safe(resetAmounts); return r; };
    });
    // Neues Mandat: Kontextzeile der Cashflow-Seite aus den (geleerten) KPIs des neuen Kunden.
    wrap('showNewClientScreen', function(orig){
      return function(){ var r = orig.apply(this, arguments); if (g('updateCfRiskContextSummary')) safe(function(){ updateCfRiskContextSummary(); }); return r; };
    });
  }

  // ------------------------------------------------------------ N-917R3-05 fehlendes Ist = nicht bewertbar
  function hookNotEvaluable(){
    wrap('reviewStrategyComparisonRows', function(orig){
      return function(allocation){
        var rows = orig.apply(this, arguments);
        var buckets = allocation && Array.isArray(allocation.buckets) ? allocation.buckets : [];
        rows.forEach(function(row){
          var b = buckets.filter(function(x){ return String(x.asset_class || '').toLowerCase() === row.assetKey; })[0];
          if (b && (b.current_weight_bps == null || b.current_weight_bps === '')) row.currentWeightBps = null;
        });
        return rows;
      };
    });
    wrap('reviewBandStateMeta', function(orig){
      return function(bucket){
        if (bucket && (bucket.current_weight_bps == null || bucket.current_weight_bps === ''))
          return {label: 'Nicht bewertbar', tagClass: 'tn', tone: 'var(--n5)', action: 'Ist-Bestand fehlt – Bandprüfung nicht möglich', notEvaluable: true};
        return orig.apply(this, arguments);
      };
    });
    wrap('_rvHeroCommonChips', function(orig){
      return function(allocation, rows, violated, tight){
        var unknown = (rows || []).filter(function(r){ return r.meta && r.meta.notEvaluable; }).length;
        var chips = orig.apply(this, arguments);
        if (!unknown) return chips;
        return chips.map(function(c){
          var m = /^(\d+)\/(\d+) Anlageklassen im Band$/.exec(c);
          return m ? (Number(m[1]) - unknown) + '/' + m[2] + ' Anlageklassen im Band · ' + unknown + ' nicht bewertbar' : c;
        });
      };
    });
  }

  function termPositions(list){
    if (!Array.isArray(list) || !g('aresTerm')) return list;
    return list.map(function(r){
      var o = Object.assign({}, r);
      ['sub_asset_class', 'product_name'].forEach(function(k){ if (o[k] != null) o[k] = aresTerm(o[k]); });
      return o;
    });
  }
  // DEMO-B4: Preisstatus ist eine Admin-Route; fuer Berater kein Aufruf (sonst 403 bei jedem Start).
  function hookPriceStatus(){
    wrap('refreshPricesFromBackend', function(orig){
      return function(){
        var u = typeof currentUser !== 'undefined' ? currentUser : null;
        return u && u.role === 'admin' ? orig.apply(this, arguments) : Promise.resolve();
      };
    });
  }

  // ------------------------------------------------------------ E2E4-06 Portfolio-Zeilen = AA-Klassenbetrag
  function hookPortfolioRounding(){
    wrap('renderPortfolioSections', function(orig){
      return function(positions){
        var a = curAlloc(), c = staleCause(), raw = positions;
        positions = termPositions(positions); // DEMO-B1: Fachbegriffe/Umlaute fuer Namen aus den Daten
        if (!a || !Array.isArray(positions) || !positions.length) {
          if (Array.isArray(raw) && raw.length) { var r1 = orig.call(this, positions); try { currentPortfolioPositions = raw.slice(); } catch(_){} return r1; }
          var r0 = orig.apply(this, arguments);
          if (c && !a) safe(function(){ stalePortfolio(c); }); // E2E4-09
          return r0;
        }
        var r = orig.call(this, aresPortfolioDisplayPositions(positions, a));
        try { currentPortfolioPositions = raw.slice(); } catch(_){} // Rohdaten bleiben fuer Finalisieren/Handelsliste
        return r;
      };
    });
  }

  // ------------------------------------------------------------ E2E4-09 Portfolio bei veralteter Strategie
  function stalePortfolio(cause){
    var sub = 'Strategie veraltet: ' + cause + ' – Portfolio gesperrt bis zur Neuberechnung';
    var wrapEl = byId('po-portfolio-sections');
    if (wrapEl) wrapEl.innerHTML = '<div class="ps"><div class="prow"><div class="prow-main" style="cursor:default"><div><div class="pname">Strategie veraltet</div>'
      + '<div class="pdet">' + esc(cause) + '. Bitte die Anlagestrategie neu berechnen, danach das Portfolio generieren.</div></div>'
      + '<div class="pclass"><span class="tag ta">Gesperrt</span></div><div class="pval">—</div><div class="pval">—</div></div></div></div>';
    var q = byId('po-price-quality-sub'); if (q) q.textContent = sub;
    var st = byId('po-status'); if (st) { st.textContent = sub; st.style.display = ''; }
    var fin = byId('btn-po-finalize'); if (fin) { fin.disabled = true; fin.setAttribute('aria-disabled', 'true'); fin.title = sub; }
    if (g('aresSyncAmountViews')) safe(function(){ aresSyncAmountViews(); });
  }
  function hookStalePortfolio(){
    wrap('refreshPortfolioFromStoredState', function(orig){
      return async function(){
        var c = staleCause();
        if (c && !curAlloc()) { stalePortfolio(c); return false; }
        return orig.apply(this, arguments);
      };
    });
    wrap('go', function(orig){
      return async function(p){
        var r = await orig.apply(this, arguments), c = staleCause();
        if (p === 'po' && c && !curAlloc()) safe(function(){ stalePortfolio(c); });
        return r;
      };
    });
  }

  // ------------------------------------------------------------ E2E4-08 Cashflow-Seite bei belegten Kursen
  function hookIstReason(){
    wrap('istProjectionBasisUnavailableReason', function(orig){
      return function(){
        var t = orig.apply(this, arguments);
        if (!/Umrechnung offen/.test(String(t || '')) || !/mehreren Währungen/.test(String(t))) return t;
        var items = g('activeClientWealthPositions') ? activeClientWealthPositions() : [];
        var mix = g('wealthMixedTotals') ? wealthMixedTotals(items) : null;
        if (!mix || mix.blocked) return t; // Kurse fehlen wirklich: Text bleibt
        return String(t).replace(/Umrechnung offen – die Anlagestrategie rechnet mit belegten Kursen/,
          'der Ist-Pfad wird hier nicht umgerechnet; die Kurse sind belegt, die Anlagestrategie rechnet damit');
      };
    });
  }

  // ------------------------------------------------------------ E2E4-14 leere Soll-Prognose ohne Achse
  function setAxis(show){
    if (typeof charts === 'undefined' || !charts || !charts.opt || !charts.opt.options || !charts.opt.options.scales) return;
    var y = charts.opt.options.scales.y;
    if (y && y.display !== show) { y.display = show; try { charts.opt.update('none'); } catch(_){} }
  }
  function hookAxis(){
    wrap('syncAllocationPendingViews', function(orig){
      return function(){ var r = orig.apply(this, arguments); if (!curAlloc()) safe(function(){ setAxis(false); }); return r; };
    });
    ['updateProjectionChartsFromSimulation', 'upgradeFanChartWithMonteCarlo'].forEach(function(n){
      wrap(n, function(orig){ return function(){ safe(function(){ setAxis(true); }); return orig.apply(this, arguments); }; });
    });
  }

  function mountAll(){
    safe(hookReset);
    safe(hookNotEvaluable);
    safe(hookPortfolioRounding);
    safe(hookStalePortfolio);
    safe(hookIstReason);
    safe(hookAxis);
    safe(hookPriceStatus);
  }
  if (typeof document !== 'undefined' && document.addEventListener) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mountAll);
    else mountAll();
  }
})();
