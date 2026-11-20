/* Ares -- Kernkette Runde 5, Classic-Berateroberflaeche (KN5, H-176-Pruefung).
 * Teil des Monolith-Bundles (eigenes Budget, direkt nach kn4-ui.js). Haengt sich selbst
 * ein (ueber die KN4-Wrapper) und nutzt die globalen Helfer erst beim Aufruf. Zahlen
 * bleiben Serverwahrheit (Bucket-Felder aus portfolio_engine_payload._bucket_rows).
 *
 * N-917R4-02  Review: Ist-% und Ist-CHF auf derselben Basis (Strategieanteil, Server-
 *             feld comparison_basis 'strategy'); Bestand und «davon Reserve ausserhalb
 *             der Strategie» getrennt (Karte + Kopfzeile); eine negative Liquiditaet
 *             (Reserve > Liquiditaet) wird als Reservelücke erklaert, nie als 0.0 %.
 * N-917R4-05  Portfolio: Hinweis, wenn eine Klasse nicht auf den AA-Betrag apportioniert
 *             wird (Toleranzschranke in kn4-ui.js aresPortfolioDisplayPositions).
 * Umgezogen aus ares.html (Budget): allocationReserveBreakdown. */

function allocationReserveBreakdown(result){var advisory=Math.max(0,Number(result&&result.advisory_wealth_rappen||0));var baseRaw=result&&result.strategy_base_rappen!=null?Number(result.strategy_base_rappen):(result&&result.investable_advisory_wealth_rappen!=null?Number(result.investable_advisory_wealth_rappen):advisory);var base=(isFinite(baseRaw)&&baseRaw>0&&baseRaw<=advisory)?baseRaw:advisory;return {advisoryRappen:advisory,strategyBaseRappen:base,reserveRappen:Math.max(0,advisory-base)};} // Live-Test 2026-11 H2: SOLL-Quoten gelten fuer die Strategiebasis (Beratungsvermoegen - externe Reserve, Engine strategy_base_rappen); Reserve separat ausweisen
// N-917R4-02: Review-Zeile auf der Basis des Servers: Ist-CHF = Strategieanteil wie Ist-%.
function aresReviewReserveBasis(row,b){
  if(!row||!b||b.comparison_basis!=='strategy'||b.current_strategy_amount_rappen==null)return row;
  row.holdingRappen=Number(b.current_amount_rappen||0);row.currentRappen=Number(b.current_strategy_amount_rappen);
  row.reserveRappen=Number(b.reserve_rappen||0);row.reserveFundedRappen=Number(b.reserve_funded_rappen||0);row.reserveGapRappen=Number(b.reserve_gap_rappen||0);
  return row;
}
function aresReviewReserveBucket(a){return ((a&&a.buckets)||[]).filter(function(x){return Number(x&&x.reserve_rappen||0)>0&&x.current_strategy_amount_rappen!=null;})[0]||null;}
function aresReviewReserveNote(a){
  var b=aresReviewReserveBucket(a);if(!b)return '';
  var f=function(r){return formatRappen(r);},st=Number(b.current_strategy_amount_rappen),gap=Number(b.reserve_gap_rappen||0);
  var t='Ist-Werte in % und als Betrag = Strategieanteil (ohne Liquiditätsreserve ausserhalb der Strategie). Liquidität: Bestand '+f(b.current_amount_rappen)+', davon Reserve ausserhalb der Strategie '+f(b.reserve_funded_rappen)+'.';
  return t+(gap>0?' Die Reserve von '+f(b.reserve_rappen)+' ist um '+f(gap)+' nicht gedeckt – deshalb ist der Strategieanteil der Liquidität negativ ('+formatBpsPercent(b.current_weight_bps)+' = '+f(st)+').'
    :' Strategieanteil der Liquidität '+formatBpsPercent(b.current_weight_bps)+' = '+f(st)+'.');
}

(function(){
  'use strict';
  function byId(id){ return document.getElementById(id); }
  function g(name){ return typeof window[name] === 'function' ? window[name] : null; }
  function safe(f){ try { return f(); } catch(e){ try { console.warn('kn5-ui', e); } catch(_){} return null; } }
  function wrap(name, make){
    var o = window[name];
    if (typeof o !== 'function' || o.__kn5Hooked) return false;
    var w = make(o);
    w.__kn5Hooked = true;
    window[name] = w;
    return true;
  }
  function curAlloc(){ return typeof strategyState !== 'undefined' && strategyState ? strategyState.allocation || null : null; }
  function esc(v){ return g('escapeHtml') ? escapeHtml(String(v)) : String(v); }

  // ------------------------------------------------------------ N-917R4-02 Review-Basis + Reserve
  function hookReviewReserve(){
    wrap('reviewStrategyComparisonRows', function(orig){
      return function(allocation){
        var rows = orig.apply(this, arguments);
        var live = g('reviewLiveDriftsBackedByHoldings') && g('liveRebalancingPayload') && reviewLiveDriftsBackedByHoldings(liveRebalancingPayload(allocation));
        if (live) return rows; // Live-Zeilen (erfasste Bestaende) haben ihre eigene Basis
        var buckets = allocation && Array.isArray(allocation.buckets) ? allocation.buckets : [];
        rows.forEach(function(row){
          aresReviewReserveBasis(row, buckets.filter(function(x){ return String(x.asset_class || '').toLowerCase() === row.assetKey; })[0]);
        });
        return rows;
      };
    });
    wrap('aresReviewPct', function(orig){
      return function(rows, key, field){
        var k = AresRounding.assetClassKey(key);
        var own = (rows || []).filter(function(r){ return AresRounding.assetClassKey(r.assetKey || r.assetClass) === k; })[0];
        if (field === 'ist' && own && Number(own.currentWeightBps) < 0) return formatBpsPercent(own.currentWeightBps); // Reservelücke sichtbar
        return orig.apply(this, arguments);
      };
    });
    wrap('_rvHeroCommonChips', function(orig){
      return function(allocation){
        var chips = orig.apply(this, arguments), rb = aresReviewReserveBucket(allocation);
        return rb ? chips.concat(['Liquiditätsreserve ausserhalb der Strategie ' + formatRappen(rb.reserve_rappen)]) : chips;
      };
    });
    wrap('renderSrImplementationDecision', function(orig){
      return function(){
        var r = orig.apply(this, arguments), steps = byId('sr-implementation-steps'), t = aresReviewReserveNote(curAlloc());
        if (steps && t) steps.innerHTML += '<div data-kn5-reserve-note style="grid-column:1/-1;font-size:10px;color:var(--n6)">' + esc(t) + '</div>';
        return r;
      };
    });
  }

  // ------------------------------------------------------------ N-917R4-05 Hinweis ohne Apportionierung
  function hookApportionNote(){
    wrap('renderPortfolioSections', function(orig){
      return function(positions){
        var r = orig.apply(this, arguments), a = curAlloc(), box = byId('po-portfolio-sections');
        var notes = a && Array.isArray(positions) && g('aresPortfolioDisplayPositions') ? (aresPortfolioDisplayPositions(positions, a).apportionNotes || []) : [];
        if (box && notes.length) box.innerHTML += '<div class="pdet" data-kn5-apportion-note>Rundungsabgleich nicht angewendet (' + esc(notes.join(', '))
          + '): Die Produktbeträge weichen um mehr als die Rundung von der Klassensumme der Asset Allokation ab und werden ohne Abgleich gezeigt.</div>';
        return r;
      };
    });
  }

  function mountAll(){
    safe(hookReviewReserve);
    safe(hookApportionNote);
  }
  if (typeof document !== 'undefined' && document.addEventListener) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mountAll);
    else mountAll();
  }
})();
