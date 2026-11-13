/**
 * Produkt-Stammdaten und Retrozessions-Offenlegung (Audit 2026-11, Paket P1;
 * Entscheid PO-6, Luecke L1 -- Art. 26 FIDLEG).
 *
 * Ausgelagert aus ares.html (Monolith-Budget, Toleranz 0). ares.html ruft
 * diese Funktionen nur ueber `typeof ...==='function'`-Hooks auf:
 *   - Fondsuniversum: Stammdatenfelder im Formular (#pf-master-data),
 *     Kennzeichen in der Suchtabelle, Export-Button.
 *   - Kostenausweis: Block #cd-retro (Retrozession je empfohlenem Produkt).
 * Grundsatz: leer = nicht erfasst; eine unbekannte Retrozession gilt nie als
 * "keine Retrozession" und wird beim Bearbeiten nie zu einer erfundenen 0.
 */
(function(){
  var L = '<label style="font-size:9px;color:var(--n4);display:block;margin-bottom:2px">';
  var FLAG = '<option value="">nicht erfasst</option><option value="true">ja</option><option value="false">nein</option>';
  var FIELDS_HTML = ''
    + '<div style="grid-column:1/-1;font-size:10px;font-weight:600;color:var(--n6);margin-top:4px">Produkt-Stammdaten (FIDLEG) – leer lassen = nicht erfasst</div>'
    + '<div>' + L + 'Domizil (ISO-Land, z.B. IE)</label><input class="fi" id="pf-domicile" maxlength="2" style="font-size:11px"></div>'
    + '<div>' + L + 'Valor (optional)</label><input class="fi" id="pf-valor" style="font-size:11px"></div>'
    + '<div>' + L + 'Waehrungsgesichert</label><select class="fsel" id="pf-is-hedged" style="font-size:11px">' + FLAG + '</select></div>'
    + '<div>' + L + 'Absicherungswaehrung (nur bei ja)</label><input class="fi" id="pf-hedge-currency" maxlength="3" style="font-size:11px"></div>'
    + '<div>' + L + 'TER-Quelle</label><input class="fi" id="pf-ter-source" placeholder="z.B. Basisinformationsblatt" style="font-size:11px"></div>'
    + '<div>' + L + 'TER-Stichtag</label><input class="fi" type="date" id="pf-ter-as-of" style="font-size:11px"></div>'
    + '<div>' + L + 'Retrozession (Bps p.a.; 0 = keine; leer = unbekannt)</label><input class="fi" type="number" min="0" max="1000" step="1" id="pf-retro" style="font-size:11px"></div>'
    + '<div>' + L + 'Retrozession-Quelle (Pflicht bei Satz)</label><input class="fi" id="pf-retro-source" style="font-size:11px"></div>'
    + '<div>' + L + 'Hausprodukt</label><select class="fsel" id="pf-house-product" style="font-size:11px">' + FLAG + '</select></div>'
    + '<div>' + L + 'Ausschuettungsart</label><select class="fsel" id="pf-distribution" style="font-size:11px"><option value="">nicht erfasst</option><option value="accumulating">thesaurierend</option><option value="distributing">ausschuettend</option></select></div>'
    + '<div>' + L + 'Mindestanlage (in Fondswaehrung, optional)</label><input class="fi" type="number" min="0" step="any" id="pf-min-investment" style="font-size:11px"></div>'
    // Owner-Anforderung P1: eigene Fonds (kotiert/nicht kotiert), Bewertung, Liquiditaetsrhythmus.
    + '<div>' + L + 'Kotierung</label><select class="fsel" id="pf-listing-status" style="font-size:11px"><option value="">nicht erfasst</option><option value="listed">kotiert (ISIN Pflicht)</option><option value="unlisted">nicht kotiert (ohne ISIN: interne ID Pflicht)</option></select></div>'
    + '<div>' + L + 'Interne Produkt-ID (eindeutig je Verwaltung)</label><input class="fi" id="pf-internal-id" maxlength="64" style="font-size:11px"></div>'
    + '<div>' + L + 'Bewertungsquelle</label><select class="fsel" id="pf-price-source" style="font-size:11px"><option value="">nicht erfasst</option><option value="market">Boersenkurs</option><option value="manual_nav">NAV manuell</option><option value="provider">NAV Anbieter</option></select></div>'
    + '<div>' + L + 'NAV-Rhythmus</label><select class="fsel" id="pf-nav-frequency" style="font-size:11px"><option value="">nicht erfasst</option><option value="daily">taeglich</option><option value="weekly">woechentlich</option><option value="monthly">monatlich</option><option value="quarterly">quartalsweise</option></select></div>'
    + '<div>' + L + 'NAV-Stichtag</label><input class="fi" type="date" id="pf-nav-as-of" style="font-size:11px"></div>'
    + '<div>' + L + 'Ruecknahmefrist (Tage)</label><input class="fi" type="number" min="0" step="1" id="pf-redemption-days" style="font-size:11px"></div>'
    + '<div>' + L + 'Kuendigungsfrist (Tage)</label><input class="fi" type="number" min="0" step="1" id="pf-notice-days" style="font-size:11px"></div>'
    + '<div>' + L + 'Gating moeglich</label><select class="fsel" id="pf-has-gating" style="font-size:11px">' + FLAG + '</select></div>'
    + '<div style="grid-column:1/-1">' + L + 'Gating-Bedingungen (optional)</label><input class="fi" id="pf-gating-terms" style="font-size:11px"></div>';

  function ensureFundMasterDataFields(){
    var host = document.getElementById('pf-master-data');
    if (host && !host.getAttribute('data-ready')) {
      host.innerHTML = FIELDS_HTML;
      host.setAttribute('data-ready', '1');
    }
  }
  window.PRODUCT_MASTER_DATA_FIELDS_HTML = FIELDS_HTML;
  window.ensureFundMasterDataFields = ensureFundMasterDataFields;
  if (typeof document !== 'undefined' && document.addEventListener) {
    document.addEventListener('DOMContentLoaded', ensureFundMasterDataFields);
  }
})();

// AUDIT-2026-11 P1 (PO-6, L1): Produkt-Stammdaten im Fondsuniversum.
// Kennzeichnung statt Zwang fuer den Altbestand; eine unbekannte
// Retrozession gilt nie als "keine Retrozession".
function adminFundMasterDataBadges(p){
  var out = '';
  if (p.isin_status === 'missing') {
    out += ' <span class="tag ta" title="Keine ISIN erfasst. Ohne ISIN ist kein Basisinformationsblatt zuordenbar.">ISIN fehlt</span>';
  } else if (p.isin_status === 'invalid') {
    out += ' <span class="tag ta" title="Die erfasste ISIN hat keine gueltige Pruefziffer (ISO 6166).">ISIN ungueltig</span>';
  }
  if (p.retrocession_status === 'unknown') {
    out += ' <span class="tag ta" title="Kein Retrozessionssatz erfasst. Das Produkt gilt NICHT als retrozessionsfrei; im Kostenausweis erscheint eine Pflichtwarnung.">Retrozession unbekannt</span>';
  } else if (p.retrocession_status === 'present') {
    out += ' <span class="tag tn" title="Quelle: ' + escapeHtml(p.retrocession_source || 'nicht angegeben') + '. Wird im Kostenausweis offengelegt.">Retro ' + escapeHtml(String(p.retrocession_bps)) + ' Bps</span>';
  }
  var gaps = Array.isArray(p.master_data_gaps) ? p.master_data_gaps.filter(function(g){ return g !== 'isin' && g !== 'retrocession_bps'; }) : [];
  if (gaps.length) {
    out += ' <span class="tag tn" title="Fehlende Stammdaten: ' + escapeHtml(gaps.join(', ')) + '">Stammdaten unvollstaendig</span>';
  }
  return out;
}
// N-861-4: Nachkommastellen je Waehrung (ISO 4217 Minor Units) statt fester
// /100. Unbekannte Codes: 2 (Regelfall).
var CURRENCY_MINOR_DIGITS = {
  BIF:0, CLP:0, DJF:0, GNF:0, ISK:0, JPY:0, KMF:0, KRW:0, PYG:0, RWF:0, UGX:0, UYI:0,
  VND:0, VUV:0, XAF:0, XOF:0, XPF:0,
  BHD:3, IQD:3, JOD:3, KWD:3, LYD:3, OMR:3, TND:3,
  CLF:4, UYW:4
};
function currencyMinorDigits(code){
  var c = String(code || '').trim().toUpperCase();
  return Object.prototype.hasOwnProperty.call(CURRENCY_MINOR_DIGITS, c) ? CURRENCY_MINOR_DIGITS[c] : 2;
}
function adminFillFundMasterData(p){
  if (typeof ensureFundMasterDataFields === 'function') ensureFundMasterDataFields();
  function setVal(id, value){ var el = document.getElementById(id); if (el) el.value = (value === null || value === undefined) ? '' : String(value); }
  function setFlag(id, value){ setVal(id, value === true ? 'true' : (value === false ? 'false' : '')); }
  setVal('pf-domicile', p.domicile);
  setVal('pf-valor', p.valor);
  setFlag('pf-is-hedged', p.is_hedged);
  setVal('pf-hedge-currency', p.hedge_currency);
  setVal('pf-ter-source', p.ter_source);
  setVal('pf-ter-as-of', p.ter_as_of);
  setVal('pf-retro', p.retrocession_bps);
  setVal('pf-retro-source', p.retrocession_source);
  setFlag('pf-house-product', p.is_house_product);
  setVal('pf-distribution', p.distribution_policy);
  setVal('pf-min-investment', p.minimum_investment_minor_units != null ? (Number(p.minimum_investment_minor_units) / Math.pow(10, currencyMinorDigits(p.currency))) : '');
  setVal('pf-listing-status', p.listing_status);
  setVal('pf-internal-id', p.internal_product_id);
  setVal('pf-price-source', p.price_source);
  setVal('pf-nav-frequency', p.nav_frequency);
  setVal('pf-nav-as-of', p.nav_as_of);
  setVal('pf-redemption-days', p.redemption_period_days);
  setVal('pf-notice-days', p.notice_period_days);
  setFlag('pf-has-gating', p.has_gating);
  setVal('pf-gating-terms', p.gating_terms);
}
function adminCollectFundMasterData(payload, editing){
  function val(id){ var el = document.getElementById(id); return el ? String(el.value || '').trim() : ''; }
  function put(field, value){ if (value !== '' && value !== null) payload[field] = value; else if (editing) payload[field] = null; }
  function flag(id){ var v = val(id); return v === 'true' ? true : (v === 'false' ? false : null); }
  put('domicile', val('pf-domicile').toUpperCase());
  put('valor', val('pf-valor'));
  put('is_hedged', flag('pf-is-hedged'));
  put('hedge_currency', val('pf-hedge-currency').toUpperCase());
  put('ter_source', val('pf-ter-source'));
  put('ter_as_of', val('pf-ter-as-of'));
  put('retrocession_source', val('pf-retro-source'));
  put('is_house_product', flag('pf-house-product'));
  put('distribution_policy', val('pf-distribution'));
  put('listing_status', val('pf-listing-status'));
  put('internal_product_id', val('pf-internal-id'));
  put('price_source', val('pf-price-source'));
  put('nav_frequency', val('pf-nav-frequency'));
  put('nav_as_of', val('pf-nav-as-of'));
  put('has_gating', flag('pf-has-gating'));
  put('gating_terms', val('pf-gating-terms'));
  var dayFields = [['pf-redemption-days', 'redemption_period_days', 'Ruecknahmefrist'], ['pf-notice-days', 'notice_period_days', 'Kuendigungsfrist']];
  for (var i = 0; i < dayFields.length; i++) {
    var raw = val(dayFields[i][0]);
    if (raw === '') { if (editing) payload[dayFields[i][1]] = null; continue; }
    var days = Number(raw);
    if (!Number.isInteger(days) || days < 0) return dayFields[i][2] + ' muss eine ganze Zahl von Tagen sein.';
    payload[dayFields[i][1]] = days;
  }
  if (val('pf-listing-status') === 'unlisted' && !val('pf-isin') && !val('pf-internal-id')) return 'Nicht kotierter Fonds ohne ISIN: bitte eine interne Produkt-ID angeben.';
  if (val('pf-listing-status') === 'listed' && !val('pf-isin')) return 'Kotierter Fonds: bitte die ISIN angeben.';
  var retroRaw = val('pf-retro');
  if (retroRaw !== '') {
    var retro = Number(retroRaw);
    if (!Number.isInteger(retro) || retro < 0 || retro > 1000) return 'Retrozession muss eine ganze Zahl 0–1000 (Bps) sein.';
    if (!val('pf-retro-source')) return 'Bitte die Quelle des Retrozessionssatzes angeben.';
    payload.retrocession_bps = retro;
  } else if (editing) {
    payload.retrocession_bps = null;
  }
  var minRaw = val('pf-min-investment');
  if (minRaw !== '') {
    var minVal = Number(minRaw);
    if (!isFinite(minVal) || minVal < 0) return 'Mindestanlage muss eine nicht-negative Zahl sein.';
    var digits = currencyMinorDigits(val('pf-currency'));
    var minor = minVal * Math.pow(10, digits);
    if (Math.abs(minor - Math.round(minor)) > 1e-6) return 'Mindestanlage: hoechstens ' + digits + ' Nachkommastellen fuer ' + (val('pf-currency').toUpperCase() || 'CHF') + '.';
    payload.minimum_investment_minor_units = Math.round(minor);
  } else if (editing) {
    payload.minimum_investment_minor_units = null;
  }
  return null;
}
async function adminExportFundsCsv(){
  try {
    var token = await API.getToken();
    var base = await API.baseUrl();
    var res = await fetch(base + '/products/export/csv', {
      headers: token ? {'Authorization': 'Bearer ' + token} : {},
    });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    var blob = await res.blob();
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url; a.download = 'fondsuniversum-export.csv'; document.body.appendChild(a); a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  } catch(e) {
    if (window.showAppError) showAppError('Export konnte nicht heruntergeladen werden.');
    else uiAlert({level:'error',message:'Export konnte nicht heruntergeladen werden.'});
  }
}

// AUDIT-2026-11 P1 (L1, Art. 26 FIDLEG): Retrozession je empfohlenem
// Produkt -- eigener Block neben der Kostentabelle (Daten:
// payload.product_retrocessions des Kostenausweises).
// N-861-12: Retro-Betraege immer auf Rappen genau (zwei Nachkommastellen),
// damit Schaetzung und Mandatsbetrag bei Teil-Deckung nie gleich aussehen.
function _retroAmount(rappen, currency){
  var unit = String(currency || '').toUpperCase().trim();
  if (!unit) return '—';  // G7 N4: Waehrung unbekannt -> keine geratene Einheit
  // G7 N-894-13: gemeinsamer Formatter (Half-up, Rappen-genau, hoechstens ISO-Stellen).
  return AresRounding.formatStoredAmount(Number(rappen || 0), unit, 2, {typography: 'plain'});
}
function renderCostRetrocessions(data){
  var box=document.getElementById('cd-retro');
  if(!box) return;
  var block=data&&data.product_retrocessions;
  var lines=(block&&Array.isArray(block.lines))?block.lines:[];
  if(!lines.length||data.evidence_status==='blocked'){ box.style.display='none'; box.innerHTML=''; return; }
  var currency=String(data.currency||'').toUpperCase().trim();
  var head=block.complete
    ? '<div style="font-weight:600;margin-bottom:6px">Retrozessionen je Produkt</div>'
    : '<div style="font-weight:600;margin-bottom:6px;color:var(--neg)">Retrozessionen je Produkt – Pflichtangaben unvollstaendig</div>';
  box.style.display='';
  box.innerHTML=head+'<div style="border:1px solid var(--b1);border-radius:var(--r);overflow:hidden;font-size:11px">'
    +lines.map(function(line){
      var rate=line.status==='unknown'?'unbekannt':(line.status==='none'?'keine':fmtPct(Number(line.rate_bps),2));
      var amount=line.status==='present'?'geschätzt '+_retroAmount(line.estimated_annual_rappen, currency):'—';
      if(line.status==='present'&&line.covered_by_mandate_entry&&line.mandate_disclosed_rappen) amount+=' / aufgeklärt '+_retroAmount(line.mandate_disclosed_rappen, currency);
      if(line.status==='present'&&line.mandate_disclosed_other_rappen) amount+=' / offengelegt (einmalig bzw. ohne Frequenz) '+_retroAmount(line.mandate_disclosed_other_rappen, currency)+', deckt die jährliche Retrozession nicht';
      var flagged=line.status==='unknown'||line.requires_resolution;
      return '<div style="display:grid;grid-template-columns:1.4fr 80px 200px 1.4fr;gap:8px;padding:7px 10px;border-bottom:1px solid var(--b1);'+(flagged?'border-left:3px solid var(--neg);':'')+'">'
        +'<div>'+escapeHtml(String(line.product_name||''))+'</div>'
        +'<div style="text-align:right">'+escapeHtml(rate)+'</div>'
        +'<div style="text-align:right">'+escapeHtml(amount)+'</div>'
        +'<div style="font-size:10px;color:var(--n5)">'+escapeHtml(String(line.treatment_label||''))+'</div>'
        +'</div>';
    }).join('')+'</div>';
}

